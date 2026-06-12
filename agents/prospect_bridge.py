"""
Prospect Bridge — connects Rust SQLite DB to Python outreach pipeline.

Flow per prospect:
  1. Read 'new' prospects from DB
  2. Find emails via Hunter.io (if missing)
  3. Detect tech stack via WebReveal (if company website known)
  4. Generate outreach package (email + LinkedIn + follow-ups)
  5. Log to outreach_log table
  6. Update status → 'researched' (human reviews before sending)
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

import outreach_agent

DB_ENV = "NETWORKING_DB"
DEFAULT_DB = Path.home() / "networking-agent.db"


# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_db_path() -> Path:
    path = os.environ.get(DB_ENV, str(DEFAULT_DB))
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"SQLite DB not found at {p}\n"
            f"Set {DB_ENV} env var or run the Rust MCP agent first to create it."
        )
    return p


def get_prospects(db: sqlite3.Connection, status: str = "new", limit: int = 50) -> list[dict]:
    db.row_factory = sqlite3.Row
    cur = db.execute(
        """
        SELECT id, name, github, email, company, role, location, notes, source, outreach_status
        FROM prospects
        WHERE outreach_status = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (status, limit),
    )
    return [dict(row) for row in cur.fetchall()]


def update_prospect_email(db: sqlite3.Connection, prospect_id: int, email: str) -> None:
    db.execute("UPDATE prospects SET email = ? WHERE id = ?", (email, prospect_id))
    db.commit()


def update_prospect_status(db: sqlite3.Connection, prospect_id: int, status: str) -> None:
    db.execute("UPDATE prospects SET outreach_status = ? WHERE id = ?", (status, prospect_id))
    db.commit()


def update_prospect_notes(db: sqlite3.Connection, prospect_id: int, notes: str) -> None:
    db.execute("UPDATE prospects SET notes = ? WHERE id = ?", (notes, prospect_id))
    db.commit()


def log_outreach(db: sqlite3.Connection, prospect_id: int, channel: str, message: str) -> None:
    db.execute(
        "INSERT INTO outreach_log (prospect_id, channel, message) VALUES (?, ?, ?)",
        (prospect_id, channel, message),
    )
    db.commit()


# ─── Enrichment ──────────────────────────────────────────────────────────────

def find_email_hunter(domain: str, api_key: str) -> Optional[tuple[str, str, str]]:
    """Returns (email, name, role) of best match or None."""
    if not api_key or not domain:
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": api_key, "limit": "5"},
            timeout=10,
        )
        data = resp.json().get("data", {})
        emails = data.get("emails", [])
        if not emails:
            return None
        # prefer decision makers: CTO, CEO, founder, VP Eng
        priority_titles = ["cto", "chief technology", "co-founder", "founder", "vp engineering", "head of engineering"]
        for e in emails:
            pos = (e.get("position") or "").lower()
            if any(t in pos for t in priority_titles):
                return e["value"], f"{e.get('first_name','')} {e.get('last_name','')}".strip(), e.get("position", "")
        # fallback: highest confidence
        best = max(emails, key=lambda x: x.get("confidence", 0))
        return best["value"], f"{best.get('first_name','')} {best.get('last_name','')}".strip(), best.get("position", "")
    except Exception as e:
        print(f"  [hunter] error: {e}")
        return None


def get_tech_stack(url: str) -> list[str]:
    """Returns list of detected technology names from WebReveal."""
    if not url:
        return []
    try:
        resp = requests.get(
            "https://api.webreveal.io/tech",
            params={"url": url},
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=15,
        )
        data = resp.json()
        techs = data.get("technologies", [])
        return [t.get("name", "") for t in techs if t.get("name")]
    except Exception as e:
        print(f"  [webreveal] error: {e}")
        return []


def extract_domain(notes_or_url: str) -> Optional[str]:
    """Pull domain from a URL or return None."""
    if not notes_or_url:
        return None
    for word in notes_or_url.split():
        if "." in word and "/" in word:
            stripped = word.strip(".,;\"'")
            stripped = stripped.replace("https://", "").replace("http://", "").replace("www.", "")
            return stripped.split("/")[0]
    return None


