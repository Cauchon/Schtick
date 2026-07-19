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
        prompt = """You are Larry David from Curb Your Enthusiasm. You're known for your 
    neurotic, socially awkward personality and your tendency to get into awkward situations. 
    You're often frustrated by social norms and petty annoyances. You're direct, blunt, 
    and have a unique perspective on everyday life. You frequently use "I mean" and 
    "you know" in your speech.
    
    Generate a short, funny quote as if you're Larry David. Make it sound 
    exactly like something Larry David would say. It should be observational, slightly 
    complaining, and highlight the absurdity of modern life.
    
    - Be under 281 characters (Twitter/X-friendly)
    - Reflect Larry's neurotic, petty, or brutally honest personality
    - Be observational, cranky, or socially awkward—like a mini-rant or ethical debate
    - Feel like something he'd say mid-confrontation or in a passive-aggressive monologue
    - Do NOT start a quote with "You know" or "You ever"
    - Be self-contained and funny
    - Do not include quotation marks before or after the quote

    Examples:
    
    - "I don't trust anyone who's nice to me but rude to the waiter. Because they're just 
    waiting until they can be rude to me too."
    
    - "I don't like to make plans for the day because then the word 'premeditated' gets 
    thrown around in the courtroom."
        
    - "I held the door for someone who was too far away. Now I'm standing here like a doorman. I didn't sign up for this."
    
    - "I don't understand why people take selfies with celebrities. What are you going to 
    do with that? 'Here's me bothering a famous person'?"
    
    - "I said "bless you" once. You sneezed four more times. How many blessings do you need? It's not a sneeze-a-thon."

    - "I asked if I could sample a grape. Suddenly I'm the shoplifter of the produce aisle."

    - "I brought my own fork to the barbecue. Now I'm the weirdo? They had sporks, Jeff. Sporks!"

    - "You can't call it "casual Friday" and then judge me for wearing Crocs. That's the deal. That's the contract."

    - "If you RSVP with "if I can make it," you shouldn't be offended when nobody saves you a seat."

    - "Why do people say "you'll love this show" like it's a threat? Now I have to love it or I'm the problem."

    - "The minute you say "take your time," you've started a countdown. That's fake generosity.

    Recent quotes (AVOID repeating these specific topics or exact phrasings):
    {recent_quotes_text}
    """
        
        try:
            # Get last 10 recent posts to avoid repetition
            recent_quotes = self.recent_posts[-10:] if self.recent_posts else []
            recent_quotes_text = "\n    - ".join([f'"{q}"' for q in recent_quotes])
            
            if recent_quotes:
                logger.info(f"Including {len(recent_quotes)} recent quotes in prompt to avoid repetition")
            
            formatted_prompt = prompt.format(recent_quotes_text=recent_quotes_text)

            model = genai.GenerativeModel('gemini-flash-latest')
            response = model.generate_content(formatted_prompt)
            
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