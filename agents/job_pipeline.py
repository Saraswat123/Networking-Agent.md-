"""
Track A Job Pipeline — all 5 gaps fixed in one module.

Fixes:
  1. Posting-age filter  — only jobs posted ≤ 7 days (configurable)
  2. Team-size filter    — only companies ≤ 50 people
  3. Obsidian tracking   — auto-write application note on apply
  4. Email finder        — Hunter.io + pattern fallback before portal
  5. Scoring formula     — rank every job before you touch it

Sources:
  - YC API (batch + keyword + team_size)
  - HN "Who Is Hiring" (Firebase API — freshest jobs on the internet)
  - RemoteOK (free, no key)
  - web3.career RSS feed

Usage:
  python cli.py jobs --search "AI automation" --max-age 3 --max-team 30
  python cli.py jobs --source hn --search "rust python" --score-min 8
  python cli.py jobs apply --company Callback --role "AI Engineer" --jd agents/jds/callback.txt
"""

import json
import os
import re
import sys
import time
import sqlite3
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
VAULT_PATH   = Path("/Users/aitsgroup/Documents/Obsidian Vault")
JOBS_DIR     = VAULT_PATH / "Jobs" / "Applications"
DB_PATH      = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
OUTPUT_DIR   = Path(__file__).parent / "output" / "jobs"
JOBS_DB      = Path(__file__).parent / "output" / "jobs" / "jobs.db"
HUNTER_KEY   = os.environ.get("HUNTER_API_KEY", "")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# ── Scoring weights ───────────────────────────────────────────────────────────
def score_job(job: dict) -> int:
    """
    Score a job 0-25. Higher = apply first.

    +3  YC-backed (any batch)
    +3  YC batch W24/S24/W25
    +3  team_size ≤ 15 (founder reads directly)
    +2  team_size 16-50
    +3  recent funding (seed/series A/crunchbase signal)
    +2  tech match (AI/LLM/Python/Rust/Automation/Blockchain)
    +2  founding/special-projects/founders-office role signal
    +2  global/worldwide remote
    +1  UK/EU/AU/NZ remote (less competition)
    +2  posted < 6 hours (first batch)
    +1  posted 6-24 hours
    +1  salary $30-50K USD range (exact sweet spot)
    +1  salary up to $100K (acceptable)
    +2  experience ≤ 2 years explicitly OK
    -2  US-only remote
    -2  team_size > 100
    -3  5+ years required
    -3  no tech match at all
    """
    score = 0
    src   = str(job.get("source", "")).lower()
    batch = str(job.get("batch", "")).upper()
    tech  = str(job.get("tech_stack", "") or "").lower()
    loc   = str(job.get("location", "")).lower()
    title = str(job.get("title", "")).lower()
    desc  = str(job.get("description", "") or "").lower()
    combined = tech + " " + desc + " " + title

    # ── Source / YC ──
    if "yc" in src or "ycombinator" in src or job.get("is_yc"):
        score += 3
    if any(b in batch for b in ["W25", "S24", "W24"]):
        score += 3

    # ── Team size ──
    ts = job.get("team_size")
    if ts:
        try:
            ts = int(ts)
            if ts <= 15:   score += 3
            elif ts <= 50: score += 2
            elif ts > 100: score -= 2
        except Exception:
            pass

    # ── Funding ──
    funding_kws = [
        "seed", "series a", "series b", "recently raised", "backed by",
        "yc funded", "crunchbase", "raised $", "funding round",
        "new funding", "just raised", "freshly funded",
    ]
    if job.get("funded_recently") or any(k in combined for k in funding_kws):
        score += 3

    # ── Tech domain match ──
    tech_kws = [
        "rust", "python", "ai", "llm", "large language model",
        "blockchain", "ethereum", "agent", "automation", "data pipeline",
        "mcp", "protocol", "claude", "openai", "gpt", "gen ai", "generative ai",
        "workflow automation", "agentic", "prompt", "vector", "rag", "embedding",
        "ai infrastructure", "ai engineer", "ml engineer", "llm engineer",
        "fastapi", "postgresql", "asyncio", "langchain", "langgraph",
        "ocr", "document", "etl", "multi-agent",
    ]
    tech_matches = [k for k in tech_kws if k in combined]
    if len(tech_matches) >= 3:
        score += 2
    elif tech_matches:
        score += 1
    else:
        score -= 3

    # Detect tech domain for output label
    domains_matched = []
    from sources.config import TECH_DOMAIN_KEYWORDS
    for domain, kws in TECH_DOMAIN_KEYWORDS.items():
        if any(k in combined for k in kws):
            domains_matched.append(domain)
    job["tech_domains"] = domains_matched

    # ── Founders office / early hire signal ──
    fo_kws = [
        "founder", "special projects", "founding engineer", "early team",
        "0 to 1", "first engineer", "founding team", "chief of staff",
        "ai ops", "founding ai", "early hire", "build from scratch",
    ]
    if any(k in combined for k in fo_kws):
        score += 2

    # ── Location ──
    worldwide_kws = ["worldwide", "global", "anywhere", "international", "remote (global)"]
    low_competition_kws = [
        "united kingdom", "uk remote", "europe", "eu remote", "cet", "cest",
        "australia", "aest", "new zealand", "nzst", "canada",
    ]
    us_only_kws = ["us only", "(us)", "must live in us", "must be us", "united states only"]

    if any(k in loc for k in worldwide_kws) or any(k in combined for k in worldwide_kws):
        score += 2
    elif any(k in loc for k in low_competition_kws):
        score += 1  # less competition than US applicants
    if any(k in loc for k in us_only_kws) or any(k in combined for k in us_only_kws):
        score -= 2

    # ── Posting age (hours) ──
    posted_hrs = job.get("posted_hours_ago")
    posted_days = job.get("posted_days_ago")
    if posted_hrs is not None:
        if posted_hrs < 6:    score += 2   # first batch
        elif posted_hrs < 24: score += 1
    elif posted_days is not None:
        if posted_days < 0.25: score += 2
        elif posted_days < 1:  score += 1

    # ── Salary ──
    try:
        sal_max = int(job.get("salary_max") or 0)
        sal_min = int(job.get("salary_min") or 0)
        if 30_000 <= sal_max <= 50_000:   score += 1   # exact sweet spot
        elif 50_000 < sal_max <= 100_000: score += 1   # acceptable range
    except Exception:
        pass

    # ── Experience ──
    exp_ok = [
        "0-2 year", "1-2 year", "2 year", "2+ year",
        "junior", "entry level", "fresher", "fresh grad", "new grad",
        "0-3 year", "1-3 year", "entry", "associate",
        "no experience required",
    ]
    exp_bad = [
        "5+ year", "5 years", "6+ year", "7+ year", "8+ year", "10+ year",
        "senior only", "staff engineer", "principal engineer", "lead engineer",
    ]
    if any(k in combined for k in exp_ok):
        score += 2
    if any(k in combined for k in exp_bad) or re.search(r"[5-9]\+\s*year", combined):
        score -= 3

    return max(0, score)


