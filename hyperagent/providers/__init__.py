"""LLM provider factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .anthropic_provider import AnthropicProvider
from .base import CompletionResult, LLMProvider, Message, ToolCall
from .openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from ..config import ProviderConfig

__all__ = [
    "CompletionResult",
    "LLMProvider",
    "Message",
    "ToolCall",
    "AnthropicProvider",
    "OpenAIProvider",
    "create_provider",
]

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def create_provider(config: ProviderConfig, *, model: str = "") -> LLMProvider:
    """Instantiate the LLM provider described by *config*.

    Parameters
    ----------
    config:
        Provider settings from :func:`hyperagent.config.load_config`.
    model:
        Per-stage model override.  Falls back to ``config.model``, then the
        provider default.
    """
    provider_cls = _PROVIDERS.get(config.name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown provider: {config.name!r}. Supported: {sorted(_PROVIDERS)}"
        )
    if not config.api_key:
        raise ValueError(f"No API key configured for provider {config.name!r}")

    return provider_cls(
        api_key=config.api_key,
        model=model or config.model or _DEFAULT_MODELS[config.name],
        max_output_tokens=config.max_output_tokens,
        temperature=config.temperature,
    )
