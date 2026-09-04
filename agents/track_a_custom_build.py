"""Track A Custom Build — find non-technical CEOs/CTOs/VCs/Founders who want to build
something and position Saraswat as the person who builds it for them.

Target: Foreign founders, solo operators, non-technical entrepreneurs with:
  - An idea but no technical co-founder
  - A manual process they want to automate
  - A product they want to launch but can't code
  - A startup in planning stage needing MVP

Positioning: "I build your idea into working software in 4-6 weeks."

Pipeline:
  Track C connection → signal detected → custom build outreach → scoping call → build
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import claude_cli as anthropic

DB_PATH = Path(os.environ.get("NETWORKING_DB", Path.home() / "networking-agent.db"))
OUTPUT_DIR = Path(__file__).parent / "output" / "custom_build"
VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
OBSIDIAN_DIR = VAULT_PATH / "Prospects" / "TrackA_CustomBuild"

PROFILE = {
    "name": "Saraswat Das",
    "email": "davidmusk2002@gmail.com",
    "linkedin": "linkedin.com/in/saraswat-das",
    "website": "saraswat.vercel.app",
    "github": "github.com/Saraswat123",
    "proof": [
        "Built multi-model LLM pipeline (Ollama + Claude + vector DB): 80% reduction in manual comms prep for 50+ staff",
        "Replaced 15 disconnected spreadsheets across 15 locations with PostgreSQL warehouse: 95% accuracy, 85% overhead cut",
        "OCR + handwriting recognition pipeline: paper docs → structured data in minutes",
        "Production Rust MCP server + autonomous AI agent pipeline",
        "FOCIL + DVT-FOCIL Ethereum protocol R&D contributions",
    ],
    "build_offer": "I build your idea into working software in 4-6 weeks. MVP, automation pipeline, or data system — scoped, built, deployed.",
    "price_range": "£3,000-£15,000 per project depending on scope",
}

# Signals in LinkedIn bio/posts that indicate non-technical founder wanting to build
BUILD_SIGNALS = [
    "building", "idea", "non-technical founder", "looking for CTO", "co-founder",
    "stealth", "pre-launch", "early stage", "no-code", "MVP", "prototype",
    "want to build", "need a developer", "technical co-founder", "automating",
    "manual process", "spreadsheet", "workflow", "app idea",
]


def detect_build_signal(bio: str, posts: list[str] = None) -> tuple[bool, str]:
    """Return (has_signal, signal_description) from LinkedIn bio/posts."""
    text = (bio + " " + " ".join(posts or "")).lower()
    found = [s for s in BUILD_SIGNALS if s in text]
    if len(found) >= 2:
        return True, ", ".join(found[:3])
    return False, ""


def add_prospect(
    name: str,
    role: str,
    company: str,
    country: str,
    linkedin_url: str = "",
    x_handle: str = "",
    idea: str = "",
    problem: str = "",
    source: str = "track_c",
    notes: str = "",
    email: str = "",
) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        """INSERT INTO custom_build_prospects
           (name, role, company, country, linkedin_url, x_handle, idea, problem, source, created_at, notes, email)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, role, company, country, linkedin_url, x_handle, idea, problem, source,
         datetime.now().isoformat(), notes, email),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    _write_obsidian_note(pid, name, role, company, country, linkedin_url, idea, problem, notes)
    return pid