# ── Source 1: YC API ──────────────────────────────────────────────────────────
def fetch_yc_jobs(keyword: str, max_team: int = 50, max_age_days: int = 30) -> list[dict]:
    """Fetch YC companies matching keyword, filter by team size."""
    jobs = []
    try:
        r = requests.get(
            "https://api.ycombinator.com/v0.1/companies",
            params={"q": keyword, "limit": 100},
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=10,
        )
        companies = r.json() if isinstance(r.json(), list) else r.json().get("companies", [])
        for c in companies:
            if not isinstance(c, dict):
                continue
            batch = c.get("batch", "")
            if not any(b in str(batch) for b in ["W25", "S24", "W24", "S23", "W23"]):
                continue
            ts = c.get("team_size") or c.get("teamSize")
            if ts:
                try:
                    if int(ts) > max_team:
                        continue
                except Exception:
                    pass
            jobs.append({
                "source":   "yc",
                "is_yc":    True,
                "batch":    batch,
                "company":  c.get("name", ""),
                "title":    "Software Engineer / AI Engineer",
                "location": "Remote (YC company)",
                "website":  c.get("website", ""),
                "one_liner": c.get("one_liner", ""),
                "team_size": ts,
                "description": (c.get("one_liner", "") or "") + " " + keyword,
                "tech_stack": keyword,
                "url":      c.get("website", ""),
                "posted_days_ago": None,
                "salary_min": None,
                "salary_max": None,
            })
    except Exception as e:
        print(f"  [yc] error: {e}")
    return jobs


# ── YC Full Sweep: heavy investment + tiny team ───────────────────────────────
YC_SWEEP_KEYWORDS = [
    # AI / LLM
    "AI", "LLM", "automation", "agent", "generative", "Claude", "OpenAI",
    # Data / Infra
    "data", "pipeline", "infrastructure", "backend", "API",
    # Founders office / ops
    "founders", "operations", "workflow", "productivity",
    # Web3 / protocol
    "blockchain", "ethereum", "protocol", "crypto", "defi",
    # Domain
    "fintech", "edtech", "healthtech", "devtools", "saas",
    # Rust / Python
    "rust", "python",
]

# Funding tiers in YC one-liner / description signals
HEAVY_FUND_SIGNALS = [
    "raised", "funded", "series a", "series b", "seed", "yc backed",
    "backed by", "investment", "$", "million", "m round",
]


