# networking-agent

Rust MCP server for autonomous technical outreach — 2-direction pipeline that discovers funded companies, analyzes their GitHub org for real pain points, drafts peer-tone proposals or warm candidate emails, and sends only after human confirmation.

**55 tools · 7 modules · 12 external APIs · SQLite pipeline · Google Sheets export**

---

## Two Directions

| | Dir A — Proposal (70%) | Dir B — Job (30%) |
|---|---|---|
| **Target** | Any funded startup with tech pain | Startup with open engineering role |
| **Gate** | Pain signal ≥ Medium from GitHub analysis | Real OSS PR acknowledged/merged first |
| **Tone** | Peer — technical depth, no cover letter feel | Candidate — portfolio link, contribution ref |
| **Email from** | saraswatdas94@gmail.com | saraswatdas94@gmail.com |

---

## Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│             Claude Code / Claude Desktop (orchestrator)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │  JSON-RPC 2.0 · stdin/stdout
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│          networking-agent  (Rust · rmcp 1.7.0 · 55 tools)       │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ DISCOVER │→ │ ANALYZE  │→ │  ROUTE   │→ │ PROPOSE/EMAIL  │  │
│  │  13 tools│  │ depth+   │  │ Dir A/B  │  │  6+5 tools     │  │
│  │          │  │ 7d cache │  │          │  │  "send it" gate│  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  SQLite (sqlx)  ·  6 tables                                │ │
│  │  prospects · contributions · outreach_log                  │ │
│  │  proposals · analysis_cache (7d TTL) · tool_call_log       │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │  HTTPS (rustls TLS 1.3)
         ┌─────────────────┼─────────────────────┐
         ▼                 ▼                      ▼
    GitHub API        YC · HN · RSS          Apollo · Hunter
    issues/orgs/      Remotive · WWR          Crunchbase · PH
    trending          Wellfound               WebReveal
```

### Direction A — Proposal

```
search_funding_news / search_github_trending / search_hn_hiring
    ↓
save_prospect + analyze_company_depth   ← cached 7 days
    ↓
route_prospect → direction: proposal
    ↓
draft_company_proposal   ← reads cache, no re-analysis
    ↓
draft_proposal_email     ← peer tone, auto-filled, no placeholder
    ↓  (human "send it" required)
log_email_sent → outreach_status: emailed
```

### Direction B — Job

```
search_workatastartup / search_hn_hiring / search_remotive
    ↓
save_prospect + route_prospect → direction: job
    ↓
list_org_repos → score_repo_issues ≥60 → open real PR
    ↓
track_contribution (wait for acknowledgment)
    ↓
draft_warm_email tone=candidate
    ↓  (human "send it" required)
