"""Export the llm-compare sample subset as a standalone reference manifest.

Pulls the ``in_llm_ablation_subset`` entries out of
``experiments/results/sample_selection.json`` -- the same 10 samples
``run_study.py llm-compare`` already filters to internally via
``subset_samples()`` -- into their own small JSON file, so a collaborator
running that mode can see exactly which samples/conditions are theirs
without diffing the full 30-sample manifest.

This file is for reference only: it is NOT passed as ``--manifest`` to
``run_study.py``. The receiving machine should just run
``python -m experiments.run_study llm-compare`` against its own checkout,
which already contains the full manifest with the same subset flags.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_study import LLM_CONDITIONS, MANIFEST_PATH, load_manifest, subset_samples

DEFAULT_OUT = Path("experiments/results/llm_compare_set3_manifest.json")


def build_export(manifest_path: Path) -> dict:
    manifest = load_manifest(manifest_path)
    samples = subset_samples(manifest)
    return {
        "mode": "llm-compare",
        "source_manifest": str(manifest_path),
        "sample_count": len(samples),
        "conditions": [
            {"slug": c.slug, "model": c.model, "reused_from_default_location": c.reused_from_default_location}
            for c in LLM_CONDITIONS
        ],
        "note": (
            "Reference only -- do not pass this file as --manifest. Run "
            "`python -m experiments.run_study llm-compare` on the receiving "
            "machine; it already filters to this same subset. Each sample's "
            "'path' below is local to the machine that generated this file "
            "(H:\\Dataset\\...) -- the receiving machine needs its own copy "
            "of these files, ideally at a matching path, since sample "
            "binaries are not included in this export."
        ),
        "samples": samples,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the llm-compare subset for handoff")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    export = build_export(args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {export['sample_count']} samples to {args.out}")
    for s in export["samples"]:
        print(f"  {s['hash'][:12]}  {s['label']:9s}  {s.get('dominant_category', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
