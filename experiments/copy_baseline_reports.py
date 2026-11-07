"""Mirror baseline_30's per-sample report dirs into the repo.

``baseline`` runs against the default ``reports_root`` (next to each sample,
on the H: dataset drive), unlike ``llm-compare``/``ablation`` which point
``reports_root`` at ``experiments/results/<mode>/.../reports/`` inside the
repo. This copies each of the 30 samples' report dirs into
``experiments/results/baseline_30/reports/<hash>/`` so baseline is equally
inspectable from the repo, matching the other two modes' layout.

Sample binaries themselves are never touched -- only the ``reports/<hash>``
subtree next to each sample, which never contains the sample itself.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from experiments.run_study import MANIFEST_PATH, all_samples, load_manifest

DEST_ROOT = Path("experiments/results/baseline_30/reports")
_SKIP_SUFFIXES = (".bak-corrupt", ".bak-before-retry", ".bak-before-auto-retry")


def _skip(path: Path) -> bool:
    name = path.name
    return any(part in name for part in _SKIP_SUFFIXES)


def copy_one(sample_path: Path, sample_hash: str) -> tuple[str, int]:
    src = sample_path.parent / "reports" / sample_hash
    dest = DEST_ROOT / sample_hash
    if not src.exists():
        return ("missing", 0)
    if dest.exists():
        shutil.rmtree(dest)
    file_count = 0

    def _ignore(dirpath: str, names: list[str]) -> list[str]:
        nonlocal file_count
        ignored = []
        base = Path(dirpath)
        for name in names:
            p = base / name
            if p.is_file():
                if _skip(p):
                    ignored.append(name)
                else:
                    file_count += 1
        return ignored

    shutil.copytree(src, dest, ignore=_ignore)
    return ("copied", file_count)


def main() -> int:
    manifest = load_manifest(MANIFEST_PATH)
    samples = all_samples(manifest)
    DEST_ROOT.mkdir(parents=True, exist_ok=True)

    total_files = 0
    missing = []
    for s in samples:
        status, count = copy_one(Path(s["path"]), s["hash"])
        short = s["hash"][:12]
        if status == "missing":
            missing.append(short)
            print(f"[skip] {short}: no report dir found")
        else:
            total_files += count
            print(f"[ok]   {short}: {count} file(s)")

    print(f"\ncopied {len(samples) - len(missing)}/{len(samples)} sample report dirs, {total_files} files total -> {DEST_ROOT}")
    if missing:
        print(f"missing report dirs for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
