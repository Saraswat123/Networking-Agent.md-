"""
X (Twitter) Agent — Free tier, OAuth 2.0 PKCE (required for apps post-March 2023).

OAuth 1.0a is blocked on new X apps. This uses OAuth 2.0 User Context (PKCE).

First run: browser opens → authorize → paste redirect URL → x_token.json saved.
After that: automatic token refresh, no browser needed.

Setup:
  developer.twitter.com → your app → User authentication settings
  Add to .env:
    X_OAUTH2_CLIENT_ID=...      (OAuth 2.0 Client ID)
    X_OAUTH2_CLIENT_SECRET=...  (Client Secret)

Free tier limits:
  Write: 500 tweets/mo (includes replies)
  Read: none (use Grok or browse manually)

Workflow:
  1. x-research --company "Acme" → prints Grok prompt
  2. Paste into x.com/grok → get tweet URL
  3. x-reply --tweet-url "https://x.com/user/status/ID" --message "..."
  4. Wait 2-3 days → email
"""

import json
import os
import re
import webbrowser
from datetime import datetime, date
from pathlib import Path
from typing import Optional

TOKEN_PATH = Path(__file__).parent.parent / "x_token.json"
OUTPUT_DIR = Path(__file__).parent / "output" / "x_replies"
REPLIES_LOG = OUTPUT_DIR / "replies_sent.jsonl"

REDIRECT_URI = "http://127.0.0.1:8080"
SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access"]

MAX_REPLIES_PER_DAY = 15


def _get_client():
    """
    Get authenticated Tweepy Client via OAuth 2.0 PKCE.
    First run opens browser for authorization.
    Subsequent runs auto-refresh token from x_token.json.
    """
    try:
        import tweepy
    except ImportError:
        raise ImportError("Run: pip3 install tweepy")

    client_id = os.environ.get("X_OAUTH2_CLIENT_ID", "")
    client_secret = os.environ.get("X_OAUTH2_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise ValueError(
            "Set X_OAUTH2_CLIENT_ID and X_OAUTH2_CLIENT_SECRET in .env\n"
            "Find them at: developer.twitter.com → your app → User authentication settings"
        )

    handler = tweepy.OAuth2UserHandler(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        client_secret=client_secret,
    )

    token_data = None
    if TOKEN_PATH.exists():
        try:
            token_data = json.loads(TOKEN_PATH.read_text())
        except Exception:
            token_data = None

    if token_data and token_data.get("refresh_token"):
        try:
            new_token = handler.refresh_token(
                "https://api.twitter.com/2/oauth2/token",
                refresh_token=token_data["refresh_token"],
            )
            TOKEN_PATH.write_text(json.dumps(new_token, indent=2))
            return tweepy.Client(access_token=new_token["access_token"])
        except Exception:
            # Refresh failed — re-auth
            token_data = None

    # Full PKCE browser flow — auto-capture redirect via local server
    auth_url = handler.get_authorization_url()
    print("\n[x] Opening browser for X authorization...")
    webbrowser.open(auth_url)
    print("Browser opened. Authorize the app on X...")

    # Start local server to catch redirect automatically
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    captured = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            captured["url"] = f"http://127.0.0.1:8080{self.path}"
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>X Authorization complete. You can close this tab.</h2>")

        def log_message(self, *args):
            pass  # silence server logs

    server = HTTPServer(("127.0.0.1", 8080), _Handler)
    print("[x] Waiting for browser callback on http://127.0.0.1:8080 ...")
    server.handle_request()  # blocks until one request received
    server.server_close()

    redirect_response = captured.get("url", "")
    if not redirect_response or "code=" not in redirect_response:
        raise RuntimeError(
            f"[x] Auth failed or browser did not redirect correctly.\n"
            f"Got: {redirect_response}"
        )

    token = handler.fetch_token(redirect_response)
    TOKEN_PATH.write_text(json.dumps(token, indent=2))
    print(f"[x] Token saved → {TOKEN_PATH}")

    return tweepy.Client(access_token=token["access_token"])


def _extract_tweet_id(tweet_url_or_id: str) -> str:
    """Extract numeric tweet ID from URL or return as-is."""
    match = re.search(r"/status/(\d+)", tweet_url_or_id)
    if match:
        return match.group(1)
    if tweet_url_or_id.strip().isdigit():
        return tweet_url_or_id.strip()
    raise ValueError(
        f"Cannot parse tweet ID from: {tweet_url_or_id}\n"
        "Provide full URL: https://x.com/username/status/1234567890"
    )


def _check_daily_limit() -> bool:
    if not REPLIES_LOG.exists():
        return True
    today = date.today().isoformat()
    count = sum(
        1 for line in open(REPLIES_LOG)
        if json.loads(line).get("date") == today
    )
    if count >= MAX_REPLIES_PER_DAY:
        print(f"  [x] Daily limit {MAX_REPLIES_PER_DAY} reached.")
        return False
    return True


def _log_reply(tweet_id: str, reply_id: str, text: str, prospect: str = ""):
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
    Reply to tweet. Works on Free tier with OAuth 2.0.

    Args:
        tweet_url_or_id: Full URL or numeric tweet ID
        reply_text: Max 280 chars. Lead with insight, not pitch.
        prospect: Company/person name for logging
        dry_run: Print without posting

    Example:
        post_reply(
            "https://x.com/cto/status/1234567890",
            "The async batching approach trades latency for throughput — solid for batch workloads. What's your P99 at peak?",
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

    client = _get_client()
    result = client.create_tweet(text=reply_text, in_reply_to_tweet_id=tweet_id)
    reply_id = str(result.data.get("id", ""))

    _log_reply(tweet_id, reply_id, reply_text, prospect)

    reply_url = f"https://x.com/i/web/status/{reply_id}"
    print(f"  [x] Replied → {reply_url}")
    print(f"  [x] Next: wait 2-3 days → email {prospect or 'prospect'}")

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

    client = _get_client()
    result = client.create_tweet(text=text)
    tweet_id = str(result.data.get("id", ""))
    url = f"https://x.com/i/web/status/{tweet_id}"
    print(f"  [x] Posted → {url}")
    return {"status": "posted", "tweet_id": tweet_id, "url": url}


def get_reply_stats() -> dict:
    today = date.today().isoformat()
    count = 0
    if REPLIES_LOG.exists():
        with open(REPLIES_LOG) as f:
            for line in f:
                try:
                    if json.loads(line).get("date") == today:
                        count += 1
                except Exception:
                    pass
    return {
        "today": today,
        "replies_sent": count,
        "replies_remaining": max(0, MAX_REPLIES_PER_DAY - count),
        "monthly_budget": 500,
    }


def grok_research_prompt(company: str, role: str = "CEO/CTO/Founder") -> str:
    """
    Generate Grok prompt to find prospect tweet URL.
    Paste output into Grok at x.com/grok.

    Usage:
        print(grok_research_prompt("Acme Capital", "Managing Partner"))
        # paste into Grok
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


def authorize():
    """
    Run OAuth 2.0 PKCE authorization flow.
    Opens browser → user authorizes → paste redirect URL → token saved.

    Call this once to set up: python -c "from x_agent import authorize; authorize()"
    """
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print("[x] Cleared old token, starting fresh auth.")
    _get_client()
    print("[x] Authorization complete. x_token.json saved.")
