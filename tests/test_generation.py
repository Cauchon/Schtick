"""Unit tests for prompt building and provider dispatch in :mod:`schtick.generation`.

No network and no API keys: the provider is a recording stub registered into
``providers.PROVIDERS`` for the duration of a test, so ``configure()`` and
``generate_quote()`` never reach a real SDK.
"""

import pytest

from schtick import generation, providers
from schtick.generation import (
    RECENT_QUOTES_PLACEHOLDER,
    build_prompt,
    format_recent_quotes,
)


class StubPersona:
    """The three attributes generation.py actually reads, plus a slug for errors."""

    def __init__(self, prompt="", slug="test_persona", provider="fake",
                 model="", generation_config=None):
        self.SLUG = slug
        self.PROMPT = prompt
        self.PROVIDER = provider
        self.MODEL = model
        self.GENERATION_CONFIG = generation_config if generation_config is not None else {}


class FakeProvider:
    """Records configure()/generate() calls and replays a canned quote."""

    name = "fake"
    api_key_env = "FAKE_API_KEY"
    default_model = "fake-default-model"
    signup_url = "example.invalid"

    def __init__(self, reply="a fresh line"):
        self.reply = reply
        self.configured_with = None
        self.generate_calls = []

    def configure(self, api_key):
        self.configured_with = api_key

    def generate(self, prompt, model, generation_config):
        self.generate_calls.append((prompt, model, generation_config))
        return self.reply


@pytest.fixture
def fake_provider(monkeypatch):
    """Register a stub provider under the name 'fake' for one test."""
    provider = FakeProvider()
    monkeypatch.setitem(providers.PROVIDERS, "fake", provider)
    monkeypatch.delenv(provider.api_key_env, raising=False)
    return provider


# --- format_recent_quotes --------------------------------------------------

def test_format_recent_quotes_is_empty_for_no_quotes():
    assert format_recent_quotes([]) == ""


def test_format_recent_quotes_wraps_a_single_quote_in_double_quotes():
    assert format_recent_quotes(["one"]) == '"one"'


def test_format_recent_quotes_joins_with_a_bulleted_indent():
    # The exact separator is load-bearing: it lands inside an already-indented
    # prompt body, so the legacy rendering is reproduced character for character.
    assert format_recent_quotes(["one", "two"]) == '"one"\n    - "two"'


# --- build_prompt: the placeholder is inline -------------------------------

def test_placeholder_is_replaced_in_place():
    persona = StubPersona(f"before\n    - {RECENT_QUOTES_PLACEHOLDER}\nafter")

    assert build_prompt(persona, ["one", "two"]) == (
        'before\n    - "one"\n    - "two"\nafter'
    )


def test_an_inline_placeholder_suppresses_the_trailer():
    persona = StubPersona(f"body {RECENT_QUOTES_PLACEHOLDER} end")
    built = build_prompt(persona, ["one"])

    assert built == 'body "one" end'
    assert "AVOID repeating" not in built


def test_every_occurrence_of_the_placeholder_is_replaced():
    persona = StubPersona(f"{RECENT_QUOTES_PLACEHOLDER}|{RECENT_QUOTES_PLACEHOLDER}")

    assert build_prompt(persona, ["one"]) == '"one"|"one"'


def test_an_inline_placeholder_with_no_recent_quotes_leaves_a_blank():
    persona = StubPersona(f"body\n{RECENT_QUOTES_PLACEHOLDER}\n")

    assert build_prompt(persona, []) == "body\n\n"


# --- build_prompt: the trailer path ----------------------------------------

def test_a_prompt_without_the_placeholder_gets_the_trailer_appended():
    persona = StubPersona("Say something.")
    built = build_prompt(persona, ["one", "two"])

    assert built.startswith("Say something.")
    assert built == "Say something." + generation.RECENT_QUOTES_TRAILER.replace(
        RECENT_QUOTES_PLACEHOLDER, '"one"\n    - "two"'
    )
    assert "AVOID repeating" in built


def test_the_trailer_still_appears_with_no_recent_quotes():
    persona = StubPersona("Say something.")
    built = build_prompt(persona, [])

    assert built.startswith("Say something.")
    assert "AVOID repeating" in built
    assert RECENT_QUOTES_PLACEHOLDER not in built


# --- build_prompt: literal braces ------------------------------------------

def test_literal_braces_in_a_prompt_survive_untouched():
    # build_prompt uses str.replace, NOT str.format, precisely so that
    # user-authored prose may contain braces.
    body = "Use {curly} braces and {} and {0} freely. " + RECENT_QUOTES_PLACEHOLDER
    persona = StubPersona(body)

    assert build_prompt(persona, ["one"]) == (
        'Use {curly} braces and {} and {0} freely. "one"'
    )


