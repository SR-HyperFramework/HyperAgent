# Phase 4 — VM Auto-Rollback + Rule Verifier (Gap #2, #3)

Read `00-index.md` first for shared constraints and reference paths.
Independent of Phase 3 — can be done in parallel with it, except the
launcher (3d) has a call-site stub waiting for
`vm_auto_revert_after_dynamic`.

## Part A — VM Auto-Rollback (Gap #3)

### Why

After a `05-dynamic` stage runs the sample in the guest VM, the VM must be
reverted to a clean snapshot unconditionally — regardless of whether the
stage succeeded, failed, or checkpointed — so malware never persists into
the next run. This must NOT be an LLM-callable tool (the LLM deciding
whether/when to revert defeats the safety purpose); it's a host-side hook
the launcher calls directly.

### File to modify: `hyperagent/tools/vmware_tools.py`

Existing file already has `_run_vmrun()` helper (module-level, takes
`args: list[str], timeout: int = 30`) and `create_vmware_tools(config)`
which builds the LLM-facing `ToolDefinition` list including
`vm_revert_snapshot` (see current file, lines 49-50 for the pattern). Add,
at module level (NOT inside `create_vmware_tools`, NOT added to the
`ToolDefinition` list it returns):

```python
def vm_auto_revert_after_dynamic(config: VMwareConfig) -> ToolResult:
    """Called automatically by the launcher after '05-dynamic' completes.
    Reverts the VM to its clean snapshot unconditionally. Internal safety
    hook — NOT exposed to the LLM as a callable tool."""
    return _run_vmrun(["-T", "ws", "revertToSnapshot", config.vmx_path, config.snapshot_name])
```

Do not register this in `create_vmware_tools()`'s return list or in
`tools/registry.py::STAGE_TOOLS` — that would make it LLM-callable, which
is exactly what must be avoided (per `implementation_plan.md`'s CAUTION
note on this gap).

### Launcher wiring

If Phase 3d has landed, replace its stub with a real call to
`vm_auto_revert_after_dynamic(config.vmware)` right after the `05-dynamic`
stage's attempt loop exits in `engine/launcher.py`. If 3d hasn't landed
yet, nothing to do here — 3d's plan file already accounts for calling this
once it exists.

### Exit criteria (Part A)

```bash
python -m pytest hyperagent/tests/test_tools.py -v  # existing vmware tests still pass
```
Add `hyperagent/tests/test_vm_safety.py`: mock/monkeypatch
`subprocess.run` (matching the existing mocking style in
`test_tools.py` for `_run_vmrun`-backed tools), call
`vm_auto_revert_after_dynamic(config)` directly, assert the constructed
`vmrun` command is exactly
`["vmrun", "-T", "ws", "revertToSnapshot", <vmx_path>, <snapshot_name>]`.
If 3d has landed, add a second test asserting the launcher calls this hook
after a `05-dynamic` attempt regardless of the stage's pass/fail outcome
(use a mock/monkeypatch on `vmware_tools.vm_auto_revert_after_dynamic`
itself rather than shelling out).

---

## Part B — Rule Verifier (Gap #2, Trident-style FPR=0)

### Why

Agent-generated JQ (or YARA) detection rules can false-positive on benign
files. Before saving a rule, run it against a corpus of known-benign sandbox
JSON reports; if it matches any of them, reject and ask the LLM to repair
it. Target FPR is 0%, same policy as the Trident paper this project is
modeled on.

### File to create: `hyperagent/tools/rule_verifier.py`

```python
@dataclass
class VerificationResult:
    passed: bool
    fps: list[str]  # filenames of benign reports the rule matched, if any

class RuleVerifier:
    def __init__(self, benign_reports_dir: Path) -> None:
        """benign_reports_dir: directory of ~100 benign sandbox JSON reports.
        Store the dir; don't eagerly load all files into memory at init —
        glob lazily inside verify_jq_rule so tests can point at a tiny
        fixture dir with 2-3 files instead of the real 100-file corpus."""

    def verify_jq_rule(self, jq_rule: str) -> VerificationResult:
        """Run `jq <jq_rule>` against every *.json in benign_reports_dir.
        A rule 'matches' a file if jq's stdout for that file is non-empty
        and not exactly 'null'/'false' (jq's own truthy-output convention —
        confirm this against how jq rules are actually authored elsewhere
        in this repo, e.g. any existing .jq rule files in reports/ or
        skill/, before hardcoding the match predicate)."""

    def generate_repair_prompt(self, rule: str, fps: list[str]) -> str:
        """Return a prompt string telling the LLM: here is the rule, here
        are the benign files it incorrectly matched (include each file's
        path and, ideally, the specific field(s) the rule matched on if
        cheaply extractable), fix the rule to not match any of them while
        still matching the original malicious pattern."""
```

