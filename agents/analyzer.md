# Research / Analyzer Agent

**Role:** Company intelligence, tech stack detection, email discovery, signal extraction  
**Runtime:** Python (`prospect_bridge.py`)  
**Model:** None (calls external APIs directly, no LLM needed for enrichment)  
**Triggered by:** `python cli.py bridge` or `python cli.py run`

---

## Responsibility

Takes raw prospects from Networking Agent (status=`new`) and enriches them before Outreach Agent writes emails. Owns the "know before you contact" layer.

What it does per prospect:
1. Extract domain from GitHub URL or notes field
2. Detect tech stack via WebReveal (what are they actually running?)
3. Find decision maker email via Hunter.io
4. Build signal string from available data
5. Update prospect record with new data
6. Advance status → `researched`
7. Hand off to Outreach Agent

---

## Tools Used

| Tool | Source | Key Output |
|---|---|---|
| WebReveal API | `https://api.webreveal.io/tech?url=<url>` | technologies[] array |
| Hunter.io API | `https://api.hunter.io/v2/domain-search` | email, name, role, confidence |

Both called directly via `requests` in `prospect_bridge.py`. No MCP needed — batch Python process, not interactive.

---

## Inputs

```
HUNTER_API_KEY        Hunter.io (free tier: 25 searches/mo)
NETWORKING_DB         Path to SQLite (reads 'new' prospects)
```

Prospect fields used:
```
notes       → extract website domain (URL pattern match)
github      → extract domain from github.com/<org> → find company website
company     → fallback for domain inference
source      → "yc" gets "YC-backed" signal tag
```

---

## Signal Construction

The signal feeds directly into the Outreach Agent prompt. Quality here determines email quality.

```python
# Example signal outputs per prospect:
"YC-backed company; runs Rust, Go in production"
"stack includes React, Postgres, Kubernetes; source: github"
"found via YC W25 batch; fintech, Singapore"
```

Priority signals:
- Stack uses Rust/Go/C++ → "runs systems languages in production" (matches our positioning)
- Source = YC → add batch + funding context
- Notes contain job posting → "actively hiring [role]"
- Company blog/website → scrape for recent product launches (future: Research Agent v2)

---

## Email Discovery Priority

Hunter.io returns multiple contacts. We rank them:

```
Priority 1: CTO / Chief Technology Officer
Priority 2: Co-Founder / Founder
Priority 3: VP Engineering / Head of Engineering
Priority 4: Highest confidence score (fallback)
```

If no email found → prospect marked `skipped_no_email` → listed in summary for manual lookup.

---

## Outputs

Updates SQLite:
```sql
UPDATE prospects SET email = ?, notes = notes || '\ntech_stack: ...' WHERE id = ?
```

Logs to `tool_call_log` (via prospect_bridge, not Rust compliance layer):
```
Hunter.io call: domain=acme.com → found john@acme.com (CTO, confidence: 91)
WebReveal call: url=acme.com → Rust, Postgres, AWS detected
```

---

## Configuration

```bash
export HUNTER_API_KEY=your_key_here
export NETWORKING_DB=~/networking-agent.db
export ANTHROPIC_API_KEY=sk-ant-...   # needed for Outreach Agent (called after)

# Run enrichment only (no outreach generation)
python cli.py bridge --skip-enrichment  # skip WebReveal + Hunter
python cli.py bridge --dry-run          # preview what would run
python cli.py bridge --limit 10         # process 10 prospects max
```

---

## Rate Limits

| Service | Free Tier | Paid |
|---|---|---|
| WebReveal | Unlimited (free, no key) | N/A |
| Hunter.io | 25 searches/month | $49/mo → 500/mo |

→ At 25 free searches: enough for 25 targeted companies/month on free tier.
→ Upgrade Hunter.io to $49/mo when pipeline exceeds 25 companies/month.

---

## Future: Research Agent v2

Currently missing (manual gap):
- Company blog scraping → recent product launches → better outreach signals
- LinkedIn company page → headcount growth → "scaling fast" signal
- Crunchbase/OpenVC → funding round → "just raised Series A" signal
- Job postings → "actively hiring Rust engineers" signal

Next build: `tools/research.rs` in Rust — scraper + OpenVC API for funding signals.

---

## Handoff → Outreach Agent

After enrichment, calls:
```python
outreach_agent.generate_outreach(
    company_name=company,
    contact_name=contact_name,
    contact_role=contact_role,
    contact_email=email,
    tech_stack=tech_stack,       # from WebReveal
    signal=signal,               # constructed from all available data
)
```
