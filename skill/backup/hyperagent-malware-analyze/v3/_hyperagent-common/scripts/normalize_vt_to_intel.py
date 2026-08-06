#!/usr/bin/env python3
"""Normalize VirusTotal file JSON into a HyperAgent 06-intel.json-shaped document.

Expected inputs are the JSON files produced by fetch_vt_file_report.py for:
- --endpoint file_info
- --endpoint behaviour_summary

An optional local-context JSON can provide upstream mapping hints:
{
  "sample_sha256": "<64-hex>",
  "upstream_inputs": ["02-static-pass1.json", "05-dynamic.json"],
  "local_iocs": [
    {
      "id": "ioc.network.url",
      "category": "network",
      "value": "http://update.example.invalid/gate",
      "upstream_evidence_ids": ["dyn.ev.network-1"],
      "notes": "Observed during dynamic execution."
    }
  ],
  "claims": [
    {
      "id": "cc.network-loader-url",
      "claim_text": "The sample reaches an outbound update URL during execution.",
      "related_stage": "dynamic",
      "related_finding_ids": ["network.http-beacon"],
      "indicator_values": ["http://update.example.invalid/gate"],
      "label_values": ["mediyes"],
      "conflict_label_values": ["benign"],
      "report_use": "supporting_context"
    }
  ]
}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

FILE_INFO_DOCS_URL = "https://docs.virustotal.com/reference/file-info"
BEHAVIOUR_SUMMARY_DOCS_URL = "https://docs.virustotal.com/reference/file-all-behaviours-summary"


def default_schema_path() -> Path:
    configured = os.environ.get("HYPERAGENT_SKILLS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve() / "hyperagent-intel" / "schema.json"
    return Path(__file__).resolve().parents[2] / "hyperagent-intel" / "schema.json"


DEFAULT_SCHEMA_PATH = default_schema_path()
ALLOWED_CATEGORIES = {"network", "host", "persistence", "other"}
PERSISTENCE_MARKERS = (
    "\\currentversion\\run",
    "\\currentversion\\runonce",
    "\\services\\",
    "\\runservices",
    "startup",
    "\\winlogon",
    "\\taskcache\\tasks",
    "\\taskcache\\tree",
)
IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize VirusTotal file_info and behaviour_summary JSON into a HyperAgent intel-stage document."
    )
    parser.add_argument(
        "--file-info",
        type=Path,
        help="JSON from fetch_vt_file_report.py --endpoint file_info.",
    )
    parser.add_argument(
        "--behaviour-summary",
        type=Path,
        help="JSON from fetch_vt_file_report.py --endpoint behaviour_summary.",
    )
    parser.add_argument(
        "--local-context",
        type=Path,
        help="Optional JSON mapping local claims and IOCs to VT data.",
    )
    parser.add_argument(
        "--sample-sha256",
        help="Override or supply the original sample SHA256 when it cannot be inferred from the inputs.",
    )
    parser.add_argument(
        "--upstream-input",
        action="append",
        default=[],
        help="Upstream stage filename to include in upstream_inputs. Can be passed multiple times.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the generated payload against schema.json before emitting it.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help="Schema path used when --validate is set.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the normalized JSON to a file instead of stdout.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level for emitted output.",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dict(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def ensure_list(value: Any, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return value


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def slugify(value: str, fallback: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or fallback


def looks_like_sha256(value: str | None) -> bool:
    return bool(value and SHA256_RE.fullmatch(value.strip()))


def classify_hash(value: str | None) -> str:
    if not value:
        return "other"
    text = value.strip()
    if len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return "sha256"
    if len(text) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return "sha1"
    if len(text) == 32 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return "md5"
    return "other"


def source_meta(raw: dict[str, Any], default_resource: str, default_docs_url: str) -> dict[str, Any]:
    query = ensure_dict(raw.get("query"), f"{default_resource}.query") if "query" in raw else {}
    is_error = raw.get("status") == "error" and isinstance(raw.get("error"), dict)
    response = raw.get("response", raw)
    return {
        "resource": raw.get("resource") or default_resource,
        "docs_url": raw.get("docs_url") or default_docs_url,
        "endpoint": raw.get("endpoint"),
        "query_id": query.get("id"),
        "error": raw.get("error") if is_error else None,
        "response": ensure_dict(response, f"{default_resource}.response"),
    }


def response_data(source: dict[str, Any]) -> dict[str, Any]:
    return ensure_dict(source["response"].get("data"), f"{source['resource']}.data")


def file_info_details(source: dict[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return {}
    data = response_data(source)
    attributes = ensure_dict(data.get("attributes"), "file_info.attributes")
    return {
        "sample_id": data.get("id"),
        "self_link": ensure_dict(data.get("links"), "file_info.links").get("self"),
        "meaningful_name": attributes.get("meaningful_name"),
        "popular_threat_classification": ensure_dict(
            attributes.get("popular_threat_classification"),
            "file_info.popular_threat_classification",
        ),
    }


def behaviour_summary_details(source: dict[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return {}
    data = response_data(source)
    if isinstance(data.get("attributes"), dict):
        attributes = ensure_dict(data.get("attributes"), "behaviour_summary.attributes")
        self_link = ensure_dict(data.get("links"), "behaviour_summary.links").get("self")
    else:
        attributes = data
        self_link = ensure_dict(data.get("links"), "behaviour_summary.links") .get("self") if "links" in data else None
    return {
        "attributes": attributes,
        "self_link": self_link,
    }


def first_string(items: list[str]) -> str | None:
    for item in items:
        if item:
            return item
    return None


def resolve_sample_sha256(
    file_info: dict[str, Any],
    behaviour_source: dict[str, Any] | None,
    local_context: dict[str, Any],
    explicit: str | None,
) -> str:
    candidates: list[str] = []
    for value in (
        explicit,
        local_context.get("sample_sha256"),
        file_info.get("sample_id"),
        behaviour_source.get("query_id") if behaviour_source else None,
    ):
        if isinstance(value, str) and looks_like_sha256(value):
            candidates.append(value.strip().lower())
    unique = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    if not unique:
        raise ValueError(
            "Could not determine a canonical sample SHA256. Supply --sample-sha256, a file_info response, or local_context.sample_sha256."
        )
    if len(unique) > 1:
        raise ValueError(f"Conflicting sample SHA256 candidates found: {', '.join(unique)}")
    return unique[0]


def provider_query_for_file_info(source: dict[str, Any], details: dict[str, Any], sample_sha256: str) -> dict[str, Any]:
    query_value = source.get("query_id") or sample_sha256
    if source.get("error"):
        result = "error"
        matched_identity = None
        notes = f"VirusTotal file_info input contained an error payload: {source['error'].get('kind', 'unknown')}"
    else:
        result = "match"
        matched_identity = details.get("meaningful_name") or sample_sha256
        notes = "VirusTotal returned a file report for the queried sample."
    reference = source.get("endpoint") or details.get("self_link") or f"https://www.virustotal.com/api/v3/files/{sample_sha256}"
    return {
        "id": "pq.virustotal.file-info",
        "provider": "virustotal",
        "query_scope": "original_sample",
        "query_type": classify_hash(query_value),
        "query_value": query_value,
        "result": result,
        "matched_identity": matched_identity,
        "reference": reference,
        "notes": notes,
    }


def provider_query_for_behaviour_summary(source: dict[str, Any], details: dict[str, Any], sample_sha256: str) -> dict[str, Any]:
    query_value = source.get("query_id") or sample_sha256
    if source.get("error"):
        result = "error"
        matched_identity = None
        notes = f"VirusTotal behaviour_summary input contained an error payload: {source['error'].get('kind', 'unknown')}"
    else:
        result = "match"
        matched_identity = "Merged behaviour summary"
        notes = "VirusTotal returned a merged behaviour summary across available sandboxes for the sample."
    reference = source.get("endpoint") or details.get("self_link") or f"https://www.virustotal.com/api/v3/files/{sample_sha256}/behaviour_summary"
    return {
        "id": "pq.virustotal.behaviour-summary",
        "provider": "virustotal",
        "query_scope": "original_sample",
        "query_type": classify_hash(query_value),
        "query_value": query_value,
        "result": result,
        "matched_identity": matched_identity,
        "reference": reference,
        "notes": notes,
    }


def add_candidate(
    store: dict[tuple[str, str], dict[str, Any]],
    candidate_type: str,
    value: str,
    provider_query_ids: list[str],
    confidence: float,
    usage: str,
    notes: str,
) -> None:
    text = value.strip()
    if not text:
        return
    key = (candidate_type, normalize_text(text))
    if key not in store:
        store[key] = {
            "id": f"en.{candidate_type}.{slugify(text, 'item')}",
            "type": candidate_type,
            "value": text,
            "provider_query_ids": list(dict.fromkeys(provider_query_ids)),
            "confidence": max(0.0, min(1.0, confidence)),
            "usage": usage,
            "notes": notes,
        }
        return
    existing = store[key]
    existing["provider_query_ids"] = list(dict.fromkeys(existing["provider_query_ids"] + provider_query_ids))
    existing["confidence"] = max(existing["confidence"], max(0.0, min(1.0, confidence)))
    if notes and notes not in existing["notes"]:
        existing["notes"] = f"{existing['notes']} {notes}".strip()


def add_label_entry(index: dict[str, dict[str, Any]], value: str, provider_query_id: str, source: str) -> None:
    text = value.strip()
    if not text:
        return
    key = normalize_text(text)
    if key not in index:
        index[key] = {
            "value": text,
            "provider_query_ids": [provider_query_id],
            "sources": [source],
        }
        return
    existing = index[key]
    if provider_query_id not in existing["provider_query_ids"]:
        existing["provider_query_ids"].append(provider_query_id)
    if source not in existing["sources"]:
        existing["sources"].append(source)


def build_enrichment_and_labels(
    file_info: dict[str, Any],
    behaviour: dict[str, Any],
    provider_query_ids: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    label_index: dict[str, dict[str, Any]] = {}

    file_info_query_id = provider_query_ids.get("file_info")
    behaviour_query_id = provider_query_ids.get("behaviour_summary")

    if file_info_query_id:
        self_link = file_info.get("self_link")
        if self_link:
            add_candidate(
                candidates,
                "public_report",
                self_link,
                [file_info_query_id],
                0.85,
                "context_only",
                "VirusTotal file report reference.",
            )

        ptc = ensure_dict(file_info.get("popular_threat_classification"), "popular_threat_classification")
        suggested = ptc.get("suggested_threat_label")
        if isinstance(suggested, str) and suggested.strip():
            category_part, _, label_part = suggested.partition(".")
            if category_part and label_part:
                add_candidate(
                    candidates,
                    "malware_type",
                    category_part,
                    [file_info_query_id],
                    0.65,
                    "needs_local_confirmation",
                    "Derived from VirusTotal suggested_threat_label.",
                )
                add_label_entry(label_index, category_part, file_info_query_id, "suggested_threat_label")
                add_candidate(
                    candidates,
                    "family_label",
                    label_part,
                    [file_info_query_id],
                    0.58,
                    "needs_local_confirmation",
                    "Derived from VirusTotal suggested_threat_label.",
                )
                add_label_entry(label_index, label_part, file_info_query_id, "suggested_threat_label")
            else:
                add_candidate(
                    candidates,
                    "family_label",
                    suggested,
                    [file_info_query_id],
                    0.58,
                    "needs_local_confirmation",
                    "VirusTotal suggested threat label.",
                )
                add_label_entry(label_index, suggested, file_info_query_id, "suggested_threat_label")

        for item in ensure_list(ptc.get("popular_threat_name"), "popular_threat_name"):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            count = item.get("count")
            if not isinstance(value, str) or not value.strip():
                continue
            confidence = 0.35
            if isinstance(count, (int, float)):
                confidence = min(0.9, 0.35 + (float(count) / 50.0))
            add_candidate(
                candidates,
                "family_label",
                value,
                [file_info_query_id],
                confidence,
                "needs_local_confirmation",
                "VirusTotal popular threat name.",
            )
            add_label_entry(label_index, value, file_info_query_id, "popular_threat_name")

        for item in ensure_list(ptc.get("popular_threat_category"), "popular_threat_category"):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            count = item.get("count")
            if not isinstance(value, str) or not value.strip():
                continue
            confidence = 0.45
            if isinstance(count, (int, float)):
                confidence = min(0.9, 0.40 + (float(count) / 60.0))
            add_candidate(
                candidates,
                "malware_type",
                value,
                [file_info_query_id],
                confidence,
                "needs_local_confirmation",
                "VirusTotal popular threat category.",
            )
            add_label_entry(label_index, value, file_info_query_id, "popular_threat_category")

    if behaviour_query_id:
        attributes = ensure_dict(behaviour.get("attributes"), "behaviour.attributes")
        for verdict in ensure_list(attributes.get("verdicts"), "behaviour.verdicts"):
            if isinstance(verdict, str) and verdict.strip():
                add_candidate(
                    candidates,
                    "sandbox_verdict",
                    verdict,
                    [behaviour_query_id],
                    0.6,
                    "context_only",
                    "VirusTotal merged sandbox verdict.",
                )
                add_label_entry(label_index, verdict, behaviour_query_id, "verdicts")

        for tag in ensure_list(attributes.get("tags"), "behaviour.tags"):
            if isinstance(tag, str) and tag.strip():
                add_candidate(
                    candidates,
                    "behavior_tag",
                    tag,
                    [behaviour_query_id],
                    0.5,
                    "context_only",
                    "VirusTotal behaviour summary tag.",
                )
                add_label_entry(label_index, tag, behaviour_query_id, "tags")

    ordered = sorted(candidates.values(), key=lambda item: item["id"])
    return ordered, label_index


def add_external_observation(
    store: dict[str, dict[str, Any]],
    category: str,
    value: str,
    source_field: str,
) -> None:
    text = value.strip()
    if not text:
        return
    normalized = normalize_text(text)
    if normalized not in store:
        store[normalized] = {
            "category": category,
            "value": text,
            "source_fields": [source_field],
        }
        return
    existing = store[normalized]
    if source_field not in existing["source_fields"]:
        existing["source_fields"].append(source_field)


def add_strings_from_sequence(store: dict[str, dict[str, Any]], category: str, source_field: str, value: Any) -> None:
    if isinstance(value, str):
        add_external_observation(store, category, value, source_field)
        return
    if isinstance(value, list):
        for item in value:
            add_strings_from_sequence(store, category, source_field, item)


def walk_network_values(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        results.append(value)
    elif isinstance(value, list):
        for item in value:
            results.extend(walk_network_values(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"url", "hostname", "host", "domain", "sni", "ip", "dest_ip", "src_ip", "destination_ip", "ip_address"}:
                results.extend(walk_network_values(item))
            else:
                results.extend(walk_network_values(item))
    return results


def is_persistence_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PERSISTENCE_MARKERS)


def build_external_observations(behaviour: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    attributes = ensure_dict(behaviour.get("attributes"), "behaviour.attributes")

    for field in ("dns_lookups", "ja3_digests"):
        add_strings_from_sequence(observations, "network", field, attributes.get(field))

    for field in ("mutexes_created", "mutexes_opened"):
        add_strings_from_sequence(observations, "host", field, attributes.get(field))

    for field in ("services_created", "services_started"):
        add_strings_from_sequence(observations, "persistence", field, attributes.get(field))

    for field in ("registry_keys_opened", "registry_keys_deleted"):
        for value in ensure_list(attributes.get(field), field):
            if not isinstance(value, str):
                continue
            category = "persistence" if is_persistence_value(value) else "host"
            add_external_observation(observations, category, value, field)

    for item in ensure_list(attributes.get("registry_keys_set"), "registry_keys_set"):
        if isinstance(item, dict):
            key = item.get("key")
            if isinstance(key, str):
                category = "persistence" if is_persistence_value(key) else "host"
                add_external_observation(observations, category, key, "registry_keys_set")

    for field in ("http_conversations", "ids_alerts", "ip_traffic", "tls"):
        for value in walk_network_values(attributes.get(field)):
            add_external_observation(observations, "network", value, field)

    return observations


def normalize_category(value: Any) -> str:
    if isinstance(value, str) and value in ALLOWED_CATEGORIES:
        return value
    return "other"


def build_ioc_correlation(
    local_context: dict[str, Any],
    external_observations: dict[str, dict[str, Any]],
    provider_query_ids: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    matched_local: list[dict[str, Any]] = []
    local_only: list[dict[str, Any]] = []
    external_only: list[dict[str, Any]] = []
    consumed_external: set[str] = set()

    behaviour_query_id = provider_query_ids.get("behaviour_summary")

    for index, item in enumerate(ensure_list(local_context.get("local_iocs"), "local_iocs"), start=1):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        category = normalize_category(item.get("category"))
        normalized = normalize_text(value)
        entry = {
            "id": item.get("id") or f"ioc.local.{index}",
            "category": category,
            "value": value,
            "upstream_evidence_ids": [
                evidence for evidence in ensure_list(item.get("upstream_evidence_ids"), "local_ioc.upstream_evidence_ids") if isinstance(evidence, str)
            ],
            "provider_query_ids": [],
            "notes": item.get("notes") if isinstance(item.get("notes"), str) else "",
        }
        external = external_observations.get(normalized)
        if external is not None:
            consumed_external.add(normalized)
            if behaviour_query_id:
                entry["provider_query_ids"].append(behaviour_query_id)
            if external["source_fields"]:
                observed_via = ", ".join(external["source_fields"])
                suffix = f"Publicly matched in VirusTotal behaviour summary via {observed_via}."
                entry["notes"] = f"{entry['notes']} {suffix}".strip()
            matched_local.append(entry)
        else:
            if not entry["notes"]:
                entry["notes"] = "No exact match was found in the supplied VirusTotal behaviour summary input."
            local_only.append(entry)

    for normalized, external in sorted(external_observations.items(), key=lambda pair: pair[1]["value"].lower()):
        if normalized in consumed_external:
            continue
        notes = f"Appears only in VirusTotal behaviour summary via {', '.join(external['source_fields'])}."
        external_only.append(
            {
                "id": f"ioc.external.{external['category']}.{slugify(external['value'], 'item')}",
                "category": external["category"],
                "value": external["value"],
                "upstream_evidence_ids": [],
                "provider_query_ids": [behaviour_query_id] if behaviour_query_id else [],
                "notes": notes,
            }
        )

    return {
        "matched_local": matched_local,
        "local_only_no_public_match": local_only,
        "external_only": external_only,
    }


def claim_report_use(status: str, configured: Any) -> str:
    if isinstance(configured, str) and configured in {"supporting_context", "caveat_only", "followup_only", "exclude"}:
        return configured
    if status in {"corroborated", "partially_corroborated"}:
        return "supporting_context"
    if status == "public_label_only":
        return "followup_only"
    if status == "conflicting":
        return "caveat_only"
    if status == "insufficient_input":
        return "exclude"
    return "caveat_only"


def build_claim_checks(
    local_context: dict[str, Any],
    external_observations: dict[str, dict[str, Any]],
    label_index: dict[str, dict[str, Any]],
    provider_query_ids: dict[str, str],
) -> list[dict[str, Any]]:
    claim_checks: list[dict[str, Any]] = []

    for index, claim in enumerate(ensure_list(local_context.get("claims"), "claims"), start=1):
        if not isinstance(claim, dict):
            continue
        claim_text = claim.get("claim_text")
        if not isinstance(claim_text, str) or not claim_text.strip():
            continue

        indicator_values = [
            value for value in ensure_list(claim.get("indicator_values"), "claim.indicator_values") if isinstance(value, str) and value.strip()
        ]
        label_values = [
            value for value in ensure_list(claim.get("label_values"), "claim.label_values") if isinstance(value, str) and value.strip()
        ]
        conflict_indicator_values = [
            value for value in ensure_list(claim.get("conflict_indicator_values"), "claim.conflict_indicator_values") if isinstance(value, str) and value.strip()
        ]
        conflict_label_values = [
            value for value in ensure_list(claim.get("conflict_label_values"), "claim.conflict_label_values") if isinstance(value, str) and value.strip()
        ]

        matched_indicators = [
            value for value in indicator_values if normalize_text(value) in external_observations
        ]
        matched_labels = [
            value for value in label_values if normalize_text(value) in label_index
        ]
        conflicting_indicators = [
            value for value in conflict_indicator_values if normalize_text(value) in external_observations
        ]
        conflicting_labels = [
            value for value in conflict_label_values if normalize_text(value) in label_index
        ]

        query_ids: list[str] = []
        if matched_indicators or conflicting_indicators:
            behaviour_query_id = provider_query_ids.get("behaviour_summary")
            if behaviour_query_id:
                query_ids.append(behaviour_query_id)
        for value in matched_labels + conflicting_labels:
            entry = label_index.get(normalize_text(value))
            if entry:
                for provider_query_id in entry["provider_query_ids"]:
                    if provider_query_id not in query_ids:
                        query_ids.append(provider_query_id)

        if conflicting_indicators or conflicting_labels:
            status = "conflicting"
            details = []
            if conflicting_indicators:
                details.append(f"conflicting indicators matched: {', '.join(conflicting_indicators)}")
            if conflicting_labels:
                details.append(f"conflicting public labels matched: {', '.join(conflicting_labels)}")
            analysis = "VirusTotal matched information that should weaken or contradict this local claim: " + "; ".join(details) + "."
        elif matched_indicators:
            if indicator_values and len(matched_indicators) < len(indicator_values):
                status = "partially_corroborated"
                analysis = (
                    f"VirusTotal matched {len(matched_indicators)} of {len(indicator_values)} expected indicator values: "
                    f"{', '.join(matched_indicators)}."
                )
            else:
                status = "corroborated"
                analysis = "VirusTotal matched the supplied indicator values for this local claim."
        elif matched_labels:
            status = "public_label_only"
            analysis = (
                "VirusTotal matched only public labels or tags for this claim "
                f"({', '.join(matched_labels)}), so the result should remain enrichment-only unless local evidence is stronger."
            )
        elif indicator_values or label_values or conflict_indicator_values or conflict_label_values:
            status = "no_public_evidence"
            analysis = "No exact supporting or conflicting value from the supplied claim mapping was found in the provided VirusTotal inputs."
        else:
            status = "insufficient_input"
            analysis = "The claim mapping did not include indicator_values, label_values, or conflict match values, so no automated comparison was possible."

        claim_checks.append(
            {
                "id": claim.get("id") or f"cc.auto.{index}",
                "claim_text": claim_text,
                "related_stage": claim.get("related_stage") if isinstance(claim.get("related_stage"), str) else "unknown",
                "related_finding_ids": [
                    finding for finding in ensure_list(claim.get("related_finding_ids"), "claim.related_finding_ids") if isinstance(finding, str)
                ],
                "verification_status": status,
                "provider_query_ids": query_ids,
                "analysis": analysis,
                "report_use": claim_report_use(status, claim.get("report_use")),
            }
        )

    return claim_checks


def merge_upstream_inputs(local_context: dict[str, Any], cli_values: list[str]) -> list[str]:
    merged: list[str] = []
    for value in ensure_list(local_context.get("upstream_inputs"), "upstream_inputs") + cli_values:
        if isinstance(value, str) and value.strip() and value not in merged:
            merged.append(value)
    return merged


def build_limitations(
    file_info_source: dict[str, Any] | None,
    behaviour_source: dict[str, Any] | None,
    local_context: dict[str, Any],
) -> list[str]:
    limitations: list[str] = [
        "Public provider data was translated as attributed external evidence only.",
    ]
    if not file_info_source:
        limitations.append("No file_info input was supplied, so family and threat-label enrichment is limited.")
    elif file_info_source.get("error"):
        limitations.append(
            f"VirusTotal file_info input carried an error payload: {file_info_source['error'].get('kind', 'unknown')}."
        )
    if not behaviour_source:
        limitations.append("No behaviour_summary input was supplied, so IOC correlation is limited to local mappings only.")
    elif behaviour_source.get("error"):
        limitations.append(
            f"VirusTotal behaviour_summary input carried an error payload: {behaviour_source['error'].get('kind', 'unknown')}."
        )
    if not local_context:
        limitations.append(
            "No local-context mapping was supplied, so claim_checks and matched/local-only IOC buckets remain conservative."
        )
    return limitations


def determine_status(file_info_source: dict[str, Any] | None, behaviour_source: dict[str, Any] | None) -> str:
    successful = 0
    errors = 0
    for source in (file_info_source, behaviour_source):
        if not source:
            continue
        if source.get("error"):
            errors += 1
        else:
            successful += 1
    if successful and errors:
        return "partial"
    if successful:
        return "completed"
    return "failed"


def build_summary(payload: dict[str, Any]) -> str:
    provider_queries = len(payload["provider_queries"])
    claim_checks = len(payload["claim_checks"])
    matched_local = len(payload["ioc_correlation"]["matched_local"])
    local_only = len(payload["ioc_correlation"]["local_only_no_public_match"])
    external_only = len(payload["ioc_correlation"]["external_only"])
    enrichments = len(payload["enrichment_candidates"])
    return (
        "Normalized VirusTotal inputs into an intel-stage bundle with "
        f"{provider_queries} provider queries, {claim_checks} claim checks, "
        f"{matched_local} matched local IOCs, {local_only} local-only IOCs, "
        f"{external_only} external-only leads, and {enrichments} enrichment candidates."
    )


def validate_payload(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency issue path
        raise RuntimeError("Install jsonschema to use --validate.") from exc
    schema = read_json(schema_path)
    jsonschema.Draft202012Validator(schema).validate(payload)


def emit_payload(payload: dict[str, Any], output: Path | None, indent: int) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if output is None:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    if not args.file_info and not args.behaviour_summary:
        print("Provide at least --file-info or --behaviour-summary.", file=sys.stderr)
        return 1

    try:
        local_context = ensure_dict(read_json(args.local_context), "local_context") if args.local_context else {}

        file_info_source = None
        file_info = {}
        if args.file_info:
            file_info_source = source_meta(
                ensure_dict(read_json(args.file_info), "file_info"),
                "file_info",
                FILE_INFO_DOCS_URL,
            )
            file_info = file_info_details(file_info_source)

        behaviour_source = None
        behaviour = {}
        if args.behaviour_summary:
            behaviour_source = source_meta(
                ensure_dict(read_json(args.behaviour_summary), "behaviour_summary"),
                "behaviour_summary",
                BEHAVIOUR_SUMMARY_DOCS_URL,
            )
            behaviour = behaviour_summary_details(behaviour_source)

        sample_sha256 = resolve_sample_sha256(file_info, behaviour_source, local_context, args.sample_sha256)

        provider_queries: list[dict[str, Any]] = []
        provider_ids: dict[str, str] = {}
        if file_info_source:
            item = provider_query_for_file_info(file_info_source, file_info, sample_sha256)
            provider_queries.append(item)
            provider_ids["file_info"] = item["id"]
        if behaviour_source:
            item = provider_query_for_behaviour_summary(behaviour_source, behaviour, sample_sha256)
            provider_queries.append(item)
            provider_ids["behaviour_summary"] = item["id"]

        enrichment_candidates, label_index = build_enrichment_and_labels(file_info, behaviour, provider_ids)
        external_observations = build_external_observations(behaviour)
        ioc_correlation = build_ioc_correlation(local_context, external_observations, provider_ids)
        claim_checks = build_claim_checks(local_context, external_observations, label_index, provider_ids)
        limitations = build_limitations(file_info_source, behaviour_source, local_context)
        payload = {
            "schema_version": "1.0",
            "stage": "intel",
            "sample_sha256": sample_sha256,
            "status": determine_status(file_info_source, behaviour_source),
            "summary": "",
            "provider_queries": provider_queries,
            "claim_checks": claim_checks,
            "ioc_correlation": ioc_correlation,
            "enrichment_candidates": enrichment_candidates,
            "limitations": limitations,
            "upstream_inputs": merge_upstream_inputs(local_context, args.upstream_input),
        }
        payload["summary"] = build_summary(payload)

        if args.validate:
            validate_payload(args.schema, payload)

        emit_payload(payload, args.output, args.indent)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
