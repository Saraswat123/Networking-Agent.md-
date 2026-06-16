"""
X (Twitter) Agent — Free tier (write-only).

Free tier = POST tweets only. Cannot search or read others' timelines.

Workflow:
  1. Find prospect tweet manually (browse X) or use Grok to find URL
  2. Pass tweet URL to post_reply() → agent replies
  3. Wait 2-3 days → send email

Use Grok prompt:
  "Find recent tweets by [name/company] CEO/CTO about AI, technology, or business challenges.
   Give me the tweet URL to reply to."

Setup:
  developer.twitter.com → your app → Keys and tokens
  Add to .env:
    X_API_KEY=...       (Consumer Key)
    X_API_SECRET=...    (Consumer Key Secret)
    X_ACCESS_TOKEN=...  (Access Token)
    X_ACCESS_SECRET=... (Access Token Secret)

Free tier limits:
  Write: 1,500 tweets/mo (includes replies)
  Read: none (use Grok/browse manually)
"""

import json
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).parent / "output" / "x_replies"
REPLIES_LOG = OUTPUT_DIR / "replies_sent.jsonl"

MAX_REPLIES_PER_DAY = 15  # stay well under 1500/mo limit


def _client():
    """Get authenticated Tweepy client."""
    try:
        import tweepy
    except ImportError:
        raise ImportError("Run: pip3 install tweepy")

    api_key    = os.environ.get("X_API_KEY", "")
    api_secret = os.environ.get("X_API_SECRET", "")
    access_tok = os.environ.get("X_ACCESS_TOKEN", "")
    access_sec = os.environ.get("X_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_tok, access_sec]):
        raise ValueError(
            "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in .env\n"
            "Get keys at: developer.twitter.com → your app → Keys and tokens"
        )

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_tok,
        access_token_secret=access_sec,
        wait_on_rate_limit=True,
    )


def _extract_tweet_id(tweet_url_or_id: str) -> str:
    """Extract numeric tweet ID from URL or return as-is if already ID."""
    # Handle URLs like https://twitter.com/user/status/1234567890
    # or https://x.com/user/status/1234567890
    match = re.search(r"/status/(\d+)", tweet_url_or_id)
    if match:
        return match.group(1)
    # Already a numeric ID
    if tweet_url_or_id.strip().isdigit():
        return tweet_url_or_id.strip()
    raise ValueError(
        f"Cannot parse tweet ID from: {tweet_url_or_id}\n"
        "Provide full URL: https://x.com/username/status/1234567890"
    )


def _check_daily_limit() -> bool:
    """Enforce daily reply cap."""
    if not REPLIES_LOG.exists():
        return True
    today = date.today().isoformat()
    count = 0
    with open(REPLIES_LOG) as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("date") == today:
                    count += 1
            except Exception:
                pass
    if count >= MAX_REPLIES_PER_DAY:
        print(f"  [x] Daily limit {MAX_REPLIES_PER_DAY} reached. Try tomorrow.")
        return False
    return True


def _log_reply(tweet_id: str, reply_id: str, text: str, prospect: str = ""):
    """Log reply to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "tweet_id": tweet_id,
        "reply_id": reply_id,
        "text": text[:280],
        "prospect": prospect,
        "date": date.today().isoformat(),
        "ts": datetime.now().isoformat(),
    }
    with open(REPLIES_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def post_reply(
    tweet_url_or_id: str,
    reply_text: str,
    prospect: str = "",
    dry_run: bool = False,
) -> dict:
    """
    Reply to tweet. Works on Free tier.

    Args:
        tweet_url_or_id: Full URL or numeric tweet ID
        reply_text: Max 280 chars. Lead with insight, not a pitch.
        prospect: Company/person name for logging (optional)
        dry_run: Print without posting

    Returns:
        {"status": "replied"|"dry_run"|"limit_reached", "reply_id": ..., "url": ...}

    Example:
        post_reply(
            "https://x.com/cto_name/status/1234567890",
            "The latency gains from async batching are real — we saw similar numbers moving from polling to event-driven ingestion. What throughput are you hitting at peak?",
            prospect="Acme Corp CTO"
        )
    """
    tweet_id = _extract_tweet_id(tweet_url_or_id)

    if dry_run:
        print(f"\n[DRY RUN] Reply to tweet/{tweet_id}")
        print(f"Prospect: {prospect or 'unspecified'}")
        print(f"Text ({len(reply_text)} chars): {reply_text}\n")
        return {"status": "dry_run", "tweet_id": tweet_id}

    if not _check_daily_limit():
        return {"status": "limit_reached"}

    if len(reply_text) > 280:
        reply_text = reply_text[:277] + "..."

    client = _client()
    result = client.create_tweet(text=reply_text, in_reply_to_tweet_id=tweet_id)
    reply_id = str(result.data.get("id", ""))

    _log_reply(tweet_id, reply_id, reply_text, prospect)

    reply_url = f"https://x.com/i/web/status/{reply_id}"
    print(f"  [x] Replied → {reply_url}")
    print(f"  [x] Next step: wait 2-3 days, then send email to {prospect or 'prospect'}")

    return {
        "status": "replied",
        "tweet_id": tweet_id,
        "reply_id": reply_id,
        "reply_url": reply_url,
        "prospect": prospect,
    }


def post_tweet(text: str, dry_run: bool = False) -> dict:
    """Post original tweet (thought leadership, not outreach)."""
    if dry_run:
        print(f"\n[DRY RUN] Tweet ({len(text)} chars): {text}\n")
        return {"status": "dry_run"}

    if len(text) > 280:
        text = text[:277] + "..."

    client = _client()
    result = client.create_tweet(text=text)
    tweet_id = str(result.data.get("id", ""))
    url = f"https://x.com/i/web/status/{tweet_id}"
    print(f"  [x] Posted → {url}")
    return {"status": "posted", "tweet_id": tweet_id, "url": url}


def get_reply_stats() -> dict:
    """How many replies sent today and remaining."""
    today = date.today().isoformat()
    count = 0
    if REPLIES_LOG.exists():
        with open(REPLIES_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("date") == today:
                        count += 1
                except Exception:
                    pass
    return {
        "today": today,
        "replies_sent": count,
        "replies_remaining": max(0, MAX_REPLIES_PER_DAY - count),
        "monthly_budget": 1500,
    }


# ── Grok prompt helpers ──────────────────────────────────────────────────────

def grok_research_prompt(company: str, role: str = "CEO/CTO/Founder") -> str:
    """
    Generate a Grok prompt to find tweet URL for a prospect.
    Paste output into Grok at x.com/grok.

    Usage:
        prompt = grok_research_prompt("Acme Capital", "Managing Partner")
        print(prompt)  # paste into Grok
    """
    return f"""Find a recent tweet (last 30 days) by the {role} of {company} about any of:
- AI, machine learning, or automation
- Technology challenges or product decisions
- Business growth, hiring, or strategy
- Industry trends

Give me:
1. Their Twitter/X username
2. The full tweet URL (https://x.com/username/status/ID)
3. The tweet text (so I can write a relevant reply)

Search X/Twitter for: {company} {role} site:twitter.com OR site:x.com"""
