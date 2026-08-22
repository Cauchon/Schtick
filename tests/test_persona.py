"""Unit tests for the character loader in :mod:`schtick.persona`.

Synthetic characters are written into ``tmp_path`` and found via the
``SCHTICK_CHARACTERS_DIR`` override, so nothing here touches the real
``characters/`` directory except the two tests that deliberately load it.
"""

import pytest

from schtick import providers
from schtick.persona import (
    Persona,
    available_personas,
    characters_dir,
    load_persona,
)


@pytest.fixture
def characters(tmp_path, monkeypatch):
    """An empty characters directory that the loader will use."""
    directory = tmp_path / "characters"
    directory.mkdir()
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(directory))
    return directory


@pytest.fixture
def real_characters(monkeypatch):
    """Drop any override so the loader resolves the repo's own characters/."""
    monkeypatch.delenv("SCHTICK_CHARACTERS_DIR", raising=False)


def write_character(directory, slug, text):
    path = directory / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- characters_dir / available_personas -----------------------------------

def test_characters_dir_honours_the_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(tmp_path / "elsewhere"))
    assert characters_dir() == tmp_path / "elsewhere"


def test_characters_dir_defaults_next_to_the_package(real_characters):
    # Resolved relative to the package file, NOT the cwd — that is what makes
    # the Docker layout (cwd=/home/appuser/data, code=/app) work.
    assert characters_dir().name == "characters"
    assert characters_dir().is_dir()


def test_available_personas_is_empty_for_a_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(tmp_path / "does_not_exist"))
    assert available_personas() == []


def test_available_personas_is_empty_for_an_empty_directory(characters):
    assert available_personas() == []


def test_available_personas_returns_sorted_stems(characters):
    for slug in ("zelda", "aunt_carol", "kramer"):
        write_character(characters, slug, "---\nname: X\n---\nbody\n")
    (characters / "notes.txt").write_text("ignored", encoding="utf-8")

    assert available_personas() == ["aunt_carol", "kramer", "zelda"]


