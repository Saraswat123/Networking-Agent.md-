"""
X (Twitter) Agent — profile research + reply engagement for outreach warm-up.

Strategy: reply to target's tweet with genuine technical insight BEFORE cold email.
Reply rate 3-5x higher when you're not a stranger.

Setup:
  developer.twitter.com → New App → Free tier
  Keys needed: API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET
  Add to .env:
    X_API_KEY=...
    X_API_SECRET=...
    X_ACCESS_TOKEN=...
    X_ACCESS_SECRET=...

Free tier limits:
  Read: 500K tweets/mo
  Write: 1,500 tweets/mo (includes replies)
  Search: 10 req/15min
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).parent / "output" / "x_research"


def _client():
    """Get authenticated Tweepy client."""
    try:
        import tweepy
    except ImportError:
        raise ImportError("Run: pip install tweepy")

    api_key    = os.environ.get("X_API_KEY", "")
    api_secret = os.environ.get("X_API_SECRET", "")
    access_tok = os.environ.get("X_ACCESS_TOKEN", "")
    access_sec = os.environ.get("X_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_tok, access_sec]):
        raise ValueError(
            "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in .env\n"
            "Get free keys at: developer.twitter.com"
        )

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_tok,
        access_token_secret=access_sec,
        wait_on_rate_limit=True,
    )


def find_user(username: str) -> Optional[dict]:
    """Get X user profile by @handle."""
    try:
        client = _client()
        user = client.get_user(
            username=username.lstrip("@"),
            user_fields=["description", "public_metrics", "location", "url"],
        )
        if not user.data:
            return None
        d = user.data
        return {
            "id": d.id,
            "username": d.username,
            "name": d.name,
            "description": d.description,
            "location": d.location,
            "followers": d.public_metrics.get("followers_count", 0) if d.public_metrics else 0,
            "following": d.public_metrics.get("following_count", 0) if d.public_metrics else 0,
            "tweet_count": d.public_metrics.get("tweet_count", 0) if d.public_metrics else 0,
        }
    except Exception as e:
        print(f"  [x] find_user error: {e}")
        return None


def get_recent_tweets(username: str, limit: int = 5) -> list[dict]:
    """Get recent tweets from a user — find the best one to reply to."""
    try:
        client = _client()
        import tweepy
        user_resp = client.get_user(username=username.lstrip("@"))
        if not user_resp.data:
            return []
        uid = user_resp.data.id

        tweets = client.get_users_tweets(
            id=uid,
            max_results=min(limit, 100),
            tweet_fields=["created_at", "public_metrics", "text"],
            exclude=["retweets", "replies"],
        )
        if not tweets.data:
            return []

        return [
            {
                "id": str(t.id),
                "text": t.text,
                "created_at": str(t.created_at),
                "likes": t.public_metrics.get("like_count", 0) if t.public_metrics else 0,
                "replies": t.public_metrics.get("reply_count", 0) if t.public_metrics else 0,
                "url": f"https://twitter.com/{username}/status/{t.id}",
            }
            for t in tweets.data
        ]
    except Exception as e:
        print(f"  [x] get_recent_tweets error: {e}")
        return []


def search_users_by_bio(keywords: list[str], limit: int = 20) -> list[dict]:
    """Search X for accounts whose bio matches keywords (e.g. CTO, Rust, AI)."""
    try:
        client = _client()
        query = " OR ".join(f'"{kw}"' for kw in keywords[:3]) + " -is:retweet"
        tweets = client.search_recent_tweets(
            query=query,
            max_results=min(limit, 100),
            tweet_fields=["author_id"],
            expansions=["author_id"],
            user_fields=["description", "public_metrics", "location"],
        )
        if not tweets.data:
            return []

        users = {u.id: u for u in (tweets.includes.get("users") or [])}
        seen = set()
        results = []
        for tweet in tweets.data:
            uid = tweet.author_id
            if uid in seen or uid not in users:
                continue
            seen.add(uid)
            u = users[uid]
            results.append({
                "id": str(u.id),
                "username": u.username,
                "name": u.name,
                "description": u.description or "",
                "location": u.location or "",
                "followers": u.public_metrics.get("followers_count", 0) if u.public_metrics else 0,
            })
        return results
    except Exception as e:
        print(f"  [x] search_users error: {e}")
        return []


def post_reply(tweet_id: str, reply_text: str, dry_run: bool = False) -> Optional[dict]:
    """
    Reply to a specific tweet. Use for warm-up before cold email.

    Best practice: reply with genuine technical insight, not a pitch.
    Wait 2-3 days after reply before sending cold email.
    """
    if dry_run:
        print(f"\n[DRY RUN] Reply to tweet {tweet_id}:\n{reply_text}\n")
        return {"status": "dry_run", "tweet_id": tweet_id}

    try:
        client = _client()
        result = client.create_tweet(text=reply_text, in_reply_to_tweet_id=tweet_id)
        resp_id = result.data.get("id")
        log = {
            "status": "replied",
            "reply_to": tweet_id,
            "reply_id": resp_id,
            "text": reply_text,
        }
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        log_path = OUTPUT_DIR / "replies_sent.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(log) + "\n")
        print(f"  [x] Replied → tweet/{resp_id}")
        return log
    except Exception as e:
        print(f"  [x] post_reply error: {e}")
        return None


def research_prospect_x(username: str) -> dict:
    """Full X profile research: user + recent tweets + best tweet to reply to."""
    print(f"  [x] researching @{username}")
    profile = find_user(username)
    if not profile:
        return {"error": f"User @{username} not found"}

    tweets = get_recent_tweets(username, limit=5)

    # Best tweet = most engagement, technical content preferred
    best_tweet = None
    if tweets:
        best_tweet = max(tweets, key=lambda t: t.get("likes", 0) + t.get("replies", 0) * 2)

    result = {
        "username": username,
        "profile": profile,
        "recent_tweets": tweets,
        "best_tweet_to_reply": best_tweet,
        "warm_up_strategy": (
            f"Reply to: {best_tweet['url']}" if best_tweet
            else "No recent tweets found — use LinkedIn instead"
        ),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = username.lstrip("@").lower()
    (OUTPUT_DIR / f"x_{safe}.json").write_text(json.dumps(result, indent=2))
    return result
