"""Character loader: reads persona definitions from ``characters/<slug>.md``.

Each character file is markdown with a YAML frontmatter block delimited by
``---`` fences, followed by the prompt prose as the body:

    ---
    name: Larry David
    char_target: 240
    ---
    You are Larry David ...

The body (PROMPT) is preserved VERBATIM after the closing fence — no strip,
no dedent, trailing whitespace and final-newline presence/absence intact — so
the migration can byte-compare it against the legacy Python prompts.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class Persona:
    """The engine contract. Attribute names are load-bearing — do not rename."""

    SLUG: str
    DISPLAY_NAME: str
    PROMPT: str
    FALLBACK_QUOTES: List[str] = field(default_factory=list)
    GENERATION_CONFIG: dict = field(default_factory=dict)
    CHAR_TARGET: int = 240
    POST_INTERVAL_MINUTES: int = 214


def characters_dir() -> Path:
    """Return the directory that holds the ``*.md`` character files.

    Resolved relative to this file (NOT the current working directory), so it
    works when cwd differs from the code location — e.g. in Docker where cwd is
    /home/appuser/data while the code lives in /app. Overridable via the
    ``SCHTICK_CHARACTERS_DIR`` environment variable.
    """
    override = os.getenv("SCHTICK_CHARACTERS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "characters"


def available_personas() -> List[str]:
    """Return the sorted slugs (filename stems) of the available characters.

    Tolerates the characters directory not existing yet (returns []).
    """
    directory = characters_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def _parse_frontmatter(text: str, source: str) -> "tuple[dict, str]":
    """Split a character file into (frontmatter dict, verbatim body).

    The file must start with ``---\\n``; the frontmatter runs until the next
    line that is exactly ``---``. The body (PROMPT) is everything after that
    closing fence line's newline, preserved VERBATIM.
    """
    if not text.startswith("---\n"):
        raise ValueError(
            f"Malformed character file {source}: must start with a '---' frontmatter fence."
        )

    # Scan the lines after the opening fence for a line that is exactly '---',
    # tracking byte offsets so the body can be sliced out verbatim.
    body_start = None
    frontmatter_end = None  # offset of the closing fence line's start
    offset = len("---\n")
    while offset <= len(text):
        newline = text.find("\n", offset)
        if newline == -1:
            line = text[offset:]
            line_end = len(text)
        else:
            line = text[offset:newline]
            line_end = newline + 1  # include the newline
        if line == "---":
            frontmatter_end = offset
            body_start = line_end
            break
        if newline == -1:
            break
        offset = newline + 1

    if body_start is None:
        raise ValueError(
            f"Malformed character file {source}: no closing '---' frontmatter fence found."
        )

    frontmatter_text = text[len("---\n"):frontmatter_end]
    body = text[body_start:]

    meta = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(meta, dict):
        raise ValueError(
            f"Malformed character file {source}: frontmatter is not a mapping."
        )
    return meta, body


def load_persona(slug: str) -> Persona:
    """Load and return the :class:`Persona` for ``slug`` (a character filename stem).

    Raises ``ValueError`` with the list of valid slugs if the slug is unknown,
    or if the character file's frontmatter is missing/malformed.
    """
    available = available_personas()
    if slug not in available:
        raise ValueError(
            f"Unknown persona '{slug}'. Available personas: {', '.join(available)}"
        )

    path = characters_dir() / f"{slug}.md"
    text = path.read_text(encoding="utf-8")

    meta, body = _parse_frontmatter(text, source=path.name)

    name = meta.get("name")
    if not name:
        raise ValueError(
            f"Malformed character file {path.name}: missing required 'name' field."
        )

    generation = meta.get("generation")
    generation_config = dict(generation) if generation else {}

    fallbacks = meta.get("fallbacks") or []

    return Persona(
        SLUG=slug,
        DISPLAY_NAME=name,
        PROMPT=body,
        FALLBACK_QUOTES=list(fallbacks),
        GENERATION_CONFIG=generation_config,
        CHAR_TARGET=meta.get("char_target", 240),
        POST_INTERVAL_MINUTES=meta.get("post_interval_minutes", 214),
    )
