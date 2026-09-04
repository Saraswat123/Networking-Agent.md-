"""Export apply_queue.json to CSV (opens in Excel/Sheets)."""
import json, csv
from pathlib import Path
from datetime import date

QUEUE = Path("/Users/aitsgroup/networking-agent/agents/apply_queue.json")
OUT   = Path(f"/Users/aitsgroup/Desktop/outreach_database_{date.today()}.csv")

FIELDS = [
    "company", "email", "email_confirmed",
    "status_email", "email_sent_date", "batch", "tier", "source"
]

with open(QUEUE) as f:
    data = json.load(f)

# Sort: most recent first
data.sort(key=lambda x: x.get("email_sent_date", ""), reverse=True)

with open(OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in data:
        writer.writerow({k: row.get(k, "") for k in FIELDS})

print(f"Exported {len(data)} companies → {OUT}")
print(f"\nBreakdown by batch:")
from collections import Counter
batches = Counter(r.get("batch","") for r in data)
for batch, count in sorted(batches.items()):
    print(f"  {batch:30s} {count}")

print(f"\nBreakdown by source:")
sources = Counter(r.get("source","") for r in data)
for src, count in sorted(sources.items()):
    print(f"  {src:20s} {count}")
