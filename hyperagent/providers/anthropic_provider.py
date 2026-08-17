"""Anthropic Claude SDK provider implementation."""
from __future__ import annotations

import logging
import sys
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
        cache_enabled: bool = True,
        base_url: str = "",
        extended_thinking: bool = False,
        thinking_budget_tokens: int = 4096,
        debug_console: bool = False,
    ) -> None:
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**client_kwargs)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._cache_enabled = cache_enabled
        self._extended_thinking = extended_thinking
        self._thinking_budget_tokens = thinking_budget_tokens
        self._debug_console = debug_console
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

        output_tokens = self._max_output_tokens if max_tokens is None else max_tokens
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": output_tokens,
            "messages": api_messages,
        }

        if self._extended_thinking:
            # Anthropic requires max_tokens > budget_tokens; bump rather than
            # error, since the caller's max_tokens wasn't chosen with a
            # thinking budget in mind.
            kwargs["max_tokens"] = max(output_tokens, self._thinking_budget_tokens + 1024)
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget_tokens,
            }

        if system_prompt:
            system_block: dict[str, Any] = {
                "type": "text",
                "text": system_prompt,
            }
            if self._cache_enabled:
                # Use prompt caching: system prompt is stable within a stage run.
                system_block["cache_control"] = {"type": "ephemeral"}
            kwargs["system"] = [system_block]

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
        """Call the Messages API with exponential backoff on transient errors.

        Always streams and reassembles the final message, rather than calling
        ``messages.create`` directly. Streaming is required for `Message`
        Batches API and long-running requests upstream (>10 min), and some
        Anthropic-compatible proxies only implement the streaming path
        correctly, silently returning a malformed non-Anthropic response
        shape for a plain ``create`` call. Streaming is always at least as
        correct, so it's the default rather than a configurable option.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                with self._client.messages.stream(**kwargs) as stream:
                    if self._debug_console:
                        self._drain_stream_to_console(stream)
                    return stream.get_final_message()
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
    def _drain_stream_to_console(stream: Any) -> None:
        """Print thinking/text/tool-call deltas to stderr as they arrive.

        Debug-only path: normal runs never touch this, so it can be liberal
        about what it prints without affecting the parsed result (still built
        from ``get_final_message()`` by the caller).
        """
        open_tool: str | None = None
        for event in stream:
            if event.type == "thinking":
                print(event.thinking, end="", file=sys.stderr, flush=True)
            elif event.type == "text":
                print(event.text, end="", file=sys.stderr, flush=True)
            elif event.type == "content_block_start":
                block = event.content_block
                if getattr(block, "type", None) == "tool_use":
                    open_tool = block.name
                    print(f"\n[tool_use:{open_tool}] ", end="", file=sys.stderr, flush=True)
                elif getattr(block, "type", None) == "thinking":
                    print("\n[thinking] ", end="", file=sys.stderr, flush=True)
                elif getattr(block, "type", None) == "text":
                    print("\n[text] ", end="", file=sys.stderr, flush=True)
            elif event.type == "input_json":
                print(event.partial_json, end="", file=sys.stderr, flush=True)
            elif event.type == "content_block_stop":
                print(file=sys.stderr, flush=True)
                open_tool = None
        print(file=sys.stderr, flush=True)

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
        thinking_blocks: list[dict[str, Any]] = []

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
            elif block.type in ("thinking", "redacted_thinking"):
                # Must round-trip verbatim (signature included) into the next
                # assistant turn's content, so keep it as the raw wire dict
                # rather than re-deriving one from partial fields.
                thinking_blocks.append(block.model_dump())

        # Prompt-caching fields are present on the usage object only when the
        # cache_control block was sent and Anthropic processed the cache request.
        # Use getattr with a 0 default so we stay compatible with older API
        # responses or providers that do not support prompt caching.
        usage = response.usage
        cache_creation = getattr(usage, "cache_creation_input_tokens", None) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0

        return CompletionResult(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
            model=response.model,
            thinking_blocks=thinking_blocks,
        )
