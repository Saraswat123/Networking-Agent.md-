"""
Background Agent — deep company research before proposal generation.

Runs ONE Claude agent per company that pulls all available signals:
  - DuckDuckGo news search (recent press, expansion, problems)
  - UK Companies House data (founding, directors, accounts)
  - Website text analysis (tone, products, self-description)
  - LinkedIn headcount signals (from company notes or manual)

Output feeds into classifier_agent.agent_proposal_generator()
so proposals reference specific company details (founded in X, CEO is Y,
they just expanded to Z) instead of generic sector templates.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import anthropic
import requests

OUTPUT_DIR = Path(__file__).parent / "output" / "background"


# ── Data gathering (sync) ─────────────────────────────────────────────────────

def search_news(company: str, limit: int = 5) -> list[dict]:
    """DuckDuckGo news search — recent press about company."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q": f'"{company}" news',
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=10,
        )
        data = resp.json()
        results = []
        for t in data.get("RelatedTopics", [])[:limit]:
            text = t.get("Text", "")
            url = t.get("FirstURL", "")
            if text:
                results.append({"text": text, "url": url})
        return results
    except Exception:
        return []


def fetch_website_text(website: str, max_chars: int = 2000) -> str:
    """Grab plain text from company homepage."""
    if not website:
        return ""
    url = website if website.startswith("http") else f"https://{website}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        # Very basic HTML strip
        text = resp.text
        text = __import__("re").sub(r"<[^>]+>", " ", text)
        text = __import__("re").sub(r"\s+", " ", text)
        return text[:max_chars]
    except Exception:
        return ""


def lookup_uk_company(company: str) -> dict:
    """UK Companies House basic profile (if UK_CH_API_KEY set)."""
    try:
        from companies_house import research_uk_company
        return research_uk_company(company)
    except Exception:
        return {}


def extract_website(notes: str) -> Optional[str]:
    """Pull website from prospect notes field."""
    for word in notes.split():
        if "website:" in word:
            return word.replace("website:", "").strip()
        if word.startswith("http") and "github" not in word:
            return word.strip(".,;")
    return None


# ── Claude agent ──────────────────────────────────────────────────────────────

