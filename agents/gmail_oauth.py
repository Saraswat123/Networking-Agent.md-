"""
Gmail sender via Google Console OAuth 2.0.

Setup (one time):
  1. console.cloud.google.com → New Project
  2. Enable Gmail API
  3. OAuth consent screen → External → add your Gmail as test user
  4. Credentials → OAuth 2.0 Client ID → Desktop App → Download → save as
     /Users/aitsgroup/networking-agent/credentials.json
  5. First run: browser opens → grant access → token.json saved automatically

After that: no browser needed, token.json auto-refreshes.
"""

import json
import os
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64

CREDS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "token.json"
SENT_LOG   = Path(__file__).parent / "output" / "sent_emails.jsonl"

SCOPES = ["https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/gmail.readonly"]


def _get_service():
    """Authenticate and return Gmail API service."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDS_PATH}\n"
                    "Download from: console.cloud.google.com → APIs → Credentials → OAuth 2.0 Client ID → Desktop App"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def send_email(to: str, subject: str, body: str, dry_run: bool = False) -> dict:
    """Send email via Gmail API (OAuth). Falls back to SMTP if credentials.json missing."""
    if dry_run:
        print(f"\n[DRY RUN] To: {to}\nSubject: {subject}\n{body}\n")
        return {"status": "dry_run", "to": to, "subject": subject}

    # Fall back to SMTP if no OAuth creds
    if not CREDS_PATH.exists() and not TOKEN_PATH.exists():
        print("  [gmail_oauth] credentials.json not found, falling back to SMTP")
        from email_sender import send_email as smtp_send
        return smtp_send(to, subject, body)

    service = _get_service()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    from datetime import datetime
    import sqlite3

    log_entry = {
        "status": "sent",
        "to": to,
        "subject": subject,
        "message_id": result.get("id"),
        "ts": datetime.now().isoformat(),
        "method": "gmail_oauth",
    }
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SENT_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"  [gmail] Sent → {to} | {subject}")
    return log_entry


def get_inbox_threads(max_results: int = 10, label: str = "INBOX") -> list[dict]:
    """Read recent inbox threads — useful for detecting replies to outreach."""
    service = _get_service()
    result = service.users().threads().list(
        userId="me", labelIds=[label], maxResults=max_results
    ).execute()

    threads = result.get("threads", [])
    output = []
    for t in threads:
        thread = service.users().threads().get(userId="me", id=t["id"]).execute()
        messages = thread.get("messages", [])
        if not messages:
            continue
        first = messages[0]
        headers = {h["name"]: h["value"] for h in first.get("payload", {}).get("headers", [])}
        output.append({
            "thread_id": t["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "message_count": len(messages),
        })
    return output


def check_replies(sent_log_path: Path = SENT_LOG) -> list[dict]:
    """
    Cross-reference sent emails with inbox — find which got replies.
    Returns list of {company, to, replied: bool, thread_id}.
    """
    if not sent_log_path.exists():
        return []

    sent = []
    with open(sent_log_path) as f:
        for line in f:
            try:
                sent.append(json.loads(line))
            except Exception:
                pass

    inbox = get_inbox_threads(max_results=50)
    inbox_froms = {t["from"].lower() for t in inbox}

    results = []
    for s in sent:
        to_domain = s.get("to", "").split("@")[-1].lower()
        replied = any(to_domain in sender for sender in inbox_froms)
        results.append({
            "to": s.get("to"),
            "subject": s.get("subject"),
            "sent_at": s.get("ts"),
            "replied": replied,
        })
    return results
