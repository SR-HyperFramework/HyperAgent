from __future__ import annotations

import os
import shutil
from typing import Any, Iterable

UNSAFE_CLAUDE_PERMISSION_FLAG = "--dangerously-skip-permissions"


def _config_section(config: dict[str, Any] | None, section: str) -> dict[str, Any]:
    value = (config or {}).get(section)
    return value if isinstance(value, dict) else {}


def get_tool_setting(config: dict[str, Any] | None, key: str, default: str | None = None) -> str | None:
    value = _config_section(config, "tools").get(key)
    return str(value) if value else default


def get_command_setting(
    config: dict[str, Any] | None,
    section: str,
    key: str,
    default: Iterable[str],
) -> list[str]:
    value = _config_section(config, section).get(key)
    if isinstance(value, (list, tuple)) and value:
        return [str(item) for item in value]
    return [str(item) for item in default]


def get_claude_code_command(config: dict[str, Any] | None = None) -> list[str]:
    return get_command_setting(config, "llm", "claude_code_command", ["claude"])


def get_claude_code_args(instruction: str) -> list[str]:
    return ["-p", UNSAFE_CLAUDE_PERMISSION_FLAG, instruction]


def get_ida_server_command(config: dict[str, Any] | None = None) -> list[str]:
    return get_command_setting(config, "mcp", "ida_server_command", ["uv", "run", "idalib-mcp"])


def resolve_candidate_path(
    configured: str | None,
    fallbacks: list[str],
    repo_root: str | None = None,
) -> str | None:
    candidates: list[str] = []
    if configured:
        candidates.append(str(configured))
    candidates.extend(str(candidate) for candidate in fallbacks)

    for candidate in candidates:
        expanded = os.path.expandvars(os.path.expanduser(candidate))
        if os.path.isabs(expanded):
            if os.path.isfile(expanded):
                return os.path.normpath(expanded)
            continue

        which = shutil.which(expanded)
        if which:
            return os.path.normpath(which)

        if repo_root:
            repo_rel = os.path.normpath(os.path.join(repo_root, expanded))
            if os.path.isfile(repo_rel):
                return repo_rel

    return None


def resolve_tool_path(
    config: dict[str, Any] | None,
    key: str,
    fallbacks: list[str],
    repo_root: str | None = None,
) -> str | None:
    return resolve_candidate_path(get_tool_setting(config, key), fallbacks, repo_root=repo_root)
