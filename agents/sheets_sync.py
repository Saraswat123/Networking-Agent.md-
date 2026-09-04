"""
Google Sheets sync for Track B Outreach Tracker.

Reuses the existing OAuth Desktop-app credentials.json (already used by
gmail_oauth.py) but keeps a SEPARATE token file (token_sheets.json) scoped to
Sheets only, so it doesn't touch/clobber the working Gmail token's scopes.

First run opens a browser for one-time consent (Sheets scope), then
auto-refreshes. The created spreadsheet ID is cached in
output/trackb/sheet_id.txt so reruns update the same sheet instead of
creating duplicates.

Usage:
  python cli.py trackb-sheets
"""
import os
from pathlib import Path

from track_b_tracker import build_rows

CREDS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "token_sheets.json"
SHEET_ID_FILE = Path(__file__).parent / "output" / "trackb" / "sheet_id.txt"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

COLUMNS = [
    ("Hunger", "hunger_score"),
    ("Status", "outreach_status"),
    ("Company", "company"),
    ("Sector", "sector"),
    ("Country", "country"),
    ("Size", "size"),
    ("Category", "solution_category"),
    ("Solution", "solution_title"),
    ("Value", "estimated_value"),
    ("Email", "email"),
    ("Days Since Sent", "days_since_sent"),
    ("Source", "source"),
    ("Classified", "classified_date"),
    ("Company Hook", "company_hook"),
]


def _get_service():
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
                raise FileNotFoundError(f"Missing {CREDS_PATH} — see gmail_oauth.py setup instructions")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            print("Opening browser for one-time Google Sheets consent...")
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def _get_or_create_spreadsheet(service, title: str = "Track B Outreach Tracker") -> str:
    SHEET_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SHEET_ID_FILE.exists():
        sheet_id = SHEET_ID_FILE.read_text().strip()
        if sheet_id:
            try:
                service.spreadsheets().get(spreadsheetId=sheet_id).execute()
                return sheet_id
            except Exception:
                pass  # stale/deleted — fall through and recreate

    spreadsheet = service.spreadsheets().create(body={
        "properties": {"title": title},
        "sheets": [{"properties": {"title": "Proposals"}}],
    }).execute()
    sheet_id = spreadsheet["spreadsheetId"]
    SHEET_ID_FILE.write_text(sheet_id)
    print(f"Created new sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")
    return sheet_id


def sync_to_sheet() -> str:
    """Push Track B rows (same data as Excel) into the Google Sheet. Returns sheet URL."""
    rows = build_rows()
    rows.sort(key=lambda r: r["hunger_score"], reverse=True)

    service = _get_service()
    sheet_id = _get_or_create_spreadsheet(service)
    grid_id = service.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties"
    ).execute()["sheets"][0]["properties"]["sheetId"]

    header = [h for h, _ in COLUMNS]
    values = [header]
    for r in rows:
        values.append([r.get(field, "") if r.get(field) is not None else "" for _, field in COLUMNS])

    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id, range="Proposals!A1:Z10000",
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Proposals!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Bold header row + freeze it
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={
        "requests": [
            {"repeatCell": {
                "range": {"sheetId": grid_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": grid_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
        ]
    }).execute()

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"Synced {len(rows)} companies → {url}")
    return url


if __name__ == "__main__":
    sync_to_sheet()
