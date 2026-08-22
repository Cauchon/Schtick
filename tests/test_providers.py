"""Unit tests for the registry and the Gemini/Anthropic providers.

No network: both SDKs are imported lazily inside the provider methods, so stub
modules are dropped into ``sys.modules`` before ``configure()`` runs and the
real clients are never constructed. Nothing here needs an API key.

DeepSeek has its own file (tests/test_deepseek_provider.py); it is not
re-tested here.
"""

import logging
import sys
import types

import pytest

from schtick import providers
from schtick.providers import AnthropicProvider, GeminiProvider


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

def test_available_providers_is_sorted():
    names = providers.available_providers()
    assert names == sorted(names)


def test_available_providers_lists_every_shipped_service():
    assert set(providers.available_providers()) == {"anthropic", "deepseek", "gemini"}


def test_get_provider_returns_the_singleton_registered_under_the_name():
    assert providers.get_provider("gemini") is providers.PROVIDERS["gemini"]
    assert providers.get_provider("gemini").name == "gemini"


def test_get_provider_error_names_the_bad_value_and_lists_the_valid_ones():
    with pytest.raises(ValueError) as exc:
        providers.get_provider("openai")

    message = str(exc.value)
    assert "Unknown provider 'openai'" in message
    for name in providers.available_providers():
        assert name in message


def test_every_registered_provider_declares_the_engine_contract():
    for name, provider in providers.PROVIDERS.items():
        assert provider.name == name
        assert provider.api_key_env.endswith("_API_KEY")
        assert provider.default_model
        assert provider.signup_url


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

class FakeGenerateContentConfig:
    """Stand-in for ``types.GenerateContentConfig``; records its kwargs."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeModels:
    def __init__(self, client):
        self._client = client

    def generate_content(self, **kwargs):
        self._client.create_kwargs = kwargs
        return self._client.response


class FakeGenaiClient:
    """Stand-in for ``genai.Client``; records how it was constructed."""

    next_text = "a fresh line"
    last = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.response = types.SimpleNamespace(text=FakeGenaiClient.next_text)
        self.create_kwargs = None
        self.models = FakeModels(self)
        FakeGenaiClient.last = self


@pytest.fixture
def fake_genai(monkeypatch):
    """Install stub ``google`` / ``google.genai`` modules for the lazy imports."""
    FakeGenaiClient.next_text = "a fresh line"
    FakeGenaiClient.last = None

    genai_types = types.ModuleType("google.genai.types")
    genai_types.GenerateContentConfig = FakeGenerateContentConfig

    genai_module = types.ModuleType("google.genai")
    genai_module.Client = FakeGenaiClient
    genai_module.types = genai_types

    google_module = types.ModuleType("google")
    google_module.genai = genai_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    return FakeGenaiClient


@pytest.fixture
def gemini(fake_genai):
    """A freshly constructed provider — never the module-level singleton."""
    return GeminiProvider()


def test_gemini_declares_its_key_env_and_default_model():
    gemini_singleton = providers.get_provider("gemini")
    assert gemini_singleton.api_key_env == "GEMINI_API_KEY"
    assert gemini_singleton.default_model == "gemini-3.6-flash"
    assert providers.DEFAULT_PROVIDER == "gemini"


def test_gemini_configure_builds_a_per_instance_client_with_the_key(gemini, fake_genai):
    gemini.configure("gemini-test-key")

    assert fake_genai.last.api_key == "gemini-test-key"


def test_gemini_generate_before_configure_raises(fake_genai):
    with pytest.raises(RuntimeError, match="before configure"):
        GeminiProvider().generate("prompt", "gemini-3.6-flash", {})


@pytest.mark.parametrize("empty_config", [{}, None])
def test_gemini_passes_no_config_kwarg_at_all_when_the_config_is_falsy(
    gemini, fake_genai, empty_config
):
    # Kramer's frontmatter deliberately omits `generation`; absent must mean NO
    # config kwarg, not an empty GenerateContentConfig — see CLAUDE.md.
    gemini.configure("k")
    gemini.generate("say something", "gemini-3.6-flash", empty_config)

    assert fake_genai.last.create_kwargs == {
        "model": "gemini-3.6-flash",
        "contents": "say something",
    }
    assert "config" not in fake_genai.last.create_kwargs


def test_gemini_wraps_a_populated_config_in_a_generate_content_config(gemini, fake_genai):
    gemini.configure("k")
    gemini.generate("say something", "gemini-3.6-flash", {"temperature": 1.1})

    kwargs = fake_genai.last.create_kwargs
    assert kwargs["model"] == "gemini-3.6-flash"
    assert kwargs["contents"] == "say something"
    assert isinstance(kwargs["config"], FakeGenerateContentConfig)
    assert kwargs["config"].kwargs == {"temperature": 1.1}


def test_gemini_returns_the_response_text(gemini, fake_genai):
    fake_genai.next_text = "I'll tell you what the problem is."
    gemini.configure("k")

    assert gemini.generate("p", "gemini-3.6-flash", {}) == (
        "I'll tell you what the problem is."
    )


@pytest.fixture
def genai_logger():
    """Restore the SDK logger's level, which configure() raises as a side effect."""
    logger = logging.getLogger(providers.GENAI_LOGGER_NAME)
    original = logger.level
    yield logger
    logger.setLevel(original)


