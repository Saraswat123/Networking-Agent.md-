"""Contact Finder — discover CEOs/CTOs/VCs/Angel Investors at small orgs (1-50 employees)
in USA + Europe. Find emails via Hunter.io + pattern fallback.
Routes each contact to:
  Track A — if technical org with likely open role (protocol, AI, data, rust)
  Track B — if non-technical org wanting AI/automation (legal, wealth, logistics, etc.)

CLI:
  python cli.py contact-find --region usa --roles "CEO,CTO" --limit 50
  python cli.py contact-route --pending
  python cli.py contact-list
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests

DB_PATH = Path(os.environ.get("NETWORKING_DB", Path.home() / "networking-agent.db"))
OUTPUT_DIR = Path(__file__).parent / "output" / "contacts"
VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")

HUNTER_KEY = os.environ.get("HUNTER_API_KEY", "")

# Target roles — titles to search for
TARGET_ROLES = [
    # Family office + wealth
    "CEO", "Managing Director", "Chief Investment Officer",
    "Head of Operations", "Founder", "Principal",
    # HNI / private investor
    "Angel Investor", "Private Investor", "Co-Founder",
    # Endowment / foundation
    "Chief Investment Officer", "Head of Investments",
    # Tech founders
    "CTO", "VP Engineering", "Chief Digital Officer",
]

# Regions — keyword expansions for location search
REGIONS = {
    "usa": ["San Francisco", "New York", "Austin", "Boston", "Seattle", "Los Angeles", "Chicago"],
    "europe": ["London", "Berlin", "Amsterdam", "Paris", "Stockholm", "Zurich", "Dublin", "Barcelona"],
    "uk": ["London", "Manchester", "Edinburgh", "Bristol", "Birmingham"],
    "all": ["San Francisco", "New York", "London", "Berlin", "Amsterdam", "Stockholm", "Zurich"],
}

# Sectors that route to Track B (non-technical, want AI automation)
TRACK_B_SECTORS = {
    # Family office + private wealth (primary targets)
    "family office", "single family office", "multi family office",
    "mfo", "sfo", "private wealth", "wealth management",
    "private banking", "asset management", "private equity",
    "investment office", "private investment",
    # Endowments + foundations
    "endowment", "foundation", "charitable trust", "sovereign wealth",
    "institutional investor", "fund of funds",
    # Global houses + operators
    "global house", "investment house", "merchant bank",
    "legal", "law", "solicitor", "barrister", "attorney", "law firm",
    "real estate", "property", "estate agent", "proptech",
    "logistics", "supply chain", "freight", "shipping",
    "recruitment", "staffing", "headhunting",
    "accounting", "audit", "bookkeeping",
    "consulting", "management consulting",
    "insurance", "financial advisory", "family advisory",
}

# Tech keywords — presence routes to Track A
TRACK_A_KEYWORDS = {
    "rust", "protocol", "blockchain", "ethereum", "defi", "layer2",
    "ai", "llm", "machine learning", "agent", "nlp", "inference",
    "distributed systems", "p2p", "mcp", "data engineering",
    "open source", "developer tools", "devtools", "api platform",
    "infrastructure", "cloud", "kubernetes", "mlops",
}

# Email pattern guesses when Hunter.io fails
EMAIL_PATTERNS = [
    "{first}@{domain}",
    "{first}.{last}@{domain}",
    "{first_initial}{last}@{domain}",
    "info@{domain}",
    "contact@{domain}",
    "hello@{domain}",
]


def _ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            company TEXT,
            domain TEXT,
            email TEXT,
            email_confidence TEXT,
            linkedin_url TEXT,
            country TEXT,
            region TEXT,
            team_size INTEGER,
            sector TEXT,
            track TEXT DEFAULT 'unknown',
            source TEXT DEFAULT 'search',
            signal TEXT,
            status TEXT DEFAULT 'new',
            routed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        return urlparse(url).hostname.replace("www.", "") if urlparse(url).hostname else ""
    except Exception:
        return ""


def _hunter_domain_search(domain: str, limit: int = 10) -> list[dict]:
    """Find emails at domain via Hunter.io domain search."""
    if not HUNTER_KEY or not domain:
        return []
    try:
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&limit={limit}&api_key={HUNTER_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])
        return [
            {
                "name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "email": e.get("value", ""),
                "role": e.get("position", ""),
                "confidence": str(e.get("confidence", 0)),
                "linkedin": e.get("linkedin", ""),
            }
            for e in emails
            if e.get("value")
        ]
    except Exception:
        return []


def _hunter_email_finder(first: str, last: str, domain: str) -> dict:
    """Find specific person's email via Hunter.io email finder."""
    if not HUNTER_KEY or not domain or not first:
        return {}
    try:
        url = (
            f"https://api.hunter.io/v2/email-finder?"
            f"domain={domain}&first_name={quote_plus(first)}&last_name={quote_plus(last)}"
            f"&api_key={HUNTER_KEY}"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        d = data.get("data", {})
        if d.get("email"):
            return {
                "email": d["email"],
                "confidence": str(d.get("score", 0)),
                "sources": d.get("sources", []),
            }
    except Exception:
        pass
    return {}


def _guess_email_patterns(first: str, last: str, domain: str) -> list[str]:
    """Generate common email patterns for a person."""
    if not domain or not first:
        return [f"info@{domain}"] if domain else []
    fi = first[0].lower() if first else ""
    first_l = first.lower().replace(" ", "")
    last_l = last.lower().replace(" ", "") if last else ""
    guesses = []
    for pat in EMAIL_PATTERNS:
        try:
            guesses.append(pat.format(
                first=first_l,
                last=last_l,
                first_initial=fi,
                domain=domain,
            ))
        except KeyError:
            pass
    return list(dict.fromkeys(guesses))  # dedup preserving order


def _detect_track(sector: str, description: str) -> str:
    """Route to Track A (tech) or Track B (non-tech/automation)."""
    combined = ((sector or "") + " " + (description or "")).lower()
    # Track B first — non-technical orgs wanting AI
    for kw in TRACK_B_SECTORS:
        if kw in combined:
            return "B"
    # Track A — technical companies
    for kw in TRACK_A_KEYWORDS:
        if kw in combined:
            return "A"
    return "unknown"


def _ddgs_search_contacts(role: str, location: str, limit: int = 20) -> list[dict]:
    """DuckDuckGo search for decision-makers at small orgs."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        query = f'"{role}" "1-50 employees" OR "small team" site:linkedin.com/in {location}'
        results = []
        with DDGS() as ddg:
            for r in ddg.text(query, max_results=limit):
                url = r.get("href", "")
                if "linkedin.com/in/" in url:
                    name = r.get("title", "").split(" | ")[0].split(" - ")[0].strip()
                    snippet = r.get("body", "")
                    results.append({
                        "name": name,
                        "linkedin_url": url.split("?")[0],
                        "snippet": snippet,
                        "role": role,
                        "location": location,
                    })
        return results
    except Exception:
        return []


def _ddgs_company_search(sector: str, location: str, limit: int = 15) -> list[dict]:
    """Find small companies (1-50 employees) in sector + location via DDGS."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        query = f'"{sector}" company "{location}" "1-50 employees" CEO OR CTO OR Founder'
        results = []
        with DDGS() as ddg:
            for r in ddg.text(query, max_results=limit):
                results.append({
                    "company": r.get("title", "").split("|")[0].strip(),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "sector": sector,
                    "location": location,
                })
        return results
    except Exception:
        return []


def _yc_small_teams(limit: int = 30) -> list[dict]:
    """Fetch small YC teams (1-50) from YC API — high-value tech contacts."""
    try:
        url = "https://api.ycombinator.com/v0.1/companies?batch=W25,S24,W24&team_size=1-50&page=1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        companies = resp.json().get("companies", [])[:limit]
        contacts = []
        for co in companies:
            name = co.get("name", "")
            site = co.get("website", "")
            domain = _extract_domain(site)
            contacts.append({
                "company": name,
                "domain": domain,
                "website": site,
                "team_size": co.get("team_size", 0),
                "sector": co.get("one_liner", ""),
                "country": "USA",
                "source": "yc_api",
            })
        return contacts
    except Exception:
        return []


def search_contacts(
    roles: list[str] = None,
    regions: list[str] = None,
    sectors: list[str] = None,
    limit: int = 50,
    include_yc: bool = True,
) -> list[dict]:
    """
    Main search: find CEOs/CTOs/VCs at small orgs in target regions.
    Returns list of raw contact dicts (not yet saved to DB).
    """
    _ensure_table()

    roles = roles or [
        "CEO", "Managing Director", "Chief Investment Officer",
        "Founder", "Head of Operations", "Principal",
    ]
    regions = regions or ["usa", "europe"]
    sectors = sectors or [
        "family office",
        "wealth management",
        "endowment",
        "private equity",
        "law firm",
        "logistics",
        "real estate investment",
        "foundation",
    ]

    contacts = []

    # 1. DDGS LinkedIn search per role + location
    locations = []
    for r in regions:
        locations.extend(REGIONS.get(r.lower(), [r]))
    locations = list(dict.fromkeys(locations))[:8]  # max 8 locations, deduped

    for role in roles[:4]:  # cap roles to avoid rate limits
        for loc in locations[:4]:
            raw = _ddgs_search_contacts(role, loc, limit=10)
            for r in raw:
                contacts.append({
                    "name": r["name"],
                    "role": r["role"],
                    "company": "",
                    "domain": "",
                    "email": "",
                    "linkedin_url": r["linkedin_url"],
                    "country": loc,
                    "region": loc,
                    "team_size": None,
                    "sector": "",
                    "signal": r.get("snippet", "")[:300],
                    "source": "ddgs_linkedin",
                    "track": "unknown",
                })
            time.sleep(0.5)

    # 2. YC small teams (tech Track A)
    if include_yc:
        yc = _yc_small_teams(limit=30)
        for co in yc:
            track = _detect_track(co.get("sector", ""), "ai startup tech")
            contacts.append({
                "name": "",
                "role": "Founder/CEO",
                "company": co["company"],
                "domain": co.get("domain", ""),
                "email": "",
                "linkedin_url": "",
                "country": co.get("country", "USA"),
                "region": "usa",
                "team_size": co.get("team_size"),
                "sector": co.get("sector", ""),
                "signal": co.get("sector", "")[:300],
                "source": "yc_api",
                "track": "A",
            })

    # 3. Company search per sector + location → find domain → Hunter.io emails
    for sector in sectors[:4]:
        for loc in locations[:3]:
            cos = _ddgs_company_search(sector, loc, limit=8)
            for co in cos:
                domain = _extract_domain(co.get("url", ""))
                track = _detect_track(sector, co.get("snippet", ""))
                contacts.append({
                    "name": "",
                    "role": "CEO/CTO/Founder",
                    "company": co.get("company", ""),
                    "domain": domain,
                    "email": "",
                    "linkedin_url": "",
                    "country": loc,
                    "region": loc,
                    "team_size": None,
                    "sector": sector,
                    "signal": co.get("snippet", "")[:300],
                    "source": "ddgs_company",
                    "track": track,
                })
            time.sleep(0.5)

    print(f"  [Contact Finder] {len(contacts)} contacts found")
    return contacts[:limit]


def enrich_with_emails(contacts: list[dict]) -> list[dict]:
    """
    For each contact with a domain, try Hunter.io domain search,
    then email-finder, then pattern guessing.
    """
    enriched = []
    hunter_calls = 0

    for c in contacts:
        domain = c.get("domain", "")
        name = c.get("name", "")

        if not domain and not name:
            enriched.append(c)
            continue

        # Parse first/last from name
        parts = name.strip().split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""

        # Hunter.io domain search (gets multiple people from domain)
        if domain and hunter_calls < 20:  # stay under free tier per session
            domain_results = _hunter_domain_search(domain, limit=5)
            hunter_calls += 1
            if domain_results:
                # Find matching person or take first result
                match = next(
                    (r for r in domain_results if first.lower() in r["name"].lower()),
                    domain_results[0] if domain_results else None,
                )
                if match:
                    c["email"] = match["email"]
                    c["email_confidence"] = match["confidence"]
                    if not c.get("name") and match.get("name"):
                        c["name"] = match["name"]
                    if not c.get("role") and match.get("role"):
                        c["role"] = match["role"]
                    if not c.get("linkedin_url") and match.get("linkedin"):
                        c["linkedin_url"] = match["linkedin"]
                    enriched.append(c)
                    continue
            time.sleep(0.3)

        # Hunter.io email finder (specific person)
        if domain and first and hunter_calls < 20:
            result = _hunter_email_finder(first, last, domain)
            hunter_calls += 1
            if result.get("email"):
                c["email"] = result["email"]
                c["email_confidence"] = result["confidence"]
                enriched.append(c)
                continue
            time.sleep(0.3)

        # Pattern guessing (no API cost)
        if domain:
            guesses = _guess_email_patterns(first, last, domain)
            if guesses:
                c["email"] = guesses[0]
                c["email_confidence"] = "pattern"
            else:
                c["email_confidence"] = "none"

        enriched.append(c)

    return enriched


def save_contacts(contacts: list[dict], dry_run: bool = False) -> dict:
    """Save contacts to DB. Returns summary."""
    _ensure_table()

    saved = 0
    skipped = 0
    routed_a = 0
    routed_b = 0

    conn = sqlite3.connect(DB_PATH)

    for c in contacts:
        name = c.get("name", "").strip()
        company = c.get("company", "").strip()
        email = c.get("email", "").strip()
        linkedin = c.get("linkedin_url", "").strip()

        # Skip if no identifying info
        if not name and not company:
            skipped += 1
            continue

        # Dedup: skip if same name+company or same email already in DB
        if email:
            exists = conn.execute(
                "SELECT id FROM contact_leads WHERE email=?", (email,)
            ).fetchone()
            if exists:
                skipped += 1
                continue
        elif name and company:
            exists = conn.execute(
                "SELECT id FROM contact_leads WHERE name=? AND company=?",
                (name, company)
            ).fetchone()
            if exists:
                skipped += 1
                continue
        elif linkedin:
            exists = conn.execute(
                "SELECT id FROM contact_leads WHERE linkedin_url=?", (linkedin,)
            ).fetchone()
            if exists:
                skipped += 1
                continue

        track = c.get("track", "unknown")
        if track == "unknown":
            track = _detect_track(c.get("sector", ""), c.get("signal", ""))

        if dry_run:
            print(f"  [DRY] {name or company:<30} [{track}] {email or c.get('domain','?')}")
            saved += 1
        else:
            conn.execute(
                """INSERT INTO contact_leads
                   (name, role, company, domain, email, email_confidence,
                    linkedin_url, country, region, team_size, sector,
                    track, source, signal, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name,
                    c.get("role", ""),
                    company,
                    c.get("domain", ""),
                    email,
                    c.get("email_confidence", ""),
                    linkedin,
                    c.get("country", ""),
                    c.get("region", ""),
                    c.get("team_size"),
                    c.get("sector", ""),
                    track,
                    c.get("source", "search"),
                    c.get("signal", "")[:300],
                    "new",
                    datetime.now().isoformat(),
                ),
            )
            saved += 1

        if track == "A":
            routed_a += 1
        elif track == "B":
            routed_b += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "saved": saved,
        "skipped": skipped,
        "routed_a": routed_a,
        "routed_b": routed_b,
        "dry_run": dry_run,
    }


def route_pending(dry_run: bool = False) -> dict:
    """
    For contacts with track='unknown', re-detect and route to A or B.
    Contacts routed to A → add to custom_build_prospects (if non-technical founder)
    or just mark as Track A lead.
    Contacts routed to B → add to prospects table (Track B outreach).
    """
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM contact_leads WHERE track='unknown' AND status='new' LIMIT 100"
    ).fetchall()

    routed_a = 0
    routed_b = 0

    for row in rows:
        c = dict(row)
        track = _detect_track(
            c.get("sector") or "",
            (c.get("signal") or "") + " " + (c.get("notes") or ""),
        )

        if track == "unknown":
            continue

        if not dry_run:
            conn.execute(
                "UPDATE contact_leads SET track=?, routed_at=? WHERE id=?",
                (track, datetime.now().isoformat(), c["id"]),
            )

            if track == "B" and c.get("email"):
                # Add to main prospects table for Track B outreach
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO prospects
                           (name, email, company, role, location, notes, source, outreach_status)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            c["name"] or c["company"],
                            c["email"],
                            c["company"],
                            c["role"],
                            c["country"],
                            f"track: B | sector: {c['sector']} | signal: {c['signal'][:100]}",
                            "contact_finder",
                            "new",
                        ),
                    )
                except Exception:
                    pass

            elif track == "A" and c.get("email"):
                # Add to custom_build_prospects if looks like non-tech founder
                role_lower = (c.get("role") or "").lower()
                if any(w in role_lower for w in ["ceo", "founder", "co-founder", "managing director"]):
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO custom_build_prospects
                               (name, role, company, country, email, idea, source, notes)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                c["name"],
                                c["role"],
                                c["company"],
                                c["country"],
                                c["email"],
                                c["signal"][:200],
                                "contact_finder",
                                f"auto-routed | sector: {c['sector']}",
                            ),
                        )
                    except Exception:
                        pass

        if track == "A":
            routed_a += 1
        elif track == "B":
            routed_b += 1
        else:
            continue

        print(f"  → [{track}] {c['name'] or c['company']:<30} {c.get('email','?')}")

    if not dry_run:
        conn.commit()
    conn.close()

    return {"routed_a": routed_a, "routed_b": routed_b, "dry_run": dry_run}


def list_contacts(
    track: str = "",
    status: str = "",
    limit: int = 50,
    fresh_hours: int = 0,
) -> list[dict]:
    """List contacts from DB with optional filters."""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conditions = []
    params = []

    if track:
        conditions.append("track=?")
        params.append(track.upper())
    if status:
        conditions.append("status=?")
        params.append(status)
    if fresh_hours > 0:
        cutoff = (datetime.now() - timedelta(hours=fresh_hours)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM contact_leads {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run_daily_find(
    regions: list[str] = None,
    roles: list[str] = None,
    sectors: list[str] = None,
    limit: int = 50,
    dry_run: bool = False,
) -> dict:
    """
    Full pipeline: search → enrich emails → save → route.
    Run this daily from cli.py contact-find.
    """
    print(f"\n[Contact Finder] Searching {regions or ['usa', 'europe']} | {limit} contacts")

    contacts = search_contacts(
        roles=roles,
        regions=regions,
        sectors=sectors,
        limit=limit,
        include_yc=True,
    )

    print(f"  [Enrich] Finding emails via Hunter.io + pattern guessing...")
    contacts = enrich_with_emails(contacts)

    summary = save_contacts(contacts, dry_run=dry_run)
    print(f"  [Save] saved={summary['saved']} skipped={summary['skipped']} A={summary['routed_a']} B={summary['routed_b']}")

    if not dry_run:
        route = route_pending(dry_run=False)
        print(f"  [Route] A={route['routed_a']} B={route['routed_b']}")
        summary.update({"final_a": route["routed_a"], "final_b": route["routed_b"]})

    # Export fresh contacts to JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fresh = list_contacts(fresh_hours=24, limit=200)
    out = OUTPUT_DIR / f"contacts_{datetime.now().strftime('%Y-%m-%d')}.json"
    out.write_text(json.dumps(fresh, indent=2, default=str))
    print(f"  [Saved] → {out.name}")

    return summary
