"""Fixtures shared by the whole offline suite.

``schtick.generation`` sleeps between retries of a transient provider failure,
and in production that is real wall-clock time (minutes). The autouse fixture
here swaps that one module global for a recorder in every test, so no test can
ever sleep for real — and any test that wants to assert on the backoff just
takes ``recorded_sleeps`` as an argument.
"""

import pytest

from schtick import generation


@pytest.fixture(autouse=True)
def recorded_sleeps(monkeypatch):
    """Record retry delays instead of sleeping them. Returns the list."""
    slept = []
    monkeypatch.setattr(generation, "sleep", slept.append)
    return slept