def test_gemini_configure_silences_the_afc_warning(gemini, fake_genai, genai_logger):
    # The SDK warns on every generate_content call that AFC belongs in
    # Chat.send_message. We pass no tools, so it is noise in the bot's log.
    genai_logger.setLevel(logging.NOTSET)
    assert genai_logger.isEnabledFor(logging.WARNING)  # noisy by default

    gemini.configure("k")

    assert not genai_logger.isEnabledFor(logging.WARNING)


def test_gemini_configure_still_lets_sdk_errors_through(gemini, fake_genai, genai_logger):
    gemini.configure("k")

    assert genai_logger.isEnabledFor(logging.ERROR)
    assert genai_logger.isEnabledFor(logging.CRITICAL)


def test_gemini_quieting_is_scoped_to_the_sdk_logger(gemini, fake_genai, genai_logger):
    # Only the one SDK logger gets a level of its own: the root logger the bot
    # configures, and the bot's own loggers, keep whatever they had.
    root_level = logging.getLogger().level
    bot_level = logging.getLogger("schtick.bot").level

    gemini.configure("k")

    assert providers.GENAI_LOGGER_NAME == "google_genai.models"
    assert logging.getLogger().level == root_level
    assert logging.getLogger("schtick.bot").level == bot_level


@pytest.mark.parametrize("text", [None, "", "   "])
def test_gemini_empty_or_none_text_raises(gemini, fake_genai, text):
    # The new SDK returns None where the old one raised; the provider must raise
    # so the bot's fallback path fires instead of blowing up on None.strip().
    fake_genai.next_text = text
    gemini.configure("k")

    with pytest.raises(RuntimeError, match="no text"):
        gemini.generate("p", "gemini-3.6-flash", {})


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #

class FakeBlock:
    def __init__(self, block_type, text=""):
        self.type = block_type
        self.text = text


class FakeAnthropicResponse:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        self._client.create_kwargs = kwargs
        return self._client.response


class FakeAnthropicClient:
    """Stand-in for ``anthropic.Anthropic``; records how it was constructed."""

    next_response = None
    last = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.response = FakeAnthropicClient.next_response
        self.create_kwargs = None
        self.messages = FakeMessages(self)
        FakeAnthropicClient.last = self


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Install a stub ``anthropic`` module for the provider's lazy import."""
    FakeAnthropicClient.next_response = FakeAnthropicResponse([FakeBlock("text", "a fresh line")])
    FakeAnthropicClient.last = None
    module = types.ModuleType("anthropic")
    module.Anthropic = FakeAnthropicClient
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return FakeAnthropicClient


@pytest.fixture
def claude(fake_anthropic):
    """A freshly constructed provider — never the module-level singleton."""
    return AnthropicProvider()


def test_anthropic_declares_its_key_env_and_default_model():
    claude_singleton = providers.get_provider("anthropic")
    assert claude_singleton.api_key_env == "ANTHROPIC_API_KEY"
    assert claude_singleton.default_model == "claude-sonnet-5"


