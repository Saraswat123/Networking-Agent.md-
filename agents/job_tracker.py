"""
Job Application Tracker — Excel + Obsidian dashboard.

Excel:  agents/output/jobs/applications.xlsx
        Columns: Company | Role | Source | Score | Salary | Team | Batch | Tech Domains |
                 Applied Date | Email Sent To | Status | Follow-up Date | Notes | JD URL | CV Used

Obsidian: Jobs/Dashboard.md — kanban-style master view
          Jobs/Applications/<date>_<company>.md — per-application notes (already built in job_pipeline.py)

Usage:
  python job_tracker.py excel              # export all DB rows to Excel
  python job_tracker.py dashboard          # write Obsidian dashboard
  python job_tracker.py update --company X --status replied
  python cli.py jobs-dashboard             # same via CLI
"""
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

OUTPUT_DIR  = Path(__file__).parent / "output" / "jobs"
JOBS_DB     = OUTPUT_DIR / "jobs.db"
VAULT_PATH  = Path("/Users/aitsgroup/Documents/Obsidian Vault")
JOBS_DIR    = VAULT_PATH / "Jobs"
DASH_PATH   = JOBS_DIR / "Dashboard.md"
EXCEL_PATH  = OUTPUT_DIR / "applications.xlsx"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)


# ── Excel Export ──────────────────────────────────────────────────────────────
def export_excel(db_path: Path = JOBS_DB, out_path: Path = EXCEL_PATH):
    """Export all applications from SQLite → Excel with formatting."""
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side, numbers
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("pip install openpyxl")
        return

    # ── Load data ──
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM job_applications ORDER BY score DESC, created_at DESC"
    ).fetchall()
    con.close()

    if not rows:
        print("No applications in DB yet.")
        return

    # ── Workbook ──
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applications"

    # ── Status colors ──
    STATUS_FILLS = {
        "found":      PatternFill("solid", fgColor="F5F5F5"),
        "applied":    PatternFill("solid", fgColor="DBEAFE"),   # blue
        "replied":    PatternFill("solid", fgColor="D1FAE5"),   # green
        "interview":  PatternFill("solid", fgColor="FEF3C7"),   # yellow
        "offer":      PatternFill("solid", fgColor="BBFAD7"),   # bright green
        "rejected":   PatternFill("solid", fgColor="FEE2E2"),   # red
        "ghosted":    PatternFill("solid", fgColor="F3F4F6"),   # grey
    }
    SCORE_FILLS = {
        range(0,  7): PatternFill("solid", fgColor="FEE2E2"),  # red
        range(7, 12): PatternFill("solid", fgColor="FEF3C7"),  # yellow
        range(12,20): PatternFill("solid", fgColor="D1FAE5"),  # green
        range(20,26): PatternFill("solid", fgColor="86EFAC"),  # bright green
    }

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin_border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )

    # ── Columns definition ──
    COLS = [
        ("Score",          8,  "score"),
        ("Status",         12, "status"),
        ("Company",        22, "company"),
        ("Role",           30, "role"),
        ("Source",         12, "source"),
        ("Batch/Fund",     12, "batch"),
        ("Team Size",      10, "team_size"),
        ("Salary",         14, "salary_range"),
        ("Applied Date",   13, "applied_date"),
        ("Email Sent To",  28, "email_sent_to"),
        ("Follow-up",      13, None),   # computed
        ("JD URL",         40, "jd_url"),
        ("CV Used",        25, "cv_file"),
        ("Notes",          40, "notes"),
        ("Created",        13, "created_at"),
    ]

    # ── Header row ──
    for col_idx, (header, width, _) in enumerate(COLS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill  = header_fill
        cell.font  = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    # ── Data rows ──
    for row_idx, row in enumerate(rows, start=2):
        d = dict(row)

        # Compute follow-up date (applied + 3 days)
        followup = ""
        if d.get("applied_date"):
            try:
                app_dt = datetime.strptime(d["applied_date"][:10], "%Y-%m-%d")
                followup = (app_dt + timedelta(days=3)).strftime("%Y-%m-%d")
            except Exception:
                pass

        values = []
        for _, _, field in COLS:
            if field is None:
                values.append(followup)
            elif field == "created_at":
                v = d.get(field, "")
                values.append(v[:10] if v else "")
            else:
                values.append(d.get(field, "") or "")

        status = str(d.get("status", "found")).lower()
        score  = int(d.get("score", 0) or 0)

        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border    = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx in (4, 14)))

            # Status color (column 2)
            if col_idx == 2:
                fill = STATUS_FILLS.get(status, PatternFill("solid", fgColor="F9FAFB"))
                cell.fill = fill
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Score color (column 1)
            if col_idx == 1:
                for r, fill in SCORE_FILLS.items():
                    if score in r:
                        cell.fill = fill
                        break
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")

        ws.row_dimensions[row_idx].height = 20

    # ── Summary sheet ──
    ws2 = wb.create_sheet("Summary")
    from collections import Counter
    status_counts = Counter(dict(r).get("status", "found") for r in rows)
    source_counts = Counter(dict(r).get("source", "?") for r in rows)

    ws2["A1"] = "Status Breakdown"
    ws2["A1"].font = Font(bold=True, size=12)
    ws2["A2"] = "Status"
    ws2["B2"] = "Count"
    for i, (s, n) in enumerate(sorted(status_counts.items()), start=3):
        ws2[f"A{i}"] = s
        ws2[f"B{i}"] = n

    ws2["D1"] = "By Source"
    ws2["D1"].font = Font(bold=True, size=12)
    ws2["D2"] = "Source"
    ws2["E2"] = "Count"
    for i, (s, n) in enumerate(sorted(source_counts.items(), key=lambda x: -x[1]), start=3):
        ws2[f"D{i}"] = s
        ws2[f"E{i}"] = n

    ws2["G1"] = "Total"
    ws2["G1"].font = Font(bold=True, size=12)
    ws2["G2"] = len(rows)
    ws2["G3"] = f"Avg score: {sum(int(dict(r).get('score',0) or 0) for r in rows) / max(len(rows),1):.1f}"

    wb.save(out_path)
    print(f"[tracker] Excel saved → {out_path}")
    print(f"          {len(rows)} applications, {len(set(dict(r).get('status') for r in rows))} statuses")
    return out_path


