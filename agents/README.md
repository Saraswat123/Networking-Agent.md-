# agents/ — Python helper scripts

Canonical pipeline is the **Rust MCP server** (`networking-agent` binary).
These scripts handle side-channel tasks the MCP server doesn't cover.

## Entry points

| Script | Purpose | Run how |
|--------|---------|---------|
| `email_sender.py` | Send email via gmail_oauth → saraswatdas94@gmail.com | Called by MCP tool `draft_warm_email` / `draft_proposal_email` after "send it" |
| `gmail_oauth.py` | OAuth2 token helper for Gmail | `python3 gmail_oauth.py` (first-time setup) |
| `reply_monitor.py` | Poll Gmail inbox, update DB outreach_status | cron every 6h — see `deploy/pipeline-loop.timer` |
| `daily_apply.py` | Dir B job apply automation | manual or cron daily |
| `job_pipeline.py` | Dir B job discovery pipeline | manual |
| `export_database.py` | Dump SQLite → JSON / CSV | manual |
| `contact_sheets_sync.py` | Push prospects to Google Sheets | manual after `export_pipeline` MCP tool |

## Deprecated / do not use

| Script | Replaced by |
|--------|------------|
| `orchestrator.py` | Rust MCP tools + CLAUDE.md workflow |
| `lead_sourcer.py` | `search_github_users`, `search_yc_companies` MCP tools |
| `outreach_agent.py` | `draft_proposal_email`, `draft_warm_email` MCP tools |
| `linkedin_agent.py` | LinkedIn blocked by ToS — removed from pipeline |

## Ignored files (not committed)

- `send_*.py` — per-campaign batch send scripts (generated, disposable)
- `profile.json` — personal profile data
- `emails/`, `jds/`, `output/` — generated artefacts
- `apply_log.json`, `apply_queue.json` — runtime state

## Email rules (applies to ALL scripts)

- From address: **saraswatdas94@gmail.com** via `gmail_oauth.py` only
- Never use `mcp__google-workspace__send_gmail_message` (sends from aits.group)
- "send it" confirmation required before any external send
- Daily cap: 8 emails enforced by `log_email_sent` MCP tool