def test_anthropic_configure_builds_the_client_with_the_key(claude, fake_anthropic):
    claude.configure("sk-ant-test")

    assert fake_anthropic.last.api_key == "sk-ant-test"


def test_anthropic_generate_before_configure_raises(fake_anthropic):
    with pytest.raises(RuntimeError, match="before configure"):
        AnthropicProvider().generate("prompt", "claude-sonnet-5", {})


def test_anthropic_defaults_max_tokens_to_4096(claude, fake_anthropic):
    # Thinking shares the max_tokens ceiling with the visible answer, so a
    # quote-sized budget would truncate the reply — see CLAUDE.md.
    claude.configure("k")
    claude.generate("say something", "claude-sonnet-5", {})

    assert fake_anthropic.last.create_kwargs == {
        "model": "claude-sonnet-5",
        "messages": [{"role": "user", "content": "say something"}],
        "max_tokens": AnthropicProvider.DEFAULT_MAX_TOKENS,
    }
    assert AnthropicProvider.DEFAULT_MAX_TOKENS == 4096


def test_anthropic_generation_config_merges_in_and_can_override_max_tokens(
    claude, fake_anthropic
):
    claude.configure("k")
    claude.generate(
        "say something",
        "claude-sonnet-5",
        {"max_tokens": 1024, "system": "be brief"},
    )

    assert fake_anthropic.last.create_kwargs == {
        "model": "claude-sonnet-5",
        "messages": [{"role": "user", "content": "say something"}],
        "max_tokens": 1024,
        "system": "be brief",
    }


def test_anthropic_does_not_mutate_the_characters_generation_config(claude, fake_anthropic):
    config = {"system": "be brief"}
    claude.configure("k")
    claude.generate("say something", "claude-sonnet-5", config)

    assert config == {"system": "be brief"}


def test_anthropic_returns_the_text_block(claude, fake_anthropic):
    fake_anthropic.next_response = FakeAnthropicResponse(
        [FakeBlock("text", "I'll tell you what the problem is.")]
    )
    claude.configure("k")

    assert claude.generate("p", "claude-sonnet-5", {}) == (
        "I'll tell you what the problem is."
    )


def test_anthropic_ignores_thinking_blocks_and_concatenates_only_text(claude, fake_anthropic):
    fake_anthropic.next_response = FakeAnthropicResponse([
        FakeBlock("thinking", "let me consider the premise"),
        FakeBlock("text", "the visible "),
        FakeBlock("redacted_thinking", "more thinking"),
        FakeBlock("text", "answer"),
    ])
    claude.configure("k")

    assert claude.generate("p", "claude-sonnet-5", {}) == "the visible answer"


def test_anthropic_refusal_stop_reason_raises(claude, fake_anthropic):
    fake_anthropic.next_response = FakeAnthropicResponse(
        [FakeBlock("text", "partial")], stop_reason="refusal"
    )
    claude.configure("k")

    with pytest.raises(RuntimeError, match="refusal"):
        claude.generate("p", "claude-sonnet-5", {})


@pytest.mark.parametrize(
    "blocks",
    [
        [],
        [FakeBlock("text", "")],
        [FakeBlock("text", "   ")],
        [FakeBlock("thinking", "only thought about it")],
    ],
    ids=["no-blocks", "empty-text", "whitespace-text", "thinking-only"],
)
def test_anthropic_empty_text_raises(claude, fake_anthropic, blocks):
    fake_anthropic.next_response = FakeAnthropicResponse(blocks, stop_reason="max_tokens")
    claude.configure("k")

    with pytest.raises(RuntimeError, match="no text"):
        claude.generate("p", "claude-sonnet-5", {})


def test_anthropic_empty_text_error_points_at_max_tokens(claude, fake_anthropic):
    fake_anthropic.next_response = FakeAnthropicResponse([], stop_reason="max_tokens")
    claude.configure("k")

    with pytest.raises(RuntimeError) as exc:
        claude.generate("p", "claude-sonnet-5", {})

    assert "max_tokens" in str(exc.value)
