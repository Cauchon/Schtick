"""Offline OpenAI provider tests: the SDK client is always a recording stub."""

from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest
from openai.types.responses import Response

from schtick import generation, persona, providers
from schtick.providers import OpenAIProvider


def response(text="A fresh line.", status="completed", output=None, reason=None):
    return SimpleNamespace(
        output_text=text,
        status=status,
        output=output or [],
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
    )


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(reply=response(), calls=[], client_options=None)

    def create(**kwargs):
        state.calls.append(kwargs)
        if isinstance(state.reply, Exception):
            raise state.reply
        return state.reply

    def client(**kwargs):
        state.client_options = kwargs
        return SimpleNamespace(responses=SimpleNamespace(create=create))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=client))
    return state


@pytest.fixture
def provider(sdk):
    selected = OpenAIProvider()
    selected.configure("sk-offline-test")
    return selected


def test_configure_uses_openai_and_leaves_retries_to_generation(provider, sdk):
    assert sdk.client_options == {
        "api_key": "sk-offline-test", "max_retries": 0, "timeout": 60.0,
    }


def test_generate_before_configure_raises():
    with pytest.raises(RuntimeError, match="before configure"):
        OpenAIProvider().generate("prompt", "gpt-6-luna", {})


def test_default_request_uses_responses_low_effort_and_no_storage(provider, sdk):
    assert provider.generate("Say something.", "gpt-6-luna", {}) == "A fresh line."
    assert sdk.calls == [{
        "model": "gpt-6-luna",
        "input": "Say something.",
        "reasoning": {"effort": "low"},
        "store": False,
    }]


def test_native_options_override_defaults_without_mutation(provider, sdk):
    config = {
        "reasoning": {"effort": "none"},
        "store": True,
        "text": {"verbosity": "low"},
        "max_output_tokens": 2048,
    }
    original = deepcopy(config)
    provider.generate("prompt", "another-model", config)
    assert sdk.calls[0] == {"model": "another-model", "input": "prompt", **original}
    assert config == original


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled", "in_progress"])
def test_unfinished_response_is_rejected_even_with_short_text(provider, sdk, status):
    sdk.reply = response("A truncated sentence that", status=status, reason="max_output_tokens")
    with pytest.raises(RuntimeError, match="not completed") as exc:
        provider.generate("prompt", "gpt-6-luna", {})
    assert status in str(exc.value)
    assert "max_output_tokens" in str(exc.value)


def test_refusal_is_rejected_even_with_partial_text(provider, sdk):
    sdk.reply = response("Some text", output=[
        SimpleNamespace(type="reasoning"),
        SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")]),
    ])
    with pytest.raises(RuntimeError, match="refusal"):
        provider.generate("prompt", "gpt-6-luna", {})


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_reply_raises(provider, sdk, text):
    sdk.reply = response(text)
    with pytest.raises(RuntimeError, match="no text"):
        provider.generate("prompt", "gpt-6-luna", {})


def test_sdk_aggregates_visible_text_without_reasoning(provider, sdk):
    # Use a real SDK response to exercise its output_text property, without
    # constructing a client or making any network request.
    sdk.reply = Response.model_validate({
        "id": "resp_offline", "object": "response", "created_at": 0,
        "model": "gpt-6-luna", "status": "completed", "parallel_tool_calls": True,
        "tool_choice": "auto", "tools": [],
        "output": [
            {"id": "rs_offline", "type": "reasoning", "summary": []},
            {"id": "msg_offline", "type": "message", "role": "assistant",
             "status": "completed", "content": [
                 {"type": "output_text", "text": "A fresh ", "annotations": []},
                 {"type": "output_text", "text": "line.", "annotations": []},
             ]},
        ],
    })
    assert provider.generate("prompt", "gpt-6-luna", {}) == "A fresh line."


def test_persona_dispatch_reads_openai_key_and_strips_wrapping_quotes(
    tmp_path, monkeypatch, provider, sdk,
):
    (tmp_path / "aunt_carol.md").write_text(
        '---\nname: Aunt Carol\nprovider: openai\n---\nSay something.\n', encoding="utf-8",
    )
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-offline-persona")
    monkeypatch.setitem(providers.PROVIDERS, "openai", provider)
    selected = persona.load_persona("aunt_carol")
    sdk.reply = response('"A fresh line."')

    assert generation.configure(selected) is provider
    assert sdk.client_options["api_key"] == "sk-offline-persona"
    assert generation.generate_quote(selected, []) == "A fresh line."
    assert sdk.calls[0]["model"] == "gpt-6-luna"


def test_missing_openai_key_is_reported(monkeypatch, provider):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(providers.PROVIDERS, "openai", provider)
    selected = SimpleNamespace(PROVIDER="openai", SLUG="aunt_carol")
    with pytest.raises(ValueError, match="Missing OPENAI_API_KEY"):
        generation.configure(selected)


@pytest.mark.parametrize("status, attempts", [(429, 5), (503, 5), (401, 1)])
def test_sdk_status_errors_follow_shared_retry_policy(
    monkeypatch, provider, sdk, recorded_sleeps, status, attempts,
):
    class StatusError(Exception):
        status_code = status

    sdk.reply = StatusError("offline provider error")
    monkeypatch.setitem(providers.PROVIDERS, "openai", provider)
    selected = SimpleNamespace(
        PROVIDER="openai", MODEL="", PROMPT="Say something.", GENERATION_CONFIG={},
    )
    with pytest.raises(StatusError):
        generation.generate_quote(selected, [])
    assert len(sdk.calls) == attempts
    assert len(recorded_sleeps) == attempts - 1


def test_openai_is_registered_with_its_own_credentials():
    selected = providers.get_provider("openai")
    assert isinstance(selected, OpenAIProvider)
    assert selected.api_key_env == "OPENAI_API_KEY"
    assert selected.default_model == "gpt-6-luna"
    assert selected.signup_url == "platform.openai.com"
    assert providers.DEFAULT_PROVIDER == "gemini"
