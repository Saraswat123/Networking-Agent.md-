"""
Gmail Email Sender — sends outreach emails via Gmail SMTP (App Password).

No Gmail API needed. Uses SMTP with App Password.
Setup: myaccount.google.com/apppasswords (requires 2FA enabled).

Usage:
  send_email(to, subject, body)
  send_from_obsidian_note(company)  — reads email draft from Obsidian TrackB note
"""

import os
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime
import sqlite3

VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
TRACK_B_DIR = VAULT_PATH / "Prospects" / "TrackB_Proposals"
SENT_LOG = Path(__file__).parent / "output" / "sent_emails.jsonl"


def _get_creds() -> tuple[str, str]:
    addr = os.environ.get("GMAIL_ADDRESS", "")
    pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not addr or not pw:
        raise ValueError(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env\n"
            "App password: myaccount.google.com/apppasswords"
        )
    return addr, pw


def send_email(to: str, subject: str, body: str, dry_run: bool = False) -> dict:
    """Send plain-text email via Gmail SMTP."""
    from_addr, app_pw = _get_creds()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    if dry_run:
        print(f"\n[DRY RUN] Would send:")
        print(f"  To:      {to}")
        print(f"  Subject: {subject}")
        print(f"  Body:\n{body}\n")
        return {"status": "dry_run", "to": to, "subject": subject}

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_pw)
        server.sendmail(from_addr, to, msg.as_string())

    result = {
        "status": "sent",
        "from": from_addr,
        "to": to,
        "subject": subject,
        "ts": datetime.now().isoformat(),
    }

    # Log sent email
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SENT_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

    print(f"  Sent → {to} | {subject}")
    return result


def send_track_b_email(company: str, to_email: str, dry_run: bool = False) -> dict:
    """
    Read email draft from Obsidian TrackB note and send it.
    Extracts subject + body from the note's 'Email Draft' section.
    """
    safe = "".join(c for c in company if c.isalnum() or c in " -_").strip()
    note_path = TRACK_B_DIR / f"{safe}.md"

    if not note_path.exists():
        raise FileNotFoundError(f"No Track B note for '{company}' at {note_path}")

    content = note_path.read_text()

    # Extract subject line
    subject = ""
    body = ""
    for line in content.splitlines():
        if line.startswith("- **Subject line:**"):
            subject = line.split(":**", 1)[-1].strip()
            break

    # Extract email draft section
    in_draft = False
    draft_lines = []
    for line in content.splitlines():
        if line.strip() == "## Email Draft":
            in_draft = True
            continue
        if in_draft:
            if line.startswith("## "):
                break
            draft_lines.append(line)

    body = "\n".join(draft_lines).strip()

    if not subject or not body:
        raise ValueError(f"Could not extract subject/body from {note_path}")

    return send_email(to_email, subject, body, dry_run=dry_run)


def log_to_db(company: str, to_email: str, status: str):
    """Log sent email to SQLite prospects table."""
    db_path = os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db"))
    if not Path(db_path).exists():
        return
    db = sqlite3.connect(db_path)
    db.execute(
        "UPDATE prospects SET outreach_status='emailed' WHERE company=? OR name=?",
        (company, company),
    )
    db.commit()
    db.close()
