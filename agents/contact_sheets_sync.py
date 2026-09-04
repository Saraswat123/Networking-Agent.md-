"""Sync contact_leads table → user's Google Sheet (Contacts tab).

Sheet: https://docs.google.com/spreadsheets/d/1BCiz3eOGYza0fpENtUpEXJHxYPMce_a3As4ViMly9Og
Tab:   gid=1400798537

Reuses token_sheets.json OAuth token (same creds as trackb-sheets).
First run opens browser for consent if token missing.

Usage:
  python cli.py contact-sheets           # sync all contacts
  python cli.py contact-sheets --track A  # Track A only
  python cli.py contact-sheets --track B  # Track B only
"""

import os
from pathlib import Path

CREDS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH  = Path(__file__).parent.parent / "token_sheets.json"
SCOPES      = ["https://www.googleapis.com/auth/spreadsheets"]

# User's spreadsheet — fixed ID, never auto-create
SHEET_ID  = "1BCiz3eOGYza0fpENtUpEXJHxYPMce_a3As4ViMly9Og"
TAB_GID   = 1400798537
TAB_NAME  = "Contacts"  # will be fetched/confirmed on first call

COLUMNS = [
    ("Date Found",    "created_at"),
    ("Track",         "track"),
    ("Name",          "name"),
    ("Role",          "role"),
    ("Company",       "company"),
    ("Email",         "email"),
    ("Confidence",    "email_confidence"),
    ("LinkedIn",      "linkedin_url"),
    ("Country",       "country"),
    ("Team Size",     "team_size"),
    ("Sector",        "sector"),
    ("Signal",        "signal"),
    ("Status",        "status"),
    ("Source",        "source"),
    ("Domain",        "domain"),
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
                raise FileNotFoundError(
                    f"Missing {CREDS_PATH} — download from Google Cloud Console (OAuth Desktop App)"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            print("Opening browser for one-time Google Sheets consent...")
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def _get_or_create_tab(service) -> tuple[str, int]:
    """
    Find the Contacts tab in the existing spreadsheet by gid=TAB_GID.
    If not found by gid, find by name 'Contacts'. If still not found, create it.
    Returns (tab_name, sheet_id_int).
    """
    meta = service.spreadsheets().get(
        spreadsheetId=SHEET_ID, fields="sheets.properties"
    ).execute()

    sheets = meta.get("sheets", [])

    # Match by gid
    for s in sheets:
        if s["properties"]["sheetId"] == TAB_GID:
            return s["properties"]["title"], TAB_GID

    # Match by name
    for s in sheets:
        if s["properties"]["title"].strip().lower() in ("contacts", "contact leads", "contact"):
            return s["properties"]["title"], s["properties"]["sheetId"]

    # Create Contacts tab
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": "Contacts"}}}]},
    ).execute()
    new_gid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    print(f"  Created 'Contacts' tab in sheet")
    return "Contacts", new_gid


def _build_rows(track: str = "", status: str = "", limit: int = 5000) -> list[dict]:
    import sqlite3
    from pathlib import Path

    db_path = Path(os.environ.get("NETWORKING_DB", Path.home() / "networking-agent.db"))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conditions, params = [], []
    if track:
        conditions.append("track=?")
        params.append(track.upper())
    if status:
        conditions.append("status=?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM contact_leads {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sync_contacts(track: str = "", status: str = "") -> str:
    """Push contact_leads to the Contacts tab. Returns sheet URL."""
    rows = _build_rows(track=track, status=status)

    if not rows:
        print("  No contacts to sync.")
        return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

    service = _get_service()
    tab_name, tab_sheet_id = _get_or_create_tab(service)

    # Build values matrix
    header = [h for h, _ in COLUMNS]
    values = [header]
    for r in rows:
        row_vals = []
        for _, field in COLUMNS:
            v = r.get(field)
            if v is None:
                v = ""
            # Truncate long signal/notes fields
            if field in ("signal",) and isinstance(v, str):
                v = v[:200]
            row_vals.append(str(v) if v else "")
        values.append(row_vals)

    range_name = f"{tab_name}!A1:Z{len(values) + 5}"

    # Clear existing data
    service.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID,
        range=f"{tab_name}!A1:Z100000",
    ).execute()

    # Write new data
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Bold + freeze header row
    service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={
        "requests": [
            {"repeatCell": {
                "range": {
                    "sheetId": tab_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }},
            {"updateSheetProperties": {
                "properties": {
                    "sheetId": tab_sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }},
        ]
    }).execute()

    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={tab_sheet_id}"
    print(f"  Synced {len(rows)} contacts → {url}")
    return url
