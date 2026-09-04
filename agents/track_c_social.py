"""Track C Social Growth Agent — daily LinkedIn + X growth automation.

Actions (ONLY):
  LinkedIn:
    - Send connection requests: CEOs, CTOs, VCs, new startups, Founders
    - Follow profiles (broader net, no approval needed)
    NO comments, NO post replies

  X (Twitter):
    - Follow relevant accounts (AI/infra/protocol/VC)
    - Like + Retweet trending tech posts (via browser automation)
    - Post articles from saraswat.vercel.app/writing (2-3x/week)
    NO post replies (unless user manually requests via x-reply CLI)

Daily targets:
  LinkedIn connections:  20 → ramp to 50
  LinkedIn follows:      100-150
  X follows:             80-100
  X likes:               20-30 per session
  X retweets:            5-10 per session
  X article posts:       1 (Mon/Wed/Fri only)
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("NETWORKING_DB", Path.home() / "networking-agent.db"))
VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
ANALYTICS_DIR = VAULT_PATH / "Prospects" / "TrackC_Social" / "Analytics"
LOG_FILE = Path(__file__).parent / "output" / "track_c_log.jsonl"
POSTED_ARTICLES_FILE = Path(__file__).parent / "output" / "posted_articles.json"

today = datetime.now().strftime("%Y-%m-%d")
today_weekday = datetime.now().weekday()  # 0=Mon, 6=Sun

# Connection notes by persona — max 300 chars, opens conversation, no pitch
CONNECTION_NOTES = {
    "ceo": [
        "Replaced 15 disconnected spreadsheets across 15 locations with a single PostgreSQL warehouse — cut ops overhead 85%. Building similar systems now. Thought it worth connecting.",
        "Built an LLM pipeline that cut manual comms prep 80% for 50+ staff org. If you're scaling ops with AI, happy to connect.",
        "Engineer focused on AI automation for ops-heavy orgs — cut manual overhead 85% at 15-location org. Saw your company and thought the work aligned. Worth connecting.",
        "Currently building AI systems that replace manual workflows for complex orgs. Following operators who've scaled — good to connect.",
    ],
    "cto": [
        "Building production Rust MCP servers and autonomous agent pipelines — your infrastructure stack looks close to what I'm working on. Worth connecting.",
        "Contributed to FOCIL + DVT-FOCIL Ethereum protocol R&D. Now building AI agent infrastructure in Rust. Your CTO background in distributed systems caught my eye.",
        "Deep in Rust + LLM infrastructure — built OCR/handwriting recognition pipeline that converts paper docs to structured data in minutes. Worth connecting.",
        "Working on distributed AI agent systems in Rust. Always good to connect with CTOs pushing the same infrastructure problems.",
    ],
    "vc": [
        "Engineer building AI automation + Rust protocol infrastructure. Contributed to Ethereum R&D (FOCIL/DVT-FOCIL). Following your portfolio — good to connect.",
        "Built AI pipelines cutting 80% manual overhead at 50-staff org. Interesting to see your investments in the space.",
        "Working at the AI infra + protocol layer — MCP servers, LLM pipelines, Ethereum protocol contributions. Would value connecting with an investor tracking this space.",
    ],
    "family_office": [
        "Built AI systems replacing manual ops for a 15-location org — 85% overhead cut, zero spreadsheets. Family offices running on Excel are a natural fit. Worth connecting.",
        "Engineer who automates complex ops for capital-heavy orgs. Replaced 15 spreadsheets with a live data warehouse. If your office is still running manual processes, happy to connect.",
        "Working with wealth management and family office operators on AI automation — reporting, due diligence, document processing. Good to have you in the network.",
        "Built OCR + document processing pipelines for structured data extraction. If your family office handles a lot of paper-based ops, worth a conversation.",
    ],
    "hni": [
        "Engineer building AI automation for private investors and family offices — portfolio tracking, reporting, document processing without the manual overhead. Good to connect.",
        "Worked with ops-heavy investment orgs to cut manual workflows 80%+ using AI. Always good to connect with investors thinking about operational efficiency.",
        "Building AI systems for capital allocators — the kind that replace spreadsheets, manual reports, and disconnected tools with a single intelligent layer. Worth connecting.",
    ],
    "endowment": [
        "Built data infrastructure for complex multi-location orgs — 15 sites, one live warehouse, 95% reporting accuracy. Similar scale to endowment operations. Worth connecting.",
        "Engineer focused on AI automation for institutions with complex ops — reporting, data aggregation, document workflows. Saw your work and thought it worth connecting.",
        "Working on AI systems that replace manual reporting and ops overhead for large capital pools. Good to connect with endowment operators thinking about this layer.",
    ],
    "founder": [
        "Built full data warehouse replacing 15 spreadsheets across 15 locations — 95% accuracy, 85% overhead cut. If you're solving similar ops problems, good to connect.",
        "Engineer who builds AI/data systems for real org problems — not demos. Replaced manual workflows at 50+ staff org with LLM pipeline.",
        "Working on autonomous AI agent systems. I ship infrastructure that replaces broken manual ops. Worth staying connected.",
        "Built production AI automation for ops-heavy orgs. Following founders tackling the same problems — good to have you in the network.",
    ],
    "engineer": [
        "Working on Rust MCP servers and distributed AI agent pipelines — Ethereum protocol R&D contributor (FOCIL/DVT-FOCIL). Worth connecting.",
        "Building agent infrastructure in Rust — OCR pipelines, LLM systems, p2p protocols. Always good to connect with engineers pushing the same layer.",
        "Deep in Rust + distributed systems. Contributed to Ethereum consensus protocol research. Saw your work and thought it worth connecting.",
    ],
    "default": [
        "Building AI infrastructure and automation systems — cut ops overhead 85% at 15-location org. Saw your work and thought worth connecting.",
        "Engineer focused on AI automation for complex orgs. Built LLM pipelines cutting 80% manual overhead. Good to expand the network.",
    ],
}


def _pick_note(keyword: str) -> str:
    """Pick connection note based on keyword persona."""
    import random
    kw = keyword.lower()
    if any(w in kw for w in ["family office", "family_office", "single family", "multi family", "mfo", "sfo", "wealth management", "private wealth"]):
        pool = CONNECTION_NOTES["family_office"]
    elif any(w in kw for w in ["hni", "high net worth", "private investor", "private client", "hnwi", "uhnwi"]):
        pool = CONNECTION_NOTES["hni"]
    elif any(w in kw for w in ["endowment", "foundation", "charitable", "trust fund", "sovereign wealth"]):
        pool = CONNECTION_NOTES["endowment"]
    elif any(w in kw for w in ["ceo", "founder", "co-founder", "operator", "md ", "managing director"]):
        pool = CONNECTION_NOTES["ceo"] + CONNECTION_NOTES["founder"]
    elif any(w in kw for w in ["cto", "vp engineering", "head of engineering", "principal", "staff engineer"]):
        pool = CONNECTION_NOTES["cto"] + CONNECTION_NOTES["engineer"]
    elif any(w in kw for w in ["partner", "vc", "investor", "general partner", "angel", "fund manager"]):
        pool = CONNECTION_NOTES["vc"]
    elif any(w in kw for w in ["engineer", "researcher", "developer"]):
        pool = CONNECTION_NOTES["engineer"]
    else:
        pool = CONNECTION_NOTES["default"]
    note = random.choice(pool)
    return note[:300]  # LinkedIn hard limit


# LinkedIn connection targets — CEOs/CTOs/VCs + new startups
LI_CONNECT_KEYWORDS = [
    # Family offices + private wealth
    "CEO family office",
    "Managing Director family office",
    "Chief Investment Officer family office",
    "Head of Operations family office",
    "founder multi family office",
    "MD single family office",
    "CEO private wealth management",
    "Managing Director wealth management",
    "Head family office London",
    "CIO family office Singapore",
    # HNIs + private investors
    "private investor technology",
    "angel investor family office",
    "Managing Director private equity",
    "CEO private investment office",
    "Principal private capital",
    # Endowments + foundations + global houses
    "Chief Investment Officer endowment",
    "CEO foundation investment",
    "Head of Investments endowment",
    "Managing Director sovereign wealth",
    "CIO foundation fund",
    "Head of Operations global house",
    # Operators — non-technical founders of capital-heavy orgs
    "founder real estate investment",
    "CEO logistics company",
    "Managing Director law firm",
    "CEO wealth management firm",
    "founder accounting firm",
    "CEO consulting firm",
    "Managing Director real estate",
    "CEO insurance broker",
    # Funded founders (AI/tech)
    "CEO AI startup",
    "founder YC AI",
    "CEO LLM startup",
    "co-founder AI agents",
    "founder data automation",
    # VCs + fund managers
    "partner seed fund AI",
    "General Partner AI fund",
    "Managing Partner early stage",
    "angel investor AI startup",
    "fund manager deep tech",
]

# X follow targets
X_FOLLOW_KEYWORDS = [
    "AI infrastructure engineer",
    "protocol engineer Rust",
    "VC partner AI fund",
    "LLM infrastructure founder",
    "distributed systems engineer",
    "ML infrastructure researcher",
    "YC founder AI",
    "crypto protocol engineer",
]

# X trending tech topics to like/RT — rotates across 5 fields
X_TECH_TRENDS = {
    "AI": [
        "#AIAgents",
        "#LLM",
        "#GenerativeAI",
        "#AIInfrastructure",
        "#MCP",
        "#Anthropic",
        "#OpenAI",
        "AI infrastructure 2026",
    ],
    "Blockchain": [
        "#Ethereum",
        "#Web3",
        "#ZeroKnowledge",
        "#ZKProofs",
        "#DeFi",
        "#Consensus",
        "#Layer2",
        "Ethereum protocol 2026",
    ],
    "DeepTech": [
        "#RustLang",
        "#eBPF",
        "#PostQuantum",
        "#DistributedSystems",
        "#P2P",
        "#BFT",
        "deep tech infrastructure",
        "#SystemsProgramming",
    ],
    "Infra": [
        "#CloudNative",
        "#Kubernetes",
        "#DevOps",
        "#DataEngineering",
        "#MLOps",
        "#AIInfra",
        "AI infrastructure startup",
        "#PostgreSQL",
    ],
    "TokenEconomics": [
        "#Tokenomics",
        "#DePIN",
        "#Web3Economics",
        "#CryptoVCs",
        "#Protocol",
        "token economy 2026",
        "#DAOs",
        "#OnchainEconomics",
    ],
}

# All fields flattened for random daily pick
_ALL_TRENDS = [t for trends in X_TECH_TRENDS.values() for t in trends]

# Daily field rotation (Mon=AI, Tue=Blockchain, Wed=DeepTech, Thu=Infra, Fri=TokenEcon, weekend=mix)
_FIELD_SCHEDULE = {0: "AI", 1: "Blockchain", 2: "DeepTech", 3: "Infra", 4: "TokenEconomics"}

# Limits
LI_CONNECT_LIMIT = 30
LI_FOLLOW_LIMIT = 120
X_FOLLOW_LIMIT = 80
X_LIKE_LIMIT = 25
X_RETWEET_LIMIT = 8
ARTICLE_POST_DAYS = {0, 2, 4}  # Mon, Wed, Fri


def _log(action: str, platform: str, target: str, result: str, notes: str = ""):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": today,
        "ts": datetime.now().isoformat(),
        "platform": platform,
        "action": action,
        "target": target,
        "result": result,
        "notes": notes,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """INSERT INTO engagement_log (platform, action, target_name, content_preview, result)
               VALUES (?, ?, ?, ?, ?)""",
            (platform, action, target, notes[:200] if notes else "", result),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _today_stats() -> dict:
    stats = {
        "li_connections_sent": 0,
        "li_follows": 0,
        "x_follows": 0,
        "x_likes": 0,
        "x_retweets": 0,
        "x_posts": 0,
    }
    if not LOG_FILE.exists():
        return stats
    with open(LOG_FILE) as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("date") != today:
                    continue
                if e["result"] in ("dry_run", "error", "failed"):
                    continue
                key = (e["platform"], e["action"])
                if key == ("linkedin", "connect") and e["result"] == "sent":
                    stats["li_connections_sent"] += 1
                elif key == ("linkedin", "follow") and e["result"] == "followed":
                    stats["li_follows"] += 1
                elif key == ("x", "follow") and e["result"] == "followed":
                    stats["x_follows"] += 1
                elif key == ("x", "like") and e["result"] == "liked":
                    stats["x_likes"] += 1
                elif key == ("x", "retweet") and e["result"] == "retweeted":
                    stats["x_retweets"] += 1
                elif key == ("x", "post") and e["result"] == "posted":
                    stats["x_posts"] += 1
            except Exception:
                pass
    return stats


def _save_daily_stats(stats: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """INSERT OR REPLACE INTO daily_social_stats
               (date, li_connections_sent, li_follows, x_follows, x_replies)
               VALUES (?, ?, ?, ?, ?)""",
            (today, stats["li_connections_sent"], stats["li_follows"], stats["x_follows"], 0),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _get_posted_article_ids() -> list:
    if POSTED_ARTICLES_FILE.exists():
        try:
            return json.loads(POSTED_ARTICLES_FILE.read_text())
        except Exception:
            pass
    return []


def _mark_article_posted(article_id: str):
    posted = _get_posted_article_ids()
    if article_id not in posted:
        posted.append(article_id)
    POSTED_ARTICLES_FILE.write_text(json.dumps(posted))


async def run_linkedin_connections(dry_run: bool = False, limit: int = LI_CONNECT_LIMIT):
    """Connect with CEOs, CTOs, VCs, new startup founders — 20+/day. One browser session."""
    import random
    import linkedin_agent

    current = _today_stats()["li_connections_sent"]
    remaining = limit - current
    if remaining <= 0:
        print(f"  [LI Connect] Limit reached ({limit}/day)")
        return 0

    priority_kws = [k for k in LI_CONNECT_KEYWORDS if any(
        w in k for w in ["startup", "founder", "CEO", "CTO", "Partner", "VC"]
    )]
    keywords_today = random.sample(priority_kws, min(6, len(priority_kws)))
    print(f"  [LI Connect] Target: {remaining} | Personas: {', '.join(keywords_today[:2])}...")

    # Build (keyword, note) pairs — one browser session for all connects
    keyword_notes = [(kw, _pick_note(kw)) for kw in keywords_today]

    try:
        result = await linkedin_agent.batch_search_and_connect(
            keyword_notes=keyword_notes,
            dry_run=dry_run,
            limit=remaining,
        )
        sent = result.get("sent", 0)
        # Log each sent action (batch function already prints)
        for i in range(sent):
            _log("connect", "linkedin", f"batch_{i}", "sent", keywords_today[0])
    except Exception as e:
        print(f"    ERROR (batch connect): {e}")
        sent = 0

    print(f"  [LI Connect] {sent} sent | total today: {current + sent}/{limit}")
    return sent


async def run_linkedin_follows(dry_run: bool = False, limit: int = LI_FOLLOW_LIMIT):
    """Follow broader audience — engineers, researchers, protocol people. One browser session."""
    import random
    import linkedin_agent

    current = _today_stats()["li_follows"]
    remaining = limit - current
    if remaining <= 0:
        print(f"  [LI Follow] Limit reached ({limit}/day)")
        return 0

    keywords_today = random.sample(LI_CONNECT_KEYWORDS, min(12, len(LI_CONNECT_KEYWORDS)))
    print(f"  [LI Follow] Target: {remaining}")

    # One browser session — visits all keywords and follows without reopening browser
    try:
        result = await linkedin_agent.batch_follow_profiles(
            keyword_list=keywords_today,
            dry_run=dry_run,
            limit=remaining,
            urls_per_keyword=30,
        )
        followed = result.get("followed", 0)
        # Log each actual URL followed for accurate stats
        for url in result.get("urls", []):
            name = url.split("/in/")[-1].split("/")[0] if "/in/" in url else url[-30:]
            _log("follow", "linkedin", name, "followed", keywords_today[0])
        # Fallback if urls list empty but count > 0 (shouldn't happen, but safe)
        if followed > 0 and not result.get("urls"):
            for i in range(followed):
                _log("follow", "linkedin", f"batch_{i}", "followed", keywords_today[0])
    except Exception as e:
        print(f"    ERROR (batch follow): {e}")
        followed = 0

    print(f"  [LI Follow] {followed} followed | total today: {current + followed}/{limit}")
    return followed


async def run_x_follows(dry_run: bool = False, limit: int = X_FOLLOW_LIMIT):
    """Follow VCs, CTOs, engineers on X via browser automation."""
    import random
    current = _today_stats()["x_follows"]
    remaining = limit - current
    if remaining <= 0:
        print(f"  [X Follow] Limit reached ({limit}/day)")
        return 0

    # Follow people from today's field
    field = _FIELD_SCHEDULE.get(today_weekday, random.choice(list(X_TECH_TRENDS)))
    field_trends = X_TECH_TRENDS[field]
    kw = random.choice(field_trends + X_FOLLOW_KEYWORDS)
    print(f"  [X Follow] Target: {remaining} | Field: {field} | Keyword: {kw}")

    # Browser automation via Playwright
    try:
        from playwright.async_api import async_playwright
        from pathlib import Path
        import os

        session_file = Path(__file__).parent.parent / "x_session.json"
        if not session_file.exists():
            print("  [SKIP] x_session.json not found — run x-setup first")
            return 0

        followed = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=str(session_file))
            page = await ctx.new_page()

            search_url = f"https://x.com/search?q={kw.replace(' ', '%20')}&f=user"
            await page.goto(search_url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(3000)

            follow_btns = page.locator("button[data-testid='follow']")
            count = await follow_btns.count()
            print(f"    Found {count} follow buttons")

            for i in range(min(count, remaining)):
                if dry_run:
                    _log("follow", "x", f"user_{i}", "dry_run", kw)
                    followed += 1
                    continue
                try:
                    btn = follow_btns.nth(i)
                    await btn.click(timeout=3000)
                    await page.wait_for_timeout(800)
                    _log("follow", "x", f"x_user_{i}", "followed", kw)
                    followed += 1
                except Exception:
                    pass

            await browser.close()

        print(f"  [X Follow] {followed} followed | total today: {current + followed}/{limit}")
        return followed

    except Exception as e:
        print(f"  [X Follow] ERROR: {e}")
        return 0


async def run_x_engagement(
    dry_run: bool = False,
    like_limit: int = X_LIKE_LIMIT,
    rt_limit: int = X_RETWEET_LIMIT,
):
    """Like + retweet trending tech posts via browser automation."""
    import random

    current = _today_stats()
    likes_remaining = like_limit - current["x_likes"]
    rt_remaining = rt_limit - current["x_retweets"]

    if likes_remaining <= 0 and rt_remaining <= 0:
        print(f"  [X Engage] Limits reached (likes: {like_limit}, RT: {rt_limit})")
        return 0, 0

    # Pick today's field by weekday, random within field
    field = _FIELD_SCHEDULE.get(today_weekday, random.choice(list(X_TECH_TRENDS)))
    trend = random.choice(X_TECH_TRENDS[field])
    print(f"  [X Engage] Target: {likes_remaining} likes, {rt_remaining} RTs | Field: {field} | Trend: {trend}")

    try:
        from playwright.async_api import async_playwright

        session_file = Path(__file__).parent.parent / "x_session.json"
        if not session_file.exists():
            print("  [SKIP] x_session.json not found")
            return 0, 0

        liked = 0
        retweeted = 0

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=str(session_file))
            page = await ctx.new_page()

            search_url = f"https://x.com/search?q={trend.replace('#', '%23')}&f=live"
            await page.goto(search_url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(3000)

            # Like posts
            like_btns = page.locator("button[data-testid='like']")
            like_count = await like_btns.count()

            for i in range(min(like_count, likes_remaining)):
                if dry_run:
                    _log("like", "x", f"post_{i}", "dry_run", trend)
                    liked += 1
                    continue
                try:
                    await like_btns.nth(i).click(timeout=3000)
                    await page.wait_for_timeout(600)
                    _log("like", "x", f"post_{i}", "liked", trend)
                    liked += 1
                except Exception:
                    pass

            # Retweet top posts
            rt_btns = page.locator("button[data-testid='retweet']")
            rt_count = await rt_btns.count()

            for i in range(min(rt_count, rt_remaining)):
                if dry_run:
                    _log("retweet", "x", f"post_{i}", "dry_run", trend)
                    retweeted += 1
                    continue
                try:
                    await rt_btns.nth(i).click(timeout=3000)
                    await page.wait_for_timeout(500)
                    # Confirm retweet in popup
                    confirm = page.locator("[data-testid='retweetConfirm']")
                    if await confirm.count() > 0:
                        await confirm.click(timeout=2000)
                        await page.wait_for_timeout(500)
                    _log("retweet", "x", f"post_{i}", "retweeted", trend)
                    retweeted += 1
                except Exception:
                    pass

            await browser.close()

        print(f"  [X Engage] {liked} liked, {retweeted} retweeted | trend: {trend}")
        return liked, retweeted

    except Exception as e:
        print(f"  [X Engage] ERROR: {e}")
        return 0, 0


async def run_x_post_article(dry_run: bool = False):
    """Post article from saraswat.vercel.app/writing to X (Mon/Wed/Fri only)."""
    if today_weekday not in ARTICLE_POST_DAYS:
        print(f"  [X Post] Skipping — article days: Mon/Wed/Fri only")
        return

    current_posts = _today_stats()["x_posts"]
    if current_posts >= 1:
        print(f"  [X Post] Already posted article today")
        return

    try:
        import articles_scraper
        import x_agent

        posted_ids = _get_posted_article_ids()
        article = articles_scraper.get_article_for_tweet(posted_ids)

        # Generate tweet text from article hook
        hook = article["hook"][:200].strip()
        url = article["url"]
        tag = article["tag"]

        # Keep under 240 chars (leave room for URL)
        tweet_parts = [
            f"{hook}",
            f"\n\n{url}",
        ]
        tweet = "".join(tweet_parts)
        if len(tweet) > 280:
            tweet = hook[:200] + f"...\n\n{url}"

        print(f"  [X Post] Article: {article['title'][:50]}")
        print(f"  [X Post] Tweet ({len(tweet)} chars): {tweet[:100]}...")

        if dry_run:
            _log("post", "x", article["id"], "dry_run", article["title"])
            print(f"  [X Post] DRY RUN — would post article: {article['id']}")
            return

        result = x_agent.post_tweet(tweet)
        if result.get("status") == "posted":
            _log("post", "x", article["id"], "posted", article["title"])
            _mark_article_posted(article["id"])
            print(f"  [X Post] Posted → {result.get('url')}")
        else:
            print(f"  [X Post] Failed: {result}")

    except Exception as e:
        print(f"  [X Post] ERROR: {e}")


def show_stats():
    """Print today's Track C stats."""
    stats = _today_stats()
    sep = "─" * 52

    print(f"\n{sep}")
    print(f"TRACK C — DAILY STATS ({today})")
    print(sep)
    print(f"LinkedIn Connections: {stats['li_connections_sent']:3d} / {LI_CONNECT_LIMIT}")
    print(f"LinkedIn Follows:     {stats['li_follows']:3d} / {LI_FOLLOW_LIMIT}")
    print(f"X Follows:            {stats['x_follows']:3d} / {X_FOLLOW_LIMIT}")
    print(f"X Likes:              {stats['x_likes']:3d} / {X_LIKE_LIMIT}")
    print(f"X Retweets:           {stats['x_retweets']:3d} / {X_RETWEET_LIMIT}")
    print(f"X Article Posts:      {stats['x_posts']:3d} / 1")
    print(sep)

    # 7-day history
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT date, li_connections_sent, li_follows, x_follows FROM daily_social_stats ORDER BY date DESC LIMIT 7"
        ).fetchall()
        conn.close()
        if rows:
            print("\n7-DAY HISTORY:")
            print(f"{'Date':12s} {'LI Connect':12s} {'LI Follow':10s} {'X Follow':8s}")
            for r in rows:
                print(f"{r[0]:12s} {r[1]:12d} {r[2]:10d} {r[3]:8d}")
    except Exception:
        pass
    print(sep)


