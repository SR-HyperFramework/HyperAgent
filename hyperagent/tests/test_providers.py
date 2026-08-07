"""Provider layer tests.

Live API tests are skipped unless ``ANTHROPIC_API_KEY`` is set.
"""
from __future__ import annotations

import os

import pytest

from hyperagent.config import ProviderConfig
from hyperagent.providers import (
    DEFAULT_ANTHROPIC_MODEL,
    AnthropicProvider,
    LLMProvider,
    Message,
    OpenAIProvider,
    create_provider,
)

live = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


class _CharProvider(LLMProvider):
    """Counts characters so token math is exactly predictable."""

    def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None,
                 temperature=None):
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text)

    def max_context_tokens(self) -> int:
        return 1000


# -- factory ----------------------------------------------------------------

def test_create_provider_reads_provider_config():
    cfg = ProviderConfig(name="anthropic", api_key="sk-test", model="claude-x",
                         max_output_tokens=1234)
    provider = create_provider(cfg)
    assert isinstance(provider, AnthropicProvider)
    assert provider._model == "claude-x"
    assert provider._max_output_tokens == 1234


def test_create_provider_resolves_default_model():
    """An empty config model falls through to the provider default, so the id
    lives in exactly one place instead of being repeated across config files."""
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))
    assert provider._model == DEFAULT_ANTHROPIC_MODEL


def test_configured_temperature_is_not_forwarded_to_anthropic():
    """Sampling parameters were removed on Claude Opus 4.7+; a non-default value
    returns a 400, so a configured temperature must never reach the client."""
    cfg = ProviderConfig(name="anthropic", api_key="sk-test", temperature=0.7)
    provider = create_provider(cfg)
    assert provider.accepts_temperature is False
    assert not hasattr(provider, "_temperature")


def test_complete_omits_temperature_from_request():
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))
    captured: dict = {}

    class _Messages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            raise _StopCall

    class _StopCall(Exception):
        pass

    provider._client = type("_C", (), {"messages": _Messages()})()

    with pytest.raises(_StopCall):
        provider.complete([Message(role="user", content="hi")], temperature=0.7)

    assert "temperature" not in captured
    assert "top_p" not in captured and "top_k" not in captured


def test_create_provider_stage_model_override():
    cfg = ProviderConfig(name="anthropic", api_key="sk-test", model="claude-x")
    assert create_provider(cfg, model="claude-y")._model == "claude-y"


def test_create_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider(ProviderConfig(name="bedrock", api_key="k"))


def test_create_provider_requires_api_key():
    with pytest.raises(ValueError, match="No API key"):
        create_provider(ProviderConfig(name="anthropic", api_key=""))


def test_openai_stub_raises_not_implemented():
    provider = create_provider(ProviderConfig(name="openai", api_key="sk-test"))
    assert isinstance(provider, OpenAIProvider)
    with pytest.raises(NotImplementedError):
        provider.complete([Message(role="user", content="hi")])


# -- token accounting -------------------------------------------------------

def test_estimate_counts_text_blocks_not_repr():
    provider = _CharProvider()
    plain = [Message(role="user", content="abcde")]
    blocked = [Message(role="user", content=[{"type": "text", "text": "abcde"}])]
    assert provider.estimate_message_tokens(plain) == 5
    assert provider.estimate_message_tokens(blocked) == 5


def test_estimate_excludes_tool_result_envelope():
    provider = _CharProvider()
    payload = "x" * 100
    messages = [
        Message(
            role="user",
            content=[
                {"type": "tool_result", "tool_use_id": "toolu_0123456789abcdef",
                 "content": payload, "is_error": False},
            ],
        )
    ]
    assert provider.estimate_message_tokens(messages) == len(payload)


def test_estimate_handles_nested_tool_result_content():
    provider = _CharProvider()
    messages = [
        Message(
            role="user",
            content=[
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "abc"},
                             {"type": "text", "text": "de"}]},
            ],
        )
    ]
    assert provider.estimate_message_tokens(messages) == 5


def test_context_usage_ratio():
    provider = _CharProvider()
    messages = [Message(role="user", content="x" * 250)]
    assert provider.context_usage_ratio(messages) == pytest.approx(0.25)


# -- live API ---------------------------------------------------------------

@live
def test_count_tokens_matches_api_within_10_percent():
    provider = create_provider(
        ProviderConfig(name="anthropic", api_key=os.environ["ANTHROPIC_API_KEY"])
    )
    text = "The quick brown fox jumps over the lazy dog. " * 20
    count = provider.count_tokens(text)
    reference = provider._client.messages.count_tokens(
        model=provider._model,
        messages=[{"role": "user", "content": text}],
    ).input_tokens
    assert abs(count - reference) <= reference * 0.10


@live
def test_count_tokens_is_cached():
    provider = create_provider(
        ProviderConfig(name="anthropic", api_key=os.environ["ANTHROPIC_API_KEY"])
    )
    text = "cache me"
    first = provider.count_tokens(text)
    assert provider._token_cache[text] == first
    provider._client = None  # any further API call would raise
    assert provider.count_tokens(text) == first


@live
def test_single_turn_completion():
    provider = create_provider(
        ProviderConfig(name="anthropic", api_key=os.environ["ANTHROPIC_API_KEY"],
                       max_output_tokens=64)
    )
    result = provider.complete(
        [Message(role="user", content="Reply with exactly: PONG")],
        system_prompt="You are a test fixture. Follow the instruction literally.",
    )
    assert "PONG" in result.content
    assert result.stop_reason == "end_turn"
    assert result.input_tokens > 0 and result.output_tokens > 0
