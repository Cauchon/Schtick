"""Unit tests for the ``status`` subcommand in :mod:`schtick.__main__`.

Everything here is offline and read-only: characters are synthetic files found
via ``SCHTICK_CHARACTERS_DIR`` (as in test_persona.py), state files are written
into ``tmp_path``, and no bot is ever constructed — ``status`` must never import
``schtick.bot``, whose constructor logs in to Bluesky.
"""

import json
import re
from datetime import datetime, timedelta

import pytest

from schtick import __main__ as cli


# --- fixtures / helpers ----------------------------------------------------

@pytest.fixture
def characters(tmp_path, monkeypatch):
    """An isolated characters directory the CLI will read."""
    directory = tmp_path / "characters"
    directory.mkdir()
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(directory))
    monkeypatch.delenv("PERSONA", raising=False)
    monkeypatch.delenv("SCHTICK_DATA_DIR", raising=False)
    return directory


def write_character(directory, slug="aunt_carol", name="Aunt Carol", extra=""):
    (directory / f"{slug}.md").write_text(
        f"---\nname: {name}\npost_interval_minutes: 60\n{extra}---\nbody\n",
        encoding="utf-8",
    )


def write_state(directory, slug="aunt_carol", last_post=None, cache=None, log=None):
    """Write any subset of the three state files a running bot leaves behind."""
    directory.mkdir(parents=True, exist_ok=True)
    last_post_name, cache_name, log_name = cli._state_filenames(slug)
    if last_post is not None:
        (directory / last_post_name).write_text(
            json.dumps({"last_post": last_post.isoformat()}), encoding="utf-8"
        )
    if cache is not None:
        (directory / cache_name).write_text(json.dumps(cache), encoding="utf-8")
    if log is not None:
        (directory / log_name).write_text(log, encoding="utf-8")
    return directory


def run_status(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["schtick", "status", *argv])
    cli.main()


# --- _humanize_delta -------------------------------------------------------

@pytest.mark.parametrize(
    "delta, expected",
    [
        (timedelta(seconds=5), "less than a minute"),
        (timedelta(minutes=45), "45m"),
        (timedelta(hours=2, minutes=13), "2h 13m"),
        (timedelta(hours=3), "3h"),
        (timedelta(days=1), "1d"),
        (timedelta(days=3, hours=4, minutes=30), "3d 4h"),
    ],
)
def test_humanize_delta(delta, expected):
    assert cli._humanize_delta(delta) == expected


# --- _status_data_dir ------------------------------------------------------

def test_data_dir_defaults_to_the_current_directory(monkeypatch):
    monkeypatch.delenv("SCHTICK_DATA_DIR", raising=False)
    assert str(cli._status_data_dir(None)) == "."


def test_data_dir_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SCHTICK_DATA_DIR", "/srv/schtick/data")
    assert str(cli._status_data_dir(None)) == "/srv/schtick/data"


def test_the_flag_beats_the_environment(monkeypatch):
    monkeypatch.setenv("SCHTICK_DATA_DIR", "/srv/schtick/data")
    assert str(cli._status_data_dir("elsewhere")) == "elsewhere"


# --- _find_state_dir: the two layouts --------------------------------------

def test_finds_state_in_the_per_slug_subdirectory(tmp_path):
    # The compose layout: ./data/<slug> is bind-mounted as the bot's cwd.
    write_state(tmp_path / "aunt_carol", cache=["hi"])

    assert cli._find_state_dir(tmp_path, "aunt_carol") == tmp_path / "aunt_carol"


def test_finds_state_in_the_directory_itself(tmp_path):
    # A bot started by hand from that directory writes straight into it.
    write_state(tmp_path, cache=["hi"])

    assert cli._find_state_dir(tmp_path, "aunt_carol") == tmp_path


def test_the_per_slug_subdirectory_wins_when_both_exist(tmp_path):
    write_state(tmp_path, cache=["flat"])
    write_state(tmp_path / "aunt_carol", cache=["nested"])

    assert cli._find_state_dir(tmp_path, "aunt_carol") == tmp_path / "aunt_carol"


def test_no_state_dir_when_neither_holds_a_file(tmp_path):
    (tmp_path / "aunt_carol").mkdir()

    assert cli._find_state_dir(tmp_path, "aunt_carol") is None


def test_any_one_of_the_three_files_is_enough(tmp_path):
    write_state(tmp_path / "aunt_carol", log="a line\n")

    assert cli._find_state_dir(tmp_path, "aunt_carol") == tmp_path / "aunt_carol"


# --- _tail_lines -----------------------------------------------------------

