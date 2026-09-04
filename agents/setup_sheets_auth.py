"""
One-time Google Sheets OAuth setup.
Run: python3 agents/setup_sheets_auth.py
Requires: agents/credentials_sheets.json from Google Cloud Console
"""
from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path
import json

CREDS = Path(__file__).parent / "credentials_sheets.json"
TOKEN = Path(__file__).parent / "token_sheets.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if not CREDS.exists():
    print("ERROR: agents/credentials_sheets.json not found.")
    print("  1. Go to console.cloud.google.com")
    print("  2. Create project → Enable Google Sheets API")
    print("  3. OAuth 2.0 → Desktop App → Download JSON → save as agents/credentials_sheets.json")
    exit(1)

flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
creds = flow.run_local_server(port=0)
TOKEN.write_text(creds.to_json())
print(f"Auth complete. Token saved: {TOKEN}")
