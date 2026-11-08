"""Shared environment settings, with no SDK imports or network calls."""

from typing import Mapping


TWITTER_ENV = (
    "TWITTER_BEARER_TOKEN",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_SECRET",
)


def x_enabled(environment: Mapping[str, str]) -> bool:
    """X is opt-in; credentials alone never enable paid cross-posting."""
    value = environment.get("X_ENABLED", "").strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"", "false", "0", "no", "off"}:
        return False
    raise ValueError("X_ENABLED must be true or false")
