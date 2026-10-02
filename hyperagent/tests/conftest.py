"""Shared test setup."""

from __future__ import annotations

import pytest

from hyperagent.run_registry import INDEX_ENV


@pytest.fixture(autouse=True)
def _isolated_run_index(tmp_path_factory, monkeypatch):
    """Never let a test run read or write the user's ~/.hyperagent/runs.json."""
    monkeypatch.setenv(INDEX_ENV, str(tmp_path_factory.mktemp("run-index") / "runs.json"))
