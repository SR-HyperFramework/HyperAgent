"""Unit tests for the telemetry metrics module."""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from hyperagent.telemetry.metrics import (
    MetricsCollector,
    RunMetrics,
    StageMetrics,
    _price_table,
)


class TestStageMetrics:
    """Tests for StageMetrics computed properties."""

    def _make(self, **kwargs) -> StageMetrics:
        defaults = dict(
            run_id="test-run",
            sample_sha256="abc" * 21 + "ab",  # 64 hex chars
            stage_id="05-dynamic",
            provider="claude-sonnet-4-5-20251201",
        )
        defaults.update(kwargs)
        return StageMetrics(**defaults)

    def test_precision_zero_division(self):
        sm = self._make(true_positives=0, false_positives=0)
        assert sm.precision == 0.0

    def test_precision_basic(self):
        sm = self._make(true_positives=8, false_positives=2)
        assert sm.precision == pytest.approx(0.8)

    def test_recall_basic(self):
        sm = self._make(true_positives=8, false_negatives=2)
        assert sm.recall == pytest.approx(0.8)

    def test_f1_balanced(self):
        sm = self._make(true_positives=8, false_positives=2, false_negatives=2)
        # P = 0.8, R = 0.8 → F1 = 0.8
        assert sm.f1_score == pytest.approx(0.8)

    def test_token_efficiency(self):
        sm = self._make(true_positives=10, total_input_tokens=5_000)
        # 10 / 5000 * 1000 = 2.0
        assert sm.token_efficiency == pytest.approx(2.0)

    def test_cache_hit_rate(self):
        sm = self._make(
            cache_creation_input_tokens=4_000,
            cache_read_input_tokens=36_000,
        )
        assert sm.cache_hit_rate == pytest.approx(0.9)

    def test_cache_hit_rate_no_cache(self):
        sm = self._make()
        assert sm.cache_hit_rate == 0.0

    def test_effective_cost_usd_sonnet(self):
        """Cache reads should be 10× cheaper than plain input for Sonnet."""
        sm = self._make(
            total_input_tokens=10_000,
            total_output_tokens=1_000,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=10_000,
        )
        p = _price_table("claude-sonnet-4-5")
        expected = (
            0 * p["input"]          # plain input = 0 (all served from cache)
            + 0 * p["cache_write"]  # no writes
            + 10_000 * p["cache_read"]
            + 1_000 * p["output"]
        )
        assert sm.effective_cost_usd == pytest.approx(expected, rel=1e-6)

    def test_cache_savings_percent(self):
        """Savings should be positive when cache_read > 0."""
        sm = self._make(
            total_input_tokens=10_000,
            total_output_tokens=500,
            cache_creation_input_tokens=1_000,
            cache_read_input_tokens=9_000,
        )
        assert sm.cache_savings_percent > 0

    def test_to_jsonl_roundtrip(self):
        sm = self._make(true_positives=5, false_positives=1, false_negatives=2)
        sm.end_time = sm.start_time + 10.0
        sm.stage_status = "completed"
        jsonl = sm.to_jsonl()
        obj = json.loads(jsonl)
        assert obj["stage_id"] == "05-dynamic"
        assert obj["evaluation"]["precision"] == pytest.approx(sm.precision, abs=1e-3)
        assert obj["evaluation"]["recall"] == pytest.approx(sm.recall, abs=1e-3)


class TestMetricsCollector:
    """Tests for the MetricsCollector accumulator."""

    def test_start_and_record_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = MetricsCollector(
                run_id=uuid.uuid4().hex,
                sample_sha256="a" * 64,
                output_path=Path(tmpdir) / "telemetry.jsonl",
            )
            collector.start_stage("05-dynamic", provider="claude-sonnet")
            collector.record_turn(
                "05-dynamic",
                input_tokens=1_000,
                output_tokens=200,
                cache_creation_input_tokens=500,
                cache_read_input_tokens=0,
                tool_calls=3,
                tool_errors=0,
            )
            collector.record_turn(
                "05-dynamic",
                input_tokens=500,
                output_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=500,
                tool_calls=2,
                tool_errors=1,
            )

            sm = collector.get_stage("05-dynamic")
            assert sm is not None
            assert sm.turns == 2
            assert sm.total_input_tokens == 1_500
            assert sm.cache_read_input_tokens == 500
            assert sm.tool_calls == 5
            assert sm.tool_errors == 1

    def test_finalize_stage_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "telemetry.jsonl"
            collector = MetricsCollector(
                run_id="run-1",
                sample_sha256="b" * 64,
                output_path=out,
            )
            collector.start_stage("08-report")
            collector.record_turn("08-report", input_tokens=500, output_tokens=100)
            collector.finalize_stage(
                "08-report",
                status="completed",
                true_positives=10,
                false_positives=2,
                false_negatives=3,
            )

            assert out.exists()
            with out.open() as fh:
                obj = json.loads(fh.readline())
            assert obj["stage_id"] == "08-report"
            assert obj["evaluation"]["true_positives"] == 10
            assert obj["evaluation"]["f1_score"] > 0

    def test_finalize_run_aggregates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = MetricsCollector(
                run_id="run-agg",
                sample_sha256="c" * 64,
                output_path=Path(tmpdir) / "telemetry.jsonl",
            )
            for stage in ["02-static-pass1", "05-dynamic", "08-report"]:
                collector.start_stage(stage)
                collector.record_turn(stage, input_tokens=1_000, output_tokens=200)
                collector.finalize_stage(
                    stage,
                    status="completed",
                    true_positives=5,
                    false_positives=1,
                    false_negatives=1,
                )

            run = collector.finalize_run()
            assert run.total_input_tokens == 3_000
            assert run.total_output_tokens == 600
            # 3 stages × 5 TP = 15 total TP
            assert run.aggregate_precision > 0
            assert isinstance(run.to_dict(), dict)

    def test_record_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = MetricsCollector(
                run_id="run-ckpt",
                sample_sha256="d" * 64,
                output_path=Path(tmpdir) / "telemetry.jsonl",
            )
            collector.start_stage("05-dynamic")
            collector.record_checkpoint("05-dynamic")
            sm = collector.get_stage("05-dynamic")
            assert sm is not None
            assert sm.checkpoint_triggered is True
