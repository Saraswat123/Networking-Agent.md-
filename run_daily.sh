#!/bin/bash
# Daily growth automation — runs at 9am via cron
# Cron entry: 0 9 * * * /Users/aitsgroup/networking-agent/run_daily.sh

cd /Users/aitsgroup/networking-agent

LOG="/Users/aitsgroup/networking-agent/agents/output/daily_growth/cron_$(date +%Y-%m-%d).log"
mkdir -p "$(dirname "$LOG")"

echo "=== Daily Growth Run: $(date) ===" >> "$LOG"
python3 agents/cli.py grow >> "$LOG" 2>&1
echo "=== Done: $(date) ===" >> "$LOG"
