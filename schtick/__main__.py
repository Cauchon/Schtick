#!/usr/bin/env python3
"""
CLI entry point for the Schtick engine.

Turn a written character into a bot that posts on a schedule.

Usage:
    python -m schtick new                    Create a new character (interactive)
    python -m schtick list                   List your characters
    python -m schtick preview <slug> [-n N]  Hear a character before going live
    python -m schtick run <slug>             Start the bot (posts on a schedule)
    python -m schtick <slug>                 Same as 'run <slug>' (used by Docker)

The slug is a character's filename stem, e.g. 'larry_david'. The slug may also
be supplied via the PERSONA environment variable. Environment variables are
loaded from `.env.<slug>` if present, otherwise `.env`, so several personas can
run from one checkout on the same machine.

Backward compatibility: if the first argument is one of the subcommands above it
is dispatched as such; anything else is treated as a slug to run (this is how the
Docker image starts a bot: `python -m schtick <slug>`).
"""

import os
import re
import sys
import getpass
import logging

from dotenv import load_dotenv

from schtick import providers
from schtick.persona import load_persona, available_personas, characters_dir

logger = logging.getLogger(__name__)

SUBCOMMANDS = {"new", "list", "preview", "run"}

USAGE = """\
Schtick — turn a written character into a bot that posts on a schedule.

Usage:
  python -m schtick new                     Create a new character (interactive)
  python -m schtick list                    List your characters
  python -m schtick preview <slug> [-n N]   Hear a character before going live
                                            (generates N quotes without posting;
                                            each is one live API call against the
                                            character's provider. N defaults to 1.)
  python -m schtick run <slug>              Start the bot (posts on a schedule)
  python -m schtick <slug>                  Same as 'run <slug>' (used by Docker)

The slug is a character's filename, e.g. 'larry_david'. You can also set the
PERSONA environment variable instead of passing a slug."""


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #

def _load_env(slug: str) -> str:
    """Load env vars for ``slug``, preferring ``.env.<slug>`` over ``.env``.

    Returns the path of the file that was loaded (or would hold the values), so
    callers can name it in error messages.
    """
    persona_env = f".env.{slug}"
    if os.path.exists(persona_env):
        load_dotenv(persona_env)
        return persona_env
    load_dotenv()
    return ".env"


def _humanize_minutes(minutes: int) -> str:
    """Render a minute count as e.g. '3h 34m', '2h', or '45m'."""
    minutes = int(minutes)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _slugify(name: str) -> str:
    """Derive a filename slug from a display name.

    Lowercase; spaces/hyphens become underscores; other non-alphanumerics are
    dropped; runs of underscores collapse; leading/trailing underscores stripped.
    """
    slug = name.strip().lower()
    slug = re.sub(r"[\s\-]+", "_", slug)
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_")


def print_usage():
    print(USAGE)
    personas = available_personas()
    if personas:
        print(f"\nYour characters: {', '.join(personas)}")
    else:
        print("\nNo characters yet. Create one with:  python -m schtick new")


# --------------------------------------------------------------------------- #
# run <slug>  (and the bare-slug / PERSONA path)
# --------------------------------------------------------------------------- #

def run_bot(slug: str):
    """Load env + persona for ``slug`` and start the scheduler (today's flow)."""
    _load_env(slug)

    try:
        persona = load_persona(slug)
    except ValueError as e:
        print(e)
        sys.exit(1)

    # Import here so bot construction (and its logging setup) happens after env
    # loading and persona resolution.
    from schtick.bot import PersonaBot

    try:
        bot = PersonaBot(persona)
        bot.run_scheduler()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise


def cmd_run(args):
    slug = args[0] if args else os.getenv("PERSONA")
    if not slug:
        print("Usage: python -m schtick run <slug>")
        personas = available_personas()
        if personas:
            print(f"Your characters: {', '.join(personas)}")
        sys.exit(1)
    run_bot(slug)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #

def cmd_list(args):
    slugs = available_personas()
    if not slugs:
        print("No characters yet. Create one with:  python -m schtick new")
        return
    for slug in slugs:
        try:
            persona = load_persona(slug)
            interval = _humanize_minutes(persona.POST_INTERVAL_MINUTES)
            print(f"  {slug}  —  {persona.DISPLAY_NAME}  (posts every {interval})")
        except ValueError as e:
            print(f"  {slug}  —  (could not load: {e})")


# --------------------------------------------------------------------------- #
# preview <slug> [-n N]
# --------------------------------------------------------------------------- #

