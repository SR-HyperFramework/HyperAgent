"""LLM provider factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .anthropic_provider import DEFAULT_MODEL as DEFAULT_ANTHROPIC_MODEL
from .anthropic_provider import AnthropicProvider
from .base import CompletionResult, LLMProvider, Message, ToolCall
from .openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from ..config import ProviderConfig
    from ..console import RunConsole

__all__ = [
    "CompletionResult",
    "LLMProvider",
    "Message",
    "ToolCall",
    "AnthropicProvider",
    "OpenAIProvider",
    "DEFAULT_ANTHROPIC_MODEL",
    "create_provider",
]

_DEFAULT_MODELS = {
    "anthropic": DEFAULT_ANTHROPIC_MODEL,
    "openai": "gpt-4o",
}

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def create_provider(
    config: ProviderConfig,
    *,
    model: str = "",
    cache_enabled: bool = True,
    run_console: RunConsole | None = None,
) -> LLMProvider:
    """Instantiate the LLM provider described by *config*.

    Parameters
    ----------
    config:
        Provider settings from :func:`hyperagent.config.load_config`.
    model:
        Per-stage model override.  Falls back to ``config.model``, then the
        provider default.
    cache_enabled:
        Whether provider-level prompt caching should be enabled where supported.
    run_console:
        Optional console renderer for minimal live output.
    """
    provider_cls = _PROVIDERS.get(config.name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown provider: {config.name!r}. Supported: {sorted(_PROVIDERS)}"
        )
    if not config.api_key:
        raise ValueError(f"No API key configured for provider {config.name!r}")

    kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "model": model or config.model or _DEFAULT_MODELS[config.name],
        "max_output_tokens": config.max_output_tokens,
    }
    if config.name == "anthropic":
        kwargs["cache_enabled"] = cache_enabled
        kwargs["extended_thinking"] = config.extended_thinking
        kwargs["thinking_budget_tokens"] = config.thinking_budget_tokens
        kwargs["console_mode"] = config.console_mode
        kwargs["run_console"] = run_console
        if config.base_url:
            kwargs["base_url"] = config.base_url
    # Only backends that still accept sampling parameters get one. Anthropic
    # removed them on Opus 4.7+, so forwarding a configured temperature there
    # would 400 every request.
    if config.temperature is not None and provider_cls.accepts_temperature:
        kwargs["temperature"] = config.temperature

    return provider_cls(**kwargs)