# ── Obsidian Dashboard ────────────────────────────────────────────────────────
def write_obsidian_dashboard(db_path: Path = JOBS_DB) -> Path:
    """
    Write master Obsidian dashboard — kanban-style with all applications.

    Layout:
      ## Stats
      ## Kanban: found → applied → replied → interview → offer/rejected
      ## High Score Targets (score ≥ 12)
      ## Follow-up Needed
      ## Cold Pitch Queue (no careers page found)
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM job_applications ORDER BY score DESC, created_at DESC"
    ).fetchall()]
    con.close()

    today = date.today().isoformat()
    total = len(rows)

    from collections import defaultdict
    by_status = defaultdict(list)
    for r in rows:
        by_status[r.get("status", "found")].append(r)

    # Follow-up needed: applied > 3 days ago, no reply
    followup_needed = []
    for r in by_status.get("applied", []):
        app_date = r.get("applied_date", "")
        if app_date:
            try:
                app_dt = datetime.strptime(app_date[:10], "%Y-%m-%d")
                if (datetime.now() - app_dt).days >= 3:
                    followup_needed.append(r)
            except Exception:
                pass

    # High score targets not yet applied
    hot = [r for r in by_status.get("found", []) if (r.get("score") or 0) >= 12]

    def _row_line(r, show_email=False):
        score = r.get("score", 0) or 0
        sal   = r.get("salary_range") or "?"
        ts    = f"team:{r['team_size']}" if r.get("team_size") else ""
        src   = r.get("source", "?")
        url   = r.get("jd_url") or r.get("url") or ""
        email = r.get("email_sent_to") or ""
        applied = r.get("applied_date") or ""
        note_link = f"[[{applied[:10] if applied else today}_{re.sub(chr(32),'_',r['company'])}_{re.sub(chr(32),'_',r['role'][:20])}]]"
        base = f"- **[{score}/25]** [{r['company']}]({url}) — {r['role'][:40]} | {sal} | {ts} | {src}"
        if show_email and email:
            base += f" | 📧 {email}"
        if applied:
            base += f" | applied:{applied[:10]}"
        return base

    content = f"""---
updated: {today}
type: job-dashboard
---

