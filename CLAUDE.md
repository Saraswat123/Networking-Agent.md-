# Networking Agent

2-direction architecture. Direction A (Proposal) = 70% budget. Direction B (Job) = 30%.

## 2-Direction Workflow

### Direction A — Proposal (primary)
```
search_funding_news / search_github_trending / search_remotive
    ↓
save_prospect + analyze_company_depth  ← cached 7 days
    ↓
route_prospect → direction: proposal
    ↓
draft_company_proposal  ← reads cache, no re-analysis
    ↓
draft_proposal_email    ← peer tone, auto-filled, no placeholder
    ↓  (confirm 'send it' before sending)
log_email_sent → outreach_status: emailed
```

### Direction B — Job (secondary)
```
search_workatastartup / search_hn_hiring / search_remotive
    ↓
save_prospect
    ↓
route_prospect → direction: job
    ↓
track_contribution (open real PR first)
    ↓
draft_warm_email tone=candidate  ← candidate tone, portfolio link
    ↓  (confirm 'send it' before sending)
log_email_sent → outreach_status: emailed
```

### Reply Monitor
```
python3 agents/reply_monitor.py         # check + update DB
python3 agents/reply_monitor.py --dry-run   # preview only
python3 agents/reply_monitor.py --followups # show follow-up queue
```

### Email Rules (always)
- From: saraswatdas94@gmail.com ONLY
- No "Dear Name". No teaser hooks. State problem + solution plainly
- Lead with business impact, not tech specs
- Signoff always includes https://saraswat.vercel.app/
- "send it" confirmation required before any external email

## Tools Available

### Discover
- `get_yc_companies` — YC founders by batch (W24, S25, W25, etc.)
- `search_yc_companies` — search YC companies by keyword + location
- `search_hn_hiring` — search HN "Who is Hiring?" thread
- `search_wwr` — We Work Remotely RSS (free)
- `search_workatastartup` — YC companies hiring now (highest signal)
- `search_jobs` — RemoteOK by tag (free, no key)
- `search_producthunt` — recently launched products (needs PRODUCTHUNT_API_TOKEN)
- `search_crunchbase` — funded startups by size/category (needs CRUNCHBASE_API_KEY)
- `search_github_repos` — find companies by language + topic
- `search_funding_news` — TechCrunch + EU-Startups + Sifted RSS: just-raised companies (free, global)
- `search_remotive` — Remotive.io global remote jobs: EU/Asia/LATAM coverage YC misses (free)
- `search_github_trending` — GitHub trending repos by language: active companies building NOW (free)
- `search_wellfound` — Wellfound/AngelList startup jobs: seed/Series A companies with equity (free)

### Enrich
- `enrich_company` — Clearbit: size, funding, tech stack, social (needs CLEARBIT_API_KEY, 50/mo free; fallback: lookup_tech_stack)
- `lookup_tech_stack` — WebReveal tech detection from URL (free, unlimited, fallback)
- `search_crunchbase` — funding/size fallback when Clearbit exhausted

### Find People
- `search_apollo_people` — CTO/founder/eng lead: name+title+LinkedIn FREE, email costs credits (needs APOLLO_API_KEY)
- `get_yc_company_team` — GitHub org members for YC company
- `get_org_members` — all public members of GitHub org
- `search_github_users` — engineers/founders by role + location

### Email Waterfall (in order)
1. Apollo email reveal (50 credits/mo)
2. `find_company_emails` — Hunter.io by domain (25 searches/mo, needs HUNTER_API_KEY)
3. GitHub public profile email (free)
4. Pattern-guess `firstname@domain` — verify via Hunter `/email-verifier`

### Contribute
- `list_org_repos` — active repos with open issues for a GitHub org
- `score_repo_issues` — rank issues 0-100 by contribution opportunity
- `track_contribution` — log PR/comment submitted; links to prospect
- `list_contributions` — see what's submitted/acknowledged/merged