def infer_signal(prospect: dict, tech_stack: list[str]) -> str:
    """Build a signal string from available prospect data for outreach personalization."""
    parts = []
    if prospect.get("source") == "yc":
        parts.append("YC-backed company")
    if tech_stack:
        rust_adjacent = [t for t in tech_stack if t.lower() in ["rust", "go", "c++", "webassembly", "wasm"]]
        if rust_adjacent:
            parts.append(f"runs {', '.join(rust_adjacent)} in production")
        else:
            parts.append(f"stack includes {', '.join(tech_stack[:3])}")
    if prospect.get("notes"):
        parts.append(prospect["notes"][:100])
    return "; ".join(parts) if parts else f"found via {prospect.get('source', 'search')}"


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run_bridge(
    status_filter: str = "new",
    limit: int = 20,
    dry_run: bool = False,
    skip_enrichment: bool = False,
) -> None:
    hunter_key = os.environ.get("HUNTER_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not anthropic_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    db_path = get_db_path()
    db = sqlite3.connect(str(db_path))

    prospects = get_prospects(db, status=status_filter, limit=limit)
    print(f"\nFound {len(prospects)} prospects with status='{status_filter}'\n")

    results = []

    for i, p in enumerate(prospects, 1):
        print(f"[{i}/{len(prospects)}] {p['name']} @ {p.get('company', '?')}")

        email = p.get("email")
        contact_name = p["name"]
        contact_role = p.get("role", "")
        company = p.get("company", "Unknown")
        tech_stack: list[str] = []
        domain: Optional[str] = None

        # ── Enrichment ──
        if not skip_enrichment:
            # Try to extract domain from notes or github URL
            notes = p.get("notes") or ""
            github = p.get("github") or ""
            domain = extract_domain(notes) or extract_domain(github)

            # Tech stack detection
            if domain:
                print(f"  → tech stack: {domain}")
                tech_stack = get_tech_stack(f"https://{domain}")
                if tech_stack:
                    print(f"  ✓ detected: {', '.join(tech_stack[:5])}")
                    # Append tech to notes in DB
                    new_notes = f"{notes}\ntech_stack: {', '.join(tech_stack)}".strip()
                    if not dry_run:
                        update_prospect_notes(db, p["id"], new_notes)

            # Email finding
            if not email and domain and hunter_key:
                print(f"  → email search: {domain}")
                found = find_email_hunter(domain, hunter_key)
                if found:
                    email, contact_name_found, contact_role_found = found
                    # Use found name/role if we don't have better data
                    if not p["name"] or p["name"] == contact_name:
                        contact_name = contact_name_found or contact_name
                    if not contact_role:
                        contact_role = contact_role_found
                    print(f"  ✓ email: {email} ({contact_role})")
                    if not dry_run:
                        update_prospect_email(db, p["id"], email)
                else:
                    print(f"  ✗ no email found")

        if not email:
            print(f"  ⚠ no email — skipping outreach generation")
            results.append({"prospect": p["name"], "company": company, "status": "skipped_no_email"})
            continue

        # ── Outreach generation ──
        signal = infer_signal(p, tech_stack)
        print(f"  → signal: {signal}")

        if dry_run:
            print(f"  [dry-run] would generate outreach for {contact_name} <{email}>")
            results.append({"prospect": contact_name, "company": company, "status": "dry_run"})
            continue

        try:
            result = outreach_agent.generate_outreach(
                company_name=company,
                contact_name=contact_name,
                contact_role=contact_role,
                contact_email=email,
                tech_stack=tech_stack,
                signal=signal,
            )
            outreach_agent.print_outreach(result)

            # Log to DB
            log_outreach(db, p["id"], "email", result.get("email", ""))
            if result.get("linkedin_message"):
                log_outreach(db, p["id"], "linkedin", result["linkedin_message"])

            # Advance status
            update_prospect_status(db, p["id"], "researched")
            results.append({"prospect": contact_name, "company": company, "email": email, "status": "done"})

        except Exception as e:
            print(f"  ✗ outreach error: {e}")
            results.append({"prospect": p["name"], "company": company, "status": f"error: {e}"})

        # Rate limit — avoid hammering APIs
        time.sleep(2)

    # ── Summary ──
    db.close()
    print("\n" + "─" * 60)
    print(f"SUMMARY — {len(results)} processed")
    done = [r for r in results if r["status"] == "done"]
    skipped = [r for r in results if "skipped" in r["status"]]
    errors = [r for r in results if "error" in r["status"]]
    print(f"  ✓ outreach generated: {len(done)}")
    print(f"  ⚠ skipped (no email):  {len(skipped)}")
    print(f"  ✗ errors:              {len(errors)}")
    print(f"\nOutputs saved → agents/output/emails/")
    print(f"Prospects updated → status='researched' in {db_path}")
    if skipped:
        print(f"\nProspects needing manual email:")
        for r in skipped:
            print(f"  - {r['prospect']} @ {r['company']}")
    print("─" * 60)
