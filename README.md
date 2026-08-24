# networking-agent

A Rust MCP server for autonomous job search — contribution-first pipeline that discovers companies, scores GitHub issues, tracks PRs, and triggers warm outreach only after a real contribution is acknowledged.

**31 tools · 10 external APIs · SQLite pipeline · Google Sheets export · Compliance built-in**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Claude Code / Claude Desktop               │
│                      (MCP orchestrator)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │  JSON-RPC 2.0 over stdin/stdout
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              networking-agent  (Rust release binary)         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ComplianceLayer  —  every tool call passes through  │   │
│  │  RateLimiter ──▶ execute ──▶ PiiFilter ──▶ AuditLog  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────┐   ┌──────────────────────────────────┐    │
│  │ rmcp 1.7.0  │   │  27 tools via #[tool_router]     │    │
│  │ MCP Server  │──▶│  12 modules — see Tool Registry  │    │
│  └─────────────┘   └──────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  SQLite (sqlx)  ·  prospects  ·  contributions       │   │
│  │                 ·  audit_log                         │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTPS (rustls TLS 1.3)
         ┌─────────────────┼──────────────────────┐
         ▼                 ▼                       ▼
    GitHub API        YC · HN · WWR          Apollo · Hunter
    (issues/orgs)     WAS · RemoteOK         Crunchbase · PH
                      ProductHunt            WebReveal
