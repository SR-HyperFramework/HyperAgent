#!/usr/bin/env python3
"""Fetch VirusTotal v3 file data by hash."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = 30.0
HASH_RE = re.compile(r"^(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
ENDPOINTS = {
    "file_info": {
        "docs_url": "https://docs.virustotal.com/reference/file-info",
        "url_template": "https://www.virustotal.com/api/v3/files/{id}",
        "description": "Get a file report.",
    },
    "behaviour_summary": {
        "docs_url": "https://docs.virustotal.com/reference/file-all-behaviours-summary",
        "url_template": "https://www.virustotal.com/api/v3/files/{id}/behaviour_summary",
        "description": "Get a merged summary of all behavior reports for a file.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch VirusTotal v3 file data by MD5, SHA-1, or SHA-256."
    )
    parser.add_argument("file_id", help="SHA-256, SHA-1, or MD5 identifying the file.")
    parser.add_argument(
        "--endpoint",
        choices=tuple(ENDPOINTS.keys()),
        default="file_info",
        help=(
            "VirusTotal endpoint to query. "
            "Use 'file_info' for /files/{id} or 'behaviour_summary' "
            "for /files/{id}/behaviour_summary."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON output to a file instead of stdout.",
    )
    parser.add_argument(
        "--api-key",
        help="VirusTotal API key. Defaults to VT_API_KEY or VIRUSTOTAL_API_KEY.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level for output.",
    )
    parser.add_argument(
        "--include-meta",
        action="store_true",
        help="Wrap the VirusTotal response with request metadata.",
    )
    return parser.parse_args()


def default_env_files() -> list[Path]:
    """Locations searched for a .env file, in priority order."""
    return [
        Path(__file__).resolve().parent / ".env",  # alongside this script
        Path.cwd() / ".env",                       # analysis workspace
    ]


def load_dotenv(candidates: list[Path] | None = None) -> dict[str, str]:
    """Minimal .env loader: KEY=VALUE lines, ignoring blanks and # comments.

    Quotes around values are stripped. Later files (and later lines within a
    file) do not overwrite earlier keys, so the first value wins.
    """
    result: dict[str, str] = {}
    for path in candidates or default_env_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                result.setdefault(key, value)
    return result


def resolve_api_key(explicit: str | None) -> str | None:
    dotenv = load_dotenv()
    for candidate in (
        explicit,
        os.environ.get("VT_API_KEY"),
        os.environ.get("VIRUSTOTAL_API_KEY"),
        dotenv.get("VT_API_KEY"),
        dotenv.get("VIRUSTOTAL_API_KEY"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def classify_hash(file_id: str) -> str:
    if len(file_id) == 32:
        return "md5"
    if len(file_id) == 40:
        return "sha1"
    if len(file_id) == 64:
        return "sha256"
    return "unknown"


def build_endpoint(file_id: str, endpoint_name: str) -> str:
    template = ENDPOINTS[endpoint_name]["url_template"]
    return template.format(id=urllib.parse.quote(file_id, safe=""))


def parse_json_bytes(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"))


def build_error_payload(
    docs_url: str,
    endpoint_name: str,
    endpoint: str,
    kind: str,
    details: object,
) -> str:
    payload = {
        "provider": "virustotal",
        "resource": endpoint_name,
        "status": "error",
        "docs_url": docs_url,
        "endpoint": endpoint,
        "error": {
            "kind": kind,
            "details": details,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def fetch_json(endpoint: str, api_key: str, timeout: float) -> object:
    request = urllib.request.Request(
        endpoint,
        headers={
            "accept": "application/json",
            "x-apikey": api_key,
            "User-Agent": "hyperagent-vt-fetch/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_json_bytes(response.read())


def build_output_payload(
    response_payload: object,
    file_id: str,
    endpoint_name: str,
    endpoint: str,
    docs_url: str,
    include_meta: bool,
) -> object:
    if not include_meta:
        return response_payload
    return {
        "provider": "virustotal",
        "resource": endpoint_name,
        "docs_url": docs_url,
        "endpoint": endpoint,
        "query": {
            "id": file_id,
            "hash_type": classify_hash(file_id),
        },
        "response": response_payload,
    }


def emit_payload(payload: object, output: Path | None, indent: int) -> None:
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
    file_id = args.file_id.strip()

    if not HASH_RE.fullmatch(file_id):
        print(
            "file_id must be an MD5, SHA-1, or SHA-256 hex string.",
            file=sys.stderr,
        )
        return 1

    if args.timeout <= 0:
        print("--timeout must be greater than 0.", file=sys.stderr)
        return 1

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(
            "Missing VirusTotal API key. Provide --api-key or set VT_API_KEY / VIRUSTOTAL_API_KEY.",
            file=sys.stderr,
        )
        return 2

    endpoint_name = args.endpoint
    docs_url = ENDPOINTS[endpoint_name]["docs_url"]
    endpoint = build_endpoint(file_id, endpoint_name)

    try:
        response_payload = fetch_json(endpoint, api_key, args.timeout)
    except urllib.error.HTTPError as exc:
        raw_body = exc.read()
        if raw_body:
            try:
                body = parse_json_bytes(raw_body)
            except json.JSONDecodeError:
                body = raw_body.decode("utf-8", errors="replace")
        else:
            body = None
        print(
            build_error_payload(
                docs_url,
                endpoint_name,
                endpoint,
                "http_error",
                {
                    "status_code": exc.code,
                    "reason": str(exc.reason),
                    "body": body,
                },
            ),
            file=sys.stderr,
        )
        return 3
    except urllib.error.URLError as exc:
        print(
            build_error_payload(
                docs_url,
                endpoint_name,
                endpoint,
                "network_error",
                {
                    "reason": str(exc.reason),
                },
            ),
            file=sys.stderr,
        )
        return 4
    except json.JSONDecodeError as exc:
        print(
            build_error_payload(
                docs_url,
                endpoint_name,
                endpoint,
                "invalid_json",
                {
                    "message": str(exc),
                },
            ),
            file=sys.stderr,
        )
        return 5

    output_payload = build_output_payload(
        response_payload,
        file_id,
        endpoint_name,
        endpoint,
        docs_url,
        args.include_meta,
    )

    try:
        emit_payload(output_payload, args.output, args.indent)
    except OSError as exc:
        print(f"Failed to write output: {exc}", file=sys.stderr)
        return 6

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