def _check_careers_page(website: str, company: str, timeout: int = 6) -> dict:
    """
    Try to find real job listings on company careers page.
    Returns dict with: has_jobs, jobs_url, roles_found, raw_snippet
    """
    if not website:
        return {"has_jobs": False, "jobs_url": "", "roles_found": []}

    base = website.rstrip("/")
    careers_paths = ["/careers", "/jobs", "/hiring", "/join", "/join-us", "/work-with-us"]
    result = {"has_jobs": False, "jobs_url": "", "roles_found": [], "raw_snippet": ""}

    for path in careers_paths:
        url = base + path
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                continue
            text = r.text.lower()
            # Must have some job signal
            if not any(k in text for k in ["engineer", "developer", "position", "opening", "role", "join our team", "hiring"]):
                continue

            # Extract role titles from HTML
            raw = re.sub("<[^>]+>", " ", r.text)
            raw = re.sub(r"\s+", " ", raw)
            role_matches = re.findall(
                r"((?:senior|junior|founding|lead|staff|principal)?\s*(?:software|backend|frontend|full.?stack|ai|ml|data|platform|infra|devops|protocol|rust|python|llm)\s*engineer(?:ing)?|product engineer|ai engineer|ml engineer|founding engineer|data scientist|data engineer)",
                raw, re.I
            )
            roles = list(dict.fromkeys(r.strip() for r in role_matches))[:8]

            result = {
                "has_jobs": True,
                "jobs_url": url,
                "roles_found": roles,
                "raw_snippet": raw[200:500],
            }
            return result
        except Exception:
            continue

    return result


def hunt_funded_small_teams(
    max_team: int = 30,
    batches: list[str] = None,
    keywords: list[str] = None,
    check_careers: bool = True,
    score_min: int = 8,
) -> list[dict]:
    """
    Aggressive hunt: sweep YC with 20 keywords → deduplicate → filter small teams
    → check careers pages for real open roles → score → rank.

    Target profile: heavy YC investment + team ≤ 30 = burning to hire fast.
    """
    if batches is None:
        batches = ["W25", "S24", "W24", "S23", "W23"]
    if keywords is None:
        keywords = YC_SWEEP_KEYWORDS

    print(f"[hunt] Sweeping YC with {len(keywords)} keywords, batch filter: {batches}")

    # Collect all matching companies
    seen_names: set[str] = set()
    all_companies: list[dict] = []

    for kw in keywords:
        try:
            r = requests.get(
                "https://api.ycombinator.com/v0.1/companies",
                params={"q": kw, "limit": 100},
                headers={"User-Agent": "networking-agent/0.1"},
                timeout=10,
            )
            data = r.json()
            companies = data if isinstance(data, list) else data.get("companies", [])
            for c in companies:
                if not isinstance(c, dict):
                    continue
                name = c.get("name", "").strip()
                if not name or name in seen_names:
                    continue
                batch = str(c.get("batch", ""))
                if not any(b in batch for b in batches):
                    continue
                ts = c.get("team_size") or c.get("teamSize")
                try:
                    ts_int = int(ts) if ts else None
                except Exception:
                    ts_int = None
                if ts_int and ts_int > max_team:
                    continue
                seen_names.add(name)
                all_companies.append({
                    "name":      name,
                    "batch":     batch,
                    "website":   c.get("website", ""),
                    "one_liner": c.get("one_liner", ""),
                    "team_size": ts_int,
                    "kw_match":  kw,
                })
            time.sleep(0.2)
        except Exception as e:
            print(f"  [hunt] YC error kw={kw}: {e}")

    print(f"[hunt] Found {len(all_companies)} unique companies (team ≤ {max_team}, recent batches)")

    # Score + check careers pages
    results = []
    for i, c in enumerate(all_companies):
        one_liner = (c.get("one_liner") or "").lower()
        kw = (c.get("kw_match") or "").lower()
        combined = one_liner + " " + kw

        # Quick score from one_liner alone
        base_score = 0
        # YC batch bonus
        batch = c.get("batch", "")
        if any(b in batch for b in ["W25", "S24", "W24"]):
            base_score += 6   # recent batch = +3 (yc) + 3 (recent)
        else:
            base_score += 3

        # Team size
        ts = c.get("team_size")
        if ts:
            if ts <= 5:    base_score += 4
            elif ts <= 15: base_score += 3
            elif ts <= 30: base_score += 2

        # Tech match
        tech_kws = ["ai", "llm", "python", "rust", "automation", "agent", "data", "api",
                    "blockchain", "protocol", "infra", "workflow", "claude", "openai"]
        if any(k in combined for k in tech_kws):
            base_score += 2

        # Founders office signal
        fo_kws = ["founder", "early", "first", "0 to 1", "small team", "seed", "tiny"]
        if any(k in combined for k in fo_kws):
            base_score += 2

        if base_score < score_min - 2:   # pre-filter before expensive careers check
            continue

        # Check careers page
        careers = {"has_jobs": False, "jobs_url": "", "roles_found": []}
        if check_careers and c.get("website"):
            careers = _check_careers_page(c["website"], c["name"])
            if careers["has_jobs"]:
                base_score += 3   # real open role found = big signal

        results.append({
            "source":      "yc_hunt",
            "is_yc":       True,
            "batch":       batch,
            "company":     c["name"],
            "title":       ", ".join(careers["roles_found"]) if careers["roles_found"] else "Engineer",
            "location":    "Remote (YC)",
            "website":     c["website"],
            "one_liner":   c["one_liner"],
            "team_size":   ts,
            "url":         careers["jobs_url"] or c["website"],
            "has_open_roles": careers["has_jobs"],
            "roles_found": careers["roles_found"],
            "posted_days_ago": None,
            "salary_min":  None,
            "salary_max":  None,
            "description": one_liner + " " + kw,
            "tech_stack":  kw,
            "score":       base_score,
        })
        if (i + 1) % 10 == 0:
            print(f"  [hunt] checked {i+1}/{len(all_companies)} companies...")

    # Sort: open roles first, then score
    results.sort(key=lambda x: (-int(x["has_open_roles"]), -x["score"]))

    print(f"[hunt] Done. {len(results)} companies passed filter. "
          f"{sum(1 for r in results if r['has_open_roles'])} have confirmed open roles.")
    return results


