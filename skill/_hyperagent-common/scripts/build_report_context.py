#!/usr/bin/env python3
"""Build a compact Markdown briefing for the 08-report stage.

The report stage should synthesize from a small, validated digest rather than
pulling large upstream JSON artifacts directly into the model conversation.
This helper validates the available stage outputs, extracts the fields that map
onto the final Markdown report, writes a compact context artifact, and prints
that same compact briefing to stdout so the caller can pass it straight back to
an LLM as a bounded tool result.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STAGE_SPECS = (
    ("01-prepare-env", "01-prepare-env.json", "hyperagent-prepare-env/schema.json", True),
    ("02-static-pass1", "02-static-pass1.json", "hyperagent-static/schema.json", True),
    ("03-unpack", "03-unpack.json", "hyperagent-unpack/schema.json", False),
    ("04-static-pass2", "04-static-pass2.json", "hyperagent-static/schema.json", False),
    ("05-dynamic", "05-dynamic.json", "hyperagent-dynamic/schema.json", True),
    ("06-intel", "06-intel.json", "hyperagent-intel/schema.json", False),
    ("07-deepdive", "07-deepdive.json", "hyperagent-deepdive/schema.json", True),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact Markdown briefing for HyperAgent 08-report."
    )
    parser.add_argument(
        "report_dir",
        type=Path,
        help="reports/<sha256> directory containing upstream stage artifacts.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional output path for the generated compact Markdown briefing.",
    )
    return parser.parse_args()


def skills_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_payload(payload_path: Path, schema_path: Path) -> dict[str, Any]:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency issue path
        raise RuntimeError("Install jsonschema to validate report-context inputs.") from exc

    payload = read_json(payload_path)
    schema = read_json(schema_path)
    jsonschema.Draft202012Validator(schema).validate(payload)
    return payload


def load_stage_payloads(report_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    root = skills_root()
    loaded: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for stage_id, filename, schema_rel, _required in STAGE_SPECS:
        payload_path = report_dir / filename
        if not payload_path.exists():
            missing.append(filename)
            continue
        loaded[stage_id] = validate_payload(payload_path, root / schema_rel)

    return loaded, missing


def missing_line(filename: str) -> str:
    if filename == "07-deepdive.json":
        return "07-deepdive.json is missing — authoritative verdict and claim-policy guidance are unavailable, so the final report must be explicitly incomplete."
    if filename == "05-dynamic.json":
        return "05-dynamic.json is missing — treat dynamic behavior, IOC, and runtime sections as limited or not observed in this run profile."
    if filename == "06-intel.json":
        return "06-intel.json is missing — public-source enrichment is unavailable; do not infer it from local evidence."
    return f"{filename} is missing — state the limitation instead of inventing replacement findings."


def loaded_filenames(payloads: dict[str, dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for stage_id, filename, _schema_rel, _required in STAGE_SPECS:
        if stage_id in payloads:
            names.append(filename)
    return names


def render_missing_items(missing: list[str]) -> list[str]:
    return [missing_line(name) for name in missing]


def text_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        text = " ".join(value.strip().split())
        return text or None
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def short_text(value: Any, limit: int = 220) -> str:
    text = text_or_none(value) or "Not available."
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def confidence_text(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return None


def add_section(lines: list[str], title: str) -> None:
    lines.extend(["", f"## {title}"])


def add_bullets(lines: list[str], items: list[str], *, limit: int | None = None) -> None:
    filtered = [item for item in items if item]
    if not filtered:
        lines.append("- Not available.")
        return
    shown = filtered if limit is None else filtered[:limit]
    for item in shown:
        lines.append(f"- {item}")
    if limit is not None and len(filtered) > limit:
        lines.append(f"- ... {len(filtered) - limit} additional items omitted from the compact context.")


def source_label(entry: dict[str, Any]) -> str:
    stage = text_or_none(entry.get("stage")) or "unknown-stage"
    artifact = text_or_none(entry.get("artifact"))
    location = text_or_none(entry.get("location"))
    pieces = [stage]
    if artifact:
        pieces.append(artifact)
    if location:
        pieces.append(location)
    return " / ".join(pieces)


def finding_line(entry: dict[str, Any], *, include_disposition: bool = False) -> str:
    title = text_or_none(entry.get("title")) or text_or_none(entry.get("claim")) or text_or_none(entry.get("statement")) or text_or_none(entry.get("problem")) or "Untitled"
    status = text_or_none(entry.get("final_status")) or text_or_none(entry.get("status"))
    confidence = confidence_text(entry.get("final_confidence") if "final_confidence" in entry else entry.get("confidence"))
    summary = (
        text_or_none(entry.get("summary"))
        or text_or_none(entry.get("description"))
        or text_or_none(entry.get("technical_summary"))
        or text_or_none(entry.get("reasoning"))
        or text_or_none(entry.get("analysis"))
        or text_or_none(entry.get("resolution"))
        or text_or_none(entry.get("recommended_action"))
        or text_or_none(entry.get("evidence_gap"))
    )
    notes: list[str] = []
    if status:
        notes.append(status)
    if confidence:
        notes.append(f"confidence {confidence}")
    if include_disposition:
        disposition = text_or_none(entry.get("report_disposition"))
        if disposition:
            notes.append(disposition)
    prefix = f"[{text_or_none(entry.get('id'))}] " if text_or_none(entry.get("id")) else ""
    if summary:
        if notes:
            return f"{prefix}{title} — {short_text(summary)} ({', '.join(notes)})"
        return f"{prefix}{title} — {short_text(summary)}"
    if notes:
        return f"{prefix}{title} ({', '.join(notes)})"
    return f"{prefix}{title}"


def behavior_line(entry: dict[str, Any]) -> str:
    behavior_type = text_or_none(entry.get("type")) or "behavior"
    description = text_or_none(entry.get("description"))
    status = text_or_none(entry.get("status"))
    confidence = confidence_text(entry.get("confidence"))
    details = [item for item in (status, f"confidence {confidence}" if confidence else None) if item]
    if description:
        suffix = f" — {short_text(description)}"
    else:
        suffix = ""
    if details:
        return f"{behavior_type}{suffix} ({', '.join(details)})"
    return f"{behavior_type}{suffix}"


def artifact_line(entry: dict[str, Any]) -> str:
    artifact_type = text_or_none(entry.get("type")) or "artifact"
    path = text_or_none(entry.get("path")) or "path unavailable"
    sha256 = text_or_none(entry.get("sha256"))
    validation = text_or_none(entry.get("validation_status"))
    context = text_or_none(entry.get("context"))
    extras = [item for item in (validation, sha256, short_text(context, 120) if context else None) if item]
    if extras:
        return f"{artifact_type}: {path} ({'; '.join(extras)})"
    return f"{artifact_type}: {path}"


def action_line(entry: dict[str, Any]) -> str:
    priority = entry.get("priority")
    target = text_or_none(entry.get("target")) or "unspecified target"
    action = text_or_none(entry.get("recommended_action")) or text_or_none(entry.get("action")) or "unspecified action"
    reason = text_or_none(entry.get("reason"))
    success = text_or_none(entry.get("success_criteria"))
    prefix = f"P{priority}: " if isinstance(priority, int) else ""
    parts = [f"{prefix}{target} — {short_text(action, 180)}"]
    if reason:
        parts.append(f"reason: {short_text(reason, 140)}")
    if success:
        parts.append(f"done when: {short_text(success, 140)}")
    return "; ".join(parts)


def render_report_context(report_dir: Path, payloads: dict[str, dict[str, Any]], missing: list[str]) -> str:
    prepare = payloads.get("01-prepare-env", {})
    static1 = payloads.get("02-static-pass1", {})
    unpack = payloads.get("03-unpack", {})
    static2 = payloads.get("04-static-pass2", {})
    dynamic = payloads.get("05-dynamic", {})
    intel = payloads.get("06-intel", {})
    deepdive = payloads.get("07-deepdive", {})

    sample_prepare = prepare.get("sample", {})
    sample_static = static1.get("sample", {})
    profile = static1.get("binary_profile", {})
    sample_dynamic = dynamic.get("sample", {})
    executive = deepdive.get("executive_assessment", {})
    claim_policy = deepdive.get("final_claim_policy", {})
    finding_reviews = deepdive.get("finding_reviews", [])
    contradictions = deepdive.get("contradictions", [])
    hypotheses = deepdive.get("hypotheses", [])
    root_causes = deepdive.get("root_cause_analysis", [])
    actions = sorted(
        deepdive.get("investigation_targets", []),
        key=lambda item: (item.get("priority", 99), text_or_none(item.get("id")) or ""),
    )

    confirmed_reviews = [
        finding_line(item, include_disposition=True)
        for item in finding_reviews
        if item.get("report_disposition") == "include_confirmed"
    ]
    caveated_reviews = [
        finding_line(item, include_disposition=True)
        for item in finding_reviews
        if item.get("report_disposition") == "include_with_caveat"
    ]
    rejected_reviews = [
        finding_line(item, include_disposition=True)
        for item in finding_reviews
        if item.get("report_disposition") == "exclude" or item.get("final_status") in {"contradicted", "rejected"}
    ]

    observed_behaviors = [
        behavior_line(item)
        for item in dynamic.get("behaviors", [])
        if item.get("status") in {"observed", "partial"}
    ]
    not_observed_behaviors = [
        behavior_line(item)
        for item in dynamic.get("behaviors", [])
        if item.get("status") == "not_observed"
    ]

    intel_claims = [
        finding_line(item)
        for item in intel.get("claim_checks", [])
        if item.get("report_use") in {"supporting_context", "caveat_only", "followup_only"}
    ]

    lines: list[str] = [
        "# Compact report context",
        "",
        "Use this compact briefing instead of reading raw stage JSON into the conversation.",
        "`07-deepdive.json` remains authoritative for verdicts and claim boundaries.",
        "Public-source intelligence is enrichment-only and must not widen claims beyond Deepdive.",
        "",
        "Validated source artifacts:",
    ]
    add_bullets(lines, [f"{name}" for name in loaded_filenames(payloads)])
    if missing:
        lines.append("")
        lines.append("Missing validated source artifacts:")
        add_bullets(lines, render_missing_items(missing), limit=8)

    add_section(lines, "Sample identity")
    add_bullets(
        lines,
        [
            f"File name: {text_or_none(sample_prepare.get('file_name')) or text_or_none(Path(text_or_none(sample_prepare.get('absolute_path')) or '').name) or 'unknown'}",
            f"Absolute path: {text_or_none(sample_prepare.get('absolute_path')) or text_or_none(sample_dynamic.get('target_path')) or 'unknown'}",
            f"SHA256: {text_or_none(sample_prepare.get('sha256')) or text_or_none(sample_static.get('original_sha256')) or 'unknown'}",
            f"Architecture: {text_or_none(profile.get('architecture')) or 'unknown'}",
            f"Original entry point: {text_or_none(profile.get('entry_point')) or 'unknown'}",
            f"Packing / protection: {text_or_none(profile.get('packer')) or 'not identified'}",
        ],
    )

    add_section(lines, "Environment and scope")
    readiness = prepare.get("readiness", {})
    add_bullets(
        lines,
        [
            f"Static readiness: {text_or_none((readiness.get('static') if isinstance(readiness, dict) else None)) or 'unknown'}",
            f"Dynamic readiness: {text_or_none((readiness.get('dynamic') if isinstance(readiness, dict) else None)) or 'unknown'}",
            f"Overall readiness: {text_or_none((readiness.get('overall') if isinstance(readiness, dict) else None)) or 'unknown'}",
            f"Prepare-env summary: {short_text(prepare.get('summary') or 'Environment stage does not expose a summary field; use readiness and blockers below.', 220)}",
        ],
    )
    blockers = [finding_line(item) for item in prepare.get("blockers", []) if isinstance(item, dict)]
    if blockers:
        lines.append("")
        lines.append("Blockers / limitations:")
        add_bullets(lines, blockers, limit=6)

    add_section(lines, "Packing and artifact recovery")
    unpack_decision = static1.get("unpack_decision", {})
    handoff = unpack.get("static_pass2_handoff", {})
    add_bullets(
        lines,
        [
            f"Static-pass1 summary: {short_text(static1.get('summary'))}",
            f"Unpack required: {unpack_decision.get('required') if isinstance(unpack_decision, dict) else 'unknown'}",
            f"Unpack strategy: {text_or_none(unpack_decision.get('strategy') if isinstance(unpack_decision, dict) else None) or 'unknown'}",
            f"Unpack stage summary: {short_text(unpack.get('summary')) if unpack else 'Unpack artifact not present.'}",
            f"Recovery status: {text_or_none(unpack.get('recovery_status')) or 'not available'}",
            f"Static-pass2 handoff recommended: {handoff.get('recommended') if isinstance(handoff, dict) else 'unknown'}",
            f"Candidate handoff artifact: {text_or_none(handoff.get('artifact_path') if isinstance(handoff, dict) else None) or 'not available'}",
            f"Candidate handoff entry: {text_or_none(handoff.get('candidate_entry') if isinstance(handoff, dict) else None) or 'not available'}",
        ],
    )
    recovery_artifacts = [artifact_line(item) for item in unpack.get("artifacts", []) if isinstance(item, dict)]
    if recovery_artifacts:
        lines.append("")
        lines.append("Recovered artifacts:")
        add_bullets(lines, recovery_artifacts, limit=6)

    add_section(lines, "Static evidence")
    add_bullets(
        lines,
        [
            f"Static-pass1 summary: {short_text(static1.get('summary'))}",
            f"Static-pass2 summary: {short_text(static2.get('summary')) if static2 else 'Static-pass2 artifact not present.'}",
        ],
    )
    static_findings = [finding_line(item) for item in static1.get("findings", []) if isinstance(item, dict)]
    static2_findings = [finding_line(item) for item in static2.get("findings", []) if isinstance(item, dict)]
    if static_findings:
        lines.append("")
        lines.append("Original-sample findings:")
        add_bullets(lines, static_findings, limit=8)
    if static2_findings:
        lines.append("")
        lines.append("Recovered-artifact findings:")
        add_bullets(lines, static2_findings, limit=8)

    add_section(lines, "Dynamic evidence")
    add_bullets(
        lines,
        [
            f"Dynamic summary: {short_text(dynamic.get('summary'))}",
            f"Runtime executed: {dynamic.get('runtime', {}).get('executed') if isinstance(dynamic.get('runtime'), dict) else 'unknown'}",
            f"Observation window: {text_or_none(dynamic.get('runtime', {}).get('observation_window') if isinstance(dynamic.get('runtime'), dict) else None) or 'unknown'}",
            f"Stop reason: {text_or_none(dynamic.get('runtime', {}).get('stop_reason') if isinstance(dynamic.get('runtime'), dict) else None) or 'unknown'}",
        ],
    )
    if observed_behaviors:
        lines.append("")
        lines.append("Observed behaviors:")
        add_bullets(lines, observed_behaviors, limit=8)
    if not_observed_behaviors:
        lines.append("")
        lines.append("Not observed during the run:")
        add_bullets(lines, not_observed_behaviors, limit=6)
    dynamic_artifacts = [artifact_line(item) for item in dynamic.get("artifacts", []) if isinstance(item, dict)]
    if dynamic_artifacts:
        lines.append("")
        lines.append("Dynamic-stage artifacts:")
        add_bullets(lines, dynamic_artifacts, limit=6)
    iocs = dynamic.get("iocs", {})
    lines.append("")
    lines.append("IOC snapshots:")
    add_bullets(
        lines,
        [
            f"Network: {', '.join(iocs.get('network', [])[:8]) or 'not observed'}",
            f"Host: {', '.join(iocs.get('host', [])[:8]) or 'not observed'}",
            f"Persistence: {', '.join(iocs.get('persistence', [])[:8]) or 'not observed'}",
        ],
    )
    dynamic_limitations = [short_text(item, 180) for item in dynamic.get("limitations", []) if text_or_none(item)]
    if dynamic_limitations:
        lines.append("")
        lines.append("Dynamic limitations:")
        add_bullets(lines, dynamic_limitations, limit=6)

    add_section(lines, "Deepdive conclusions (authoritative)")
    add_bullets(
        lines,
        [
            f"Verdict: {text_or_none(executive.get('verdict')) or 'unknown'}",
            f"Confidence: {confidence_text(executive.get('confidence')) or 'unknown'}",
            f"Technical summary: {short_text(executive.get('technical_summary'))}",
            f"Highest-value resolution: {short_text(executive.get('highest_value_resolution'), 180)}",
            f"Remaining decision point: {short_text(executive.get('remaining_decision_point'), 180)}",
        ],
    )
    lines.append("")
    lines.append("Confirmed report findings:")
    add_bullets(lines, confirmed_reviews, limit=10)
    lines.append("")
    lines.append("Findings that must keep caveats:")
    add_bullets(lines, caveated_reviews, limit=10)
    lines.append("")
    lines.append("Rejected / downgraded findings:")
    add_bullets(lines, rejected_reviews, limit=10)

    if contradictions:
        lines.append("")
        lines.append("Contradictions and reconciliations:")
        add_bullets(lines, [finding_line(item) for item in contradictions if isinstance(item, dict)], limit=8)
    if hypotheses:
        lines.append("")
        lines.append("Open / tested hypotheses:")
        add_bullets(lines, [finding_line(item) for item in hypotheses if isinstance(item, dict)], limit=8)
    if root_causes:
        lines.append("")
        lines.append("Root-cause analysis notes:")
        add_bullets(lines, [finding_line(item) for item in root_causes if isinstance(item, dict)], limit=6)

    lines.append("")
    lines.append("Final claim policy:")
    add_bullets(
        lines,
        [
            "Allowed claims: " + (", ".join(claim_policy.get("allowed_claims", [])[:8]) or "none listed"),
            "Caveated claims: " + (", ".join(claim_policy.get("caveated_claims", [])[:8]) or "none listed"),
            "Prohibited claims: " + (", ".join(claim_policy.get("prohibited_claims", [])[:8]) or "none listed"),
        ],
    )

    lines.append("")
    lines.append("Recommended follow-up actions:")
    add_bullets(lines, [action_line(item) for item in actions if isinstance(item, dict)], limit=8)

    deepdive_limitations = [short_text(item, 180) for item in deepdive.get("limitations", []) if text_or_none(item)]
    if deepdive_limitations:
        lines.append("")
        lines.append("Deepdive limitations:")
        add_bullets(lines, deepdive_limitations, limit=6)

    add_section(lines, "Intel digest (enrichment only)")
    if intel:
        matched = intel.get("ioc_correlation", {}).get("matched_local", []) if isinstance(intel.get("ioc_correlation"), dict) else []
        local_only = intel.get("ioc_correlation", {}).get("local_only_no_public_match", []) if isinstance(intel.get("ioc_correlation"), dict) else []
        external_only = intel.get("ioc_correlation", {}).get("external_only", []) if isinstance(intel.get("ioc_correlation"), dict) else []
        add_bullets(
            lines,
            [
                f"Intel summary: {short_text(intel.get('summary'))}",
                f"Provider queries: {len(intel.get('provider_queries', []))}",
                f"Claim checks carried for context: {len(intel_claims)}",
                f"IOC correlation counts — matched local: {len(matched)}, local-only: {len(local_only)}, external-only: {len(external_only)}",
                "Do not widen claims from this section. Only use it when Deepdive already carried the corroboration or caveat forward.",
            ],
        )
        if intel_claims:
            lines.append("")
            lines.append("Intel claim-check highlights:")
            add_bullets(lines, intel_claims, limit=6)
    else:
        add_bullets(
            lines,
            [
                "06-intel.json not present. Rely on Deepdive-carried public-source context only.",
                "Raw intel JSON is intentionally excluded from the report-stage context to avoid repeated large-file compaction.",
            ],
        )

    add_section(lines, "Source provenance cues")
    provenance_items: list[str] = []
    for item in dynamic.get("findings", [])[:4]:
        if isinstance(item, dict) and item.get("sources"):
            sources = [source_label(source) for source in item.get("sources", []) if isinstance(source, dict)]
            provenance_items.append(
                f"Dynamic {text_or_none(item.get('id')) or text_or_none(item.get('title')) or 'finding'} sources: {', '.join(sources) or 'unspecified'}"
            )
    for item in finding_reviews[:4]:
        if isinstance(item, dict) and item.get("original_claims"):
            claims = []
            for claim in item.get("original_claims", []):
                if isinstance(claim, dict):
                    stage = text_or_none(claim.get("stage")) or "unknown-stage"
                    finding_id = text_or_none(claim.get("finding_id")) or "no-finding-id"
                    claims.append(f"{stage}/{finding_id}")
            provenance_items.append(
                f"Deepdive {text_or_none(item.get('id')) or text_or_none(item.get('title')) or 'review'} traces back to: {', '.join(claims) or 'unspecified'}"
            )
    add_bullets(lines, provenance_items, limit=8)

    lines.extend([
        "",
        "## Rendering notes",
        "- Use the final Markdown report as the only human-facing artifact for this stage.",
        "- Do not introduce new findings beyond the validated context above.",
        "- If a required detail seems missing, prefer stating the limitation over widening the claim.",
    ])

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    report_dir = args.report_dir.expanduser().resolve()
    if not report_dir.is_dir():
        print(f"ERROR: report_dir is not a directory: {report_dir}", file=sys.stderr)
        return 2

    try:
        payloads, missing = load_stage_payloads(report_dir)
        context_text = render_report_context(report_dir, payloads, missing)
        output_path = args.output.expanduser().resolve() if args.output else report_dir / "08-report.context.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(context_text, encoding="utf-8")
        sys.stdout.write(context_text)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
