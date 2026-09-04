"""
Track B Sourcer — bulk discovery of non-technical, AI-hungry companies.

Replaces manual company picking (the 6 hand-built in run_track_b_outreach.py)
with automated discovery feeding straight into classifier_agent.classify_batch().

Two discovery paths:
  UK:     Companies House Advanced Search by SIC code (needs UK_CH_API_KEY)
          Falls back to DDGS if no key set.
  Global: DDGS search per sector+country — no API key needed, works everywhere
          in classifier_agent.TARGET_REGIONS.

Website resolution: Companies House gives no website field, so every company
is run through a DDGS lookup to find its real domain (skip social/wiki/directory
domains). Required because classifier_agent.extract_website_from_prospect()
reads website: token from prospect notes.

Output: inserted into prospects DB (source='trackb_sourcer', outreach_status='new')
        ready for: python cli.py classify --mode db --limit N
"""
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import companies_house

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

DB_PATH = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))

# Sectors → DDGS query fragments (used both as UK fallback and global discovery)
SECTOR_QUERY_TERMS = {
    "wealth":        "wealth management firm",
    "family_office": "family office",
    "real_estate":   "real estate consultancy property management firm",
    "legal":         "law firm",
    "accounting":    "accounting firm advisory",
    "consulting":    "management consulting firm",
    "logistics":     "logistics freight company",
    "recruitment":   "recruitment agency",
}

# Curated worldwide list — major wealth/business hubs across every region in
# classifier_agent.TARGET_REGIONS, deduped to one canonical name per country.
WORLDWIDE_COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Australia", "New Zealand",
    "Germany", "France", "Netherlands", "Switzerland", "Sweden", "Norway",
    "Denmark", "Finland", "Belgium", "Ireland", "Luxembourg", "Spain", "Italy",
    "UAE", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain",
    "Singapore", "Hong Kong", "Japan", "South Korea", "Taiwan", "Malaysia",
    "India", "Brazil", "Mexico", "Chile", "South Africa",
]

SKIP_DOMAINS = [
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "wikipedia.org", "crunchbase.com", "bloomberg.com", "glassdoor.com",
    "indeed.com", "youtube.com", "yelp.com", "tripadvisor.com",
    "companieshouse.gov.uk", "company-information.service.gov.uk",
    "google.com", "bing.com", "duckduckgo.com", "zoominfo.com",
]


# ── UK discovery ──────────────────────────────────────────────────────────────
def fetch_uk_by_sector(sector: str, limit: int = 30, min_age_years: int = 3) -> list[dict]:
    """
    UK companies by sector. Uses Companies House SIC search if key set,
    else DDGS fallback. min_age_years filters out shell/inactive-looking new cos.
    """
    sic_codes = companies_house.SECTOR_SIC_MAP.get(sector, [])
    has_key = bool(os.environ.get("UK_CH_API_KEY", ""))

    results = []
    if has_key and sic_codes:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=min_age_years * 365)).strftime("%Y-%m-%d")
        # incorporated_from in CH means "from this date onward" — we want OLDER than cutoff,
        # so we don't pass it as a lower bound; instead post-filter by age.
        seen_names = set()
        for sic in sic_codes:
            companies = companies_house.search_by_sic(sic, limit=limit)
            for c in companies:
                name = c.get("name", "")
                if not name or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())
                age = companies_house._years_since(c.get("incorporated"))
                if age is not None and age < min_age_years:
                    continue
                results.append({
                    "name": name,
                    "company": name,
                    "location": f"{c.get('locality','')}, UK".strip(", "),
                    "sector": sector,
                    "country": "UK",
                    "ch_url": c.get("ch_url", ""),
                    "incorporated": c.get("incorporated", ""),
                    "source": "trackb_sourcer_ch",
                })
            time.sleep(0.3)
            if len(results) >= limit:
                break
        return results[:limit]

    # Fallback: DDGS
    print(f"  [uk:{sector}] no UK_CH_API_KEY — using DDGS fallback")
    return fetch_global_by_sector(sector, "United Kingdom", limit)


def _ddgs_text_retry(ddgs, query: str, max_results: int, retries: int = 3) -> list[dict]:
    """
    DDGS (no API key, scrapes search backends) fails *silently* under rate-limiting —
    returns an empty list instead of raising. A single empty result is therefore not
    trustworthy; retry with backoff before treating it as "no results."
    """
    for attempt in range(retries):
        try:
            results = list(ddgs.text(query, max_results=max_results))
            if results:
                return results
        except Exception as e:
            print(f"    [ddgs] attempt {attempt+1}/{retries} error: {e}")
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    return []


