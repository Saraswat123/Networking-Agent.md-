# Networking Agent

**Role:** Company discovery, prospect targeting, pipeline management  
**Runtime:** Rust MCP server (`src/`)  
**Invoked by:** Claude Code via MCP protocol (stdio)

---

## Responsibility

Owns the top of the funnel. Finds companies and people, saves to SQLite, advances pipeline status. No outreach generation — that's Outreach Agent's job.

---

## Tools

| Tool | Purpose | API | Rate Limit |
|---|---|---|---|
| `search_github_users` | Find engineers/founders by role + location | GitHub REST v3 | 30/min |
| `get_org_members` | All engineers at a target company GitHub org | GitHub REST v3 | 30/min |
| `find_open_issues` | Entry points in target repos (good-first-issue) | GitHub REST v3 | 30/min |
| `get_yc_companies` | YC companies by batch (W25, S25, W24) | YC API (free) | 30/min |
| `search_yc_companies` | Search YC by keyword + location | YC API (free) | 30/min |
| `get_yc_company_team` | Find GitHub org team for a YC company | GitHub REST v3 | 30/min |
| `save_prospect` | Write prospect to SQLite pipeline | SQLite | 60/min |
| `list_prospects` | Read pipeline with status filter | SQLite | 30/min |
| `update_prospect_status` | Advance prospect through funnel | SQLite | 30/min |

---

## Inputs

```
GITHUB_TOKEN         GitHub PAT (read:user, read:org)
NETWORKING_DB        Path to SQLite file (default: ~/networking-agent.db)
```

---

## Output

Writes to `prospects` table:
```sql
name, github, email, company, role, location, notes, source, outreach_status='new'
```

---

## Pipeline Status Flow

```
new → researched → github_engaged → x_engaged → emailed → replied → meeting_scheduled
 ↑                                                                            
 │ Networking Agent owns                                                      
                  │ Research Agent advances to here                           
                               │ Outreach Agent advances from here            
```

---

## Compliance (automatic on every call)

- Rate limited: 30 calls/min per tool
- Every tool call logged to `tool_call_log`
- PII detected in outputs, flagged in audit log
- Input previews redacted before storage

---

## Configuration: Claude Code MCP

```bash
claude mcp add networking-agent \
  -s user \
  -e GITHUB_TOKEN="ghp_..." \
  -e HUNTER_API_KEY="..." \
  -e NETWORKING_DB="$HOME/networking-agent.db" \
  -- ./target/release/networking-agent
```

---

## Typical Workflow

```
Claude calls:
  search_yc_companies(query="AI infrastructure", location="Singapore")
  → get_yc_company_team(company_name="Acme", website="https://acme.com")
  → save_prospect(name="John Doe", company="Acme", role="CTO", source="yc")

Python orchestrator calls (automated batch):
  python cli.py run --query "CTO" --location "Singapore" --mode yc --limit 10
```

---

## Handoff → Research Agent

When `outreach_status = 'new'`, Research Agent picks up:
```
python cli.py bridge   # reads 'new' prospects → enriches → generates outreach
```