def update_obsidian_stats():
    """Update Obsidian Analytics/Weekly Stats.md."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT date, li_connections_sent, li_follows, li_comments_made, x_follows, x_replies FROM daily_social_stats ORDER BY date DESC LIMIT 14"
        ).fetchall()
        conn.close()

        if not rows:
            return

        lines = [
            "---",
            "tags: [track-c, analytics]",
            f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "---",
            "",
            "# Weekly Social Stats",
            "",
            "| Date | LI Connections | LI Follows | X Follows |",
            "|---|---|---|---|",
        ]
        for r in rows:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[4]} |")

        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        (ANALYTICS_DIR / "Weekly Stats.md").write_text("\n".join(lines))
    except Exception:
        pass


async def run_daily(
    dry_run: bool = False,
    li_connect: int = LI_CONNECT_LIMIT,
    li_follow: int = LI_FOLLOW_LIMIT,
    x_follow: int = X_FOLLOW_LIMIT,
    x_like: int = X_LIKE_LIMIT,
    x_rt: int = X_RETWEET_LIMIT,
    linkedin_only: bool = False,
    x_only: bool = False,
):
    """Run full daily Track C session."""
    print(f"\n{'═'*52}")
    print(f"TRACK C — DAILY SOCIAL GROWTH ({today})")
    if dry_run:
        print("  [DRY RUN MODE]")
    print(f"{'═'*52}\n")

    if not x_only:
        await run_linkedin_connections(dry_run=dry_run, limit=li_connect)
        print()
        await run_linkedin_follows(dry_run=dry_run, limit=li_follow)
        print()

    if not linkedin_only:
        await run_x_follows(dry_run=dry_run, limit=x_follow)
        print()
        await run_x_engagement(dry_run=dry_run, like_limit=x_like, rt_limit=x_rt)
        print()
        await run_x_post_article(dry_run=dry_run)
        print()

    stats = _today_stats()
    _save_daily_stats(stats)
    update_obsidian_stats()
    show_stats()


if __name__ == "__main__":
    asyncio.run(run_daily(dry_run=True))
