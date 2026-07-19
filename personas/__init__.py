"""Persona registry: each persona is a plain module with prompt/fallback/config constants."""

import importlib

AVAILABLE_PERSONAS = ["larry_david", "kramer"]


def load_persona(slug: str):
    """Import and return the persona module for the given slug.

    Raises ValueError with the list of valid slugs if the slug is unknown.
    """
    if slug not in AVAILABLE_PERSONAS:
        raise ValueError(
            f"Unknown persona '{slug}'. Available personas: {', '.join(AVAILABLE_PERSONAS)}"
        )
    return importlib.import_module(f"personas.{slug}")
