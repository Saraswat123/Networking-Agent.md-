"""
Generate Track B outreach for all companies in Obsidian TrackB_Proposals/.
Reads proposal data from notes → generates email + LinkedIn + follow-ups → saves JSON.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import outreach_agent
import obsidian_sync

COMPANIES = [
    {
        "company_name": "Stonehage Fleming",
        "sector": "family office / wealth management",
        "location": "London, UK",
        "contact_name": "Charlotte Thorne",
        "contact_role": "COO",
        "contact_email": "cthorne@stonehagefleming.com",
        "pain_points": [
            "Manual portfolio consolidation across asset classes and entities",
            "Client reporting built by hand in Excel/Word each cycle",
            "Email-based client communication and status updates",
            "Manual compliance/KYC document collection and tracking",
            "Ad-hoc tracking of family entities, trusts, intercompany transactions",
        ],
        "solution_title": "Family Office Intelligence Layer",
        "solution_description": "Claude-powered backend that consolidates portfolio data across asset classes, auto-generates client reports, and extracts KYC/trust documents into structured records.",
        "hook": "Your reporting team is still rebuilding the same Excel performance pack every cycle — that's a data pipeline problem, not a headcount problem.",
        "estimated_value": "£35,000-55,000 setup + £3,500/mo",
        "deliverables": [
            "Automated portfolio consolidation from custodian/bank feeds",
            "AI-generated client performance reports (Word/PDF) from live data",
            "Claude-drafted client update emails, reviewer-approved before send",
            "Document intake pipeline for KYC, trust, and tax docs",
            "Entity/trust/intercompany transaction tracker",
        ],
        "hunger_score": 6,
    },
    {
        "company_name": "Knight Frank",
        "sector": "real estate consultancy",
        "location": "London, UK",
        "contact_name": "Alasdair Nicholls",
        "contact_role": "Chief Executive",
        "contact_email": "alasdair.nicholls@knightfrank.com",
        "pain_points": [
            "Manual market/valuation report compilation in Excel and Word",
            "Lead intake and qualification done by agents via email/phone — no scoring",
            "Property listing data entry duplicated across portals and internal CRM",
            "Client portfolio/asset summaries built manually per request",
            "Comparable sales/market research pulled manually from multiple sources",
        ],
        "solution_title": "Valuation & Listing Intelligence Suite",
        "solution_description": "AI layer that turns raw property data, comparables, and inbound inquiries into drafted valuation reports, scored leads, and synced listings — cutting manual Excel/Word grind per deal.",
        "hook": "Your agents still hand-build valuation reports in Word while comparables sit scattered across three sources — we automate that end to end.",
        "estimated_value": "£35,000-55,000 setup + £3,500/mo",
        "deliverables": [
            "Automated market/valuation report generator (pulls comparables, drafts Word/PDF)",
            "Lead scoring bot for inbound inquiries ranked by deal likelihood",
            "AI-drafted client emails and portfolio summary generator",
            "Listing sync/dedup engine across CRM and portals (Rightmove, Zoopla)",
            "Comparable sales research from Land Registry + internal sold data",
        ],
        "hunger_score": 7,
    },
    {
        "company_name": "Al Tamimi and Company",
        "sector": "law firm (MENA)",
        "location": "Dubai, UAE",
        "contact_name": "Husam Hourani",
        "contact_role": "Managing Partner",
        "contact_email": "h.hourani@tamimi.com",
        "pain_points": [
            "Manual contract review and redlining by associates",
            "Client intake and conflict-check done via email/forms",
            "Document drafting from templates by hand",
            "Legal research compiled manually per matter",
            "Billing/time tracking reconciled in Excel",
        ],
        "solution_title": "AI Matter Intelligence Suite",
        "solution_description": "AI layer across intake, drafting, research, and billing — cutting associate hours on repetitive document work. Claude-powered clause extraction and conflict screening let fee-earners focus on judgment calls, not paperwork.",
        "hook": "Your associates are still redlining NDAs by hand while AI can flag the risky clauses in seconds — that's billable hours lost to busywork, not judgment.",
        "estimated_value": "$45,000-70,000 setup + $4,500/mo",
        "deliverables": [
            "AI contract review: clause extraction, risk flagging, redline suggestions",
            "Automated client intake + conflict-check system",
            "Template-based document generator (NDAs, MSAs, engagement letters)",
            "AI legal research assistant: summarization + citation-checked memos",
            "Billing/time reconciliation dashboard",
        ],
        "hunger_score": 7,
    },
    {
        "company_name": "Gateley Legal",
        "sector": "law firm (UK plc)",
        "location": "London, UK",
        "contact_name": "Rod Waldie",
        "contact_role": "CEO",
        "contact_email": "rod.waldie@gateleyplc.com",
        "pain_points": [
            "Manual contract review and redlining by associates",
            "Client intake and matter onboarding via email/forms",
            "Time tracking and billing reconciliation across departments",
            "Due diligence document review for M&A, real estate, finance",
            "Drafting routine correspondence and standard clauses",
        ],
        "solution_title": "Gateley Diligence Engine: AI Contract & DD Automation",
        "solution_description": "AI layer that reads contracts and due diligence bundles — flagging risk clauses, extracting key terms, generating first-pass redlines in minutes. Rust backend handles large M&A/real estate data rooms without choking.",
        "hook": "Your associates are still redlining NDAs and reconciling time entries by hand — that's billable hours going into work AI now does in minutes.",
        "estimated_value": "£35,000-55,000 setup + £4,000-6,000/mo",
        "deliverables": [
            "AI clause-extraction and redlining tool for contract review",
            "Due diligence document review pipeline for M&A/real estate/finance",
            "Client intake + conflict check triage bot",
            "Auto-drafted client correspondence templates",
            "Billing narrative generator from raw time entries",
        ],
        "hunger_score": 6,
    },
    {
        "company_name": "Portcullis Group",
        "sector": "trust and family office services",
        "location": "Singapore",
        "contact_name": "David Chong",
        "contact_role": "Managing Director",
        "contact_email": "david.chong@portcullis.co",
        "pain_points": [
            "Manual portfolio reporting compiled in Excel for each client every quarter",
            "Email-based client communication with no CRM automation",
            "Manual document handling for legal/compliance/KYC",
            "Ad-hoc market research and report drafting by staff",
            "No structured lead/prospect tracking for new client intake",
        ],
        "solution_title": "AI Back-Office Suite for Trust and Family Offices",
        "solution_description": "Automates the manual, repetitive work that eats up your team's time: portfolio reporting, client emails, compliance document review, and prospect tracking. Built for trust and family office workflows where accuracy and confidentiality matter.",
        "hook": "Your team rebuilds the same portfolio report in Excel every quarter for every client — we can cut that to minutes.",
        "estimated_value": "SGD 18,000-28,000 setup + SGD 1,500-2,500/mo",
        "deliverables": [
            "Automated portfolio summary generator from custodian/broker statements",
            "AI-drafted client update emails and quarterly commentary",
            "Document intake pipeline for KYC/compliance files",
            "Lightweight CRM/lead tracker for new client intake",
            "Market/news summarization tool for client-facing commentary",
        ],
        "hunger_score": 7,
    },
    {
        "company_name": "Vermeer Capital Management",
        "sector": "wealth management (boutique)",
        "location": "London, UK",
        "contact_name": "Managing Partner",
        "contact_role": "Managing Partner / Principal",
        "contact_email": "info@vermeercap.com",
        "pain_points": [
            "Manual portfolio performance reports built in Excel each quarter",
            "Advisor time wasted writing bespoke client update emails",
            "Compliance documentation reviewed line-by-line manually",
            "Client onboarding via paper forms or email chains",
            "Market research and asset summaries compiled manually",
        ],
        "solution_title": "WealthOps AI — Automated Client Intelligence Suite",
        "solution_description": "Claude-powered back-office layer that turns existing portfolio data into polished quarterly reports, personalised client emails, and flagged compliance docs — automatically.",
        "hook": "Your advisors are spending two weeks a quarter rebuilding the same Excel reports — we can cut that to two hours.",
        "estimated_value": "£14,000-20,000 setup + £1,400/mo",
        "deliverables": [
            "Quarterly portfolio report generator → branded PDF from holdings/performance data",
            "Client email drafting tool from portfolio movements and market events",
            "Compliance document screener — flags FCA/KYC gaps with line references",
            "Digital onboarding intake — replaces paper chains, extracts into CRM",
            "Weekly internal research digest by asset class",
        ],
        "hunger_score": 6,
    },
]


def run():
    print(f"\n{'═'*60}")
    print(f"TRACK B OUTREACH GENERATION — {len(COMPANIES)} companies")
    print(f"{'═'*60}\n")

    results = []
    for i, c in enumerate(COMPANIES, 1):
        print(f"[{i}/{len(COMPANIES)}] {c['company_name']} ({c['location']})")
        try:
            result = outreach_agent.generate_track_b_outreach(**c)
            results.append(result)
            print(f"  Subject: {result['subject']}")
            print(f"  To: {c['contact_name']} <{c['contact_email']}>")
            print()
        except Exception as e:
            print(f"  ERROR: {e}")
            print()

    print(f"{'═'*60}")
    print(f"Done — {len(results)}/{len(COMPANIES)} generated")
    print(f"Saved → agents/output/emails/outreach_trackb_*.json")
    print(f"{'═'*60}\n")

    # Print all outreach
    for r in results:
        print(f"\n{'─'*60}")
        print(f"TO:      {r['contact']} <{r['to']}>")
        print(f"COMPANY: {r['company']} [{r['sector']}]")
        print(f"{'─'*60}")
        print(f"SUBJECT: {r['subject']}\n")
        print(r["email"])
        print(f"\n--- LINKEDIN ({len(r['linkedin_message'].split())} words) ---")
        print(r["linkedin_message"])
        print(f"\n--- FOLLOW-UP 1 (day 5) ---")
        print(r["follow_up_1"])
        print(f"\n--- FOLLOW-UP 2 (day 12) ---")
        print(r["follow_up_2"])

    return results


if __name__ == "__main__":
    run()
