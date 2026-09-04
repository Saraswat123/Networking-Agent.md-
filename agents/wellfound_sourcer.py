"""
Wellfound Sourcer — finds non-technical founders looking for a technical
co-founder / founding engineer / CTO, for track_a_custom_build.py.

wellfound.com blocks direct scraping (Cloudflare, 403 on WebFetch/requests),
so this goes through DDGS (search engine index) instead — same DDGS fallback
pattern as track_b_sourcer.py. Search engines index Wellfound listing titles
fine even though the site itself can't be fetched directly.

Listings give company + role title only, never a founder's real name or email
— those must be resolved manually (WebSearch the company → LinkedIn/website)
before any outreach is generated or sent. Never invent a name.

Output: inserted into custom_build_prospects DB (source='wellfound_sourcer',
status='new'), name field holds the company name as a placeholder until the
real founder name is resolved.
"""
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

DB_PATH = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))

QUERY_TERMS = [
    "solo founder technical cofounder",
    "non-technical founder cofounder",
    "idea stage technical cofounder",
    "pre-seed cofounder no equity salary",
]

# Job titles that read like "<Role> at <Company>" or "<Role> | <Company>"
TITLE_PATTERNS = [
    re.compile(r"^(.*?)\s+at\s+([A-Za-z0-9&.,\'\- ]+?)\s*[•\|]", re.I),
    re.compile(r"^(.*?)\s+at\s+([A-Za-z0-9&.,\'\- ]+)$", re.I),
]

SKIP_DOMAINS = ("wellfound.com/role", "wellfound.com/jobs/applications")


def _parse_title(title: str) -> tuple[str, str]:
    """Returns (role, company) parsed from a Wellfound job title, or ("", "")."""
    for pat in TITLE_PATTERNS:
        m = pat.match(title)
        if m:
            role = m.group(1).strip(" -|")
            company = m.group(2).strip(" -|")
            return role, company
    return "", ""


def source_wellfound(limit_per_term: int = 15, save: bool = True) -> dict:
    if DDGS is None:
        print("  [wellfound] DDGS not installed — pip install ddgs")
        return {"found": 0, "inserted": 0}

    conn = sqlite3.connect(DB_PATH) if save else None
    found = []
    seen_companies = set()

    for term in QUERY_TERMS:
        query = f"site:wellfound.com {term}"
        print(f"[source] {term} (wellfound)...")
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit_per_term))
        except Exception as e:
            print(f"  [ddgs] error: {e}")
            continue

        for r in results:
            url = r.get("href", "") or r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("body", "") or r.get("description", "")
            if "wellfound.com" not in url:
                continue
            if "/role/" in url or "/company/" in url and "/jobs/" not in url:
                # role-listing index pages and bare company pages, not a posting
                if "/jobs/" not in url:
                    continue

            role, company = _parse_title(title)
            if not company:
                continue
            key = company.lower().strip()
            if key in seen_companies:
                continue
            seen_companies.add(key)
            found.append({
                "role": role or term,
                "company": company,
                "url": url,
                "snippet": snippet,
            })
        time.sleep(1)

    print(f"\n[source] Found {len(found)} unique companies.")

    inserted = 0
    if save and conn:
        for f in found:
            exists = conn.execute(
                "SELECT id FROM custom_build_prospects WHERE company=? AND source='wellfound_sourcer'",
                (f["company"],),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO custom_build_prospects
                   (name, role, company, country, linkedin_url, idea, problem, source, status, created_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'wellfound_sourcer', 'new', datetime('now'), ?)""",
                (f["company"], f["role"], f["company"], "", f["url"], f["snippet"], f["snippet"],
                 "NAME IS PLACEHOLDER (=company) — resolve real founder name before outreach"),
            )
            inserted += 1
        conn.commit()
        conn.close()

    print(f"[source] Inserted: {inserted} | Dupes skipped: {len(found) - inserted}")
    return {"found": len(found), "inserted": inserted, "rows": found}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source_wellfound(limit_per_term=args.limit, save=not args.dry_run)
