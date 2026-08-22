"""Unit tests for the posting rules in :mod:`schtick.bot`.

No network: the helpers under test are pure, and the few tests that need a
``PersonaBot`` build one with ``__new__`` and set the attributes they touch.
Never call ``PersonaBot(persona)`` here — the constructor logs in to Bluesky.
"""

import json
import logging
from datetime import datetime, timedelta

import pytest

import schedule

from schtick import bot as bot_module
from schtick.bot import (
    BLUESKY_CHAR_LIMIT,
    TWITTER_CHAR_LIMIT,
    PersonaBot,
    choose_quote,
    next_post_delay,
    rejection_reason,
)


class StubPersona:
    SLUG = "test-persona"
    DISPLAY_NAME = "Test Persona"
    POST_INTERVAL_MINUTES = 60
    FALLBACK_QUOTES = ["fallback one", "fallback two"]


def make_bot(tmp_path, **attrs):
    """Build a PersonaBot without running __init__ (which logs in to Bluesky)."""
    bot = PersonaBot.__new__(PersonaBot)
    bot.persona = StubPersona()
    bot.recent_posts = []
    bot.max_cache_size = 100
    bot.posts_cache_file = str(tmp_path / "recent_posts_test-persona.json")
    bot.last_post_file = str(tmp_path / "last_post_test-persona.json")
    bot.twitter_client = None
    for name, value in attrs.items():
        setattr(bot, name, value)
    return bot


# --- rejection_reason ------------------------------------------------------

def test_rejection_reason_accepts_a_fresh_short_quote():
    assert rejection_reason("a fresh line", ["something else"]) is None


def test_rejection_reason_flags_a_duplicate():
    assert rejection_reason("seen it", ["seen it"]) == "duplicate"


def test_rejection_reason_flags_over_length():
    long_quote = "x" * (BLUESKY_CHAR_LIMIT + 1)
    assert "over the" in rejection_reason(long_quote, [])


def test_rejection_reason_allows_exactly_the_limit():
    assert rejection_reason("x" * BLUESKY_CHAR_LIMIT, []) is None


def test_rejection_reason_flags_empty():
    assert rejection_reason("   ", []) == "empty"


# --- choose_quote ----------------------------------------------------------

def test_choose_quote_takes_the_first_acceptable_candidate():
    chosen = choose_quote(iter(["fresh line"]), ["old line"], ["fallback one"])
    assert chosen == "fresh line"


def test_choose_quote_stops_generating_once_one_is_accepted():
    consumed = []

    def candidates():
        for quote in ["dup", "fresh", "never reached"]:
            consumed.append(quote)
            yield quote

    chosen = choose_quote(candidates(), ["dup"], ["fallback one"])
    assert chosen == "fresh"
    assert consumed == ["dup", "fresh"]


def test_choose_quote_skips_duplicates_and_over_length_candidates():
    too_long = "x" * (BLUESKY_CHAR_LIMIT + 1)
    chosen = choose_quote(iter(["dup", too_long, "fresh"]), ["dup"], ["fallback one"])
    assert chosen == "fresh"


def test_choose_quote_falls_back_when_every_candidate_is_rejected():
    chosen = choose_quote(iter(["dup", "dup"]), ["dup"], ["fallback one", "fallback two"])
    assert chosen in ("fallback one", "fallback two")


def test_choose_quote_falls_back_when_generation_yields_nothing():
    # An empty candidate stream is how the bot signals a failing provider.
    chosen = choose_quote(iter([]), [], ["fallback one"])
    assert chosen == "fallback one"


def test_choose_quote_never_reuses_a_posted_fallback():
    chosen = choose_quote(iter([]), ["fallback one"], ["fallback one", "fallback two"])
    assert chosen == "fallback two"


def test_choose_quote_ignores_over_length_fallbacks():
    too_long = "x" * (BLUESKY_CHAR_LIMIT + 1)
    chosen = choose_quote(iter([]), [], [too_long, "fallback two"])
    assert chosen == "fallback two"


def test_choose_quote_returns_none_when_fallbacks_are_exhausted():
    assert choose_quote(iter([]), ["fallback one", "fallback two"],
                        ["fallback one", "fallback two"]) is None


def test_choose_quote_returns_none_without_any_fallbacks():
    assert choose_quote(iter(["dup"]), ["dup"], []) is None


# --- post_quote ------------------------------------------------------------

def test_post_quote_skips_the_slot_when_nothing_is_postable(tmp_path, caplog):
    bot = make_bot(tmp_path, recent_posts=["fallback one", "fallback two"])
    bot.generate_quote = lambda: None  # provider down
    posted = []
    bot.post_to_bluesky = lambda text: posted.append(text) or True
    bot.post_to_twitter = lambda text: posted.append(text) or True

    with caplog.at_level(logging.WARNING):
        assert bot.post_quote() is False

    assert posted == []
    assert "skipping this post" in caplog.text


def test_post_quote_posts_an_unused_fallback_during_an_outage(tmp_path):
    bot = make_bot(tmp_path, recent_posts=["fallback one"])
    bot.generate_quote = lambda: None
    posted = []
    bot.post_to_bluesky = lambda text: posted.append(text) or True
    bot.post_to_twitter = lambda text: True

    assert bot.post_quote() is True
    assert posted == ["fallback two"]


