#!/usr/bin/env python3
"""
Test script for Larry David Bot - generates quotes without posting to Bluesky
"""

import os
import sys
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

def test_quote_generation():
    """Test the quote generation functionality."""
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    
    if not gemini_api_key:
        print("❌ GEMINI_API_KEY not found in environment variables")
        return False
    
    genai.configure(api_key=gemini_api_key)
    
    prompt = """You are Larry David from Curb Your Enthusiasm. You're known for your 
    neurotic, socially awkward personality and your tendency to get into awkward situations. 
    You're often frustrated by social norms and petty annoyances. You're direct, blunt, 
    and have a unique perspective on everyday life.
    
    Generate a short, funny quote as if you're Larry David. Make it sound 
    exactly like something Larry David would say. It should be observational, slightly 
    complaining, and highlight the absurdity of modern life.
    
    - Be under 281 characters (Twitter/X-friendly)
    - Reflect Larry's neurotic, petty, or brutally honest personality
    - Be observational, cranky, or socially awkward—like a mini-rant or ethical debate
    - Feel like something he'd say mid-confrontation or in a passive-aggressive monologue
    - Do NOT start a quote with "You know" or "You ever"
    - Do NOT end the quote with "you know.." or similar repetitive phrases
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
        print("🤖 Testing Gemini API connection...")
        model = genai.GenerativeModel('gemini-flash-latest')
        formatted_prompt = prompt.format(recent_quotes_text="")
        response = model.generate_content(formatted_prompt)
        
        quote = response.text.strip()
        
        # Clean up the quote
        if quote.startswith('"') and quote.endswith('"'):
            quote = quote[1:-1]
        
        print("✅ Gemini API connection successful!")
        print(f"📝 Generated quote: {quote}")
        print(f"📏 Character count: {len(quote)}")
        
        if len(quote) > 281:
            print("⚠️  Warning: Quote exceeds 281 character limit (Twitter limit)")
        else:
            print("✅ Quote within 281 character limit (Twitter compatible)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing Gemini API: {e}")
        return False

def test_fallback_quotes():
    """Test the fallback quote system."""
    print("\n🔄 Testing fallback quotes...")
    
    fallback_quotes = [
        "I tried to make my own oat milk… I milked the oats, Jerry! But they just got soggy!",
        "You ever been in a Zoom breakout room, Jerry? It's like being trapped in an elevator… with no buttons!",
        "I sold my neighbor an NFT of his own front door. It's art, Jerry!",
        "I was tracking my steps with a smart ring… now it thinks I'm a hummingbird!",
        "You know what the problem is with AI girlfriends? No garlic breath! It's unnatural!"
    ]
    
    for i, quote in enumerate(fallback_quotes, 1):
        print(f"📝 Fallback quote {i}: {quote}")
        print(f"📏 Character count: {len(quote)}")
        if len(quote) > 300:
            print("⚠️  Warning: Quote exceeds 300 character limit")
        print()
    
    return True

def test_environment_variables():
    """Test that all required environment variables are set."""
    print("🔧 Testing environment variables...")
    
    required_vars = [
        'BLUESKY_HANDLE',
        'BLUESKY_APP_PASSWORD', 
        'GEMINI_API_KEY'
    ]
    
    # Optional Twitter API variables
    twitter_vars = [
        'TWITTER_BEARER_TOKEN',
        'TWITTER_API_KEY',
        'TWITTER_API_SECRET',
        'TWITTER_ACCESS_TOKEN',
        'TWITTER_ACCESS_SECRET'
    ]
    
    # Check if any Twitter credentials are set
    twitter_configured = any(os.getenv(var) for var in twitter_vars)
    
    all_set = True
    # Test required variables
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: Set")
        else:
            print(f"❌ {var}: Not set")
            all_set = False
    
    # Test Twitter variables
    print("\n🔍 Twitter API Configuration:")
    twitter_status = ""
    if twitter_configured:
        missing = [var for var in twitter_vars if not os.getenv(var)]
        if missing:
            print(f"⚠️  Twitter API partially configured. Missing: {', '.join(missing)}")
            twitter_status = "Partially Configured"
            
            # Check if at least Bearer Token is set (required for v2)
            if not os.getenv('TWITTER_BEARER_TOKEN'):
                print("❌ TWITTER_BEARER_TOKEN is required for Twitter API v2")
        else:
            print("✅ Twitter API v2 fully configured")
            twitter_status = "Fully Configured"
    else:
        print("ℹ️  Twitter API not configured (optional)")
        twitter_status = "Not Configured"
    
    return all_set, twitter_status

def main():
    """Run all tests."""
    print("🧪 Larry David Bot Test Suite")
    print("=" * 50)
    
    # Test environment variables
    env_ok, twitter_status = test_environment_variables()
    print()
    
    # Test Gemini API
    gemini_ok = test_quote_generation()
    print()
    
    # Test fallback quotes
    fallback_ok = test_fallback_quotes()
    
    # Summary
    print("=" * 50)
    print("📊 Test Summary:")
    print(f"Environment variables: {'✅' if env_ok else '❌'}")
    print(f"Gemini API: {'✅' if gemini_ok else '❌'}")
    print(f"Fallback quotes: {'✅' if fallback_ok else '❌'}")
    print(f"Twitter API: {twitter_status}")
    
    if all([env_ok, gemini_ok, fallback_ok]):
        print("\n🎉 All tests passed! The bot should work correctly.")
    else:
        print("\n⚠️  Some tests failed. Please check the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 