def test_tail_returns_the_last_n_lines(tmp_path):
    path = tmp_path / "aunt_carol.log"
    path.write_text("".join(f"line {i}\n" for i in range(50)), encoding="utf-8")

    assert cli._tail_lines(path, 5) == [f"line {i}" for i in range(45, 50)]


def test_tail_spans_more_than_one_block(tmp_path):
    # Forces the seek-backwards loop to run several times.
    path = tmp_path / "aunt_carol.log"
    path.write_text("".join(f"line {i}\n" for i in range(500)), encoding="utf-8")

    assert cli._tail_lines(path, 3, block_size=64) == ["line 497", "line 498", "line 499"]


def test_tail_of_a_short_file_returns_everything(tmp_path):
    path = tmp_path / "aunt_carol.log"
    path.write_text("only line\n", encoding="utf-8")

    assert cli._tail_lines(path, 5) == ["only line"]


def test_tail_tolerates_a_missing_file(tmp_path):
    assert cli._tail_lines(tmp_path / "nope.log", 5) == []


def test_tail_of_zero_lines_is_empty(tmp_path):
    path = tmp_path / "aunt_carol.log"
    path.write_text("line\n", encoding="utf-8")

    assert cli._tail_lines(path, 0) == []


# --- the report ------------------------------------------------------------

