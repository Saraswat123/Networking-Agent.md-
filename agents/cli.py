#!/usr/bin/env python3
"""
Networking Agent CLI — Phase 2 agents
Usage:
  python cli.py cv      --jd path/to/jd.txt --company "Stripe" --role "Backend Engineer"
  python cli.py email   --company "Stripe" --contact "John Doe" --role "CTO" --email "john@stripe.com" --signal "just raised Series B" --stack "Rust,Go,Kubernetes"
  python cli.py analyze --jd path/to/jd.txt
"""

import json
import os
import sys
from pathlib import Path

# Auto-load .env from repo root
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

import classifier_agent
import companies_house
import cv_agent
import email_sender
import obsidian_sync
import orchestrator
import outreach_agent
import prospect_bridge
import research_agent

app = typer.Typer(help="Networking Agent — CV + Outreach automation")
console = Console()


def require_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY not set")
        raise typer.Exit(1)


@app.command()
def cv(
    jd: Path = typer.Option(..., help="Path to job description text file"),
    company: str = typer.Option(..., help="Company name e.g. 'Stripe'"),
    role: str = typer.Option(..., help="Role title e.g. 'Backend Engineer'"),
):
    """Generate tailored CV for a job posting."""
    require_api_key()
    if not jd.exists():
        console.print(f"[red]File not found:[/red] {jd}")
        raise typer.Exit(1)

    jd_text = jd.read_text()
    console.print(f"\n[bold]Generating CV for:[/bold] {role} @ {company}\n")
    cv_agent.generate_cv(jd_text, company, role)


@app.command()
def analyze(
    jd: Path = typer.Option(..., help="Path to job description text file"),
):
    """Parse a job description and show structured signal data."""
    require_api_key()
    if not jd.exists():
        console.print(f"[red]File not found:[/red] {jd}")
        raise typer.Exit(1)

    jd_text = jd.read_text()
    console.print("\n[bold]Analyzing JD...[/bold]\n")
    result = cv_agent.analyze_jd(jd_text)
    console.print_json(json.dumps(result, indent=2))


@app.command()
def email(
    company: str = typer.Option(..., help="Company name"),
    contact: str = typer.Option(..., help="Contact full name"),
    role: str = typer.Option(..., help="Contact's role/title"),
    to: str = typer.Option(..., help="Contact email address"),
    signal: str = typer.Option(..., help="Specific signal e.g. 'just raised Series A' or 'posted Rust engineer job'"),
    stack: str = typer.Option("", help="Comma-separated tech stack e.g. 'Rust,Go,Kubernetes'"),
    jd: Path = typer.Option(None, help="Optional: path to JD file for role-specific tailoring"),
):
    """Generate cold email + LinkedIn message + follow-up sequence."""
    require_api_key()

    tech_list = [t.strip() for t in stack.split(",") if t.strip()] if stack else []
    jd_text = jd.read_text() if jd and jd.exists() else ""
    jd_analysis = cv_agent.analyze_jd(jd_text) if jd_text else None

    console.print(f"\n[bold]Generating outreach for:[/bold] {contact} @ {company}\n")
    result = outreach_agent.generate_outreach(
        company_name=company,
        contact_name=contact,
        contact_role=role,
        contact_email=to,
        tech_stack=tech_list,
        signal=signal,
        job_description=jd_text,
        jd_analysis=jd_analysis,
    )
    outreach_agent.print_outreach(result)


