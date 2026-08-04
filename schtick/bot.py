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
from datetime import datetime, timedelta
from typing import List, Optional
import random

import tweepy
from atproto import Client
try:
    from atproto import RichText
except ImportError:  # Older atproto version without RichText helper
    RichText = None

from schtick import generation

logger = logging.getLogger(__name__)


def configure_logging(slug: str):
    """Configure logging to a persona-specific log file and the console.

    Done in a function (not at import time) because the log filename depends on
    the persona slug.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'{slug}.log'),
            logging.StreamHandler()
        ]
    )


class PersonaBot:
    def __init__(self, persona):
        """Initialize the Persona Bot with Bluesky client and configuration."""
        self.persona = persona

        # Configure logging first so the persona's log file is used from here on.
        configure_logging(persona.SLUG)

        self.client = Client()
        self.posts_cache_file = f'recent_posts_{persona.SLUG}.json'
        self.legacy_cache_file = 'recent_posts.json'
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

    def generate_quote(self) -> str:
        """Generate a new persona quote using the character's AI provider."""
        try:
            # Get last 10 recent posts to avoid repetition
            recent_quotes = self.recent_posts[-10:] if self.recent_posts else []

            if recent_quotes:
                logger.info(f"Including {len(recent_quotes)} recent quotes in prompt to avoid repetition")

            return generation.generate_quote(self.persona, recent_quotes)

        except Exception as e:
            logger.error(f"Error generating quote: {e}")
            return self.get_fallback_quote()

    def get_fallback_quote(self) -> str:
        """Return a fallback persona quote if AI generation fails."""
        return random.choice(self.persona.FALLBACK_QUOTES)

    def is_duplicate(self, quote: str) -> bool:
        """Check if a quote is a duplicate of recent posts."""
        return quote in self.recent_posts

    def post_to_twitter(self, quote: str) -> bool:
        """Post the quote to Twitter (X) using API v2. Returns True on success."""
        if not self.twitter_client:
            logger.info("Twitter client not configured; skipping tweet.")
            return False

        # Twitter has 280-character limit
        tweet_text = quote[:280]

        try:
            response = self.twitter_client.create_tweet(text=tweet_text)
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
        logger.info(f"Posted to Bluesky: {text}")
        return True

    def post_quote(self):
        """Generate and post a new persona quote to Bluesky."""
        try:
            # Generate a unique quote
            max_attempts = 10
            for attempt in range(max_attempts):
                quote = self.generate_quote()

                if not self.is_duplicate(quote):
                    break
                logger.info(f"Generated duplicate quote, trying again (attempt {attempt + 1})")
            else:
                logger.warning("Could not generate unique quote after max attempts, using fallback")
                quote = self.get_fallback_quote()

            # Post to Bluesky
            self.post_to_bluesky(quote)

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
        schedule.every(self.persona.POST_INTERVAL_MINUTES).minutes.do(self.post_quote)

        # Post immediately on startup
        logger.info("Posting initial quote...")
        self.post_quote()

        # Run the scheduler
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