def test_reports_a_healthy_bot_from_the_compose_layout(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    data = tmp_path / "data"
    write_state(
        data / "aunt_carol",
        last_post=datetime.now() - timedelta(minutes=20),
        cache=[f"post {i}" for i in range(87)],
        log="".join(f"log line {i}\n" for i in range(20)),
    )

    run_status(monkeypatch, "--data-dir", str(data))

    out = capsys.readouterr().out
    assert "Aunt Carol" in out
    assert "(aunt_carol)" in out
    assert str(data / "aunt_carol") in out
    assert "gemini" in out
    assert "every 1h" in out
    assert "20m ago" in out
    # Durations truncate to whole minutes, and a few microseconds elapse
    # between the fixture's now() and the command's, so 40m can read as 39m.
    assert re.search(r"next post: in (39m|40m)\b", out)
    assert "post 86" in out            # the newest cached post
    assert "(87 posts cached)" in out
    assert "log line 19" in out
    assert "OVERDUE" not in out


def test_reports_a_bot_run_from_the_data_directory_itself(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    write_state(tmp_path / "flat", cache=["only post"], last_post=datetime.now())

    run_status(monkeypatch, "--data-dir", str(tmp_path / "flat"))

    out = capsys.readouterr().out
    assert str(tmp_path / "flat") in out
    assert "only post" in out


def test_the_data_dir_can_come_from_the_environment(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    write_state(tmp_path / "aunt_carol", cache=["from the env"])
    monkeypatch.setenv("SCHTICK_DATA_DIR", str(tmp_path))

    run_status(monkeypatch)

    assert "from the env" in capsys.readouterr().out


def test_a_bot_that_has_never_posted(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    write_state(tmp_path / "aunt_carol", log="starting up\n")

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "last post: never" in out
    assert "next post: unknown" in out
    assert "starting up" in out
    assert "OVERDUE" not in out


def test_an_overdue_bot_is_flagged(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)  # a 60-minute interval
    write_state(tmp_path / "aunt_carol", last_post=datetime.now() - timedelta(minutes=95))

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "OVERDUE by 35m" in out
    assert "1h 35m ago" in out


def test_an_overdue_bot_still_exits_zero(characters, tmp_path, monkeypatch, capsys):
    # status is a report, not a health check — SystemExit would break scripts.
    write_character(characters)
    write_state(tmp_path / "aunt_carol", last_post=datetime.now() - timedelta(days=2))

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    assert "OVERDUE" in capsys.readouterr().out


def test_no_state_found_names_both_places_it_looked(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "no state found" in out
    assert str(tmp_path / "aunt_carol") in out
    assert str(tmp_path) in out


def test_corrupt_last_post_does_not_kill_the_report(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    state = tmp_path / "aunt_carol"
    write_state(state, cache=["still readable"], log="still logging\n")
    (state / "last_post_aunt_carol.json").write_text("{not json", encoding="utf-8")

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "unreadable (last_post_aunt_carol.json)" in out
    assert "still readable" in out       # the other fields survive
    assert "still logging" in out


def test_corrupt_cache_does_not_kill_the_report(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    state = tmp_path / "aunt_carol"
    write_state(state, last_post=datetime.now() - timedelta(minutes=10), log="alive\n")
    (state / "recent_posts_aunt_carol.json").write_text("[[[", encoding="utf-8")

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "unreadable (recent_posts_aunt_carol.json)" in out
    assert "10m ago" in out
    assert "alive" in out


def test_a_cache_that_is_not_a_list_is_treated_as_corrupt(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    state = tmp_path / "aunt_carol"
    state.mkdir(parents=True)
    (state / "recent_posts_aunt_carol.json").write_text('{"a": 1}', encoding="utf-8")

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    assert "unreadable (recent_posts_aunt_carol.json)" in capsys.readouterr().out


def test_log_lines_defaults_to_five(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    write_state(tmp_path / "aunt_carol", log="".join(f"entry {i}\n" for i in range(30)))

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    shown = [line for line in out.splitlines() if line.strip().startswith("entry ")]
    assert len(shown) == 5
    assert shown[-1].strip() == "entry 29"
    assert "entry 25" in out
    assert "entry 24" not in out


def test_log_lines_is_configurable(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    write_state(tmp_path / "aunt_carol", log="".join(f"entry {i}\n" for i in range(30)))

    run_status(monkeypatch, "--data-dir", str(tmp_path), "--log-lines", "12")

    out = capsys.readouterr().out
    shown = [line for line in out.splitlines() if line.strip().startswith("entry ")]
    assert len(shown) == 12
    assert "entry 18" in out
    assert "entry 17" not in out


def test_reports_every_character_by_default(characters, tmp_path, monkeypatch, capsys):
    write_character(characters, "aunt_carol", "Aunt Carol")
    write_character(characters, "uncle_bob", "Uncle Bob")
    write_state(tmp_path / "aunt_carol", cache=["carol speaks"])
    write_state(tmp_path / "uncle_bob", slug="uncle_bob", cache=["bob speaks"])

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "carol speaks" in out
    assert "bob speaks" in out


def test_a_slug_narrows_the_report_to_one_character(characters, tmp_path, monkeypatch, capsys):
    write_character(characters, "aunt_carol", "Aunt Carol")
    write_character(characters, "uncle_bob", "Uncle Bob")
    write_state(tmp_path / "aunt_carol", cache=["carol speaks"])
    write_state(tmp_path / "uncle_bob", slug="uncle_bob", cache=["bob speaks"])

    run_status(monkeypatch, "aunt_carol", "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "carol speaks" in out
    assert "bob speaks" not in out
    assert "Uncle Bob" not in out


def test_an_unknown_slug_exits_1(characters, monkeypatch, capsys):
    write_character(characters)

    with pytest.raises(SystemExit) as exc:
        run_status(monkeypatch, "nobody")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Unknown persona 'nobody'" in out
    assert "aunt_carol" in out  # the error lists what is available


def test_says_so_when_there_are_no_characters(characters, monkeypatch, capsys):
    run_status(monkeypatch)

    assert "No characters yet" in capsys.readouterr().out


def test_a_broken_character_does_not_stop_the_others(characters, tmp_path, monkeypatch, capsys):
    write_character(characters)
    (characters / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")

    run_status(monkeypatch, "--data-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "could not load" in out
    assert "Aunt Carol" in out


def test_a_bad_log_lines_value_exits_1(characters, monkeypatch, capsys):
    write_character(characters)

    with pytest.raises(SystemExit) as exc:
        run_status(monkeypatch, "--log-lines", "many")

    assert exc.value.code == 1
    assert "expects a number" in capsys.readouterr().out


def test_an_extra_argument_exits_1(characters, monkeypatch, capsys):
    write_character(characters)

    with pytest.raises(SystemExit) as exc:
        run_status(monkeypatch, "aunt_carol", "uncle_bob")

    assert exc.value.code == 1
    assert "unexpected argument" in capsys.readouterr().out


# --- dispatch --------------------------------------------------------------

def test_status_is_a_subcommand(characters, monkeypatch):
    # Without this, `python -m schtick status` would be read as a slug and
    # start a bot (which logs in to Bluesky).
    assert "status" in cli.SUBCOMMANDS

    dispatched = []
    monkeypatch.setattr(cli, "cmd_status", lambda args: dispatched.append(args))
    monkeypatch.setattr(cli, "run_bot", lambda slug: pytest.fail("run_bot must not run"))

    run_status(monkeypatch, "aunt_carol", "--log-lines", "3")

    assert dispatched == [["aunt_carol", "--log-lines", "3"]]


def test_status_is_documented_in_the_usage_text():
    assert "python -m schtick status" in cli.USAGE
    assert "python -m schtick status" in cli.__doc__


def test_the_state_filenames_match_the_bots(characters, monkeypatch):
    # These three f-strings are duplicated from bot.py; if bot.py's names ever
    # change, status goes blind. Kept in sync by hand — see _state_filenames.
    assert cli._state_filenames("aunt_carol") == (
        "last_post_aunt_carol.json",
        "recent_posts_aunt_carol.json",
        "aunt_carol.log",
    )