@app.command()
def pipeline(
    prospects_file: Path = typer.Option(..., help="JSON file with list of prospects"),
    signal_key: str = typer.Option("signal", help="Field name for signal in each prospect"),
):
    """
    Batch generate outreach for multiple prospects from a JSON file.

    Prospects file format:
    [
      {
        "company": "Stripe",
        "contact": "John Doe",
        "role": "CTO",
        "email": "john@stripe.com",
        "signal": "just raised Series B",
        "stack": ["Rust", "Go"],
        "jd_path": "optional/path/to/jd.txt"
      }
    ]
    """
    require_api_key()
    if not prospects_file.exists():
        console.print(f"[red]File not found:[/red] {prospects_file}")
        raise typer.Exit(1)

    prospects = json.loads(prospects_file.read_text())
    console.print(f"\n[bold]Processing {len(prospects)} prospects...[/bold]\n")

    for i, p in enumerate(prospects, 1):
        console.rule(f"[bold]{i}/{len(prospects)} — {p.get('company', '?')}[/bold]")
        jd_text = ""
        jd_analysis = None
        jd_path = p.get("jd_path")
        if jd_path and Path(jd_path).exists():
            jd_text = Path(jd_path).read_text()
            jd_analysis = cv_agent.analyze_jd(jd_text)

        result = outreach_agent.generate_outreach(
            company_name=p["company"],
            contact_name=p["contact"],
            contact_role=p.get("role", ""),
            contact_email=p["email"],
            tech_stack=p.get("stack", []),
            signal=p.get(signal_key, ""),
            job_description=jd_text,
            jd_analysis=jd_analysis,
        )
        outreach_agent.print_outreach(result)

    console.print(f"\n[green]Done.[/green] {len(prospects)} outreach packages saved to agents/output/emails/")


@app.command()
def research(
    status: str = typer.Option("new", help="Prospect status to research: new | researched"),
    limit: int = typer.Option(10, help="Max companies to research"),
    concurrency: int = typer.Option(3, help="Parallel Claude agents (3 agents × N companies)"),
    min_score: int = typer.Option(5, help="Skip companies scoring below this (0-10)"),
):
    """
    Multi-agent company research: job scanner + collaboration scanner + shortlist scorer.

    Runs 3 Claude agents in parallel per company. Outputs:
      PATH A: open position found → apply + outreach
      PATH B: GitHub entry point → contribute first → then outreach
      PATH C: no opening → pure cold outreach

    Results saved to agents/output/research/<company>.json
    """
    require_api_key()

    import sqlite3
    db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
    if not db_path.exists():
        console.print(f"[red]DB not found:[/red] {db_path}")
        raise typer.Exit(1)

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, name, github, email, company, role, location, notes, source FROM prospects WHERE outreach_status = ? ORDER BY created_at DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    db.close()

    prospects = [dict(r) for r in rows]
    console.print(f"\n[bold]Researching {len(prospects)} companies[/bold] — 3 parallel agents each\n")

    results = research_agent.research_batch(prospects, concurrency=concurrency)

    # Filter by min_score
    results = [r for r in results if r.get("shortlist", {}).get("shortlist_score", 0) >= min_score or r["pathway"].get("pathway") == research_agent.PATH_A]

    research_agent.print_research_report(results)


