"""Tests for hyperagent.run_registry (the index of report folders)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from hyperagent import run_registry
from hyperagent.cli import main
from hyperagent.run_registry import (
    default_index_path,
    find_run_dirs,
    link_run,
    link_runs,
    load_links,
    report_dirs,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _run_dir(root: Path, sha: str, marker: str = "STATE.json") -> Path:
    run_dir = root / sha
    run_dir.mkdir(parents=True)
    (run_dir / marker).write_text(json.dumps({"input_path": f"C:/samples/{sha[:4]}"}), "utf-8")
    return run_dir


def test_link_run_records_and_refreshes_one_entry_per_folder(tmp_path: Path):
    run_dir = _run_dir(tmp_path / "dataset" / "reports", SHA_A)

    assert link_run(SHA_A.upper(), run_dir, sample_path="C:/s.exe")
    first = load_links()[0]
    assert link_run(SHA_A, run_dir)  # second run of the same sample

    (link,) = load_links()
    assert link.sha256 == SHA_A and link.path == run_dir.resolve()
    assert link.sample_path == "C:/s.exe"  # kept when not given again
    assert link.first_seen == first.first_seen
    assert default_index_path().is_file()


def test_same_sample_in_two_trees_keeps_both_links(tmp_path: Path):
    one = _run_dir(tmp_path / "one", SHA_A)
    two = _run_dir(tmp_path / "two", SHA_A)

    link_runs([(SHA_A, one, ""), (SHA_A, two, "")])

    assert sorted(report_dirs()) == sorted([one.resolve(), two.resolve()])


def test_links_must_name_a_run_folder_and_vanished_folders_are_dropped(tmp_path: Path):
    stray = tmp_path / "not-a-run"
    stray.mkdir()
    gone = _run_dir(tmp_path, SHA_B)

    assert not link_run(SHA_A, stray)
    assert link_run(SHA_B, gone)
    (gone / "STATE.json").unlink()
    gone.rmdir()

    assert load_links() == []
    assert len(load_links(existing_only=False)) == 1
    link_run(SHA_A, _run_dir(tmp_path, SHA_A))  # rewriting prunes the dead link
    assert [link.sha256 for link in load_links(existing_only=False)] == [SHA_A]


def test_hand_edited_index_cannot_point_at_arbitrary_folders(tmp_path: Path):
    default_index_path().parent.mkdir(parents=True, exist_ok=True)
    default_index_path().write_text(
        json.dumps({"runs": [{"sha256": SHA_A, "report_dir": str(tmp_path)}, "junk"]}), "utf-8"
    )

    assert load_links(existing_only=False) == []


def test_concurrent_writers_do_not_lose_links(tmp_path: Path):
    dirs = [_run_dir(tmp_path, f"{index:x}" * 64) for index in range(8)]

    threads = [threading.Thread(target=link_run, args=(d.name, d)) for d in dirs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(report_dirs()) == 8
    assert not Path(str(default_index_path()) + ".lock").exists()


def test_find_run_dirs_stops_at_run_folders(tmp_path: Path):
    outer = _run_dir(tmp_path / "m" / "reports", SHA_A)
    _run_dir(outer / "reports", SHA_A, marker="09-summary.json")  # nested legacy layout
    _run_dir(tmp_path / "x" / "results", SHA_B, marker="console.jsonl")
    (tmp_path / "x" / "results" / ("c" * 64)).mkdir()  # empty: not a run

    found = find_run_dirs(tmp_path)

    assert [(sha, path) for sha, path, _ in found] == [
        (SHA_A, outer),
        (SHA_B, tmp_path / "x" / "results" / SHA_B),
    ]
    assert found[0][2] == f"C:/samples/{SHA_A[:4]}"


def test_link_reports_command_links_existing_folders(tmp_path: Path, capsys):
    _run_dir(tmp_path / "m" / "reports", SHA_A)
    _run_dir(tmp_path / "exp", SHA_B)

    assert main(["link-reports", str(tmp_path / "m"), str(tmp_path / "exp")]) == 0

    out = capsys.readouterr().out
    assert "Linked 2 run(s)" in out
    assert {link.sha256 for link in load_links()} == {SHA_A, SHA_B}
    assert main(["link-reports", str(tmp_path / "missing")]) == 2


def test_index_path_follows_the_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(run_registry.INDEX_ENV, str(tmp_path / "elsewhere.json"))
    assert default_index_path() == tmp_path / "elsewhere.json"
