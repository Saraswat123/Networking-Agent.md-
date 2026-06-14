"""
Classifier Agent — identifies non-technical companies wanting AI automation.

Two-track classification:
  TRACK A: Technical company, open position → job application
  TRACK B: Non-technical, AI-hungry → proposal + implementation

Three parallel Claude agents per company:
  1. Tech Classifier    → is this company technical or non-technical?
  2. AI Hunger Detector → do they want/need AI automation?
  3. Proposal Generator → what specific AI solution do we offer?

Target markets: US, UK, Europe
Target sectors: wealth management, legal, real estate, logistics,
                family offices, private equity, professional services
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import anthropic
import requests

import obsidian_sync

OUTPUT_DIR = Path(__file__).parent / "output" / "classifier"

TRACK_A = "A"   # technical, job application
TRACK_B = "B"   # non-technical, proposal + implementation
TRACK_SKIP = "skip"

# Target countries for Track B sourcing
TARGET_REGIONS = ["US", "UK", "United Kingdom", "Europe", "Germany", "France",
                  "Netherlands", "Switzerland", "Sweden", "Spain", "Italy",
                  "United States", "Canada", "Australia"]

# Sectors that have money + need AI but lack technical staff
HIGH_VALUE_SECTORS = [
    "wealth management", "family office", "private equity", "hedge fund",
    "real estate", "property", "legal", "law firm", "accounting", "consulting",
    "logistics", "supply chain", "manufacturing", "healthcare", "insurance",
    "financial services", "investment", "asset management", "hospitality",
    "retail", "construction", "education", "recruitment", "hr",
]


# ─── Data gathering ────────────────────────────────────────────────────────────

def fetch_company_website_info(website: str) -> dict:
    """Try to get basic info from company website."""
    if not website:
        return {}
    url = website if website.startswith("http") else f"https://{website}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text[:3000]  # first 3kb for signals
        return {
            "status_code": resp.status_code,
            "has_careers_page": "careers" in text.lower() or "jobs" in text.lower(),
            "has_tech_blog": "engineering" in text.lower() or "tech blog" in text.lower(),
            "has_ai_mention": "ai" in text.lower() or "artificial intelligence" in text.lower() or "automation" in text.lower(),
            "text_snippet": text[:500],
        }
    except Exception:
        return {}


def fetch_tech_signals(website: str) -> dict:
    """WebReveal tech stack — low/no stack = non-technical signal."""
    if not website:
        return {"technologies": [], "tech_count": 0}
    url = website if website.startswith("http") else f"https://{website}"
    try:
        resp = requests.get(
            "https://api.webreveal.io/tech",
            params={"url": url},
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=15,
        )
        techs = resp.json().get("technologies", [])
        names = [t.get("name", "") for t in techs if t.get("name")]
        return {
            "technologies": names,
            "tech_count": len(names),
            "has_custom_tech": any(t in " ".join(names).lower() for t in ["react", "vue", "django", "rails", "node", "rust", "python", "java", "kubernetes"]),
            "only_marketing_stack": all(t in ["WordPress", "Wix", "Squarespace", "Google Analytics", "HubSpot", "Mailchimp", "Shopify"] for t in names),
        }
    except Exception:
        return {"technologies": [], "tech_count": 0}


def extract_website_from_prospect(prospect: dict) -> Optional[str]:
    notes = prospect.get("notes", "")
    for word in notes.split():
        if "website:" in word:
            return word.replace("website:", "").strip()
        if word.startswith("http") and "github" not in word:
            return word.strip(".,;")
    return None


def is_target_region(prospect: dict) -> bool:
    location = (prospect.get("location") or "").lower()
    notes = (prospect.get("notes") or "").lower()
    combined = location + " " + notes
    return any(r.lower() in combined for r in TARGET_REGIONS)


def detect_sector(prospect: dict) -> str:
    text = " ".join([
        prospect.get("company", ""),
        prospect.get("notes", ""),
        prospect.get("role", ""),
    ]).lower()
    for sector in HIGH_VALUE_SECTORS:
        if sector in text:
            return sector
    return "unknown"


# ─── Claude agents (async parallel) ───────────────────────────────────────────

async def agent_tech_classifier(client, company: str, prospect: dict,
                                 tech_signals: dict, website_info: dict) -> dict:
    """Agent 1: Is this a technical company or non-technical?"""
    tech_str = json.dumps(tech_signals, indent=2)
    site_str = json.dumps(website_info, indent=2)
    notes = prospect.get("notes", "")[:400]
    location = prospect.get("location", "")

    prompt = f"""Classify this company as TECHNICAL or NON-TECHNICAL.

