"""OpenAI SDK provider stub — interface only, not yet implemented."""
from __future__ import annotations

from typing import Any

from .base import CompletionResult, LLMProvider, Message


class OpenAIProvider(LLMProvider):
    """Placeholder for OpenAI API integration.

    Implements the ``LLMProvider`` interface so the factory can validate
    the provider name, but all runtime methods raise ``NotImplementedError``
    until the OpenAI backend is built out.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        max_output_tokens: int = 16384,
        temperature: float = 0.0,
        **_kwargs: Any,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        raise NotImplementedError(
            "OpenAI provider is not yet implemented. Use 'anthropic' as the provider."
        )

    def count_tokens(self, text: str) -> int:
        # Rough heuristic matching GPT tokenization ratio.
        return max(1, len(text) // 4)

    def max_context_tokens(self) -> int:
        # GPT-4o context window
        return 128_000