# ── Source 2: HN Who Is Hiring ────────────────────────────────────────────────
HN_THREAD_IDS = {
    "2026-06": 48357725,
    "2026-05": 47975571,
    "2026-04": 47581920,
    "2026-03": 47219668,
    "2026-02": 46857488,
    "2026-01": 46466074,
}

def fetch_hn_jobs(keyword: str = "", max_age_days: int = 7, limit: int = 80) -> list[dict]:
    """Fetch current month's HN Who Is Hiring thread."""
    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    thread_id = HN_THREAD_IDS.get(month_key)
    if not thread_id:
        print(f"  [hn] no thread ID for {month_key}")
        return []

    thread_posted = datetime(now.year, now.month, 1)

    try:
        r = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{thread_id}.json", timeout=10)
        kids = (r.json().get("kids") or [])[:limit]
    except Exception as e:
        print(f"  [hn] fetch error: {e}")
        return []

    jobs = []
    kw_lower = keyword.lower()

    for kid_id in kids:
        try:
            c = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{kid_id}.json", timeout=5).json()
            text = c.get("text", "") or ""
            # Clean HTML
            clean = re.sub("<[^>]+>", " ", text)
            for ent, rep in [("&amp;","&"),("&#x27;","'"),("&gt;",">"),("&lt;","<"),("&#x2F;","/"),("&nbsp;"," ")]:
                clean = clean.replace(ent, rep)
            clean = re.sub(r"\s+", " ", clean).strip()
            cl = clean.lower()

            # Skip if keyword doesn't match
            if kw_lower and kw_lower not in cl:
                # Broader check — any relevant tech keyword
                relevant_kws = ["rust", "python", "ai ", "llm", "agent", "blockchain", "ethereum",
                               "automation", "data", "infrastructure", "protocol", "remote"]
                if not any(k in cl for k in relevant_kws):
                    continue

            # Must be remote
            if "remote" not in cl:
                continue

            # Filter noise: job seekers posting "SEEKING WORK", freelancers, location-only posts
            noise_signals = ["seeking work", "seeking employment", "looking for work", "open to work",
                             "available for", "freelance available", "hire me", "seeking remote"]
            if any(n in cl[:100] for n in noise_signals):
                continue
            # Skip posts where first line looks like a person's location (no company signal)
            if re.match(r"^location:", clean, re.I):
                continue

            # Filter US-only if strict global needed
            us_only = bool(re.search(r'\(us only\)|\(US\)|\bUS only\b|must live in (the )?US', clean, re.I))

            # Extract salary
            sal_match = re.search(r"[\$£€]([\d,]+)[kK]?\s*[-–]\s*[\$£€]?([\d,]+)[kK]?", clean)
            sal_min = sal_max = None
            if sal_match:
                try:
                    lo = int(sal_match.group(1).replace(",",""))
                    hi = int(sal_match.group(2).replace(",",""))
                    sal_min = lo * 1000 if lo < 1000 else lo
                    sal_max = hi * 1000 if hi < 1000 else hi
                except Exception:
                    pass

            # Team size signals
            ts_match = re.search(r"team of (\d+)|(\d+)[-\s]person team|(\d+) employees", cl)
            team_size = None
            if ts_match:
                for g in ts_match.groups():
                    if g:
                        team_size = int(g)
                        break

            # Small signals
            small_signals = ["solo founder", "founding engineer", "small team", "seed", "series a",
                           "yc", "y combinator", "3 person", "5 person", "10 person", "early stage"]
            is_small = any(s in cl for s in small_signals)

            # Extract company name (first word(s) before | or ,)
            first_line = clean.split("\n")[0].split("|")[0].split(",")[0].strip()
            company = first_line[:50] if first_line else f"HN-{kid_id}"

            # Posting age — HN posts go up on month 1st, but individual comments can vary
            # Use thread creation date as approximation
            posted_ts = c.get("time")
            if posted_ts:
                posted_dt = datetime.fromtimestamp(posted_ts)
                posted_days_ago = (datetime.now() - posted_dt).days
            else:
                posted_days_ago = (datetime.now() - thread_posted).days

            if posted_days_ago > max_age_days:
                continue

            jobs.append({
                "source":        "hn",
                "is_yc":         False,
                "batch":         "",
                "company":       company,
                "title":         clean[:80],
                "location":      "Remote" + (" (US only)" if us_only else " (global signal)"),
                "website":       f"https://news.ycombinator.com/item?id={kid_id}",
                "description":   clean[:600],
                "tech_stack":    cl[:200],
                "team_size":     team_size,
                "funded_recently": is_small,
                "url":           f"https://news.ycombinator.com/item?id={kid_id}",
                "posted_days_ago": posted_days_ago,
                "salary_min":    sal_min,
                "salary_max":    sal_max,
                "us_only":       us_only,
                "raw_text":      clean,
            })
        except Exception:
            continue

    return jobs


