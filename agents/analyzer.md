# Research / Analyzer Agent

**Role:** Multi-agent company intelligence — shortlisting, open position detection, collaboration opportunity scanning  
**Runtime:** Python (`research_agent.py`) — 3 Claude agents run in parallel per company  
**Model:** `claude-opus-4-8` × 3 agents (parallel async)  
**Triggered by:** `python cli.py research`

---

## Multi-Agent Architecture

Three specialized Claude agents run simultaneously per company. Each owns one question. A Decision Router combines their outputs into one pathway.

```
Company prospect (from Networking Agent)
         │
         ├── [parallel data fetch]
         │     ├── RemoteOK → open jobs at company
         │     ├── GitHub API → open issues in company org
         │     └── WebReveal → live tech stack
         │
         ├── [3 Claude claude-opus-4-8 agents, parallel]
         │     ├── Agent 1: Job Scanner
         │     │     "Are there open positions? Which ones fit our profile?"
         │     │
         │     ├── Agent 2: Collaboration Scanner
         │     │     "Is there a GitHub entry point or open-source angle?"
         │     │
         │     └── Agent 3: Shortlist Scorer
         │           "Score this company 0-10. Should we prioritize them?"
         │
         └── [Decision Router]
               ├── PATH A → open position found (fit ≥ 6)
               ├── PATH B → GitHub entry point found
               └── PATH C → no opening, cold outreach
```

---

## Three Agents

### Agent 1 — Job Scanner

**Question:** Does this company have an open position that matches our skills?

**Data in:** RemoteOK jobs filtered by company name, detected tech stack  
**Claude does:** Scores each position for fit, picks best match, rates overall company-role fit 0-10

**Output:**
```json
{
  "has_open_position": true,
  "relevant_positions": [{"title": "Rust Backend Engineer", "fit_score": 9, "why": "Requires async Rust, MCP integration mentioned"}],
  "best_position": "Rust Backend Engineer",
  "fit_score": 9,
  "stack_overlap": ["Rust", "tokio", "async"]
}
```

**Threshold for PATH A:** `has_open_position = true` AND `fit_score ≥ 6`

---

### Agent 2 — Collaboration Scanner

**Question:** Is this company open to collaboration? Is there a GitHub contribution entry point?

**Data in:** GitHub issues (good-first-issue, help-wanted) from top 3 org repos  
**Claude does:** Identifies which issues match our Rust/MCP skills, builds collaboration pitch angle

**Output:**
```json
{
  "has_entry_point": true,
  "contribution_opportunities": [
    {"repo": "agent-sdk", "issue": "Add Rust MCP transport layer", "angle": "Exactly what we've shipped"}
  ],
  "best_opportunity": "PR: Add Rust stdio transport to their Python MCP SDK",
  "collab_angle": "We've already built a production Rust MCP server — merge ours into theirs",
  "open_for_collaboration": true,
  "collaboration_signal": "12 open issues tagged help-wanted, active maintainer responses"
}
```

**Threshold for PATH B:** `has_entry_point = true` (used only if PATH A not triggered)

---

### Agent 3 — Shortlist Scorer

**Question:** Should this company be in our priority shortlist? Why?

**Data in:** Company notes, source (YC/GitHub), tech stack  
**Claude does:** Scores against our positioning wedge, picks best outreach angle

**Scoring matrix:**
```
+3  Uses Rust or Go (systems language → they understand performance)
+3  FinTech / LegalTech / HealthTech / Gov (regulatory pressure → compliance layer matters)
+2  AI/agent company (our infra = their core need)
+2  Series A/B startup (budget + urgency + small enough to move fast)
+2  Open source contributor (collaboration angle exists)
+1  Remote-first
-2  FAANG / Big Tech (too slow, no budget owner)
-2  Pure frontend / consumer app (no systems need)
-3  No tech overlap
```

