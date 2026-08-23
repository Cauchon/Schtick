"""Unit tests for the CLI helpers and dispatch in :mod:`schtick.__main__`.

Nothing here starts a bot, generates a quote, or reads a real ``.env``:
``load_dotenv`` is replaced with a recorder, characters come from ``tmp_path``
via ``SCHTICK_CHARACTERS_DIR``, and only the offline subcommands are dispatched.
"""

import builtins

import pytest

from schtick import __main__ as cli


# --- _slugify --------------------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Aunt Carol", "aunt_carol"),
        ("Larry David", "larry_david"),
        ("Kramer", "kramer"),
        ("  Aunt   Carol  ", "aunt_carol"),
        ("Jean-Paul", "jean_paul"),
        ("O'Brien", "obrien"),
        ("Agent 47", "agent_47"),
        ("Dr. Strange!", "dr_strange"),
        ("--Foo-Bar--", "foo_bar"),
        ("ALL CAPS", "all_caps"),
    ],
)
def test_slugify(name, expected):
    assert cli._slugify(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "!!!", "?? ??"])
def test_slugify_returns_empty_when_nothing_usable_is_left(name):
    # The wizard checks for this and bails with a helpful message.
    assert cli._slugify(name) == ""


def test_slugify_output_is_a_valid_slug_for_the_compose_block():
    slug = cli._slugify("Aunt Carol's Nephew")
    assert slug == "aunt_carols_nephew"
    assert cli._slugify(slug) == slug  # idempotent


# --- _humanize_minutes -----------------------------------------------------

@pytest.mark.parametrize(
    "minutes, expected",
    [
        (214, "3h 34m"),
        (45, "45m"),
        (60, "1h"),
        (120, "2h"),
        (61, "1h 1m"),
        (0, "0m"),
        (1440, "24h"),
    ],
)
def test_humanize_minutes(minutes, expected):
    assert cli._humanize_minutes(minutes) == expected


def test_humanize_minutes_accepts_a_string_from_frontmatter():
    assert cli._humanize_minutes("90") == "1h 30m"


# --- _compose_service_block ------------------------------------------------

def test_compose_service_block_hyphenates_the_service_name_only():
    block = cli._compose_service_block("aunt_carol")

    # Service names use hyphens; the slug (command, env file, data dir) keeps
    # its underscores.
    assert block.startswith("  schtick-aunt-carol:\n")
    assert "    command: aunt_carol\n" in block
    assert "    env_file: .env.aunt_carol\n" in block
    assert "      - ./data/aunt_carol:/home/appuser/data\n" in block
    assert "    image: schtick:latest\n" in block
    assert "    restart: unless-stopped\n" in block
    assert '"health", "aunt_carol"' in block


def test_compose_service_block_is_valid_yaml_under_a_services_key():
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load("services:\n" + cli._compose_service_block("larry_david"))

    assert parsed["services"]["schtick-larry-david"] == {
        "build": ".",
        "image": "schtick:latest",
        "command": "larry_david",
        "env_file": ".env.larry_david",
        "volumes": ["./data/larry_david:/home/appuser/data"],
        "restart": "unless-stopped",
        "healthcheck": {
            "test": [
                "CMD", "python", "-m", "schtick", "health", "larry_david",
                "--data-dir", ".", "--quiet",
            ],
            "interval": "5m",
            "timeout": "10s",
            "retries": 2,
            "start_period": "5m",
        },
    }


# --- _load_env -------------------------------------------------------------

