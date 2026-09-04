"""
Track B LinkedIn outreach — connect with a decision-maker at each classified
Track B company, using the same Playwright engine + shared daily rate limits
as Track C's social-growth agent (linkedin_agent.py / SENT_LOG), so the two
tracks never combine to exceed LinkedIn's real per-account daily cap.

For each company: search_people() for a likely decision-maker (CEO/Director/
Partner depending on sector), then send_connection_request() with a short
note built from the Agent-3 proposal's company_specific_hook/outreach_hook.

Defaults to dry_run=True everywhere — LinkedIn bans accounts that automate
too aggressively, so nothing real sends without --live.

Usage:
  python cli.py trackb-linkedin --limit 5            # dry-run preview
  python cli.py trackb-linkedin --limit 5 --live      # actually connect
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import linkedin_agent
from track_b_tracker import load_classify_results, load_db_status

# sector -> likely decision-maker title, used in the people-search query
_SECTOR_ROLE = {
    "law firm": "Partner",
    "real_estate": "Director",
    "real estate": "Director",
    "wealth management": "Partner",
    "wealth": "Partner",
    "family office": "Director",
}


def _build_note(proposal: dict) -> str:
    hook = proposal.get("company_specific_hook") or proposal.get("outreach_hook") or ""
    note = f"Hi — {hook} Worth connecting?" if hook else "Hi — came across your firm, worth connecting?"
    return note[:300]


async def run(limit: int = 5, dry_run: bool = True, min_hunger: int = 0) -> dict:
    classify_results = load_classify_results()
    db_status = load_db_status()

    sent, skipped = 0, 0
    for r in classify_results[:limit]:
        company = r.get("company", "")
        ai_hunger_score = r.get("ai_hunger", {}).get("hunger_score", 0)
        if ai_hunger_score < min_hunger:
            skipped += 1
            continue

        db = db_status.get(company.lower(), {})
        # LinkedIn runs as a parallel channel to email — only exclude terminal/closed states.
        if db.get("outreach_status") in ("replied", "won", "rejected"):
            skipped += 1
            continue

        sector = (r.get("classifier", {}) or {}).get("sector", "").lower()
        role = _SECTOR_ROLE.get(sector, "Director")
        query = f"{company} {role}"

        print(f"\n[linkedin] {company}: searching '{query}'...")
        profiles = await linkedin_agent.search_people(query, limit=1)
        if not profiles:
            print(f"  [linkedin] {company}: no profile found — skip")
            skipped += 1
            continue

        note = _build_note(r.get("proposal", {}))
        result = await linkedin_agent.send_connection_request(profiles[0], note=note, dry_run=dry_run)
        print(f"  [linkedin] {company} → {profiles[0]} : {result['status']}"
              + (f" ({result.get('error','')})" if result.get('error') else ""))

        if result["status"] in ("sent", "dry_run"):
            sent += 1
        else:
            skipped += 1

        await asyncio.sleep(2)

    return {"sent": sent, "skipped": skipped}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--min-hunger", type=int, default=0)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    summary = asyncio.run(run(limit=args.limit, dry_run=not args.live, min_hunger=args.min_hunger))
    print(f"\nSent: {summary['sent']} | Skipped: {summary['skipped']}")