# ── Global discovery (DDGS) ───────────────────────────────────────────────────
def fetch_global_by_sector(sector: str, country: str, limit: int = 20) -> list[dict]:
    """
    DDGS search for individual companies in sector+country. No API key needed.

    Targets LinkedIn company pages — each result is exactly one named company
    (per classifier.md's documented manual-research pattern), not a ranking/
    directory page. Website resolved separately in save_to_db() via find_website(),
    which excludes LinkedIn/social/directory domains.
    """
    if DDGS is None:
        print("  pip install ddgs")
        return []

    term = SECTOR_QUERY_TERMS.get(sector, sector)
    queries = [
        f'"{term}" "{country}" site:linkedin.com/company',
        f'"{term}" company "{country}" -site:linkedin.com -site:wikipedia.org -inurl:rankings -inurl:best',
    ]

    results = []
    seen_names = set()
    try:
        with DDGS() as ddgs:
            for q in queries:
                if len(results) >= limit:
                    break
                hits = _ddgs_text_retry(ddgs, q, max_results=limit * 2)
                if not hits:
                    print(f"    [ddgs:{sector}:{country}] no results after retries: {q[:60]}")
                for r in hits:
                    title = r.get("title", "")
                    href  = r.get("href", "")
                    body  = r.get("body", "")

                    name = _clean_company_name(title)
                    if not name or len(name) < 3 or name.lower() in seen_names:
                        continue
                    # Skip generic directory/ranking titles that slipped through
                    if any(bad in name.lower() for bad in ["top ", "best ", "ranking", "list of"]):
                        continue
                    seen_names.add(name.lower())

                    domain = _extract_domain(href)
                    is_linkedin = domain and "linkedin.com" in domain

                    results.append({
                        "name":     name,
                        "company":  name,
                        "location": country,
                        "sector":   sector,
                        "country":  country,
                        "website":  "" if is_linkedin else (domain or ""),
                        "snippet":  body[:200],
                        "source":   "trackb_sourcer_ddgs",
                    })
                    if len(results) >= limit:
                        break
                time.sleep(1)
    except Exception as e:
        print(f"  [ddgs:{sector}:{country}] error: {e}")

    return results


def find_website(company_name: str, country: str = "") -> Optional[str]:
    """DDGS lookup for a company's real domain — skips social/directory sites."""
    if DDGS is None:
        return None
    query = f'"{company_name}" {country} official website'
    try:
        with DDGS() as ddgs:
            for r in _ddgs_text_retry(ddgs, query, max_results=5):
                domain = _extract_domain(r.get("href", ""))
                if domain and not any(skip in domain for skip in SKIP_DOMAINS):
                    return domain
    except Exception:
        pass
    return None


def _extract_domain(url: str) -> Optional[str]:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else None


def _clean_company_name(title: str) -> str:
    # Strip common suffixes DDGS titles append: " | Home", " - LinkedIn", etc.
    name = re.split(r"\s*[|\-–]\s*(?:Home|LinkedIn|Official|Welcome)", title, flags=re.I)[0]
    return name.strip()[:80]


# ── DB persistence ────────────────────────────────────────────────────────────
def save_to_db(prospects: list[dict], db_path: Path = DB_PATH, resolve_websites: bool = True) -> int:
    """
    Insert sourced companies into prospects DB. Dedupes by company name (case-insensitive).
    Resolves missing websites via DDGS before insert (needed for classifier).
    Returns count of new rows inserted.
    """
    if not db_path.exists():
        print(f"DB not found: {db_path} — run setup.sh first")
        return 0

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    existing = {
        row["company"].lower()
        for row in con.execute("SELECT company FROM prospects WHERE company IS NOT NULL")
        if row["company"]
    }

    inserted = 0
    for p in prospects:
        name = p.get("company") or p.get("name", "")
        if not name or name.lower() in existing:
            continue

        website = p.get("website", "")
        if resolve_websites and not website:
            website = find_website(name, p.get("country", "")) or ""
            time.sleep(0.5)

        notes_parts = []
        if website:
            notes_parts.append(f"website:{website}")
        if p.get("sector"):
            notes_parts.append(f"sector:{p['sector']}")
        if p.get("country"):
            notes_parts.append(f"country:{p['country']}")
        if p.get("ch_url"):
            notes_parts.append(f"ch:{p['ch_url']}")
        if p.get("incorporated"):
            notes_parts.append(f"incorporated:{p['incorporated']}")

        con.execute(
            "INSERT INTO prospects (name, company, location, notes, source, outreach_status) "
            "VALUES (?, ?, ?, ?, ?, 'new')",
            (name, name, p.get("location", p.get("country", "")), " ".join(notes_parts),
             p.get("source", "trackb_sourcer")),
        )
        existing.add(name.lower())
        inserted += 1

    con.commit()
    con.close()
    return inserted


# ── Orchestration ─────────────────────────────────────────────────────────────
def source_track_b(
    sectors: list[str],
    countries: list[str],
    limit_per_combo: int = 15,
    save: bool = True,
) -> dict:
    """
    Run discovery across sector × country combos. UK uses Companies House
    (or DDGS fallback); all other countries use DDGS.
    """
    if any(c.strip().lower() == "worldwide" for c in countries):
        countries = WORLDWIDE_COUNTRIES

    all_results = []
    for sector in sectors:
        for country in countries:
            print(f"[source] {sector} × {country}...")
            if country.lower() in ("uk", "united kingdom", "gb"):
                results = fetch_uk_by_sector(sector, limit=limit_per_combo)
            else:
                results = fetch_global_by_sector(sector, country, limit=limit_per_combo)
            print(f"  → {len(results)} found")
            all_results.extend(results)
            time.sleep(1)

    inserted = 0
    if save and all_results:
        print(f"\n[source] Resolving websites + saving {len(all_results)} candidates...")
        inserted = save_to_db(all_results)

    return {
        "found": len(all_results),
        "inserted": inserted,
        "skipped_duplicate": len(all_results) - inserted,
        "results": all_results,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sectors", default="wealth,legal,real_estate", help="Comma-separated")
    parser.add_argument("--countries", default="UK", help="Comma-separated")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sectors   = [s.strip() for s in args.sectors.split(",")]
    countries = [c.strip() for c in args.countries.split(",")]

    summary = source_track_b(sectors, countries, limit_per_combo=args.limit, save=not args.dry_run)
    print(f"\n{'='*50}")
    print(f"Found: {summary['found']} | Inserted: {summary['inserted']} | Dupes skipped: {summary['skipped_duplicate']}")
    print(f"{'='*50}")
    if args.dry_run:
        for r in summary["results"][:20]:
            print(f"  {r['company']:<35} [{r['sector']}] {r.get('location','?')}")
