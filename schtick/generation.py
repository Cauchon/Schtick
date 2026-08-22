"""Shared quote generation.

The single generation path shared by the bot and the ``preview`` subcommand,
so what you hear in a preview is exactly what the bot would post. Which AI
service does the writing is the character's choice (frontmatter
``provider``); see schtick/providers.py.

Callers must call ``configure(persona)`` once before ``generate_quote``.
"""

import logging
import os
import time
from typing import Optional

from schtick import providers

logger = logging.getLogger(__name__)

# The token character files use to mark where the recent-quotes block goes.
RECENT_QUOTES_PLACEHOLDER = "{recent_quotes_text}"

# Appended to prompts that do NOT contain the placeholder inline, so every
# character still gets the "avoid repeats" context.
RECENT_QUOTES_TRAILER = (
    "\n\nRecent quotes (AVOID repeating these specific topics or exact phrasings):\n"
    "{recent_quotes_text}\n"
)

# --- Transient-failure retry policy ----------------------------------------
#
# A provider outage is not all-or-nothing: in the August 2026 Gemini episode
# roughly one call in three succeeded while the rest returned 503. Without
# retries a single 503 ended the whole posting slot (see bot.py's
# `_candidates`), so the bots went silent for a day. One backoff sequence turns
# that into a posted quote.
#
# Delays between successive attempts, so up to len()+1 = 5 attempts spanning
# ~3.25 minutes. Deliberately longer than an SDK's own retry: this is riding
# out a minutes-long capacity wobble, not a network blip. The scheduler loop
# blocks for that whole time, which is fine — posts are hours apart.
RETRY_DELAYS_SECONDS = (15, 30, 60, 90)

# The statuses worth waiting out: rate limits and server-side/gateway faults.
# Everything else (auth, bad request, an unknown model) fails the same way on
# every attempt, so retrying it only burns quota and delays the fallback.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Bound as a module global so tests can replace it with a recorder; a direct
# `time.sleep(...)` call would be unpatchable without touching the stdlib.
sleep = time.sleep


def transient_status(exc: BaseException) -> Optional[int]:
    """Return the HTTP status of ``exc`` if it is one worth retrying, else None.

    Each SDK spells the status differently — google-genai's ``APIError`` has
    ``.code``, anthropic's and openai's ``APIStatusError`` have
    ``.status_code`` — so both are read with ``getattr`` rather than by
    importing (and thereby requiring) three SDKs here. An exception carrying no
    status at all, including our own RuntimeErrors for a refusal or an empty
    reply, is not transient.
    """
    for attribute in ("code", "status_code"):
        status = getattr(exc, attribute, None)
        # bool is an int subclass; a True/False attribute is not a status.
        if isinstance(status, bool) or not isinstance(status, int):
            continue
        if status in TRANSIENT_STATUS_CODES:
            return status
    return None


def format_recent_quotes(recent_quotes: list) -> str:
    """Format the recent-quotes list exactly as the legacy code did."""
    return "\n    - ".join(f'"{q}"' for q in recent_quotes)


def build_prompt(persona, recent_quotes: list) -> str:
    """Build the final prompt for ``persona`` given ``recent_quotes``.

    Uses ``str.replace`` (NOT ``str.format``) so that user-authored prose may
    contain literal braces without breaking. For the two legacy characters
    (placeholder inline) the result is byte-identical to the old
    ``prompt.format(recent_quotes_text=...)`` output.
    """
    recent_quotes_text = format_recent_quotes(recent_quotes)
    if RECENT_QUOTES_PLACEHOLDER in persona.PROMPT:
        return persona.PROMPT.replace(RECENT_QUOTES_PLACEHOLDER, recent_quotes_text)
    trailer = RECENT_QUOTES_TRAILER.replace(RECENT_QUOTES_PLACEHOLDER, recent_quotes_text)
    return persona.PROMPT + trailer


def configure(persona):
    """Configure the client for ``persona``'s provider and return the provider.

    The API key comes from the environment variable the provider declares, so
    which key is required follows from the character file.

    Raises ``ValueError`` naming the missing variable if it isn't set.
    """
    provider = providers.get_provider(persona.PROVIDER)
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(
            f"Missing {provider.api_key_env} — {persona.SLUG} uses the "
            f"'{provider.name}' provider (get a key at {provider.signup_url})."
        )
    provider.configure(api_key)
    return provider


def _generate_with_retries(provider, prompt: str, model: str, generation_config: dict) -> str:
    """Call ``provider.generate``, retrying transient failures with backoff.

    Walks ``RETRY_DELAYS_SECONDS``; anything ``transient_status`` does not
    recognise is re-raised on the first attempt, and the last exception is
    re-raised once the schedule is exhausted.
    """
    max_attempts = len(RETRY_DELAYS_SECONDS) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            return provider.generate(prompt, model, generation_config)
        except Exception as exc:
            status = transient_status(exc)
            if status is None or attempt == max_attempts:
                raise
            delay = RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                f"{provider.name} returned {status} on attempt {attempt}/{max_attempts} "
                f"({exc}); retrying in {delay}s"
            )
            sleep(delay)


def generate_quote(persona, recent_quotes: list) -> str:
    """Generate a single quote for ``persona``. Exceptions propagate to callers.

    Transient provider failures (see ``TRANSIENT_STATUS_CODES``) are retried
    here on the ``RETRY_DELAYS_SECONDS`` backoff before anything propagates, so
    a caller only sees an exception once the provider has failed every attempt
    — or failed for a reason retrying cannot fix.

    ``configure(persona)`` must have run first.
    """
    formatted_prompt = build_prompt(persona, recent_quotes)

    provider = providers.get_provider(persona.PROVIDER)
    model = persona.MODEL or provider.default_model

    quote = _generate_with_retries(
        provider, formatted_prompt, model, persona.GENERATION_CONFIG
    ).strip()

    # Remove one pair of surrounding double quotes if present. The length guard
    # keeps a lone `"` from being read as its own opening AND closing quote,
    # which would strip the whole reply to "" — an empty post the bot would then
    # have to reject.
    if len(quote) >= 2 and quote.startswith('"') and quote.endswith('"'):
        quote = quote[1:-1]

    return quote