def cmd_preview(args):
    slug = None
    count = 1
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-n", "--number"):
            i += 1
            if i >= len(args):
                print("Error: -n needs a number, e.g. -n 3")
                sys.exit(1)
            try:
                count = int(args[i])
            except ValueError:
                print(f"Error: -n expects a number, got '{args[i]}'.")
                sys.exit(1)
        elif slug is None:
            slug = arg
        else:
            print(f"Error: unexpected argument '{arg}'.")
            print("Usage: python -m schtick preview <slug> [-n N]")
            sys.exit(1)
        i += 1

    if not slug:
        print("Usage: python -m schtick preview <slug> [-n N]")
        personas = available_personas()
        if personas:
            print(f"Your characters: {', '.join(personas)}")
        sys.exit(1)
    if count < 1:
        print("Error: -n must be at least 1.")
        sys.exit(1)

    env_file = _load_env(slug)

    try:
        persona = load_persona(slug)
    except ValueError as e:
        print(e)
        sys.exit(1)

    # Import after env loading, mirroring the bot's late imports.
    from schtick import generation

    try:
        provider = generation.configure(persona)
    except ValueError as e:
        print(f"{e}\nAdd it to {env_file} and try again.")
        sys.exit(1)

    model = persona.MODEL or provider.default_model
    print(
        f"Previewing {persona.DISPLAY_NAME} via {provider.name} ({model}) — "
        f"{count} quote{'s' if count != 1 else ''}:\n"
    )
    for idx in range(count):
        try:
            quote = generation.generate_quote(persona, [])
        except Exception as e:
            print(f"Could not generate a quote: {e}")
            sys.exit(1)
        length = len(quote)
        over = "  [!] over target" if length > persona.CHAR_TARGET else ""
        print(quote)
        print(f"({length}/{persona.CHAR_TARGET} chars){over}")
        if idx < count - 1:
            print()


# --------------------------------------------------------------------------- #
# new  (the interactive wizard)
# --------------------------------------------------------------------------- #

CHARACTER_TEMPLATE = """\
---
name: <Name>
<PROVIDER_LINE>char_target: 240
post_interval_minutes: 214
fallbacks:
  - "A line <Name> would actually say."
  - "Another line <Name> would actually say."
---
You are <Name>. [Describe who they are in 2-3 sentences: their personality and
    their worldview — what do they believe, what can't they stand, how do they see
    the world? Be specific. The sharper the character, the sharper the quotes.]

    Write ONE short quote in their voice. [Say what a typical line sounds like — a
    muttered complaint? unsolicited advice? a wild theory stated as fact? Describe
    the kind of moment they'd be reacting to.]

    Their signature moves (use at least one, vary which):
    - [A habit of speech — a phrase they lean on, or a way they twist a sentence.]
    - [Another verbal habit — how they exaggerate, understate, or land a point.]
    - [A third move — maybe they incriminate themselves, name-drop, or overshare.]

    Topics they riff on. Rotate topics — do NOT lean on the same one repeatedly:
    [list 6-10 things this character has opinions about — the more specific and
    personal to them, the funnier].

    Rules:
    - Under 240 characters.
    - Land on a punchline; don't just state an opinion.
    - Be specific — concrete details and exact numbers are funnier than vague ones.
    - Keep it PG-13: no slurs, no gendered insults, no profanity aimed at a person.
    - Output the quote text ONLY: no surrounding quotation marks, no label, no
      hashtags, no emoji. (Quotation marks INSIDE the quote are fine.)

    Examples (this is the exact output format — bare text, no wrapping quotes).
    Replace these with 3-5 real lines in <Name>'s voice:

    [An example quote that really sounds like them.]

    [Another example — a different topic and a different rhythm.]

    [A third example, landing on a punchline.]
"""

ENV_TEMPLATE = """\
# Environment for {name} (slug: {slug})

# Bluesky API credentials
BLUESKY_HANDLE={handle}
BLUESKY_APP_PASSWORD={app_password}

# API key for quote generation ({provider})
{api_key_env}={api_key}

# Optional X/Twitter credentials — not set up by the wizard.
# See env.example if you also want to post to X/Twitter.
"""


def _compose_service_block(slug: str) -> str:
    service = "schtick-" + slug.replace("_", "-")
    return (
        f"  {service}:\n"
        f"    build: .\n"
        f"    image: schtick:latest\n"
        f"    command: {slug}\n"
        f"    env_file: .env.{slug}\n"
        f"    volumes:\n"
        f"      - ./data/{slug}:/home/appuser/data\n"
        f"    restart: unless-stopped\n"
    )


