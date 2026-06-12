# Networking Agent

Use the `networking-agent` MCP server tools to build and manage a prospect pipeline.

## Tools Available

- `search_github_users` — find engineers/founders by role + location
- `get_org_members` — all engineers at a target company org
- `find_open_issues` — entry points (good-first-issue, help-wanted) in target repos
- `get_yc_companies` — YC founders by batch (W24, S25, W25, etc.)
- `search_yc_companies` — search YC companies by keyword + location
- `get_yc_company_team` — find GitHub team members for a YC company
- `lookup_tech_stack` — detect tech stack from website URL (WebReveal, free, live)
- `find_company_emails` — find emails for a domain via Hunter.io (needs HUNTER_API_KEY)
- `search_jobs` — search remote jobs by tag on RemoteOK (free, no key needed)
- `save_prospect` — add to SQLite pipeline
- `list_prospects` — show full pipeline
- `update_prospect_status` — track outreach progress

## Outreach Status Flow

`new` → `researched` → `github_engaged` → `x_engaged` → `emailed` → `replied` → `meeting_scheduled`

## Workflow

1. Search for targets by role + location
2. Find their open repos/issues → identify contribution entry point
3. Save to prospects DB
4. For each prospect: find the hook (what they're building, what they care about)
5. Draft outreach anchored to specific work they did

## Outreach Rules

- GitHub first: open a PR or meaningful issue on their repo before emailing
- X (Twitter): reply to their post with insight before cold DM
- Email: one sentence hook + ask for 15 min call — send only after warmup
- Never mass-blast — one personalized touch at a time

## Environment Variables

- `GITHUB_TOKEN` — GitHub personal access token (required for GitHub tools)
- `HUNTER_API_KEY` — Hunter.io API key (free: 25 searches/mo at hunter.io, required for `find_company_emails`)
- `NETWORKING_DB` — SQLite DB path (default: `~/networking-agent.db`)

## Target Profiles

- **VCs**: find via X (follow @paulg, @sama, @naval, @garrytan followers)
- **CTOs**: search GitHub orgs of Series A/B companies in target location
- **YC Founders**: use get_yc_companies with recent batches
- **Protocol/Infra Engineers**: search "protocol" "p2p" "blockchain" location:Singapore etc.
