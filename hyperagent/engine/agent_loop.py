"""Core agentic execution loop."""
from __future__ import annotations

import logging
from typing import Any

from ..providers.base import LLMProvider, Message
from ..tools.registry import ToolRegistry
from .checkpoint import CheckpointReached, ContextTracker
from .injection_guard import build_system_prompt

logger = logging.getLogger(__name__)


class AgentLoop:
    """Orchestrates the tool-calling loop for a single LLM stage."""

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        checkpoint_threshold: float = 0.75,
        max_turns: int = 50,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.tracker = ContextTracker(provider, threshold=checkpoint_threshold)

    def run(
        self,
        skill_instructions: str,
        initial_prompt: str,
        stage_tools: list[str],
        reads_sample_content: bool = False,
        global_context: str | None = None,
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
            
        Returns
        -------
        The final text output of the model.
        """
        system_prompt = build_system_prompt(
            skill_instructions=skill_instructions,
            reads_sample_content=reads_sample_content,
            global_context=global_context,
        )

        tools = self._resolve_tools(stage_tools)
        anthropic_tools = [t.to_anthropic_schema() for t in tools]

        messages: list[Message] = [Message(role="user", content=initial_prompt)]

        for turn in range(1, self.max_turns + 1):
            logger.info("Agent turn %d/%d", turn, self.max_turns)
            
            # 1. Enforce context window safety
            try:
                self.tracker.check_messages(messages)
            except CheckpointReached as exc:
                logger.warning("Checkpoint triggered: %s", exc)
                return self._checkpoint_response(exc)

            # 2. Get LLM completion
            result = self.provider.complete(
                messages=messages,
                tools=anthropic_tools,
                system_prompt=system_prompt,
            )
            
            # Anthropic returns content alongside tool_calls if it wants to speak
            content_blocks: list[dict[str, Any]] = []
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

            # 3. Check stopping condition
            if result.stop_reason != "tool_use" and not result.tool_calls:
                logger.info("Agent finished (stop_reason=%s)", result.stop_reason)
                return result.content

            # 4. Execute tools requested by LLM
            tool_results = self._execute_tool_calls(result.tool_calls)
            messages.append(Message(role="user", content=tool_results))

        logger.warning("Agent loop reached max turns (%d)", self.max_turns)
        return "ERROR: Max iterations reached without a final answer."

    # -- Internal Helpers -----------------------------------------------------

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

    def _execute_tool_calls(self, tool_calls: list) -> list[dict[str, Any]]:
        """Run requested tools and format results for the LLM."""
        results = []
        for tc in tool_calls:
            logger.info("Calling tool: %s", tc.name)
            res = self.registry.execute(tc.name, tc.arguments)
            
            content = res.content
            if res.is_error:
                logger.warning("Tool %s returned an error", tc.name)
                content = f"Error: {content}"
                
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": content,
                "is_error": res.is_error,
            })
        return results

    def _checkpoint_response(self, exc: CheckpointReached) -> str:
        """Generate a response telling the orchestrator a checkpoint is needed."""
        # For a smooth v3 -> v4 transition, if a stage checkpoints, it should output
        # valid JSON with its current findings so the pipeline STATE.json updates,
        # then mark itself 'running' (handled by skills natively, or by the launcher).
        # We return a system message so the launcher knows it was forcibly interrupted.
        return f"[SYSTEM CHECKPOINT] Context threshold reached at {exc.tokens} tokens."
