#!/usr/bin/env python3
"""
Schtick - A Bluesky/Twitter bot that posts fictional persona quotes.
Posts on a schedule with modern-day observations and complaints.

The persona (voice, prompt, fallbacks, config) is loaded from a character file;
see the character contract in schtick/persona.py.
"""

import os
import json
import time
import schedule
import logging
import logging.handlers
from datetime import datetime, timedelta
from typing import Iterable, List, Optional
import random

import tweepy
from atproto import Client
try:
    from atproto import RichText
except ImportError:  # Older atproto version without RichText helper
    RichText = None

from schtick import generation

logger = logging.getLogger(__name__)

# Hard platform limits. Bluesky rejects the post outright above 300 graphemes;
# len() over-counts graphemes, so testing the string length is conservative.
BLUESKY_CHAR_LIMIT = 300
TWITTER_CHAR_LIMIT = 280

LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def configure_logging(slug: str):
    """Configure logging to a persona-specific log file and the console.

    Done in a function (not at import time) because the log filename depends on
    the persona slug. The file handler rotates: the bot runs for months on a
    Raspberry Pi SD card, where an unbounded log eventually fills the card.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.handlers.RotatingFileHandler(
                f'{slug}.log',
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
            ),
            logging.StreamHandler()
        ]
    )


def rejection_reason(quote: str, recent_posts: List[str],
                     limit: int = BLUESKY_CHAR_LIMIT) -> Optional[str]:
    """Return why ``quote`` cannot be posted, or None if it can be.

    The reason is a human-readable fragment for the log line.
    """
    if not quote or not quote.strip():
        return "empty"
    if quote in recent_posts:
        return "duplicate"
    if len(quote) > limit:
        return f"{len(quote)} chars, over the {limit}-character limit"
    return None


def choose_quote(candidates: Iterable[str], recent_posts: List[str],
                 fallbacks: List[str],
                 limit: int = BLUESKY_CHAR_LIMIT) -> Optional[str]:
    """Pick a postable quote, or None if there is nothing safe to post.

    ``candidates`` is consumed lazily so the caller can stop paying for
    generation as soon as one is accepted; exhausting it — including yielding
    nothing at all, which is how a caller signals a failing provider — falls
    through to the character's fallbacks. Fallbacks are held to the same rules
    as generated quotes, so an outage can no longer walk the bot through its
    fallback list and then start repeating it.
    """
    for attempt, candidate in enumerate(candidates, start=1):
        reason = rejection_reason(candidate, recent_posts, limit)
        if reason is None:
            return candidate
        logger.info(f"Rejected generated quote ({reason}), trying again (attempt {attempt})")

    usable = [q for q in fallbacks if rejection_reason(q, recent_posts, limit) is None]
    if not usable:
        return None
    logger.warning(f"No usable generated quote; falling back ({len(usable)} unused fallbacks left)")
    return random.choice(usable)


def next_post_delay(last_post_time: Optional[datetime], interval_minutes: int,
                    now: datetime) -> Optional[timedelta]:
    """Return how long to wait before the first post, or None to post now.

    Measured from ``last_post_time``, not from ``now``, so a restart neither
    fires an extra post nor slides the cadence forward.
    """
    if last_post_time is None:
        return None
    due = last_post_time + timedelta(minutes=interval_minutes)
    if due <= now:
        return None
    # A clock or container-timezone shift can leave a timestamp in the future;
    # capping the wait at one interval keeps that from stalling the bot for hours.
    return min(due - now, timedelta(minutes=interval_minutes))


class PersonaBot:
    def __init__(self, persona):
        """Initialize the Persona Bot with Bluesky client and configuration."""
        self.persona = persona

        # Configure logging first so the persona's log file is used from here on.
        configure_logging(persona.SLUG)

        self.client = Client()
        self.posts_cache_file = f'recent_posts_{persona.SLUG}.json'
        self.legacy_cache_file = 'recent_posts.json'
        self.last_post_file = f'last_post_{persona.SLUG}.json'
        self.max_cache_size = 100  # Keep last 100 posts to avoid repeats
        self.recent_posts = self.load_recent_posts()

        # Bluesky credentials
        self.handle = os.getenv('BLUESKY_HANDLE')
        self.app_password = os.getenv('BLUESKY_APP_PASSWORD')

        if not all([self.handle, self.app_password]):
            raise ValueError("Missing required environment variables. Check BLUESKY_HANDLE and BLUESKY_APP_PASSWORD")

        # AI provider — which one, and therefore which API key is required,
        # comes from the character file. Raises ValueError naming the key.
        self.provider = generation.configure(persona)
        logger.info(f"Generating with {self.provider.name} ({persona.MODEL or self.provider.default_model})")

        # Login to Bluesky
        self.client.login(self.handle, self.app_password)
        logger.info(f"Logged in to Bluesky as {self.handle}")

        # Twitter API v2 Client
        self.twitter_client = None
        twitter_bearer_token = os.getenv('TWITTER_BEARER_TOKEN')

        if twitter_bearer_token:
            try:
                self.twitter_client = tweepy.Client(
                    bearer_token=twitter_bearer_token,
                    consumer_key=os.getenv('TWITTER_API_KEY'),
                    consumer_secret=os.getenv('TWITTER_API_SECRET'),
                    access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
                    access_token_secret=os.getenv('TWITTER_ACCESS_SECRET')
                )
                logger.info("Initialized Twitter API v2 client")
            except Exception as e:
                logger.error(f"Error initializing Twitter client: {e}")
                self.twitter_client = None
        else:
            logger.warning("Twitter Bearer Token not found. Twitter posting disabled.")

    def load_recent_posts(self) -> List[str]:
        """Load recent posts from cache file to avoid duplicates.

        Migration: if the persona-specific cache file does not exist but the
        legacy shared cache does, adopt the legacy contents and save them to the
        new path (leaving the legacy file in place).
        """
        try:
            if os.path.exists(self.posts_cache_file):
                with open(self.posts_cache_file, 'r') as f:
                    return json.load(f)
            elif os.path.exists(self.legacy_cache_file):
                with open(self.legacy_cache_file, 'r') as f:
                    legacy_posts = json.load(f)
                logger.info(f"Migrating legacy cache {self.legacy_cache_file} to {self.posts_cache_file}")
                self.recent_posts = legacy_posts
                self.save_recent_posts()
                return legacy_posts
        except Exception as e:
            logger.warning(f"Could not load recent posts cache: {e}")
        return []

    def save_recent_posts(self):
        """Save recent posts to cache file."""
        try:
            with open(self.posts_cache_file, 'w') as f:
                json.dump(self.recent_posts, f)
        except Exception as e:
            logger.error(f"Could not save recent posts cache: {e}")

    def load_last_post_time(self) -> Optional[datetime]:
        """Return the time of the last successful post, or None if unrecorded."""
        try:
            if os.path.exists(self.last_post_file):
                with open(self.last_post_file, 'r') as f:
                    return datetime.fromisoformat(json.load(f)['last_post'])
        except Exception as e:
            logger.warning(f"Could not read {self.last_post_file}: {e}")
        return None

    def save_last_post_time(self, when: Optional[datetime] = None):
        """Record the time of a successful post so a restart can skip ahead.

        Naive local time, matching what ``schedule`` compares against.
        """
        when = when or datetime.now()
        try:
            with open(self.last_post_file, 'w') as f:
                json.dump({'last_post': when.isoformat()}, f)
        except Exception as e:
            logger.error(f"Could not save {self.last_post_file}: {e}")

    def generate_quote(self) -> Optional[str]:
        """Generate a new persona quote, or None if the provider errored."""
        try:
            # Get last 10 recent posts to avoid repetition
            recent_quotes = self.recent_posts[-10:] if self.recent_posts else []

            if recent_quotes:
                logger.info(f"Including {len(recent_quotes)} recent quotes in prompt to avoid repetition")

            return generation.generate_quote(self.persona, recent_quotes)

        except Exception as e:
            logger.error(f"Error generating quote: {e}")
            return None

    def _candidates(self, max_attempts: int) -> Iterable[str]:
        """Yield up to ``max_attempts`` generated quotes, stopping on an error.

        A generation error ends the run rather than retrying: the provider is
        down or over quota, and further attempts only burn quota to fail again.
        """
        for _ in range(max_attempts):
            quote = self.generate_quote()
            if quote is None:
                return
            yield quote

    def post_to_twitter(self, quote: str) -> bool:
        """Post the quote to Twitter (X) using API v2. Returns True on success."""
        if not self.twitter_client:
            logger.info("Twitter client not configured; skipping tweet.")
            return False

        # Truncating would post half a joke under the character's name, so an
        # over-length quote loses the tweet, not its ending. Bluesky's 300 is
        # the looser limit, so this is reachable with a legitimately posted quote.
        if len(quote) > TWITTER_CHAR_LIMIT:
            logger.warning(f"Quote is {len(quote)} characters, over Twitter's "
                           f"{TWITTER_CHAR_LIMIT}-character limit; skipping the tweet.")
            return False

        try:
            response = self.twitter_client.create_tweet(text=quote)
            if response and response.data and response.data.get('id'):
                logger.info(f"Successfully tweeted quote (ID: {response.data['id']})")
                return True
            else:
                logger.error("Failed to get tweet ID from Twitter API response")
                return False

        except tweepy.TweepyException as e:
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                error_msg = str(e)

                if status_code == 403:
                    logger.error("Twitter API Error: Authentication or permission error. "
                               "Please check your API keys and app permissions.")
                elif status_code == 401:
                    logger.error("Twitter API Error: Invalid or expired credentials. "
                               "Please check your Twitter API keys and access tokens.")
                elif status_code == 429:
                    logger.error("Twitter API Error: Rate limit exceeded. The bot will try again later.")
                else:
                    logger.error(f"Twitter API Error ({status_code}): {error_msg}")
            else:
                logger.error(f"Twitter API Error: {str(e)}")

            return False

    def _send_bluesky_post(self, text: str):
        """Send a single post to Bluesky, using RichText if available."""
        if RichText is not None:
            rt = RichText(text)
            rt.detect_links()
            return self.client.send_post(text=rt.text, facets=rt.facets)
        return self.client.send_post(text=text)

    def post_to_bluesky(self, text: str) -> bool:
        """Post the given text to Bluesky, re-logging in if the session expired."""
        try:
            post = self._send_bluesky_post(text)
        except Exception as e:
            # Long-running sessions get revoked/expire; the client never recovers
            # on its own, so re-authenticate and retry once before giving up.
            logger.warning(f"Bluesky post failed ({e}); re-logging in and retrying...")
            try:
                self.client = Client()
                self.client.login(self.handle, self.app_password)
                logger.info(f"Re-logged in to Bluesky as {self.handle}")
                post = self._send_bluesky_post(text)
            except Exception as e2:
                logger.error(f"Error posting to Bluesky after re-login: {e2}")
                return False

        self.recent_posts.append(text)
        # Keep only the most recent posts in cache
        if len(self.recent_posts) > self.max_cache_size:
            self.recent_posts = self.recent_posts[-self.max_cache_size:]
        self.save_recent_posts()
        self.save_last_post_time()
        logger.info(f"Posted to Bluesky: {text}")
        return True

    def post_quote(self):
        """Generate and post a new persona quote to Bluesky."""
        try:
            max_attempts = 10
            quote = choose_quote(
                self._candidates(max_attempts),
                self.recent_posts,
                self.persona.FALLBACK_QUOTES,
            )

            if quote is None:
                # Every fallback is spent (or over-length): repeating one is
                # worse than staying quiet until the next slot.
                logger.warning("No postable quote and no unused fallback left; skipping this post.")
                return False

            # Bluesky is the baseline platform: if the quote did not land there
            # it is not "posted", so the slot fails rather than half-succeeding.
            # Cross-posting to Twitter here would put the line out under the
            # character's name on the secondary platform only, and — because
            # post_to_bluesky records nothing on failure — the same quote could
            # be tweeted again on a later slot.
            if not self.post_to_bluesky(quote):
                logger.error("Bluesky post failed; skipping the tweet and this post.")
                return False

            # Also post to Twitter
            self.post_to_twitter(quote)

            logger.info(f"Posted quote: {quote}")
            return True

        except Exception as e:
            logger.error(f"Error posting quote: {e}")
            return False

    def run_scheduler(self):
        """Run the scheduler to post on the persona's configured interval."""
        logger.info(f"Starting {self.persona.DISPLAY_NAME} Bot scheduler...")

        # Schedule posts on the persona's configured interval
        interval = self.persona.POST_INTERVAL_MINUTES
        job = schedule.every(interval).minutes.do(self.post_quote)

        # The container restarts on its own (restart: unless-stopped) and gets
        # redeployed by hand, so an unconditional startup post turns a crash
        # loop into a posting spree.
        delay = next_post_delay(self.load_last_post_time(), interval, datetime.now())
        if delay is None:
            logger.info("No post on record within the interval; posting initial quote...")
            self.post_quote()
        else:
            job.next_run = datetime.now() + delay
            logger.info(f"Posted less than {interval} minutes ago; skipping the startup post. "
                        f"Next post at {job.next_run:%Y-%m-%d %H:%M:%S} "
                        f"(in {int(delay.total_seconds() // 60)} min).")

        # Run the scheduler
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