def cmd_new(args):
    try:
        _run_wizard()
    except (KeyboardInterrupt, EOFError):
        # Nothing may have been written yet if we abort early; the wizard writes
        # files only after it has what it needs, so a clean exit is safe here.
        print("\nCancelled. Nothing was created.")
        sys.exit(1)


def _choose_provider() -> object:
    """Ask which AI service writes the quotes. Enter accepts the default."""
    print("\nWhich AI writes the quotes?")
    print("  1. Gemini (Google) — free tier available  [default]")
    print("  2. Claude (Anthropic)")
    print("  3. DeepSeek")
    choice = input("Pick 1, 2 or 3:  ").strip()
    name = {"2": "anthropic", "3": "deepseek"}.get(choice, providers.DEFAULT_PROVIDER)
    return providers.get_provider(name)


def _run_wizard():
    print("Let's make a new character.\n")

    name = input("What's the character's name? (e.g. Aunt Carol)  ").strip()
    if not name:
        print("A character needs a name. Try again when you're ready.")
        sys.exit(1)

    slug = _slugify(name)
    if not slug:
        print(f"Couldn't make a filename from '{name}'. Try a name with letters or numbers.")
        sys.exit(1)

    directory = characters_dir()
    char_path = directory / f"{slug}.md"
    if char_path.exists():
        print(f"A character named '{slug}' already exists at {char_path}.")
        print("Pick a different name, or edit that file directly.")
        sys.exit(1)

    provider = _choose_provider()

    # --- Write the starter character file --------------------------------- #
    # The provider line is only written when it isn't the default, so a plain
    # character file stays as short as possible.
    provider_line = (
        "" if provider.name == providers.DEFAULT_PROVIDER else f"provider: {provider.name}\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    char_path.write_text(
        CHARACTER_TEMPLATE.replace("<Name>", name).replace("<PROVIDER_LINE>", provider_line),
        encoding="utf-8",
    )
    print(f"\nCreated {char_path}")
    print("  (It's a template — you'll fill in the voice in a minute.)")

    # --- Collect credentials for .env.<slug> ------------------------------ #
    print("\nNow a few credentials so the bot can post and write. Leave any blank")
    print("to drop in a placeholder you can fill in later.\n")

    handle = input(
        "Bluesky handle (e.g. yourname.bsky.social):  "
    ).strip()
    print("  App password — make one at bsky.app → Settings → App Passwords.")
    app_password = getpass.getpass("Bluesky app password (hidden):  ").strip()
    print(f"  {provider.name} key — get one at {provider.signup_url}.")
    api_key = getpass.getpass(f"{provider.api_key_env} (hidden):  ").strip()

    env_content = ENV_TEMPLATE.format(
        name=name,
        slug=slug,
        handle=handle or "your-handle.bsky.social",
        app_password=app_password or "your-app-password",
        provider=provider.name,
        api_key_env=provider.api_key_env,
        api_key=api_key or f"your-{provider.name}-api-key",
    )
    env_path = f".env.{slug}"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_content)
    print(f"\nCreated {env_path}")

    # --- Next steps -------------------------------------------------------- #
    print("\n" + "-" * 60)
    print(f"Done! Here's how to bring {name} to life:\n")
    print(f"  1. Edit {char_path}")
    print("     Write the voice — this is the fun part. Replace the [bracketed]")
    print("     fill-ins and the two placeholder fallback lines in the header.")
    print(f"  2. python -m schtick preview {slug}")
    print("     Hear the character before going live.")
    print(f"  3. python -m schtick run {slug}")
    print("     Go live — it posts on a schedule.\n")
    print("Running on Docker? Add this service to docker-compose.yml")
    print("(and create ./data/{}):\n".format(slug))
    print(_compose_service_block(slug))
    print("Want to post to X/Twitter too? See env.example for the optional keys,")
    print(f"then add them to {env_path}.")


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def main():
    argv = sys.argv[1:]
    command = argv[0] if argv else None

    if command in SUBCOMMANDS:
        rest = argv[1:]
        if command == "new":
            cmd_new(rest)
        elif command == "list":
            cmd_list(rest)
        elif command == "preview":
            cmd_preview(rest)
        elif command == "run":
            cmd_run(rest)
        return

    # Backward compatibility: a bare slug (or the PERSONA env var) runs the bot.
    slug = command if command else os.getenv("PERSONA")
    if not slug:
        print_usage()
        sys.exit(1)
    run_bot(slug)


if __name__ == "__main__":
    main()
