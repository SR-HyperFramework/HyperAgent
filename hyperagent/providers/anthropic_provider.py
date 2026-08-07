"""Anthropic Claude SDK provider implementation."""
from __future__ import annotations

import logging
import time
from typing import Any

import anthropic

from .base import CompletionResult, LLMProvider, Message, ToolCall

logger = logging.getLogger(__name__)

# Context windows are read from the Models API at runtime rather than kept in a
# table here, which silently goes stale every release. This value is only the
# fallback for when that lookup fails: guessing low costs early checkpoints,
# guessing high overflows the window and loses the run, so it stays low.
_FALLBACK_CONTEXT = 200_000

DEFAULT_MODEL = "claude-opus-5"

# Bound on memoized per-block counts; cleared wholesale when exceeded.
_TOKEN_CACHE_MAX = 4096


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API wrapper with retry and prompt caching."""

    accepts_temperature = False

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 16384,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._token_cache: dict[str, int] = {}
        self._context_window: int | None = None

    # -- LLMProvider interface ------------------------------------------------

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        api_messages = self._to_api_messages(messages)

        # Accepted for interface compatibility, never forwarded: a non-default
        # temperature is a 400 on Claude Opus 4.7 and later. Steer with the
        # prompt, or with output_config.effort, instead.
        if temperature is not None:
            logger.warning(
                "Ignoring temperature=%s: current Claude models reject sampling "
                "parameters. Use prompting to guide behaviour.",
                temperature,
            )

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
            "messages": api_messages,
        }

        if system_prompt:
            # Use prompt caching: system prompt is stable within a stage run.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if tools:
            kwargs["tools"] = tools

        response = self._call_with_retry(**kwargs)
        return self._parse_response(response)

    def count_tokens(self, text: str) -> int:
        """Exact token count via the Anthropic count_tokens API, memoized.

        The agent loop re-measures the whole history every turn, so identical
        blocks would otherwise cost one API round-trip each, every turn.
        """
        if not text:
            return 0
        cached = self._token_cache.get(text)
        if cached is not None:
            return cached

        try:
            result = self._client.messages.count_tokens(
                model=self._model,
                messages=[{"role": "user", "content": text}],
            )
            count = result.input_tokens
        except Exception as exc:
            logger.warning("count_tokens API failed (%s) — using char heuristic", exc)
            return max(1, len(text) // 4)

        if len(self._token_cache) >= _TOKEN_CACHE_MAX:
            self._token_cache.clear()
        self._token_cache[text] = count
        return count

    def max_context_tokens(self) -> int:
        """Context window for the configured model, fetched once and memoized.

        Asking the Models API keeps this correct across releases. Getting it
        wrong is expensive in one specific way: the checkpoint threshold is a
        fraction of this number, so an under-reported window makes every stage
        checkpoint and restart far earlier than it needs to — which inflates
        both wall-clock time and token spend without any visible error.
        """
        if self._context_window is None:
            try:
                self._context_window = self._client.models.retrieve(
                    self._model
                ).max_input_tokens
            except Exception as exc:
                logger.warning(
                    "models.retrieve(%s) failed (%s) — assuming %d input tokens",
                    self._model,
                    exc,
                    _FALLBACK_CONTEXT,
                )
                self._context_window = _FALLBACK_CONTEXT
        return self._context_window

    # -- internal helpers -----------------------------------------------------

    def _call_with_retry(self, **kwargs: Any) -> anthropic.types.Message:
        """Call the Messages API with exponential backoff on transient errors."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return self._client.messages.create(**kwargs)
            except (
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.APIConnectionError,
            ) as exc:
                last_error = exc
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Anthropic API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError(
            f"Anthropic API failed after {self._max_retries} retries"
        ) from last_error

    @staticmethod
    def _to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Convert provider-agnostic Messages to Anthropic wire format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            result.append({"role": msg.role, "content": msg.content})
        return result

    @staticmethod
    def _parse_response(response: anthropic.types.Message) -> CompletionResult:
        """Parse Anthropic response into a normalized CompletionResult."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,  # type: ignore[arg-type]
                    )
                )

        return CompletionResult(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
