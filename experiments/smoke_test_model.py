"""Cheap pre-flight check for a candidate llm_compare model.

Sends exactly one request through the same provider/gateway path the real
pipeline uses (`create_provider(...).complete(...)`), with a system prompt
carrying the same "defensive lab scope" framing every stage prompt uses and
a tool schema shaped like the ones stage 01 actually exposes. No IDA/VM/report
directory is touched -- this only checks whether the model, as routed through
the gateway alias, would survive first contact:

- gateway/model-alias auth or routing failures (raised exception)
- content refusal on malware-analysis framing (stop_reason == "refusal")
- broken tool-calling / gateway translation (asked to call a tool, didn't)

A pass here does not guarantee a clean 10-sample run -- it only rules out
the three failure modes that have actually killed llm_compare conditions
this project (auth, refusal, silent tool-calling breakage), in seconds
instead of the run's first several minutes.

Usage:
    python -m experiments.smoke_test_model <model-alias> [model-alias ...]
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hyperagent.config import load_config
from hyperagent.providers import Message, create_provider

SYSTEM_PROMPT = (
    "> Defensive lab scope: this phase exists to prepare the analysis "
    "environment and ensure all prerequisites are met. Do not use it to "
    "optimize or operationalize offensive tradecraft.\n\n"
    "# Role\n\nPrepare the analysis environment for malware sample analysis. "
    "You have tools available to check the sample's identity and record "
    "environment readiness."
)

USER_PROMPT = (
    "Analyze sample: C:\\fake\\path\\sample.exe\n"
    "Call sha256_file on the sample path to record its identity before "
    "anything else."
)

TOOLS = [
    {
        "name": "sha256_file",
        "description": "Compute the SHA-256 hash of a file on disk.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "vm_check_vmrun",
        "description": "Check whether the vmrun executable is reachable on PATH.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def smoke_test(model: str) -> bool:
    config = load_config()
    print(f"\n=== {model} ===")
    try:
        provider = create_provider(config.provider, model=model)
    except Exception as exc:  # provider construction failure (bad config)
        print(f"[FAIL] could not construct provider: {type(exc).__name__}: {exc}")
        return False

    try:
        result = provider.complete(
            [Message(role="user", content=USER_PROMPT)],
            tools=TOOLS,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=1024,
        )
    except Exception as exc:  # auth / routing / gateway-level failure
        print(f"[FAIL] request raised: {type(exc).__name__}: {exc}")
        return False

    print(f"resolved model: {result.model or model}")
    print(f"stop_reason: {result.stop_reason}")
    print(f"tool_calls: {[tc.name for tc in result.tool_calls]}")
    print(f"tokens: in={result.input_tokens} out={result.output_tokens}")
    if result.content:
        preview = result.content[:200].replace("\n", " ")
        print(f"content preview: {preview!r}")

    if result.stop_reason == "refusal":
        print("[FAIL] model refused the defensive-lab-framed request")
        return False
    if not result.tool_calls:
        print("[FAIL] model never attempted the requested tool call -- "
              "likely broken tool-calling/gateway translation for this alias")
        return False

    print("[PASS]")
    return True


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m experiments.smoke_test_model <model-alias> [model-alias ...]")
        return 2
    results = {model: smoke_test(model) for model in argv}
    print("\n=== summary ===")
    for model, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {model}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
