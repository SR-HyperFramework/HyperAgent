"""HyperAgent central configuration.

Loads settings from environment variables with optional YAML config file override.
Environment variables always take precedence over config file values.

VM credentials have no built-in defaults: set ``HYPERAGENT_VMX_PATH``,
``HYPERAGENT_VM_SNAPSHOT``, ``HYPERAGENT_GUEST_USER``, ``HYPERAGENT_GUEST_PASSWORD``,
``HYPERAGENT_GUEST_DESKTOP`` and ``HYPERAGENT_GUEST_DEBUGGER``, or the matching
``vmware:`` keys in ``~/.hyperagent/config.yaml``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class VMwareConfig:
    """VMware Workstation guest VM settings."""

    vmx_path: str = ""
    snapshot_name: str = ""
    guest_user: str = ""
    guest_password: str = ""
    guest_desktop: str = ""
    guest_debugger: str = ""
    startup_timeout: int = 120
    command_timeout: int = 30


@dataclass
class MCPEndpoint:
    """MCP server connection settings."""

    url: str
    health_path: str = "/"
    timeout: int = 30


@dataclass
class ProviderConfig:
    """LLM provider settings."""

    name: str = "anthropic"
    model: str = ""
    """Model id. Empty means "whatever the selected provider defaults to" —
    keeping the default in one place (``providers._DEFAULT_MODELS``) instead of
    repeating a model string that has to be updated here too when it retires."""
    api_key: str = ""
    base_url: str = ""
    """Override the API endpoint, e.g. for an Anthropic-compatible proxy or
    gateway. Empty means the provider SDK's own default (``api.anthropic.com``)."""
    max_output_tokens: int = 16384
    temperature: float | None = None
    """Sampling temperature, forwarded only to backends that still accept one.

    ``None`` by default because Anthropic removed sampling parameters on Claude
    Opus 4.7 and later — a non-default value there returns a 400. Note that
    ``temperature=0`` never guaranteed identical outputs on any model; to reduce
    variance, tighten the prompt rather than the sampler."""
    extended_thinking: bool = False
    """Request Claude's extended-thinking content blocks (Anthropic only)."""
    thinking_budget_tokens: int = 4096
    """Token budget for extended thinking when ``extended_thinking`` is on."""
    debug_console: bool = False
    """Stream thinking/text/tool-call deltas to the console as they arrive."""
    # Per-stage model overrides: stage_id -> model name
    stage_models: dict[str, str] = field(default_factory=dict)


@dataclass
class HyperAgentConfig:
    """Top-level configuration for HyperAgent v4."""

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    vmware: VMwareConfig = field(default_factory=VMwareConfig)

    # MCP endpoints
    x64dbg_mcp: MCPEndpoint = field(
        default_factory=lambda: MCPEndpoint(url="http://192.168.248.169:3000/mcp")
    )
    ida_mcp: MCPEndpoint = field(
        default_factory=lambda: MCPEndpoint(url="http://localhost:13337/mcp")
    )

    # Paths
    skills_root: Path = field(default_factory=lambda: Path.home() / ".claude" / "skills")
    reports_root: Path | None = None  # Default: <sample_parent>/reports

    # Pipeline
    max_stage_attempts: int = 20
    checkpoint_threshold: float = 0.75

    # API keys (non-LLM)
    virustotal_api_key: str = ""


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw is not None else default


def _env_float(key: str, default: float | None) -> float | None:
    raw = os.environ.get(key)
    return float(raw) if raw is not None else default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    return raw.strip().lower() in ("1", "true", "yes", "on") if raw is not None else default


