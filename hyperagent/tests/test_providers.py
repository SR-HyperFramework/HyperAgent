"""Provider layer tests.

Live API tests are skipped unless ``ANTHROPIC_API_KEY`` is set.
"""
from __future__ import annotations

import os
from io import StringIO
from types import SimpleNamespace

import pytest

from hyperagent.config import ProviderConfig
from hyperagent.console import RunConsole
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

    class _StopCall(Exception):
        pass

    class _Messages:
        @staticmethod
        def stream(**kwargs):
            captured.update(kwargs)
            raise _StopCall

    provider._client = type("_C", (), {"messages": _Messages()})()

    with pytest.raises(_StopCall):
        provider.complete([Message(role="user", content="hi")], temperature=0.7)

    assert "temperature" not in captured
    assert "top_p" not in captured and "top_k" not in captured


def test_create_provider_stage_model_override():
    cfg = ProviderConfig(name="anthropic", api_key="sk-test", model="claude-x")
    assert create_provider(cfg, model="claude-y")._model == "claude-y"


def test_create_provider_passes_run_console_to_anthropic():
    console = RunConsole(stream=StringIO())
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"), run_console=console)
    assert provider._run_console is console


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


def test_stream_final_message_assertion_is_retried(monkeypatch):
    provider = create_provider(
        ProviderConfig(name="anthropic", api_key="sk-test")
    )
    provider._max_retries = 2
    monkeypatch.setattr("hyperagent.providers.anthropic_provider.time.sleep", lambda _: None)

    final = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
        model="claude-test",
    )

    class _Stream:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_message(self):
            _Stream.calls += 1
            if _Stream.calls == 1:
                raise AssertionError("missing final message snapshot")
            return final

    class _Messages:
        @staticmethod
        def stream(**kwargs):
            return _Stream()

    provider._client = type("_C", (), {"messages": _Messages()})()

    result = provider.complete([Message(role="user", content="hi")])

    assert result.content == "ok"
    assert _Stream.calls == 2


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


def test_full_console_output_uses_distinct_labels(capsys):
    events = [
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="thinking")),
        SimpleNamespace(type="thinking", thinking="plan"),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text")),
        SimpleNamespace(type="text", text="answer"),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name="lookup")),
        SimpleNamespace(type="input_json", partial_json='{"q":"abc"}'),
        SimpleNamespace(type="content_block_stop"),
    ]

    AnthropicProvider._drain_stream_to_console(events)

    stderr = capsys.readouterr().err
    assert "🧠 thinking" in stderr
    assert "💬 assistant" in stderr
    assert "🛠 tool[lookup]" in stderr



def test_minimal_console_output_uses_distinct_labels(capsys):
    events = [
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="thinking")),
        SimpleNamespace(type="thinking", thinking="plan"),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text")),
        SimpleNamespace(type="text", text="answer"),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name="lookup")),
        SimpleNamespace(type="input_json", partial_json='{"q":"abc"}'),
        SimpleNamespace(type="content_block_stop"),
    ]

    AnthropicProvider._drain_stream_to_console_minimal(events)

    stderr = capsys.readouterr().err
    assert "🧠 thinking" in stderr
    assert "💬 assistant" in stderr
    assert "🛠 tool lookup({\"q\":\"abc\"})" in stderr


def test_minimal_console_output_uses_run_console_and_collapses_tool_args():
    stream = StringIO()
    console = RunConsole(stream=stream, preview_chars=80)
    events = [
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="thinking")),
        SimpleNamespace(type="thinking", thinking="plan" * 40),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text")),
        SimpleNamespace(type="text", text="answer"),
        SimpleNamespace(type="content_block_stop"),
        SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name="lookup")),
        SimpleNamespace(type="input_json", partial_json='{"q":"' + "A" * 120 + '"}'),
        SimpleNamespace(type="content_block_stop"),
    ]

    AnthropicProvider._drain_stream_to_console_minimal(events, run_console=console)

    output = stream.getvalue()
    assert "\033[" not in output
    assert "🧠 plan" in output
    assert "💬 assistant answer" in output
    assert "🛠 tool lookup(" in output
    assert "collapsed" in output


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


# -- prompt-cache breakpoints ------------------------------------------------


def _capture_request(provider, messages, **kwargs) -> dict:
    """Run complete() far enough to capture the outgoing request kwargs."""
    captured: dict = {}

    class _StopCall(Exception):
        pass

    class _Messages:
        @staticmethod
        def stream(**kw):
            captured.update(kw)
            raise _StopCall

    provider._client = type("_C", (), {"messages": _Messages()})()
    with pytest.raises(_StopCall):
        provider.complete(messages, **kwargs)
    return captured


def test_cache_breakpoint_is_placed_on_the_end_of_history():
    """The growing part of the prompt is the history, so cache it too.

    Caching only the system block leaves the tokens that actually accumulate —
    every upstream artifact the stage read, resent on every later turn — billed
    at full rate for the whole stage.
    """
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))
    messages = [
        Message(role="user", content="start"),
        Message(role="assistant", content=[{"type": "text", "text": "thinking about it"}]),
        Message(role="user", content=[
            {"type": "tool_result", "tool_use_id": "t1", "content": "a" * 100},
            {"type": "tool_result", "tool_use_id": "t2", "content": "b" * 100},
        ]),
    ]

    captured = _capture_request(provider, messages, system_prompt="rules")

    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    sent = captured["messages"]
    assert sent[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # Exactly one breakpoint in the history: Anthropic allows at most four, and
    # earlier positions stay hittable without being marked again.
    marked = [
        block
        for msg in sent
        if isinstance(msg["content"], list)
        for block in msg["content"]
        if isinstance(block, dict) and "cache_control" in block
    ]
    assert len(marked) == 1


def test_cache_breakpoint_does_not_mutate_caller_messages():
    """The blocks belong to the agent loop's live history.

    A cache_control key left on them would be replayed as part of the
    conversation on every later turn, planting stale breakpoints throughout.
    """
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))
    block = {"type": "tool_result", "tool_use_id": "t1", "content": "payload"}
    messages = [Message(role="user", content=[block])]

    _capture_request(provider, messages)

    assert "cache_control" not in block
    assert messages[0].content == [block]


def test_cache_breakpoint_skipped_when_caching_disabled():
    """A4_no_cache has to actually remove caching, or the ablation measures nothing."""
    provider = create_provider(
        ProviderConfig(name="anthropic", api_key="sk-test"), cache_enabled=False
    )
    messages = [Message(role="user", content=[{"type": "text", "text": "hello"}])]

    captured = _capture_request(provider, messages, system_prompt="rules")

    assert "cache_control" not in captured["system"][0]
    assert "cache_control" not in captured["messages"][-1]["content"][-1]


def test_cache_breakpoint_never_lands_on_a_thinking_block():
    """Thinking blocks round-trip under a signature covering their wire shape."""
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))
    messages = [
        Message(role="assistant", content=[
            {"type": "thinking", "thinking": "...", "signature": "sig"},
        ]),
    ]

    captured = _capture_request(provider, messages)

    assert "cache_control" not in captured["messages"][-1]["content"][-1]


def test_string_content_is_promoted_to_a_cacheable_block():
    """The first turn of every stage is a plain string prompt."""
    provider = create_provider(ProviderConfig(name="anthropic", api_key="sk-test"))

    captured = _capture_request(provider, [Message(role="user", content="analyse this")])

    block = captured["messages"][-1]["content"][-1]
    assert block["type"] == "text"
    assert block["text"] == "analyse this"
    assert block["cache_control"] == {"type": "ephemeral"}