log_email_sent
```

---

## Tool Registry — 55 tools

### Discover (13)

| Tool | Source | Auth |
|---|---|---|
| `search_funding_news` | TechCrunch + EU-Startups + Sifted RSS | free |
| `search_github_trending` | GitHub trending by language | free / `GITHUB_TOKEN` |
| `search_workatastartup` | YC companies hiring now | free |
| `get_yc_companies` | YC batch (W24, S25, W25, F26…) | free |
| `search_yc_companies` | YC keyword + location | free |
| `search_hn_hiring` | "Ask HN: Who is Hiring?" via Algolia | free |
| `search_wwr` | We Work Remotely RSS | free |
| `search_jobs` | RemoteOK by tag | free |
| `search_producthunt` | Recently launched products | `PRODUCTHUNT_API_TOKEN` |
| `search_crunchbase` | Funded startups by size/category | `CRUNCHBASE_API_KEY` |
| `search_github_repos` | Repos by language + topic | `GITHUB_TOKEN` |
| `search_remotive` | Remotive.io — global remote (EU/Asia/LATAM) | free |
| `search_wellfound` | Wellfound — seed/Series A with equity | free |

### Enrich (4)

| Tool | Source | Auth |
|---|---|---|
| `enrich_company` | Clearbit: size, funding, tech stack, social | `CLEARBIT_API_KEY` |
| `lookup_tech_stack` | WebReveal live detection from URL | free · unlimited |
| `search_crunchbase` | Funding/size fallback | `CRUNCHBASE_API_KEY` |
| `rdap_domain` | RDAP domain lookup — registrant, dates | free |

### Find People (5)

| Tool | Source | Auth |
|---|---|---|
| `search_apollo_people` | Apollo.io — name/title/LinkedIn free, email = 1 credit | `APOLLO_API_KEY` |
| `get_yc_company_team` | GitHub org lookup by company name | `GITHUB_TOKEN` |
| `get_org_members` | All public members of GitHub org | `GITHUB_TOKEN` |
| `search_github_users` | GitHub user search by role + location | `GITHUB_TOKEN` |
| `find_email_by_name` | Pattern guess + Hunter verify | `HUNTER_API_KEY` |

### Email Waterfall (5)

```
1. Apollo email reveal (50 credits/mo)
2. find_company_emails → Hunter.io domain search (25/mo)
3. GitHub public profile email
4. Pattern firstname@domain → verify via Hunter /email-verifier
```

| Tool | Purpose |
|---|---|
| `find_company_emails` | Hunter.io domain search — all emails at company |
| `find_person_email` | 4-step waterfall per person |
| `verify_email` | Hunter email verifier |
| `find_email_by_name` | Name → pattern variants → verify |
| `search_apollo_people` | Apollo people + optional email reveal |

### Contribute (7)

| Tool | Purpose |
|---|---|
| `list_org_repos` | Active repos for org — filters archived, zero-issue |
| `score_repo_issues` | Score issues 0–100: no-PR +30, unassigned +20, stack-match +20, age<14d +15 |
| `find_open_issues` | good-first-issue + help-wanted labels |
| `check_issue_activity` | Comment/PR count on specific issue |
| `check_repo_health` | Stars, forks, last-commit freshness |
| `track_contribution` | Log PR to DB: prospect_id + repo + issue + status |
| `list_contributions` | Query by status — find acknowledged PRs ready for email |

### Propose — Direction A (6)

| Tool | Purpose |
|---|---|
| `analyze_company_depth` | Deep GitHub org analysis: repos, issues, commits, pain points, tech stack. **Cached 7 days** |
| `draft_company_proposal` | Generate technical proposals from cached analysis — stored in proposals table |
| `route_prospect` | Decide Dir A vs B based on pain signals + open role |
| `draft_proposal_email` | Peer-tone email, auto-filled from cached analysis, no placeholders |
| `draft_warm_email` | Candidate-tone email (Dir B) with contribution reference |
| `check_role_fit` | Score role/company fit against skills profile |

### Pipeline & Sync (15)

| Tool | Purpose |
|---|---|
| `save_prospect` | Upsert to SQLite — dedupes on GitHub handle or email |
| `list_prospects` | Full pipeline with filters |
| `update_prospect_status` | Move through outreach funnel |
| `export_pipeline` | Sheet-ready JSON → google-workspace MCP |
| `log_email_sent` | Record send, enforce 8/day cap |
| `get_outreach_stats` | Summary: emailed, replied, rate |
| `list_followup_due` | Prospects past follow-up window |
| `check_already_contacted` | Dedup before outreach |
| `check_company_exists` | Dedup on company name/domain |
| `archive_stale_prospects` | Mark inactive prospects archived |
| `compute_fund_signal` | Score funding news item for relevance |
| `search_form_d` | SEC Form D filings — US funding signal |
| `search_gdelt_funding` | GDELT news — global funding mentions |
| `fr_company_lookup` | French company registry (SIRENE) |
| `uk_company_lookup` | UK Companies House API |

---

## Repository Structure

```
networking-agent/
├── src/
│   ├── main.rs              # Entry: env vars, DB init, MCP stdio loop
│   ├── server.rs            # NetworkingServer + 55 tool definitions
│   ├── db.rs                # SqlitePool init, schema (6 tables)
│   └── tools/
│       ├── mod.rs
│       ├── apollo.rs        # Apollo.io people + org search
│       ├── clearbit.rs      # Clearbit enrichment
│       ├── crunchbase.rs    # Crunchbase v4 autocomplete + search
│       ├── discovery.rs     # Funding RSS · Remotive · GitHub trending · Wellfound
│       ├── email_finder.rs  # Hunter waterfall + pattern variants
│       ├── github.rs        # GitHub REST v3 — users, orgs, issues, repos
│       ├── hiring.rs        # HN Algolia "Who is Hiring?"
│       ├── jobs.rs          # RemoteOK API
│       ├── platforms.rs     # WWR · WorkAtAStartup · GitHub repo search
│       ├── producthunt.rs   # ProductHunt GraphQL
│       ├── proposal.rs      # analyze_company_depth + draft_company_proposal
│       ├── scorer.rs        # Issue scoring 0–100 + repo health
│       ├── tech_stack.rs    # WebReveal live detection
│       └── yc.rs            # YC API — batch + keyword
├── agents/
│   ├── email_sender.py      # Sends via gmail_oauth → saraswatdas94@gmail.com
│   ├── gmail_oauth.py       # Google Gmail API OAuth2
│   ├── reply_monitor.py     # Poll inbox, update outreach_status=replied
│   └── sync_to_sheets.py    # Pipeline → Google Sheets
├── drafts/                  # Outreach drafts pending "send it"
├── migrations/              # SQLite schema migrations
├── CLAUDE.md                # Tool reference + workflow rules loaded by Claude Code
├── ARCHITECTURE.md          # Extended architecture notes
└── STRATEGY.md              # Outreach strategy + targeting notes
```

---

## SQLite Schema — 6 Tables

```sql
CREATE TABLE prospects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    company         TEXT,
    github          TEXT UNIQUE,
    email           TEXT,
    role            TEXT,
    location        TEXT,
    direction       TEXT,          -- 'proposal' | 'job' | NULL
    source          TEXT,
    outreach_status TEXT NOT NULL DEFAULT 'new',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contributions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id       INTEGER REFERENCES prospects(id),
    repo              TEXT NOT NULL,
    issue_number      INTEGER,
    issue_title       TEXT,
    pr_url            TEXT,
    status            TEXT NOT NULL DEFAULT 'drafted',
    -- drafted|submitted|acknowledged|merged|rejected
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE outreach_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id),
    subject     TEXT,
    body        TEXT,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    method      TEXT DEFAULT 'gmail_oauth'
);

