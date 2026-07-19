#!/usr/bin/env python3
"""
CLI entry point for the Persona Bot engine.

Usage:
    python -m persona_bot <slug>

The persona slug may also be supplied via the PERSONA environment variable.
Environment variables are loaded from `.env.<slug>` if present, otherwise `.env`,
so several personas can run from one checkout on the same machine.
"""

import os
import sys
import logging

from dotenv import load_dotenv

from personas import load_persona, AVAILABLE_PERSONAS

logger = logging.getLogger(__name__)


def main():
    """Main function to run the bot."""
    # Determine the persona slug: CLI arg, then PERSONA env var.
    slug = sys.argv[1] if len(sys.argv) > 1 else os.getenv('PERSONA')

    if not slug:
        print("Usage: python -m persona_bot <slug>")
        print(f"Available personas: {', '.join(AVAILABLE_PERSONAS)}")
        print("(You can also set the PERSONA environment variable.)")
        sys.exit(1)

    # Load environment variables BEFORE constructing the bot. Prefer a
    # persona-specific .env.<slug> file if one exists, else fall back to .env.
    persona_env = f'.env.{slug}'
    if os.path.exists(persona_env):
        load_dotenv(persona_env)
    else:
        load_dotenv()

    try:
        persona = load_persona(slug)
    except ValueError as e:
        print(e)
        sys.exit(1)

    # Import here so bot construction (and its logging setup) happens after env
    # loading and persona resolution.
    from persona_bot.bot import PersonaBot

    try:
        bot = PersonaBot(persona)
        bot.run_scheduler()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise


if __name__ == "__main__":
    main()
