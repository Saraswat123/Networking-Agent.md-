"""
Phase 4 Orchestrator — full pipeline in one command.

Discovery → Save to DB → Enrich → Generate Outreach

Calls same APIs as the Rust MCP tools (GitHub, YC, WebReveal, Hunter.io)
but runs autonomously without requiring Claude as the MCP client.
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

import prospect_bridge

GITHUB_API = "https://api.github.com"
YC_API = "https://api.ycombinator.com/v0.1/companies"
DEFAULT_DB = Path.home() / "networking-agent.db"


# ─── GitHub discovery ─────────────────────────────────────────────────────────

def search_github_users(token: str, query: str, location: str, limit: int = 10) -> list[dict]:
    q = f"{query} location:{location}" if location else query
    resp = requests.get(
        f"{GITHUB_API}/search/users",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "networking-agent/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        params={"q": q, "per_page": "30"},
        timeout=15,
    )
    resp.raise_for_status()
    logins = [u["login"] for u in resp.json().get("items", [])[:limit]]

    profiles = []
    for login in logins:
        try:
            p = requests.get(
                f"{GITHUB_API}/users/{login}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "networking-agent/0.1",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            ).json()
            profiles.append(p)
            time.sleep(0.3)  # GitHub rate limit
        except Exception as e:
            print(f"  [github] profile error {login}: {e}")
    return profiles


def search_yc_companies(query: str, location: str, limit: int = 20) -> list[dict]:
    location_lower = location.lower()
    results = []

    for page in range(1, 6):
        params = [("limit", "50"), ("page", str(page))]
        if query:
            params.append(("q", query))
        resp = requests.get(
            YC_API,
            headers={"User-Agent": "networking-agent/0.1"},
            params=params,
            timeout=15,
        )
        data = resp.json().get("companies", [])
        if not data:
            break

        for c in data:
            locs = c.get("locations") or []
            regions = c.get("regions") or []
            all_locs = " ".join(locs + regions).lower()
            if location and location_lower not in all_locs:
                continue
            results.append(c)
            if len(results) >= limit:
                return results

    return results


# ─── DB helpers ───────────────────────────────────────────────────────────────

def ensure_db(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS prospects (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            github          TEXT UNIQUE,
            email           TEXT,
            company         TEXT,
            role            TEXT,
            location        TEXT,
            notes           TEXT,
            source          TEXT,
            outreach_status TEXT DEFAULT 'new',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS outreach_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id     INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
            channel         TEXT NOT NULL,
            message         TEXT,
            sent_at         DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    return db


def save_prospect(db: sqlite3.Connection, name: str, github: Optional[str],
                  email: Optional[str], company: Optional[str], role: Optional[str],
                  location: Optional[str], notes: Optional[str], source: str) -> bool:
    """Returns True if inserted (new), False if already existed."""
    try:
        db.execute(
            """
            INSERT INTO prospects (name, github, email, company, role, location, notes, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(github) DO UPDATE SET
                email    = COALESCE(excluded.email, email),
                company  = COALESCE(excluded.company, company),
                notes    = COALESCE(excluded.notes, notes)
            """,
            (name, github, email, company, role, location, notes, source),
        )
        db.commit()
        return db.execute("SELECT changes()").fetchone()[0] > 0
    except Exception as e:
        print(f"  [db] save error: {e}")
        return False


# ─── Main orchestrator ────────────────────────────────────────────────────────

def run(
    mode: str,            # "github" | "yc" | "both"
    query: str,
    location: str,
    limit: int = 10,
    run_bridge: bool = True,
    dry_run: bool = False,
    bridge_limit: int = 20,
) -> None:
    github_token = os.environ.get("GITHUB_TOKEN", "")
    db_path = Path(os.environ.get("NETWORKING_DB", str(DEFAULT_DB)))

    db = ensure_db(db_path)
    new_count = 0

    # ── Discovery ──
    if mode in ("github", "both"):
        if not github_token:
            print("⚠ GITHUB_TOKEN not set — skipping GitHub search")
        else:
            print(f"\n[GitHub] searching: '{query}' in '{location}'")
            try:
                users = search_github_users(github_token, query, location, limit)
                print(f"  found {len(users)} profiles")
                for u in users:
                    name = u.get("name") or u.get("login", "")
                    github_url = u.get("html_url")
                    company = (u.get("company") or "").strip().lstrip("@")
                    role_guess = "Engineer"
                    blog = u.get("blog") or ""
                    notes = f"followers: {u.get('followers', 0)}, repos: {u.get('public_repos', 0)}"
                    if blog:
                        notes += f", blog: {blog}"

                    inserted = save_prospect(
                        db, name, github_url, u.get("email"),
                        company or None, role_guess,
                        u.get("location"), notes, "github"
                    )
                    status = "+" if inserted else "~"
                    print(f"  {status} {name} @ {company or '?'}")
                    if inserted:
                        new_count += 1
            except Exception as e:
                print(f"  [github] search error: {e}")

    if mode in ("yc", "both"):
        print(f"\n[YC] searching: '{query}' in '{location}'")
        try:
            companies = search_yc_companies(query, location, limit)
            print(f"  found {len(companies)} companies")
            for c in companies:
                name = c.get("name", "")
                website = c.get("website") or c.get("url") or ""
                description = c.get("oneLiner") or c.get("one_liner") or ""
                batch = c.get("batch", "")
                tags = ", ".join(c.get("tags") or [])
                notes = f"batch: {batch}, tags: {tags}, website: {website}, desc: {description[:120]}"

                inserted = save_prospect(
                    db, name, None, None,
                    name, "Founder/CTO",
                    ", ".join(c.get("locations") or []),
                    notes, "yc"
                )
                status = "+" if inserted else "~"
                print(f"  {status} {name} ({batch})")
                if inserted:
                    new_count += 1
        except Exception as e:
            print(f"  [yc] search error: {e}")

    db.close()

    print(f"\n── Discovery complete: {new_count} new prospects saved to {db_path}")

    # ── Bridge pipeline ──
    if run_bridge and new_count > 0:
        print(f"\n── Running outreach pipeline for new prospects...\n")
        prospect_bridge.run_bridge(
            status_filter="new",
            limit=min(bridge_limit, new_count + 5),
            dry_run=dry_run,
        )
    elif run_bridge and new_count == 0:
        print("── No new prospects — skipping outreach generation")
    else:
        print("── Bridge skipped (--no-bridge flag)")