def test_post_quote_reports_success_only_after_bluesky_accepts(tmp_path):
    bot = make_bot(tmp_path)
    bot.generate_quote = lambda: "a fresh line"
    bluesky, tweets = [], []
    bot.post_to_bluesky = lambda text: bluesky.append(text) or True
    bot.post_to_twitter = lambda text: tweets.append(text) or True

    assert bot.post_quote() is True
    assert bluesky == ["a fresh line"]
    assert tweets == ["a fresh line"]


def test_post_quote_fails_and_skips_the_tweet_when_bluesky_rejects(tmp_path, caplog):
    # Bluesky is the baseline platform: cross-posting a quote that never landed
    # there would publish it under the character's name on Twitter only.
    bot = make_bot(tmp_path)
    bot.generate_quote = lambda: "a fresh line"
    tweets = []
    bot.post_to_bluesky = lambda text: False
    bot.post_to_twitter = lambda text: tweets.append(text) or True

    with caplog.at_level(logging.ERROR):
        assert bot.post_quote() is False

    assert tweets == []
    assert "Bluesky post failed" in caplog.text


def test_candidates_stop_at_the_first_generation_error(tmp_path):
    bot = make_bot(tmp_path)
    calls = []

    def flaky():
        calls.append(1)
        return None

    bot.generate_quote = flaky
    assert list(bot._candidates(10)) == []
    assert len(calls) == 1


# --- Twitter length guard --------------------------------------------------

class StubTwitterClient:
    def __init__(self):
        self.sent = []

    def create_tweet(self, text):
        self.sent.append(text)
        return type("Response", (), {"data": {"id": "123"}})()


def test_post_to_twitter_skips_an_over_length_quote(tmp_path, caplog):
    client = StubTwitterClient()
    bot = make_bot(tmp_path, twitter_client=client)
    quote = "x" * (TWITTER_CHAR_LIMIT + 1)

    with caplog.at_level(logging.WARNING):
        assert bot.post_to_twitter(quote) is False

    assert client.sent == []
    assert "skipping the tweet" in caplog.text


def test_post_to_twitter_sends_a_quote_at_the_limit_untruncated(tmp_path):
    client = StubTwitterClient()
    bot = make_bot(tmp_path, twitter_client=client)
    quote = "x" * TWITTER_CHAR_LIMIT

    assert bot.post_to_twitter(quote) is True
    assert client.sent == [quote]


# --- startup guard ---------------------------------------------------------

def test_next_post_delay_posts_now_without_a_record():
    assert next_post_delay(None, 60, datetime(2026, 1, 1, 12, 0)) is None


def test_next_post_delay_posts_now_when_the_interval_has_elapsed():
    now = datetime(2026, 1, 1, 12, 0)
    assert next_post_delay(now - timedelta(minutes=61), 60, now) is None


def test_next_post_delay_waits_out_the_remainder_of_the_interval():
    now = datetime(2026, 1, 1, 12, 0)
    delay = next_post_delay(now - timedelta(minutes=10), 60, now)
    assert delay == timedelta(minutes=50)


def test_next_post_delay_caps_a_future_timestamp_at_one_interval():
    now = datetime(2026, 1, 1, 12, 0)
    delay = next_post_delay(now + timedelta(hours=5), 60, now)
    assert delay == timedelta(minutes=60)


def test_last_post_time_round_trips(tmp_path):
    bot = make_bot(tmp_path)
    when = datetime(2026, 1, 1, 12, 0)
    bot.save_last_post_time(when)

    assert json.load(open(bot.last_post_file))["last_post"] == when.isoformat()
    assert bot.load_last_post_time() == when


def test_load_last_post_time_tolerates_a_corrupt_file(tmp_path):
    bot = make_bot(tmp_path)
    with open(bot.last_post_file, "w") as f:
        f.write("{not json")
    assert bot.load_last_post_time() is None


class StopLoop(Exception):
    """Raised from the patched sleep to break run_scheduler's forever loop."""


@pytest.fixture
def stop_scheduler_loop(monkeypatch):
    schedule.clear()

    def boom(_seconds):
        raise StopLoop

    monkeypatch.setattr(bot_module.time, "sleep", boom)
    yield
    schedule.clear()


def test_run_scheduler_skips_the_startup_post_after_a_recent_post(tmp_path, stop_scheduler_loop):
    bot = make_bot(tmp_path)
    posted = []
    bot.post_quote = lambda: posted.append("post") or True

    last_post = datetime.now() - timedelta(minutes=10)
    bot.save_last_post_time(last_post)

    with pytest.raises(StopLoop):
        bot.run_scheduler()

    assert posted == []
    # The next run is anchored to the last post, not to startup, so the cadence
    # survives a restart.
    expected = last_post + timedelta(minutes=StubPersona.POST_INTERVAL_MINUTES)
    assert abs((schedule.jobs[0].next_run - expected).total_seconds()) < 5


def test_run_scheduler_posts_immediately_without_a_record(tmp_path, stop_scheduler_loop):
    bot = make_bot(tmp_path)
    posted = []
    bot.post_quote = lambda: posted.append("post") or True

    with pytest.raises(StopLoop):
        bot.run_scheduler()

    assert posted == ["post"]


def test_run_scheduler_posts_immediately_when_the_interval_has_elapsed(tmp_path, stop_scheduler_loop):
    bot = make_bot(tmp_path)
    posted = []
    bot.post_quote = lambda: posted.append("post") or True
    bot.save_last_post_time(datetime.now() - timedelta(minutes=StubPersona.POST_INTERVAL_MINUTES + 1))

    with pytest.raises(StopLoop):
        bot.run_scheduler()

    assert posted == ["post"]
