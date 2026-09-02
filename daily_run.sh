#!/bin/bash
# Networking Agent — Daily Runner (2-Direction Architecture)
#
# Cron schedule:
#   0 6  * * * /bin/bash /Users/aitsgroup/networking-agent/daily_run.sh >> /Users/aitsgroup/networking-agent/logs/daily.log 2>&1
#   0 12 * * * /bin/bash /Users/aitsgroup/networking-agent/daily_run.sh --replies-only >> /Users/aitsgroup/networking-agent/logs/daily.log 2>&1
#   0 18 * * * /bin/bash /Users/aitsgroup/networking-agent/daily_run.sh --replies-only >> /Users/aitsgroup/networking-agent/logs/daily.log 2>&1
#
# Direction A (Proposal) — 70% of company budget:
#   Discover → Analyze GitHub → Route → Draft proposal email
# Direction B (Job) — 30% of company budget:
#   Discover roles → Score fit → Draft candidate email

set -euo pipefail

cd /Users/aitsgroup/networking-agent
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%Y-%m-%d).log"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
    echo "[$(timestamp)] $*" | tee -a "$LOG"
}

divider() {
    echo "" | tee -a "$LOG"
    echo "────────────────────────────────────────" | tee -a "$LOG"
    log "$*"
    echo "────────────────────────────────────────" | tee -a "$LOG"
}

# ── Load env ──────────────────────────────────────────────────────────────────
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

export SENDER_EMAIL="${SENDER_EMAIL:-saraswatdas94@gmail.com}"

divider "NETWORKING AGENT DAILY RUN — $(timestamp)"
log "Sender: $SENDER_EMAIL"
log "Mode: ${1:-full}"

# ── Replies-only mode (midday + evening cron) ─────────────────────────────────
if [ "${1:-}" = "--replies-only" ]; then
    divider "REPLY MONITOR"
    python3 agents/reply_monitor.py 2>&1 | tee -a "$LOG"
    log "Reply check done."
    exit 0
fi

# ── Direction A: PROPOSAL (70%) ───────────────────────────────────────────────
divider "DIRECTION A — PROPOSAL PIPELINE"

log "[A1] Discovering companies with GitHub signals..."
# Run via networking-agent MCP (Claude handles this — this script triggers the daily loop)
# For autonomous: would call networking-agent binary directly with a discovery command
# For now: log that discovery step needs Claude session
log "  → Open Claude Code and run: search_funding_news + search_github_trending + search_remotive"
log "  → Then: analyze_company_depth for each, route_prospect, draft_proposal_email"

# ── Direction B: JOB (30%) ────────────────────────────────────────────────────
divider "DIRECTION B — JOB PIPELINE"

log "[B1] Discovering open roles..."
log "  → Open Claude Code and run: search_workatastartup + search_remotive + search_hn_hiring"
log "  → Then: score_repo_issues, draft_warm_email with tone=candidate"

# ── Reply Monitor ─────────────────────────────────────────────────────────────
divider "REPLY MONITOR"

log "[R] Checking Gmail for replies..."
python3 agents/reply_monitor.py 2>&1 | tee -a "$LOG"

# ── Follow-up due ─────────────────────────────────────────────────────────────
divider "FOLLOW-UP QUEUE"

log "[F] Prospects due for follow-up (7+ days, no reply):"
python3 agents/reply_monitor.py --followups 2>&1 | tee -a "$LOG"

# ── LinkedIn ──────────────────────────────────────────────────────────────────
divider "LINKEDIN (Direction A — Proposal Connects)"

log "[LI] Sending connection requests to proposal targets..."
python3 agents/cli.py social --li-connect 15 --li-follow 60 2>&1 | tee -a "$LOG" || log "  [LI] cli.py social failed — skipping"

# ── Stats ─────────────────────────────────────────────────────────────────────
divider "PIPELINE STATS"

python3 - <<'PYEOF' 2>&1 | tee -a "$LOG"
import sqlite3, os
from pathlib import Path
db_path = os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db"))
try:
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT outreach_status, direction, COUNT(*) FROM prospects WHERE archived=0 GROUP BY outreach_status, direction ORDER BY direction, COUNT(*) DESC"
    ).fetchall()
    print("\nPipeline breakdown:")
    print(f"  {'status':<22} {'direction':<12} {'count':>6}")
    print(f"  {'-'*22} {'-'*12} {'-'*6}")
    for status, direction, count in rows:
        print(f"  {(status or 'unknown'):<22} {(direction or 'unrouted'):<12} {count:>6}")

    today_emails = db.execute(
        "SELECT COUNT(*) FROM outreach_log WHERE channel='email' AND DATE(sent_at)=DATE('now')"
    ).fetchone()[0]
    replies_total = db.execute(
        "SELECT COUNT(*) FROM prospects WHERE outreach_status='replied'"
    ).fetchone()[0]
    proposals_total = db.execute(
        "SELECT COUNT(*) FROM proposals"
    ).fetchone()[0]

    print(f"\n  Emails sent today: {today_emails}/8")
    print(f"  Total replies:     {replies_total}")
    print(f"  Proposals stored:  {proposals_total}")
    db.close()
except Exception as e:
    print(f"  Stats error: {e}")
PYEOF

divider "DONE — $(timestamp)"