def test_literal_braces_survive_on_the_trailer_path_too():
    persona = StubPersona("A {brace} and a {mystery_field}.")
    built = build_prompt(persona, [])

    assert built.startswith("A {brace} and a {mystery_field}.")


def test_braces_inside_a_recent_quote_survive():
    persona = StubPersona(RECENT_QUOTES_PLACEHOLDER)

    assert build_prompt(persona, ["{not_a_field}"]) == '"{not_a_field}"'


# --- configure -------------------------------------------------------------

def test_configure_passes_the_key_from_the_environment_to_the_provider(
    fake_provider, monkeypatch
):
    monkeypatch.setenv("FAKE_API_KEY", "sk-from-the-env")

    returned = generation.configure(StubPersona())

    assert returned is fake_provider
    assert fake_provider.configured_with == "sk-from-the-env"


def test_configure_raises_naming_the_missing_environment_variable(fake_provider):
    with pytest.raises(ValueError) as exc:
        generation.configure(StubPersona(slug="aunt_carol"))

    message = str(exc.value)
    assert "FAKE_API_KEY" in message
    assert "aunt_carol" in message
    assert "fake" in message
    assert fake_provider.configured_with is None


def test_configure_treats_an_empty_key_as_missing(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "")

    with pytest.raises(ValueError, match="FAKE_API_KEY"):
        generation.configure(StubPersona())


def test_configure_rejects_an_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider 'nope'"):
        generation.configure(StubPersona(provider="nope"))


# --- generate_quote --------------------------------------------------------

def test_generate_quote_sends_the_built_prompt_and_the_default_model(fake_provider):
    persona = StubPersona("Say something.")

    generation.generate_quote(persona, ["one"])

    prompt, model, config = fake_provider.generate_calls[0]
    assert prompt == build_prompt(persona, ["one"])
    assert model == "fake-default-model"
    assert config == {}


def test_generate_quote_prefers_the_characters_own_model(fake_provider):
    persona = StubPersona("Say something.", model="fake-tuned-model")

    generation.generate_quote(persona, [])

    assert fake_provider.generate_calls[0][1] == "fake-tuned-model"


def test_generate_quote_forwards_the_generation_config_verbatim(fake_provider):
    persona = StubPersona("Say something.", generation_config={"temperature": 1.1})

    generation.generate_quote(persona, [])

    assert fake_provider.generate_calls[0][2] == {"temperature": 1.1}


def test_generate_quote_strips_surrounding_whitespace(fake_provider):
    fake_provider.reply = "  \n a fresh line \n\n "

    assert generation.generate_quote(StubPersona(), []) == "a fresh line"


def test_generate_quote_strips_one_pair_of_surrounding_double_quotes(fake_provider):
    fake_provider.reply = '"a fresh line"'

    assert generation.generate_quote(StubPersona(), []) == "a fresh line"


def test_generate_quote_strips_whitespace_before_looking_for_the_quotes(fake_provider):
    fake_provider.reply = '\n  "a fresh line"  \n'

    assert generation.generate_quote(StubPersona(), []) == "a fresh line"


def test_generate_quote_strips_exactly_one_pair(fake_provider):
    fake_provider.reply = '""a fresh line""'

    assert generation.generate_quote(StubPersona(), []) == '"a fresh line"'


def test_generate_quote_keeps_quotes_that_are_not_a_surrounding_pair(fake_provider):
    fake_provider.reply = 'He said "hello" and left.'

    assert generation.generate_quote(StubPersona(), []) == 'He said "hello" and left.'


@pytest.mark.parametrize("reply", ['"only leading', 'only trailing"'])
def test_generate_quote_keeps_an_unpaired_quote(fake_provider, reply):
    fake_provider.reply = reply

    assert generation.generate_quote(StubPersona(), []) == reply


def test_generate_quote_keeps_a_lone_double_quote_character(fake_provider):
    # A single `"` both starts and ends with a double quote; without a length
    # guard the strip would eat it and hand the bot an empty quote.
    fake_provider.reply = '"'

    assert generation.generate_quote(StubPersona(), []) == '"'


def test_generate_quote_strips_an_empty_quoted_string_to_empty(fake_provider):
    # Two characters IS a real pair, so this one is stripped — the guard is
    # about length 1, not about the result being empty.
    fake_provider.reply = '""'

    assert generation.generate_quote(StubPersona(), []) == ""


def test_generate_quote_propagates_provider_errors(fake_provider):
    def boom(prompt, model, config):
        raise RuntimeError("provider is down")

    fake_provider.generate = boom

    # The bot's fallback path depends on the exception reaching it.
    with pytest.raises(RuntimeError, match="provider is down"):
        generation.generate_quote(StubPersona(), [])
