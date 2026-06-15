"""
Lead Sourcer — finds Track B companies (non-technical, AI-hungry) to classify.

Free sources:
  UK Companies House  → search by SIC code (wealth, legal, real estate)
  FCA Register        → UK wealth managers, financial advisors
  DuckDuckGo/Bing     → sector + region searches
  Google Maps API     → local business search by category + city (needs key)

Saves discovered companies directly to SQLite prospects DB (status='new', source='track_b_lead')
so they flow into classifier automatically.
"""

import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

DB_PATH = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))

# UK Companies House SIC codes → high-value non-technical sectors
UK_SIC_CODES = {
    "64205": "Activities of financial holding companies",
    "64301": "Activities of investment trusts",
    "64302": "Activities of unit trusts",
    "64910": "Financial leasing",
    "64992": "Family offices / other financial service activities",
    "66110": "Administration of financial markets",
    "66190": "Other activities auxiliary to financial services",
    "68100": "Buying and selling of own real estate",
    "68201": "Renting and operating of Housing Association real estate",
    "68209": "Other letting and operating of own or leased real estate",
    "68310": "Real estate agencies",
    "68320": "Management of real estate",
    "69101": "Barristers at law",
    "69102": "Solicitors",
    "69109": "Activities of law offices NEC",
    "70100": "Activities of head offices",
    "70221": "Financial management",
    "70229": "Management consultancy activities NEC",
    "82110": "Combined office administrative service activities",
}

# Sectors for DuckDuckGo search
SEARCH_SECTORS = [
    "family office",
    "private wealth management",
    "asset management",
    "investment management",
    "property management",
    "real estate investment",
    "private equity",
    "estate management",
    "law firm",
    "solicitors",
    "logistics company",
    "freight forwarding",
    "agricultural estate",
    "hospitality management",
]

# Cities / regions per country
TARGET_CITIES = {
    "UK": ["London", "Manchester", "Edinburgh", "Birmingham", "Bristol", "Leeds", "Oxford", "Cambridge"],
    "UAE": ["Dubai", "Abu Dhabi", "Sharjah"],
    "Switzerland": ["Geneva", "Zurich", "Basel", "Lugano"],
    "Singapore": ["Singapore"],
    "Germany": ["Frankfurt", "Munich", "Hamburg", "Berlin", "Düsseldorf"],
    "Netherlands": ["Amsterdam", "Rotterdam", "The Hague", "Utrecht"],
}


# ── UK Companies House source ─────────────────────────────────────────────────

