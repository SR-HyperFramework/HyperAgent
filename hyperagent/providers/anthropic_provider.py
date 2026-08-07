"""Anthropic Claude SDK provider implementation."""
from __future__ import annotations

import logging
import time
from typing import Any

import anthropic

from .base import CompletionResult, LLMProvider, Message, ToolCall

logger = logging.getLogger(__name__)

# Model context window sizes (input tokens).
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-3-5-20241022": 200_000,
}
_DEFAULT_CONTEXT = 200_000

# Bound on memoized per-block counts; cleared wholesale when exceeded.
_TOKEN_CACHE_MAX = 4096


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API wrapper with retry and prompt caching."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_output_tokens: int = 16384,
        temperature: float = 0.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._token_cache: dict[str, int] = {}

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

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
            "messages": api_messages,
            "temperature": self._temperature if temperature is None else temperature,
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
        return _CONTEXT_WINDOWS.get(self._model, _DEFAULT_CONTEXT)

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
