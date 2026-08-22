"""Shared quote generation.

The single generation path shared by the bot and the ``preview`` subcommand,
so what you hear in a preview is exactly what the bot would post. Which AI
service does the writing is the character's choice (frontmatter
``provider``); see schtick/providers.py.

Callers must call ``configure(persona)`` once before ``generate_quote``.
"""

import os

from schtick import providers

# The token character files use to mark where the recent-quotes block goes.
RECENT_QUOTES_PLACEHOLDER = "{recent_quotes_text}"

# Appended to prompts that do NOT contain the placeholder inline, so every
# character still gets the "avoid repeats" context.
RECENT_QUOTES_TRAILER = (
    "\n\nRecent quotes (AVOID repeating these specific topics or exact phrasings):\n"
    "{recent_quotes_text}\n"
)


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


def generate_quote(persona, recent_quotes: list) -> str:
    """Generate a single quote for ``persona``. Exceptions propagate to callers.

    ``configure(persona)`` must have run first.
    """
    formatted_prompt = build_prompt(persona, recent_quotes)

    provider = providers.get_provider(persona.PROVIDER)
    model = persona.MODEL or provider.default_model

    quote = provider.generate(formatted_prompt, model, persona.GENERATION_CONFIG).strip()

    # Remove one pair of surrounding double quotes if present. The length guard
    # keeps a lone `"` from being read as its own opening AND closing quote,
    # which would strip the whole reply to "" — an empty post the bot would then
    # have to reject.
    if len(quote) >= 2 and quote.startswith('"') and quote.endswith('"'):
        quote = quote[1:-1]

    return quote