def test_load_persona_rejects_an_unknown_slug(characters):
    write_character(characters, "aunt_carol", "---\nname: Aunt Carol\n---\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("uncle_bob")

    assert "Unknown persona 'uncle_bob'" in str(exc.value)
    assert "aunt_carol" in str(exc.value)


# --- the body is preserved verbatim ----------------------------------------

BODY = (
    "You are Test Character.\n"
    "    An indented continuation line.\n"
    "\n"
    "    A line with trailing spaces.   \n"
    "\tA tab-indented line.\n"
)


def test_body_is_preserved_verbatim(characters):
    write_character(characters, "verbatim", "---\nname: Test Character\n---\n" + BODY)

    # Byte-identical: no strip, no dedent, trailing newline intact.
    assert load_persona("verbatim").PROMPT == BODY


def test_body_without_a_trailing_newline_stays_without_one(characters):
    body = BODY.rstrip("\n")
    write_character(characters, "no_newline", "---\nname: Test Character\n---\n" + body)

    prompt = load_persona("no_newline").PROMPT
    assert prompt == body
    assert not prompt.endswith("\n")


def test_a_body_of_only_a_closing_fence_is_empty(characters):
    # Closing fence at EOF with no newline after it: the body is "".
    write_character(characters, "empty_body", "---\nname: Test Character\n---")

    assert load_persona("empty_body").PROMPT == ""


def test_a_dashed_line_in_the_body_does_not_re_split_the_file(characters):
    body = "First paragraph.\n---\nSecond paragraph.\n"
    write_character(characters, "dashes", "---\nname: Test Character\n---\n" + body)

    assert load_persona("dashes").PROMPT == body


# --- malformed files -------------------------------------------------------

def test_missing_opening_fence_is_rejected(characters):
    write_character(characters, "no_open", "name: Test Character\n---\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("no_open")

    assert "must start with a '---' frontmatter fence" in str(exc.value)
    assert "no_open.md" in str(exc.value)


def test_missing_closing_fence_is_rejected(characters):
    write_character(characters, "no_close", "---\nname: Test Character\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("no_close")

    assert "no closing '---' frontmatter fence" in str(exc.value)


def test_frontmatter_that_is_not_a_mapping_is_rejected(characters):
    write_character(characters, "sequence", "---\n- one\n- two\n---\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("sequence")

    assert "frontmatter is not a mapping" in str(exc.value)


def test_missing_name_is_rejected(characters):
    write_character(characters, "nameless", "---\nchar_target: 240\n---\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("nameless")

    assert "missing required 'name' field" in str(exc.value)


def test_empty_frontmatter_is_rejected_for_the_missing_name(characters):
    write_character(characters, "blank", "---\n---\nbody\n")

    with pytest.raises(ValueError) as exc:
        load_persona("blank")

    assert "missing required 'name' field" in str(exc.value)


def test_unknown_provider_is_rejected_with_the_valid_names(characters):
    write_character(
        characters, "wrong_provider", "---\nname: X\nprovider: openai\n---\nbody\n"
    )

    with pytest.raises(ValueError) as exc:
        load_persona("wrong_provider")

    message = str(exc.value)
    assert "wrong_provider.md" in message
    assert "Unknown provider 'openai'" in message
    for name in providers.available_providers():
        assert name in message


# --- frontmatter fields ----------------------------------------------------

def test_defaults_apply_when_frontmatter_is_minimal(characters):
    write_character(characters, "minimal", "---\nname: Minimal\n---\nbody\n")

    persona = load_persona("minimal")

    assert persona.SLUG == "minimal"
    assert persona.DISPLAY_NAME == "Minimal"
    assert persona.CHAR_TARGET == 240
    assert persona.POST_INTERVAL_MINUTES == 214
    assert persona.PROVIDER == providers.DEFAULT_PROVIDER
    assert persona.MODEL == ""
    assert persona.FALLBACK_QUOTES == []


def test_absent_generation_stays_an_empty_falsy_dict(characters):
    write_character(characters, "no_generation", "---\nname: X\n---\nbody\n")

    config = load_persona("no_generation").GENERATION_CONFIG

    # A missing `generation` key is meaningful: falsy means the Gemini provider
    # passes NO config kwarg at all. Do not "normalize" this into a populated
    # default — see CLAUDE.md.
    assert config == {}
    assert not config


def test_generation_block_is_read_as_a_dict(characters):
    write_character(
        characters, "tuned", "---\nname: X\ngeneration:\n  temperature: 1.1\n---\nbody\n"
    )

    assert load_persona("tuned").GENERATION_CONFIG == {"temperature": 1.1}


def test_optional_fields_are_read(characters):
    write_character(
        characters,
        "full",
        "---\n"
        "name: Full Character\n"
        "char_target: 281\n"
        "post_interval_minutes: 90\n"
        "provider: anthropic\n"
        "model: claude-custom\n"
        "fallbacks:\n"
        "  - \"first\"\n"
        "  - \"second\"\n"
        "---\n"
        "body\n",
    )

    persona = load_persona("full")

    assert persona.CHAR_TARGET == 281
    assert persona.POST_INTERVAL_MINUTES == 90
    assert persona.PROVIDER == "anthropic"
    assert persona.MODEL == "claude-custom"
    assert persona.FALLBACK_QUOTES == ["first", "second"]


def test_persona_defaults_are_independent_between_instances():
    # The mutable defaults are dataclass fields, so two personas must not share
    # one list/dict.
    first = Persona(SLUG="a", DISPLAY_NAME="A", PROMPT="")
    second = Persona(SLUG="b", DISPLAY_NAME="B", PROMPT="")
    first.FALLBACK_QUOTES.append("only mine")
    first.GENERATION_CONFIG["only"] = "mine"

    assert second.FALLBACK_QUOTES == []
    assert second.GENERATION_CONFIG == {}


# --- the real character files ----------------------------------------------

def test_the_shipped_characters_are_discoverable(real_characters):
    assert set(available_personas()) >= {"kramer", "larry_david"}


def test_kramer_loads(real_characters):
    kramer = load_persona("kramer")

    assert kramer.SLUG == "kramer"
    assert kramer.DISPLAY_NAME == "Kramer"
    assert kramer.PROVIDER == "gemini"
    # Kramer deliberately omits `generation` — see CLAUDE.md.
    assert not kramer.GENERATION_CONFIG
    assert kramer.FALLBACK_QUOTES
    assert kramer.PROMPT.startswith("You are Cosmo Kramer")


def test_larry_david_loads(real_characters):
    larry = load_persona("larry_david")

    assert larry.SLUG == "larry_david"
    assert larry.DISPLAY_NAME == "Larry David"
    assert larry.PROVIDER == "gemini"
    # No `generation` block: Gemini 3.x deprecates temperature/top_p/top_k, so
    # the old `temperature: 1.1` was dropped — see CLAUDE.md.
    assert not larry.GENERATION_CONFIG
    assert larry.FALLBACK_QUOTES
    assert larry.PROMPT.startswith("You are Larry David")


@pytest.mark.parametrize("slug", ["kramer", "larry_david"])
def test_every_shipped_character_names_a_registered_provider(real_characters, slug):
    persona = load_persona(slug)
    assert providers.get_provider(persona.PROVIDER).name == persona.PROVIDER
