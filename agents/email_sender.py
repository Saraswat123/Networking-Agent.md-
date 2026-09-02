"""
Gmail Email Sender — sends outreach emails as saraswatdas94@gmail.com via Gmail OAuth.

Usage:
  send_email(to, subject, body)
  send_from_obsidian_note(company)  — reads email draft from Obsidian TrackB note
"""

import json
import os
from pathlib import Path
from datetime import datetime
import sqlite3

import gmail_oauth

VAULT_PATH = Path("/Users/aitsgroup/Documents/Obsidian Vault")
TRACK_B_DIR = VAULT_PATH / "Prospects" / "TrackB_Proposals"
SENT_LOG = Path(__file__).parent / "output" / "sent_emails.jsonl"

SIGNOFF = "\n\nSaraswat\nsaraswatdas94@gmail.com\nhttps://saraswat.vercel.app/"


def send_email(to: str, subject: str, body: str, dry_run: bool = False, company: str = "") -> dict:
    """Send plain-text email via saraswatdas94@gmail.com Gmail OAuth."""
    if "saraswat.vercel.app" not in body.lower():
        body = body.rstrip() + SIGNOFF

    result = gmail_oauth.send_email(to, subject, body, dry_run=dry_run)
    if result["status"] == "dry_run":
        return result

    result["company"] = company

    # Log sent email
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SENT_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

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

    return send_email(to_email, subject, body, dry_run=dry_run, company=company)


def get_account() -> str:
    """Return the sending account identity for confirmation."""
    return "saraswatdas94@gmail.com"


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
