# Job Agent

**Role:** Remote job discovery, JD parsing, opportunity scoring  
**Runtime:** Python (`cli.py` → `cv_agent.analyze_jd()` + `orchestrator.search_remoteok`)  
**Model:** `claude-opus-4-8` (JD analysis only)  
**Triggered by:** `python cli.py run` or `python cli.py analyze`

---

## Responsibility

Finds relevant job postings, parses them into structured signal data, scores fit against candidate profile, and triggers CV Agent for tailored applications. Bridges the "apply to jobs" workflow alongside the "cold outreach" workflow.

---

## Data Sources

| Source | API | Filter | Free |
|---|---|---|---|
| RemoteOK | `https://remoteok.com/api?tags=<tags>` | Tags: rust, typescript, senior, ml, etc. | Yes |
| GitHub Jobs | Deprecated — not used | — | — |
| Wellfound | Requires Apify (future) | — | $49/mo |
| LinkedIn | Requires Apify (future) | — | $49/mo |

Current default: **RemoteOK only** (free, no key, live feed).

---

## Tool: `search_jobs` (Rust MCP)

```
search_jobs(tags="rust,senior", limit=20)
→ returns: title, company, company_url, url, location, tags, salary_min, salary_max, date, description_snippet
```

Rate limit: 30 calls/min (compliance layer).

---

## JD Analysis (Claude)

`cv_agent.analyze_jd(jd_text)` → structured JSON:

```json
{
  "role_type": "backend | frontend | fullstack | ml | devtools | protocol | infra",
  "seniority": "junior | mid | senior | staff | lead",
  "must_have": ["Rust", "async", "distributed systems"],
  "nice_to_have": ["MCP", "protocol engineering", "WASM"],
  "stack": ["Rust", "Postgres", "Kubernetes"],
  "hiring_signals": ["Series B", "team of 20", "fast-growing"],
  "culture_tags": ["remote-first", "open-source", "research"]
}
```

Used by:
- CV Agent → reorder skills section, rewrite bullet points
- Outreach Agent → match tech stack to our positioning

---

## Opportunity Scoring (built into profile.json)

Score each job against `profile.json → target_roles`:

```
+3  Rust is required or in stack
+2  MCP / protocol engineering mentioned
+2  Agent infrastructure / LLM tooling
+1  Remote-first
+1  Seed / Series A / Series B (early = more impact)
-2  Requires 5+ years of [language we don't know]
-3  FAANG / Big Tech generic role (low signal-based leverage)
```

High score → apply + cold outreach to hiring manager  
Low score → skip or apply without outreach

---

## Inputs

```
ANTHROPIC_API_KEY    For JD analysis
```

Job description file (plain text):
```bash
python cli.py analyze --jd path/to/jd.txt
python cli.py cv --jd path/to/jd.txt --company "Stripe" --role "Backend Engineer"
```

Or from search:
```bash
python cli.py run --query "Rust protocol engineer" --mode github --no-bridge
# discovers GitHub users at companies hiring Rust engineers
```

---

## Outputs

`cv_agent.analyze_jd()` returns dict → consumed by:
- `cv_agent.generate_cv()` for tailored CV
- `outreach_agent.generate_outreach()` for targeted email

Saved to `agents/output/cvs/cv_<company>_<role>.md`

---

## Configuration: Scoring Targets

Edit `profile.json → target_roles` to adjust what scores high:

```json
"target_roles": [
  "MCP Infrastructure Engineer",
  "Agent Infrastructure Engineer",
  "Rust Backend Engineer (AI/LLM tooling)",
  "Protocol Engineer",
  "Developer Tools Engineer (Rust)"
]
```

Add/remove to shift what the CV Agent emphasizes and what Job Agent flags as high-priority.

---

## Workflow: Full Job Application Pipeline

```
Step 1 — Find job
  python cli.py run --query "Rust engineer" --mode github --no-bridge
  OR: manually paste JD into a .txt file

Step 2 — Analyze JD
  python cli.py analyze --jd stripe_jd.txt
  → see what Claude extracts: must-haves, stack, seniority

Step 3 — Generate tailored CV
  python cli.py cv --jd stripe_jd.txt --company "Stripe" --role "Backend Engineer"
  → streams CV to terminal, saves to agents/output/cvs/

Step 4 — Find hiring manager + generate outreach
  python cli.py email \
    --company "Stripe" \
    --contact "David Singleton" \
    --role "VP Engineering" \
    --to "david@stripe.com" \
    --signal "just posted Rust backend role" \
    --stack "Rust,Go,Postgres" \
    --jd stripe_jd.txt
  → email + LinkedIn message + 2 follow-ups saved to agents/output/emails/
```

---

## Future: Job Agent v2

- Wellfound scraper via Apify → startup jobs with equity data
- LinkedIn job search → corporate roles
- Auto-score + rank opportunities (skip manual review for low scores)
- Weekly job digest: new postings matching target_roles sent to terminal
