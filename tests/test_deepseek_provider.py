"""Unit tests for the DeepSeek provider in :mod:`schtick.providers`.

No network: the ``openai`` SDK is imported lazily inside the provider's
methods, so a stub module is dropped into ``sys.modules`` before ``configure()``
runs and the real SDK is never constructed. Nothing here needs an API key.
"""

import sys
import types

import pytest

from schtick import persona as persona_module
from schtick import providers
from schtick.providers import DeepSeekProvider


# --- the openai stub -------------------------------------------------------

class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = FakeMessage(content)
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [FakeChoice(content, finish_reason)]


class FakeCompletions:
    """Records the kwargs of the last create() call and replays a canned reply."""

    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        self._client.create_kwargs = kwargs
        return self._client.response


class FakeOpenAI:
    """Stand-in for ``openai.OpenAI``; records how it was constructed."""

    # Set by a test before configure() to control what create() returns.
    next_response = FakeResponse("a fresh line")
    # The most recently constructed instance, so a test can inspect it.
    last = None

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        self.response = FakeOpenAI.next_response
        self.create_kwargs = None
        self.chat = types.SimpleNamespace(completions=FakeCompletions(self))
        FakeOpenAI.last = self


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a stub ``openai`` module for the provider's lazy import."""
    FakeOpenAI.next_response = FakeResponse("a fresh line")
    FakeOpenAI.last = None
    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return FakeOpenAI


@pytest.fixture
def provider(fake_openai):
    """A freshly constructed provider — never the module-level singleton."""
    return DeepSeekProvider()


# --- configure -------------------------------------------------------------

def test_configure_builds_the_client_with_the_key_and_deepseek_base_url(provider, fake_openai):
    provider.configure("sk-deepseek-test")

    assert fake_openai.last.api_key == "sk-deepseek-test"
    assert fake_openai.last.base_url == "https://api.deepseek.com"


def test_generate_before_configure_raises(fake_openai):
    with pytest.raises(RuntimeError, match="before configure"):
        DeepSeekProvider().generate("prompt", "deepseek-flash", {})


# --- generate: request shape ----------------------------------------------

def test_empty_generation_config_disables_thinking(provider, fake_openai):
    provider.configure("sk-test")
    provider.generate("say something", "deepseek-flash", {})

    assert fake_openai.last.create_kwargs == {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "say something"}],
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_generation_config_is_merged_into_the_call(provider, fake_openai):
    provider.configure("sk-test")
    provider.generate("say something", "deepseek-v4-pro", {"temperature": 1.3, "max_tokens": 200})

    assert fake_openai.last.create_kwargs == {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "say something"}],
        "temperature": 1.3,
        "max_tokens": 200,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_generation_config_is_not_mutated_by_generate(provider, fake_openai):
    config = {"temperature": 1.3}
    provider.configure("sk-test")
    provider.generate("say something", "deepseek-flash", config)

    assert config == {"temperature": 1.3}


def test_character_can_enable_thinking(provider, fake_openai):
    config = {
        "reasoning_effort": "low",
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    provider.configure("sk-test")
    provider.generate("p", "deepseek-flash", config)

    assert fake_openai.last.create_kwargs["extra_body"] == config["extra_body"]
    assert fake_openai.last.create_kwargs["reasoning_effort"] == "low"
    assert config["extra_body"] == {"thinking": {"type": "enabled"}}


def test_thinking_default_preserves_other_extra_body_options(provider, fake_openai):
    config = {"extra_body": {"custom_option": True}}
    provider.configure("sk-test")
    provider.generate("p", "deepseek-flash", config)

    assert fake_openai.last.create_kwargs["extra_body"] == {
        "custom_option": True,
        "thinking": {"type": "disabled"},
    }
    assert config == {"extra_body": {"custom_option": True}}


# --- generate: response handling ------------------------------------------

def test_generate_returns_the_message_content(provider, fake_openai):
    fake_openai.next_response = FakeResponse("I'll tell you what the problem is.")
    provider.configure("sk-test")

    assert provider.generate("p", "deepseek-flash", {}) == "I'll tell you what the problem is."


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_content_raises(provider, fake_openai, content):
    fake_openai.next_response = FakeResponse(content)
    provider.configure("sk-test")

    with pytest.raises(RuntimeError, match="no text"):
        provider.generate("p", "deepseek-flash", {})


def test_content_filter_finish_reason_raises(provider, fake_openai):
    fake_openai.next_response = FakeResponse("partial", finish_reason="content_filter")
    provider.configure("sk-test")

    with pytest.raises(RuntimeError, match="content_filter"):
        provider.generate("p", "deepseek-flash", {})


# --- registration ----------------------------------------------------------

def test_deepseek_is_registered():
    assert "deepseek" in providers.available_providers()
    assert providers.get_provider("deepseek").name == "deepseek"


def test_deepseek_declares_its_key_env_and_default_model():
    deepseek = providers.get_provider("deepseek")
    assert deepseek.api_key_env == "DEEPSEEK_API_KEY"
    assert deepseek.default_model == "deepseek-flash"
    assert deepseek.signup_url == "platform.deepseek.com"


def test_gemini_is_still_the_default_provider():
    assert providers.DEFAULT_PROVIDER == "gemini"


# --- a character can ask for it -------------------------------------------

CHARACTER_FILE = """\
---
name: Deep Thoughts
provider: deepseek
generation:
  temperature: 1.2
---
You are a character. Say something.
"""


def test_a_persona_can_select_deepseek(tmp_path, monkeypatch):
    (tmp_path / "deep_thoughts.md").write_text(CHARACTER_FILE, encoding="utf-8")
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(tmp_path))

    loaded = persona_module.load_persona("deep_thoughts")

    assert loaded.PROVIDER == "deepseek"
    assert loaded.MODEL == ""  # empty means the provider's default_model
    assert loaded.GENERATION_CONFIG == {"temperature": 1.2}