def search_uk_by_sic(sic_code: str, limit: int = 20) -> list[dict]:
    """Search UK Companies House for active companies with given SIC code."""
    key = os.environ.get("UK_CH_API_KEY", "")
    if not key:
        return []

    import base64
    token = base64.b64encode(f"{key}:".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    try:
        resp = requests.get(
            "https://api.company-information.service.gov.uk/advanced-search/companies",
            params={
                "sic_codes": sic_code,
                "company_status": "active",
                "size": limit,
            },
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("items", [])
        return [
            {
                "company": i.get("company_name", ""),
                "location": f"{i.get('registered_office_address', {}).get('postal_code', '')} UK",
                "source": "uk_companies_house",
                "notes": f"SIC:{sic_code} sector:{UK_SIC_CODES.get(sic_code, 'unknown')} website: cn:{i.get('company_number','')}",
                "sector": UK_SIC_CODES.get(sic_code, "unknown"),
            }
            for i in items
            if i.get("company_name")
        ]
    except Exception as e:
        print(f"  [CH SIC {sic_code}] error: {e}")
        return []


def source_uk_companies_house(limit_per_sic: int = 10) -> list[dict]:
    """Scan key SIC codes for wealth/legal/property firms."""
    leads = []
    for sic, sector in UK_SIC_CODES.items():
        batch = search_uk_by_sic(sic, limit=limit_per_sic)
        if batch:
            print(f"  [CH] SIC {sic} ({sector}): {len(batch)} companies")
        leads.extend(batch)
        time.sleep(0.3)  # rate limit: 600 req/5min
    return leads


# ── UK FCA Register source ────────────────────────────────────────────────────

def source_fca_register(limit: int = 50) -> list[dict]:
    """FCA Financial Services Register — wealth managers, IFAs, asset managers."""
    try:
        resp = requests.get(
            "https://register.fca.org.uk/services/V0.1/Firms",
            params={
                "q": "wealth management",
                "type": "Firm",
                "status": "Authorised",
                "page": 1,
                "per_page": min(limit, 50),
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        firms = data.get("Data", [])
        return [
            {
                "company": f.get("Organisation Name", ""),
                "location": f"{f.get('Town', '')} UK",
                "source": "fca_register",
                "notes": f"FCA authorised wealth manager. FCA ref:{f.get('FRN','')} website: ",
                "sector": "wealth management / financial services",
            }
            for f in firms
            if f.get("Organisation Name")
        ]
    except Exception as e:
        print(f"  [FCA] error: {e}")
        return []


# ── DuckDuckGo search source ──────────────────────────────────────────────────

def search_ddg(query: str, limit: int = 10) -> list[dict]:
    """DuckDuckGo Instant Answer API — free, no key needed."""
    leads = []
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=10,
        )
        data = resp.json()
        # RelatedTopics → company names
        topics = data.get("RelatedTopics", [])[:limit]
        for t in topics:
            text = t.get("Text", "")
            url = t.get("FirstURL", "")
            if text and len(text) > 10:
                company = text.split(" - ")[0].strip()[:80]
                if company:
                    leads.append({
                        "company": company,
                        "location": _extract_location_from_query(query),
                        "source": "ddg_search",
                        "notes": f"query:{query} website:{url}",
                        "sector": _query_to_sector(query),
                    })
    except Exception:
        pass
    return leads


def source_ddg_batch(sectors: Optional[list[str]] = None, cities: Optional[list[str]] = None,
                     limit_per_query: int = 5) -> list[dict]:
    """Run DuckDuckGo searches across sector × city combinations."""
    sectors = sectors or SEARCH_SECTORS[:6]
    cities = cities or ["London", "Singapore", "Dubai", "Zurich"]
    leads = []
    for city in cities:
        for sector in sectors:
            query = f"{sector} firm {city}"
            batch = search_ddg(query, limit=limit_per_query)
            if batch:
                print(f"  [DDG] '{query}': {len(batch)} results")
            leads.extend(batch)
            time.sleep(1)  # be kind to DDG
    return leads


# ── Google Maps source (optional) ─────────────────────────────────────────────

def source_google_maps(keyword: str, city: str, limit: int = 20) -> list[dict]:
    """Google Maps Places API — requires GOOGLE_MAPS_API_KEY."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return []
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": f"{keyword} {city}", "key": key},
            timeout=15,
        )
        places = resp.json().get("results", [])[:limit]
        return [
            {
                "company": p.get("name", ""),
                "location": f"{p.get('formatted_address', city)}",
                "source": "google_maps",
                "notes": f"keyword:{keyword} website: rating:{p.get('rating','')}",
                "sector": keyword,
            }
            for p in places if p.get("name")
        ]
    except Exception as e:
        print(f"  [GMaps] error: {e}")
        return []


# ── DB write ──────────────────────────────────────────────────────────────────

def save_leads_to_db(leads: list[dict], dry_run: bool = False) -> int:
    """Insert discovered leads into prospects DB (skip duplicates)."""
    if dry_run:
        for lead in leads:
            print(f"  [DRY RUN] {lead['company']} | {lead['location']} | {lead['sector']}")
        return len(leads)

    if not DB_PATH.exists():
        print(f"  [DB] Not found at {DB_PATH} — run `bash setup.sh` first")
        return 0

    db = sqlite3.connect(str(DB_PATH))
    inserted = 0
    for lead in leads:
        company = lead.get("company", "").strip()
        if not company or len(company) < 3:
            continue
        # Skip duplicates
        exists = db.execute(
            "SELECT 1 FROM prospects WHERE company=? OR name=?", (company, company)
        ).fetchone()
        if exists:
            continue
        db.execute(
            """INSERT INTO prospects (name, company, location, notes, source, outreach_status, created_at)
               VALUES (?, ?, ?, ?, ?, 'new', ?)""",
            (
                company,
                company,
                lead.get("location", ""),
                lead.get("notes", ""),
                f"lead_sourcer:{lead.get('source','')}",
                datetime.now().isoformat(),
            ),
        )
        inserted += 1
    db.commit()
    db.close()
    return inserted


# ── Main entry ────────────────────────────────────────────────────────────────

def source_leads(
    sources: list[str] = None,
    sectors: list[str] = None,
    cities: list[str] = None,
    limit: int = 50,
    dry_run: bool = False,
) -> list[dict]:
    """
    Run all or selected sources, deduplicate, save to DB.

    sources: ["uk_ch", "fca", "ddg", "gmaps"] — default all available
    """
    sources = sources or ["uk_ch", "fca", "ddg"]
    all_leads = []

    if "uk_ch" in sources:
        print("\n[Source: UK Companies House]")
        leads = source_uk_companies_house(limit_per_sic=max(5, limit // len(UK_SIC_CODES)))
        print(f"  → {len(leads)} companies found")
        all_leads.extend(leads)

    if "fca" in sources:
        print("\n[Source: FCA Register]")
        leads = source_fca_register(limit=min(limit, 50))
        print(f"  → {len(leads)} firms found")
        all_leads.extend(leads)

    if "ddg" in sources:
        print("\n[Source: DuckDuckGo search]")
        leads = source_ddg_batch(sectors=sectors, cities=cities, limit_per_query=5)
        print(f"  → {len(leads)} results found")
        all_leads.extend(leads)

    if "gmaps" in sources:
        print("\n[Source: Google Maps]")
        for sector in (sectors or SEARCH_SECTORS[:3]):
            for city in (cities or ["London", "Singapore"]):
                batch = source_google_maps(sector, city, limit=10)
                all_leads.extend(batch)
                time.sleep(0.5)
        print(f"  → {len(all_leads)} places found")

    # Deduplicate by company name
    seen = set()
    unique = []
    for lead in all_leads:
        key = lead["company"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(lead)

    print(f"\n  Unique leads: {len(unique)} (from {len(all_leads)} raw)")

    inserted = save_leads_to_db(unique, dry_run=dry_run)
    if not dry_run:
        print(f"  Saved to DB: {inserted} new prospects")

    return unique


def _extract_location_from_query(query: str) -> str:
    for city_list in TARGET_CITIES.values():
        for city in city_list:
            if city.lower() in query.lower():
                return city
    return ""


def _query_to_sector(query: str) -> str:
    for s in SEARCH_SECTORS:
        if s in query.lower():
            return s
    return "unknown"
