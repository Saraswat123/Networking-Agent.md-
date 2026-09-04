"""
Daily job application automation — 30-40 applications per day.
Methods: A) direct founder email  B) workatastartup.com list  C) company careers

Run: python3 agents/daily_apply.py
Cron (macOS LaunchAgent): runs 9:00 AM IST = 3:30 AM UTC daily
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent
ROOT = BASE.parent
load_dotenv(ROOT / ".env")

QUEUE_FILE = BASE / "apply_queue.json"
LOG_FILE = BASE / "apply_log.json"
EMAILS_DIR = BASE / "emails"
CVS_DIR = BASE / "output" / "cvs"
PDFS_DIR = BASE / "output" / "pdfs"
JDS_DIR = BASE / "jds"

# PDF CV files (pre-generated, always attach to outgoing emails)
PDF_AI   = PDFS_DIR / "Saraswat_Das_AI_Engineer.pdf"
PDF_DATA = PDFS_DIR / "Saraswat_Das_Data_AI_Engineer.pdf"

SHEETS_CREDS = BASE / "credentials_sheets.json"
SHEETS_TOKEN = BASE / "token_sheets.json"
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

DAILY_EMAIL_LIMIT = 15
DAILY_PORTAL_LIMIT = 10
DAILY_CAREERS_LIMIT = 5
DAILY_WELLFOUND_LIMIT = 5
DAILY_HN_LIMIT = 5
DAILY_REMOTEOK_LIMIT = 5
DAILY_LINKEDIN_LIMIT = 5
DAILY_TOTAL = DAILY_EMAIL_LIMIT + DAILY_PORTAL_LIMIT + DAILY_CAREERS_LIMIT + DAILY_WELLFOUND_LIMIT + DAILY_HN_LIMIT + DAILY_REMOTEOK_LIMIT + DAILY_LINKEDIN_LIMIT


# ──────────────────────────────────────────────
# Queue helpers
# ──────────────────────────────────────────────

def load_queue():
    return json.loads(QUEUE_FILE.read_text())


def save_queue(q):
    QUEUE_FILE.write_text(json.dumps(q, indent=2))


def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return []


def append_log(entry):
    log = load_log()
    log.append(entry)
    LOG_FILE.write_text(json.dumps(log, indent=2))


def sync_to_sheets(company: dict, method: str = "email"):
    """Append one row to Google Sheets tracker. Silently skips if not authenticated."""
    if not SHEET_ID or not SHEETS_TOKEN.exists():
        return
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(SHEETS_TOKEN))
        svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

        row = [
            today(),
            company.get("company", ""),
            company.get("role", ""),
            company.get("domain", ""),
            company.get("email", ""),
            method,
            company.get("angle", ""),
            company.get("tier", ""),
            company.get("score", ""),
            company.get("batch", ""),
            company.get("portal_url", ""),
            company.get("notes", ""),
            "sent",
        ]
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range="Applications!A:M",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
        print(f"  [sheets] Row appended for {company['company']}")
    except Exception as e:
        print(f"  [sheets] Skip — {e}")


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# Email draft generator (inline, no file needed)
# ──────────────────────────────────────────────

SIGNATURE = """Warm regards,

Saraswat Das
saraswat.vercel.app"""

EMAIL_TEMPLATES = {
    "ai_ml_infra": {
        "subject": "{role} — Saraswat Das",
        "body": """Hi {first_name},

{hook}

I built a Rust MCP server (rmcp + tokio, 11 live tools, stdio transport) + parallel async Claude orchestration layer (asyncio.gather + Semaphore, 9 simultaneous LLM calls) in production. Also shipped a Claude Vision doc-extraction pipeline (confidence-scored JSON, 11 parameters/doc) live across 50+ staff, and a 30-table PostgreSQL warehouse with 15 API integrations.

{specific_angle}

{SIGNATURE}""",
    },
    "data_engineering": {
        "subject": "{role} — Saraswat Das",
        "body": """Hi {first_name},

{hook}

Built a Claude Vision doc-extraction pipeline in prod + 30-table PostgreSQL warehouse + 15 API integrations (Zoho CRM/HRMS/Books, payment, EdTech APIs), Power BI layer — all live across 15 locations/50+ staff. Then layered an Ollama + Claude LLM pipeline for multi-model ETL inference.

{specific_angle}

{SIGNATURE}""",
    },
    "rust_mcp": {
        "subject": "{role} — Saraswat Das",
        "body": """Hi {first_name},

