# Track A Job Strategy — Saraswat Das

## The One-Line Formula

**Small team (≤30) + heavy funding (seed/series A) + worldwide remote + apply within 24h via direct email = max probability of getting hired.**

---

## Why This Works

Indian applicant applying for $30-50K USD remote = 10× less competition than US applicant for same role.
- US applicant expects $120-200K. You offer $30-50K. Founder saves $70-150K/year.
- Small team = founder reads every application personally.
- First 10 applications = 80% of founder attention. Apply within 2-6h of posting.
- Email beats portal. Portal = ATS filter = resume black hole. Email to founder = human reads it.

---

## CV Angles — When to Use Which

| Angle | Use when JD has | Title |
|-------|----------------|-------|
| `protocol_engineer` | Rust / Ethereum / BFT / eBPF / consensus / p2p / distributed | Protocol Engineer · Rust / Ethereum Consensus |
| `ai_ml_infra` | AI / LLM / Claude / OpenAI / agents / automation / MCP / RAG | AI Engineer · LLM Automation |
| `data_engineering` | Python / PostgreSQL / ETL / Power BI / data pipeline / OCR | Data Engineer · AI & Automation |
| `rust_mcp` | Rust / MCP / agent infra / devtools / async | Rust Engineer · MCP / Agent Infrastructure |

**CV Format is locked — Saraswat Das's exact layout:**
```
# SARASWAT DAS
**[Title matching JD]**
[email] · [github] · [linkedin] · [x] · [website] · Gurgaon, India (Remote OK)
---
## SUMMARY          ← 2 lines, JD language, engineer voice, no fluff
## [ANGLE SECTION]  ← protocol R&D or AI/data work, reordered to match JD
## EXPERIENCE       ← AITS Founders Office + Coddle (rewritten with JD keywords)
## OPEN SOURCE      ← Lighthouse + QuorumOS (if relevant to JD)
## PROJECTS         ← table: Project | Stack | Repo (most JD-relevant first)
## TECHNICAL SKILLS ← table: Area | Skills (reordered — JD must-haves first)
## ACHIEVEMENTS     ← IIT Hyderabad, L&T, Patent, AICTE, Youth India
## WRITING          ← saraswat.in essays (include for thought leadership roles)
## EDUCATION        ← B.Tech Computer Engineering, OUTR
```

---

## Source Priority (highest → lowest probability)

| Priority | Source | Why | Command |
|----------|--------|-----|---------|
| 1 | **HN Who Is Hiring** | Founders post directly. First 48h = max attention. | `python cli.py jobs --sources hn --max-age 1` |
| 2 | **workatastartup.com** | YC official board. Every company funded. Filter junior. | `python cli.py wats --exp j --max-team 20` |
| 3 | **YC API hunt** | Sweep all batches, check careers pages. | `python cli.py jobs-hunt --max-team 15` |
| 4 | **euremotejobs / berlinstartups** | EU boards — very few Indian applicants. | `python cli.py jobs-boards --boards euremotejobs,berlinstartups` |
| 5 | **startup.jobs / jobspresso** | Low traffic = low competition. | `python cli.py jobs-boards --boards startup_jobs,jobspresso` |
| 6 | **Wellfound (AU/NZ/UK)** | Geo filter = less competition. | `python cli.py jobs --sources wellfound` |
| 7 | **RemoteOK** | RSS with exact date. Filter < 24h. | `python cli.py jobs --sources remoteok --max-age 1` |
| 8 | **Crunchbase funding news** | Company just raised → urgently hiring. | `python cli.py jobs --sources crunchbase` |
| 9 | **LinkedIn** | Largest volume. Easy Apply only. Small company filter. | `python cli.py jobs --sources linkedin --max-age 1` |

---

## Scoring Formula (0–25 points)

```
+3  YC-backed company
+3  YC batch W24/S24/W25 (recent)
+3  team_size ≤ 15
+2  team_size 16-50
+3  recently funded (seed/series A signal)
+2  tech domain match (AI/LLM/Python/Rust/automation/blockchain)
+2  founding/early-hire/special-projects role signal
+2  worldwide/global remote explicit
+1  UK/EU/AU/NZ remote (less competition)
+2  posted < 6 hours (first batch)
+1  posted 6-24 hours
+1  salary $30-50K USD (exact sweet spot)
+1  salary up to $100K (acceptable)
+2  experience ≤ 2 years explicitly OK
-2  US-only remote
-2  team > 100 people
-3  5+ years required
-3  no tech match at all
```

**Apply if score ≥ 10. Priority apply if score ≥ 14.**

---

## Target Companies Right Now (confirmed open roles)

