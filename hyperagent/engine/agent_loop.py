"""Core agentic execution loop."""
from __future__ import annotations

import logging
import json
import sys
from typing import TYPE_CHECKING, Any

from ..providers.base import LLMProvider, Message
from ..telemetry.metrics import MetricsCollector
from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry, UnauthorizedToolError
from .checkpoint import CheckpointReached, ContextTracker, compact_messages
from .injection_guard import build_system_prompt

if TYPE_CHECKING:
    from ..console import RunConsole

logger = logging.getLogger(__name__)


class ModelRefusal(Exception):
    """The model declined to answer for safety reasons.

    Anthropic returns ``stop_reason: "refusal"`` with no content and no tool
    calls. Without this exception the loop reads that as a clean finish and
    hands the launcher an empty final answer, which then fails as a generic
    "stage produced no artifact" — indistinguishable from a tool crash or a
    context overflow.

    That distinction matters more here than in most applications. Refusals are
    not uniformly distributed over a malware corpus: they cluster on the
    samples whose content most strongly trips a safety classifier, which are
    disproportionately the overtly malicious ones. Scoring a corpus that
    silently lost those samples reports a recall measured on the easy
    remainder.
    """

    def __init__(self, stage_id: str, turn: int) -> None:
        self.stage_id = stage_id
        self.turn = turn
        super().__init__(
            f"model refused to answer during {stage_id} at turn {turn}; "
            "no artifact was produced"
        )


