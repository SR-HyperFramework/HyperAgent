# Phase 5 — Batch Evaluation Pipeline

Read `00-index.md` first for shared constraints and reference paths.
**Depends on Phase 3d** (`engine/launcher.py::run_pipeline_with_config`) —
this phase calls it per-sample.

## Goal

Run the full pipeline across a labeled corpus (malware + benign samples)
and produce precision/recall/F1/FPR/token-cost metrics, with a temporal
train/test-style split to check for concept drift (does accuracy degrade on
samples first-seen after a cutoff date vs. before it).

## File to create: `experiments/batch_eval.py`

```python
@dataclass
class SampleMeta:
    path: Path
    label: str  # "malware" | "benign"
    first_seen: date | None = None

@dataclass
class EvaluationReport:
    per_sample: list[dict]  # one row per sample: precision/recall/f1/fpr/token_cost/verdict
    aggregate: dict          # macro/micro averages
    temporal_drift: dict | None = None  # only populated if a split_date was given

class BatchEvaluator:
    async def evaluate_corpus(
        self,
        malware_dir: Path,
        benign_dir: Path,
        output_dir: Path,
        ablation_config: AblationConfig | None = None,
        quick_test: bool = False,  # cap sample count for --quick-test CLI flag
    ) -> EvaluationReport: ...

    def temporal_split(
        self, samples: list[SampleMeta], split_date: date
    ) -> tuple[list[SampleMeta], list[SampleMeta]]:
        """Split by first-seen date; samples missing first_seen go in neither
        half — log a warning listing which ones were dropped and why (don't
        silently exclude them)."""
```

Implementation notes:
- Per sample: call `hyperagent.engine.launcher.run_pipeline_with_config(
  sample_path, config, ablation_config, run_id=<sample_hash>)`, which
  returns a `RunMetrics` (see `hyperagent/telemetry/metrics.py` for its
  exact fields before assuming what's on it — read that file first).
- "Verdict" for precision/recall purposes needs to come from the pipeline's
  final `09-summary` stage output JSON (`reports/<sha256>/09-summary.json`
  or equivalent — confirm the actual final-stage output filename against
  `tools/registry.py::STAGE_TOOLS` keys / the real skill files under
  `~/.claude/skills/hyperagent-summary/` before hardcoding a path).
- Ground truth is `SampleMeta.label` (malware/benign, from which directory
  the sample came from — `malware_dir` vs `benign_dir`).
- FPR here = fraction of `benign`-labeled samples the pipeline verdicts as
  malicious — distinct from the FPR in Phase 4's `RuleVerifier` (that one is
  about generated detection *rules*, this one is about the *pipeline's own
  verdicts*). Don't conflate the two FPR concepts in the output schema;
  name fields clearly (`pipeline_fpr` vs anything rule-related).
- Output: CSV (`per_sample` rows) + JSONL (raw `EvaluationReport` dump) to
  `output_dir`. Use the stdlib `csv` module — no new dependency.
- `--quick-test` mode: cap total samples processed (e.g. 5 malware + 5
  benign) instead of the full 200-sample minimum, so this is runnable in a
  reasonable time during development.

## Exit criteria

```bash
python -m experiments.batch_eval --quick-test --malware-dir samples/malware --benign-dir samples/benign --output-dir experiments/results
```
Produces CSV/JSONL in `experiments/results/` with per-sample and aggregate
metrics on a small (~10 sample) test set. If `samples/malware` and
`samples/benign` directories don't exist yet in this repo, create tiny
placeholder fixture dirs under `hyperagent/tests/fixtures/` instead and
point the exit-criteria command at those — don't block this phase on
sourcing a real malware corpus.

Add `hyperagent/tests/test_batch_eval.py` (or `experiments/tests/` if that's
where `ablation_runner.py`'s own tests live — check for an existing
`experiments/tests/` dir first) mocking `run_pipeline_with_config` so the
test suite doesn't need real samples/VM/LLM calls; assert
`temporal_split()` correctly buckets samples by date and logs (doesn't
silently drop) samples with missing `first_seen`.
