"""Tests for configuration loading and the thinking-level resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperagent.config import THINKING_LEVELS, ProviderConfig, load_config


def test_thinking_level_loads_from_yaml(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HYPERAGENT_THINKING_LEVEL", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "provider:\n"
        "  thinking_level: medium\n"
        "  stage_thinking_levels:\n"
        "    07-deepdive: max\n",
        encoding="utf-8",
    )

    provider = load_config(config_path).provider

    assert provider.thinking_level == "medium"
    assert provider.resolve_thinking("07-deepdive") == (True, THINKING_LEVELS["max"])
    assert provider.resolve_thinking("08-report") == (True, THINKING_LEVELS["medium"])


def test_thinking_level_env_overrides_yaml(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider:\n  thinking_level: low\n", encoding="utf-8")
    monkeypatch.setenv("HYPERAGENT_THINKING_LEVEL", "high")

    assert load_config(config_path).provider.thinking_level == "high"


def test_resolve_thinking_defaults_to_disabled():
    assert ProviderConfig().resolve_thinking() == (False, 4096)


def test_resolve_thinking_rejects_unknown_stage_level():
    cfg = ProviderConfig(stage_thinking_levels={"05-dynamic": "deep"})
    with pytest.raises(ValueError, match="Unknown thinking level"):
        cfg.resolve_thinking("05-dynamic")
