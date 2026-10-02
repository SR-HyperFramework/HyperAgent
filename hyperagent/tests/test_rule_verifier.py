"""Rule verifier tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hyperagent.tools.rule_verifier import RuleVerifier

FIXTURES = Path(__file__).parent / "fixtures" / "benign_reports"


def test_verify_jq_rule_passes_when_no_fixture_matches(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        assert cmd[0] == "jq"
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule('. | has("nonexistent_field")')

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_collects_matching_filenames(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout='"abc"\n', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is False
    assert result.fps == [
        str(FIXTURES / "report_a.json"),
        str(FIXTURES / "report_b.json"),
    ]


def test_generate_repair_prompt_includes_rule_and_false_positives():
    verifier = RuleVerifier(FIXTURES)
    fps = [str(FIXTURES / "report_a.json"), str(FIXTURES / "report_b.json")]

    prompt = verifier.generate_repair_prompt(".pe.imphash", fps)

    assert ".pe.imphash" in prompt
    assert fps[0] in prompt
    assert fps[1] in prompt


def test_verify_jq_rule_requires_existing_fixture_dir(tmp_path):
    verifier = RuleVerifier(tmp_path / "missing")

    with pytest.raises(FileNotFoundError):
        verifier.verify_jq_rule(".pe.imphash")


def test_verify_wrapper_delegates_to_jq_verifier(monkeypatch):
    monkeypatch.setattr(
        RuleVerifier,
        "verify_jq_rule",
        lambda self, rule: type("_Result", (), {"passed": True, "fps": []})(),
    )

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_raises_when_jq_is_missing(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        raise FileNotFoundError("jq")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    with pytest.raises(RuntimeError, match="jq executable not found"):
        verifier.verify_jq_rule(".pe.imphash")


def test_verify_jq_rule_raises_on_jq_failure(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="syntax error")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    with pytest.raises(RuntimeError, match="syntax error"):
        verifier.verify_jq_rule(".pe.imphash")


def test_verify_jq_rule_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES, timeout=12)
    with pytest.raises(RuntimeError, match="timed out after 12s"):
        verifier.verify_jq_rule(".pe.imphash")


def test_verify_jq_rule_treats_null_and_empty_as_non_matches(monkeypatch):
    outputs = iter(["null\n", "\n"])

    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_uses_custom_jq_binary(monkeypatch):
    seen = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        seen.append(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES, jq_bin="jq-custom")
    verifier.verify_jq_rule('. | has("nonexistent_field")')

    assert seen == ["jq-custom", "jq-custom"]


def test_verify_jq_rule_respects_fixture_sort_order(monkeypatch):
    seen_paths = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        seen_paths.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 0, stdout='"abc"\n', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    verifier.verify_jq_rule(".pe.imphash")

    assert seen_paths == [
        str(FIXTURES / "report_a.json"),
        str(FIXTURES / "report_b.json"),
    ]


def test_generate_repair_prompt_lists_each_false_positive_on_its_own_line():
    verifier = RuleVerifier(FIXTURES)
    fps = [str(FIXTURES / "report_a.json"), str(FIXTURES / "report_b.json")]

    prompt = verifier.generate_repair_prompt(".pe.imphash", fps)

    assert f"- {fps[0]}" in prompt
    assert f"- {fps[1]}" in prompt
    assert "False-positive files:" in prompt


def test_verify_jq_rule_returns_no_false_positives_for_empty_fixture_dir(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        raise AssertionError("subprocess.run should not be called for an empty fixture dir")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(tmp_path)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_only_scans_json_files(tmp_path, monkeypatch):
    (tmp_path / "report.json").write_text('{"pe": {"imphash": "abc"}}', encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("ignored", encoding="utf-8")
    seen = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        seen.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(tmp_path)
    verifier.verify_jq_rule(".pe.imphash")

    assert seen == [str(tmp_path / "report.json")]


def test_verify_jq_rule_treats_false_literal_as_non_match(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout="false", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_treats_truthy_output_as_match(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is False
    assert result.fps == [
        str(FIXTURES / "report_a.json"),
        str(FIXTURES / "report_b.json"),
    ]


def test_verify_jq_rule_preserves_timeout_configuration():
    verifier = RuleVerifier(FIXTURES, timeout=99)
    assert verifier.timeout == 99


def test_verify_jq_rule_preserves_benign_reports_dir():
    verifier = RuleVerifier(FIXTURES)
    assert verifier.benign_reports_dir == FIXTURES


def test_verify_jq_rule_preserves_jq_binary():
    verifier = RuleVerifier(FIXTURES, jq_bin="jq-custom")
    assert verifier.jq_bin == "jq-custom"


def test_generate_repair_prompt_mentions_benign_reports():
    verifier = RuleVerifier(FIXTURES)
    prompt = verifier.generate_repair_prompt(".pe.imphash", [])
    assert "benign sandbox reports" in prompt
    assert "Revise it" in prompt


def test_verify_jq_rule_returns_verification_result_shape(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert hasattr(result, "passed")
    assert hasattr(result, "fps")
    assert isinstance(result.fps, list)


def test_verify_delegates_exact_rule_text(monkeypatch):
    captured = {}

    def fake_verify(self, rule):
        captured["rule"] = rule
        return type("_Result", (), {"passed": True, "fps": []})()

    monkeypatch.setattr(RuleVerifier, "verify_jq_rule", fake_verify)

    verifier = RuleVerifier(FIXTURES)
    verifier.verify(".foo")

    assert captured["rule"] == ".foo"


def test_verify_jq_rule_uses_report_path_strings(monkeypatch):
    paths = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        paths.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    verifier.verify_jq_rule(".pe.imphash")

    assert all(isinstance(path, str) for path in paths)


def test_verify_jq_rule_keeps_all_false_positive_paths(monkeypatch):
    outputs = iter(['"abc"\n', '"def"\n'])

    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.fps == [
        str(FIXTURES / "report_a.json"),
        str(FIXTURES / "report_b.json"),
    ]


def test_verify_jq_rule_returns_passed_false_when_any_match(monkeypatch):
    outputs = iter(["false\n", '"abc"\n'])

    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is False
    assert result.fps == [str(FIXTURES / "report_b.json")]


def test_verify_jq_rule_returns_passed_true_when_no_match(monkeypatch):
    outputs = iter(["null\n", "false\n"])

    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_generate_repair_prompt_handles_empty_false_positive_list():
    verifier = RuleVerifier(FIXTURES)
    prompt = verifier.generate_repair_prompt(".pe.imphash", [])
    assert "Rule:" in prompt
    assert ".pe.imphash" in prompt
    assert "False-positive files:" in prompt


def test_verify_jq_rule_uses_configured_timeout(monkeypatch):
    seen = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        seen.append(timeout)
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES, timeout=7)
    verifier.verify_jq_rule(".pe.imphash")

    assert seen == [7, 7]


def test_verify_jq_rule_does_not_treat_whitespace_only_output_as_match(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout="  \n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is True
    assert result.fps == []


def test_verify_jq_rule_ignores_nonzero_with_stdout_by_raising(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 4, stdout="partial", stderr="bad filter")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    with pytest.raises(RuntimeError, match="bad filter"):
        verifier.verify_jq_rule(".pe.imphash")


def test_verify_jq_rule_handles_single_match_among_multiple(monkeypatch):
    outputs = iter(["false\n", '"abc"\n'])

    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.passed is False
    assert result.fps == [str(FIXTURES / "report_b.json")]


def test_generate_repair_prompt_contains_original_guidance_phrase():
    verifier = RuleVerifier(FIXTURES)
    prompt = verifier.generate_repair_prompt(".pe.imphash", [str(FIXTURES / "report_a.json")])
    assert "preserving the intended malicious detection logic" in prompt


def test_verify_jq_rule_reports_sorted_false_positive_paths(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 0, stdout='"abc"\n', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    result = verifier.verify_jq_rule(".pe.imphash")

    assert result.fps == sorted(result.fps)


def test_verify_jq_rule_raises_with_report_path_in_message(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="broken")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES)
    with pytest.raises(RuntimeError) as exc:
        verifier.verify_jq_rule(".pe.imphash")

    assert str(FIXTURES / "report_a.json") in str(exc.value)


def test_verify_jq_rule_raises_with_timeout_path_in_message(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = RuleVerifier(FIXTURES, timeout=5)
    with pytest.raises(RuntimeError) as exc:
        verifier.verify_jq_rule(".pe.imphash")

    assert str(FIXTURES / "report_a.json") in str(exc.value)
