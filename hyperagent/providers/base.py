"""Abstract base classes and data models for the LLM provider layer."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Message model — provider-agnostic conversation representation
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """Single conversation turn.

    ``role`` follows the Anthropic convention:
      - ``"user"``      — human or tool-result turn
      - ``"assistant"``  — model turn (may contain tool_use blocks)
    """

    role: str
    content: str | list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Tool call model
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


# ---------------------------------------------------------------------------
# Completion result
# ---------------------------------------------------------------------------

@dataclass
class CompletionResult:
    """Normalized result from any LLM provider."""

    content: str
    """Plain-text portion of the model's response (may be empty when tool_use)."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    """Tool-use blocks the model wants executed."""

    stop_reason: str = "end_turn"
    """Why the model stopped: ``end_turn``, ``tool_use``, ``max_tokens``."""

    input_tokens: int = 0
    output_tokens: int = 0

    # -- Anthropic prompt-caching fields (RQ2 measurement) -------------------

    cache_creation_input_tokens: int = 0
    """Tokens written to Anthropic's prompt cache this turn (billed at 1.25× rate).

    Non-zero only on the first turn of a stage (or after cache expiry).  Always
    zero for providers that do not support prompt caching.
    """

    cache_read_input_tokens: int = 0
    """Tokens read from Anthropic's prompt cache this turn (billed at 0.10× rate).

    Non-zero on turns 2…N of a stage when the system prompt is stable and cached.
    Always zero for providers that do not support prompt caching.
    """

    model: str = ""
    """Actual model id used for this completion."""

    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)
    """Raw ``thinking``/``redacted_thinking`` content blocks, in response order.

    Only non-empty when extended thinking is enabled. Must be replayed verbatim
    (including their signatures) at the start of the assistant turn's content
    when the conversation continues, or the next request is rejected.
    """


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Provider-agnostic interface that every backend must implement."""

    accepts_temperature: bool = True
    """Whether this backend accepts sampling parameters.

    False for Anthropic: ``temperature``/``top_p``/``top_k`` were removed on
    Claude Opus 4.7 and later, and sending a non-default value returns a 400.
    The factory reads this instead of hardcoding a provider name.
    """

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        """Send a completion request and return the normalized result.

        Parameters
        ----------
        messages:
            Conversation history in provider-agnostic format.
        tools:
            Tool definitions in **Anthropic-native** JSON Schema format.
            Providers that use a different wire format (e.g. OpenAI) must
            translate internally.
        system_prompt:
            Top-level system instructions.  Passed outside the messages
            array so each provider can place it correctly.
        max_tokens:
            Maximum output tokens for this call.  ``None`` uses the value the
            provider was constructed with.
        temperature:
            Sampling temperature.  ``None`` uses the provider's configured value.
        """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return a best-effort token count for *text*."""

    @abstractmethod
    def max_context_tokens(self) -> int:
        """Return the context window size for the configured model."""

    # -- convenience ----------------------------------------------------------

    def estimate_message_tokens(self, messages: list[Message]) -> int:
        """Rough token estimate for the full message array."""
        return sum(self.count_tokens(t) for m in messages for t in _message_texts(m))

    def context_usage_ratio(self, messages: list[Message]) -> float:
        """Fraction of the context window consumed by *messages*."""
        cap = self.max_context_tokens()
        return self.estimate_message_tokens(messages) / cap if cap > 0 else 1.0


def _message_texts(message: Message) -> list[str]:
    """Extract the billable text of a message, one string per content block.

    Counting ``str(block)`` instead would fold Python dict punctuation and
    repr-quoted payloads into the estimate, which badly inflates tool results.
    """
    if isinstance(message.content, str):
        return [message.content]

    texts: list[str] = []
    for block in message.content:
        if not isinstance(block, dict):
            texts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            texts.append(str(block.get("text", "")))
        elif kind == "tool_use":
            texts.append(str(block.get("name", "")))
            texts.append(json.dumps(block.get("input", {}), separators=(",", ":")))
        elif kind == "tool_result":
            content = block.get("content", "")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for sub in content:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        texts.append(str(sub.get("text", "")))
                    else:
                        texts.append(str(sub))
            else:
                texts.append(str(content))
        else:
            texts.append(json.dumps(block, separators=(",", ":"), default=str))
    return [t for t in texts if t]