class AgentLoop:
    """Orchestrates the tool-calling loop for a single LLM stage."""

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        checkpoint_threshold: float = 0.75,
        max_turns: int = 100,
        metrics: MetricsCollector | None = None,
        console_mode: str = "off",
        run_console: RunConsole | None = None,
        compact_enabled: bool = True,
        compact_threshold: float | None = None,
        compact_target_ratio: float = 0.45,
        max_compactions: int = 3,
        max_compaction_tokens: int = 2048,
        message_repeat_limit: int = 3,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.console_mode = console_mode
        self._run_console = run_console
        self.tracker = ContextTracker(provider, threshold=checkpoint_threshold)
        self._checkpoint_threshold = checkpoint_threshold
        self._compact_enabled = compact_enabled
        self._compact_threshold = compact_threshold if compact_threshold is not None else checkpoint_threshold
        self._compact_target_ratio = compact_target_ratio
        self._max_compactions = max_compactions
        self._max_compaction_tokens = max_compaction_tokens
        self._message_repeat_limit = max(2, message_repeat_limit)
        self._metrics = metrics
        self.turns_used = 0
        """Turns consumed by the most recent ``run()`` call."""
        self.total_input_tokens = 0
        """Cumulative ``input_tokens`` across all turns of the most recent ``run()`` call."""
        self.total_output_tokens = 0
        """Cumulative ``output_tokens`` across all turns of the most recent ``run()`` call."""
        self.last_messages: list[Message] = []
        """Conversation state from the most recent ``run()`` call."""

    def run(
        self,
        skill_instructions: str,
        initial_prompt: str,
        stage_tools: list[str],
        reads_sample_content: bool = False,
        global_context: str | None = None,
        stage_id: str = "unknown",
        initial_messages: list[Message] | None = None,
        include_injection_guard: bool = True,
    ) -> str:
        """Run the autonomous loop until completion or checkpoint.

        Parameters
        ----------
        skill_instructions:
            The raw SKILL.md contents containing system instructions.
        initial_prompt:
            The user prompt that starts the conversation (e.g., sample paths).
        stage_tools:
            List of tool names allowed for this stage.
        reads_sample_content:
            Whether this stage reads untrusted sample data directly.
        global_context:
            Optional global pipeline context (from STATE.json).
        stage_id:
            Identifier used for telemetry attribution (e.g. ``"05-dynamic"``).
            Passed through to the ``MetricsCollector`` if one was provided.
        initial_messages:
            Optional prior conversation turns to seed the loop with (e.g. a
            parent stage's history for a non-isolated sub-agent). ``None``
            (the default) starts from just ``initial_prompt``, unchanged from
            prior behavior.
        include_injection_guard:
            Whether to append the untrusted-sample injection guard when
            ``reads_sample_content`` is true.

        Returns
        -------
        The final text output of the model.
        """
        system_prompt, _token_map = build_system_prompt(
            skill_instructions=skill_instructions,
            reads_sample_content=reads_sample_content,
            global_context=global_context,
            include_injection_guard=include_injection_guard,
        )

        tools = self._resolve_tools(stage_tools)
        anthropic_tools = [t.to_anthropic_schema() for t in tools]

        seed = list(initial_messages) if initial_messages else []
        messages: list[Message] = seed + [Message(role="user", content=initial_prompt)]

        self.turns_used = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_messages = list(messages)

        compactions_used = 0

        for turn in range(1, self.max_turns + 1):
            self.turns_used = turn

            # 1. Enforce context window safety, compacting before checkpoint fallback.
            while True:
                try:
                    self.tracker.check_messages(messages)
                    break
                except CheckpointReached as exc:
                    if not self._should_compact(messages, compactions_used):
                        logger.warning("Checkpoint triggered: %s", exc)
                        if self._metrics is not None:
                            self._metrics.record_checkpoint(stage_id)
                        self.last_messages = list(messages)
                        raise

                    target_tokens = int(self.tracker.max_tokens * self._compact_target_ratio)
                    try:
                        if self._run_console is not None:
                            self._run_console.set_activity("compacting context")
                        compacted = compact_messages(
                            self.provider,
                            messages,
                            stage_id=stage_id,
                            target_tokens=target_tokens,
                            max_summary_tokens=self._max_compaction_tokens,
                        )
                    except Exception as compact_exc:
                        logger.warning(
                            "Context compaction failed; falling back to checkpoint: %s",
                            compact_exc,
                        )
                        if self._metrics is not None:
                            self._metrics.record_checkpoint(stage_id)
                        self.last_messages = list(messages)
                        raise exc from compact_exc

                    compactions_used += 1
                    messages = compacted.messages
                    self.last_messages = list(messages)
                    self.total_input_tokens += compacted.input_tokens
                    self.total_output_tokens += compacted.output_tokens
                    if self._metrics is not None:
                        self._metrics.record_turn(
                            stage_id,
                            input_tokens=compacted.input_tokens,
                            output_tokens=compacted.output_tokens,
                            cache_creation_input_tokens=compacted.cache_creation_input_tokens,
                            cache_read_input_tokens=compacted.cache_read_input_tokens,
                            provider=compacted.model,
                        )
                    logger.info(
                        "Compacted context for %s: %d -> %d tokens",
                        stage_id,
                        compacted.original_tokens,
                        compacted.compacted_tokens,
                    )

            context_tokens = self.tracker.current_tokens
            context_cap = self.tracker.max_tokens
            context_ratio = (context_tokens / context_cap) if context_cap > 0 else 0.0
            if self._run_console is not None:
                self._run_console.set_context(
                    turn=turn,
                    max_turns=self.max_turns,
                    tokens=context_tokens,
                    cap=context_cap,
                )
            logger.info(
                "Agent turn %d/%d (context %d/%d tokens, %.1f%%)",
                turn,
                self.max_turns,
                context_tokens,
                context_cap,
                context_ratio * 100,
                extra={"run_console_skip": self._run_console is not None},
            )

            # 2. Get LLM completion
            result = self.provider.complete(
                messages=messages,
                tools=anthropic_tools,
                system_prompt=system_prompt,
            )
            self.total_input_tokens += result.input_tokens
            self.total_output_tokens += result.output_tokens

            # -- Telemetry: record per-turn token usage -----------------------
            if self._metrics is not None:
                self._metrics.record_turn(
                    stage_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_creation_input_tokens=result.cache_creation_input_tokens,
                    cache_read_input_tokens=result.cache_read_input_tokens,
                    provider=result.model,
                )
            # -----------------------------------------------------------------

            # 2b. A refusal ends the stage immediately. Retrying is pointless —
            # the same prompt over the same sample refuses again — so raise
            # rather than let the launcher burn its retry budget on it.
            if result.stop_reason == "refusal":
                logger.error(
                    "Model refused to answer during %s at turn %d; aborting stage",
                    stage_id,
                    turn,
                )
                if self._metrics is not None:
                    self._metrics.record_refusal(stage_id)
                self.last_messages = list(messages)
                raise ModelRefusal(stage_id, turn)

            if result.stop_reason == "max_tokens":
                # The model was cut off mid-answer. Whatever it did say is a
                # fragment, so flag it rather than let a truncated turn read as
                # a deliberate one.
                logger.warning(
                    "Turn %d of %s hit max_tokens; output is truncated",
                    turn,
                    stage_id,
                )

            # Anthropic returns content alongside tool_calls if it wants to speak
            content_blocks: list[dict[str, Any]] = list(result.thinking_blocks)
            if result.content:
                content_blocks.append({"type": "text", "text": result.content})

            for tc in result.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })

            messages.append(Message(role="assistant", content=content_blocks))

            # Break model hallucination loops before executing the same response forever.
            if self._message_repeat_count(messages) >= self._message_repeat_limit:
                logger.warning(
                    "Repeated assistant message detected for %s; refreshing the turn.",
                    stage_id,
                )
                print(
                    f"[message-guard] repeated assistant message detected for {stage_id}; refreshing turn",
                    file=sys.stderr,
                    flush=True,
                )
                messages.append(Message(
                    role="user",
                    content=(
                        "[SYSTEM REFRESH] Your previous response repeated an earlier response. "
                        "Do not restate the plan. Continue with exactly one new tool call or "
                        "return a concise final result."
                    ),
                ))
                self.last_messages = list(messages)
                continue

            # 3. Check stopping condition
            if result.stop_reason != "tool_use" and not result.tool_calls:
                logger.info("Agent finished (stop_reason=%s)", result.stop_reason)
                self.last_messages = list(messages)
                return result.content

            # 4. Execute tools requested by LLM
            tool_results = self._execute_tool_calls(
                result.tool_calls,
                stage_id=stage_id,
                allowed_tool_names={tool.name for tool in tools},
            )
            messages.append(Message(role="user", content=tool_results))

        # Reaching max_turns falls out of the for-loop rather than looping back
        # to the step-1 checkpoint check, so without this the final turn's
        # tool results (just appended above) are never re-measured against the
        # context threshold and no checkpoint is written -- the launcher's
        # next attempt starts from a blank slate, silently discarding however
        # much work this attempt did. Raising CheckpointReached routes this
        # through the same write_checkpoint/compaction path as a real
        # context-threshold hit, so the next attempt resumes from a summary
        # instead of from scratch.
        self.last_messages = list(messages)
        logger.warning(
            "Agent loop reached max turns (%d); checkpointing for retry", self.max_turns
        )
        if self._metrics is not None:
            self._metrics.record_checkpoint(stage_id)
        max_tokens = self.tracker.max_tokens
        raise CheckpointReached(
            f"reached max turns ({self.max_turns}) without a final answer",
            self.tracker.current_tokens,
            (self.tracker.current_tokens / max_tokens) if max_tokens else 0.0,
        )

    # -- Internal Helpers -----------------------------------------------------

    def _message_repeat_count(self, messages: list[Message]) -> int:
        """Return the count of the newest assistant message fingerprint."""
        assistants = [m for m in messages if m.role == "assistant"]
        if not assistants:
            return 0
        newest = self._message_fingerprint(assistants[-1])
        return sum(self._message_fingerprint(message) == newest for message in assistants)

    @staticmethod
    def _message_fingerprint(message: Message) -> str:
        content = message.content
        if isinstance(content, str):
            return content.strip()
        return json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)

    def _should_compact(self, messages: list[Message], compactions_used: int) -> bool:
        """Return whether an over-threshold history should be compacted."""
        if not self._compact_enabled:
            return False
        if compactions_used >= self._max_compactions:
            return False
        if len(messages) < 2:
            return False
        if self.tracker.max_tokens <= 0:
            return False
        return self.tracker.ratio >= self._compact_threshold

    def _resolve_tools(self, tool_patterns: list[str]) -> list:
        """Resolve wildcard patterns (e.g. 'vm_*') to registered tools."""
        from fnmatch import fnmatch
        
        all_tools = self.registry.get_all_tools()
        resolved = []
        
        for t in all_tools:
            for pattern in tool_patterns:
                if fnmatch(t.name, pattern):
                    resolved.append(t)
                    break
                    
        return resolved

    def _execute_tool_calls(
        self,
        tool_calls: list,
        stage_id: str = "unknown",
        allowed_tool_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run requested tools and format results for the LLM."""
        results = []
        tool_errors = 0
        for tc in tool_calls:
            logger.info("Calling tool: %s", tc.name)
            try:
                if allowed_tool_names is not None and tc.name not in allowed_tool_names:
                    raise UnauthorizedToolError(stage_id, tc.name, allowed_tool_names)
                res = self.registry.execute(tc.name, tc.arguments)
            except UnauthorizedToolError as exc:
                logger.warning(
                    "Blocked unauthorized tool call for %s: %s",
                    stage_id,
                    tc.name,
                )
                res = ToolResult(content=str(exc), is_error=True)

            content = res.content
            if res.is_error:
                logger.warning("Tool %s returned an error", tc.name)
                content = f"Error: {content}"
                tool_errors += 1

            if self.console_mode == "minimal":
                if self._run_console is not None:
                    self._run_console.tool_result(content, is_error=res.is_error)
                else:
                    preview = content.strip().replace("\n", " ")
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    marker = "x" if res.is_error else "="
                    print(f"  {marker} {preview}", file=sys.stderr, flush=True)

            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": content,
                "is_error": res.is_error,
            })

        # Report tool errors to telemetry (if any occurred this batch)
        if tool_errors > 0 and self._metrics is not None:
            self._metrics.record_turn(
                stage_id,
                input_tokens=0,
                output_tokens=0,
                tool_errors=tool_errors,
            )
        return results

    def _checkpoint_response(self, exc: CheckpointReached) -> str:
        """Generate a response telling the orchestrator a checkpoint is needed."""
        # For a smooth v3 -> v4 transition, if a stage checkpoints, it should output
        # valid JSON with its current findings so the pipeline STATE.json updates,
        # then mark itself 'running' (handled by skills natively, or by the launcher).
        # We return a system message so the launcher knows it was forcibly interrupted.
        return f"[SYSTEM CHECKPOINT] Context threshold reached at {exc.tokens} tokens."