def load_config(config_path: Path | None = None) -> HyperAgentConfig:
    """Load configuration from YAML file, then override with environment variables.

    Resolution order (highest priority first):
    1. Environment variables
    2. YAML config file
    3. Dataclass defaults
    """
    file_data: dict[str, Any] = {}
    if config_path is None:
        config_path = Path.home() / ".hyperagent" / "config.yaml"
    if config_path.exists():
        file_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    provider_data = file_data.get("provider", {})
    vmware_data = file_data.get("vmware", {})

    provider = ProviderConfig(
        name=_env("HYPERAGENT_PROVIDER", provider_data.get("name", "anthropic")),
        model=_env("HYPERAGENT_MODEL", provider_data.get("model", "")),
        api_key=_env("ANTHROPIC_API_KEY", _env("OPENAI_API_KEY", provider_data.get("api_key", ""))),
        base_url=_env(
            "HYPERAGENT_ANTHROPIC_BASE_URL", provider_data.get("base_url", "")
        ),
        max_output_tokens=_env_int(
            "HYPERAGENT_MAX_OUTPUT_TOKENS",
            provider_data.get("max_output_tokens", 16384),
        ),
        temperature=_env_float(
            "HYPERAGENT_TEMPERATURE", provider_data.get("temperature")
        ),
        extended_thinking=_env_bool(
            "HYPERAGENT_EXTENDED_THINKING", provider_data.get("extended_thinking", False)
        ),
        thinking_budget_tokens=_env_int(
            "HYPERAGENT_THINKING_BUDGET", provider_data.get("thinking_budget_tokens", 4096)
        ),
        debug_console=_env_bool(
            "HYPERAGENT_DEBUG_CONSOLE", provider_data.get("debug_console", False)
        ),
        stage_models=provider_data.get("stage_models", {}),
    )

    vmware = VMwareConfig(
        vmx_path=_env("HYPERAGENT_VMX_PATH", vmware_data.get("vmx_path", "")),
        snapshot_name=_env("HYPERAGENT_VM_SNAPSHOT", vmware_data.get("snapshot_name", "")),
        guest_user=_env("HYPERAGENT_GUEST_USER", vmware_data.get("guest_user", "")),
        guest_password=_env("HYPERAGENT_GUEST_PASSWORD", vmware_data.get("guest_password", "")),
        guest_desktop=_env("HYPERAGENT_GUEST_DESKTOP", vmware_data.get("guest_desktop", "")),
        guest_debugger=_env("HYPERAGENT_GUEST_DEBUGGER", vmware_data.get("guest_debugger", "")),
        startup_timeout=_env_int(
            "HYPERAGENT_VM_STARTUP_TIMEOUT", vmware_data.get("startup_timeout", 120)
        ),
        command_timeout=_env_int(
            "HYPERAGENT_VM_COMMAND_TIMEOUT", vmware_data.get("command_timeout", 30)
        ),
    )

    x64dbg_url = _env(
        "HYPERAGENT_X64DBG_MCP_URL",
        file_data.get("x64dbg_mcp", {}).get("url", "http://192.168.248.169:3000/mcp"),
    )
    ida_url = _env(
        "HYPERAGENT_IDA_MCP_URL",
        file_data.get("ida_mcp", {}).get("url", "http://localhost:13337/mcp"),
    )

    skills_root_str = _env(
        "HYPERAGENT_SKILLS_ROOT",
        file_data.get("skills_root", str(Path.home() / ".claude" / "skills")),
    )

    return HyperAgentConfig(
        provider=provider,
        vmware=vmware,
        x64dbg_mcp=MCPEndpoint(url=x64dbg_url),
        ida_mcp=MCPEndpoint(url=ida_url),
        skills_root=Path(skills_root_str),
        max_stage_attempts=_env_int(
            "HYPERAGENT_MAX_STAGE_ATTEMPTS",
            file_data.get("max_stage_attempts", 20),
        ),
        checkpoint_threshold=_env_float(
            "HYPERAGENT_CHECKPOINT_THRESHOLD",
            file_data.get("checkpoint_threshold", 0.75),
        ),
        virustotal_api_key=_env(
            "VT_API_KEY",
            _env("VIRUSTOTAL_API_KEY", file_data.get("virustotal_api_key", "")),
        ),
    )
