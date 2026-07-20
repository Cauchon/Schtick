#!/usr/bin/env python3
"""
Test script for Schtick - generates quotes without posting to Bluesky.

Usage:
    python test_bot.py                 # check every available character
    python test_bot.py larry_david     # check only the named persona
"""

import os
import sys
from dotenv import load_dotenv
import google.generativeai as genai

from schtick import generation
from schtick.persona import available_personas, load_persona

# Load environment variables
load_dotenv()

def test_quote_generation(persona):
    """Test the quote generation functionality for a persona."""
    gemini_api_key = os.getenv('GEMINI_API_KEY')

    if not gemini_api_key:
        print("❌ GEMINI_API_KEY not found in environment variables")
        return False

    genai.configure(api_key=gemini_api_key)

    try:
        print("🤖 Testing Gemini API connection...")
        # Generate via the shared engine (single source of truth), no history.
        quote = generation.generate_quote(persona, [])

        print("✅ Gemini API connection successful!")
        print(f"📝 Generated quote: {quote}")
        print(f"📏 Character count: {len(quote)}")

        if len(quote) > persona.CHAR_TARGET:
            print(f"⚠️  Warning: Quote exceeds {persona.CHAR_TARGET} character target")
        else:
            print(f"✅ Quote within {persona.CHAR_TARGET} character target (Twitter/Bluesky compatible)")

        return True

    except Exception as e:
        print(f"❌ Error testing Gemini API: {e}")
        return False

def test_fallback_quotes(persona):
    """Test the fallback quote system for a persona."""
    print("\n🔄 Testing fallback quotes...")

    for i, quote in enumerate(persona.FALLBACK_QUOTES, 1):
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

def test_persona(slug):
    """Run quote + fallback checks for a single persona. Returns (gemini_ok, fallback_ok)."""
    print("=" * 50)
    print(f"🎭 Persona: {slug}")
    print("=" * 50)

    try:
        persona = load_persona(slug)
    except ValueError as e:
        print(f"❌ {e}")
        return False, False

    print(f"📛 {persona.DISPLAY_NAME} (slug: {persona.SLUG})")
    print()

    # Test Gemini API
    gemini_ok = test_quote_generation(persona)

    # Test fallback quotes
    fallback_ok = test_fallback_quotes(persona)

    return gemini_ok, fallback_ok

def main():
    """Run all tests."""
    print("🧪 Schtick Test Suite")
    print("=" * 50)

    # Determine which personas to check
    if len(sys.argv) > 1:
        slugs = [sys.argv[1]]
    else:
        slugs = list(available_personas())

    # Environment variable checks run once (shared across personas)
    env_ok, twitter_status = test_environment_variables()
    print()

    # Per-persona checks
    persona_results = {}
    for slug in slugs:
        gemini_ok, fallback_ok = test_persona(slug)
        persona_results[slug] = (gemini_ok, fallback_ok)
        print()

    # Summary
    print("=" * 50)
    print("📊 Test Summary:")
    print(f"Environment variables: {'✅' if env_ok else '❌'}")
    print(f"Twitter API: {twitter_status}")
    print("\nPer-persona results:")
    all_personas_ok = True
    for slug, (gemini_ok, fallback_ok) in persona_results.items():
        print(f"  {slug}:")
        print(f"    Gemini API: {'✅' if gemini_ok else '❌'}")
        print(f"    Fallback quotes: {'✅' if fallback_ok else '❌'}")
        if not (gemini_ok and fallback_ok):
            all_personas_ok = False

    if env_ok and all_personas_ok:
        print("\n🎉 All tests passed! The bot should work correctly.")
    else:
        print("\n⚠️  Some tests failed. Please check the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
