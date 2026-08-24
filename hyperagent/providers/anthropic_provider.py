"""Anthropic Claude SDK provider implementation."""
from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING, Any

import anthropic

from .base import CompletionResult, LLMProvider, Message, ToolCall
from ..console import preview_json_or_text

if TYPE_CHECKING:
    from ..console import RunConsole

logger = logging.getLogger(__name__)

_ANSI_RESET = "\033[0m"
_OUTPUT_STYLES = {
    "thinking": ("\033[35m", "🧠 thinking"),
    "text": ("\033[32m", "💬 assistant"),
    "tool_use": ("\033[36m", "🛠 tool"),
}


def _styled_output_label(kind: str, detail: str = "") -> str:
    color, label = _OUTPUT_STYLES[kind]
    return f"{color}{label}{detail}{_ANSI_RESET}"

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
        console_mode: str = "off",
        run_console: RunConsole | None = None,
        context_window_override: int | None = None,
    ) -> None:
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**client_kwargs)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._context_window_override = context_window_override
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._cache_enabled = cache_enabled
        self._extended_thinking = extended_thinking
        self._thinking_budget_tokens = thinking_budget_tokens
        self._console_mode = console_mode
        self._run_console = run_console
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
        if self._cache_enabled:
            api_messages = self._with_history_cache_breakpoint(api_messages)

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
                # First of two breakpoints: the system prompt is constant for
                # the whole stage. The second sits at the end of the message
                # history (see _with_history_cache_breakpoint), which is where
                # the tokens actually accumulate.
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

        ``context_window_override`` skips the lookup entirely: some gateways
        don't implement ``models.retrieve()`` in a shape this SDK understands,
        so the call always fails there and this is the only way to stop paying
        for (and logging) a request that can never succeed.
        """
        if self._context_window_override is not None:
            return self._context_window_override
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
                    if self._console_mode == "full":
                        self._drain_stream_to_console(stream)
                    elif self._console_mode == "minimal":
                        self._drain_stream_to_console_minimal(stream, run_console=self._run_console)
                    return stream.get_final_message()
            except AssertionError as exc:
                last_error = exc
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Anthropic stream ended without a final message (attempt %d/%d) — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    delay,
                )
                time.sleep(delay)
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
        open_type: str | None = None
        for event in stream:
            if event.type == "thinking":
                print(event.thinking, end="", file=sys.stderr, flush=True)
            elif event.type == "text":
                print(event.text, end="", file=sys.stderr, flush=True)
            elif event.type == "content_block_start":
                block = event.content_block
                open_type = getattr(block, "type", None)
                if open_type == "tool_use":
                    open_tool = block.name
                    print(
                        f"\n{_styled_output_label('tool_use', f'[{open_tool}]')} ",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                elif open_type == "thinking":
                    print(
                        f"\n{_styled_output_label('thinking')} ",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                elif open_type == "text":
                    print(
                        f"\n{_styled_output_label('text')} ",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
            elif event.type == "input_json":
                print(event.partial_json, end="", file=sys.stderr, flush=True)
            elif event.type == "content_block_stop":
                print(file=sys.stderr, flush=True)
                open_tool = None
                open_type = None
        print(file=sys.stderr, flush=True)

    @staticmethod
    def _drain_stream_to_console_minimal(stream: Any, run_console: RunConsole | None = None) -> None:
        """Print concise, labeled stream output to stderr.

        Assistant prose streams live under a text label, thinking appears under
        a separate thinking label, and tool calls collapse into a single
        labeled line once the call is fully formed.
        """
        open_type: str | None = None
        tool_name: str | None = None
        tool_json = ""
        thinking_text = ""
        text_label_open = False
        for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                open_type = getattr(block, "type", None)
                if open_type == "tool_use":
                    tool_name = block.name
                    tool_json = ""
                    if run_console is not None:
                        run_console.set_activity("tool")
                elif open_type == "text":
                    if run_console is not None:
                        run_console.assistant_label()
                    else:
                        print(f"{_styled_output_label('text')} ", end="", file=sys.stderr, flush=True)
                    text_label_open = True
                elif open_type == "thinking":
                    thinking_text = ""
                    if run_console is not None:
                        run_console.set_activity("thinking")
                    else:
                        print(f"{_styled_output_label('thinking')} ", end="", file=sys.stderr, flush=True)
            elif event.type == "thinking" and open_type == "thinking":
                if run_console is not None:
                    thinking_text += event.thinking
                else:
                    print(event.thinking, end="", file=sys.stderr, flush=True)
            elif event.type == "text" and open_type == "text":
                if run_console is not None:
                    run_console.write_inline(event.text)
                else:
                    print(event.text, end="", file=sys.stderr, flush=True)
            elif event.type == "input_json" and open_type == "tool_use":
                tool_json += event.partial_json
            elif event.type == "content_block_stop":
                if open_type == "tool_use" and tool_name:
                    if run_console is not None:
                        run_console.tool_call(tool_name, tool_json)
                    else:
                        args_preview = preview_json_or_text(tool_json, max_chars=200)
                        print(
                            f"\n{_styled_output_label('tool_use', f' {tool_name}({args_preview})')}",
                            file=sys.stderr,
                            flush=True,
                        )
                elif open_type == "text":
                    if run_console is not None:
                        run_console.write_inline("\n")
                    else:
                        print(file=sys.stderr, flush=True)
                    text_label_open = False
                elif open_type == "thinking":
                    if run_console is not None:
                        run_console.thinking(thinking_text)
                    else:
                        print(file=sys.stderr, flush=True)
                open_type = None
                tool_name = None
                tool_json = ""
                thinking_text = ""
        if text_label_open:
            if run_console is not None:
                run_console.write_inline("\n")
            else:
                print(file=sys.stderr, flush=True)

    @staticmethod
    def _to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Convert provider-agnostic Messages to Anthropic wire format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            result.append({"role": msg.role, "content": msg.content})
        return result

    @staticmethod
    def _with_history_cache_breakpoint(
        api_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Mark the end of the conversation as a prompt-cache breakpoint.

        Caching a stage's system prompt alone leaves most of the bill on the
        table. The system block is a few thousand tokens and constant; the
        message history is the part that grows, because every artifact the
        stage reads lands in a tool result and is then resent on every
        subsequent turn. A stage that reads six upstream artifacts carries tens
        of thousands of tokens for the rest of its run.

        Anthropic matches caches by prefix, so a breakpoint at the current end
        of the history makes turn N+1 read everything through turn N from cache
        at 0.1x and pay full rate only on the delta. The breakpoint moves
        forward each turn; earlier positions stay hittable, so moving it does
        not invalidate what was already written.

        Returns a copy: the blocks handed in belong to the caller's live
        conversation state, and a ``cache_control`` key left behind on them
        would be resent as history on every later turn.
        """
        if not api_messages:
            return api_messages

        last = api_messages[-1]
        content = last.get("content")

        if isinstance(content, str):
            if not content:
                return api_messages
            blocks: list[Any] = [{"type": "text", "text": content}]
        elif isinstance(content, list) and content:
            blocks = list(content)
        else:
            return api_messages

        tail = blocks[-1]
        if not isinstance(tail, dict):
            return api_messages
        # Thinking blocks round-trip with a signature that covers their exact
        # wire shape, so leave them untouched and cache from the block before.
        if tail.get("type") in ("thinking", "redacted_thinking"):
            return api_messages

        blocks[-1] = {**tail, "cache_control": {"type": "ephemeral"}}
        return [*api_messages[:-1], {**last, "content": blocks}]

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
