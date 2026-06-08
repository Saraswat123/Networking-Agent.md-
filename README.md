# Networking Agent

A Rust MCP (Model Context Protocol) server that builds a global prospect pipeline — finding CEOs, CTOs, VCs, and founders across GitHub, YC, and other sources. Runs locally and integrates directly with Claude Code (no API billing).

## What It Does

- **Search GitHub** for engineers and founders by role + location (global — SF, NYC, Singapore, London, etc.)
- **Find org members** at target companies on GitHub
- **Discover open issues** in target repos (warm entry points for contribution)
- **Browse YC companies** by batch or keyword + location
- **Track prospects** in local SQLite — status from `new` → `meeting_scheduled`

## Architecture

```
Claude Code (claude.ai/code)
        │
        │  MCP protocol (JSON-RPC 2.0 over stdio)
        ▼
networking-agent  (Rust binary)
        │
        ├── GitHub API  (search users, org members, issues)
        ├── YC API      (ycombinator.com public API)
        └── SQLite DB   (prospect pipeline state)
```

## Stack

| Layer | Technology |
|-------|-----------|
| MCP Server | `rmcp 1.7` (official Rust MCP SDK) |
| Async runtime | `tokio 1.52` |
| HTTP client | `reqwest 0.13` + `rustls` (no OpenSSL) |
| Database | `sqlx 0.8` + SQLite |
| Serialization | `serde` + `serde_json` |
| Schema | `schemars` (JSON Schema for tool params) |

## Tools Exposed to Claude

| Tool | Description |
|------|-------------|
| `search_github_users` | Search by role + location globally |
| `get_org_members` | All engineers at a GitHub org |
| `find_open_issues` | Open issues tagged `good first issue` / `help wanted` |
| `get_yc_companies` | YC companies by batch (W25, S24, W24…) |
| `search_yc_companies` | YC companies by keyword + location |
| `save_prospect` | Add to SQLite pipeline |
| `list_prospects` | View full pipeline |
| `update_prospect_status` | Track outreach progress |

## Outreach Status Flow

```
new → researched → github_engaged → x_engaged → emailed → replied → meeting_scheduled
```

## Setup

### Prerequisites

- Rust 1.70+
- Claude Code (claude.ai/code) with Premium subscription
- GitHub Personal Access Token (read:user, read:org scopes)

### Build

```bash
git clone https://github.com/Saraswat123/Networking-Agent.md-.git
cd Networking-Agent.md-

# Copy env template
cp .env.example .env
# Edit .env and add your GITHUB_TOKEN

# Build release binary
cargo build --release
```

### Register with Claude Code

```bash
claude mcp add networking-agent \
  -s user \
  -e GITHUB_TOKEN="your_github_pat_here" \
  -e NETWORKING_DB="$HOME/networking-agent.db" \
  -- ./target/release/networking-agent
```

Restart Claude Code. Tools are now available in every session.

### Docker

```bash
# Build image
docker build -t networking-agent .

# Run with env file
docker run --rm \
  --env-file .env \
  -v "$HOME/networking-agent.db:/data/networking.db" \
  -e NETWORKING_DB=/data/networking.db \
  networking-agent
```

Or with Docker Compose:

```bash
docker compose up
```

## Usage Examples

Once registered with Claude Code, ask Claude:

```
"Find CTOs in Singapore on GitHub and save top 5 as prospects"

"Get all W25 YC companies in fintech and save founders as prospects"

"Find open issues in the modelcontextprotocol/rust-sdk repo"

"List all my prospects and show their outreach status"

"Search for AI infrastructure founders in New York on GitHub"
```

## Database Schema

```sql
prospects (
  id, name, github, email, company, role,
  location, notes, source, outreach_status, created_at
)

outreach_log (
  id, prospect_id, channel, message, sent_at
)
```

DB file location: `$HOME/networking-agent.db` (configurable via `NETWORKING_DB` env var)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub PAT with `read:user`, `read:org` |
| `NETWORKING_DB` | No | SQLite file path (default: `$HOME/networking-agent.db`) |

## Project Structure

```
networking-agent/
├── src/
│   ├── main.rs          # MCP stdio server entry point
│   ├── server.rs        # Tool definitions (#[tool] macros)
│   ├── db.rs            # SQLite schema + pool init
│   └── tools/
│       ├── github.rs    # GitHub API calls
│       └── yc.rs        # YC public API
├── migrations/
│   └── 001_init.sql     # Database schema
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── CLAUDE.md            # Agent workflow instructions for Claude
```

## Contributing

1. Fork → branch → PR
2. Run `cargo clippy` before submitting
3. No secrets in commits — use `.env` for tokens

## License

MIT