Use `subprocess.run(["jq", jq_rule, str(file)], capture_output=True,
text=True, shell=False, timeout=...)` matching the `shell=False` +
bounded-timeout pattern already used in `tools/analysis_tools.py::_run_bounded`
and `tools/vmware_tools.py::_run_vmrun` — reuse one of those helpers via
import if their signature fits, rather than writing a third copy of the
same subprocess-safety logic.

Confirm `jq` is actually the intended rule engine before writing this — the
plan doc also mentions YARA as an alternative in the section title. If this
repo has no existing `.jq`/`.yar` rule examples to anchor on, ask the user
which engine Gap #2 should target before implementing, rather than guessing.

### Exit criteria (Part B)

```bash
python -m pytest hyperagent/tests/test_rule_verifier.py -v
```
Write `hyperagent/tests/test_rule_verifier.py` with a fixture dir of 2-3
tiny benign JSON files under `hyperagent/tests/fixtures/benign_reports/`
(e.g. `{"pe": {"imphash": "abc"}}`, `{"pe": {"imphash": "def"}}`). Test:
1. A rule matching neither fixture (`.|has("nonexistent_field")`) →
   `passed=True`, `fps=[]`.
2. A rule matching both (`.pe.imphash`) → `passed=False`,
   `fps=[<both filenames>]`.
3. `generate_repair_prompt` includes both the rule text and the FP
   filenames in its output.

### Integration (defer if Phase 3 launcher not ready)

Per `implementation_plan.md`: hook into `engine/agent_loop.py` or a
task-specific subagent so that when the LLM writes a JQ rule to disk, it's
automatically verified before being accepted, with a retry loop feeding
`generate_repair_prompt()` back to the LLM on failure. This wiring can wait
until Phase 3's `AgentLoop`/`subagent.py` design is settled — write
`rule_verifier.py` standalone and testable now; wire it into the loop as a
follow-up once 3c lands, don't block Part B's exit criteria on it.

---

## Progress (2026-08-16) — Complete

- **Part A**: Added `vm_auto_revert_after_dynamic(config)` to `hyperagent/tools/vmware_tools.py`, module-level, reusing `_run_vmrun`. Not registered in `create_vmware_tools()` or `STAGE_TOOLS` — confirmed not LLM-callable via `test_vm_auto_revert_after_dynamic_is_not_llm_callable`. Launcher's pre-existing guarded `finally` hook in `engine/launcher.py` (`05-dynamic` → `vm_auto_revert_after_dynamic`) now resolves to a real function; added `test_launcher_reverts_vm_after_dynamic_stage_succeeds` and `_fails` to `test_launcher.py` proving the revert fires regardless of stage outcome.
- **Part B**: Added `hyperagent/tools/rule_verifier.py::VerificationResult`/`RuleVerifier` targeting **JQ** (user-confirmed choice; structured so a YARA verifier can be added later without rework). `verify_jq_rule` globs the benign corpus lazily per call and raises `RuntimeError` (not silent `False`) on missing `jq`, timeout, or non-zero exit — a deliberate fail-loud deviation from swallowing errors, since silently treating a broken verifier as "no false positives" would defeat the FPR=0 safety intent. `generate_repair_prompt` builds the LLM repair prompt. Fixtures at `hyperagent/tests/fixtures/benign_reports/{report_a,report_b}.json`; full coverage in `hyperagent/tests/test_rule_verifier.py` (35 tests).
- Integration into `agent_loop.py`'s rule-generation retry loop remains deferred, as specified above — not part of this phase's exit criteria.
- Test results: `python -m pytest hyperagent/tests/ -q` → **141 passed, 3 skipped** (was 101 passed, 3 skipped before this phase).