```

---

## 5-Stage Pipeline

```
01 DISCOVER ──▶ 02 ENRICH ──▶ 03 FIND PERSON ──▶ 04 CONTRIBUTE ──▶ 05 EMAIL
```

| Stage | Tools | Signal |
|---|---|---|
| **Discover** | workatastartup, hn_hiring, yc, producthunt, crunchbase, wwr, remoteok, funding_news, remotive, github_trending, wellfound | Companies actively hiring + recently funded |
| **Enrich** | enrich_company (WebReveal+CB+Hunter), lookup_tech_stack | Size, funding, tech stack |
| **Find Person** | search_apollo_people, get_yc_company_team, find_person_email | Name + verified email |
| **Contribute** | list_org_repos, score_repo_issues, track_contribution | Real PR on their repo |
| **Email** | list_contributions, draft_warm_email, export_pipeline | 3-sentence warm email after PR ack |

> **Rule:** Email sends only after contribution is acknowledged or merged. No cold spray.

---

## Tool Registry — 27 tools

### Discover (13)

| Tool | Source | Auth |
|---|---|---|
| `search_workatastartup` | YC companies hiring — HTML extract | free |
| `get_yc_companies` | YC batch (W25, S25…) | free |
| `search_yc_companies` | YC keyword + location | free |
| `search_hn_hiring` | "Ask HN: Who is Hiring?" via Algolia | free |
| `search_wwr` | We Work Remotely RSS | free |
| `search_jobs` | RemoteOK by tag | free |
| `search_producthunt` | Recently launched products | `PRODUCTHUNT_API_TOKEN` |
| `search_crunchbase` | Funded startups by size/category | `CRUNCHBASE_API_KEY` |
| `search_github_repos` | Repos by language + topic | `GITHUB_TOKEN` |
| `search_funding_news` | TechCrunch + EU-Startups + Sifted RSS — just-raised companies | free |
| `search_remotive` | Remotive.io — global remote jobs (EU/Asia/LATAM) | free |
| `search_github_trending` | GitHub trending repos by language — companies building NOW | free / `GITHUB_TOKEN` |
| `search_wellfound` | Wellfound (AngelList) startup jobs — seed/Series A companies | free |

### Enrich (2)

| Tool | Source | Auth |
|---|---|---|
| `enrich_company` | WebReveal (tech) + Crunchbase (meta) + Hunter (social) | free + optional keys |
| `lookup_tech_stack` | WebReveal — live detection from URL | free · unlimited |

### Find People (4)

| Tool | Source | Auth |
|---|---|---|
| `search_apollo_people` | Apollo.io — name/title/LinkedIn free, email = 1 credit | `APOLLO_API_KEY` |
| `get_yc_company_team` | GitHub org lookup by company name/domain | `GITHUB_TOKEN` |
| `get_org_members` | All public members of a GitHub org | `GITHUB_TOKEN` |
| `search_github_users` | GitHub user search by role + location | `GITHUB_TOKEN` |

### Email Waterfall (3)

| Tool | Logic | Auth |
|---|---|---|
| `find_person_email` | Hunter finder → GitHub profile → 6 pattern variants → Hunter verify | `HUNTER_API_KEY` |
| `find_company_emails` | Hunter domain search — all emails at company | `HUNTER_API_KEY` |
| `draft_warm_email` | DB join (contribution + prospect) → 3-sentence draft | SQLite only |

### Contribute (5)

| Tool | Purpose |
|---|---|
| `list_org_repos` | Active repos for GitHub org — filters archived, zero-issue |
| `score_repo_issues` | Score issues 0–100: no linked PR +30, unassigned +20, stack match +20, age <14d +15 |
| `find_open_issues` | good-first-issue + help-wanted in a repo |
| `track_contribution` | Log PR to DB: prospect_id + repo + issue + status |
| `list_contributions` | Query by status — find acknowledged PRs ready for email |

### Pipeline (4)

| Tool | Purpose |
|---|---|
| `save_prospect` | Upsert to SQLite — dedupes on GitHub handle |
| `list_prospects` | Full pipeline view |
| `update_prospect_status` | Move: new → researched → github_engaged → emailed → replied → meeting_scheduled |
| `export_pipeline` | Sheet-ready JSON → write to Google Sheets via google-workspace MCP |

---

## Repository Structure

```
networking-agent/
├── src/
│   ├── main.rs                  # Entry: env vars, DB init, MCP stdio loop
│   ├── server.rs                # NetworkingServer + 31 tool definitions + param structs
│   ├── db.rs                    # SqlitePool init, schema (3 tables)
│   ├── compliance/
│   │   ├── mod.rs               # ComplianceLayer struct
│   │   ├── audit.rs             # AuditLogger → audit_log per call
│   │   ├── pii.rs               # PiiFilter — email, phone, API key redaction
│   │   └── rate_limiter.rs      # Per-tool sliding window (tokio::Mutex)
│   └── tools/
│       ├── mod.rs
│       ├── apollo.rs            # Apollo.io — people + org search
│       ├── clearbit.rs          # Free enrichment: WebReveal + Crunchbase + Hunter
│       ├── crunchbase.rs        # Crunchbase v4 — autocomplete + search
│       ├── discovery.rs         # Funding news RSS · Remotive · GitHub trending · Wellfound
│       ├── email_finder.rs      # Hunter.io domain search + 4-step person waterfall
│       ├── github.rs            # GitHub REST v3 — users, orgs, issues
│       ├── hiring.rs            # HN Algolia — "Who is Hiring?" thread
│       ├── jobs.rs              # RemoteOK API
│       ├── platforms.rs         # WWR RSS · WorkAtAStartup HTML · GitHub repo search
│       ├── producthunt.rs       # ProductHunt GraphQL
│       ├── scorer.rs            # Issue scoring 0–100 + org repo lister
│       ├── tech_stack.rs        # WebReveal live tech detection
│       └── yc.rs                # YC API — batch + keyword search
├── Cargo.toml
└── CLAUDE.md                    # Tool reference loaded by Claude Code
```

---

## SQLite Schema

```sql
CREATE TABLE prospects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    github          TEXT UNIQUE,
    email           TEXT,
    company         TEXT,
    role            TEXT,
    location        TEXT,
    notes           TEXT,
    source          TEXT,
    outreach_status TEXT NOT NULL DEFAULT 'new',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contributions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id       INTEGER REFERENCES prospects(id),
    repo_owner        TEXT NOT NULL,
    repo_name         TEXT NOT NULL,
    issue_number      INTEGER,
    issue_title       TEXT,
    contribution_type TEXT NOT NULL DEFAULT 'pr',
    pr_url            TEXT,
    status            TEXT NOT NULL DEFAULT 'drafted',  -- drafted|submitted|acknowledged|merged|rejected
    notes             TEXT,
    submitted_at      DATETIME,
    acknowledged_at   DATETIME,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name      TEXT NOT NULL,
    input_summary  TEXT,   -- PII redacted before write
    output_summary TEXT,
    pii_types      TEXT,   -- JSON array of detected types
    duration_ms    INTEGER,
    called_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Compliance Layer

Every tool call passes through three gates before execution:

```
RateLimiter.check(tool_name)
  └── returns early with error string if limit hit — server never crashes

execute tool (HTTP call or SQLite query)

PiiFilter.detect_types(output)
  └── detects: email · api_key · phone · ip_address

AuditLogger.log() → audit_log (SQLite)
  └── tool_name · redacted input · pii_types · duration_ms
```

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
| `HUNTER_API_KEY` | Optional | 25 domain searches/mo free |
| `CRUNCHBASE_API_KEY` | Optional | 200 req/mo free |
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

---

## Sheets Sync

Claude bridges the SQLite pipeline to Google Sheets via the google-workspace MCP (if connected):

```
export_pipeline → JSON { prospects[], contributions[] }
     ↓
google-workspace MCP → modify_sheet_values
     ↓
Google Sheet: Sheet1 = Prospects · Sheet2 = Contributions
```

Say: **"sync to sheets"** — Claude runs the export and writes both tables automatically.

---

## License

MIT