def generate_outreach(prospect_id: int) -> dict:
    """Generate cold outreach for custom build prospect."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM custom_build_prospects WHERE id=?", (prospect_id,)).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Prospect {prospect_id} not found")

    p = dict(row)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You write hyper-personalized cold outreach from a technical builder to a non-technical founder/CEO/VC who wants to build something.

SENDER:
Name: {PROFILE['name']}
Email: {PROFILE['email']}
Website: {PROFILE['website']}
GitHub: {PROFILE['github']}
Offer: {PROFILE['build_offer']}
Price: {PROFILE['price_range']}

PROOF POINTS:
{chr(10).join(f'- {p_}' for p_ in PROFILE['proof'])}

TARGET:
Name: {p['name']}
Role: {p['role']}
Company: {p.get('company', '?')}
Country: {p.get('country', '?')}
What they want to build: {p.get('idea', 'unclear — infer from role/company')}
Their problem: {p.get('problem', 'manual processes, no tech co-founder')}
Source: connected via {p.get('source', 'LinkedIn')}

RULES:
- Email: 100-130 words. Shorter = stronger.
- Never start with "I". Start with their problem or a number.
- No: "hope this finds you well", "excited to connect", "reaching out"
- Yes: one specific observation about their situation → one concrete proof point → one ask (20-min call)
- Position as: "I build the thing you've been trying to figure out how to build"
- NOT a job seeker. A builder they can hire project-by-project.
- LinkedIn DM: 40-50 words. End with specific question about what they're building.
- Follow-up (day 5): 40 words, add new angle (different proof point or case study)
- Follow-up (day 12): 20 words, soft close
- NEVER write a placeholder token like "[Name]", "[Company]" etc.
- NEVER open with a greeting line ("Hi X", "Dear X", "Hello") even if a real name is known —
  open the first sentence directly on their problem/situation, no greeting line at all.
- Body must state two things back to back, not just tease: (1) the actual problem/situation
  they're in right now, in concrete terms, (2) the actual thing we'd build to fix it, in
  concrete terms. Say it plainly in the email — don't hide it behind a "want to see more?" ask.

Return ONLY valid JSON:
{{
  "subject": "email subject (under 7 words)",
  "email": "full plain text email body",
  "linkedin_dm": "LinkedIn direct message after connecting",
  "follow_up_1": "day-5 follow-up",
  "follow_up_2": "day-12 follow-up"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
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

    result.update({
        "prospect_id": prospect_id,
        "name": p["name"],
        "company": p.get("company", ""),
        "country": p.get("country", ""),
    })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f"{p['name']}_{p.get('company','')}" if c.isalnum() or c in "-_").lower()
    out = OUTPUT_DIR / f"outreach_{safe}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"  [saved → {out.name}]")

    # Update status
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE custom_build_prospects SET status='contacted', outreach_sent=? WHERE id=?",
        (datetime.now().isoformat(), prospect_id),
    )
    conn.commit()
    conn.close()

    _update_obsidian_note(prospect_id, result)
    return result


def send_outreach(prospect_id: int, dry_run: bool = True) -> dict:
    """Send the saved outreach draft to a prospect via the davidmusk2002 Gmail identity."""
    import track_a_gmail

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM custom_build_prospects WHERE id=?", (prospect_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Prospect {prospect_id} not found")
    p = dict(row)
    if not p.get("email"):
        raise ValueError(f"Prospect {prospect_id} ({p['name']}) has no email saved")

    safe = "".join(c for c in f"{p['name']}_{p.get('company','')}" if c.isalnum() or c in "-_").lower()
    draft_path = OUTPUT_DIR / f"outreach_{safe}.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"No outreach draft for prospect {prospect_id} — run build-outreach first")
    draft = json.loads(draft_path.read_text())

    result = track_a_gmail.send(p["email"], draft["subject"], draft["email"], dry_run=dry_run)

    if result["status"] == "sent":
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE custom_build_prospects SET status='contacted', outreach_sent=? WHERE id=?",
            (datetime.now().isoformat(), prospect_id),
        )
        conn.commit()
        conn.close()
    return result


def list_prospects(status: str = "") -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if status:
        rows = conn.execute(
            "SELECT * FROM custom_build_prospects WHERE status=? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custom_build_prospects ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _write_obsidian_note(pid, name, role, company, country, linkedin_url, idea, problem, notes):
    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f"{name}" if c.isalnum() or c in " -").strip()
    note = OBSIDIAN_DIR / f"{safe}.md"
    note.write_text(f"""---
tags: [track-a, custom-build, prospect]
status: new
created: {datetime.now().strftime('%Y-%m-%d')}
---

# {name}

**Role:** {role}
**Company:** {company or '—'}
**Country:** {country or '—'}
**LinkedIn:** {linkedin_url or '—'}

## What They Want to Build
{idea or '—'}

## Problem / Pain
{problem or '—'}

## Notes
{notes or '—'}

## Outreach

> Not yet generated. Run: `python agents/cli.py build-outreach --id {pid}`

## Status Log
- {datetime.now().strftime('%Y-%m-%d')}: Added to pipeline
""")


def _update_obsidian_note(pid: int, outreach: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM custom_build_prospects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        return
    p = dict(row)
    safe = "".join(c for c in p['name'] if c.isalnum() or c in " -").strip()
    note = OBSIDIAN_DIR / f"{safe}.md"
    if not note.exists():
        return
    content = note.read_text()
    content = content.replace(
        "> Not yet generated. Run: `python agents/cli.py build-outreach --id " + str(pid) + "`",
        f"""**Subject:** {outreach.get('subject', '')}

**Email:**
{outreach.get('email', '')}

**LinkedIn DM:**
{outreach.get('linkedin_dm', '')}

**Follow-up 1 (day 5):**
{outreach.get('follow_up_1', '')}

**Follow-up 2 (day 12):**
{outreach.get('follow_up_2', '')}"""
    )
    content = content.replace(
        "- " + datetime.now().strftime('%Y-%m-%d') + ": Added to pipeline",
        f"- {datetime.now().strftime('%Y-%m-%d')}: Added to pipeline\n- {datetime.now().strftime('%Y-%m-%d')}: Outreach generated"
    )
    note.write_text(content)
