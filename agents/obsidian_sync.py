"""
Obsidian Sync — writes classifier and research results as Markdown notes
to the local Obsidian vault. Auto-creates folder structure.

Vault structure created:
  Obsidian Vault/
  ├── Prospects/
  │   ├── _Dashboard.md          ← auto-updated index
  │   ├── TrackA_Jobs/           ← technical companies, job applications
  │   │   └── <Company>.md
  │   └── TrackB_Proposals/      ← non-technical, AI automation proposals
  │       └── <Company>.md
  └── Classifier/
      └── _Classifier_Log.md     ← all runs logged
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
PROSPECTS_DIR = VAULT_PATH / "Prospects"
TRACK_A_DIR = PROSPECTS_DIR / "TrackA_Jobs"
TRACK_B_DIR = PROSPECTS_DIR / "TrackB_Proposals"
CLASSIFIER_DIR = VAULT_PATH / "Classifier"
DASHBOARD = PROSPECTS_DIR / "_Dashboard.md"
LOG_FILE = CLASSIFIER_DIR / "_Classifier_Log.md"


def _ensure_dirs():
    for d in [TRACK_A_DIR, TRACK_B_DIR, CLASSIFIER_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def write_track_a(company: str, data: dict) -> Path:
    """Write Track A (job application) note to Obsidian."""
    _ensure_dirs()
    safe = "".join(c for c in company if c.isalnum() or c in " -_").strip()
    path = TRACK_A_DIR / f"{safe}.md"

    job = data.get("job_analysis", {})
    collab = data.get("collab_analysis", {})
    score = data.get("shortlist", {})
    pathway = data.get("pathway", {})
    stack = data.get("tech_stack", [])

    note = f"""---
tags: [prospect, track-a, job-application]
company: {company}
score: {score.get("shortlist_score", "?")}
priority: {score.get("priority", "?")}
pathway: track_a
date_added: {_today()}
status: new
---

# {company} — Track A (Job Application)

> **{score.get("why_shortlist", "")}**

## Open Position
- **Role:** {job.get("best_position", "?")}
- **Fit Score:** {job.get("fit_score", "?")}/10
- **Why fit:** {job.get("fit_reason", "")}
- **Stack overlap:** {", ".join(job.get("stack_overlap", []))}

{chr(10).join(f'- [{p.get("title")}]({p.get("url")}) — fit {p.get("fit_score")}/10: {p.get("why")}' for p in job.get("relevant_positions", []))}

## Tech Stack
{", ".join(stack) if stack else "Not detected"}

## Outreach Hook
> {score.get("outreach_hook", "")}

## Action
```
python cli.py cv --jd <jd_file>.txt --company "{company}" --role "{job.get("best_position", "")}"
python cli.py email --company "{company}" --signal "{job.get("best_position", "")} role open" --stack "{", ".join(stack[:3])}"
```

## Collaboration Entry
{collab.get("best_opportunity", "None found")}

## Notes
- Source: {data.get("prospect", {}).get("source", "?")}
- GitHub: {data.get("prospect", {}).get("github", "?")}
- Added: {_now()}
"""
    path.write_text(note)
    return path


def write_track_b(company: str, data: dict) -> Path:
    """Write Track B (AI automation proposal) note to Obsidian."""
    _ensure_dirs()
    safe = "".join(c for c in company if c.isalnum() or c in " -_").strip()
    path = TRACK_B_DIR / f"{safe}.md"

    classifier = data.get("classifier", {})
    ai_hunger = data.get("ai_hunger", {})
    proposal = data.get("proposal", {})
    prospect = data.get("prospect", {})
    bg = data.get("background", {})

    note = f"""---
tags: [prospect, track-b, proposal, non-technical]
company: {company}
country: {classifier.get("country", "?")}
sector: {classifier.get("sector", "?")}
ai_hunger_score: {ai_hunger.get("hunger_score", "?")}
proposal_value: {proposal.get("estimated_value", "?")}
date_added: {_today()}
status: new
---

# {company} — Track B (AI Automation Proposal)

> **{classifier.get("one_liner", "")}**

## Company Profile
| Field | Value |
|---|---|
| Sector | {classifier.get("sector", "?")} |
| Country | {classifier.get("country", "?")} |
| Size | {classifier.get("company_size", "?")} |
| Tech maturity | {classifier.get("tech_maturity", "?")} /10 |
| Non-tech signal | {classifier.get("non_tech_signal", "")} |

## AI Hunger Assessment
- **Score:** {ai_hunger.get("hunger_score", "?")}/10
- **Why they want AI:** {ai_hunger.get("why_they_want_ai", "")}
- **Pain points:** {", ".join(ai_hunger.get("pain_points", []))}
- **Manual processes detected:** {", ".join(ai_hunger.get("manual_processes", []))}
- **Decision maker signal:** {ai_hunger.get("decision_maker_signal", "")}