async def agent_background_researcher(
    client: anthropic.AsyncAnthropic,
    company: str,
    prospect: dict,
    news: list[dict],
    website_text: str,
    ch_data: dict,
) -> dict:
    """
    Single Claude agent: synthesize all signals into structured company profile.
    Used to make proposals specific and credible.
    """
    notes = prospect.get("notes", "")[:300]
    location = prospect.get("location", "")
    source = prospect.get("source", "")

    news_str = json.dumps(news, indent=2) if news else "No news found."
    website_str = website_text[:800] if website_text else "No website text available."

    ch_profile = ch_data.get("company", {})
    officers = ch_data.get("decision_makers", [])
    ch_str = ""
    if ch_profile:
        ch_str = f"""
Companies House:
  Incorporated: {ch_profile.get('incorporated', '?')} ({ch_data.get('incorporated_years', '?')} years ago)
  Status: {ch_profile.get('status', '?')}
  SIC codes: {', '.join(ch_profile.get('sic_codes', []))}
  Address: {ch_profile.get('address', '')} {ch_profile.get('postcode', '')}
  Active directors: {', '.join(o['name'] for o in officers[:5])}
"""

    prompt = f"""Research this company and produce a structured profile to inform an AI automation proposal.

COMPANY: {company}
LOCATION: {location}
SOURCE: {source}
NOTES: {notes}

{ch_str}

RECENT NEWS / WEB MENTIONS:
{news_str}

WEBSITE HOMEPAGE TEXT (first 800 chars):
{website_str}

TASK: Synthesize all signals into a company profile. Be specific — names, dates, numbers.
If information is not available, say "unknown" rather than guessing.

Return ONLY valid JSON:
{{
  "company_name": "official company name",
  "founded_year": "year or unknown",
  "age_years": "approximate age in years or unknown",
  "headquarters": "city, country",
  "size_estimate": "number of employees or range e.g. 10-50",
  "revenue_estimate": "rough estimate e.g. £2-10M/yr based on size/sector, or unknown",
  "key_people": [
    {{"name": "...", "role": "CEO/MD/Partner/etc", "source": "companies_house|website|linkedin|news"}}
  ],
  "what_they_do": "2-3 sentence description of core business — specific, not generic",
  "main_clients": "who are their typical clients? (e.g. HNW individuals, SMEs, property developers)",
  "recent_news": "1-2 bullet points of most relevant recent news or activity",
  "growth_signals": "any evidence of expansion, hiring, new locations, new services",
  "pain_signals": "any evidence of manual processes, operational stress, staff overload",
  "tech_signals": "any mention of software, tools, IT systems they use",
  "ai_readiness": "high|medium|low — are they likely to be open to AI? Why?",
  "best_contact_approach": "email | linkedin | phone | referral",
  "proposal_hook": "one sentence that references something SPECIFIC about this company — their age, their client type, a recent news item — to open a proposal email"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "background_researcher")


# ── Main entry ────────────────────────────────────────────────────────────────

async def research_company_background_async(prospect: dict) -> dict:
    company = prospect.get("company") or prospect.get("name") or "Unknown"
    print(f"\n  [background] {company}")

    notes = prospect.get("notes", "")
    website = extract_website(notes)
    location = prospect.get("location", "")

    # Parallel data fetch
    news, website_text = await asyncio.gather(
        asyncio.to_thread(search_news, company),
        asyncio.to_thread(fetch_website_text, website or ""),
    )

    # UK Companies House (sync, conditional)
    ch_data = {}
    if "uk" in location.lower() or "united kingdom" in location.lower() or "london" in location.lower():
        ch_data = await asyncio.to_thread(lookup_uk_company, company)
        if ch_data.get("error"):
            ch_data = {}

    print(f"    news={len(news)} website={len(website_text)}chars ch={'yes' if ch_data else 'no'}")

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    profile = await agent_background_researcher(client, company, prospect, news, website_text, ch_data)

    result = {
        "company": company,
        "prospect": prospect,
        "profile": profile,
        "raw": {
            "news": news,
            "ch_data": ch_data,
            "website_chars": len(website_text),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in company if c.isalnum() or c in "-_").lower()
    (OUTPUT_DIR / f"background_{safe}.json").write_text(json.dumps(result, indent=2))

    return result


def research_company_background(prospect: dict) -> dict:
    return asyncio.run(research_company_background_async(prospect))


async def research_batch_async(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)

    async def bounded(p):
        async with sem:
            return await research_company_background_async(p)

    return list(await asyncio.gather(*[bounded(p) for p in prospects]))


def research_batch(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    return asyncio.run(research_batch_async(prospects, concurrency))


def print_background_report(results: list[dict]) -> None:
    sep = "─" * 65
    print(f"\n{sep}")
    print(f"BACKGROUND RESEARCH — {len(results)} companies")
    print(sep)
    for r in results:
        p = r.get("profile", {})
        print(f"\n  {r['company']}")
        print(f"    Founded:    {p.get('founded_year', '?')} ({p.get('age_years', '?')} yrs old)")
        print(f"    Size:       {p.get('size_estimate', '?')} employees")
        print(f"    Revenue:    {p.get('revenue_estimate', '?')}")
        print(f"    Key people: {', '.join(k['name'] + ' (' + k['role'] + ')' for k in p.get('key_people', [])[:3])}")
        print(f"    AI ready:   {p.get('ai_readiness', '?')}")
        print(f"    Hook:       {p.get('proposal_hook', '')[:100]}")
    print(sep)


def _parse_json(text: str, agent_name: str) -> dict:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned.strip())
    except Exception as e:
        print(f"  [{agent_name}] parse error: {e}")
        return {}
