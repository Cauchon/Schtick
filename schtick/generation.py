"""Shared quote generation via Gemini.

Extracted from the old persona_bot/bot.py generate_quote() and
test_bot.py test_quote_generation() so the bot and the test suite generate
quotes identically. The caller is responsible for having already called
``genai.configure(...)``.
"""

import google.generativeai as genai

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


def generate_quote(persona, recent_quotes: list) -> str:
    """Generate a single quote for ``persona``. Exceptions propagate to callers.

    Preserves the legacy per-persona branch: if GENERATION_CONFIG is truthy it
    is passed through as a GenerationConfig; if falsy, generate_content is
    called with NO generation_config kwarg at all (Kramer's original behavior).
    """
    formatted_prompt = build_prompt(persona, recent_quotes)

    model = genai.GenerativeModel('gemini-flash-latest')
    if persona.GENERATION_CONFIG:
        response = model.generate_content(
            formatted_prompt,
            generation_config=genai.types.GenerationConfig(**persona.GENERATION_CONFIG),
        )
    else:
        response = model.generate_content(formatted_prompt)

    quote = response.text.strip()

    # Remove one pair of surrounding double quotes if present.
    if quote.startswith('"') and quote.endswith('"'):
        quote = quote[1:-1]

    return quote
