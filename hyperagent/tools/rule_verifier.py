"""Rule verification helpers for benign-corpus false-positive checks."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerificationResult:
    """Result of checking a generated rule against benign reports."""

    passed: bool
    fps: list[str]


class RuleVerifier:
    """Validate generated jq rules against a benign sandbox-report corpus."""

    def __init__(self, benign_reports_dir: Path, *, jq_bin: str = "jq", timeout: int = 30) -> None:
        self.benign_reports_dir = Path(benign_reports_dir)
        self.jq_bin = jq_bin
        self.timeout = timeout

    def verify_jq_rule(self, jq_rule: str) -> VerificationResult:
        """Return whether *jq_rule* avoids matching every benign JSON report."""
        if not self.benign_reports_dir.is_dir():
            raise FileNotFoundError(f"Benign reports directory not found: {self.benign_reports_dir}")

        fps: list[str] = []
        for report_path in sorted(self.benign_reports_dir.glob("*.json")):
            if self._matches_report(jq_rule, report_path):
                fps.append(str(report_path))
        return VerificationResult(passed=not fps, fps=fps)

    def verify(self, jq_rule: str) -> VerificationResult:
        """Compatibility wrapper for future engine-agnostic verifier integration."""
        return self.verify_jq_rule(jq_rule)

    def generate_repair_prompt(self, rule: str, fps: list[str]) -> str:
        """Tell the LLM how to revise a rule that hit benign reports."""
        lines = [
            "The generated jq rule produced false positives on benign sandbox reports.",
            "Revise it so it no longer matches these benign files while preserving the intended malicious detection logic.",
            "",
            "Rule:",
            rule,
            "",
            "False-positive files:",
        ]
        lines.extend(f"- {fp}" for fp in fps)
        return "\n".join(lines)

    def _matches_report(self, jq_rule: str, report_path: Path) -> bool:
        try:
            completed = subprocess.run(
                [self.jq_bin, jq_rule, str(report_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"jq executable not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"jq timed out after {self.timeout}s while checking {report_path}"
            ) from exc

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown jq failure"
            raise RuntimeError(f"jq failed for {report_path}: {stderr}")

        output = completed.stdout.strip()
        return bool(output) and output not in {"null", "false"}