CREATE TABLE proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id),
    pain_points TEXT,
    proposal    TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE analysis_cache (
    org_key    TEXT PRIMARY KEY,   -- github org slug
    data       TEXT,               -- JSON blob
    expires_at DATETIME
    -- 7-day TTL, instant on repeat calls
);

CREATE TABLE tool_call_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name  TEXT NOT NULL,
    args       TEXT,
    called_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Outreach Rules (enforced in code + CLAUDE.md)

- **From:** `saraswatdas94@gmail.com` only — never aits.group Gmail MCP
- **Cap:** 8 emails/day enforced by `log_email_sent`
- **Gate:** Human "send it" confirmation required before every send
- **Dir B gate:** PR must be acknowledged/merged before emailing
- **Style:** No "Dear Name", no teaser hooks — state problem + solution plainly
- **Signoff:** Always includes `https://saraswat.vercel.app/`

---

## Tech Stack

| Layer | Crate | Version |
|---|---|---|
| MCP Protocol | `rmcp` | 1.7.0 |
| Async Runtime | `tokio` | 1.x |
| HTTP Client | `reqwest` | 0.13 |
| TLS | `rustls` | 0.23 |
| Database | `sqlx` | 0.8 |
| Serialization | `serde` + `serde_json` | 1.0 |
| JSON Schema | `schemars` | 1.x |
| Date math | `chrono` | 0.4 |
| Error handling | `anyhow` | 1.0 |

---

## Environment Variables

| Variable | Status | Notes |
|---|---|---|
| `GITHUB_TOKEN` | **Required** | PAT with `read:user`, `read:org` |
| `APOLLO_API_KEY` | **Set** | 50 email reveals/mo free |
| `HUNTER_API_KEY` | **Set** | 25 domain searches/mo free |
| `CRUNCHBASE_API_KEY` | Optional | 200 req/mo free |
| `CLEARBIT_API_KEY` | Optional | 50 lookups/mo free |
| `PRODUCTHUNT_API_TOKEN` | Optional | OAuth token |
| `NETWORKING_DB` | Optional | SQLite path (default: `~/networking-agent.db`) |

---

## Setup

```bash
git clone https://github.com/Saraswat123/Networking-Agent.md-.git
cd Networking-Agent.md-

cargo build --release

# Register with Claude Code
claude mcp add networking-agent \
  -s user \
  -e GITHUB_TOKEN="ghp_yourtoken" \
  -e APOLLO_API_KEY="your_apollo_key" \
  -e HUNTER_API_KEY="your_hunter_key" \
  -e NETWORKING_DB="$HOME/networking-agent.db" \
  -- ./target/release/networking-agent
```

### Email Setup (Gmail OAuth)

```bash
# One-time browser auth for saraswatdas94@gmail.com
python3 agents/gmail_oauth.py
# → token.json saved at ~/networking-agent/token.json
```

### Google Sheets Sync

```bash
python3 agents/sync_to_sheets.py
# Writes all prospects + funding leads to Google Sheets
# Sheet: https://docs.google.com/spreadsheets/d/1ut16oQPDTcR--06U5IsPw-D8iC5LhiqQ1CK2k_wwUdg
```

---

## Pipeline Status (2026-09-21)

| Metric | Value |
|---|---|
| Total prospects | 135 |
| Emailed | 4 (ReJot, Laminar, HumanLayer + 1 pending) |
| Active PR (Dir B) | #12937 on rerun-io/rerun — waiting ack |
| Funding leads queued | 5 (Exein HIGH, Euclyd MEDIUM, Crusoe/CompAI/Evvy low) |
| Reply rate | Tracking via reply_monitor.py |

---

## License

MIT
