"""Offline preflight tests for ``schtick doctor``."""

import pytest

from schtick import __main__ as cli
from schtick import diagnostics


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    characters = tmp_path / "characters"
    characters.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCHTICK_CHARACTERS_DIR", str(characters))
    for key in (
        "BLUESKY_HANDLE",
        "BLUESKY_APP_PASSWORD",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    return characters, data


def write_character(directory, body="A sharply written character prompt.\n", extra=""):
    (directory / "aunt_carol.md").write_text(
        "---\n"
        "name: Aunt Carol\n"
        "char_target: 240\n"
        "post_interval_minutes: 60\n"
        "fallbacks:\n"
        "  - A fully written fallback line.\n"
        f"{extra}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )


def write_env(directory):
    (directory / ".env.aunt_carol").write_text(
        "BLUESKY_HANDLE=carol.example.com\n"
        "BLUESKY_APP_PASSWORD=app-password-value\n"
        "GEMINI_API_KEY=gemini-key-value\n",
        encoding="utf-8",
    )


def run_doctor(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["schtick", "doctor", *args])
    cli.main()


def test_valid_character_passes_offline_doctor(workspace, monkeypatch, capsys):
    characters, data = workspace
    write_character(characters)
    write_env(data.parent)

    run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data))

    out = capsys.readouterr().out
    assert "Doctor passed" in out
    assert "PASS  credentials" in out
    assert "PASS  storage" in out
    assert "Offline checks only" in out


def test_default_doctor_never_calls_external_services(workspace, monkeypatch):
    characters, data = workspace
    write_character(characters)
    write_env(data.parent)
    monkeypatch.setattr(
        diagnostics.generation,
        "generate_quote",
        lambda *_args: pytest.fail("offline doctor must not generate"),
    )

    class ForbiddenClient:
        def __init__(self):
            pytest.fail("offline doctor must not create a Bluesky client")

    monkeypatch.setattr("atproto.Client", ForbiddenClient)
    run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data))


def test_missing_credentials_fail_without_printing_values(workspace, monkeypatch, capsys):
    characters, data = workspace
    write_character(characters)
    (data.parent / ".env.aunt_carol").write_text(
        "BLUESKY_HANDLE=carol.example.com\n"
        "BLUESKY_APP_PASSWORD=top-secret-password\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data))

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "GEMINI_API_KEY" in out
    assert "top-secret-password" not in out
    assert "Doctor failed" in out


def test_starter_template_markers_and_bad_values_are_reported(
    workspace, monkeypatch, capsys
):
    characters, data = workspace
    write_character(
        characters,
        body="You are <Name>. [Describe who they are in 2-3 sentences.]\n",
        extra="mystery_setting: yes\n",
    )
    # Replacing the otherwise-valid numeric lines makes them invalid YAML types
    # without making the entire frontmatter unreadable.
    path = characters / "aunt_carol.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("char_target: 240", "char_target: 400")
    text = text.replace("post_interval_minutes: 60", "post_interval_minutes: never")
    path.write_text(text, encoding="utf-8")
    write_env(data.parent)

    with pytest.raises(SystemExit):
        run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data))

    out = capsys.readouterr().out
    assert "exceeds Bluesky's 300-character limit" in out
    assert "positive whole number" in out
    assert "unfilled marker" in out
    assert "unknown field: mystery_setting" in out


def test_placeholder_credentials_are_treated_as_missing(workspace, monkeypatch, capsys):
    characters, data = workspace
    write_character(characters)
    (data.parent / ".env.aunt_carol").write_text(
        "BLUESKY_HANDLE=your-handle.bsky.social\n"
        "BLUESKY_APP_PASSWORD=your-app-password\n"
        "GEMINI_API_KEY=your-gemini-api-key\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data))

    assert "missing or placeholder" in capsys.readouterr().out


def test_live_flag_runs_opt_in_checks(workspace, monkeypatch, capsys):
    characters, data = workspace
    write_character(characters)
    write_env(data.parent)
    called = []

    def fake_live(report):
        called.append(report.slug)
        report.add("pass", "live generation", "test response")
        report.add("pass", "Bluesky login", "test login")

    monkeypatch.setattr(diagnostics, "run_live_checks", fake_live)

    run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data), "--live")

    assert called == ["aunt_carol"]
    out = capsys.readouterr().out
    assert "live generation" in out
    assert "Live mode never posts" in out


def test_missing_data_directory_fails(workspace, monkeypatch, capsys):
    characters, data = workspace
    write_character(characters)
    write_env(data.parent)

    with pytest.raises(SystemExit):
        run_doctor(monkeypatch, "aunt_carol", "--data-dir", str(data / "missing"))

    assert "data directory does not exist" in capsys.readouterr().out


def test_doctor_is_documented_and_dispatched():
    assert "doctor" in cli.SUBCOMMANDS
    assert "python -m schtick doctor" in cli.USAGE
    assert "python -m schtick doctor" in cli.__doc__
