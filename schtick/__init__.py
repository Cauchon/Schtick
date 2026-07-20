"""Schtick engine: a generic Bluesky/Twitter quote bot driven by character files."""

__all__ = ["PersonaBot"]


def __getattr__(name):
    # Lazy re-export so that importing lightweight modules (schtick.persona,
    # schtick.generation) does not drag in bot.py's heavy dependencies
    # (google.generativeai, tweepy, atproto) until a bot is actually built.
    if name == "PersonaBot":
        from schtick.bot import PersonaBot

        return PersonaBot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
