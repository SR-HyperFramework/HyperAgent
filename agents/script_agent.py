import asyncio
import hashlib
import os
import re
import shutil
import sys
from typing import Any, Dict

import yaml

from core.claude_code_runner import run_claude_code


class ScriptAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.output_root = "script_output"
        self.repo_root = os.path.normpath(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            return {}
        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
            return {}

    def _tool_config(self, key: str) -> str | None:
        tools = (self.config or {}).get("tools") or {}
        value = tools.get(key)
        return str(value) if value else None

    def _abs_path(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))

    def _to_workspace_rel_posix(self, path: str) -> str:
        repo_root_abs = self._abs_path(self.repo_root)
        path_abs = self._abs_path(path)
        try:
            rel = os.path.relpath(path_abs, start=repo_root_abs)
        except Exception:
            rel = path_abs
        return rel.replace("\\", "/")

    def _ensure_output_dir(self, file_hash: str) -> str:
        output_dir = self._abs_path(os.path.join(self.output_root, file_hash))
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    async def _run_cmd(self, *cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return (
            process.returncode,
            stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout),
            stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr),
        )

    def _resolve_tool(self, configured: str | None, fallbacks: list[str]) -> str | None:
        candidates = [configured] if configured else []
        candidates.extend(fallbacks)

        for candidate in candidates:
            expanded = os.path.expandvars(os.path.expanduser(str(candidate)))
            if os.path.isabs(expanded) and os.path.isfile(expanded):
                return os.path.normpath(expanded)

            which = shutil.which(expanded)
            if which:
                return os.path.normpath(which)

            repo_rel = os.path.normpath(os.path.join(self.repo_root, expanded))
            if os.path.isfile(repo_rel):
                return repo_rel

        return None

    async def _extract_pyinstaller(self, file_path: str, output_dir: str) -> tuple[str, list[str]]:
        extractor = self._resolve_tool(
            self._tool_config("pyinstxtractor"),
            ["pyinstxtractor.py", "pyinstxtractor"],
        )
        if not extractor:
            return file_path, []

        before_dirs = {entry for entry in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, entry))}
        cmd = [sys.executable, extractor, file_path]
        code, _, stderr = await self._run_cmd(*cmd, cwd=output_dir)
        if code != 0:
            print(f"[WARN] pyinstxtractor failed: {stderr.strip()}")
            return file_path, []

        after_dirs = [
            os.path.join(output_dir, entry)
            for entry in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, entry)) and entry not in before_dirs
        ]
        after_dirs.sort(key=lambda p: len(p), reverse=True)
        extract_dir = after_dirs[0] if after_dirs else file_path

        extracted_files: list[str] = []
        if os.path.isdir(extract_dir):
            for root, _, files in os.walk(extract_dir):
                for name in files:
                    extracted_files.append(os.path.join(root, name))

        return extract_dir, extracted_files

    async def _disassemble_with_pycdas(self, target_dir: str) -> list[str]:
        pycdas = self._resolve_tool(self._tool_config("pycdas"), ["pycdas", "pycdas.exe"])
        if not pycdas or not os.path.isdir(target_dir):
            return []

        pyc_files: list[str] = []
        for root, _, files in os.walk(target_dir):
            for name in files:
                if name.lower().endswith((".pyc", ".pyo")):
                    pyc_files.append(os.path.join(root, name))

        created_pyasm: list[str] = []
        for pyc_file in pyc_files:
            pyasm_path = f"{pyc_file}.pyasm"
            code, stdout, stderr = await self._run_cmd(pycdas, pyc_file)
            if code != 0:
                print(f"[WARN] pycdas failed for {pyc_file}: {(stderr or stdout).strip()}")
                continue
            with open(pyasm_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(stdout)
            created_pyasm.append(pyasm_path)

        return created_pyasm

    def _pick_interesting_files(self, base_dir: str, suffixes: tuple[str, ...], limit: int = 20) -> list[str]:
        if not os.path.isdir(base_dir):
            return []

        interesting_names = {"__main__.py", "main.py", "app.py", "run.py", "loader.py", "bootstrap.py"}
        keywords = ("main", "entry", "loader", "bootstrap", "decrypt", "config", "socket", "http", "request", "exec")
        hits: list[str] = []
        others: list[str] = []

        for root, _, files in os.walk(base_dir):
            for name in files:
                low = name.lower()
                if not low.endswith(suffixes):
                    continue
                rel = self._to_workspace_rel_posix(os.path.join(root, name))
                if low in interesting_names or any(keyword in low for keyword in keywords):
                    hits.append(rel)
                else:
                    others.append(rel)

        result = hits[:limit]
        if len(result) < limit:
            result.extend(others[: limit - len(result)])
        return result

    @staticmethod
    def filter_goose_report(raw_log: str) -> str:
        start_marker = "**Start of Analysis**"
        end_marker = "**End of Analysis**"

        start_idx = raw_log.find(start_marker)
        end_idx = raw_log.find(end_marker)

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = raw_log[start_idx : end_idx + len(end_marker)]
        elif start_idx != -1:
            content = raw_log[start_idx:]
        else:
            content = raw_log

        content = re.sub(r"───.*?\n", "", content)
        content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)
        content = re.sub(r"\n\s*\n", "\n\n", content).strip()
        return content

    @staticmethod
    def _get_file_hash(file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    async def run_goose_analysis(self, file_path: str, extract_dir: str) -> str:
        abs_target = self._abs_path(file_path)
        workspace_target = self._to_workspace_rel_posix(file_path)

        pyasm_files = self._pick_interesting_files(extract_dir, (".pyasm",), limit=20)
        extracted_files = self._pick_interesting_files(extract_dir, (".py", ".pyc", ".pyo", ".pyasm"), limit=25)
        workspace_extract_dir = self._to_workspace_rel_posix(extract_dir)

        files_block = "\n".join(f"- {path}" for path in pyasm_files) if pyasm_files else "- (no .pyasm files generated)"
        extracted_block = "\n".join(f"- {path}" for path in extracted_files) if extracted_files else "- (no extracted files detected)"

        instruction = (
            "You are a Senior Python malware analyst. "
            f"Target file path: {abs_target}. "
            f"Workspace-relative target path: {workspace_target}. "
            f"Use the extracted contents under: {workspace_extract_dir}.\n"
            "Start with the generated .pyasm files listed below because they contain pycdas disassembly output.\n"
            f"Primary .pyasm files to inspect first:\n{files_block}\n\n"
            "Other extracted files/directories worth checking:\n"
            f"{extracted_block}\n\n"
            "Tasks:\n"
            "1) Reconstruct the likely entry point and main execution flow from the extraction/disassembly output.\n"
            "2) Call out suspicious strings, imports, dynamic execution, filesystem/network/process behavior, persistence, and obfuscation.\n"
            "3) Cross-check findings between .pyasm output and extracted source/bytecode files.\n"
            "4) NEVER execute the file.\n"
            "If you cannot read the target or extracted files, write exactly: Error: Cannot access target file.\n"
            "Write a report starting with **Start of Analysis** and ending with **End of Analysis**."
        )
        return await run_claude_code(instruction, config=self.config)

    async def analyze(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {"error": "File does not exist"}
        if not os.access(file_path, os.R_OK):
            return {"error": "File is not readable"}

        abs_file_path = self._abs_path(file_path)
        file_hash = self._get_file_hash(abs_file_path)
        output_dir = self._ensure_output_dir(file_hash)
        extract_dir, _ = await self._extract_pyinstaller(abs_file_path, output_dir)
        if os.path.isfile(extract_dir):
            extract_dir = os.path.dirname(abs_file_path)
        pyasm_files = await self._disassemble_with_pycdas(extract_dir)
        if not pyasm_files and os.path.isdir(extract_dir):
            for root, _, files in os.walk(extract_dir):
                for name in files:
                    if name.lower().endswith(".pyasm"):
                        pyasm_files.append(os.path.join(root, name))

        raw_report = await self.run_goose_analysis(abs_file_path, extract_dir)
        return {
            "file_name": os.path.basename(abs_file_path),
            "file_hash": file_hash,
            "extract_dir": extract_dir,
            "pyasm_files": [self._to_workspace_rel_posix(path) for path in pyasm_files],
            "ai_analysis_report": self.filter_goose_report(raw_report),
        }