| Score | Company | Team | Angle | Careers URL |
|-------|---------|------|-------|-------------|
| 15 | **Datacurve** | 4 | data_engineering | datacurve.ai/careers |
| 15 | **Pre** | 2 | ai_ml_infra | buildwithpre.com/join |
| 14 | **Confident AI** | 7 | ai_ml_infra | confident-ai.com/careers |
| 14 | **Contrario** | 15 | ai_ml_infra | contrario.ai/careers |
| 13 | **Callback AI** | 2 | data_engineering | getcallback.ai/careers |
| 13 | **Rowboat Labs** | 3 | ai_ml_infra | rowboatlabs.com/careers |
| 13 | **assistant-ui** | 3 | ai_ml_infra | assistant-ui.com/careers |
| 13 | **Miyagi Labs** | 2 | ai_ml_infra | miyagilabs.ai/jobs |
| 13 | **Mathos** | 5 | data_engineering | info.mathos.ai/jobs |
| 12 | **PromptArmor** | ? | ai_ml_infra | promptarmor.com/careers |

---

## Apply Workflow (per company)

```
1. Read careers page → copy JD text → save as agents/jds/<company>.txt
2. python cli.py jobs-apply --company X --role "AI Engineer" --jd agents/jds/X.txt --domain X.ai
   → Email finder (Hunter → pattern fallback)
   → CV rewrite using JD language (cv_agent.py)
   → Obsidian note written (Jobs/Applications/YYYY-MM-DD_X_AI_Engineer.md)
   → DB logged (status=applied)
3. Send email to founder@X.ai with CV attached (or linked)
4. Day 3: follow-up if no reply
5. Day 7: second follow-up or LinkedIn message
6. python cli.py jobs-update --company X --role "AI Engineer" --status replied
```

---

## Email Template (founder direct)

```
Subject: AI Engineer — [specific thing from their product]

Hi [Name],

[One sentence: I saw you're building X and noticed Y specific thing].
[One sentence: here's the most relevant thing I've built — link].

I've been doing [2-3 word summary of work]. Open to $30-50K remote.
CV: [link or attached].

— Saraswat
saraswatdas94@gmail.com
```

**Rules:**
- Never more than 4 sentences
- Always link a specific project/repo — no CV-only emails
- Subject = specific signal from their product (not "Application for...")
- Send Monday-Wednesday 9am local founder time

---

## Salary Positioning

- Target: **$30-50K USD annually** (₹25-42L/year equivalent)
- State it in email → removes ambiguity → founder knows you fit budget
- Never list salary expectations on CV
- If they offer more → take it. If they offer less → negotiate.
- Keyword: "open to equity in lieu of higher base" → YC startups love this

---

## Daily Cadence (max probability)

```
06:00  python cli.py jobs --sources hn --max-age 1 --score-min 8
       → HN overnight posts, first batch

07:00  python cli.py wats --exp j --max-team 20 --score-min 8
       → YC board junior/founding roles

08:00  python cli.py jobs-boards --boards euremotejobs,berlinstartups,startup_jobs --max-age 48
       → Low competition niche boards

09:00  Apply to top 3-5 matches:
       python cli.py jobs-apply --company X --role Y --jd jds/X.txt --domain X.ai

Daily  python cli.py jobs-dashboard
       → Refresh Obsidian kanban + Excel

Week 1  35 connects + 150 follows (LinkedIn daily_growth)
        15 X replies (daily_growth)
```

---

## File Structure

```
networking-agent/
  agents/
    STRATEGY.md          ← this file
    job_pipeline.py      ← multi-source search + scoring
    job_tracker.py       ← Excel + Obsidian dashboard
    cv_agent.py          ← JD → tailored CV generator
    
    jds/                 ← raw JD text files (one per company)
      callback_ai_engineer.txt
      reform_ai_engineer.txt
      confident_ai_founding_engineer.txt
      contrario_ai_engineer.txt
      datacurve_software_engineer.txt
      [more...]
    
    output/
      cvs/               ← generated tailored CVs
        cv_<company>_<role>_<angle>.md
      jobs/
        jobs.db          ← SQLite application tracker
        applications.xlsx ← Excel export (auto-generated)
    
    sources/
      config.py          ← all source params (edit here only)
      README.md          ← per-source steps + daily schedule
      linkedin/          ← Playwright, Easy Apply, 24h filter
      wellfound/         ← Playwright, geo targeting
      workatastartup/    ← YC official board via YC API
      remoteboards/      ← weworkremotely, jobspresso, euremotejobs, etc.
      web3career/        ← RSS feed
      crunchbase/        ← funding news → urgent hiring signal
      email/             ← Hunter.io + Snov.io + pattern fallback
  
  Obsidian Vault/
    Jobs/
      Dashboard.md       ← kanban master view (auto-generated)
      Applications/
        YYYY-MM-DD_<Company>_<Role>.md  ← per-application note
```

---

## Keys Needed (add to .env)

```bash
HUNTER_API_KEY=<key>      # hunter.io → free 25/mo → real founder emails
                           # Get: hunter.io → Login → API

SNOV_API_KEY=<key>        # alternative to Hunter, free tier
SNOV_API_SECRET=<secret>  # Get: snov.io → Settings → API

CRUNCHBASE_API_KEY=<key>  # $49/mo → companies that just raised seed/A
                           # Get: crunchbase.com/api

TRACXN_API_KEY=<key>      # optional, alternative funding data source
```
