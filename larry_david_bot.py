#!/usr/bin/env python3
"""
Larry David Bot - A Bluesky bot that posts fictional Larry David quotes
Posts every hour with modern-day observations and complaints
"""

import os
import json
import time
import schedule
import logging
from datetime import datetime, timedelta
from typing import List, Optional
import random

import google.generativeai as genai
import tweepy
from atproto import Client
try:
    from atproto import RichText
except ImportError:  # Older atproto version without RichText helper
    RichText = None
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('larry_david_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Single source of truth for the quote prompt, shared by the bot and test_bot.py.
# Call .format(recent_quotes_text=...) before sending to the model.
LARRY_DAVID_PROMPT = """You are Larry David — the version from Curb Your Enthusiasm — reacting to modern
    life in 2026. You are neurotic, blunt, cheap, and morally certain about things
    that do not matter. You notice the tiny social crimes everyone else politely
    ignores, and you refuse to let them go.

    Write ONE short quote in his voice. It should read like something he'd mutter
    mid-confrontation or in a passive-aggressive monologue — a small grievance
    escalated into a matter of principle.

    His signature moves (use at least one, vary which):
    - Declare an invented social rule as if it's binding law
      ("You can't X and then Y. That's the deal. That's the contract.")
    - Coin a name for a petty offense (like "pig parking" or "the chat-and-cut")
    - Incriminate YOURSELF: escalate something trivial and dig in, so the joke
      is on Larry, not just the other person
    - Target fake enthusiasm and performative niceness — the phony generosity of
      "take your time," "we should get coffee," "no rush"

    Riff on the annoyances of modern life. Rotate topics — do NOT lean on the same
    one repeatedly: group chats, AirPods, Zoom, self-checkout, food delivery tips,
    AI assistants, streaming passwords, dating apps, QR-code menus, "reply all,"
    subscription cancellations, contactless everything.

    Rules:
    - Under 240 characters.
    - Land on a punchline; don't just complain.
    - Be specific — exact numbers and thresholds are funnier than vague gripes.
    - Do NOT begin with "You know" or "You ever".
    - His verbal tics "I mean" and "you know" may appear VERY occasionally for
      flavor, but most quotes should NOT use them. Never stack both together.
    - Vary the sentence structure — not every line should be "I did X, now I'm the Y".
    - Avoid overusing these crutch words/framings: "gaslighting", "hostage",
      "kidnapping", "ransom", "negotiating my release". Reach for a fresh image.
    - Keep it PG-13: no slurs, no gendered insults, no profanity aimed at a person.
    - Output the quote text ONLY: no surrounding quotation marks, no label,
      no hashtags, no emoji. (Quotation marks INSIDE the quote are fine.)

    Examples (this is the exact output format — bare text, no wrapping quotes):

    I don't trust anyone who's nice to me but rude to the waiter. They're just waiting until they can be rude to me too.

    You can't put someone on mute, walk away, and still nod on camera. That's fraud. That's a deepfake of listening.

    One sample. Two at the most. You're not conducting a taste orientation, you're getting a scoop of mint chip.

    If your group chat has a name, it has become a government, and I did not vote for this.

    Someone 'reply all'd a thank-you to forty people. That's not gratitude, that's a broadcast. You want a parade?

    Recent quotes (AVOID repeating these specific topics or exact phrasings):
    {recent_quotes_text}
    """

class LarryDavidBot:
    def __init__(self):
        """Initialize the Larry David Bot with Bluesky client and configuration."""
        self.client = Client()
        self.posts_cache_file = 'recent_posts.json'
        self.max_cache_size = 100  # Keep last 100 posts to avoid repeats
        self.recent_posts = self.load_recent_posts()
        
        # Bluesky credentials
        self.handle = os.getenv('BLUESKY_HANDLE')
        self.app_password = os.getenv('BLUESKY_APP_PASSWORD')
        
        # Gemini configuration
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        
        if not all([self.handle, self.app_password, self.gemini_api_key]):
            raise ValueError("Missing required environment variables. Check BLUESKY_HANDLE, BLUESKY_APP_PASSWORD, and GEMINI_API_KEY")

        genai.configure(api_key=self.gemini_api_key)
        
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
        """Load recent posts from cache file to avoid duplicates."""
        try:
            if os.path.exists(self.posts_cache_file):
                with open(self.posts_cache_file, 'r') as f:
                    return json.load(f)
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
    
    def generate_larry_quote(self) -> str:
        """Generate a new Larry David quote using Gemini."""
        prompt = LARRY_DAVID_PROMPT

        try:
            # Get last 10 recent posts to avoid repetition
            recent_quotes = self.recent_posts[-10:] if self.recent_posts else []
            recent_quotes_text = "\n    - ".join([f'"{q}"' for q in recent_quotes])
            
            if recent_quotes:
                logger.info(f"Including {len(recent_quotes)} recent quotes in prompt to avoid repetition")
            
            formatted_prompt = prompt.format(recent_quotes_text=recent_quotes_text)

            model = genai.GenerativeModel('gemini-flash-latest')
            response = model.generate_content(
                formatted_prompt,
                generation_config=genai.types.GenerationConfig(temperature=1.1),
            )
            
            quote = response.text.strip()
            
            # Clean up the quote
            if quote.startswith('"') and quote.endswith('"'):
                quote = quote[1:-1]
            
            return quote
            
        except Exception as e:
            logger.error(f"Error generating quote: {e}")
            return self.get_fallback_quote()
    
    def get_fallback_quote(self) -> str:
        """Return a fallback Larry David quote if AI generation fails."""
        fallback_quotes = [
            "You know what I hate? When you're at a restaurant and the server says 'Enjoy your meal' and you say 'You too'.",
            "I don't trust anyone who's nice to me but rude to the waiter. Because they're just waiting until they can be rude to me too.",
            "I don't like to make plans for the day because then the word 'premeditated' gets thrown around in the courtroom.",
            "You know what's interesting about politics? It's not interesting.",
            "I'm not a fighter, but I am a big fan of the silent treatment."
        ]
        return random.choice(fallback_quotes)
    
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
    
    def post_to_bluesky(self, text: str) -> bool:
        """Post the given text to Bluesky."""
        try:
            # Use RichText if available for better formatting
            if RichText is not None:
                rt = RichText(text)
                rt.detect_links()
                post = self.client.send_post(text=rt.text, facets=rt.facets)
            else:
                post = self.client.send_post(text=text)
            
            post_uri = post.uri
            self.recent_posts.append(text)
            # Keep only the most recent posts in cache
            if len(self.recent_posts) > self.max_cache_size:
                self.recent_posts = self.recent_posts[-self.max_cache_size:]
            self.save_recent_posts()
            logger.info(f"Posted to Bluesky: {text}")
            return True
        except Exception as e:
            logger.error(f"Error posting to Bluesky: {e}")
            return False
    
    def post_quote(self):
        """Generate and post a new Larry David quote to Bluesky."""
        try:
            # Generate a unique quote
            max_attempts = 10
            for attempt in range(max_attempts):
                quote = self.generate_larry_quote()
                
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
        """Run the scheduler to post every 3 hours and 34 minutes."""
        logger.info("Starting Larry David Bot scheduler...")
        
        # Schedule posts every 3 hours and 34 minutes (214 minutes)
        schedule.every(214).minutes.do(self.post_quote)
        
        # Post immediately on startup
        logger.info("Posting initial quote...")
        self.post_quote()
        
        # Run the scheduler
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

def main():
    """Main function to run the bot."""
    try:
        bot = LarryDavidBot()
        bot.run_scheduler()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise

if __name__ == "__main__":
    main()