@app.command()
def run(
    query: str = typer.Option(..., help="Search query e.g. 'CTO', 'Rust engineer', 'AI infrastructure'"),
    location: str = typer.Option("", help="Location filter e.g. 'Singapore', 'San Francisco', '' for global"),
    mode: str = typer.Option("both", help="Discovery source: github | yc | both"),
    limit: int = typer.Option(10, help="Max prospects to discover per source"),
    no_bridge: bool = typer.Option(False, "--no-bridge", help="Skip outreach generation, just discover"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Discover + preview without generating outreach"),
):
    """
    Full pipeline: discover prospects → save to DB → enrich → generate outreach.

    Examples:
      python cli.py run --query "CTO" --location "Singapore" --mode yc
      python cli.py run --query "Rust engineer" --location "" --mode github --limit 5
      python cli.py run --query "AI infrastructure" --mode both --dry-run
    """
    require_api_key()
    console.print(f"\n[bold]Pipeline:[/bold] {mode.upper()} discovery → enrich → outreach")
    console.print(f"Query: '{query}'  Location: '{location or 'global'}'  Limit: {limit}/source\n")
    orchestrator.run(
        mode=mode,
        query=query,
        location=location,
        limit=limit,
        run_bridge=not no_bridge,
        dry_run=dry_run,
    )


@app.command()
def dashboard():
    """Show pipeline status — prospect counts by stage."""
    import sqlite3
    from pathlib import Path

    db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
    if not db_path.exists():
        console.print(f"[red]DB not found:[/red] {db_path}")
        raise typer.Exit(1)

    db = sqlite3.connect(str(db_path))
    rows = db.execute(
        "SELECT outreach_status, COUNT(*) as n FROM prospects GROUP BY outreach_status ORDER BY n DESC"
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    recent = db.execute(
        "SELECT name, company, outreach_status, created_at FROM prospects ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    db.close()

    console.print("\n[bold]── Pipeline Dashboard ──[/bold]\n")
    console.print(f"Total prospects: [bold]{total}[/bold]\n")

    status_colors = {
        "new": "white", "researched": "yellow", "github_engaged": "cyan",
        "x_engaged": "blue", "emailed": "green", "replied": "bright_green",
        "meeting_scheduled": "bright_magenta",
    }
    for status, count in rows:
        bar = "█" * min(count, 40)
        color = status_colors.get(status, "white")
        console.print(f"  [{color}]{status:<20}[/{color}] {bar} {count}")

    console.print("\n[bold]Recent prospects:[/bold]")
    for name, company, status, created in recent:
        console.print(f"  {created[:10]}  {(name or '?'):<25} @ {(company or '?'):<20}  [{status}]")
    console.print()


@app.command()
def bridge(
    status: str = typer.Option("new", help="Prospect status to process: new | researched"),
    limit: int = typer.Option(20, help="Max prospects to process in one run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without generating outreach or writing to DB"),
    skip_enrichment: bool = typer.Option(False, "--skip-enrichment", help="Skip Hunter.io + WebReveal calls"),
):
    """
    Read prospects from Rust SQLite DB → enrich → generate outreach automatically.

    Requires: ANTHROPIC_API_KEY, NETWORKING_DB (or default ~/networking-agent.db)
    Optional: HUNTER_API_KEY for email discovery
    """
    require_api_key()
    if dry_run:
        console.print("\n[yellow]DRY RUN — no DB writes, no API calls for outreach[/yellow]\n")
    prospect_bridge.run_bridge(
        status_filter=status,
        limit=limit,
        dry_run=dry_run,
        skip_enrichment=skip_enrichment,
    )


@app.command()
def classify(
    mode: str = typer.Option("both", help="Source: db | manual | both"),
    limit: int = typer.Option(20, help="Max prospects to classify"),
    concurrency: int = typer.Option(3, help="Parallel Claude agent sets per company"),
    status: str = typer.Option("new", help="DB status filter: new | researched"),
    company: str = typer.Option("", help="Classify single company by name (manual mode)"),
    website: str = typer.Option("", help="Website for single company (manual mode)"),
    location: str = typer.Option("", help="Location for single company (manual mode)"),
    sector: str = typer.Option("", help="Sector hint for single company (manual mode)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without writing to Obsidian"),
):
    """
    Classifier Agent — identify non-technical companies (wealth families, family
    offices, law firms, logistics, real estate) in US/UK/Europe wanting AI automation.

    Two-track output:
      TRACK A: Technical company → job application pipeline
      TRACK B: Non-technical, AI-hungry → proposal + implementation outreach

    Results written to Obsidian vault:
      TrackA_Jobs/<Company>.md
      TrackB_Proposals/<Company>.md

    Examples:
      python cli.py classify --mode db --limit 20
      python cli.py classify --mode manual --company "Vermeer Capital" --website "vermeercap.com" --location "London, UK" --sector "wealth management"
    """
    require_api_key()

    prospects = []

    # Manual single company
    if mode in ("manual",) or company:
        if not company:
            console.print("[red]--company required for manual mode[/red]")
            raise typer.Exit(1)
        notes = ""
        if website:
            notes = f"website:{website}"
        if sector:
            notes += f" sector:{sector}"
        prospects = [{
            "company": company,
            "name": company,
            "location": location,
            "notes": notes,
            "source": "manual",
        }]

    # Load from DB
    if mode in ("db", "both") and not (mode == "manual" or company):
        import sqlite3
        db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
        if not db_path.exists():
            console.print(f"[yellow]DB not found:[/yellow] {db_path}")
        else:
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id, name, github, email, company, role, location, notes, source FROM prospects WHERE outreach_status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
            db.close()
            prospects.extend([dict(r) for r in rows])

    if not prospects:
        console.print("[yellow]No prospects to classify.[/yellow]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Classifier Agent:[/bold] {len(prospects)} companies — 3 agents each")
    console.print(f"Tracks: A (job applications) + B (AI proposals → Obsidian)\n")

    if dry_run:
        console.print("[yellow]DRY RUN — no Obsidian writes[/yellow]\n")
        for p in prospects:
            console.print(f"  Would classify: {p.get('company') or p.get('name')} ({p.get('location', '?')})")
        raise typer.Exit(0)

    results = classifier_agent.classify_batch(prospects, concurrency=concurrency)
    classifier_agent.print_classifier_report(results)


@app.command()
def send(
    company: str = typer.Option(..., help="Company name (must have TrackB Obsidian note)"),
    to: str = typer.Option(..., help="Recipient email address"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview email without sending"),
):
    """
    Send Track B proposal email from Obsidian draft via Gmail SMTP.

    Reads subject + body from TrackB_Proposals/<Company>.md in Obsidian.
    Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD in env.

    Examples:
      python cli.py send --company "Vermeer Capital" --to "ceo@vermeercap.com" --dry-run
      python cli.py send --company "Vermeer Capital" --to "ceo@vermeercap.com"
    """
    if not dry_run:
        if not os.environ.get("GMAIL_ADDRESS") or not os.environ.get("GMAIL_APP_PASSWORD"):
            console.print("[red]Set GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env[/red]")
            console.print("App password: myaccount.google.com/apppasswords")
            raise typer.Exit(1)

    result = email_sender.send_track_b_email(company, to, dry_run=dry_run)
    if result["status"] == "sent":
        email_sender.log_to_db(company, to, "emailed")
        console.print(f"\n[green]Sent.[/green] Status updated to 'emailed' in DB.")
    elif result["status"] == "dry_run":
        console.print("\n[yellow]Dry run complete. Add --no-dry-run to send.[/yellow]")


@app.command()
def lookup(
    company: str = typer.Option(..., help="Company name to look up"),
    country: str = typer.Option("uk", help="Country code: uk | us | uae | sg | au | de | nl | fr | sa | in"),
):
    """
    Look up company background from public registries (global).

    UK:        Companies House API (free) — full profile, incorporation date, active directors
    US:        SEC EDGAR search link
    UAE/Dubai: DED company search link
    Singapore: ACRA BizFile link
    Australia: ASIC search link
    Germany:   Handelsregister link
    + France, Netherlands, Saudi Arabia, India

    Examples:
      python cli.py lookup --company "Vermeer Capital Management" --country uk
      python cli.py lookup --company "Gulf Family Office" --country uae
      python cli.py lookup --company "Apex Holdings" --country sg
    """
    console.print(f"\n[bold]Looking up:[/bold] {company} ({country.upper()})\n")

    result = companies_house.research_company_global(company, country)

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    # Non-UK: show registry link
    if "registry_url" in result:
        console.print(f"[yellow]{result['note']}[/yellow]")
        console.print(f"  Registry: {result['registry_url']}")
        raise typer.Exit(0)

    # UK: full data
    co = result["company"]
    profile = result.get("profile", {})
    dms = result.get("decision_makers", [])

    console.print(f"[bold]{co['name']}[/bold]")
    console.print(f"  Status:       {co.get('status')}")
    console.print(f"  Incorporated: {co.get('incorporated')} ({result.get('incorporated_years', '?')} years ago)")
    console.print(f"  Type:         {co.get('type')}")
    console.print(f"  SIC codes:    {', '.join(co.get('sic_codes', []))}")
    console.print(f"  Address:      {co.get('address', '')} {co.get('postcode', '')}")
    console.print(f"  CH link:      {co.get('ch_url', '')}")

    if dms:
        console.print(f"\n[bold]Active Directors/Officers ({len(dms)}):[/bold]")
        for d in dms:
            console.print(f"  {d['name']:<35} {d['role']}")

    if profile.get("last_accounts"):
        console.print(f"\n  Last accounts: {profile['last_accounts']}")


if __name__ == "__main__":
    app()
