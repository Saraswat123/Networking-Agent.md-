# Networking Agent

A production Rust MCP server for autonomous prospect discovery, outreach generation, and enterprise-grade compliance. Integrates directly with Claude Code. No API billing — works with Claude Premium.

**Positioning:** The only MCP server built for regulated industries — audit trail, PII filter, and rate limiting built into every tool call at the Rust layer. No Python GC pauses. No memory-unsafe data handling.

---

## Repository Structure

```
networking-agent/
├── src/                         # Rust MCP server
│   ├── main.rs                  # Entry point — loads env, inits DB, starts MCP stdio loop
│   ├── server.rs                # NetworkingServer + all 11 tool definitions
│   ├── db.rs                    # SqlitePool init, schema creation (3 tables)
│   ├── compliance/              # Enterprise compliance layer
│   │   ├── mod.rs               # ComplianceLayer struct (audit + pii + rate_limiter)
│   │   ├── audit.rs             # AuditLogger — writes tool_call_log per invocation
│   │   ├── pii.rs               # PiiFilter — redacts email, API keys, phone, SSN, IP
│   │   └── rate_limiter.rs      # RateLimiter — per-tool sliding window (tokio::Mutex)
│   └── tools/                   # External API integrations
│       ├── mod.rs
│       ├── github.rs            # GitHub REST API v3 — search, org members, issues, profiles
│       ├── yc.rs                # YC API — batch fetch + keyword/location search
│       ├── tech_stack.rs        # WebReveal API — live tech stack detection
│       ├── email_finder.rs      # Hunter.io API — domain email discovery
│       └── jobs.rs              # RemoteOK API — remote job search by tag
│
├── agents/                      # Python outreach pipeline (Phase 2+)
│   ├── cli.py                   # Unified CLI: run | cv | email | analyze | bridge | dashboard
│   ├── orchestrator.py          # Discovery → DB save → bridge (full pipeline automation)
│   ├── prospect_bridge.py       # SQLite → enrichment → outreach generation
│   ├── cv_agent.py              # Claude claude-opus-4-8: JD parsing + tailored CV generation
│   ├── outreach_agent.py        # Claude claude-opus-4-8: signal-based email + follow-up sequences
│   ├── profile.json             # Candidate profile + positioning + target company tiers
│   ├── requirements.txt         # anthropic, typer, rich, requests
│   └── output/                  # Generated CVs and outreach packages (gitignored)
│       ├── cvs/
│       └── emails/
│
├── migrations/
│   └── 001_init.sql             # prospects + outreach_log + tool_call_log + indexes + trigger
│
├── Dockerfile                   # Multi-stage: rust:1.93-slim → debian:bookworm-slim (~15MB)
├── docker-compose.yml
├── Cargo.toml                   # anyhow, reqwest, rmcp, schemars, serde, sqlx, tokio, regex
├── CLAUDE.md                    # Tool reference + env vars (loaded by Claude Code)
└── ARCHITECTURE.md              # Deep technical dive: rmcp internals, tokio model, MCP wire protocol
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Claude Code / CLI                      │
└───────────────────────┬──────────────────────────────────┘
                        │  JSON-RPC 2.0 over stdin/stdout
                        │  (MCP Protocol)
┌───────────────────────▼──────────────────────────────────┐
│              networking-agent  (Rust binary)              │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  ComplianceLayer (every tool call)                  │ │
│  │  RateLimiter → execute → PiiFilter → AuditLogger    │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────┐   ┌──────────────────────────────────┐ │
│  │  rmcp 1.7   │   │  11 tools via #[tool_router]     │ │
│  │  MCP Server │──▶│  GitHub · YC · WebReveal ·       │ │
│  └─────────────┘   │  Hunter.io · RemoteOK · SQLite   │ │
│                    └──────────────────────────────────┘ │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  SQLite (sqlx)  ·  tool_call_log  ·  prospects      │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────┬─────────────────────────────┘
                             │  HTTPS (rustls TLS 1.3)
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         GitHub API      YC API       WebReveal / Hunter.io / RemoteOK

┌─────────────────────────────────────────────────────────┐
│  Python agents/  (Phase 2 — runs separately)            │
│                                                         │
│  orchestrator.py                                        │
│    ├── GitHub search → SQLite save                     │
│    ├── YC search → SQLite save                         │
│    └── → prospect_bridge.py                            │
│           ├── WebReveal tech stack per prospect        │
│           ├── Hunter.io email discovery                │
│           └── Claude claude-opus-4-8:                          │
│                 outreach_agent → email+LinkedIn+followups│
│                 cv_agent → tailored CV per JD          │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Library | Version | Role |
|---|---|---|---|
| MCP Protocol | `rmcp` | 1.7.0 | JSON-RPC 2.0 server, tool routing macros |
| Async Runtime | `tokio` | 1.52.3 | Multi-threaded async executor |
| HTTP Client | `reqwest` | 0.13.4 | Async HTTP/2 + connection pooling |
| TLS | `rustls` | 0.23 | Pure-Rust TLS 1.3 (no OpenSSL) |
| Database | `sqlx` | 0.8.6 | Async SQLite, compile-time query check |
| Serialization | `serde` + `serde_json` | 1.0 | Zero-copy JSON parse/emit |
| JSON Schema | `schemars` | 1.2.1 | Auto-generates tool parameter schemas |
| PII Detection | `regex` | 1.x | Email, API key, phone, SSN redaction |
| Error Handling | `anyhow` | 1.0.102 | Ergonomic `?` propagation |
| HTML Parsing | `scraper` | 0.27.0 | CSS selector fallback scraping |
| AI (Python) | `anthropic` | ≥0.40.0 | claude-opus-4-8 for CV + outreach |
| CLI (Python) | `typer` + `rich` | latest | Terminal interface + colored output |

---

## Tools Reference (11 total)

### Discovery

| Tool | Parameters | API | Auth |
|---|---|---|---|
| `search_github_users` | `query`, `location` | GitHub REST v3 | `GITHUB_TOKEN` |
| `get_org_members` | `org` | GitHub REST v3 | `GITHUB_TOKEN` |
| `find_open_issues` | `owner`, `repo` | GitHub REST v3 | `GITHUB_TOKEN` |
| `get_yc_companies` | `batch` | YC API | none |
| `search_yc_companies` | `query`, `location` | YC API | none |
| `get_yc_company_team` | `company_name`, `website?`, `github_org?` | GitHub REST v3 | `GITHUB_TOKEN` |

### Enrichment

| Tool | Parameters | API | Auth |
|---|---|---|---|
| `lookup_tech_stack` | `url` | WebReveal | none (free) |
| `find_company_emails` | `domain`, `limit?` | Hunter.io | `HUNTER_API_KEY` |
| `search_jobs` | `tags?`, `limit?` | RemoteOK | none (free) |

### Pipeline

| Tool | Parameters | Storage |
|---|---|---|
| `save_prospect` | `name`, `github?`, `email?`, `company?`, `role?`, `location?`, `notes?`, `source?` | SQLite |
| `list_prospects` | none | SQLite |
| `update_prospect_status` | `id`, `status` | SQLite |

**Status flow:** `new` → `researched` → `github_engaged` → `x_engaged` → `emailed` → `replied` → `meeting_scheduled`

---

## Compliance Layer

Every tool call passes through three gates:

```
RateLimiter.check(tool_name)
  └── 30 calls/min default · Hunter.io=5/min · WebReveal=20/min

