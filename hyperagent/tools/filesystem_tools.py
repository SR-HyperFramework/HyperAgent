"""Filesystem tool wrappers for the agentic loop."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import ToolDefinition, ToolResult
from .path_scope import PathScope, PathScopeError


def _read_file(scope: PathScope, path: str = "", **_kw) -> ToolResult:
    try:
        p = scope.check_read(path)
        if not p.is_file():
            return ToolResult(content=f"Error: {path} is not a file or does not exist", is_error=True)

        stat = p.stat()
        max_bytes = 2 * 1024 * 1024  # 2MB safety limit
        if stat.st_size > max_bytes:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(max_bytes)
            return ToolResult(
                content=f"{text}\n\n--- [TRUNCATED: File size is {stat.st_size} bytes, which exceeds the 2MB safety limit] ---"
            )

        text = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(content=text)
    except (PathScopeError, Exception) as exc:
        return ToolResult(content=f"read_file error: {exc}", is_error=True)


def _write_file(scope: PathScope, path: str = "", content: str = "", **_kw) -> ToolResult:
    try:
        p = scope.check_write(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(content=f"Written {len(content)} bytes to {p}")
    except (PathScopeError, Exception) as exc:
        return ToolResult(content=f"write_file error: {exc}", is_error=True)


def _sha256_file(scope: PathScope, path: str = "", **_kw) -> ToolResult:
    try:
        p = scope.check_read(path)
        digest = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return ToolResult(content=digest.hexdigest())
    except (PathScopeError, Exception) as exc:
        return ToolResult(content=f"sha256 error: {exc}", is_error=True)


def _list_directory(scope: PathScope, path: str = "", **_kw) -> ToolResult:
    try:
        directory = scope.check_read(path)
        entries = []
        for entry in sorted(directory.iterdir()):
            kind = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else 0
            entries.append({"name": entry.name, "type": kind, "size": size})
        return ToolResult(content=json.dumps(entries, indent=2))
    except (PathScopeError, Exception) as exc:
        return ToolResult(content=f"list_directory error: {exc}", is_error=True)


def _file_exists(scope: PathScope, path: str = "", **_kw) -> ToolResult:
    try:
        resolved = scope.check_read(path)
        exists = resolved.exists()
        return ToolResult(content=json.dumps({"exists": exists, "path": str(resolved)}))
    except PathScopeError as exc:
        return ToolResult(content=f"file_exists error: {exc}", is_error=True)


def _mkdir(scope: PathScope, path: str = "", **_kw) -> ToolResult:
    try:
        resolved = scope.check_write(path)
        resolved.mkdir(parents=True, exist_ok=True)
        return ToolResult(content=f"Directory created: {resolved}")
    except (PathScopeError, Exception) as exc:
        return ToolResult(content=f"mkdir error: {exc}", is_error=True)


def create_filesystem_tools(scope: PathScope) -> list[ToolDefinition]:
    """Return all filesystem tool definitions."""
    return [
        ToolDefinition(
            name="read_file",
            description="Read the text content of a file at the given path.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute file path"}},
                "required": ["path"],
            },
            handler=lambda **kwargs: _read_file(scope, **kwargs),
            source="filesystem",
        ),
        ToolDefinition(
            name="write_file",
            description="Write text content to a file, creating parent directories as needed.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "content": {"type": "string", "description": "Text content to write"},
                },
                "required": ["path", "content"],
            },
            handler=lambda **kwargs: _write_file(scope, **kwargs),
            source="filesystem",
        ),
        ToolDefinition(
            name="sha256_file",
            description="Compute the SHA256 hash of a file.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute file path"}},
                "required": ["path"],
            },
            handler=lambda **kwargs: _sha256_file(scope, **kwargs),
            source="filesystem",
        ),
        ToolDefinition(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
                "required": ["path"],
            },
            handler=lambda **kwargs: _list_directory(scope, **kwargs),
            source="filesystem",
        ),
        ToolDefinition(
            name="file_exists",
            description="Check if a file or directory exists at the given path.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute path to check"}},
                "required": ["path"],
            },
            handler=lambda **kwargs: _file_exists(scope, **kwargs),
            source="filesystem",
        ),
        ToolDefinition(
            name="mkdir",
            description="Create a directory (and parents) if it does not exist.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
                "required": ["path"],
            },
            handler=lambda **kwargs: _mkdir(scope, **kwargs),
            source="filesystem",
        ),
    ]
