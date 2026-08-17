"""Bounded sub-conversations spawned by a stage for a self-contained sub-task."""
from __future__ import annotations

from dataclasses import dataclass

from ..providers.base import LLMProvider, Message
from ..telemetry.metrics import MetricsCollector
from ..tools.registry import ToolRegistry
from .agent_loop import AgentLoop


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
    loop = AgentLoop(
        provider,
        registry,
        checkpoint_threshold=checkpoint_threshold,
        max_turns=max_turns,
        metrics=metrics,
    )

    initial_messages = parent_messages if (not isolated and parent_messages) else None

    final_text = loop.run(
        skill_instructions=system_prompt,
        initial_prompt=task_prompt,
        stage_tools=stage_tools,
        stage_id=stage_id,
        initial_messages=initial_messages,
    )

    return SubagentResult(
        final_text=final_text,
        turns_used=loop.turns_used,
        input_tokens=loop.total_input_tokens,
        output_tokens=loop.total_output_tokens,
    )