{hook}

Production Rust MCP server (rmcp, tokio, JSON-RPC 2.0, 11 live tools including GitHub, YC data, SQLite, X posting, PII redaction + rate limiting). Underneath: parallel async Claude orchestration — 9 simultaneous calls via asyncio.gather + Semaphore.

{specific_angle}

{SIGNATURE}""",
    },
    "protocol_engineer": {
        "subject": "{role} — Saraswat Das",
        "body": """Hi {first_name},

{hook}

Built Axiom Engine — a ZK-proof AI agent engine in Rust with TEE attestation. Also a production Rust MCP server (rmcp, tokio, 11 live tools) and parallel async Claude orchestration layer. Studying on-chain execution mechanics and ZK verification.

{specific_angle}

{SIGNATURE}""",
    },
    "eu_uk": {
        "subject": "{role} — Saraswat Das",
        "body": """Hi {first_name},

{hook}

Remote from India — $30-50K USD total comp. Built LLM pipelines + multi-agent systems in production (9 concurrent Claude calls, Rust MCP server, PostgreSQL warehouse, 15 API integrations) live across 50-staff edtech company.

{specific_angle}

{SIGNATURE}""",
    },
}

EU_DOMAINS = {"arva.ai", "getdexter.co", "quivr.app"}


def pick_template(company: dict) -> tuple[str, str]:
    domain = company["domain"]
    angle = company.get("angle", "ai_ml_infra")

    if domain in EU_DOMAINS:
        tmpl = EMAIL_TEMPLATES["eu_uk"]
    else:
        tmpl = EMAIL_TEMPLATES.get(angle, EMAIL_TEMPLATES["ai_ml_infra"])

    first_name = _guess_first_name(company)
    domain_hook = _domain_hook(company)

    subject = tmpl["subject"].format(
        role=company.get("role", "AI Engineer"),
        company=company["company"],
        first_name=first_name,
    )

    # hook: use company notes or angle-specific observation
    hook = company.get("email_hook") or f"Came across {company['company']} — {_domain_hook(company)} is exactly the layer I've been building."
    specific_angle = company.get("email_angle_line") or f"Would be a strong fit for the {company.get('role','AI Engineer')} role."

    body = tmpl["body"].format(
        first_name=first_name,
        company=company["company"],
        role=company.get("role", "AI Engineer"),
        domain_hook=domain_hook,
        hook=hook,
        specific_angle=specific_angle,
        SIGNATURE=SIGNATURE,
    )
    return subject, body


def _guess_first_name(company: dict) -> str:
    """Extract first name from email or fall back to 'there'."""
    email = company.get("email", "")
    local = email.split("@")[0]
    if local in ("hi", "hello", "team", "founders", "contact", "info"):
        return "there"
    # camelCase or dot-separated: devjain, serena, jeffrey
    name = local.replace(".", " ").replace("-", " ").replace("_", " ").split()[0]
    return name.capitalize()


def _domain_hook(company: dict) -> str:
    hooks = {
        "data_engineering": "unstructured document → structured data pipelines",
        "ai_ml_infra": "agent infrastructure and multi-agent orchestration",
        "rust_mcp": "agent integration and MCP tool dispatch",
        "protocol_engineer": "distributed protocol and systems engineering",
    }
    return hooks.get(company.get("angle", "ai_ml_infra"), "AI infrastructure")


# ──────────────────────────────────────────────
# Email send
# ──────────────────────────────────────────────

def send_email(company: dict) -> bool:
    """Send personalized email as davidmusk2002@gmail.com via Gmail API. Returns True on success."""
    import track_a_gmail

    # Use existing draft if present
    draft_file = EMAILS_DIR / company["email_draft"] if company.get("email_draft") else None
    if draft_file and draft_file.exists():
        subject, body = _parse_draft_body(draft_file)
    else:
        subject, body = pick_template(company)

    try:
        track_a_gmail.send(
            company["email"], subject, body,
            cc=company.get("email_cc", ""),
            dry_run=False,
        )
        sync_to_sheets(company, method="email")
        return True
    except Exception as e:
        print(f"  Gmail API error: {e}")
        return False


def _parse_draft_body(path: Path):
    """Parse existing .md draft → (subject, body)."""
    text = path.read_text()
    lines = text.split("\n")
    subject = ""
    body_lines = []
    in_body = False
    sep_count = 0

    for line in lines:
        if line.startswith("**Subject:**"):
            subject = line.replace("**Subject:**", "").strip()
        if line.strip() == "---":
            sep_count += 1
            if sep_count == 1:
                in_body = True
                continue
            elif sep_count == 2:
                in_body = False
                continue
        if in_body:
            body_lines.append(line)

    return subject, "\n".join(body_lines).strip()


# ──────────────────────────────────────────────
# CV generation for companies without CVs
# ──────────────────────────────────────────────

def ensure_cv(company: dict):
    """Generate CV for company if not already present. Returns filename."""
    if company.get("cv_file"):
        if (CVS_DIR / company["cv_file"]).exists():
            return company["cv_file"]

    print(f"  [cv_gen] Generating CV for {company['company']}...")
    try:
        result = subprocess.run(
            ["python3", str(BASE / "cli.py"), "generate-cv",
             "--company", company["company"],
             "--role", company.get("role", "AI Engineer"),
             "--angle", company.get("angle", "ai_ml_infra")],
            capture_output=True, text=True, timeout=300,
            cwd=str(ROOT),
        )
        if result.returncode == 0:
            print(f"  [cv_gen] Done")
            return None  # cli.py saves file internally
        else:
            print(f"  [cv_gen] Failed: {result.stderr[:100]}")
            return None
    except Exception as e:
        print(f"  [cv_gen] Error: {e}")
        return None


# ──────────────────────────────────────────────
# Portal/Careers list generators
# ──────────────────────────────────────────────

def generate_portal_list(companies: list, limit: int) -> list:
    pending = [c for c in companies if c["status_portal"] == "pending"]
    return pending[:limit]


def generate_careers_list(companies: list, limit: int) -> list:
    pending = [c for c in companies if c["status_careers"] == "pending"]
    return pending[:limit]


# ── Extra platforms ────────────────────────────────────────

WELLFOUND_SEARCHES = [
    "https://wellfound.com/role/r/software-engineer?remote=true&salary_min=30000&query=AI+agent",
    "https://wellfound.com/role/r/software-engineer?remote=true&salary_min=30000&query=LLM+engineer",
    "https://wellfound.com/role/r/software-engineer?remote=true&salary_min=30000&query=founding+engineer+AI",
    "https://wellfound.com/role/r/software-engineer?remote=true&salary_min=30000&query=data+engineer+AI",
    "https://wellfound.com/role/r/software-engineer?remote=true&salary_min=30000&query=MCP+Rust",
]

HN_BOARDS = [
    "https://hn.algolia.com/?q=who+is+hiring+AI+engineer+remote&dateRange=pastMonth&type=comment",
    "https://news.ycombinator.com/item?id=43939638",   # latest "Who's Hiring" thread
    "https://hnhiring.com/?technologies=rust,python&locations=remote",
    "https://whoishiring.io/search/engineers/remote/AI",
    "https://hnjobs.emilburzo.com/?q=AI+engineer+remote",
]

REMOTEOK_BOARDS = [
    "https://remoteok.com/remote-ai-jobs",
    "https://remoteok.com/remote-llm-jobs",
    "https://remoteok.com/remote-python-jobs?min_salary=30000",
    "https://remoteok.com/remote-rust-jobs",
    "https://remoteok.com/remote-ml-jobs?min_salary=30000",
]

LINKEDIN_SEARCHES = [
    "https://www.linkedin.com/jobs/search/?keywords=AI+engineer+founding&f_WT=2&f_E=1%2C2&sortBy=DD",
    "https://www.linkedin.com/jobs/search/?keywords=LLM+engineer+remote&f_WT=2&sortBy=DD",
    "https://www.linkedin.com/jobs/search/?keywords=data+engineer+AI+startup+remote&f_WT=2&sortBy=DD",
    "https://www.linkedin.com/jobs/search/?keywords=MCP+agent+engineer&f_WT=2&sortBy=DD",
    "https://www.linkedin.com/jobs/search/?keywords=multi+agent+engineer+remote&f_WT=2&f_E=1%2C2&sortBy=DD",
]


# ──────────────────────────────────────────────
# Main daily runner
# ──────────────────────────────────────────────

def check_followups(queue: list):
    """Print companies needing Day-3 follow-up today or overdue."""
    from datetime import date, timedelta
    today_d = date.today()
    due = []
    overdue = []
    for c in queue:
        if c.get("status_email") != "sent":
            continue
        if c.get("reply_date"):
            continue
        sent = c.get("email_sent_date", "")
        if not sent:
            continue
        try:
            sent_d = date.fromisoformat(sent)
            followup_d = sent_d + timedelta(days=3)
            delta = (followup_d - today_d).days
            if delta == 0:
                due.append((c["company"], c["email"], str(followup_d)))
            elif delta < 0:
                overdue.append((c["company"], c["email"], abs(delta)))
        except Exception:
            pass

    if overdue:
        print(f"\n🚨 OVERDUE FOLLOW-UPS ({len(overdue)}):")
        for co, em, days in overdue:
            print(f"  ❌ {co:25} → {em}  ({days}d overdue)")

    if due:
        print(f"\n🔔 FOLLOW UP TODAY ({len(due)}):")
        for co, em, dt in due:
            print(f"  📧 {co:25} → {em}")
            print(f"     Subject: Following up — AI Engineer @ {co}")
            print(f"     Body: Hi, just following up on my email from {dt}. Happy to share more about my work if useful.")
        print()


def run_daily():
    print(f"\n{'='*60}")
    print(f"DAILY APPLY RUN — {today()}")
    print(f"Target: {DAILY_TOTAL} applications (email:{DAILY_EMAIL_LIMIT} portal:{DAILY_PORTAL_LIMIT} careers:{DAILY_CAREERS_LIMIT})")
    print(f"{'='*60}\n")

    queue = load_queue()
    by_tier = sorted(queue, key=lambda x: (x["tier"], -x["score"]))

    # ── Follow-up check ─────────────────────────────────────────
    check_followups(queue)

    # ── Part A: Emails ──────────────────────────────────────────
    print("── PART A: Direct Emails ──")
    email_pending = [c for c in by_tier if c["status_email"] == "pending" and c.get("email")]
    email_sent = 0

    for company in email_pending[:DAILY_EMAIL_LIMIT]:
        print(f"\n[{email_sent+1}/{DAILY_EMAIL_LIMIT}] {company['company']} → {company['email']}")
        ok = send_email(company)
        if ok:
            company["status_email"] = "sent"
            company["email_sent_date"] = today()
            email_sent += 1
            append_log({
                "date": today(),
                "company": company["company"],
                "method": "email",
                "to": company["email"],
                "status": "sent",
            })
            print(f"  ✅ SENT")
        else:
            append_log({
                "date": today(),
                "company": company["company"],
                "method": "email",
                "to": company["email"],
                "status": "failed",
            })

    # ── Part B: Portal list ──────────────────────────────────────
    print(f"\n── PART B: workatastartup.com Portal ({DAILY_PORTAL_LIMIT} companies) ──")
    portal_list = generate_portal_list(by_tier, DAILY_PORTAL_LIMIT)
    print("Apply manually at these YC portals (copy-paste links):\n")
    for i, c in enumerate(portal_list, 1):
        print(f"  {i:2}. {c['company']:25} → {c['portal_url']}")
        c["status_portal"] = "queued"

    # ── Part C: Careers list ──────────────────────────────────────
    print(f"\n── PART C: Company Career Pages ({DAILY_CAREERS_LIMIT} companies) ──")
    careers_list = generate_careers_list(by_tier, DAILY_CAREERS_LIMIT)
    print("Apply via company sites:\n")
    for i, c in enumerate(careers_list, 1):
        print(f"  {i:2}. {c['company']:25} → {c['careers_url']}/careers  (or /jobs)")
        c["status_careers"] = "queued"

    # ── Part D: WellFound (AngelList) ────────────────────────────
    print(f"\n── PART D: WellFound / AngelList ({DAILY_WELLFOUND_LIMIT} searches) ──")
    print("Search + apply (Easy Apply available for most YC startups):\n")
    for i, url in enumerate(WELLFOUND_SEARCHES[:DAILY_WELLFOUND_LIMIT], 1):
        print(f"  {i}. {url}")

    # ── Part E: HN Who's Hiring ───────────────────────────────────
    print(f"\n── PART E: HN Who's Hiring ({DAILY_HN_LIMIT} boards) ──")
    print("Ctrl+F 'remote' + 'AI' / 'LLM' / 'agent' — reply directly in thread:\n")
    for i, url in enumerate(HN_BOARDS[:DAILY_HN_LIMIT], 1):
        print(f"  {i}. {url}")

    # ── Part F: RemoteOK ─────────────────────────────────────────
    print(f"\n── PART F: RemoteOK ({DAILY_REMOTEOK_LIMIT} boards) ──")
    print("Sort by newest — apply via company link directly:\n")
    for i, url in enumerate(REMOTEOK_BOARDS[:DAILY_REMOTEOK_LIMIT], 1):
        print(f"  {i}. {url}")

    # ── Part G: LinkedIn Easy Apply ──────────────────────────────
    print(f"\n── PART G: LinkedIn Easy Apply ({DAILY_LINKEDIN_LIMIT} searches) ──")
    print("Filter: Remote + Entry/Mid + Date Posted: Past Week — Easy Apply only:\n")
    for i, url in enumerate(LINKEDIN_SEARCHES[:DAILY_LINKEDIN_LIMIT], 1):
        print(f"  {i}. {url}")

    # ── Save updated queue ──────────────────────────────────────
    save_queue(queue)

    # ── Summary ──────────────────────────────────────────────────
    total_actions = email_sent + len(portal_list) + len(careers_list) + DAILY_WELLFOUND_LIMIT + DAILY_HN_LIMIT + DAILY_REMOTEOK_LIMIT + DAILY_LINKEDIN_LIMIT
    print(f"\n{'='*60}")
    print(f"SUMMARY — {today()}")
    print(f"  A) Emails auto-sent:  {email_sent}/{DAILY_EMAIL_LIMIT}")
    print(f"  B) YC portal queue:   {len(portal_list)} companies")
    print(f"  C) Career pages:      {len(careers_list)} companies")
    print(f"  D) WellFound:         {DAILY_WELLFOUND_LIMIT} searches")
    print(f"  E) HN Hiring:         {DAILY_HN_LIMIT} boards")
    print(f"  F) RemoteOK:          {DAILY_REMOTEOK_LIMIT} boards")
    print(f"  G) LinkedIn:          {DAILY_LINKEDIN_LIMIT} searches")
    print(f"  ─────────────────────────────────────────")
    print(f"  TOTAL ACTION ITEMS:   {total_actions}")

    total_sent = sum(1 for c in queue if c.get("status_email") == "sent")
    total_pending = sum(1 for c in queue if c.get("status_email") == "pending")
    print(f"\n  Lifetime emails sent: {total_sent}")
    print(f"  Pipeline pending:     {total_pending}")
    print(f"{'='*60}\n")

    # ── Auto-sync Google Sheet ───────────────────────────────────
    try:
        import sys
        sys.path.insert(0, str(BASE))
        import jobs_sheets_sync
        jobs_sheets_sync.sync_to_sheet()
    except Exception as e:
        print(f"  [sheet sync skipped: {e}]")


# ──────────────────────────────────────────────
# Mark sent / replied (manual update helper)
# ──────────────────────────────────────────────

def mark_sent(company_name: str, method: str = "email"):
    queue = load_queue()
    for c in queue:
        if c["company"].lower() == company_name.lower():
            key = f"status_{method}"
            c[key] = "sent"
            c[f"{method}_sent_date"] = today()
            save_queue(queue)
            print(f"Marked {company_name} {method} → sent")
            return
    print(f"Company '{company_name}' not found in queue")


def mark_replied(company_name: str):
    queue = load_queue()
    for c in queue:
        if c["company"].lower() == company_name.lower():
            c["status_email"] = "replied"
            c["reply_date"] = today()
            save_queue(queue)
            print(f"Marked {company_name} → replied ✅")
            return
    print(f"Company '{company_name}' not found in queue")


def show_status():
    queue = load_queue()
    print(f"\n{'Company':<25} {'Score':>5} {'Email':>8} {'Portal':>8} {'Careers':>8}")
    print("-" * 65)
    for c in sorted(queue, key=lambda x: (x["tier"], -x["score"])):
        print(f"{c['company']:<25} {c['score']:>5}  {c['status_email']:>8}  {c['status_portal']:>8}  {c['status_careers']:>8}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "status":
            show_status()
        elif cmd == "mark-sent" and len(sys.argv) >= 3:
            mark_sent(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "email")
        elif cmd == "mark-replied" and len(sys.argv) >= 3:
            mark_replied(sys.argv[2])
        else:
            print("Usage: daily_apply.py [status | mark-sent <company> [email|portal|careers] | mark-replied <company>]")
    else:
        run_daily()
