"""Content Agent — generates LinkedIn posts and X threads for Track C social growth.

Five content pillars:
  1. rust_protocol   — MCP server builds, p2p, BFT consensus, Rust patterns
  2. ai_infra        — LLM pipeline architecture, agent patterns, what breaks at scale
  3. data_engineering — warehouse design, automation wins, real metrics
  4. build_in_public — weekly ship logs, project updates, failures
  5. industry_take   — opinionated takes on AI/infra/protocol news
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import claude_cli as anthropic

DB_PATH = Path(os.environ.get("NETWORKING_DB", Path.home() / "networking-agent.db"))
OUTPUT_DIR = Path(__file__).parent / "output" / "content"
VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
CONTENT_DIR = VAULT_PATH / "Prospects" / "TrackC_Social" / "Content"
CALENDAR_FILE = CONTENT_DIR / "Content Calendar.md"

PILLARS = ["rust_protocol", "ai_infra", "data_engineering", "build_in_public", "industry_take"]

PILLAR_SCHEDULE = {
    0: "rust_protocol",      # Monday
    1: "industry_take",      # Tuesday
    2: "data_engineering",   # Wednesday
    3: "build_in_public",    # Thursday
    4: "ai_infra",           # Friday
    5: "rust_protocol",      # Saturday (thread)
}

PROFILE = {
    "name": "Saraswat Das",
    "x": "@SaraswatDas13",
    "linkedin": "linkedin.com/in/saraswat-das",
    "github": "github.com/Saraswat123",
    "proof_points": [
        "Built production Rust MCP server + autonomous AI agent pipeline",
        "Multi-model LLM pipeline (Ollama + Claude + vector DB): 80% reduction in manual comms prep across 50+ staff",
        "PostgreSQL warehouse replacing 15 disconnected spreadsheets across 15 locations: 95% data accuracy, 85% overhead reduction",
        "OCR + handwriting recognition pipeline: handwritten docs → structured data in minutes",
        "FOCIL + DVT-FOCIL Ethereum protocol R&D contributions",
        "p2pflow: Rust async networking library",
        "HotStuff BFT consensus Rust implementation",
    ]
}


def _get_client():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_post(
    pillar: str,
    platform: str = "both",  # linkedin / x / both
    topic: str = "",
    context: str = "",
) -> dict:
    """Generate a single post for given pillar and platform."""
    client = _get_client()

    pillar_guides = {
        "rust_protocol": "Rust systems programming, MCP protocol, p2p networking, BFT consensus, Ethereum protocol R&D. Show engineering depth.",
        "ai_infra": "LLM pipeline architecture, multi-model orchestration, agent patterns, what breaks at scale in production AI systems.",
        "data_engineering": "PostgreSQL warehouse design, automation pipelines, OCR, real metrics and numbers. Proof over claims.",
        "build_in_public": "What shipped this week, what broke, what learned. Raw and honest. Real numbers where possible.",
        "industry_take": "Opinionated take on AI/infra/protocol news or trends. Not a summary — a stance. Contrarian if warranted.",
    }

    topic_hint = f"\nSpecific topic/angle: {topic}" if topic else ""
    context_hint = f"\nAdditional context: {context}" if context else ""

    prompt = f"""You are a ghostwriter for a protocol engineer and AI systems builder. Generate social content.

AUTHOR PROFILE:
Name: {PROFILE['name']}
X: {PROFILE['x']}
GitHub: {PROFILE['github']}

