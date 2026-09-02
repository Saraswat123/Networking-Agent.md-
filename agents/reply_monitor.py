"""
Reply Monitor — checks Gmail (saraswatdas94@gmail.com) for replies from prospects.
Updates SQLite outreach_status → 'replied' when match found.

Run:
  python3 agents/reply_monitor.py              # check + update DB
  python3 agents/reply_monitor.py --dry-run    # print matches only
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import gmail_oauth

DB_PATH = os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db"))
SENT_LOG = Path(__file__).parent / "output" / "sent_emails.jsonl"
REPLY_LOG = Path(__file__).parent / "output" / "reply_log.jsonl"


def load_sent_emails() -> list[dict]:
    """Load all sent emails from log."""
    if not SENT_LOG.exists():
        return []
    out = []
    with open(SENT_LOG) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def get_prospect_emails(db: sqlite3.Connection) -> dict[str, int]:
    """Map email → prospect_id for all emailed prospects."""
    cur = db.execute(
        "SELECT id, email FROM prospects WHERE email IS NOT NULL AND outreach_status IN ('emailed', 'researched', 'github_engaged')"
    )
    return {row[1].lower(): row[0] for row in cur.fetchall()}


def check_replies(dry_run: bool = False) -> list[dict]:
    """
    Check Gmail inbox for replies from prospects.
    Updates DB outreach_status to 'replied' for matches.
    Returns list of reply records found.
    """
    print(f"[reply_monitor] Checking Gmail for replies — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    try:
        threads = gmail_oauth.get_inbox_threads(max_results=50, label="INBOX")
    except Exception as e:
        print(f"[reply_monitor] Gmail error: {e}")
        return []

    if not threads:
        print("[reply_monitor] No inbox threads found.")
        return []

    db = sqlite3.connect(DB_PATH)
    prospect_map = get_prospect_emails(db)

    replies_found = []

    for thread in threads:
        sender_email = thread.get("from", "").lower()
        subject = thread.get("subject", "")
        snippet = thread.get("snippet", "")
        thread_id = thread.get("thread_id", "")
        received = thread.get("date", "")

        # Match against known prospect emails
        matched_id = None
        for email, pid in prospect_map.items():
            if email in sender_email:
                matched_id = pid
                break

        if matched_id is None:
            continue

        reply = {
            "prospect_id": matched_id,
            "from": sender_email,
            "subject": subject,
            "snippet": snippet,
            "thread_id": thread_id,
            "received": received,
            "logged_at": datetime.utcnow().isoformat(),
        }
        replies_found.append(reply)

        if dry_run:
            print(f"  [DRY RUN] Reply from {sender_email} (prospect_id={matched_id}): {snippet[:80]}")
            continue

        # Update prospect status
        db.execute(
            "UPDATE prospects SET outreach_status = 'replied' WHERE id = ? AND outreach_status != 'meeting_scheduled'",
            (matched_id,),
        )

        # Log to outreach_log
        db.execute(
            "INSERT INTO outreach_log (prospect_id, channel, message, sent_at) VALUES (?, 'email_reply', ?, ?)",
            (matched_id, f"from={sender_email} subject={subject}", datetime.utcnow().isoformat()),
        )

        print(f"  REPLY: {sender_email} → prospect_id={matched_id} | {snippet[:60]}")

    if not dry_run:
        db.commit()

    db.close()

    # Append to reply log
    if replies_found and not dry_run:
        REPLY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(REPLY_LOG, "a") as f:
            for r in replies_found:
                f.write(json.dumps(r) + "\n")

    print(f"[reply_monitor] Done — {len(replies_found)} replies matched.")
    return replies_found


def show_pending_followups(days: int = 7) -> None:
    """Print prospects due for follow-up (emailed N+ days ago, no reply)."""
    db = sqlite3.connect(DB_PATH)
    cur = db.execute(
        """
        SELECT id, name, email, company, email_sent_at
        FROM prospects
        WHERE outreach_status = 'emailed'
          AND archived = 0
          AND follow_up_sent_at IS NULL
          AND email_sent_at IS NOT NULL
          AND CAST((julianday('now') - julianday(email_sent_at)) AS INTEGER) >= ?
        ORDER BY email_sent_at ASC
        """,
        (days,),
    )
    rows = cur.fetchall()
    db.close()

    if not rows:
        print(f"[reply_monitor] No follow-ups due (threshold: {days} days).")
        return

    print(f"\n[reply_monitor] Follow-ups due ({len(rows)} prospects, {days}+ days since email):")
    for pid, name, email, company, sent_at in rows:
        print(f"  id={pid} | {name} <{email}> @ {company} — sent {sent_at}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    followup_only = "--followups" in sys.argv

    if followup_only:
        show_pending_followups()
    else:
        check_replies(dry_run=dry_run)
        show_pending_followups()
