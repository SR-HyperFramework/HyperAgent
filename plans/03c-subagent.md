# Phase 3c — engine/subagent.py

Read `00-index.md` first for shared constraints and reference paths.

## Goal

Let a stage spawn a fresh, bounded sub-conversation for a sub-task (e.g. a
static-analysis stage delegating "decompile and summarize function X" to a
child loop) without polluting the parent's message history — except when
ablation condition A3 (`isolated_subagents=False` in `AblationConfig`,
see `00-index.md`) asks for the opposite, to measure isolation's marginal
value.

## Files to create

### `hyperagent/engine/subagent.py` [NEW]

```python
@dataclass
class SubagentResult:
    final_text: str
    turns_used: int
    input_tokens: int
    output_tokens: int

def spawn_subagent(
    provider: LLMProvider,
    registry: ToolRegistry,
    task_prompt: str,
    stage_tools: list[str],
    *,
    parent_messages: list[Message] | None = None,
    isolated: bool = True,
    max_turns: int = 20,
    checkpoint_threshold: float = 0.75,
    metrics: MetricsCollector | None = None,
    stage_id: str = "subagent",
    system_prompt: str = "",
) -> SubagentResult:
    """Run a bounded AgentLoop-style turn loop for one sub-task.

    isolated=True (default): starts from an empty message history — the
    child never sees the parent's prior turns.
    isolated=False: starts from parent_messages + the new task_prompt —
    used by ablation condition A3 to test whether isolation actually
    matters for output quality/token cost.
    """
```

Implementation notes:
- Reuse `engine/agent_loop.py::AgentLoop` internals rather than
  reimplementing the turn loop — either instantiate an `AgentLoop` and call
  a variant of `.run()` that accepts a pre-seeded message list, or (cleaner)
  add an optional `initial_messages: list[Message] | None = None` parameter
  to `AgentLoop.run()` itself in `engine/agent_loop.py` (currently line 74
  hardcodes `messages: list[Message] = [Message(role="user", content=initial_prompt)]`
  — change to `messages = initial_messages + [Message(...)] if initial_messages else [...]`).
  Prefer this over duplicating the loop; `AgentLoop.run()`'s existing
  behavior for `initial_messages=None` must stay byte-identical (all
  existing `agent_loop.py` tests must keep passing unmodified).
- `spawn_subagent` builds the `AgentLoop`, calls `.run(...)`, wraps the
  returned string + whatever turn/token counts are available into
  `SubagentResult`. `AgentLoop.run()` currently returns only a `str` — you
  may need it to also expose turns-used/token counts (check
  `ContextTracker.current_tokens` after the call, and track a turn counter
  either inside `AgentLoop` or by wrapping the loop in `subagent.py`).

## Exit criteria

```bash
python -m pytest hyperagent/tests/test_agent_loop.py -v  # existing behavior unchanged (if this file doesn't exist yet, that's Phase 7's job — skip if absent)
```
Add `hyperagent/tests/test_subagent.py` with a fake/mock `LLMProvider` (see
`hyperagent/tests/test_providers.py` for the existing mocking pattern used
in this repo) asserting:
1. `isolated=True` — the child's first message to the provider does NOT
   contain any content from `parent_messages`.
2. `isolated=False` — the child's first message DOES contain
   `parent_messages` content plus the new task prompt.