## Proposed Solution
### {proposal.get("solution_title", "AI Automation Package")}

{proposal.get("solution_description", "")}

**What we build:**
{chr(10).join(f'- {item}' for item in proposal.get("deliverables", []))}

**Tech we use:** {", ".join(proposal.get("tech_stack_we_use", []))}

**Timeline:** {proposal.get("timeline", "?")}
**Estimated value:** {proposal.get("estimated_value", "?")}
**Pricing model:** {proposal.get("pricing_model", "?")}

## Outreach Strategy
- **Channel:** {proposal.get("outreach_channel", "Email + LinkedIn")}
- **Decision maker:** {proposal.get("target_contact_role", "CEO / Operations Director")}
- **Hook:** {proposal.get("outreach_hook", "")}
- **Subject line:** {proposal.get("email_subject", "")}

## Email Draft
{proposal.get("email_draft", "_To be generated via outreach agent_")}

## Background Research
| Field | Value |
|---|---|
| Founded | {bg.get("founded_year", "?") if bg else "?"} |
| Size | {bg.get("size_estimate", "?") if bg else "?"} employees |
| Revenue est. | {bg.get("revenue_estimate", "?") if bg else "?"} |
| AI readiness | {bg.get("ai_readiness", "?") if bg else "?"} |
| Key people | {", ".join(f"{p['name']} ({p['role']})" for p in (bg.get("key_people", []) if bg else [])[:3]) or "?"} |
| Recent news | {bg.get("recent_news", "?") if bg else "?"} |
| Pain signals | {bg.get("pain_signals", "?") if bg else "?"} |

## Proposal Hook
> {(bg.get("proposal_hook") or proposal.get("outreach_hook") or "") if bg else proposal.get("outreach_hook", "")}

## Contact Info
- Website: {prospect.get("notes", "").split("website:")[-1].split()[0] if "website:" in prospect.get("notes", "") else "?"}
- Source: {prospect.get("source", "?")}
- Location: {prospect.get("location", "?")}

## Outreach Checklist
- [ ] Background research complete
- [ ] Email drafted (use Email Draft above)
- [ ] Outreach sent
- [ ] Follow-up 1 (day 7)
- [ ] Follow-up 2 (day 14)
- [ ] Proposal document sent
- [ ] Contract signed
"""
    path.write_text(note)
    return path


def update_dashboard(track_a_companies: list[str], track_b_companies: list[str]):
    """Regenerate the Prospects dashboard note."""
    _ensure_dirs()

    # Count existing notes
    a_notes = list(TRACK_A_DIR.glob("*.md"))
    b_notes = list(TRACK_B_DIR.glob("*.md"))

    content = f"""---
tags: [dashboard, prospects]
updated: {_now()}
---

# Prospects Dashboard

> Auto-updated by Classifier Agent — {_now()}

## Summary
| Track | Count | Description |
|---|---|---|
| Track A — Jobs | {len(a_notes)} | Technical companies, job applications |
| Track B — Proposals | {len(b_notes)} | Non-technical, AI automation proposals |
| **Total** | **{len(a_notes) + len(b_notes)}** | |

## Latest Track A (Job Applications)
{chr(10).join(f'- [[TrackA_Jobs/{c}]]' for c in track_a_companies[-10:])}

## Latest Track B (AI Proposals)
{chr(10).join(f'- [[TrackB_Proposals/{c}]]' for c in track_b_companies[-10:])}

## Pipeline Status
```
new → contacted → replied → proposal_sent → contract → active_client
```

## Quick Actions
```bash
# Run classifier on new prospects
python cli.py classify --limit 20 --mode both

# Generate proposal email for Track B
python cli.py email --company "<name>" --track b

# Check pipeline
python cli.py dashboard
```
"""
    DASHBOARD.write_text(content)


def log_classifier_run(results: list[dict]):
    """Append classifier run summary to log file."""
    _ensure_dirs()

    a = [r for r in results if r.get("track") == "A"]
    b = [r for r in results if r.get("track") == "B"]
    skipped = [r for r in results if r.get("track") == "skip"]

    entry = f"""
## Run — {_now()}

Processed: {len(results)} companies

**Track A (Jobs):** {len(a)}
{chr(10).join(f'  - {r["company"]} (score: {r.get("score", "?")})' for r in a)}

**Track B (Proposals):** {len(b)}
{chr(10).join(f'  - {r["company"]} (AI hunger: {r.get("ai_hunger_score", "?")}/10)' for r in b)}

**Skipped:** {len(skipped)}
{chr(10).join(f'  - {r["company"]}: {r.get("reason", "")}' for r in skipped)}

---
"""
    with open(LOG_FILE, "a") as f:
        f.write(entry)
