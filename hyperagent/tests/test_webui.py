"""Smoke tests for the read-only web UI."""
from __future__ import annotations

import json
from pathlib import Path

from webui.app import create_app


SHA = "a" * 64
BROKEN_SHA = "b" * 64


def _write_summary(root: Path, sha256: str = SHA) -> None:
    run_dir = root / sha256
    run_dir.mkdir(parents=True)
    summary = {
        "schema_version": "1.0",
        "stage": "summary",
        "sample": {
            "sha256": sha256,
            "file_name": "sample.exe",
            "absolute_path": "C:/analysis/sample.exe",
            "architecture": "x86",
            "packing_or_protection": "No strong packing evidence was confirmed.",
        },
        "status": "completed",
        "executive_summary": {
            "verdict": "suspicious",
            "confidence": 0.56,
            "confidence_label": "medium",
            "risk_level": "medium",
            "one_sentence_summary": "The sample behaves like a staged loader, but impact is unresolved.",
            "plain_language_assessment": "The run found loader-style behavior, but did not prove final payload execution.",
            "remaining_decision_point": "Validate the unresolved transfer target.",
        },
        "confirmed_findings": [
            {
                "id": "summary.loader",
                "title": "Loader-style staging was supported",
                "summary": "The summary supports staged behavior.",
                "source_refs": ["07-deepdive.json:final_claim_policy.allowed_claims"],
            }
        ],
        "findings_with_caveats": [
            {
                "id": "summary.payload.unresolved",
                "title": "Payload behavior remains unresolved",
                "summary": "A later payload step may exist.",
                "caveat": "Do not claim payload execution yet.",
                "source_refs": ["07-deepdive.json:final_claim_policy.caveated_claims"],
            }
        ],
        "not_supported_claims": [
            {
                "id": "summary.ransomware.unsupported",
                "claim": "The sample is confirmed ransomware.",
                "reason": "The evidence did not support ransomware behavior.",
                "source_refs": ["07-deepdive.json:final_claim_policy.prohibited_claims"],
            }
        ],
        "classification": {
            "malware_type": "loader",
            "malware_family": None,
            "family_status": "unconfirmed",
            "overall_assessment": "Best described as a suspicious loader-like artifact.",
        },
        "confirmed_iocs": {
            "network": [],
            "host": [],
            "persistence": [],
        },
        "recommended_actions": [
            {
                "id": "action.validate-target",
                "priority": 1,
                "target": "Transfer target",
                "action": "Validate the unresolved transfer target.",
                "reason": "It is the highest-value remaining question.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            }
        ],
        "limitations": [
            "The run did not prove final payload execution.",
        ],
        "upstream_inputs": ["07-deepdive.json"],
    }
    (run_dir / "09-summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_index_renders_readable_run_cards(tmp_path: Path):
    _write_summary(tmp_path)
    client = create_app(tmp_path).test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "run-card" in html
    assert "The sample behaves like a staged loader" in html
    assert "readable run cards" not in html
    assert "grid" not in html


def test_detail_renders_dossier_sections_without_tabs(tmp_path: Path):
    _write_summary(tmp_path)
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Plain-language summary" in html
    assert "Confirmed findings" in html
    assert "Findings with caveats" in html
    assert "Not supported claims" in html
    assert "What this run could not establish" in html
    assert "role=\"tab\"" not in html


def test_recommended_actions_sort_lowest_priority_number_first(tmp_path: Path):
    _write_summary(tmp_path)
    data = json.loads((tmp_path / SHA / "09-summary.json").read_text(encoding="utf-8"))
    data["recommended_actions"].extend(
        [
            {
                "id": "action.lower-priority",
                "priority": 5,
                "target": "Later work",
                "action": "Do this later.",
                "reason": "Lower priority than the main validation target.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            },
            {
                "id": "action.mid-priority",
                "priority": 3,
                "target": "Middle work",
                "action": "Do this in the middle.",
                "reason": "Medium priority follow-up.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            },
        ]
    )
    (tmp_path / SHA / "09-summary.json").write_text(json.dumps(data), encoding="utf-8")
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.index("P1") < html.index("P3") < html.index("P5")


def test_unreadable_summary_renders_parse_error(tmp_path: Path):
    run_dir = tmp_path / BROKEN_SHA
    run_dir.mkdir()
    (run_dir / "09-summary.json").write_text("not json", encoding="utf-8")
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{BROKEN_SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Summary unreadable" in html
    assert "Invalid JSON" in html


def test_invalid_sha_uses_error_template(tmp_path: Path):
    client = create_app(tmp_path).test_client()

    response = client.get("/runs/not-a-sha")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Nothing here" in html
    assert "not a valid SHA256" in html