# 🎯 Job Application Dashboard
**Updated:** {today} | **Total:** {total} applications

---

## 📊 Stats

| Status | Count |
|--------|-------|
""" + "\n".join(
        f"| {s} | {len(v)} |"
        for s, v in sorted(by_status.items(), key=lambda x: -len(x[1]))
    ) + f"""

**Applied:** {len(by_status.get('applied',[]))} | **Replied:** {len(by_status.get('replied',[]))} | **Interview:** {len(by_status.get('interview',[]))} | **Offer:** {len(by_status.get('offer',[]))}

---

## 🔥 Hot Targets — Apply Today (score ≥ 12, not yet applied)

""" + (
    "\n".join(_row_line(r) for r in hot[:15]) if hot else "_None found. Run `python cli.py jobs-hunt`_"
) + """

---

## 📬 Follow-up Needed (applied ≥ 3 days ago, no reply)

""" + (
    "\n".join(_row_line(r, show_email=True) for r in followup_needed[:20])
    if followup_needed else "_None. You're on top of things._"
) + """

---

## 🗂️ Kanban

### 🟡 Applied

""" + "\n".join(_row_line(r, show_email=True) for r in by_status.get("applied", [])[:30]) + """

### 🟢 Replied

""" + "\n".join(_row_line(r) for r in by_status.get("replied", [])[:20]) + """

### 🟣 Interview

""" + "\n".join(_row_line(r) for r in by_status.get("interview", [])[:20]) + """

### ⚫ Found (not yet applied)

""" + "\n".join(_row_line(r) for r in by_status.get("found", [])[:30]) + """

### ❌ Rejected

""" + "\n".join(_row_line(r) for r in by_status.get("rejected", [])[:15]) + """

---

## 📋 Source Breakdown

""" + "\n".join(
    f"- **{src}**: {len(jobs)} applications"
    for src, jobs in sorted(
        {s: [r for r in rows if r.get("source") == s] for s in set(r.get("source","?") for r in rows)}.items(),
        key=lambda x: -len(x[1])
    )
) + """

---

## 🔄 Quick Commands

```bash
# Search new jobs (24h)
python cli.py jobs --search genai --sources yc,hn,remoteok,workatastartup --max-age 1

# Hunt tiny YC teams
python cli.py jobs-hunt --max-team 15 --batches W25,S24

# Apply + generate CV + email
python cli.py jobs-apply --company X --role "AI Engineer" --jd agents/jds/X.txt --domain X.com

# Update status after reply
python cli.py jobs-update --company X --role "AI Engineer" --status replied

# Refresh this dashboard
python cli.py jobs-dashboard

# Export to Excel
python cli.py jobs-excel
```
"""

    DASH_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASH_PATH.write_text(content)
    print(f"[tracker] Dashboard → {DASH_PATH}")
    return DASH_PATH


def update_status(company: str, role: str, status: str, notes: str = "", replied_date: str = ""):
    """Update application status in DB + regenerate dashboard."""
    con = sqlite3.connect(JOBS_DB)
    con.execute(
        "UPDATE job_applications SET status=? WHERE company=? AND role=?",
        (status, company, role),
    )
    if notes:
        con.execute(
            "UPDATE job_applications SET notes=? WHERE company=? AND role=?",
            (notes, company, role),
        )
    if replied_date or status in ("replied", "interview"):
        con.execute(
            "UPDATE job_applications SET replied_date=? WHERE company=? AND role=?",
            (replied_date or date.today().isoformat(), company, role),
        )
    con.commit()
    con.close()
    write_obsidian_dashboard()
    export_excel()
    print(f"Updated: {company} — {role} → {status}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("excel",     help="Export to Excel")
    sub.add_parser("dashboard", help="Write Obsidian dashboard")
    p_update = sub.add_parser("update", help="Update status")
    p_update.add_argument("--company", required=True)
    p_update.add_argument("--role",    required=True)
    p_update.add_argument("--status",  required=True)
    p_update.add_argument("--notes",   default="")
    args = parser.parse_args()

    if args.cmd == "excel":
        export_excel()
    elif args.cmd == "dashboard":
        write_obsidian_dashboard()
    elif args.cmd == "update":
        update_status(args.company, args.role, args.status, args.notes)
    else:
        export_excel()
        write_obsidian_dashboard()
