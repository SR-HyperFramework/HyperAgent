import asyncio
import os
import hashlib
import shutil
import yaml
import re
from typing import Dict, Any

class ScriptAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        # Khởi tạo công cụ pycdas thay vì pycdc/pylingual
        # pyinstxtractor đã có trong PATH
        self.pyinstxtractor = self._tool_config("pyix") or "pyix.exe"
        self.pycdas_path = self._tool_config("pycdas") or "pycdas.exe" # Cập nhật pycdas

        self.output_root = "python_output"
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

    def _ensure_output_dir(self, output_dir: str, clean: bool = True) -> str:
        output_dir = self._abs_path(output_dir)
        output_root_abs = self._abs_path(self.output_root)
        if os.path.commonpath([output_root_abs, output_dir]) != output_root_abs:
            raise ValueError(f"Refusing to use output_dir outside output_root: {output_dir}")
        if clean and os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    async def _run_cmd(self, cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode, (out or b"").decode("utf-8", errors="replace")

    async def _run_goose(self, instruction: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "goose", "run", "--text", instruction,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        return (stdout or b"").decode("utf-8", errors="ignore")

    def _get_file_hash(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""): sha256.update(chunk)
        return sha256.hexdigest()

    async def _extract_pyinstaller(self, file_path: str, extract_dir: str) -> bool:
        configured = os.path.expandvars(os.path.expanduser(str(self.pyinstxtractor)))
        if os.path.isabs(configured) and os.path.isfile(configured):
            pyinst = os.path.normpath(configured)
        else:
            pyinst = shutil.which(configured) or shutil.which("pyix.exe")

        if not pyinst:
            print("[-] pyinstxtractor not found in PATH. Skipping extraction.")
            return False

        extract_dir = self._ensure_output_dir(extract_dir, clean=True)

        print(f"[*] Extracting PyInstaller bundle: {file_path}")
        cmd_extract = [pyinst, self._abs_path(file_path)]
        code, out = await self._run_cmd(cmd_extract, cwd=extract_dir)
        return code == 0

    # THAY ĐỔI CHÍNH: Sử dụng pycdas để disassemble bytecode
    async def _disassemble_with_pycdas(self, extract_dir: str, limit: int = 15) -> list[str]:
        """Sử dụng pycdas để tạo file disassembly (.pyasm) từ các file .pyc."""
        candidates = [self.pycdas_path, "pycdas.exe", "pycdas"]
        pycdas: str | None = None
        for candidate in candidates:
            expanded = os.path.expandvars(os.path.expanduser(str(candidate)))
            if os.path.isabs(expanded) and os.path.isfile(expanded):
                pycdas = os.path.normpath(expanded)
                break
            which = shutil.which(expanded)
            if which:
                pycdas = os.path.normpath(which)
                break
            repo_rel = os.path.normpath(os.path.join(self.repo_root, expanded))
            if os.path.isfile(repo_rel):
                pycdas = repo_rel
                break

        if not pycdas:
            print("[-] pycdas not found. Skipping disassembly.")
            return []

        extract_abs = self._abs_path(extract_dir)
        pyc_files: list[str] = []
        for root, _, files in os.walk(extract_abs):
            for name in files:
                if name.lower().endswith(".pyc"):
                    pyc_files.append(os.path.join(root, name))

        generated_files = []
        # Ưu tiên các file có tên quan trọng
        priority_keywords = ["pyiboot", "main", "entry", "script"]
        pyc_files.sort(key=lambda x: any(k in x.lower() for k in priority_keywords), reverse=True)

        for pyc in pyc_files[:limit]:
            out_asm = pyc + ".pyasm" # Tạo file .pyasm chứa bytecode
            try:
                # Chạy pycdas và lưu output vào file .pyasm
                proc = await asyncio.create_subprocess_exec(
                    pycdas, pyc,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await proc.communicate()
                if proc.returncode == 0 and out:
                    with open(out_asm, "wb") as f:
                        f.write(out)
                    generated_files.append(self._to_workspace_rel_posix(out_asm))
            except Exception as e:
                print(f"[-] pycdas failed for {pyc}: {e}")
        
        return generated_files

    @staticmethod
    def filter_goose_report(raw_log: str) -> str:
        start_marker = "**Start of Analysis**"
        end_marker = "**End of Analysis**"
        start_idx = raw_log.find(start_marker)
        end_idx = raw_log.find(end_marker)

        if start_idx != -1 and end_idx != -1:
            content = raw_log[start_idx : end_idx + len(end_marker)]
        elif start_idx != -1:
            content = raw_log[start_idx:]
        else:
            content = raw_log

        content = re.sub(r"───.*?\n", "", content)
        content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)
        content = re.sub(r"\n\s*\n", "\n\n", content).strip()
        return content
    
    async def run_goose_analysis(self, file_path: str, extract_dir: str) -> str:
        file_abs = self._abs_path(file_path)
        extract_abs = self._abs_path(extract_dir)

        # 1. Giải nén PyInstaller
        ok = await self._extract_pyinstaller(file_abs, extract_abs)
        if not ok: return "Error: PyInstaller extraction failed."

        # 2. THAY ĐỔI: Chạy pycdas để tạo bytecode disassembly
        asm_files = await self._disassemble_with_pycdas(extract_abs, limit=15)
        
        workspace_target = self._to_workspace_rel_posix(extract_abs)
        files_block = "\n".join(f"- {p}" for p in asm_files) if asm_files else "- (no bytecode disassembly generated)"

        print("[*] Running Goose AI for Python Bytecode Analysis (pycdas)...")

        # Cập nhật Instruction cho Goose để hiểu là đang đọc Bytecode
        instruction = (
            "Role: Python Bytecode Specialist & Malware Researcher.\n"
            f"Target Workspace: {workspace_target}\n"
            f"Files to analyze (Bytecode Disassembly):\n{files_block}\n\n"
            "Tasks:\n"
            "- Analyze the Python Bytecode (opcodes like LOAD_CONST, CALL_FUNCTION, etc.).\n"
            "- Identify the main execution flow and hidden functionality.\n"
            "- Look for dynamic code execution (EXEC_STMT, eval), obfuscated strings, or network IOCs.\n"
            "- Explain the logic of the disassembled bytecode in plain English.\n"
            "Constraints:\n"
            "- NEVER execute code.\n"
            "- Focus on the .pyasm files generated by pycdas.\n\n"
            "Report Structure:\n"
            "1. Start with **Start of Analysis**.\n"
            "2. [Summary] | [Bytecode Logic] | [IOCs] | [Behavior] | [Verdict].\n"
            "3. End with **End of Analysis**."
        )

        raw = await self._run_goose(instruction)
        return self.filter_goose_report(raw)
    
    async def analyze(self, file_path: str) -> Dict[str, Any]:
        file_hash = self._get_file_hash(file_path)
        extract_dir = os.path.join(self.output_root, f"{file_hash}_extracted")
        report = await self.run_goose_analysis(file_path, extract_dir)
        return {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "extracted_path": extract_dir,
            "ai_analysis_report": report
        }