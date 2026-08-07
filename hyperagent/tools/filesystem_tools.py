"""Filesystem tool wrappers for the agentic loop."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .base import ToolDefinition, ToolResult


def _read_file(path: str = "", **_kw) -> ToolResult:
    try:
        p = Path(path)
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
    except Exception as exc:
        return ToolResult(content=f"read_file error: {exc}", is_error=True)


def _write_file(path: str = "", content: str = "", **_kw) -> ToolResult:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(content=f"Written {len(content)} bytes to {path}")
    except Exception as exc:
        return ToolResult(content=f"write_file error: {exc}", is_error=True)


def _sha256_file(path: str = "", **_kw) -> ToolResult:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return ToolResult(content=digest.hexdigest())
    except Exception as exc:
        return ToolResult(content=f"sha256 error: {exc}", is_error=True)


def _list_directory(path: str = "", **_kw) -> ToolResult:
    try:
        entries = []
        for entry in sorted(Path(path).iterdir()):
            kind = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else 0
            entries.append({"name": entry.name, "type": kind, "size": size})
        return ToolResult(content=json.dumps(entries, indent=2))
    except Exception as exc:
        return ToolResult(content=f"list_directory error: {exc}", is_error=True)


def _file_exists(path: str = "", **_kw) -> ToolResult:
    exists = Path(path).exists()
    return ToolResult(content=json.dumps({"exists": exists, "path": path}))


def _mkdir(path: str = "", **_kw) -> ToolResult:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return ToolResult(content=f"Directory created: {path}")
    except Exception as exc:
        return ToolResult(content=f"mkdir error: {exc}", is_error=True)


def create_filesystem_tools() -> list[ToolDefinition]:
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
            handler=_read_file,
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
            handler=_write_file,
        ),
        ToolDefinition(
            name="sha256_file",
            description="Compute the SHA256 hash of a file.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute file path"}},
                "required": ["path"],
            },
            handler=_sha256_file,
        ),
        ToolDefinition(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
                "required": ["path"],
            },
            handler=_list_directory,
        ),
        ToolDefinition(
            name="file_exists",
            description="Check if a file or directory exists at the given path.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute path to check"}},
                "required": ["path"],
            },
            handler=_file_exists,
        ),
        ToolDefinition(
            name="mkdir",
            description="Create a directory (and parents) if it does not exist.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
                "required": ["path"],
            },
            handler=_mkdir,
        ),
    ]
