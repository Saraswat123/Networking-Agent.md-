"""
Track B Tracker — Excel + Obsidian dashboard for AI-automation-proposal outreach.

Source of truth is two places, joined here:
  1. output/classifier/classify_*.json   — full classify_agent.classify_company_async()
     result per company (sector, hunger score, proposal, email draft, etc.)
  2. prospects DB (NETWORKING_DB)        — outreach_status / email, the only place
     status changes (emailed, replied, ...) get persisted across runs.
  3. output/sent_emails.jsonl            — written by email_sender.send_email(), used
     to compute days-since-sent for follow-up due dates (no separate column for this
     in the DB, so the send log is the timestamp source).

Excel:    output/trackb/proposals.xlsx
Obsidian: Prospects/TrackB_Dashboard.md

Usage:
  python track_b_tracker.py excel
  python track_b_tracker.py dashboard
  python cli.py trackb-excel
  python cli.py trackb-dashboard
"""
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

CLASSIFY_DIR = Path(__file__).parent / "output" / "classifier"
OUTPUT_DIR   = Path(__file__).parent / "output" / "trackb"
SENT_LOG     = Path(__file__).parent / "output" / "sent_emails.jsonl"
DB_PATH      = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))

VAULT_PATH   = Path("/Users/aitsgroup/Documents/Obsidian Vault")
PROSPECTS_DIR = VAULT_PATH / "Prospects"
TRACK_B_DIR  = PROSPECTS_DIR / "TrackB_Proposals"
DASH_PATH    = PROSPECTS_DIR / "TrackB_Dashboard.md"
EXCEL_PATH   = OUTPUT_DIR / "proposals.xlsx"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Load + join ────────────────────────────────────────────────────────────────
def load_classify_results() -> list[dict]:
    """All Track B classify results from output/classifier/*.json."""
    results = []
    for f in sorted(CLASSIFY_DIR.glob("classify_*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("track") == "B":
            d["_file"] = f.name
            d["_mtime"] = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
            results.append(d)
    return results


def load_db_status() -> dict:
    """company (lowercase) -> {email, outreach_status, source, created_at}."""
    if not DB_PATH.exists():
        return {}
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT company, email, outreach_status, source, created_at FROM prospects WHERE company IS NOT NULL"
    ).fetchall()
    con.close()
    return {r["company"].lower(): dict(r) for r in rows if r["company"]}


def load_sent_log() -> dict:
    """company (lowercase) -> most recent sent timestamp (ISO str)."""
    if not SENT_LOG.exists():
        return {}
    latest = {}
    for line in SENT_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        # sent log doesn't carry company directly — matched via "to" address fallback,
        # but send_track_b_email/cli `send` know the company name at call time, so we
        # also accept an optional "company" key if present (forward-compatible).
        company = (d.get("company") or "").lower()
        if not company:
            continue
        ts = d.get("ts", "")
        if company not in latest or ts > latest[company]:
            latest[company] = ts
    return latest


def build_rows() -> list[dict]:
    """One row per Track B company, joining classify + DB + send log."""
    classify_results = load_classify_results()
    db_status = load_db_status()
    sent_log = load_sent_log()

    rows = []
    for r in classify_results:
        company = r.get("company", "Unknown")
        key = company.lower()
        classifier = r.get("classifier", {})
        ai_hunger = r.get("ai_hunger", {})
        proposal = r.get("proposal", {})
        prospect = r.get("prospect", {})
        db = db_status.get(key, {})

        sent_ts = sent_log.get(key, "")
        days_since_sent = None
        if sent_ts:
            try:
                days_since_sent = (datetime.now() - datetime.fromisoformat(sent_ts)).days
            except Exception:
                pass

        rows.append({
            "company":          company,
            "sector":           classifier.get("sector", "?"),
            "country":          classifier.get("country", "?"),
            "size":             classifier.get("company_size", "?"),
            "hunger_score":     ai_hunger.get("hunger_score", 0),
            "solution_category": proposal.get("solution_category", "?"),
            "solution_title":   proposal.get("solution_title", "?"),
            "estimated_value":  proposal.get("estimated_value", "?"),
            "company_hook":     proposal.get("company_specific_hook", ""),
            "track_record_proof": proposal.get("track_record_proof", ""),
            "email":            db.get("email") or prospect.get("email") or "",
            "outreach_status":  db.get("outreach_status") or "new",
            "source":           db.get("source") or prospect.get("source") or "?",
            "classified_date":  r.get("_mtime", "?"),
            "days_since_sent":  days_since_sent,
            "obsidian_note":    f"Prospects/TrackB_Proposals/{company}.md",
        })
    return rows


# ── Excel export ───────────────────────────────────────────────────────────────
def export_excel(out_path: Path = EXCEL_PATH):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("pip install openpyxl")
        return

    rows = build_rows()
    if not rows:
        print("No Track B companies classified yet — run: python cli.py classify --mode db")
        return

    rows.sort(key=lambda r: r["hunger_score"], reverse=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Proposals"

    STATUS_FILLS = {
        "new":               PatternFill("solid", fgColor="F5F5F5"),
        "researched":        PatternFill("solid", fgColor="E0E7FF"),
        "emailed":           PatternFill("solid", fgColor="DBEAFE"),
        "followed_up_1":     PatternFill("solid", fgColor="BFDBFE"),
        "followed_up_2":     PatternFill("solid", fgColor="93C5FD"),
        "replied":           PatternFill("solid", fgColor="D1FAE5"),
        "meeting_scheduled": PatternFill("solid", fgColor="FEF3C7"),
        "won":               PatternFill("solid", fgColor="86EFAC"),
        "rejected":          PatternFill("solid", fgColor="FEE2E2"),
        "ghosted":           PatternFill("solid", fgColor="F3F4F6"),
    }
    HUNGER_FILLS = {
        range(0, 5):  PatternFill("solid", fgColor="FEE2E2"),
        range(5, 7):  PatternFill("solid", fgColor="FEF3C7"),
        range(7, 9):  PatternFill("solid", fgColor="D1FAE5"),
        range(9, 11): PatternFill("solid", fgColor="86EFAC"),
    }

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin_border = Border(*(Side(style="thin", color="D1D5DB"),) * 4)

    COLS = [
        ("Hunger",      8,  "hunger_score"),
        ("Status",      14, "outreach_status"),
        ("Company",     28, "company"),
        ("Sector",      14, "sector"),
        ("Country",     14, "country"),
        ("Size",        14, "size"),
        ("Category",    20, "solution_category"),
        ("Solution",     28, "solution_title"),
        ("Value",       22, "estimated_value"),
        ("Email",       28, "email"),
        ("Days Since Sent", 14, "days_since_sent"),
        ("Source",      18, "source"),
        ("Classified",  12, "classified_date"),
        ("Company Hook", 40, "company_hook"),
    ]

    for col_idx, (header, width, _) in enumerate(COLS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"

    for row_idx, r in enumerate(rows, start=2):
        for col_idx, (_, _, field) in enumerate(COLS, start=1):
            v = r.get(field, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=v if v is not None else "")
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=(field in ("company_hook", "solution_title")))

        status_fill = STATUS_FILLS.get(r["outreach_status"], PatternFill("solid", fgColor="FFFFFF"))
        for col_idx in range(1, len(COLS) + 1):
            ws.cell(row=row_idx, column=col_idx).fill = status_fill

        hscore = r["hunger_score"]
        for rng, fill in HUNGER_FILLS.items():
            if hscore in rng:
                ws.cell(row=row_idx, column=1).fill = fill
                break

    # ── Summary sheet ──
    ws2 = wb.create_sheet("Summary")
    status_counts = Counter(r["outreach_status"] for r in rows)
    sector_counts = Counter(r["sector"] for r in rows)
    ws2.cell(row=1, column=1, value="Status").font = Font(bold=True)
    ws2.cell(row=1, column=2, value="Count").font = Font(bold=True)
    r_idx = 2
    for status, count in status_counts.most_common():
        ws2.cell(row=r_idx, column=1, value=status)
        ws2.cell(row=r_idx, column=2, value=count)
        r_idx += 1
    r_idx += 1
    ws2.cell(row=r_idx, column=1, value="Sector").font = Font(bold=True)
    ws2.cell(row=r_idx, column=2, value="Count").font = Font(bold=True)
    r_idx += 1
    for sector, count in sector_counts.most_common():
        ws2.cell(row=r_idx, column=1, value=sector)
        ws2.cell(row=r_idx, column=2, value=count)
        r_idx += 1
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 10

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"Excel saved → {out_path} ({len(rows)} companies)")


# ── Obsidian dashboard ───────────────────────────────────────────────────────
def write_obsidian_dashboard() -> Path:
    rows = build_rows()
    PROSPECTS_DIR.mkdir(parents=True, exist_ok=True)

    status_counts = Counter(r["outreach_status"] for r in rows)
    sector_counts = Counter(r["sector"] for r in rows)
    source_counts = Counter(r["source"] for r in rows)

    hot = [r for r in rows if r["hunger_score"] >= 7 and r["outreach_status"] == "new"]
    hot.sort(key=lambda r: r["hunger_score"], reverse=True)

    followup_due = [
        r for r in rows
        if r["days_since_sent"] is not None and (
            (r["outreach_status"] == "emailed" and r["days_since_sent"] >= 3)
            or (r["outreach_status"] == "followed_up_1" and r["days_since_sent"] >= 4)
        )
    ]

    lines = [
        "---",
        "tags: [dashboard, track-b]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "---",
        "",
        "# Track B Dashboard — AI Automation Proposals",
        "",
        "## Stats",
        "| Status | Count |",
        "|---|---|",
    ]
    for status, count in status_counts.most_common():
        lines.append(f"| {status} | {count} |")
    lines += ["", f"**Total:** {len(rows)} companies", ""]

    lines += ["## Hot Targets (hunger ≥7, not yet contacted)", ""]
    if hot:
        lines += ["| Company | Sector | Hunger | Category | Value |", "|---|---|---|---|---|"]
        for r in hot:
            lines.append(
                f"| [[{r['company']}]] | {r['sector']} | {r['hunger_score']}/10 | "
                f"{r['solution_category']} | {r['estimated_value']} |"
            )
    else:
        lines.append("_none_")
    lines.append("")

    lines += ["## Follow-up Due (emailed ≥3 days, no reply)", ""]
    if followup_due:
        lines += ["| Company | Days Since Sent | Email |", "|---|---|---|"]
        for r in followup_due:
            lines.append(f"| [[{r['company']}]] | {r['days_since_sent']} | {r['email']} |")
    else:
        lines.append("_none_")
    lines.append("")

    lines += ["## Kanban", ""]
    for status in ["new", "researched", "emailed", "followed_up_1", "followed_up_2",
                   "replied", "meeting_scheduled", "won", "rejected"]:
        bucket = [r for r in rows if r["outreach_status"] == status]
        if not bucket:
            continue
        lines.append(f"### {status} ({len(bucket)})")
        for r in bucket:
            lines.append(f"- [[{r['company']}]] — {r['sector']} — {r['estimated_value']}")
        lines.append("")

    lines += ["## Sector Breakdown", ""]
    for sector, count in sector_counts.most_common():
        lines.append(f"- {sector}: {count}")
    lines.append("")

    lines += ["## Source Breakdown", ""]
    for source, count in source_counts.most_common():
        lines.append(f"- {source}: {count}")
    lines.append("")

    lines += [
        "## Quick Commands",
        "```",
        "python cli.py source-trackb --sectors wealth,legal --countries worldwide --limit 15",
        "python cli.py classify --mode db --limit 20",
        "python cli.py trackb-find-emails",
        "python cli.py trackb-send --dry-run",
        "python cli.py trackb-linkedin --limit 5",
        "python cli.py trackb-dashboard",
        "python cli.py trackb-excel",
        "python cli.py trackb-sheets",
        "```",
    ]

    DASH_PATH.write_text("\n".join(lines))
    print(f"Obsidian dashboard → {DASH_PATH}")
    return DASH_PATH


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["excel", "dashboard"])
    args = parser.parse_args()

    if args.action == "excel":
        export_excel()
    elif args.action == "dashboard":
        write_obsidian_dashboard()