# ── Source 3: web3.career (RSS, 24h) ─────────────────────────────────────────
def fetch_web3career_jobs_safe(max_age_hours: int = 24) -> list[dict]:
    """Wrapper — import web3career scraper dynamically."""
    try:
        sys.path.insert(0, str(Path(__file__).parent / "sources" / "web3career"))
        from scraper import fetch_web3career_jobs
        return fetch_web3career_jobs(max_age_hours=max_age_hours)
    except Exception as e:
        print(f"  [web3career] error: {e}")
        return []


# ── Source 4: RemoteOK ────────────────────────────────────────────────────────
def fetch_remoteok_jobs(tags: str = "ai,python,rust", max_age_days: int = 7) -> list[dict]:
    jobs = []
    try:
        r = requests.get(
            f"https://remoteok.com/api?tags={tags}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        cutoff = datetime.now() - timedelta(days=max_age_days)
        for j in r.json():
            if not isinstance(j, dict) or not j.get("position"):
                continue
            posted_str = j.get("date", "")
            try:
                posted_dt = datetime.fromisoformat(posted_str.replace("Z",""))
                if posted_dt < cutoff:
                    continue
                posted_days_ago = (datetime.now() - posted_dt).days
            except Exception:
                posted_days_ago = None

            desc = (j.get("description", "") or "").lower()
            title = j.get("position", "").lower()
            jobs.append({
                "source":        "remoteok",
                "is_yc":         False,
                "batch":         "",
                "company":       j.get("company", "?"),
                "title":         j.get("position", ""),
                "location":      "Remote",
                "website":       j.get("company_url", ""),
                "description":   j.get("description", "")[:600],
                "tech_stack":    str(j.get("tags", "")),
                "team_size":     None,
                "url":           j.get("url", ""),
                "posted_days_ago": posted_days_ago,
                "salary_min":    j.get("salary_min"),
                "salary_max":    j.get("salary_max"),
            })
    except Exception as e:
        print(f"  [remoteok] error: {e}")
    return jobs


# ── Email Finder ──────────────────────────────────────────────────────────────
def find_founder_email(company_name: str, domain: str = "", role: str = "founder", website: str = "") -> dict:
    """
    Find founder/CTO email. Strategy:
    1. Hunter.io domain search (if HUNTER_API_KEY set)
    2. Pattern guesses: founder@domain, cto@domain, hello@domain
    3. Return best guess with confidence
    """
    # Use centralized email finder
    try:
        from sources.email.finder import find_email, find_yc_founder_email
        if website and not domain:
            result = find_yc_founder_email(company_name, website)
        else:
            result = find_email(company_name, domain=domain)
        return result
    except Exception:
        pass

    # Direct fallback
    if not domain:
        slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
        domain = f"{slug}.com"
    patterns = [f"founder@{domain}", f"ceo@{domain}", f"cto@{domain}",
                f"hello@{domain}", f"hi@{domain}", f"team@{domain}", f"hr@{domain}"]
    return {"email": patterns[0], "confidence": "pattern_guess", "method": "pattern", "all_patterns": patterns}


# ── SQLite job tracking DB ────────────────────────────────────────────────────
def _init_jobs_db():
    con = sqlite3.connect(JOBS_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            source TEXT,
            batch TEXT,
            team_size INTEGER,
            salary_range TEXT,
            jd_url TEXT,
            jd_file TEXT,
            cv_file TEXT,
            score INTEGER,
            status TEXT DEFAULT 'found',
            applied_date TEXT,
            replied_date TEXT,
            interview_date TEXT,
            rejection_reason TEXT,
            notes TEXT,
            email_sent_to TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, role)
        )
    """)
    con.commit()
    return con


def save_job(job: dict) -> int:
    """Save job to tracking DB. Returns row id."""
    con = _init_jobs_db()
    sal = ""
    if job.get("salary_min") and job.get("salary_max"):
        sal = f"${job['salary_min']//1000}K-${job['salary_max']//1000}K"
    try:
        cur = con.execute(
            """INSERT OR IGNORE INTO job_applications
               (company, role, source, batch, team_size, salary_range, jd_url, score, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'found')""",
            (
                job.get("company", ""),
                job.get("title", ""),
                job.get("source", ""),
                job.get("batch", ""),
                job.get("team_size"),
                sal,
                job.get("url", ""),
                job.get("score", 0),
            ),
        )
        row_id = cur.lastrowid
        con.commit()
        return row_id
    finally:
        con.close()


def update_application(company: str, role: str, **kwargs):
    """Update status, notes, email_sent_to, etc."""
    con = _init_jobs_db()
    try:
        for key, val in kwargs.items():
            con.execute(
                f"UPDATE job_applications SET {key}=? WHERE company=? AND role=?",
                (val, company, role),
            )
        con.commit()
    finally:
        con.close()


def list_applications(status: str = None) -> list[dict]:
    con = _init_jobs_db()
    try:
        q = "SELECT * FROM job_applications"
        if status:
            q += f" WHERE status='{status}'"
        q += " ORDER BY score DESC, created_at DESC"
        rows = con.execute(q).fetchall()
        cols = [d[0] for d in con.execute(q).description] if rows else []
        # Re-query with description
        cur = con.execute(q if not status else f"SELECT * FROM job_applications WHERE status='{status}' ORDER BY score DESC")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


# ── Obsidian Application Note ─────────────────────────────────────────────────
def write_obsidian_application(
    company: str,
    role: str,
    jd_text: str,
    cv_file: str = "",
    email_sent_to: str = "",
    source: str = "",
    salary: str = "",
    score: int = 0,
    notes: str = "",
) -> Path:
    """Write application tracking note to Obsidian vault."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{today}_{company}_{role}")[:80]
    note_path = JOBS_DIR / f"{safe_name}.md"

    # Summarize JD in 5 bullets using Claude CLI
    jd_summary = ""
    try:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        prompt = f"Summarize this job description in exactly 5 bullet points. Focus on: required tech stack, key responsibilities, experience level, company size signal. Be brief.\n\n{jd_text[:1500]}"
        res = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=60, env=env)
        jd_summary = res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        jd_summary = jd_text[:400]

    content = f"""---
company: {company}
role: {role}
applied: {today}
source: {source}
salary: {salary}
score: {score}
status: applied
email_sent_to: {email_sent_to}
cv_used: {Path(cv_file).name if cv_file else ""}
---

# {company} — {role}

**Applied:** {today} | **Source:** {source} | **Salary:** {salary} | **Score:** {score}/20

## JD Summary
{jd_summary}

## Why I Fit
*(fill after generating CV — paste the Fit section from the CV)*

## Outreach Sent
- **Email:** {email_sent_to or "not sent"}
- **LinkedIn:** [ ] sent
- **Portal:** [ ] applied

## CV Used
`{Path(cv_file).name if cv_file else "TBD"}`

## Timeline
| Date | Event |
|------|-------|
| {today} | Applied |

## Notes
{notes}

## Follow-Up Checklist
- [ ] Day 3: follow-up email if no reply
- [ ] Day 7: second follow-up or LinkedIn nudge
- [ ] Day 14: close out if no response

## Rejection Reason
*(fill if rejected)*
"""

    note_path.write_text(content)
    print(f"  [obsidian] Written → {note_path}")
    return note_path