**Output:**
```json
{
  "shortlist_score": 8,
  "priority": "high",
  "score_breakdown": {"rust_affinity": 3, "regulatory_pull": 2, "ai_need": 2, "stage_fit": 1},
  "why_shortlist": "Rust-heavy FinTech in compliance-heavy space — exact fit for our compliance MCP layer",
  "best_angle": "compliance",
  "outreach_hook": "Ramp's finance AI agents hit PCI scope the moment they call a tool — our Rust MCP server has the audit trail your compliance team needs."
}
```

---

## Decision Router

Combines all 3 agents into one pathway:

| Condition | Pathway | Action |
|---|---|---|
| `shortlist_score < 4` | **SKIP** | Don't reach out |
| `has_open_position AND fit ≥ 6` | **PATH A** | Apply for job + email hiring manager |
| `has_entry_point = true` | **PATH B** | Open PR/issue first → then outreach |
| Neither | **PATH C** | Cold outreach with collaboration pitch |

---

## Pathway Actions

### PATH A — Apply + Outreach
```bash
# 1. Generate tailored CV
python cli.py cv --jd <company>_jd.txt --company "Ramp" --role "Rust Backend Engineer"

# 2. Generate email to hiring manager
python cli.py email \
  --company "Ramp" --contact "Head of AI" \
  --signal "open Rust Backend Engineer role, finance AI stack" \
  --stack "Rust,Go,Postgres"
```

### PATH B — Contribute First → Then Outreach
```bash
# 1. Open GitHub PR or meaningful issue on their repo
#    (contribution is the signal for the email)

# 2. After contribution merged/acknowledged:
python cli.py email \
  --company "Acme" \
  --signal "just merged PR #123 adding Rust stdio transport to your MCP SDK"
```
This gets reply rates 3-5× higher than cold email — you're not a stranger, you shipped code for them.

### PATH C — Cold Outreach
```bash
python cli.py email \
  --company "Ironclad" \
  --contact "CTO" \
  --signal "contract data + Python MCP = attorney-client privilege risk"
  # hook from Agent 3's outreach_hook field
```

---

## Running Research

```bash
# Research all 'new' prospects
python cli.py research --limit 10 --concurrency 3

# Research only high-fit companies (score ≥ 7)
python cli.py research --limit 20 --min-score 7

# Research 'researched' prospects (re-check for new openings)
python cli.py research --status researched --limit 10
```

**Output per run:**
- Terminal report: companies grouped by pathway, top priority list with hooks
- `agents/output/research/<company>.json` — full analysis per company

---

## Concurrency Model

```
asyncio.gather() — 3 agents per company run simultaneously
asyncio.Semaphore(N) — controls how many companies process at once

Default: concurrency=3
  → 3 companies × 3 agents = 9 parallel Claude calls
  → Full batch of 10 companies ≈ 4 API round trips
  → Typical runtime: 45-90 seconds for 10 companies
```

---

## Inputs

```
ANTHROPIC_API_KEY    Required — claude-opus-4-8 × 3 agents
GITHUB_TOKEN         Required — for open issue discovery
HUNTER_API_KEY       Optional — email finding (called in bridge, not research)
NETWORKING_DB        SQLite path (reads 'new' or 'researched' prospects)
```

---

## Integration with Full Pipeline

```
python cli.py run --query "AI FinTech" --mode yc --no-bridge
  └── Networking Agent discovers + saves 20 companies (status='new')

python cli.py research --limit 20
  └── Research Agent:
       ├── PATH A companies (5) → python cli.py cv + email
       ├── PATH B companies (3) → contribute to GitHub first
       └── PATH C companies (8) → python cli.py bridge (standard cold outreach)

python cli.py dashboard
  └── Shows funnel by status
```

---

## Future: Research Agent v2

- **Funding signals:** OpenVC/Crunchbase API → "just raised Series B" in signal
- **Product launch signals:** Scrape company blog → "shipped v2 last week" signal
- **Hiring velocity:** Track job posting count over time → "headcount growing fast"
- **LinkedIn intelligence:** Company follower growth → momentum signal
- **GitHub activity:** Commit velocity, star growth → engineering team health
