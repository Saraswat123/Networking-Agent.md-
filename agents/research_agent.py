"""
Multi-Agent Research Layer — runs 3 parallel Claude analyses per company.

Agents:
  1. Job Scanner       → finds open positions at company
  2. Collaboration Scanner → finds GitHub issues + MCP/open-source entry points
  3. Shortlist Scorer  → scores company fit against our positioning

Decision Router maps results → one of three pathways:
  PATH_A: Open position found  → CV Agent + targeted outreach
  PATH_B: GitHub entry point   → contribute first → then outreach
  PATH_C: No opening           → pure cold outreach (collaboration pitch)
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import claude_cli as anthropic
import requests

GITHUB_API = "https://api.github.com"
OUTPUT_DIR = Path(__file__).parent / "output" / "research"

PATH_A = "apply_and_outreach"       # open position exists
PATH_B = "contribute_then_outreach" # GitHub entry point exists
PATH_C = "cold_outreach"            # no opening, pure collaboration pitch


# ─── Data gathering (sync, called before async Claude phase) ─────────────────

def fetch_remote_jobs(company_name: str) -> list[dict]:
    """Search RemoteOK for open positions at this company."""
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=10,
        )
        all_jobs = resp.json()[1:]  # skip legal notice
        name_lower = company_name.lower()
        return [
            j for j in all_jobs
            if (j.get("company") or "").lower() == name_lower
            or name_lower in (j.get("description") or "").lower()
        ][:5]
    except Exception:
        return []


def fetch_open_issues(github_org: str, github_token: str) -> list[dict]:
    """Find good-first-issue / help-wanted issues in company's GitHub org repos."""
    if not github_org or not github_token:
        return []
    try:
        # Get top repos
        repos_resp = requests.get(
            f"{GITHUB_API}/orgs/{github_org}/repos",
            headers={
                "Authorization": f"Bearer {github_token}",
                "User-Agent": "networking-agent/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"sort": "stars", "per_page": "5"},
            timeout=10,
        )
        repos = [r["name"] for r in repos_resp.json() if isinstance(r, dict)]

        issues = []
        for repo in repos[:3]:
            r = requests.get(
                f"{GITHUB_API}/repos/{github_org}/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "User-Agent": "networking-agent/0.1",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"labels": "good first issue,help wanted", "state": "open", "per_page": "5"},
                timeout=10,
            )
            for issue in r.json():
                if isinstance(issue, dict) and "title" in issue:
                    issues.append({
                        "repo": repo,
                        "title": issue["title"],
                        "url": issue.get("html_url", ""),
                        "labels": [l["name"] for l in issue.get("labels", [])],
                    })
            time.sleep(0.2)
        return issues[:10]
    except Exception:
        return []


def fetch_tech_stack(website: str) -> list[str]:
    """WebReveal tech stack detection."""
    if not website:
        return []
    url = website if website.startswith("http") else f"https://{website}"
    try:
        resp = requests.get(
            "https://api.webreveal.io/tech",
            params={"url": url},
            headers={"User-Agent": "networking-agent/0.1"},
            timeout=15,
        )
        techs = resp.json().get("technologies", [])
        return [t.get("name", "") for t in techs if t.get("name")]
    except Exception:
        return []


def extract_github_org(prospect: dict) -> Optional[str]:
    """Pull GitHub org from prospect notes or github field."""
    notes = prospect.get("notes") or ""
    github = prospect.get("github") or ""
    for text in [notes, github]:
        for word in text.split():
            if "github.com/" in word:
                parts = word.replace("https://", "").replace("http://", "").split("/")
                if len(parts) >= 2:
                    return parts[1].split("?")[0]
    return None


# ─── Claude agents (async, parallel) ─────────────────────────────────────────

async def agent_job_scanner(client, company: str, jobs: list[dict], tech_stack: list[str]) -> dict:
    """Agent 1: Are there open positions? Which ones fit our profile?"""
    jobs_str = json.dumps(jobs, indent=2) if jobs else "No remote jobs found on RemoteOK."
    stack_str = ", ".join(tech_stack[:8]) if tech_stack else "unknown"

    prompt = f"""You are a job-fit analyst for a Rust MCP infrastructure engineer.

CANDIDATE POSITIONING:
- Rust systems engineer building AI agent infrastructure
- Speciality: MCP servers, zero-GC performance, compliance-ready agent tooling
- Key proof: production rmcp MCP server, 11 tools, tokio async, SQLite, PII filter, audit log

TARGET COMPANY: {company}
DETECTED TECH STACK: {stack_str}
OPEN REMOTE POSITIONS FOUND:
{jobs_str}

TASK: Return ONLY valid JSON, no other text:
{{
  "has_open_position": true/false,
  "relevant_positions": [
    {{"title": "...", "url": "...", "fit_score": 1-10, "why": "one sentence"}}
  ],
  "best_position": "title of best match or null",
  "fit_score": 0-10,
  "fit_reason": "why this company/role is a strong or weak fit in 1-2 sentences",
  "stack_overlap": ["Rust technologies or concepts that overlap with our skills"]
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "job_scanner")


async def agent_collab_scanner(client, company: str, issues: list[dict], tech_stack: list[str]) -> dict:
    """Agent 2: Are there GitHub contribution entry points or collaboration angles?"""
    issues_str = json.dumps(issues, indent=2) if issues else "No open issues found."
    stack_str = ", ".join(tech_stack[:8]) if tech_stack else "unknown"

    prompt = f"""You are an open-source contribution strategist.

CANDIDATE: Rust MCP infrastructure engineer. Can contribute to:
- Rust async systems, MCP protocol implementations, CLI tooling
- Performance optimization (removing Python, adding Rust)
- AI agent tooling, LLM integrations, protocol design

TARGET COMPANY: {company}
TECH STACK: {stack_str}
OPEN GITHUB ISSUES:
{issues_str}

TASK: Return ONLY valid JSON:
{{
  "has_entry_point": true/false,
  "contribution_opportunities": [
    {{"repo": "...", "issue": "...", "url": "...", "angle": "how our Rust/MCP skills apply"}}
  ],
  "best_opportunity": "one line description of best first contribution",
  "collab_angle": "broader collaboration pitch — what can we build together?",
  "open_for_collaboration": true/false,
  "collaboration_signal": "evidence they value community contributions (e.g. open-source, MCP adoption, etc.)"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "collab_scanner")


async def agent_shortlist_scorer(client, company: str, prospect: dict, tech_stack: list[str]) -> dict:
    """Agent 3: Should this company be in our top shortlist? Score and rank."""
    stack_str = ", ".join(tech_stack[:8]) if tech_stack else "unknown"
    notes = prospect.get("notes", "")
    source = prospect.get("source", "")

    prompt = f"""You are a strategic outreach prioritizer for a Rust MCP engineer targeting compliance-heavy companies.

OUR WEDGE:
- Rust MCP server = faster + more compliant than Python alternatives
- Target pain points: enterprises blocked by compliance teams from deploying AI agents
- Best fits: FinTech, LegalTech, HealthTech, enterprise SaaS, defense-adjacent

COMPANY: {company}
SOURCE: {source}
TECH STACK: {stack_str}
NOTES: {notes[:300]}

SCORING CRITERIA:
+3  Uses Rust or Go (systems language = they get performance)
+3  FinTech/LegalTech/HealthTech/Gov (regulatory pressure = our compliance layer matters)
+2  AI/agent company (our infra is their core need)
+2  Series A/B startup (budget + urgency + small enough to move fast)
+2  Open source contributor (collaboration angle exists)
+1  Remote-first culture
-2  Big Tech/FAANG (too slow, no budget owner, generic roles)
-2  Pure frontend/consumer app (no systems programming need)
-3  No tech overlap with our skills

TASK: Return ONLY valid JSON:
{{
  "shortlist_score": 0-10,
  "priority": "high | medium | low | skip",
  "score_breakdown": {{"rust_affinity": 0-3, "regulatory_pull": 0-3, "ai_need": 0-2, "stage_fit": 0-2}},
  "why_shortlist": "one sentence on why they should/shouldn't be prioritized",
  "best_angle": "compliance | performance | rarity | timing",
  "outreach_hook": "one specific sentence to open the email — references their actual situation"
}}"""

    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.content[0].text, "shortlist_scorer")


# ─── Decision router ─────────────────────────────────────────────────────────

def decide_pathway(job: dict, collab: dict, score: dict) -> dict:
    """
    Combine 3 agent outputs → one pathway decision.

    PATH_A: Open position + good fit → apply + targeted outreach
    PATH_B: GitHub entry point → contribute first → then outreach
    PATH_C: No opening, no GitHub issue → pure cold outreach
    """
    has_job = job.get("has_open_position") and job.get("fit_score", 0) >= 6
    has_entry = collab.get("has_entry_point")
    priority = score.get("priority", "low")
    shortlist_score = score.get("shortlist_score", 0)

    if shortlist_score < 4 or priority == "skip":
        return {
            "pathway": "skip",
            "reason": score.get("why_shortlist", "Low fit"),
            "action": None,
        }

    if has_job:
        return {
            "pathway": PATH_A,
            "reason": f"Open position: {job.get('best_position')} (fit: {job.get('fit_score')}/10)",
            "action": f"Apply + email hiring manager. JD: {job.get('best_position')}",
            "first_step": "python cli.py cv + python cli.py email",
        }
    elif has_entry:
        return {
            "pathway": PATH_B,
            "reason": f"GitHub entry: {collab.get('best_opportunity')}",
            "action": f"Open PR/issue on {collab.get('contribution_opportunities', [{}])[0].get('repo', '?')} first. Then email.",
            "first_step": f"Contribute to GitHub → then python cli.py email with contribution as signal",
        }
    else:
        return {
            "pathway": PATH_C,
            "reason": "No open position or GitHub entry found. Cold outreach.",
            "action": f"Signal: {score.get('outreach_hook')}",
            "first_step": f"python cli.py email --signal \"{score.get('outreach_hook', '')}\"",
        }


# ─── Main entry point ─────────────────────────────────────────────────────────

async def research_company_async(prospect: dict) -> dict:
    """Run all 3 agents in parallel for one company. Returns full research profile."""
    company = prospect.get("company", "Unknown")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    print(f"\n  [research] {company}")

    # ── Data gathering (parallel HTTP calls) ──
    github_org = extract_github_org(prospect)
    notes = prospect.get("notes", "")
    website = None
    for word in notes.split():
        if "website:" in word:
            website = word.replace("website:", "").strip()
            break

    jobs, issues, tech_stack = await asyncio.gather(
        asyncio.to_thread(fetch_remote_jobs, company),
        asyncio.to_thread(fetch_open_issues, github_org or "", github_token),
        asyncio.to_thread(fetch_tech_stack, website or company),
    )

    print(f"    jobs={len(jobs)} issues={len(issues)} stack={len(tech_stack)}")

    # ── Claude agents (parallel) ──
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    job_analysis, collab_analysis, shortlist = await asyncio.gather(
        agent_job_scanner(client, company, jobs, tech_stack),
        agent_collab_scanner(client, company, issues, tech_stack),
        agent_shortlist_scorer(client, company, prospect, tech_stack),
    )

    pathway = decide_pathway(job_analysis, collab_analysis, shortlist)

    result = {
        "company": company,
        "prospect_id": prospect.get("id"),
        "tech_stack": tech_stack,
        "pathway": pathway,
        "job_analysis": job_analysis,
        "collab_analysis": collab_analysis,
        "shortlist": shortlist,
    }

    # Save output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in company if c.isalnum() or c in "-_").lower()
    (OUTPUT_DIR / f"research_{safe}.json").write_text(json.dumps(result, indent=2))

    return result


def research_company(prospect: dict) -> dict:
    """Sync wrapper for research_company_async."""
    return asyncio.run(research_company_async(prospect))


async def research_batch_async(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    """Research multiple companies with controlled concurrency."""
    sem = asyncio.Semaphore(concurrency)

    async def bounded(p):
        async with sem:
            return await research_company_async(p)

    return await asyncio.gather(*[bounded(p) for p in prospects])


def research_batch(prospects: list[dict], concurrency: int = 3) -> list[dict]:
    return asyncio.run(research_batch_async(prospects, concurrency))


# ─── Printing ─────────────────────────────────────────────────────────────────

def print_research_report(results: list[dict]) -> None:
    sep = "─" * 65
    print(f"\n{sep}")
    print(f"RESEARCH REPORT — {len(results)} companies")
    print(sep)

    path_counts = {PATH_A: [], PATH_B: [], PATH_C: [], "skip": []}
    for r in results:
        p = r["pathway"].get("pathway", "skip")
        path_counts.get(p, path_counts["skip"]).append(r["company"])

    print(f"\n  PATH A (apply + outreach):      {len(path_counts[PATH_A])} companies")
    for c in path_counts[PATH_A]:
        print(f"    → {c}")

    print(f"\n  PATH B (contribute → outreach): {len(path_counts[PATH_B])} companies")
    for c in path_counts[PATH_B]:
        print(f"    → {c}")

    print(f"\n  PATH C (cold outreach):         {len(path_counts[PATH_C])} companies")
    for c in path_counts[PATH_C]:
        print(f"    → {c}")

    print(f"\n  SKIPPED (low fit):              {len(path_counts['skip'])} companies")

    print(f"\n{sep}")
    print("TOP PRIORITY (score ≥ 7):")
    high = [r for r in results if r["shortlist"].get("shortlist_score", 0) >= 7]
    high.sort(key=lambda x: x["shortlist"].get("shortlist_score", 0), reverse=True)
    for r in high:
        score = r["shortlist"].get("shortlist_score", 0)
        pathway = r["pathway"].get("pathway", "?")
        hook = r["shortlist"].get("outreach_hook", "")
        print(f"\n  [{score}/10] {r['company']}  [{pathway}]")
        print(f"  Hook: {hook}")
        print(f"  Next: {r['pathway'].get('first_step', '')}")
    print(sep)


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
