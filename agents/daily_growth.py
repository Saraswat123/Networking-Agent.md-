"""
Daily Growth Agent — runs every morning.

LinkedIn: source 20 protocol/Rust/ETH engineers → send connection requests with personalized notes
X: find relevant accounts → post 10-15 thoughtful replies to grow visibility

Sources:
  - GitHub search: "ethereum protocol rust" engineers
  - YC companies: recent batch founders
  - DDGS: find X handles of people to engage

Limits (hard):
  LinkedIn: 20 connections/day (ban risk above this)
  X replies: 15/day (free tier budget: 500/mo)

Run daily:
  python3 agents/daily_growth.py
  python3 agents/daily_growth.py --linkedin-only
  python3 agents/daily_growth.py --x-only
  python3 agents/daily_growth.py --dry-run
"""

import asyncio
import json
import os
import sys
import time
import random
import argparse
import subprocess
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import requests

OUTPUT_DIR = Path(__file__).parent / "output" / "daily_growth"
LOG_FILE = OUTPUT_DIR / "growth_log.jsonl"

LINKEDIN_DAILY_LIMIT = 20
X_DAILY_LIMIT = 15

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"

# LinkedIn search keywords — high-value decision makers first, then engineers
LINKEDIN_SEARCH_KEYWORDS = [
    # Founders / CEOs — highest priority
    "founder CEO AI startup",
    "founder CTO AI infrastructure",
    "CEO artificial intelligence company",
    "co-founder AI agent startup",
    "founder web3 startup",
    "founder ethereum startup",
    "CEO crypto blockchain startup",
    # CTOs — technical decision makers
    "CTO AI infrastructure startup",
    "CTO blockchain crypto startup",
    "CTO distributed systems",
    "CTO rust systems",
    "chief technology officer AI",
    # VCs / Investors / Fund Managers
    "venture capital AI fund",
    "VC partner crypto web3",
    "fund manager AI technology",
    "managing partner AI venture",
    "angel investor AI startup",
    "principal VC fund AI",
    "general partner blockchain fund",
    # AI infrastructure engineers (peer network)
    "AI infrastructure engineer",
    "LLM platform engineer",
    "protocol engineer ethereum",
    "distributed systems engineer",
]

# X topics to engage with — founder/VC/CTO tweets first, then technical
X_ENGAGE_TOPICS = [
    # High-value accounts post about these
    "AI startup founder raised funding",
    "AI infrastructure investment VC",
    "ethereum protocol upgrade founder",
    "AI agent startup launch",
    "web3 AI founder building",
    # Technical topics (gets seen by CTOs/engineers)
    "ethereum consensus FOCIL inclusion list",
    "Rust async tokio production",
    "AI agent infrastructure MCP",
    "distributed validator technology DVT",
    "ZK proof AI agent verification",
    "LLM production deployment latency",
]

# Sender profile (from profile.json)
SENDER_NAME = "Saraswat Das"
SENDER_TITLE = "Protocol Engineer (Rust / Ethereum)"
SENDER_GITHUB = "github.com/Saraswat123"


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(action: str, target: str, result: str, channel: str = ""):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": date.today().isoformat(),
        "ts": datetime.now().isoformat(),
        "channel": channel,
        "action": action,
        "target": target,
        "result": result,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  [{channel}] {action}: {target} → {result}")


def _today_count(channel: str, action: str) -> int:
    if not LOG_FILE.exists():
        return 0
    today = date.today().isoformat()
    count = 0
    with open(LOG_FILE) as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("date") == today and e.get("channel") == channel and e.get("action") == action:
                    count += 1
            except Exception:
                pass
    return count


# ── Claude CLI helper ─────────────────────────────────────────────────────────

