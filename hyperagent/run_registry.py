"""Where every run's report directory lives: ``~/.hyperagent/runs.json``.

A run writes its reports next to its sample (``<sample_dir>/reports/<sha>``)
unless ``reports_root`` says otherwise, so runs over different datasets end up
in different trees. The launcher records each run's report directory here, and
the dashboard reads this index on top of its own reports root, so it can show
every run no matter which folder it was written to.

The file is a small JSON object::

    {"version": 1, "runs": [{"sha256": "...", "report_dir": "H:\\\\...\\\\<sha>",
      "sample_path": "...", "first_seen": "...Z", "last_seen": "...Z"}]}

Entries are keyed by report directory, so one sample analysed into two trees
keeps both. Entries whose directory is gone are skipped when reading and
dropped on the next write. Stdlib only: ``webui`` imports it too.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

INDEX_ENV = "HYPERAGENT_RUN_INDEX"
INDEX_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_LOCK_TIMEOUT_SECONDS = 5.0


def default_index_path() -> Path:
    configured = os.environ.get(INDEX_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hyperagent" / "runs.json"


@dataclass(frozen=True)
class RunLink:
    sha256: str
    report_dir: str
    sample_path: str = ""
    first_seen: str = ""
    last_seen: str = ""

    @property
    def path(self) -> Path:
        return Path(self.report_dir)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid(sha256: str, report_dir: Path) -> bool:
    """A link must name a run directory: ``<anything>/<sha256>``.

    The dashboard reads fixed artifact names inside linked directories, so a
    hand-edited entry must not be able to point it at an arbitrary folder.
    """
    return bool(_SHA256.match(sha256)) and report_dir.name.lower() == sha256.lower()


def _parse(raw: Any) -> list[RunLink]:
    entries = raw.get("runs") if isinstance(raw, dict) else None
    links = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        sha256 = str(entry.get("sha256") or "").lower()
        report_dir = str(entry.get("report_dir") or "")
        if not report_dir or not _valid(sha256, Path(report_dir)):
            continue
        links.append(
            RunLink(
                sha256=sha256,
                report_dir=report_dir,
                sample_path=str(entry.get("sample_path") or ""),
                first_seen=str(entry.get("first_seen") or ""),
                last_seen=str(entry.get("last_seen") or ""),
            )
        )
    return links


def _read(path: Path) -> list[RunLink]:
    try:
        return _parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def load_links(index_path: Path | None = None, *, existing_only: bool = True) -> list[RunLink]:
    """Every linked run, most recently seen first."""
    links = _read(index_path or default_index_path())
    if existing_only:
        links = [link for link in links if link.path.is_dir()]
    return sorted(links, key=lambda link: link.last_seen, reverse=True)


def report_dirs(index_path: Path | None = None) -> list[Path]:
    return [link.path for link in load_links(index_path)]


class _IndexLock:
    """Cross-process lock file, so concurrent runs do not drop each other's link."""

    def __init__(self, path: Path) -> None:
        self.path = path.with_name(path.name + ".lock")
        self._fd: int | None = None

    def __enter__(self) -> "_IndexLock":
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:  # a lock left by a crashed process
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"run index is locked: {self.path}") from None
                time.sleep(0.05)

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass


def link_runs(entries: Iterable[tuple[str, Path, str]], *, index_path: Path | None = None) -> int:
    """Add or refresh ``(sha256, report_dir, sample_path)`` links; returns how many."""
    path = index_path or default_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    with _IndexLock(path):
        current = {
            os.path.normcase(link.report_dir): link for link in _read(path) if link.path.is_dir()
        }
        added = 0
        for sha256, report_dir, sample_path in entries:
            report_dir = Path(report_dir).expanduser().resolve()
            sha256 = sha256.lower()
            if not _valid(sha256, report_dir):
                logger.debug("Not linking %s: directory name is not its SHA256", report_dir)
                continue
            key = os.path.normcase(str(report_dir))
            previous = current.get(key)
            current[key] = RunLink(
                sha256=sha256,
                report_dir=str(report_dir),
                sample_path=sample_path or (previous.sample_path if previous else ""),
                first_seen=previous.first_seen if previous else now,
                last_seen=now,
            )
            added += 1
        payload = {
            "version": INDEX_VERSION,
            "runs": [asdict(link) for link in current.values()],
        }
        handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".runs-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
            os.replace(temp, path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
    return added


def link_run(
    sha256: str, report_dir: Path, *, sample_path: str = "", index_path: Path | None = None
) -> bool:
    """Record one run. Never raises: the analysis matters more than the index."""
    try:
        return link_runs([(sha256, report_dir, sample_path)], index_path=index_path) == 1
    except Exception as exc:  # noqa: BLE001 - disk, permissions, lock timeout
        logger.warning(
            "Could not record the run in %s: %s", index_path or default_index_path(), exc
        )
        return False


def find_run_dirs(root: Path) -> list[tuple[str, Path, str]]:
    """Run directories under *root*: ``<sha256>/`` folders holding STATE.json
    or a 09-summary.json, searched recursively."""
    markers = ("STATE.json", "09-summary.json", "console.jsonl")
    found = []
    for current, dirs, files in os.walk(root):
        here = Path(current)
        if _SHA256.match(here.name) and any(name in files for name in markers):
            sample = ""
            try:
                data = json.loads((here / "STATE.json").read_text(encoding="utf-8"))
                sample = str(data.get("input_path") or "") if isinstance(data, dict) else ""
            except (OSError, ValueError):
                pass
            found.append((here.name.lower(), here, sample))
            dirs.clear()  # a run's own subfolders (_state, nested reports/) are not runs
            continue
        dirs[:] = sorted(name for name in dirs if not name.startswith((".", "__")))
    return found