COMPANY: {company}
LOCATION: {location}
NOTES: {notes}
TECH STACK DETECTED: {tech_str}
WEBSITE INFO: {site_str}

DEFINITION:
- TECHNICAL: Has software engineers, builds own products, custom tech stack,
  engineering blog, GitHub org, developer job postings
- NON-TECHNICAL: Professional services, wealth/family office, law firm, logistics,
  real estate, retail, manufacturing — uses tech as a tool but doesn't build it.
  May have simple CMS website, no custom stack.

Return ONLY valid JSON:
{{
  "is_technical": true/false,
  "tech_maturity": 1-10,
  "company_size": "micro (<10) | small (10-50) | mid (50-500) | large (500+)",
  "sector": "detected sector",
  "country": "detected country",
  "non_tech_signal": "key evidence they are non-technical (e.g. WordPress site, no GitHub, estate management company)",
  "tech_signal": "key evidence they have tech capability (if any)",
  "one_liner": "one sentence describing what this company does",
  "confidence": "high | medium | low"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "tech_classifier")


async def agent_ai_hunger(client, company: str, prospect: dict,
                           tech_signals: dict, website_info: dict) -> dict:
    """Agent 2: Does this company want/need AI automation? How hungry are they?"""
    notes = prospect.get("notes", "")[:400]
    sector = detect_sector(prospect)
    has_ai_mention = website_info.get("has_ai_mention", False)
    tech_count = tech_signals.get("tech_count", 0)

    prompt = f"""Assess how much this company NEEDS and WANTS AI automation.

COMPANY: {company}
SECTOR: {sector}
NOTES: {notes}
CURRENT TECH: {tech_signals.get("technologies", [])}
MENTIONS AI ON WEBSITE: {has_ai_mention}
TECH SOPHISTICATION: {tech_count} technologies detected

CONTEXT: This is a non-technical company in {sector}. They likely have:
- Manual Excel/email workflows
- No data automation
- Paper-based or legacy processes
- A leadership team that has heard about AI but doesn't know how to start

AI AUTOMATION OPPORTUNITIES IN THIS SECTOR:
- Wealth/finance: automated reporting, portfolio summaries, client emails
- Legal: contract analysis, document review, client intake
- Real estate: property analysis, market reports, lead qualification
- Logistics: route optimization, demand forecasting, vendor communication
- Recruitment: CV screening, candidate matching, interview scheduling
- Retail: inventory management, customer service bots, trend analysis

Return ONLY valid JSON:
{{
  "hunger_score": 0-10,
  "why_they_want_ai": "specific reason this sector/company needs AI",
  "pain_points": ["list of 3-5 manual processes they likely do now"],
  "manual_processes": ["specific things we could automate for them"],
  "decision_maker_signal": "who in this company makes the buy decision (CEO, COO, Director)",
  "urgency": "high | medium | low",
  "budget_signal": "do they seem to have budget for this? evidence?"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "ai_hunger")


async def agent_proposal_generator(client, company: str, prospect: dict,
                                    classifier: dict, ai_hunger: dict) -> dict:
    """Agent 3: Generate a specific AI automation proposal for this company."""
    sector = classifier.get("sector", "unknown")
    pain_points = ai_hunger.get("pain_points", [])
    manual = ai_hunger.get("manual_processes", [])
    country = classifier.get("country", "")
    size = classifier.get("company_size", "")

    prompt = f"""You are a technical consultant pitching AI automation to a non-technical company.

COMPANY: {company}
SECTOR: {sector}
COUNTRY: {country}
SIZE: {size}
PAIN POINTS: {json.dumps(pain_points)}
MANUAL PROCESSES: {json.dumps(manual)}

OUR CAPABILITIES:
- Rust backend systems (fast, reliable, memory-safe)
- Claude AI integration (document analysis, email generation, data extraction)
- MCP servers (connect AI to any tool or database)
- Python automation scripts
- Simple dashboards and reporting systems
- No-code/low-code interfaces for non-technical users

TASK: Design a specific AI automation package for this company.
Make it concrete, not generic. Reference their sector specifically.
Price it realistically for a company of this size in this country.

Return ONLY valid JSON:
{{
  "solution_title": "short catchy name e.g. 'AI Operations Suite for Family Offices'",
  "solution_description": "2-3 sentences what we build and why it matters to them",
  "deliverables": ["list of 4-6 specific things we deliver"],
  "tech_stack_we_use": ["Claude API", "Python", etc.],
  "timeline": "e.g. '6 weeks MVP, 12 weeks full system'",
  "estimated_value": "e.g. '$15,000-25,000 setup + $2,000/mo maintenance'",
  "pricing_model": "project | retainer | hybrid",
  "outreach_channel": "email | linkedin | referral",
  "target_contact_role": "who to contact e.g. 'CEO or COO'",
  "outreach_hook": "one punchy sentence to open the email — not generic, references their specific pain",
  "email_subject": "email subject line under 8 words",
  "email_draft": "50-80 word cold email draft — lead with their pain, show we understand their world, ask for 20 min call"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "proposal_generator")


# ─── Decision logic ────────────────────────────────────────────────────────────

def classify_track(classifier: dict, ai_hunger: dict,
                   prospect: dict, research_data: Optional[dict] = None) -> dict:
    """Decide TRACK A, TRACK B, or skip."""
    is_technical = classifier.get("is_technical", True)
    tech_maturity = classifier.get("tech_maturity", 5)
    hunger_score = ai_hunger.get("hunger_score", 0)

    # Research data from research_agent (if available)
    if research_data:
        shortlist_score = research_data.get("shortlist", {}).get("shortlist_score", 0)
        has_job = research_data.get("job_analysis", {}).get("has_open_position", False)
        if is_technical and shortlist_score >= 6 and has_job:
            return {"track": TRACK_A, "reason": "Technical company, open position"}

    # Track B: non-technical + hungry for AI
    if not is_technical and hunger_score >= 6:
        return {"track": TRACK_B, "reason": f"Non-technical, AI hunger {hunger_score}/10"}

    # Track B fallback: low-tech in high-value sector even if partially technical
    if tech_maturity <= 4 and hunger_score >= 7:
        return {"track": TRACK_B, "reason": f"Low tech maturity ({tech_maturity}/10), high AI need"}

    # Track A fallback for technical companies
    if is_technical and tech_maturity >= 6:
        return {"track": TRACK_A, "reason": "Technical company"}

    return {"track": TRACK_SKIP, "reason": f"Low fit: technical={is_technical}, hunger={hunger_score}"}


# ─── Main entry ────────────────────────────────────────────────────────────────

async def classify_company_async(prospect: dict, research_data: Optional[dict] = None) -> dict:
    company = prospect.get("company") or prospect.get("name") or "Unknown"
    print(f"\n  [classify] {company} ({prospect.get('location', '?')})")

    website = extract_website_from_prospect(prospect)

    # Data gathering
    tech_signals, website_info = await asyncio.gather(
        asyncio.to_thread(fetch_tech_signals, website or ""),
        asyncio.to_thread(fetch_company_website_info, website or ""),
    )

    print(f"    tech_count={tech_signals.get('tech_count', 0)} ai_mention={website_info.get('has_ai_mention', False)}")

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Run tech classifier + AI hunger detector in parallel
    classifier, ai_hunger = await asyncio.gather(
        agent_tech_classifier(client, company, prospect, tech_signals, website_info),
        agent_ai_hunger(client, company, prospect, tech_signals, website_info),
    )

    track_decision = classify_track(classifier, ai_hunger, prospect, research_data)
    track = track_decision["track"]

    proposal = {}
    if track == TRACK_B:
        proposal = await agent_proposal_generator(client, company, prospect, classifier, ai_hunger)

    result = {
        "company": company,
        "prospect": prospect,
        "track": track,
        "track_reason": track_decision["reason"],
        "classifier": classifier,
        "ai_hunger": ai_hunger,
        "proposal": proposal,
        "tech_signals": tech_signals,
        "score": ai_hunger.get("hunger_score", 0) if track == TRACK_B else classifier.get("tech_maturity", 0),
        "ai_hunger_score": ai_hunger.get("hunger_score", 0),
    }

    # Save output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in company if c.isalnum() or c in "-_").lower()
    (OUTPUT_DIR / f"classify_{safe}.json").write_text(json.dumps(result, indent=2))

    # Write to Obsidian
    if track == TRACK_A:
        path = obsidian_sync.write_track_a(company, research_data or result)
        print(f"    → Track A: {path.name}")
    elif track == TRACK_B:
        path = obsidian_sync.write_track_b(company, result)
        print(f"    → Track B: {path.name}")
    else:
        print(f"    → Skipped: {track_decision['reason']}")

    return result


def classify_company(prospect: dict, research_data: Optional[dict] = None) -> dict:
    return asyncio.run(classify_company_async(prospect, research_data))


async def classify_batch_async(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)

    async def bounded(p):
        async with sem:
            return await classify_company_async(p)

    results = await asyncio.gather(*[bounded(p) for p in prospects])

    # Update Obsidian dashboard + log
    track_a = [r["company"] for r in results if r["track"] == TRACK_A]
    track_b = [r["company"] for r in results if r["track"] == TRACK_B]
    obsidian_sync.update_dashboard(track_a, track_b)
    obsidian_sync.log_classifier_run(results)

    return list(results)


def classify_batch(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    return asyncio.run(classify_batch_async(prospects, concurrency))


def print_classifier_report(results: list[dict]) -> None:
    sep = "─" * 65
    print(f"\n{sep}")
    print("CLASSIFIER REPORT")
    print(sep)

    a = [r for r in results if r["track"] == TRACK_A]
    b = [r for r in results if r["track"] == TRACK_B]
    skipped = [r for r in results if r["track"] == TRACK_SKIP]

    print(f"\n  TRACK A (Job Applications):    {len(a)}")
    for r in a:
        print(f"    → {r['company']} | {r['classifier'].get('sector', '?')} | {r['classifier'].get('country', '?')}")

    print(f"\n  TRACK B (AI Proposals):        {len(b)}")
    for r in sorted(b, key=lambda x: x.get("ai_hunger_score", 0), reverse=True):
        score = r.get("ai_hunger_score", 0)
        value = r.get("proposal", {}).get("estimated_value", "?")
        hook = r.get("proposal", {}).get("outreach_hook", "")
        print(f"    [{score}/10] {r['company']}")
        print(f"           Value: {value}")
        print(f"           Hook:  {hook[:80]}")

    print(f"\n  Skipped: {len(skipped)}")
    print(f"\n  Obsidian notes saved:")
    print(f"    Track A → Obsidian/Prospects/TrackA_Jobs/")
    print(f"    Track B → Obsidian/Prospects/TrackB_Proposals/")
    print(f"    Log     → Obsidian/Classifier/_Classifier_Log.md")
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
