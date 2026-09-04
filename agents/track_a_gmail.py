"""
Track A's Gmail identity — davidmusk2002@gmail.com.

Custom Build prospects (founders/CEOs/VCs with an idea, no technical
co-founder) get a separate identity from Track B's saraswatdas94 account,
so the "builder for hire" persona doesn't mix with the AI-consulting pitch
sent to established companies.

New account → no App Password available yet (Google blocks App Passwords on
accounts younger than ~a few weeks). So this sends/reads via the Gmail API
(OAuth) instead of SMTP/IMAP. Same OAuth client as credentials.json (project
356700412873), separate token file + test-user entry for this account.

Usage:
  import track_a_gmail
  track_a_gmail.send(to, subject, body)
  track_a_gmail.list_replies(since_days=7)
"""
import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CREDS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "token_tracka.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    attachments: list = None,
    dry_run: bool = False,
) -> dict:
    """Send an email as davidmusk2002@gmail.com via the Gmail API. attachments = list of Path."""
    if dry_run:
        extra = f" (+{len(attachments)} attachment(s))" if attachments else ""
        print(f"\n[DRY RUN — Track A / davidmusk2002] To: {to}{extra}\nSubject: {subject}\n\n{body}\n")
        return {"status": "dry_run", "to": to, "subject": subject}

    service = _get_service()
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body, "plain"))
        for path in attachments:
            path = Path(path)
            if not path.exists():
                continue
            part = MIMEApplication(path.read_bytes(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)
    else:
        msg = MIMEText(body)
    msg["From"] = "Saraswat Das <davidmusk2002@gmail.com>"
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"  Sent → {to} | {subject}")
    return {"status": "sent", "to": to, "subject": subject, "id": sent["id"]}


def list_replies(since_days: int = 7) -> list[dict]:
    """Recent inbox messages (not sent by us) — used to check for prospect replies."""
    service = _get_service()
    results = service.users().messages().list(
        userId="me", q=f"in:inbox newer_than:{since_days}d", maxResults=50
    ).execute()
    out = []
    for m in results.get("messages", []):
        full = service.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        out.append({"from": headers.get("From", ""), "subject": headers.get("Subject", ""), "date": headers.get("Date", "")})
    return out
