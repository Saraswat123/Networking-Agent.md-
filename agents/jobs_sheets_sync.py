"""
Sync apply_queue.json → new 'Job Applications' tab in existing Google Sheet.
Reuses token_sheets.json (same OAuth creds as trackb-sheets).

Usage:  python agents/jobs_sheets_sync.py
        python cli.py jobs-sheets
"""
import json
import os
from datetime import date
from pathlib import Path

BASE      = Path(__file__).parent
ROOT      = BASE.parent
QUEUE     = BASE / "apply_queue.json"
TOKEN     = ROOT / "token_sheets.json"
CREDS     = ROOT / "credentials.json"
SHEET_ID_FILE = BASE / "output" / "trackb" / "sheet_id.txt"
SCOPES    = ["https://www.googleapis.com/auth/spreadsheets"]
TAB_NAME  = "Job Applications"

COLUMNS = [
    ("Tier",              "tier"),
    ("Score",             "score"),
    ("Company",           "company"),
    ("Batch",             "batch"),
    ("Team Size",         "team_size"),
    ("Role",              "role"),
    ("Angle",             "angle"),
    ("Email",             "email"),
    ("Confirmed?",        "email_confirmed"),
    ("Email Status",      "status_email"),
    ("Portal Status",     "status_portal"),
    ("Careers Status",    "status_careers"),
    ("Email Sent Date",   "email_sent_date"),
    ("Follow-Up Date",    "_followup_date"),
    ("Follow-Up Status",  "_followup_status"),
    ("Reply Date",        "reply_date"),
    ("Portal URL",        "portal_url"),
    ("Notes",             "notes"),
]


def _get_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS.exists():
                raise FileNotFoundError(f"Missing {CREDS} — run gmail_oauth.py setup first")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            print("Opening browser for Google Sheets consent...")
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def _get_sheet_id() -> str:
    if SHEET_ID_FILE.exists():
        sid = SHEET_ID_FILE.read_text().strip()
        if sid:
            return sid
    raise FileNotFoundError(
        "No sheet_id.txt found. Run: python cli.py trackb-sheets first to create the master sheet."
    )


def _get_or_create_tab(service, spreadsheet_id: str) -> int:
    """Return sheetId of tab TAB_NAME, creating it if missing."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == TAB_NAME:
            return s["properties"]["sheetId"]

    # Create new tab
    body = {"requests": [{"addSheet": {"properties": {"title": TAB_NAME}}}]}
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def _followup_date(c: dict) -> str:
    sent = c.get("email_sent_date", "")
    if not sent:
        return ""
    try:
        from datetime import date, timedelta
        d = date.fromisoformat(sent)
        return str(d + timedelta(days=3))
    except Exception:
        return ""


def _followup_status(c: dict) -> str:
    if c.get("status_email") not in ("sent",):
        return ""
    if c.get("reply_date"):
        return "✅ replied"
    fu = _followup_date(c)
    if not fu:
        return ""
    try:
        from datetime import date
        today = date.today()
        fu_date = date.fromisoformat(fu)
        delta = (fu_date - today).days
        if delta < 0:
            return f"⚠️ OVERDUE ({abs(delta)}d)"
        elif delta == 0:
            return "🔔 FOLLOW UP TODAY"
        else:
            return f"⏳ in {delta}d ({fu})"
    except Exception:
        return fu


def _build_rows(queue: list) -> list:
    headers = [col[0] for col in COLUMNS]
    rows = [headers]
    for c in sorted(queue, key=lambda x: (x["tier"], -x["score"])):
        row = []
        for _, key in COLUMNS:
            if key == "_followup_date":
                val = _followup_date(c)
            elif key == "_followup_status":
                val = _followup_status(c)
            else:
                val = c.get(key, "")
            if val is None:
                val = ""
            elif isinstance(val, bool):
                val = "YES" if val else "no"
            row.append(str(val))
        rows.append(row)
    return rows


def _format(service, spreadsheet_id: str, sheet_id: int, n_rows: int):
    requests = [
        # Bold + freeze header row
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        {"updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }},
        # Auto-resize all columns
        {"autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": len(COLUMNS),
            }
        }},
    ]

    # Color rows by email status
    status_colors = {
        "sent":    {"red": 0.85, "green": 0.92, "blue": 0.83},  # light green
        "replied": {"red": 0.67, "green": 0.85, "blue": 0.67},  # green
        "pending": {"red": 1.0,  "green": 0.95, "blue": 0.8},   # light yellow
        "queued":  {"red": 0.85, "green": 0.9,  "blue": 1.0},   # light blue
    }
    # status_email is column index 9 (0-based)
    # We color per-row based on overall status
    queue = json.loads(QUEUE.read_text())
    sorted_q = sorted(queue, key=lambda x: (x["tier"], -x["score"]))
    for i, co in enumerate(sorted_q):
        st = co.get("status_email", "pending")
        color = status_colors.get(st, {"red": 1, "green": 1, "blue": 1})
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": i + 1,
                    "endRowIndex": i + 2,
                },
                "cell": {
                    "userEnteredFormat": {"backgroundColor": color}
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def sync_to_sheet() -> str:
    service    = _get_service()
    sheet_id   = _get_sheet_id()
    tab_id     = _get_or_create_tab(service, sheet_id)
    queue      = json.loads(QUEUE.read_text())
    rows       = _build_rows(queue)

    # Clear existing tab content
    range_name = f"'{TAB_NAME}'!A1:Z1000"
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id, range=range_name
    ).execute()

    # Write all rows
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{TAB_NAME}'!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()

    _format(service, sheet_id, tab_id, len(rows))

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"✅ Synced {len(rows)-1} companies → {url} (tab: '{TAB_NAME}')")
    return url


if __name__ == "__main__":
    sync_to_sheet()