@pytest.fixture
def recorded_dotenv(monkeypatch):
    """Replace load_dotenv with a recorder so no real .env is ever read."""
    calls = []

    def fake_load_dotenv(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(cli, "load_dotenv", fake_load_dotenv)
    return calls


def test_load_env_prefers_the_persona_file(tmp_path, monkeypatch, recorded_dotenv):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SHARED=generic\n", encoding="utf-8")
    (tmp_path / ".env.aunt_carol").write_text("SHARED=persona\n", encoding="utf-8")

    assert cli._load_env("aunt_carol") == ".env.aunt_carol"
    assert recorded_dotenv == [((".env.aunt_carol",), {})]


def test_load_env_falls_back_to_the_shared_file(tmp_path, monkeypatch, recorded_dotenv):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SHARED=generic\n", encoding="utf-8")

    # The fallback names ".env" explicitly rather than calling load_dotenv()
    # bare: find_dotenv() walks up from the *package* directory, not the cwd,
    # and could load an unrelated .env from outside it.
    assert cli._load_env("aunt_carol") == ".env"
    assert recorded_dotenv == [((".env",), {})]


def test_load_env_reports_the_shared_file_even_when_neither_exists(
    tmp_path, monkeypatch, recorded_dotenv
):
    monkeypatch.chdir(tmp_path)

    # The return value names where the values *would* live, for error messages.
    assert cli._load_env("aunt_carol") == ".env"
    # Still a cwd-relative path: python-dotenv returns False for a missing file.
    assert recorded_dotenv == [((".env",), {})]


def test_load_env_is_a_silent_no_op_when_no_env_file_exists(tmp_path, monkeypatch):
    # Not stubbed: the real python-dotenv must tolerate a missing file without
    # raising or warning, which is what makes the unconditional fallback safe.
    monkeypatch.chdir(tmp_path)

    assert cli.load_dotenv(".env") is False
    assert cli._load_env("aunt_carol") == ".env"


def test_load_env_does_not_pick_up_another_personas_file(
    tmp_path, monkeypatch, recorded_dotenv
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.kramer").write_text("SHARED=kramer\n", encoding="utf-8")

    assert cli._load_env("larry_david") == ".env"


# --- _choose_provider ------------------------------------------------------

@pytest.mark.parametrize(
    "typed, expected",
    [
        ("", "gemini"),      # Enter accepts the default
        ("1", "gemini"),
        ("2", "anthropic"),
        ("3", "deepseek"),
        ("x", "gemini"),     # anything unrecognised falls back to the default
        ("42", "gemini"),
        ("  2  ", "anthropic"),  # the answer is stripped
    ],
)
def test_choose_provider(monkeypatch, capsys, typed, expected):
    monkeypatch.setattr(builtins, "input", lambda _prompt="": typed)

    provider = cli._choose_provider()

    assert provider.name == expected
    assert provider is cli.providers.get_provider(expected)


def test_choose_provider_lists_every_option(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")

    cli._choose_provider()

    printed = capsys.readouterr().out
    assert "Gemini" in printed
    assert "Claude" in printed
    assert "DeepSeek" in printed


# --- main() dispatch -------------------------------------------------------

@pytest.fixture
def characters(tmp_path, monkeypatch):
    """An isolated characters directory the CLI will read."""
    directory = tmp_path / "characters"
    directory.mkdir()
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(directory))
    monkeypatch.delenv("PERSONA", raising=False)
    return directory


def write_character(directory, slug, name, extra=""):
    (directory / f"{slug}.md").write_text(
        f"---\nname: {name}\n{extra}---\nbody\n", encoding="utf-8"
    )


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["schtick", *argv])
    cli.main()


def test_main_list_prints_every_character_with_its_cadence(
    characters, monkeypatch, capsys
):
    write_character(characters, "aunt_carol", "Aunt Carol", "post_interval_minutes: 214\n")
    write_character(characters, "uncle_bob", "Uncle Bob", "post_interval_minutes: 45\n")

    run_cli(monkeypatch, "list")

    out = capsys.readouterr().out
    assert "aunt_carol" in out
    assert "Aunt Carol" in out
    assert "posts every 3h 34m" in out
    assert "uncle_bob" in out
    assert "posts every 45m" in out


def test_main_list_says_so_when_there_are_no_characters(characters, monkeypatch, capsys):
    run_cli(monkeypatch, "list")

    assert "No characters yet" in capsys.readouterr().out


def test_main_list_reports_a_broken_character_without_crashing(
    characters, monkeypatch, capsys
):
    write_character(characters, "good", "Good One")
    (characters / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

    run_cli(monkeypatch, "list")

    out = capsys.readouterr().out
    assert "could not load" in out
    assert "Good One" in out  # the healthy character still lists


def test_main_list_reads_the_shipped_characters(monkeypatch, capsys):
    monkeypatch.delenv("SCHTICK_CHARACTERS_DIR", raising=False)
    monkeypatch.delenv("PERSONA", raising=False)

    run_cli(monkeypatch, "list")

    out = capsys.readouterr().out
    assert "kramer" in out
    assert "larry_david" in out


def test_main_without_arguments_prints_usage_and_exits_1(characters, monkeypatch, capsys):
    write_character(characters, "aunt_carol", "Aunt Carol")

    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "python -m schtick new" in out
    assert "Your characters: aunt_carol" in out


def test_main_usage_nudges_towards_new_when_there_are_no_characters(
    characters, monkeypatch, capsys
):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch)

    assert exc.value.code == 1
    assert "No characters yet" in capsys.readouterr().out


def test_main_dispatches_the_known_subcommands(characters, monkeypatch):
    # Guards the bare-slug fallback: anything in SUBCOMMANDS must reach its
    # handler, never run_bot (which would log in to Bluesky).
    assert cli.SUBCOMMANDS == {
        "new", "list", "doctor", "preview", "run", "status", "health"
    }

    dispatched = []
    for command in sorted(cli.SUBCOMMANDS):
        monkeypatch.setattr(cli, f"cmd_{command}", lambda args, c=command: dispatched.append(c))
    monkeypatch.setattr(cli, "run_bot", lambda slug: pytest.fail("run_bot must not run"))

    for command in sorted(cli.SUBCOMMANDS):
        run_cli(monkeypatch, command)

    assert dispatched == ["doctor", "health", "list", "new", "preview", "run", "status"]


def test_main_treats_an_unknown_first_argument_as_a_slug(characters, monkeypatch):
    # The Docker contract: `python -m schtick <slug>` runs the bot.
    started = []
    monkeypatch.setattr(cli, "run_bot", lambda slug: started.append(slug))

    run_cli(monkeypatch, "aunt_carol")

    assert started == ["aunt_carol"]


def test_main_falls_back_to_the_persona_environment_variable(characters, monkeypatch):
    monkeypatch.setenv("PERSONA", "aunt_carol")
    started = []
    monkeypatch.setattr(cli, "run_bot", lambda slug: started.append(slug))

    run_cli(monkeypatch)

    assert started == ["aunt_carol"]