↓ execute tool

PiiFilter.detect_types(output)
  └── detects: email · api_key · credit_card · phone · ip · ssn

AuditLogger.log() → tool_call_log (SQLite)
  └── tool_name · input_preview (redacted) · output_len · output_fingerprint
      duration_ms · status (ok|error) · pii_detected
```

**Enterprise checklist:**
- SOC2 Type II → immutable audit trail per tool call
- GDPR → PII detected and redacted before logging
- HIPAA → PHI never persists in process memory longer than the call
- Memory safety → Rust, zero buffer overflows, no GC pauses
- Rate controls → no runaway API costs or abuse

---

## Database Schema

```sql
-- Prospect pipeline
prospects (id, name, github UNIQUE, email, company, role,
           location, notes, source, outreach_status, created_at, updated_at)

-- Every outreach touch point
outreach_log (id, prospect_id → prospects, channel, message, sent_at)

-- Compliance audit trail
tool_call_log (id, tool_name, input_preview, output_len,
               output_fingerprint, duration_ms, status, pii_detected, ts)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | GitHub PAT — scopes: `read:user`, `read:org` |
| `HUNTER_API_KEY` | Optional | Hunter.io — free tier: 25 searches/mo |
| `ANTHROPIC_API_KEY` | Python agents | claude-opus-4-8 for CV + outreach generation |
| `NETWORKING_DB` | Optional | SQLite path (default: `~/networking-agent.db`) |

---

## Setup

### Rust MCP Server

```bash
git clone https://github.com/Saraswat123/Networking-Agent.md-.git
cd Networking-Agent.md-

cargo build --release

# Register with Claude Code
claude mcp add networking-agent \
  -s user \
  -e GITHUB_TOKEN="ghp_yourtoken" \
  -e HUNTER_API_KEY="your_hunter_key" \
  -e NETWORKING_DB="$HOME/networking-agent.db" \
  -- ./target/release/networking-agent
```

### Python Agents

```bash
cd agents
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export NETWORKING_DB=~/networking-agent.db
export HUNTER_API_KEY=...

# Edit profile.json with your real details first
```

---

## CLI Commands (Python agents/)

```bash
# Full pipeline: discover → enrich → generate outreach
python cli.py run --query "CTO" --location "Singapore" --mode yc --limit 10

# Preview without generating outreach
python cli.py run --query "AI infrastructure" --mode both --dry-run

# Generate tailored CV for a job
python cli.py cv --jd stripe_jd.txt --company "Stripe" --role "Backend Engineer"

# Generate cold email + LinkedIn + follow-ups for one prospect
python cli.py email \
  --company "Ramp" \
  --contact "John Doe" \
  --role "Head of AI" \
  --to "john@ramp.com" \
  --signal "just posted Rust backend role" \
  --stack "Rust,Go,Postgres"

# Run bridge: enrich all 'new' prospects in DB → generate outreach
python cli.py bridge --limit 20

# View pipeline status dashboard
python cli.py dashboard
```

---

## Docker

```bash
docker build -t networking-agent .
docker compose up
```

Multi-stage build: `rust:1.93-slim` → `debian:bookworm-slim`. Final image ~15MB.

---

## Target Companies

The compliance layer makes this the right choice for:

- **FinTech** (Ramp, Brex, Mercury) — PCI-DSS audit requirements
- **LegalTech** (Harvey AI, Ironclad) — attorney-client privilege, zero data leakage
- **HealthTech** (Oscar, Cityblock) — HIPAA PHI controls
- **Enterprise SaaS** (Notion, Linear) — SOC2 Type II for enterprise tier
- **Government** — CISA/NSA memory-safe language mandate, FedRAMP audit trail

---

## License

MIT
