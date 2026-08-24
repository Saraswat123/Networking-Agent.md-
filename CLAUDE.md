# Networking Agent

Use the `networking-agent` MCP server tools to build and manage a prospect pipeline.

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

### Pipeline & Sync
- `save_prospect` — add to SQLite pipeline
- `list_prospects` — show full pipeline
- `update_prospect_status` — move through outreach funnel
- `export_pipeline` — dump prospects + contributions as sheet-ready JSON → then use google-workspace MCP to write to Google Sheets

## Outreach Status Flow

`new` → `researched` → `github_engaged` → `x_engaged` → `emailed` → `replied` → `meeting_scheduled`

## Full Pipeline (run in order)

1. **DISCOVER** — search_funding_news (just-raised = hiring NOW) / search_workatastartup / search_hn_hiring / get_yc_companies / search_remotive (global) / search_github_trending (Rust/Go) / search_wellfound / search_producthunt / search_crunchbase
2. **ENRICH** — enrich_company (Clearbit) or lookup_tech_stack (free fallback). Skip if >50 emp or no GitHub
3. **FIND PERSON** — search_apollo_people (name+title free, email costs credits) → get_yc_company_team / get_org_members for GitHub email
4. **FIND CONTRIBUTION** — list_org_repos → score_repo_issues → pick issue score ≥60, unassigned, no linked PR
5. **CONTRIBUTE** — open real PR → track_contribution (status: submitted)
6. **EMAIL TRIGGER** — list_contributions (status: acknowledged) → draft warm 3-sentence email referencing specific PR

## Outreach Rules

- GitHub PR FIRST, email only after PR acknowledged/merged
- Email max 3 sentences: (1) reference specific PR, (2) why you care about what they build, (3) one ask
- No "Dear Name". No teaser hooks. No AI slop
- Never mass-blast — one personalized touch at a time

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