PROOF POINTS (use these — they're real and verified):
{chr(10).join(f'- {p}' for p in PROFILE['proof_points'])}

PILLAR: {pillar}
GUIDE: {pillar_guides.get(pillar, '')}
{topic_hint}
{context_hint}

RULES — non-negotiable:
- NO generic AI cheerleading. No "AI is changing everything". Specific or silent.
- NO: "excited to share", "thrilled to announce", "passionate about"
- YES: specific technical detail, real numbers, concrete architecture decisions
- LinkedIn: 150-250 words. Hook line first (no "I" to start). 3-5 short paragraphs. End with question or CTA.
- X thread: 5-8 tweets. Tweet 1 = hook (under 240 chars, no hashtags). Each tweet = one idea. Last tweet = CTA or question.
- Single X post: under 240 chars, punchy, no hashtags in body (add 1-2 at end max)
- Tone: technical peer talking to technical peers. Confident, not arrogant. Direct.
- Include at least ONE specific number or technical detail from proof points above.

Return ONLY valid JSON:
{{
  "linkedin_post": "full LinkedIn post text",
  "x_thread": ["tweet 1", "tweet 2", "tweet 3", "tweet 4", "tweet 5"],
  "x_single": "single tweet version (under 240 chars)",
  "pillar": "{pillar}",
  "hook": "the opening line / hook"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    try:
        result, _ = json.JSONDecoder().raw_decode(text.strip())
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        result = json.loads(text[start:end])

    return result


def generate_week(start_date: str = "") -> list[dict]:
    """Generate 7 days of content. Returns list of content items."""
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")

    base = datetime.strptime(start_date, "%Y-%m-%d")
    week_content = []

    print(f"Generating content for week of {start_date}...")

    for day_offset in range(7):
        date = base + timedelta(days=day_offset)
        weekday = date.weekday()
        pillar = PILLAR_SCHEDULE.get(weekday)

        if not pillar:
            continue

        platform = "x" if weekday in (1, 3) else "both"
        print(f"  [{date.strftime('%a %Y-%m-%d')}] {pillar} ({platform})...")

        try:
            post = generate_post(pillar=pillar, platform=platform)
            post["date"] = date.strftime("%Y-%m-%d")
            post["platform"] = platform
            post["status"] = "draft"
            week_content.append(post)

            _save_to_db(post)
        except Exception as e:
            print(f"    ERROR: {e}")

    _save_calendar_to_obsidian(week_content)
    _save_content_files(week_content)
    return week_content


def _save_to_db(post: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR IGNORE INTO content_calendar (date, platform, content_type, topic, draft, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            post.get("date"),
            post.get("platform", "both"),
            "post",
            post.get("pillar"),
            json.dumps(post),
            "draft",
        ),
    )
    conn.commit()
    conn.close()


def _save_content_files(week_content: list):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = week_content[0]["date"] if week_content else datetime.now().strftime("%Y-%m-%d")
    out = OUTPUT_DIR / f"content_week_{date_str}.json"
    out.write_text(json.dumps(week_content, indent=2))
    print(f"[Saved → {out}]")


def _save_calendar_to_obsidian(week_content: list):
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "tags: [track-c, content, calendar]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "---",
        "",
        "# Content Calendar",
        "",
        "> Auto-generated by content_agent.py",
        "",
    ]

    for post in week_content:
        date = post.get("date", "")
        pillar = post.get("pillar", "").replace("_", " ").title()
        platform = post.get("platform", "both")
        hook = post.get("hook", "")
        status = post.get("status", "draft")

        lines += [
            f"## {date} — {pillar} ({platform})",
            f"**Status:** {status}",
            f"**Hook:** {hook}",
            "",
            "### LinkedIn Post",
            "```",
            post.get("linkedin_post", "N/A"),
            "```",
            "",
            "### X Thread",
        ]
        for i, tweet in enumerate(post.get("x_thread", []), 1):
            lines.append(f"{i}. {tweet}")
        lines += ["", "### X Single Post", post.get("x_single", ""), "", "---", ""]

    CALENDAR_FILE.write_text("\n".join(lines))
    print(f"[Obsidian calendar updated → {CALENDAR_FILE.name}]")


def print_post(post: dict):
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"DATE: {post.get('date')} | PILLAR: {post.get('pillar')} | PLATFORM: {post.get('platform')}")
    print(sep)
    print("LINKEDIN:\n")
    print(post.get("linkedin_post", ""))
    print(f"\n{sep}")
    print("X THREAD:\n")
    for i, t in enumerate(post.get("x_thread", []), 1):
        print(f"[{i}] {t}\n")
    print(f"{sep}")