def _claude(prompt: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=60, env=env,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


# ── GitHub sourcing ───────────────────────────────────────────────────────────

def _github_headers():
    h = {"User-Agent": "networking-agent/0.1", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def find_github_engineers(query: str, limit: int = 10) -> list[dict]:
    """Search GitHub for engineers matching query. Returns profile dicts with LinkedIn if available."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/search/users",
            headers=_github_headers(),
            params={"q": f"{query} type:user", "per_page": "20"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        logins = [u["login"] for u in resp.json().get("items", [])[:limit * 2]]
    except Exception as e:
        print(f"  [github] search error: {e}")
        return []

    profiles = []
    for login in logins[:limit]:
        try:
            p = requests.get(f"{GITHUB_API}/users/{login}", headers=_github_headers(), timeout=10).json()
            linkedin = ""
            bio = p.get("bio", "") or ""
            blog = p.get("blog", "") or ""
            # Extract LinkedIn from bio or blog
            for text in [bio, blog]:
                if "linkedin.com" in text.lower():
                    import re
                    m = re.search(r"linkedin\.com/in/([A-Za-z0-9_-]+)", text, re.I)
                    if m:
                        linkedin = f"https://linkedin.com/in/{m.group(1)}"
                        break
            profiles.append({
                "login": login,
                "name": p.get("name", login),
                "bio": bio[:200],
                "company": p.get("company", ""),
                "location": p.get("location", ""),
                "github_url": p.get("html_url", ""),
                "linkedin_url": linkedin,
                "followers": p.get("followers", 0),
            })
            time.sleep(0.3)
        except Exception:
            continue

    return profiles


# ── LinkedIn connection note generation ──────────────────────────────────────

def generate_linkedin_note(target: dict) -> str:
    """Generate 300-char personalized connection note."""
    prompt = f"""Write a LinkedIn connection request note. Max 280 characters. No emojis. No generic phrases.

Sender: {SENDER_NAME}, {SENDER_TITLE}. Built EIP-7805 FOCIL, DVT-FOCIL library, Rust MCP server, eBPF P2P observer for Ethereum.

Target:
Name: {target.get("name", "")}
Bio: {target.get("bio", "")}
Company: {target.get("company", "")}
Location: {target.get("location", "")}

Rules:
- Reference ONE specific thing from their bio/company
- Lead with what you're building (Ethereum consensus, Rust protocol)
- Ask to connect — no pitch, no ask for job
- Sound like a peer engineer, not a recruiter
- Under 280 chars

Output: just the note text, nothing else."""

    note = _claude(prompt)
    return note[:280] if note else f"Building Ethereum consensus tooling in Rust (FOCIL, DVT-FOCIL, eBPF P2P). Would love to connect with others working in the protocol space."


# ── X reply generation ────────────────────────────────────────────────────────

def find_x_reply_targets(topic: str, limit: int = 3) -> list[dict]:
    """Find tweet URLs via DuckDuckGo for a given topic."""
    try:
        from ddgs import DDGS
        results = list(DDGS().text(
            f"site:x.com OR site:twitter.com {topic} -filter:links",
            max_results=limit * 3,
        ))
        import re
        tweets = []
        seen = set()
        for r in results:
            url = r.get("href", "")
            m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)", url)
            if m and url not in seen:
                seen.add(url)
                tweets.append({
                    "url": url,
                    "username": m.group(1),
                    "tweet_id": m.group(2),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", "")[:200],
                })
            if len(tweets) >= limit:
                break
        return tweets
    except Exception as e:
        print(f"  [x] search error: {e}")
        return []


def generate_x_reply(tweet: dict) -> str:
    """Generate a value-adding 280-char reply."""
    prompt = f"""Write a reply to this tweet. Max 260 characters. No emojis. No @mentions unless necessary.

Tweet URL: {tweet.get("url", "")}
Tweet snippet: {tweet.get("snippet", "")}
Author: @{tweet.get("username", "")}

Sender context: Protocol engineer working on EIP-7805 FOCIL, DVT-FOCIL library (censorship resistance for Ethereum), Rust async systems, eBPF P2P networking, ZK-proof AI verification.

Rules:
- Add genuine technical insight or a specific follow-up question
- Sound like a peer, not a marketer
- No self-promotion, no links, no "check out my work"
- Short, punchy, technical
- Under 260 chars

Output: just the reply text, nothing else."""

    reply = _claude(prompt)
    return reply[:260] if reply else ""


# ── LinkedIn daily task ───────────────────────────────────────────────────────

async def run_linkedin_growth(dry_run: bool = False, limit: int = LINKEDIN_DAILY_LIMIT):
    sent_today = _today_count("linkedin", "connect")
    remaining = limit - sent_today
    if remaining <= 0:
        print(f"\n[linkedin] Daily limit reached ({limit}/day). Try tomorrow.")
        return

    print(f"\n[linkedin] Sourcing targets via LinkedIn search (want {remaining} connections)...")

    sys.path.insert(0, str(Path(__file__).parent))
    import linkedin_agent

    # Weight selection: 2 high-value (founder/CEO/VC), 1 engineer
    high_value = LINKEDIN_SEARCH_KEYWORDS[:14]   # founders, CTOs, VCs
    engineers  = LINKEDIN_SEARCH_KEYWORDS[14:]   # AI/protocol engineers
    keywords = random.sample(high_value, min(2, len(high_value))) + \
               random.sample(engineers, min(1, len(engineers)))

    all_urls = []
    for keyword in keywords:
        print(f"  Searching: '{keyword}'")
        if dry_run:
            # In dry run, generate fake URLs for preview
            all_urls += [f"https://linkedin.com/in/example-{keyword.replace(' ','-')}-{i}" for i in range(1, 4)]
        else:
            urls = await linkedin_agent.search_people(keyword, limit=10)
            all_urls += urls
            print(f"    Found {len(urls)} profiles")
            await asyncio.sleep(random.uniform(5, 10))

    # Deduplicate + shuffle
    seen = set()
    unique_urls = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    random.shuffle(unique_urls)

    print(f"  Total unique profiles: {len(unique_urls)}")

    sent = 0
    for profile_url in unique_urls:
        if sent >= remaining:
            break

        # Generate a generic professional note (no profile details available from search)
        note = _generate_generic_note()

        print(f"\n  → {profile_url}")
        print(f"    Note: {note[:80]}...")

        if dry_run:
            _log("connect", profile_url, "dry_run", "linkedin")
            sent += 1
            continue

        result = await linkedin_agent.send_connection_request(profile_url, note=note)
        status = result.get("status", "error")
        _log("connect", profile_url, status, "linkedin")

        if status == "sent":
            sent += 1
        elif status == "limit_reached":
            break

        delay = random.uniform(45, 120)
        print(f"    Waiting {delay:.0f}s...")
        await asyncio.sleep(delay)

    print(f"\n[linkedin] Done — {sent} connections sent today (total: {sent_today + sent}/{limit})")


def _generate_generic_note() -> str:
    """Pick a random professional connection note from a pool.
    Mix of founder/CEO/VC tone and peer engineer tone."""
    notes = [
        # For founders / CEOs
        "Building AI infrastructure in Rust — production MCP servers, Ethereum consensus layer, ZK-proof verification. Would love to connect and follow your work.",
        "Following your space closely. I build the protocol and agent infrastructure layer — Rust MCP server, EIP-7805 FOCIL, eBPF P2P. Keen to connect.",
        "Admire what you're building. I work at the infra layer — Rust async systems, Ethereum consensus, multi-agent AI pipelines. Would love to stay connected.",
        "Building protocol-level AI infrastructure — Rust MCP server, DVT-FOCIL for Ethereum, ZK-verifiable agent engine. Connecting with founders doing interesting work.",
        # For VCs / investors
        "I build Rust protocol infrastructure and AI agent systems. Always value connecting with people shaping where the space is going.",
        "Working on the infrastructure layer for AI agents — Rust MCP, Ethereum consensus tooling, ZK-proof verification. Would love to connect.",
        # For CTOs / technical leaders
        "Protocol engineer working on Ethereum consensus (FOCIL, DVT) and Rust AI infrastructure. Would be good to connect with others at this layer.",
        "Building production Rust systems — MCP server, eBPF P2P observer, multi-agent AI orchestration. Great to connect with technical leaders in this space.",
        # General peer
        "Rust systems engineer focused on Ethereum protocol and AI infrastructure. Always interested in connecting with people building at this level.",
    ]
    return random.choice(notes)


# ── X daily task ──────────────────────────────────────────────────────────────

async def run_x_growth(dry_run: bool = False, limit: int = X_DAILY_LIMIT):
    sent_today = _today_count("x", "reply")
    remaining = limit - sent_today
    if remaining <= 0:
        print(f"\n[x] Daily limit reached ({limit}/day). Try tomorrow.")
        return

    print(f"\n[x] Finding tweet targets (want {remaining} replies)...")

    sys.path.insert(0, str(Path(__file__).parent))
    import x_agent

    replied = 0
    for topic in X_ENGAGE_TOPICS:
        if replied >= remaining:
            break

        print(f"\n  Topic: {topic}")
        tweets = find_x_reply_targets(topic, limit=2)

        for tweet in tweets:
            if replied >= remaining:
                break

            reply_text = generate_x_reply(tweet)
            if not reply_text:
                continue

            print(f"  → @{tweet['username']}: {tweet['snippet'][:60]}...")
            print(f"    Reply: {reply_text[:80]}...")

            if dry_run:
                _log("reply", tweet["url"], "dry_run", "x")
                replied += 1
                continue

            result = x_agent.post_reply(
                tweet_url_or_id=tweet["url"],
                reply_text=reply_text,
                prospect=tweet["username"],
                dry_run=False,
            )
            status = result.get("status", "error")
            _log("reply", tweet["url"], status, "x")

            if status == "replied":
                replied += 1

            delay = random.uniform(120, 300)
            print(f"    Waiting {delay:.0f}s...")
            await asyncio.sleep(delay)

        time.sleep(2)

    print(f"\n[x] Done — {replied} replies posted today (total: {sent_today + replied}/{limit})")


# ── Stats ─────────────────────────────────────────────────────────────────────

def show_stats():
    today = date.today().isoformat()
    li_connects = _today_count("linkedin", "connect")
    x_replies = _today_count("x", "reply")

    print(f"\n{'─'*50}")
    print(f"DAILY GROWTH STATS — {today}")
    print(f"{'─'*50}")
    print(f"LinkedIn connections: {li_connects}/{LINKEDIN_DAILY_LIMIT}")
    print(f"X replies:           {x_replies}/{X_DAILY_LIMIT}")

    # 7-day totals from log
    if LOG_FILE.exists():
        week_li = week_x = 0
        with open(LOG_FILE) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("channel") == "linkedin" and e.get("action") == "connect" and e.get("result") == "sent":
                        week_li += 1
                    elif e.get("channel") == "x" and e.get("action") == "reply" and e.get("result") == "replied":
                        week_x += 1
                except Exception:
                    pass
        print(f"\nAll time:")
        print(f"  LinkedIn: {week_li} connections sent")
        print(f"  X:        {week_x} replies posted")
    print(f"{'─'*50}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Daily growth: LinkedIn connections + X replies")
    parser.add_argument("--linkedin-only", action="store_true")
    parser.add_argument("--x-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print targets without sending")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--li-limit", type=int, default=LINKEDIN_DAILY_LIMIT)
    parser.add_argument("--x-limit", type=int, default=X_DAILY_LIMIT)
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.dry_run:
        print("[DRY RUN MODE — no actual sends]\n")

    show_stats()

    if not args.x_only:
        await run_linkedin_growth(dry_run=args.dry_run, limit=args.li_limit)

    if not args.linkedin_only:
        await run_x_growth(dry_run=args.dry_run, limit=args.x_limit)

    show_stats()


async def main_args(
    dry_run: bool = False,
    linkedin_only: bool = False,
    x_only: bool = False,
    stats_only: bool = False,
    li_limit: int = LINKEDIN_DAILY_LIMIT,
    x_limit: int = X_DAILY_LIMIT,
):
    if stats_only:
        show_stats()
        return
    if dry_run:
        print("[DRY RUN MODE — no actual sends]\n")
    show_stats()
    if not x_only:
        await run_linkedin_growth(dry_run=dry_run, limit=li_limit)
    if not linkedin_only:
        await run_x_growth(dry_run=dry_run, limit=x_limit)
    show_stats()


if __name__ == "__main__":
    asyncio.run(main())