# ── Full search + score pipeline ──────────────────────────────────────────────
def search_and_score(
    keywords: list[str] = None,
    sources: list[str] = None,
    max_age_days: int = 7,
    max_team: int = 50,
    score_min: int = 7,
    limit: int = 30,
) -> list[dict]:
    """
    Multi-source job search → score → filter → rank → return top results.
    """
    if keywords is None:
        keywords = ["AI automation", "LLM", "python", "rust", "blockchain", "workflow"]
    if sources is None:
        sources = ["yc", "hn", "remoteok"]

    all_jobs = []

    if "yc" in sources:
        print("[sourcer] Fetching YC companies...")
        for kw in keywords[:4]:
            jobs = fetch_yc_jobs(kw, max_team=max_team, max_age_days=max_age_days)
            all_jobs.extend(jobs)
            time.sleep(0.3)

    if "hn" in sources:
        print("[sourcer] Fetching HN Who Is Hiring...")
        kw_str = " ".join(keywords[:3])
        jobs = fetch_hn_jobs(keyword=kw_str, max_age_days=max_age_days, limit=120)
        all_jobs.extend(jobs)

    if "remoteok" in sources:
        print("[sourcer] Fetching RemoteOK...")
        tags = ",".join(k.lower().replace(" ", "-") for k in keywords[:4] if len(k) < 15)
        jobs = fetch_remoteok_jobs(tags=tags, max_age_days=max_age_days)
        all_jobs.extend(jobs)

    if "web3career" in sources:
        print("[sourcer] Fetching web3.career RSS...")
        jobs = fetch_web3career_jobs_safe(max_age_hours=max_age_days * 24)
        all_jobs.extend(jobs)

    if "wellfound" in sources:
        print("[sourcer] Fetching Wellfound (Playwright)...")
        try:
            from sources.wellfound.scraper import scrape_wellfound
            import asyncio
            jobs = asyncio.run(scrape_wellfound())
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  [wellfound] error: {e}")

    if "linkedin" in sources:
        print("[sourcer] Fetching LinkedIn Jobs (Playwright — needs active session)...")
        try:
            from sources.linkedin.scraper import fetch_linkedin_jobs
            import asyncio
            jobs = asyncio.run(fetch_linkedin_jobs(max_age_hours=max_age_days * 24))
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  [linkedin] error: {e}")

    if "crunchbase" in sources:
        print("[sourcer] Fetching Crunchbase / funding news...")
        try:
            _cb_path = Path(__file__).parent / "sources" / "crunchbase"
            sys.path.insert(0, str(_cb_path))
            from scraper import fetch_crunchbase_funded
            jobs = fetch_crunchbase_funded(max_age_days=max_age_days * 3)
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  [crunchbase] error: {e}")

    # Deduplicate by company+title
    seen = set()
    unique = []
    for j in all_jobs:
        key = f"{j.get('company','').lower()}|{j.get('title','').lower()[:40]}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    # Score everything
    for j in unique:
        j["score"] = score_job(j)

    # Filter: score ≥ min, team size ≤ max
    filtered = [j for j in unique if j["score"] >= score_min]
    if max_team:
        ts_filtered = []
        for j in filtered:
            ts = j.get("team_size")
            if ts is None or int(ts) <= max_team:
                ts_filtered.append(j)
        filtered = ts_filtered

    # Sort by score desc, then posting age asc (newer first)
    filtered.sort(key=lambda j: (-j["score"], j.get("posted_days_ago") or 999))

    # Save to DB
    for j in filtered[:limit]:
        save_job(j)

    return filtered[:limit]


