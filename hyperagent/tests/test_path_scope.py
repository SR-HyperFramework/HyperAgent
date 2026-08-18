"""Tests for per-run path scope enforcement."""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperagent.tools.path_scope import PathScope, PathScopeError, compute_run_scope


@pytest.fixture()
def roots(tmp_path: Path):
    sample_dir = tmp_path / "samples"
    report_dir = tmp_path / "reports" / "abc"
    skills_dir = tmp_path / "skills"
    sample_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    sample = sample_dir / "sample.exe"
    sample.write_bytes(b"MZ")
    return sample, report_dir, skills_dir


@pytest.fixture()
def scope(roots) -> PathScope:
    sample, report_dir, skills_dir = roots
    return compute_run_scope(sample, report_dir, skills_dir)


def test_compute_run_scope_sets_expected_roots(roots):
    sample, report_dir, skills_dir = roots
    scope = compute_run_scope(sample, report_dir, skills_dir)
    assert scope.read_roots == (
        sample.parent.resolve(),
        report_dir.resolve(),
        skills_dir.resolve(),
    )
    assert scope.write_roots == (report_dir.resolve(),)


def test_check_read_allows_path_inside_read_root(scope, roots):
    sample, _, _ = roots
    assert scope.check_read(str(sample)) == sample.resolve()


def test_check_write_allows_path_inside_write_root(scope, roots):
    _, report_dir, _ = roots
    target = report_dir / "stage.json"
    assert scope.check_write(str(target)) == target.resolve()


def test_check_read_rejects_parent_escape(scope, roots):
    sample, _, _ = roots
    escaped = sample.parent / ".." / "other.txt"
    with pytest.raises(PathScopeError, match="allowed analysis scope"):
        scope.check_read(str(escaped))


def test_check_write_rejects_path_outside_write_root(scope, tmp_path):
    outside = tmp_path / "elsewhere" / "out.json"
    with pytest.raises(PathScopeError, match="allowed analysis scope"):
        scope.check_write(str(outside))


def test_check_relative_path_uses_write_root_as_base(scope, roots):
    _, report_dir, _ = roots
    target = report_dir / "nested" / "report.json"
    assert scope.check_write("nested/report.json") == target.resolve()


def test_check_read_and_write_roots_are_distinct(scope, roots):
    sample, _, _ = roots
    with pytest.raises(PathScopeError, match="allowed analysis scope"):
        scope.check_write(str(sample))
