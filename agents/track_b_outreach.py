"""
Track B Outreach — email discovery + batch sending for classified Track B companies.

Pipeline position: source_track_b() → classify (--mode db) → HERE → track_b_tracker.

  1. find_missing_emails()  — resolve a real-world mailbox (Hunter/Snov/pattern fallback)
     for every Track B company that doesn't have one yet, using the website resolved
     during sourcing. Writes into prospects.email.
  2. send_batch()           — send the Agent-3-generated email draft (from the Obsidian
     TrackB note) via Gmail SMTP, defaults to dry_run=True. On a real send, marks the
     prospect 'emailed' in the DB so the tracker/follow-up logic picks it up.

Requires GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env for real sends (dry_run works without).
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import classifier_agent
import email_sender
from track_b_tracker import load_classify_results, load_sent_log
from sources.email.finder import find_email, TRACK_B_ROLE_PRIORITY

DB_PATH = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))


def find_missing_emails(limit: int = 50, dry_run: bool = False) -> dict:
    """
    For every classified Track B company with no email on file, resolve one via
    find_email() (Hunter → Snov → pattern fallback) using the website stored in
    prospect notes at sourcing time. Writes to prospects.email unless dry_run.
    """
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return {"resolved": 0, "skipped": 0}

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    track_b = {r["company"]: r for r in load_classify_results()}
    resolved, skipped = 0, 0

    for company, result in list(track_b.items())[:limit]:
        row = con.execute(
            "SELECT id, email, notes FROM prospects WHERE company = ? OR name = ? LIMIT 1",
            (company, company),
        ).fetchone()
        if row is None:
            skipped += 1
            continue
        if row["email"]:
            skipped += 1
            continue

        website = classifier_agent.extract_website_from_prospect({"notes": row["notes"] or ""})
        if not website:
            print(f"  [find-email] {company}: no website on file — skip")
            skipped += 1
            continue

        domain = website.replace("https://", "").replace("http://", "").split("/")[0]
        result_e = find_email(company, domain, role_priority=TRACK_B_ROLE_PRIORITY)
        email = result_e.get("email", "")
        confidence = result_e.get("confidence", "?")

        print(f"  [find-email] {company}: {email} (confidence={confidence}, method={result_e.get('method')})")

        if not dry_run and email:
            con.execute("UPDATE prospects SET email = ? WHERE id = ?", (email, row["id"]))
            con.commit()
        resolved += 1
        time.sleep(0.3)

    con.close()
    return {"resolved": resolved, "skipped": skipped}


def send_batch(limit: int = 20, dry_run: bool = True, min_hunger: int = 0) -> dict:
    """
    Send the Agent-3 email draft (from Obsidian TrackB note) to every classified
    Track B company that has an email on file and outreach_status == 'new'.

    dry_run=True (default): prints what would be sent, sends nothing, changes nothing.
    dry_run=False: actually sends via Gmail SMTP — requires GMAIL_ADDRESS/APP_PASSWORD,
    and marks the prospect 'emailed' in the DB on success.
    """
    if not dry_run and (not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD")):
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env — cannot send for real.")
        print("App password: myaccount.google.com/apppasswords")
        return {"sent": 0, "skipped": 0, "error": "no_gmail_creds"}

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    track_b = {r["company"]: r for r in load_classify_results()}
    sent, skipped = 0, 0

    for company, result in track_b.items():
        ai_hunger_score = result.get("ai_hunger", {}).get("hunger_score", 0)
        if ai_hunger_score < min_hunger:
            skipped += 1
            continue

        row = con.execute(
            "SELECT email, outreach_status FROM prospects WHERE company = ? OR name = ? LIMIT 1",
            (company, company),
        ).fetchone()
        if row is None or not row["email"]:
            print(f"  [send] {company}: no email on file — run trackb-find-emails first")
            skipped += 1
            continue
        if row["outreach_status"] not in ("new",):
            skipped += 1
            continue

        try:
            res = email_sender.send_track_b_email(company, row["email"], dry_run=dry_run)
        except (FileNotFoundError, ValueError) as e:
            print(f"  [send] {company}: {e}")
            skipped += 1
            continue

        if res["status"] == "sent":
            con.execute(
                "UPDATE prospects SET outreach_status='emailed' WHERE company = ? OR name = ?",
                (company, company),
            )
            con.commit()
            sent += 1
        elif res["status"] == "dry_run":
            sent += 1
        time.sleep(1)

    con.close()
    return {"sent": sent, "skipped": skipped}


def send_followups(dry_run: bool = True) -> dict:
    """
    Send day-3 (follow_up_1) and day-7 breakup (follow_up_2) per REPLY-RATE RULES.

    Stages: emailed --(>=3 days, no reply)--> followed_up_1 --(>=4 more days)--> followed_up_2.
    Status gating means each stage only fires once per company; a reply (status
    set to 'replied' by hand or future inbox-check) stops the sequence immediately.
    """
    if not dry_run and (not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD")):
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env — cannot send for real.")
        return {"sent": 0, "skipped": 0, "error": "no_gmail_creds"}

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    track_b = {r["company"]: r for r in load_classify_results()}
    sent_log = load_sent_log()
    sent, skipped = 0, 0

    for company, result in track_b.items():
        row = con.execute(
            "SELECT email, outreach_status FROM prospects WHERE company = ? OR name = ? LIMIT 1",
            (company, company),
        ).fetchone()
        if row is None or not row["email"]:
            skipped += 1
            continue

        sent_ts = sent_log.get(company.lower(), "")
        days_since_sent = None
        if sent_ts:
            from datetime import datetime
            try:
                days_since_sent = (datetime.now() - datetime.fromisoformat(sent_ts)).days
            except Exception:
                pass

        proposal = result.get("proposal", {})
        status = row["outreach_status"]
        stage, body, next_status = None, None, None

        if status == "emailed" and days_since_sent is not None and days_since_sent >= 3:
            stage, body, next_status = "follow_up_1", proposal.get("follow_up_1", ""), "followed_up_1"
        elif status == "followed_up_1" and days_since_sent is not None and days_since_sent >= 4:
            stage, body, next_status = "follow_up_2", proposal.get("follow_up_2", ""), "followed_up_2"
        else:
            skipped += 1
            continue

        if not body:
            print(f"  [followup] {company}: no {stage} text generated — skip")
            skipped += 1
            continue

        subject = f"Re: {proposal.get('email_subject', company)}"
        res = email_sender.send_email(row["email"], subject, body, dry_run=dry_run, company=company)
        print(f"  [followup] {company} ({stage}) → {row['email']} : {res['status']}")

        if res["status"] == "sent":
            con.execute(
                "UPDATE prospects SET outreach_status = ? WHERE company = ? OR name = ?",
                (next_status, company, company),
            )
            con.commit()
            sent += 1
        elif res["status"] == "dry_run":
            sent += 1
        time.sleep(1)

    con.close()
    return {"sent": sent, "skipped": skipped}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)

    p1 = sub.add_parser("find-emails")
    p1.add_argument("--limit", type=int, default=50)
    p1.add_argument("--dry-run", action="store_true")

    p2 = sub.add_parser("send")
    p2.add_argument("--limit", type=int, default=20)
    p2.add_argument("--min-hunger", type=int, default=0)
    p2.add_argument("--live", action="store_true", help="Actually send (default is dry-run)")

    args = parser.parse_args()

    if args.action == "find-emails":
        summary = find_missing_emails(limit=args.limit, dry_run=args.dry_run)
        print(f"\nResolved: {summary['resolved']} | Skipped: {summary['skipped']}")
    elif args.action == "send":
        summary = send_batch(limit=args.limit, dry_run=not args.live, min_hunger=args.min_hunger)
        print(f"\nSent: {summary['sent']} | Skipped: {summary['skipped']}")
