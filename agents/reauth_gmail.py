"""
Re-authenticate saraswatdas94@gmail.com → writes token.json
Run once: python3 agents/reauth_gmail.py
Browser opens → pick saraswatdas94@gmail.com → grant access.
After that: token.json auto-refreshes, no browser needed again.
"""
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CREDS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH  = Path(__file__).parent.parent / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

def main():
    if not CREDS_PATH.exists():
        print(f"ERROR: {CREDS_PATH} not found.")
        print("Download from: console.cloud.google.com → APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop App → Download JSON")
        return

    # Force fresh login (delete old token so browser always opens)
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print(f"Removed old {TOKEN_PATH.name}")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    print(f"\nSaved: {TOKEN_PATH}")

    # Confirm which account
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"Authenticated as: {profile['emailAddress']}")
    print("Done. token.json will auto-refresh from now on.")

if __name__ == "__main__":
    main()