### Propose (Direction A)
- `analyze_company_depth` — deep GitHub org analysis: repos, issues, commits, pain points, tech stack. **Cached 7 days** — instant on repeat calls. Run this FIRST.
- `draft_company_proposal` — generate technical proposals from cached analysis. Stores in DB proposals table.
- `route_prospect` — decide Direction A (Proposal) vs B (Job) based on pain signals + open role. Updates `direction` column in DB.
- `draft_proposal_email` — peer-tone email auto-filled from cached analysis. No placeholders. Discussion opener from proposal engine.

### Pipeline & Sync
- `save_prospect` — add to SQLite pipeline
- `list_prospects` — show full pipeline
- `update_prospect_status` — move through outreach funnel
- `export_pipeline` — dump prospects + contributions as sheet-ready JSON → then use google-workspace MCP to write to Google Sheets

## Outreach Status Flow

`new` → `researched` → `github_engaged` → `emailed` → `replied` → `meeting_scheduled`

## Prospect Direction Field

`direction` column on each prospect:
- `proposal` — Direction A: send technical proposal, peer tone
- `job` — Direction B: send candidate application, job tone
- `null` — not yet routed — run `route_prospect` first

## Full Pipeline — Direction A (Proposal, 70%)

1. **DISCOVER** — search_funding_news + search_github_trending (Rust/Go) + search_remotive + search_wellfound
2. **SAVE** — save_prospect (include website for domain dedup)
3. **ANALYZE** — analyze_company_depth (cached 7d) — reads GitHub org: issues, commits, pain points, tech stack
4. **ROUTE** — route_prospect — reads cached analysis → sets direction=proposal if pain signals ≥ Medium
5. **PROPOSE** — draft_company_proposal — generates proposals from cache, stores in DB
6. **EMAIL** — draft_proposal_email — peer tone, auto-filled, no placeholder, portfolio link
7. **CONFIRM + SEND** — review draft → "send it" → log_email_sent
8. **MONITOR** — reply_monitor.py (runs every 6h via cron) → updates outreach_status=replied

## Full Pipeline — Direction B (Job, 30%)

1. **DISCOVER** — search_workatastartup + search_hn_hiring + search_remotive (category: software-dev)
2. **SAVE** — save_prospect with role field
3. **ROUTE** — route_prospect with has_open_role=true → sets direction=job
4. **CONTRIBUTE** — list_org_repos → score_repo_issues ≥60 → open PR → track_contribution
5. **EMAIL** — draft_warm_email with tone=candidate (after PR acknowledged)
6. **CONFIRM + SEND** — review → "send it" → log_email_sent

## Outreach Rules

- saraswatdas94@gmail.com ONLY — never saraswat.das@aits.group
- No "Dear Name". No teaser hooks. State problem + solution plainly
- Lead with business/financial impact, not tech specs
- Portfolio link https://saraswat.vercel.app/ in every signoff
- "send it" confirmation required — never auto-send
- Daily cap: 8 emails max (enforced by log_email_sent tool)

## Sheets Sync

When user says "sync to sheets" or "update tracker":
1. Call `export_pipeline` → get JSON with prospects[] and contributions[] arrays
2. Use `google-workspace` MCP: `create_spreadsheet` (first time) or `modify_sheet_values` (update)
3. Write prospects to Sheet1 (tab "Prospects"), contributions to Sheet2 (tab "Contributions")
4. First row = headers from export, then rows array

## Environment Variables

- `GITHUB_TOKEN` — GitHub personal access token (required for GitHub tools)
- `HUNTER_API_KEY` — Hunter.io API key (free: 25 searches/mo at hunter.io, required for `find_company_emails`)
- `NETWORKING_DB` — SQLite DB path (default: `~/networking-agent.db`)

## Target Profiles

- **VCs**: find via X (follow @paulg, @sama, @naval, @garrytan followers)
- **CTOs**: search GitHub orgs of Series A/B companies in target location
- **YC Founders**: use get_yc_companies with recent batches
- **Protocol/Infra Engineers**: search "protocol" "p2p" "blockchain" location:Singapore etc.