# ── Apply workflow ────────────────────────────────────────────────────────────
def apply_to_job(
    company: str,
    role: str,
    jd_file: str,
    domain: str = "",
    angle: str = "auto",
    dry_run: bool = False,
) -> dict:
    """
    Full apply workflow:
    1. Read JD
    2. Find founder email
    3. Generate tailored CV (cv_agent)
    4. Write Obsidian tracking note
    5. Update DB
    Returns summary dict.
    """
    sys.path.insert(0, str(Path(__file__).parent))

    jd_path = Path(jd_file)
    if not jd_path.exists():
        return {"error": f"JD file not found: {jd_file}"}
    jd_text = jd_path.read_text()

    # 1. Find email
    print(f"[apply] Finding email for {company}...")
    email_info = find_founder_email(company, domain=domain)
    email_addr = email_info.get("email", "")
    print(f"  Email: {email_addr} (via {email_info.get('method','?')}, confidence: {email_info.get('confidence','?')})")

    # 2. Generate CV
    print(f"[apply] Generating CV ({angle} angle)...")
    cv_cmd = [
        "python3", str(Path(__file__).parent / "cli.py"),
        "cv",
        "--jd", str(jd_path),
        "--company", company,
        "--role", role,
    ]
    if angle != "auto":
        cv_cmd += ["--angle", angle]

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if not dry_run:
        res = subprocess.run(cv_cmd, capture_output=True, text=True, timeout=120, env=env, cwd=str(Path(__file__).parent.parent))
        cv_output = res.stdout
        # Extract saved path
        m = re.search(r"Saved → (.+\.md)", cv_output)
        cv_file = m.group(1) if m else ""
    else:
        cv_file = f"[DRY RUN] agents/output/cvs/cv_{company.lower()}_{role.lower()}.md"

    # 3. Obsidian note
    print(f"[apply] Writing Obsidian tracking note...")
    note_path = write_obsidian_application(
        company=company,
        role=role,
        jd_text=jd_text,
        cv_file=cv_file,
        email_sent_to=email_addr if not dry_run else "",
        source="manual",
        score=0,
        notes=f"Email confidence: {email_info.get('confidence','?')}. Method: {email_info.get('method','?')}.",
    )

    # 4. Update DB
    update_application(
        company=company,
        role=role,
        status="applied" if not dry_run else "draft",
        applied_date=date.today().isoformat(),
        email_sent_to=email_addr,
        jd_file=str(jd_path),
        cv_file=cv_file,
    )

    return {
        "company": company,
        "role": role,
        "email": email_addr,
        "email_confidence": email_info.get("confidence"),
        "cv_file": cv_file,
        "obsidian_note": str(note_path),
        "status": "applied" if not dry_run else "dry_run",
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Track A Job Pipeline")
    sub = parser.add_subparsers(dest="cmd")

    # search
    p_search = sub.add_parser("search", help="Find + score jobs")
    p_search.add_argument("--keywords", nargs="+", default=["AI automation", "python", "rust", "LLM"])
    p_search.add_argument("--sources", nargs="+", default=["yc", "hn", "remoteok"])
    p_search.add_argument("--max-age", type=int, default=7, help="Max days since posted")
    p_search.add_argument("--max-team", type=int, default=50, help="Max team size")
    p_search.add_argument("--score-min", type=int, default=7)

    # apply
    p_apply = sub.add_parser("apply", help="Apply to a job")
    p_apply.add_argument("--company", required=True)
    p_apply.add_argument("--role", required=True)
    p_apply.add_argument("--jd", required=True, help="Path to JD .txt file")
    p_apply.add_argument("--domain", default="", help="Company domain for email finder")
    p_apply.add_argument("--angle", default="auto", choices=["auto","protocol_engineer","data_engineering","rust_mcp"])
    p_apply.add_argument("--dry-run", action="store_true")

    # list
    p_list = sub.add_parser("list", help="List tracked applications")
    p_list.add_argument("--status", default=None)

    # email
    p_email = sub.add_parser("email", help="Find founder email for a domain")
    p_email.add_argument("--company", required=True)
    p_email.add_argument("--domain", default="")

    args = parser.parse_args()

    if args.cmd == "search":
        jobs = search_and_score(
            keywords=args.keywords,
            sources=args.sources,
            max_age_days=args.max_age,
            max_team=args.max_team,
            score_min=args.score_min,
        )
        print(f"\n{'='*70}")
        print(f"Found {len(jobs)} jobs (score ≥ {args.score_min}, team ≤ {args.max_team}, posted ≤ {args.max_age}d)")
        print(f"{'='*70}")
        for j in jobs:
            ts_str = f"team:{j['team_size']}" if j.get("team_size") else "team:?"
            age_str = f"{j['posted_days_ago']}d ago" if j.get("posted_days_ago") is not None else "age:?"
            sal_str = f"${j['salary_min']//1000}K-${j['salary_max']//1000}K" if j.get("salary_max") else "salary:?"
            print(f"\n  [{j['score']:2d}/20] {j['company']} — {j['title'][:55]}")
            print(f"         {j['source'].upper()} | {ts_str} | {age_str} | {sal_str}")
            print(f"         {j.get('location','')[:50]}")
            print(f"         {j['url'][:70]}")
            if j.get("one_liner"):
                print(f"         \"{j['one_liner'][:80]}\"")

    elif args.cmd == "apply":
        result = apply_to_job(
            company=args.company,
            role=args.role,
            jd_file=args.jd,
            domain=args.domain,
            angle=args.angle,
            dry_run=args.dry_run,
        )
        print(f"\n{'='*60}")
        print(f"Applied: {result['company']} — {result['role']}")
        print(f"Email:   {result['email']} ({result['email_confidence']})")
        print(f"CV:      {result['cv_file']}")
        print(f"Note:    {result['obsidian_note']}")

    elif args.cmd == "list":
        apps = list_applications(status=args.status)
        print(f"\n{'='*60}")
        print(f"Applications ({args.status or 'all'}): {len(apps)}")
        for a in apps:
            print(f"  [{a['status']:10}] {a['company']} — {a['role']} | score:{a['score']} | {a['applied_date'] or 'not applied'}")

    elif args.cmd == "email":
        result = find_founder_email(args.company, domain=args.domain)
        print(json.dumps(result, indent=2))
