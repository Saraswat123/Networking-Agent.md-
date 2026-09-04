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

import background_agent
import classifier_agent
import companies_house
import content_agent
import cv_agent
import email_sender
import gmail_oauth
import lead_sourcer
import linkedin_agent
import obsidian_sync
import orchestrator
import outreach_agent
import prospect_bridge
import research_agent
import track_a_custom_build
import track_b_sourcer
import track_c_social
import x_agent

app = typer.Typer(help="Networking Agent — CV + Outreach automation")
console = Console()


def require_api_key():
    pass  # Claude Code CLI handles auth — no API key needed


@app.command()
def cv(
    jd: Path = typer.Option(..., help="Path to job description text file"),
    company: str = typer.Option(..., help="Company name e.g. 'Stripe'"),
    role: str = typer.Option(..., help="Role title e.g. 'Backend Engineer'"),
    angle: str = typer.Option("", help="Force CV angle: rust_mcp | data_engineering | protocol_engineer (auto-detect if omitted)"),
):
    """
    Generate tailored CV for a job posting.

    Auto-detects role type from JD and picks the right CV angle:
      rust_mcp          → Rust MCP/Agent Infrastructure Engineer
      data_engineering  → AI & Data Engineer (Python, PostgreSQL, Power BI)
      protocol_engineer → Protocol & Systems Engineer (distributed, async Rust)

    Examples:
      python cli.py cv --jd stripe_jd.txt --company "Stripe" --role "Backend Engineer"
      python cli.py cv --jd cloudflare_jd.txt --company "Cloudflare" --role "Rust Engineer" --angle rust_mcp
    """
    require_api_key()
    if not jd.exists():
        console.print(f"[red]File not found:[/red] {jd}")
        raise typer.Exit(1)

    jd_text = jd.read_text()
    console.print(f"\n[bold]Generating CV for:[/bold] {role} @ {company}\n")
    cv_agent.generate_cv(jd_text, company, role, angle_override=angle or None)


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
def source(
    sources: str = typer.Option("uk_ch,fca,ddg", help="Comma-separated sources: uk_ch | fca | ddg | gmaps"),
    sectors: str = typer.Option("", help="Comma-separated sectors e.g. 'family office,wealth management'"),
    cities: str = typer.Option("", help="Comma-separated cities e.g. 'London,Dubai,Singapore'"),
    limit: int = typer.Option(50, help="Max leads to source per run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without saving to DB"),
):
    """
    Source Track B leads — find non-technical companies (wealth, legal, property) to classify.

    Sources:
      uk_ch   UK Companies House (needs UK_CH_API_KEY — free)
      fca     FCA Financial Services Register (free, no key)
      ddg     DuckDuckGo sector+city search (free, no key)
      gmaps   Google Maps Places API (needs GOOGLE_MAPS_API_KEY)

    Saves to SQLite → then run `classify` to score + generate proposals.

    Examples:
      python cli.py source --sources uk_ch,fca --limit 100
      python cli.py source --sources ddg --cities "London,Dubai,Zurich" --sectors "family office,law firm"
      python cli.py source --sources uk_ch,fca,ddg --dry-run
    """
    src_list = [s.strip() for s in sources.split(",") if s.strip()]
    sec_list = [s.strip() for s in sectors.split(",") if s.strip()] or None
    city_list = [s.strip() for s in cities.split(",") if s.strip()] or None

    console.print(f"\n[bold]Lead Sourcer:[/bold] {', '.join(src_list)}")
    if sec_list:
        console.print(f"  Sectors: {', '.join(sec_list)}")
    if city_list:
        console.print(f"  Cities:  {', '.join(city_list)}")
    console.print()

    leads = lead_sourcer.source_leads(
        sources=src_list,
        sectors=sec_list,
        cities=city_list,
        limit=limit,
        dry_run=dry_run,
    )
    console.print(f"\n[green]Done.[/green] {len(leads)} leads. Run [bold]classify[/bold] to score them.")


@app.command()
def background(
    company: str = typer.Option("", help="Research single company by name"),
    status: str = typer.Option("new", help="DB status to pull from: new | researched"),
    limit: int = typer.Option(10, help="Max companies to research"),
    concurrency: int = typer.Option(3, help="Parallel Claude agents"),
):
    """
    Background Agent — deep company research before proposal generation.

    Pulls news, website text, UK Companies House data → Claude synthesizes
    into structured profile: founding year, key people, revenue estimate,
    pain signals, AI readiness, proposal hook.

    Output saved to agents/output/background/<company>.json

    Examples:
      python cli.py background --company "Vermeer Capital Management"
      python cli.py background --status new --limit 10
    """
    require_api_key()

    prospects = []
    if company:
        prospects = [{"company": company, "name": company, "location": "", "notes": "", "source": "manual"}]
    else:
        import sqlite3
        db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
        if not db_path.exists():
            console.print(f"[red]DB not found:[/red] {db_path}")
            raise typer.Exit(1)
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, name, company, location, notes, source FROM prospects WHERE outreach_status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        db.close()
        prospects = [dict(r) for r in rows]

    if not prospects:
        console.print("[yellow]No prospects found.[/yellow]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Background Agent:[/bold] researching {len(prospects)} companies\n")
    results = background_agent.research_batch(prospects, concurrency=concurrency)
    background_agent.print_background_report(results)
    console.print(f"\n[green]Saved[/green] → agents/output/background/")


@app.command(name="source-trackb")
def source_trackb(
    sectors: str = typer.Option("wealth,legal,real_estate", "--sectors",
                                help="Comma list: wealth | family_office | real_estate | legal | accounting | consulting | logistics | recruitment"),
    countries: str = typer.Option("UK", "--countries",
                                  help="Comma list: UK | UAE | Singapore | Switzerland | etc, or 'worldwide' "
                                       "to expand to ~30 major hubs across every region"),
    limit: int = typer.Option(15, "--limit", help="Max companies per sector×country combo"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without saving to DB"),
):
    """
    Bulk-discover Track B companies (non-technical, AI-hungry) — feeds classify --mode db.

    UK: Companies House Advanced Search by SIC code (needs UK_CH_API_KEY in .env,
        free key at find-and-update.company-information.service.gov.uk/get-started).
        Falls back to DDGS if no key set.
    Other countries: DDGS search, no key needed.
    --countries worldwide: expands to track_b_sourcer.WORLDWIDE_COUNTRIES (~30 countries
        across US/UK/EU/Gulf/APAC) for max-scale sourcing of the same sectors.

    Every result gets a website resolved (DDGS lookup) so classify_agent can
    run tech-stack + AI-hunger checks on it.

    Examples:
      python cli.py source-trackb --sectors wealth,legal --countries UK --limit 20
      python cli.py source-trackb --sectors family_office --countries "UAE,Singapore,Switzerland" --limit 10
      python cli.py source-trackb --sectors wealth,legal,real_estate --countries worldwide --limit 10
      python cli.py source-trackb --dry-run --sectors logistics --countries UK
    """
    sector_list   = [s.strip() for s in sectors.split(",") if s.strip()]
    country_list  = [c.strip() for c in countries.split(",") if c.strip()]

    console.print(f"\n[bold]Track B Sourcer[/bold]")
    console.print(f"  Sectors:   {sector_list}")
    console.print(f"  Countries: {country_list}")
    console.print(f"  Limit:     {limit} per combo\n")

    summary = track_b_sourcer.source_track_b(
        sector_list, country_list, limit_per_combo=limit, save=not dry_run,
    )

    console.print(f"\n[green]Found:[/green] {summary['found']}  "
                  f"[green]Inserted:[/green] {summary['inserted']}  "
                  f"[dim]Dupes skipped:[/dim] {summary['skipped_duplicate']}\n")

    if dry_run:
        for r in summary["results"][:25]:
            console.print(f"  {r['company']:<35} [{r['sector']}] {r.get('location','?')}")
    elif summary["inserted"]:
        console.print(f"Next: [bold]python cli.py classify --mode db --limit {summary['inserted']}[/bold]")


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


@app.command(name="x-research")
def x_research(
    company: str = typer.Option(..., help="Company name e.g. 'Acme Capital'"),
    role: str = typer.Option("CEO/CTO/Founder", help="Target role"),
):
    """
    Generate Grok prompt to find prospect tweet URL (Free tier workflow).

    X Free tier = write-only. Use Grok at x.com/grok to find tweet URL,
    then run x-reply with that URL.

    Workflow:
      1. python cli.py x-research --company "Acme Capital"
      2. Paste the prompt into Grok (x.com/grok)
      3. Grok gives you tweet URL
      4. python cli.py x-reply --tweet-url <url> --message "..." --prospect "Acme Capital"
    """
    prompt = x_agent.grok_research_prompt(company, role)
    console.print(f"\n[bold]── Grok Research Prompt ──[/bold]\n")
    console.print(Panel(prompt, title=f"Paste into x.com/grok", border_style="yellow"))
    console.print("\n[dim]After Grok replies → copy tweet URL → run x-reply[/dim]")


@app.command(name="x-reply")
def x_reply(
    tweet_url: str = typer.Option(..., "--tweet-url", help="Tweet URL e.g. https://x.com/user/status/123"),
    message: str = typer.Option(..., help="Reply text (max 280 chars)"),
    prospect: str = typer.Option("", help="Prospect name for logging"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Reply to tweet for warm-up outreach (Free tier — works with $0 X API).

    Best practice: genuine technical insight first, no pitch.
    Wait 2-3 days → send email referencing 'saw your tweet about X'.

    Workflow:
      1. x-research --company "Acme" → get Grok prompt
      2. Grok gives tweet URL
      3. x-reply --tweet-url <url> --message "..." --prospect "Acme"
      4. Wait 2-3 days → email command

    Requires: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in .env
    """
    result = x_agent.post_reply(tweet_url, message, prospect=prospect, dry_run=dry_run)
    if result and result.get("status") == "replied":
        console.print(f"[green]Replied → {result.get('reply_url')}[/green]")
        console.print(f"[dim]Next: wait 2-3 days, then run email command for {prospect or 'prospect'}[/dim]")
    elif result and result.get("status") == "dry_run":
        console.print("[yellow]Dry run complete.[/yellow]")
    elif result and result.get("status") == "limit_reached":
        console.print("[red]Daily limit reached (15/day).[/red]")

    stats = x_agent.get_reply_stats()
    console.print(f"\nToday: {stats['replies_sent']} replies, {stats['replies_remaining']} remaining")


@app.command(name="x-post")
def x_post(
    message: str = typer.Option(..., help="Tweet text (max 280 chars)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Post original tweet — thought leadership, not outreach.

    Use for: Rust/AI insights, open source work, industry takes.
    Builds credibility before prospect sees your reply.

    Requires: X_* keys in .env
    """
    result = x_agent.post_tweet(message, dry_run=dry_run)
    if result.get("status") == "posted":
        console.print(f"[green]Posted → {result.get('url')}[/green]")
    elif result.get("status") == "dry_run":
        console.print("[yellow]Dry run complete.[/yellow]")


@app.command(name="li-connect")
def li_connect(
    profile_url: str = typer.Option(..., help="LinkedIn profile URL"),
    note: str = typer.Option("", help="Connection note (max 300 chars)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Send LinkedIn connection request with optional note.

    Limit: 20 connections/day (enforced — LinkedIn bans over-automation).
    Use for Track A warm-up before sending CV/email.

    Requires: LINKEDIN_EMAIL, LINKEDIN_PASSWORD in .env
    Setup: pip install playwright && playwright install chromium
    """
    import asyncio
    result = asyncio.run(linkedin_agent.send_connection_request(profile_url, note, dry_run=dry_run))
    status = result.get("status") if result else "error"
    if status == "sent":
        console.print(f"[green]Connection request sent.[/green]")
    elif status == "dry_run":
        console.print("[yellow]Dry run complete.[/yellow]")
    elif status == "limit_reached":
        console.print("[red]Daily limit reached (20/day). Try tomorrow.[/red]")
    else:
        console.print(f"[yellow]{status}[/yellow]")


@app.command(name="li-message")
def li_message(
    profile_url: str = typer.Option(..., help="LinkedIn profile URL"),
    message: str = typer.Option(..., help="Message text"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Send LinkedIn message to existing connection.

    Limit: 5 messages/day (enforced).
    Send AFTER connection accepted (2-3 day wait).

    Requires: LINKEDIN_EMAIL, LINKEDIN_PASSWORD in .env
    Setup: pip install playwright && playwright install chromium
    """
    import asyncio
    result = asyncio.run(linkedin_agent.send_message(profile_url, message, dry_run=dry_run))
    status = result.get("status") if result else "error"
    if status == "sent":
        console.print(f"[green]Message sent.[/green]")
    elif status == "dry_run":
        console.print("[yellow]Dry run complete.[/yellow]")
    elif status == "limit_reached":
        console.print("[red]Daily limit reached (5 messages/day). Try tomorrow.[/red]")

    stats = linkedin_agent.get_sent_stats()
    console.print(f"\nToday: {stats['connections_sent']} connects, {stats['messages_sent']} messages")


@app.command()
def replies():
    """
    Check which outreach emails got replies (Gmail OAuth required).

    Cross-references sent_emails.jsonl with Gmail inbox.
    Shows which companies have replied — move them to 'replied' status.
    """
    try:
        results = gmail_oauth.check_replies()
    except Exception as e:
        console.print(f"[red]Gmail OAuth not set up:[/red] {e}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No sent emails logged yet.[/yellow]")
        raise typer.Exit(0)

    replied = [r for r in results if r["replied"]]
    waiting = [r for r in results if not r["replied"]]

    console.print(f"\n[bold]── Reply Tracker ──[/bold]\n")
    console.print(f"[green]Replied ({len(replied)}):[/green]")
    for r in replied:
        console.print(f"  ✓ {r['to']:<35} {r['subject'][:40]}")

    console.print(f"\n[yellow]No reply yet ({len(waiting)}):[/yellow]")
    for r in waiting:
        sent = r.get("sent_at", "")[:10]
        console.print(f"  · {r['to']:<35} sent {sent}")


@app.command()
def grow(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending"),
    linkedin_only: bool = typer.Option(False, "--linkedin-only"),
    x_only: bool = typer.Option(False, "--x-only"),
    stats: bool = typer.Option(False, "--stats", help="Show stats only"),
    li_limit: int = typer.Option(35, "--li-limit", help="LinkedIn connections limit"),
    follow_limit: int = typer.Option(150, "--follow-limit", help="LinkedIn follows limit"),
    x_limit: int = typer.Option(15, "--x-limit", help="X replies limit"),
):
    """
    Daily growth: 35 connects + 150 follows + 15 X replies = 200 touches/day → 4000+ in 2 months.

    Examples:
      python cli.py grow --dry-run
      python cli.py grow --linkedin-only --li-limit 10 --follow-limit 30
      python cli.py grow --x-only --x-limit 5
      python cli.py grow --stats
    """
    import asyncio
    import daily_growth
    import sys

    sys.argv = ["daily_growth"]

    asyncio.run(daily_growth.main_args(
        dry_run=dry_run,
        linkedin_only=linkedin_only,
        x_only=x_only,
        stats_only=stats,
        li_limit=li_limit,
        follow_limit=follow_limit,
        x_limit=x_limit,
    ))


@app.command()
def jobs(
    search: str = typer.Option("AI automation python LLM agent", "--search", help="Space-separated keywords. Presets: 'founders-office' | 'protocol' | 'genai'"),
    sources: str = typer.Option("yc,hn,remoteok", "--sources", help="yc | hn | remoteok | web3career | wellfound | linkedin | crunchbase"),
    max_age: int = typer.Option(7, "--max-age", help="Max posting age in days"),
    max_team: int = typer.Option(50, "--max-team", help="Max team size"),
    score_min: int = typer.Option(7, "--score-min", help="Min score to show (0-20)"),
):
    """
    Track A job search: multi-source → score → rank. All 5 gaps fixed.

    Sources:
      yc       YC API — W23/S24/W24/S25 batches, team_size filter
      hn       HN Who Is Hiring (current month) — freshest jobs on internet
      remoteok RemoteOK API — tagged search

    Scoring (0-20):
      +3 YC batch    +3 team≤15   +2 funded    +2 tech match
      +2 global remote   +2 posted<48h   +1 salary listed
      -2 US-only   -2 team>100   -3 enterprise   -3 5+yrs required

    Examples:
      python cli.py jobs --search "rust python" --max-age 3 --score-min 8
      python cli.py jobs --sources hn --search "ai agent" --max-team 20
    """
    import job_pipeline

    # Presets
    presets = {
        "founders-office": ["founders office", "special projects", "founding engineer", "AI ops", "chief of staff AI"],
        "protocol":        ["rust protocol", "distributed systems", "p2p", "ethereum", "BFT consensus"],
        "genai":           ["gen AI engineer", "LLM engineer", "Claude engineer", "AI automation", "agentic workflow"],
    }
    kws = presets.get(search.strip(), search.split())
    src_list = [s.strip() for s in sources.split(",") if s.strip()]

    console.print(f"\n[bold]Track A Job Search[/bold]")
    console.print(f"  Keywords: {kws}")
    console.print(f"  Sources:  {src_list}")
    console.print(f"  Filters:  posted ≤ {max_age}d | team ≤ {max_team} | score ≥ {score_min}/20\n")

    results = job_pipeline.search_and_score(
        keywords=kws,
        sources=src_list,
        max_age_days=max_age,
        max_team=max_team,
        score_min=score_min,
    )

    if not results:
        console.print("[yellow]No jobs matched. Try --score-min 5 or broader --search.[/yellow]")
        return

    console.print(f"\n[green]Found {len(results)} jobs[/green]\n")
    for j in results:
        ts = f"team:{j['team_size']}" if j.get("team_size") else "team:?"
        age = f"{j['posted_days_ago']}d ago" if j.get("posted_days_ago") is not None else "age:?"
        sal = f"${j['salary_min']//1000}K-${j['salary_max']//1000}K" if j.get("salary_max") else "salary:?"
        batch = f" [{j['batch']}]" if j.get("batch") else ""
        console.print(f"  [bold][{j['score']:2d}/20][/bold] {j['company']}{batch} — {j['title'][:50]}")
        console.print(f"         {j['source'].upper()} | {ts} | {age} | {sal}")
        console.print(f"         {j['url'][:75]}")
        if j.get("one_liner"):
            console.print(f"         [dim]\"{j['one_liner'][:80]}\"[/dim]")
        console.print()


@app.command(name="jobs-hunt")
def jobs_hunt(
    max_team: int = typer.Option(30, "--max-team", help="Max team size (default 30 = tiny team signal)"),
    batches: str = typer.Option("W25,S24,W24,S23,W23", "--batches", help="YC batches to sweep"),
    score_min: int = typer.Option(8, "--score-min"),
    no_careers: bool = typer.Option(False, "--no-careers", help="Skip careers page check (faster)"),
    limit: int = typer.Option(40, "--limit", help="Max results to show"),
):
    """
    Aggressive hunt: heavy investment + tiny team → confirmed open roles.

    Sweeps YC API with 20 keywords, deduplicates, checks each company's
    /careers page for real job listings. Best signal = funded + ≤30 people.

    Examples:
      python cli.py jobs-hunt --max-team 15 --score-min 9
      python cli.py jobs-hunt --batches W25,S24 --no-careers
    """
    import job_pipeline

    batch_list = [b.strip() for b in batches.split(",") if b.strip()]

    console.print(f"\n[bold]Track A Hunt[/bold] — YC sweep + careers check")
    console.print(f"  Batches: {batch_list} | team ≤ {max_team} | score ≥ {score_min}")
    if not no_careers:
        console.print(f"  [dim]Checking careers pages — takes ~60s[/dim]\n")

    results = job_pipeline.hunt_funded_small_teams(
        max_team=max_team,
        batches=batch_list,
        check_careers=not no_careers,
        score_min=score_min,
    )

    if not results:
        console.print("[yellow]No results. Try --score-min 6 or --max-team 50.[/yellow]")
        return

    show = results[:limit]
    open_roles = [r for r in show if r["has_open_roles"]]
    no_roles   = [r for r in show if not r["has_open_roles"]]

    console.print(f"\n[green bold]── {len(open_roles)} with confirmed open roles ──[/green bold]\n")
    for r in open_roles:
        console.print(f"  [bold][{r['score']:2d}/20][/bold] [green]{r['company']}[/green] [{r['batch']}] team:{r['team_size'] or '?'}")
        console.print(f"         Roles: {', '.join(r['roles_found'][:4]) or 'see page'}")
        console.print(f"         [link]{r['url']}[/link]")
        if r.get("one_liner"):
            console.print(f"         [dim]{r['one_liner'][:90]}[/dim]")
        console.print()

    if no_roles:
        console.print(f"[yellow]── {len(no_roles)} companies (no /careers page found — cold pitch) ──[/yellow]\n")
        for r in no_roles[:20]:
            console.print(f"  [{r['score']:2d}/20] {r['company']:<25} [{r['batch']}] team:{r['team_size'] or '?'}  {r['website']}")
            if r.get("one_liner"):
                console.print(f"           [dim]{r['one_liner'][:80]}[/dim]")

    console.print(f"\n[dim]Save a JD and run: python cli.py jobs-apply --company <name> --jd agents/jds/<file>.txt[/dim]")


@app.command(name="jobs-apply")
def jobs_apply(
    company: str = typer.Option(..., help="Company name"),
    role: str = typer.Option(..., help="Role title"),
    jd: Path = typer.Option(..., help="Path to JD .txt file"),
    domain: str = typer.Option("", help="Company domain e.g. getcallback.ai"),
    angle: str = typer.Option("auto", help="CV angle: auto | protocol_engineer | data_engineering | rust_mcp"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Full apply workflow: email finder + tailored CV + Obsidian note + DB log.

    Steps:
      1. Hunter.io domain search → pattern guess fallback
      2. Generate tailored CV (picks angle from JD keywords)
      3. Write Obsidian tracking note with JD summary
      4. Update jobs DB (status=applied)

    Examples:
      python cli.py jobs-apply --company Callback --role "AI Engineer" --jd agents/jds/callback_ai_engineer.txt --domain getcallback.ai
      python cli.py jobs-apply --company Reform --role "Software Engineer" --jd agents/jds/reform_ai_engineer.txt --dry-run
    """
    import job_pipeline

    if not jd.exists():
        console.print(f"[red]JD not found:[/red] {jd}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Applying:[/bold] {role} @ {company}")
    if dry_run:
        console.print("[yellow]DRY RUN — no email, CV will be generated[/yellow]\n")

    result = job_pipeline.apply_to_job(
        company=company,
        role=role,
        jd_file=str(jd),
        domain=domain,
        angle=angle,
        dry_run=dry_run,
    )

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Email:   {result['email']} ({result['email_confidence']})")
    console.print(f"  CV:      {result['cv_file']}")
    console.print(f"  Note:    {result['obsidian_note']}")
    console.print(f"  Status:  {result['status']}")


@app.command(name="jobs-list")
def jobs_list(
    status: str = typer.Option("", "--status", help="Filter: found | applied | replied | interview | rejected"),
):
    """
    Show tracked job applications from DB.

    Examples:
      python cli.py jobs-list
      python cli.py jobs-list --status applied
    """
    import job_pipeline

    apps = job_pipeline.list_applications(status=status or None)
    if not apps:
        console.print("[yellow]No applications tracked yet. Run jobs-apply first.[/yellow]")
        return

    console.print(f"\n[bold]Job Applications ({status or 'all'}): {len(apps)}[/bold]\n")
    for a in apps:
        date_str = a.get("applied_date") or a.get("created_at", "")[:10]
        console.print(f"  [{a['score']:2d}/20] [{a['status']:10}] {a['company']:<20} — {a['role'][:40]}")
        console.print(f"           {a.get('salary_range','?'):<15} | applied: {date_str} | email: {a.get('email_sent_to','?')}")
        console.print()


@app.command(name="jobs-dashboard")
def jobs_dashboard():
    """Obsidian kanban dashboard + Excel export. Run after every apply/update."""
    import job_tracker
    job_tracker.write_obsidian_dashboard()
    job_tracker.export_excel()
    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Obsidian: {job_tracker.DASH_PATH}")
    console.print(f"  Excel:    {job_tracker.EXCEL_PATH}")


@app.command(name="jobs-excel")
def jobs_excel():
    """Export all applications to color-coded Excel."""
    import job_tracker
    path = job_tracker.export_excel()
    if path:
        console.print(f"\n[green]Saved:[/green] {path}")


@app.command(name="jobs-update")
def jobs_update(
    company: str = typer.Option(...),
    role: str = typer.Option(...),
    status: str = typer.Option(..., help="applied | replied | interview | offer | rejected | ghosted"),
    notes: str = typer.Option("", help="Optional notes"),
):
    """
    Update application status. Auto-refreshes Obsidian + Excel.

    Examples:
      python cli.py jobs-update --company Callback --role "AI Engineer" --status replied
      python cli.py jobs-update --company Datacurve --role "Software Engineer" --status interview --notes "HR call 2026-06-25"
    """
    import job_tracker
    job_tracker.update_status(company, role, status, notes)


@app.command(name="trackb-dashboard")
def trackb_dashboard():
    """Obsidian kanban dashboard + Excel export for Track B (AI proposal) pipeline."""
    import track_b_tracker
    track_b_tracker.write_obsidian_dashboard()
    track_b_tracker.export_excel()
    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Obsidian: {track_b_tracker.DASH_PATH}")
    console.print(f"  Excel:    {track_b_tracker.EXCEL_PATH}")


@app.command(name="trackb-excel")
def trackb_excel():
    """Export all classified Track B companies to color-coded Excel."""
    import track_b_tracker
    track_b_tracker.export_excel()


@app.command(name="trackb-followup")
def trackb_followup(
    live: bool = typer.Option(False, "--live", help="Actually send. Default is dry-run."),
):
    """
    Send due follow-ups: day-3 (follow_up_1) for 'emailed' companies, day-7
    breakup (follow_up_2) for 'followed_up_1' companies with no reply.

    Default is dry-run. Pass --live to actually send. Stops per-company the
    moment outreach_status is set to 'replied' by hand.

    Example:
      python cli.py trackb-followup --live
    """
    import track_b_outreach
    summary = track_b_outreach.send_followups(dry_run=not live)
    if "error" in summary:
        raise typer.Exit(1)
    mode = "LIVE" if live else "DRY RUN"
    console.print(f"\n[bold]{mode}[/bold] — Sent: {summary['sent']}  Skipped: {summary['skipped']}")


@app.command(name="trackb-linkedin")
def trackb_linkedin(
    limit: int = typer.Option(5, "--limit", help="Max companies to target"),
    min_hunger: int = typer.Option(0, "--min-hunger", help="Only target hunger_score >= this"),
    live: bool = typer.Option(False, "--live", help="Actually send connection requests. Default is dry-run."),
):
    """
    Connect with a likely decision-maker at each Track B company on LinkedIn.

    Shares linkedin_agent.py's Playwright engine + daily rate limits with
    Track C (max 35 connects/day total across both tracks — real LinkedIn
    account cap, not per-track). Default is dry-run; pass --live to send.
    Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env.

    Examples:
      python cli.py trackb-linkedin --limit 5            # preview
      python cli.py trackb-linkedin --limit 5 --live     # actually connect
    """
    import asyncio
    import track_b_linkedin
    summary = asyncio.run(track_b_linkedin.run(limit=limit, dry_run=not live, min_hunger=min_hunger))
    mode = "LIVE" if live else "DRY RUN"
    console.print(f"\n[bold]{mode}[/bold] — Sent: {summary['sent']}  Skipped: {summary['skipped']}")


@app.command(name="trackb-sheets")
def trackb_sheets():
    """
    Sync Track B tracker to Google Sheets (same data as trackb-excel).

    First run opens a browser for one-time OAuth consent (Sheets scope only,
    separate token from Gmail). Reuses the same sheet on every later run.
    """
    import sheets_sync
    url = sheets_sync.sync_to_sheet()
    console.print(f"\n[green]Synced.[/green] {url}")


@app.command(name="jobs-sheets")
def jobs_sheets():
    """
    Sync Job Applications (apply_queue.json) → 'Job Applications' tab in existing Google Sheet.
    Same sheet as trackb-sheets. Reuses token_sheets.json OAuth token.
    Color-coded by email status: green=sent, yellow=pending, blue=queued.
    """
    import jobs_sheets_sync
    url = jobs_sheets_sync.sync_to_sheet()
    console.print(f"\n[green]Synced.[/green] {url}")


@app.command(name="trackb-find-emails")
def trackb_find_emails(
    limit: int = typer.Option(50, "--limit", help="Max companies to resolve"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing to DB"),
):
    """
    Resolve a real-world mailbox for every classified Track B company missing one.

    Uses website saved at sourcing time + Hunter.io/Snov.io if keys are set,
    else falls back to info@/enquiries@/contact@ pattern guesses (better fit
    for law/wealth/real-estate firms than startup-style founder@/ceo@).

    Example:
      python cli.py trackb-find-emails --limit 30
    """
    import track_b_outreach
    summary = track_b_outreach.find_missing_emails(limit=limit, dry_run=dry_run)
    console.print(f"\n[green]Resolved:[/green] {summary['resolved']}  [dim]Skipped:[/dim] {summary['skipped']}")


@app.command(name="trackb-send")
def trackb_send(
    limit: int = typer.Option(20, "--limit", help="Max companies to send to"),
    min_hunger: int = typer.Option(0, "--min-hunger", help="Only send to hunger_score >= this"),
    live: bool = typer.Option(False, "--live", help="Actually send. Default is dry-run (no emails sent)."),
):
    """
    Batch-send Agent-3 email drafts to classified Track B companies with an email on file.

    Default is --dry-run behavior (prints what would send, sends nothing).
    Pass --live to actually send via Gmail SMTP — requires GMAIL_ADDRESS +
    GMAIL_APP_PASSWORD in .env (myaccount.google.com/apppasswords).
    Only targets prospects with outreach_status == 'new'; marks 'emailed' after a real send.

    Examples:
      python cli.py trackb-send --min-hunger 6          # preview, no sends
      python cli.py trackb-send --min-hunger 6 --live   # actually send
    """
    import track_b_outreach
    summary = track_b_outreach.send_batch(limit=limit, dry_run=not live, min_hunger=min_hunger)
    if "error" in summary:
        raise typer.Exit(1)
    mode = "LIVE" if live else "DRY RUN"
    console.print(f"\n[bold]{mode}[/bold] — Sent: {summary['sent']}  Skipped: {summary['skipped']}")


@app.command(name="jobs-boards")
def jobs_boards(
    keywords: str = typer.Option("ai llm python automation", "--keywords"),
    max_age: int = typer.Option(48, "--max-age", help="Max age in hours"),
    boards: str = typer.Option(
        "weworkremotely,workingnomads,startup_jobs,jobspresso",
        "--boards",
        help="weworkremotely | workingnomads | startup_jobs | jobspresso | berlinstartups | euremotejobs | cwjobs_uk | crypto_jobs",
    ),
):
    """
    Niche + country boards — very low competition, worldwide remote.

    By competition:
      very_low: euremotejobs, berlinstartups, cwjobs_uk, crypto_jobs
      low:      startup_jobs, jobspresso, workingnomads
      medium:   weworkremotely

    Examples:
      python cli.py jobs-boards --boards euremotejobs,berlinstartups --max-age 72
      python cli.py jobs-boards --keywords "AI automation rust"
    """
    import job_pipeline
    from sources.remoteboards.scraper import fetch_all_boards, BOARDS

    kws = keywords.split()
    board_list = [b.strip() for b in boards.split(",") if b.strip()]

    console.print(f"\n[bold]Niche Board Search[/bold] | boards: {board_list} | ≤{max_age}h\n")
    jobs = fetch_all_boards(keywords=kws, max_age_hours=float(max_age), boards=board_list)

    if not jobs:
        console.print("[yellow]No jobs. Try --max-age 72.[/yellow]")
        return

    for j in jobs:
        j["score"] = job_pipeline.score_job(j)
    jobs.sort(key=lambda j: -j["score"])

    console.print(f"[green]{len(jobs)} jobs found[/green]\n")
    by_board = {}
    for j in jobs:
        by_board.setdefault(j["source"], []).append(j)

    for src, src_jobs in sorted(by_board.items(), key=lambda x: -len(x[1])):
        comp = BOARDS.get(src, {}).get("competition", "?")
        console.print(f"\n[bold]{src.upper()} ({len(src_jobs)}) [{comp} competition][/bold]")
        for j in src_jobs[:8]:
            age = f"{j['posted_hours_ago']:.1f}h" if j.get("posted_hours_ago") else "?"
            console.print(f"  [{j['score']:2d}/25] [{age}] {j['company']:<22} {j['title'][:45]}")
            console.print(f"          {j['url'][:80]}")


@app.command()
def wats(
    keywords: str = typer.Option("AI LLM python automation data", "--keywords"),
    exp: str = typer.Option("j", "--exp", help="i=intern j=junior m=mid s=senior a=any"),
    max_team: int = typer.Option(30, "--max-team"),
    score_min: int = typer.Option(7, "--score-min"),
):
    """
    Work At A Startup — YC's official job board (workatastartup.com).
    Every company here is YC-backed. Filter by experience level.

    Examples:
      python cli.py wats --exp j --keywords "AI automation python"
      python cli.py wats --exp i --max-team 10
    """
    import job_pipeline
    from sources.workatastartup.scraper import fetch_wats_api

    kws = keywords.split()
    console.print(f"\n[bold]Work at a Startup (YC Board)[/bold] | exp:{exp} | team≤{max_team}\n")

    jobs = fetch_wats_api(keywords=kws, exp=exp)
    for j in jobs:
        j["score"] = job_pipeline.score_job(j)

    filtered = [j for j in jobs if j["score"] >= score_min and (not j.get("team_size") or j["team_size"] <= max_team)]
    filtered.sort(key=lambda j: -j["score"])

    if not filtered:
        console.print("[yellow]No results. Try --score-min 5 or --exp a[/yellow]")
        return

    console.print(f"[green]{len(filtered)} YC jobs[/green]\n")
    for j in filtered[:30]:
        ts = f"team:{j['team_size']}" if j.get("team_size") else "team:?"
        console.print(f"  [{j['score']:2d}/25] {j['company']:<25} [{j['batch']}] {ts}")
        console.print(f"           {j['title'][:55]}")
        if j.get("one_liner"):
            console.print(f"           [dim]{j['one_liner'][:80]}[/dim]")
        console.print(f"           {j['url']}")
        console.print()


@app.command(name="find-email")
def find_email(
    company: str = typer.Option(..., help="Company name"),
    domain: str = typer.Option("", help="Domain e.g. getcallback.ai"),
):
    """
    Find founder/CTO email for a company.

    Uses Hunter.io first, then falls back to pattern guesses.
    Set HUNTER_API_KEY in .env for best results.

    Examples:
      python cli.py find-email --company Callback --domain getcallback.ai
      python cli.py find-email --company Reform
    """
    import job_pipeline

    result = job_pipeline.find_founder_email(company, domain=domain)
    console.print(f"\n[bold]Email search:[/bold] {company}\n")
    console.print_json(json.dumps(result, indent=2))


@app.command()
def social(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without acting"),
    stats: bool = typer.Option(False, "--stats", help="Show today's stats only"),
    li_connect: int = typer.Option(20, "--li-connect", help="LinkedIn connection limit (20 → ramp to 50)"),
    li_follow: int = typer.Option(120, "--li-follow", help="LinkedIn follow limit"),
    x_follow: int = typer.Option(80, "--x-follow", help="X follow limit"),
    x_like: int = typer.Option(25, "--x-like", help="X likes limit"),
    x_rt: int = typer.Option(8, "--x-rt", help="X retweet limit"),
    linkedin_only: bool = typer.Option(False, "--linkedin-only"),
    x_only: bool = typer.Option(False, "--x-only"),
):
    """
    Track C — Daily social growth: connections + follows + X engagement.

    Actions ONLY (no comments, no post replies):
      LinkedIn: 20 connections/day (CEOs/CTOs/VCs/new startups) + 120 follows/day
      X: 80 follows/day + 25 likes + 8 retweets (tech trends) + 1 article post (Mon/Wed/Fri)

    LinkedIn targets: new funded startups, CEOs, CTOs, VCs in AI/infra/protocol
    X targets: #RustLang #LLM #AIAgents #MCP #DistributedSystems trending posts

    Examples:
      python cli.py social --dry-run
      python cli.py social --stats
      python cli.py social --linkedin-only --li-connect 30
      python cli.py social --x-only --x-follow 100 --x-like 30 --x-rt 10
    """
    import asyncio

    if stats:
        track_c_social.show_stats()
        return

    asyncio.run(track_c_social.run_daily(
        dry_run=dry_run,
        li_connect=0 if x_only else li_connect,
        li_follow=0 if x_only else li_follow,
        x_follow=0 if linkedin_only else x_follow,
        x_like=0 if linkedin_only else x_like,
        x_rt=0 if linkedin_only else x_rt,
        linkedin_only=linkedin_only,
        x_only=x_only,
    ))


@app.command()
def content(
    days: int = typer.Option(7, "--days", help="Days of content to generate"),
    pillar: str = typer.Option("", "--pillar", help="Force pillar: rust_protocol | ai_infra | data_engineering | build_in_public | industry_take"),
    platform: str = typer.Option("both", "--platform", help="linkedin | x | both"),
    topic: str = typer.Option("", "--topic", help="Specific topic or angle"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print only, don't save"),
):
    """
    Track C — Generate content calendar (LinkedIn posts + X threads).

    Five pillars: rust_protocol | ai_infra | data_engineering | build_in_public | industry_take

    Output:
      agents/output/content/content_week_<date>.json
      Obsidian: TrackC_Social/Content/Content Calendar.md

    Examples:
      python cli.py content --days 7
      python cli.py content --pillar rust_protocol --platform x --topic "MCP server patterns"
      python cli.py content --pillar industry_take --topic "why most AI agents fail"
    """
    if pillar:
        post = content_agent.generate_post(pillar=pillar, platform=platform, topic=topic)
        content_agent.print_post(post)
        if not dry_run:
            post["date"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
            post["platform"] = platform
            post["status"] = "draft"
            content_agent._save_to_db(post)
            console.print(f"\n[green]Saved to DB[/green]")
    else:
        posts = content_agent.generate_week()
        console.print(f"\n[green]Generated {len(posts)} posts[/green] → agents/output/content/")
        console.print(f"[green]Obsidian calendar updated[/green] → TrackC_Social/Content/Content Calendar.md")


@app.command(name="social-stats")
def social_stats():
    """
    Track C — Show social growth stats (today + 7-day history).

    Examples:
      python cli.py social-stats
    """
    track_c_social.show_stats()
    track_c_social.update_obsidian_stats()
    console.print("[green]Obsidian analytics updated.[/green]")


@app.command(name="add-target")
def add_target(
    name: str = typer.Option(..., help="Full name"),
    role: str = typer.Option(..., help="CEO | CTO | VC | Fund Manager | Sr Engineer | Researcher"),
    company: str = typer.Option("", help="Company name"),
    linkedin: str = typer.Option("", help="LinkedIn URL"),
    x: str = typer.Option("", "--x", help="X handle e.g. @johndoe"),
    field: str = typer.Option("", help="AI | Protocol | Infra | Web3 | Finance"),
    priority: int = typer.Option(7, help="Priority 1-10"),
    notes: str = typer.Option("", help="Why this person?"),
):
    """
    Track C — Add high-value target to social pipeline.

    Examples:
      python cli.py add-target --name "John Doe" --role CEO --company "Acme AI" --linkedin "linkedin.com/in/jdoe" --x "@jdoe" --field AI --priority 9
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO social_targets (name, role, company, linkedin_url, x_handle, field, priority, notes, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, role, company, linkedin, x, field, priority, notes, "manual"),
    )
    conn.commit()
    conn.close()
    console.print(f"[green]Added target:[/green] {name} ({role} @ {company or '?'}) | priority: {priority}/10")


@app.command(name="build-add")
def build_add(
    name: str = typer.Option(..., help="Full name"),
    role: str = typer.Option(..., help="Role: Founder | CEO | CTO | VC | Entrepreneur"),
    country: str = typer.Option("", help="Country e.g. UAE / UK / Singapore / India"),
    company: str = typer.Option("", help="Company or startup name"),
    linkedin: str = typer.Option("", "--linkedin", help="LinkedIn URL"),
    x: str = typer.Option("", "--x", help="X handle"),
    idea: str = typer.Option("", "--idea", help="What they want to build"),
    problem: str = typer.Option("", "--problem", help="Their pain / gap"),
    source: str = typer.Option("track_c", "--source", help="track_c | linkedin | x | referral"),
    notes: str = typer.Option("", "--notes"),
    email: str = typer.Option("", "--email", help="Prospect's email address, if known"),
):
    """
    Track A (Custom Build) — Add non-technical founder/CEO/VC wanting to build something.

    These are people who have an idea + capital but no technical co-founder.
    Found via Track C connections → detected build signal → added here.

    Examples:
      python cli.py build-add --name "Ahmed Al-Farsi" --role Founder --country UAE --idea "inventory app for restaurant chain" --problem "managing 20 locations in Excel"
      python cli.py build-add --name "Sarah Chen" --role "VC Partner" --country Singapore --idea "portfolio monitoring dashboard" --source linkedin
    """
    pid = track_a_custom_build.add_prospect(
        name=name, role=role, company=company, country=country,
        linkedin_url=linkedin, x_handle=x, idea=idea, problem=problem,
        source=source, notes=notes, email=email,
    )
    console.print(f"[green]Added:[/green] {name} ({role}, {country or '?'}) → ID {pid}")
    console.print(f"[dim]Generate outreach: python cli.py build-outreach --id {pid}[/dim]")


@app.command(name="build-outreach")
def build_outreach(
    id: int = typer.Option(..., "--id", help="Prospect ID from build-list"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Track A (Custom Build) — Generate personalized outreach for a custom build prospect.

    Positions as builder-for-hire, not job seeker.
    Output: email + LinkedIn DM + 2 follow-ups.

    Examples:
      python cli.py build-outreach --id 1
      python cli.py build-outreach --id 3 --dry-run
    """
    if dry_run:
        console.print(f"[yellow]DRY RUN — would generate outreach for prospect {id}[/yellow]")
        return

    console.print(f"\n[bold]Generating custom build outreach for prospect {id}...[/bold]\n")
    result = track_a_custom_build.generate_outreach(id)

    console.print(f"\n[bold]TO:[/bold] {result['name']} ({result.get('company','?')}, {result.get('country','?')})")
    console.print(f"[bold]SUBJECT:[/bold] {result['subject']}\n")
    console.print(result["email"])
    console.print(f"\n[bold]LINKEDIN DM:[/bold]")
    console.print(result["linkedin_dm"])
    console.print(f"\n[bold]FOLLOW-UP 1 (day 5):[/bold]")
    console.print(result["follow_up_1"])
    console.print(f"\n[bold]FOLLOW-UP 2 (day 12):[/bold]")
    console.print(result["follow_up_2"])


@app.command(name="build-send")
def build_send(
    id: int = typer.Option(..., "--id", help="Prospect ID from build-list"),
    live: bool = typer.Option(False, "--live", help="Actually send. Default is dry-run."),
):
    """
    Track A (Custom Build) — Send the generated outreach email as davidmusk2002@gmail.com.

    Requires build-outreach to have been run first (needs the saved draft),
    and the prospect to have an email saved (--email on build-add).
    Sends via Gmail API OAuth (token_tracka.json) — separate identity from
    Track B's saraswatdas94 account.

    Examples:
      python cli.py build-send --id 3            # preview
      python cli.py build-send --id 3 --live     # actually send
    """
    try:
        result = track_a_custom_build.send_outreach(id, dry_run=not live)
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    mode = "LIVE" if live else "DRY RUN"
    console.print(f"\n[bold]{mode}[/bold] — {result['status']} → {result['to']}")


@app.command(name="build-list")
def build_list(
    status: str = typer.Option("", "--status", help="Filter: new | contacted | replied | scoping | building | done"),
):
    """
    Track A (Custom Build) — List all custom build prospects.

    Examples:
      python cli.py build-list
      python cli.py build-list --status new
    """
    prospects = track_a_custom_build.list_prospects(status=status or "")
    if not prospects:
        console.print("[yellow]No custom build prospects yet. Run build-add to add one.[/yellow]")
        return

    console.print(f"\n[bold]Custom Build Prospects ({status or 'all'}): {len(prospects)}[/bold]\n")
    for p in prospects:
        console.print(f"  [bold][{p['id']:3d}][/bold] [{p['status']:10s}] {p['name']:<25} {p['role']:<15} {p.get('country','?')}")
        if p.get("idea"):
            console.print(f"           Idea: {p['idea'][:70]}")
        console.print()


@app.command(name="contact-find")
def contact_find(
    regions: str = typer.Option("usa,europe", "--regions", help="Comma list: usa | europe | uk | all"),
    roles: str = typer.Option("CEO,CTO,Founder,Angel Investor", "--roles", help="Comma list of roles to target"),
    sectors: str = typer.Option(
        "AI startup,SaaS,fintech,legal tech,logistics,wealth management,prop tech",
        "--sectors",
        help="Comma list of sectors to search",
    ),
    limit: int = typer.Option(50, "--limit", help="Max contacts per run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without saving to DB"),
    fresh: bool = typer.Option(False, "--fresh", help="Show contacts found in last 24h only"),
):
    """
    Find CEOs/CTOs/VCs/Angels at small orgs (1-50 employees) in USA + Europe.
    Discovers emails via Hunter.io + pattern guessing.
    Routes to Track A (tech companies) or Track B (non-tech, wants AI automation).

    Runs automatically in daily_run.sh — also callable manually.

    Examples:
      python cli.py contact-find --regions usa --limit 30
      python cli.py contact-find --regions europe --sectors "legal tech,wealth management" --limit 20
      python cli.py contact-find --dry-run --regions usa
      python cli.py contact-find --fresh              # show today's contacts
    """
    import contact_finder

    region_list = [r.strip() for r in regions.split(",") if r.strip()]
    role_list   = [r.strip() for r in roles.split(",")   if r.strip()]
    sector_list = [s.strip() for s in sectors.split(",") if s.strip()]

    if fresh:
        contacts = contact_finder.list_contacts(fresh_hours=24, limit=200)
        console.print(f"\n[bold]Contacts found in last 24h: {len(contacts)}[/bold]\n")
        for c in contacts:
            track_col = "[green]A[/green]" if c["track"] == "A" else "[yellow]B[/yellow]" if c["track"] == "B" else "[dim]?[/dim]"
            console.print(
                f"  [{track_col}] {c['name'] or '—':<25} {c['role']:<20} {c.get('company','?'):<20} "
                f"{c.get('email','?')}"
            )
        return

    console.print(f"\n[bold]Contact Finder[/bold]")
    console.print(f"  Regions: {region_list}  |  Roles: {role_list[:3]}  |  Limit: {limit}")
    if dry_run:
        console.print("[yellow]  DRY RUN — no DB writes[/yellow]")
    console.print()

    summary = contact_finder.run_daily_find(
        regions=region_list,
        roles=role_list,
        sectors=sector_list,
        limit=limit,
        dry_run=dry_run,
    )

    console.print(f"\n[green]Done.[/green]  saved={summary['saved']}  skipped={summary['skipped']}  "
                  f"Track A={summary.get('final_a', summary.get('routed_a', 0))}  "
                  f"Track B={summary.get('final_b', summary.get('routed_b', 0))}")
    console.print(f"[dim]View: python cli.py contact-list[/dim]")


@app.command(name="contact-route")
def contact_route(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview routing without DB writes"),
):
    """
    Route pending contacts (track=unknown) to Track A or Track B.

    Track A (tech company) → flagged for job application / custom build outreach.
    Track B (non-tech, wants AI) → added to prospects DB for proposal outreach.

    Examples:
      python cli.py contact-route
      python cli.py contact-route --dry-run
    """
    import contact_finder

    console.print("\n[bold]Routing pending contacts...[/bold]\n")
    result = contact_finder.route_pending(dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "LIVE"
    console.print(f"\n[bold]{mode}[/bold]  Track A: {result['routed_a']}  Track B: {result['routed_b']}")
    if result["routed_b"] > 0 and not dry_run:
        console.print("[dim]Track B contacts → added to prospects table. Run: python cli.py classify --mode db[/dim]")


@app.command(name="contact-connect")
def contact_connect(
    limit: int = typer.Option(20, "--limit", help="Max connections to send (counts toward daily 35 cap)"),
    track: str = typer.Option("", "--track", help="Only connect with track A | B (default: all)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    Send LinkedIn connection requests to contacts found by contact-find.

    Targets contacts in contact_leads that have a linkedin_url but no email
    (or just haven't been connected with yet). Adds persona-matched notes.
    Status updated to 'linkedin_sent' after sending.

    Counts toward the shared daily LinkedIn limit (35 connects/day total).

    Examples:
      python cli.py contact-connect --dry-run
      python cli.py contact-connect --limit 15
      python cli.py contact-connect --track A --limit 10
    """
    import asyncio
    import sqlite3
    import contact_finder

    db_path = Path(os.environ.get("NETWORKING_DB", str(Path.home() / "networking-agent.db")))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conditions = ["linkedin_url != ''", "linkedin_url IS NOT NULL", "status = 'new'"]
    params: list = []
    if track:
        conditions.append("track = ?")
        params.append(track.upper())
    params.append(limit * 3)  # fetch more than needed — some may have no Connect button

    rows = conn.execute(
        f"SELECT id, name, role, company, linkedin_url, track, sector FROM contact_leads "
        f"WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No contacts with LinkedIn URLs in 'new' status.[/yellow]")
        console.print("[dim]Run: python cli.py contact-find first[/dim]")
        return

    # Build (url, note) pairs with persona-matched notes
    url_note_pairs = []
    for r in rows[:limit]:
        role_kw = (r["role"] or "").lower() + " " + (r["sector"] or "").lower()
        note = track_c_social._pick_note(role_kw)
        url_note_pairs.append((r["linkedin_url"], note))

    console.print(f"\n[bold]Contact Connect[/bold] — {len(url_note_pairs)} contacts")
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow]\n")

    result = asyncio.run(linkedin_agent.batch_connect_urls(
        url_note_pairs=url_note_pairs,
        dry_run=dry_run,
        limit=limit,
    ))

    sent = result.get("sent", 0)
    skipped = result.get("skipped", 0)

    # Mark sent contacts as 'linkedin_sent'
    if sent > 0 and not dry_run:
        conn = sqlite3.connect(str(db_path))
        for r in rows[:sent]:
            conn.execute(
                "UPDATE contact_leads SET status='linkedin_sent' WHERE id=?",
                (r["id"],),
            )
        conn.commit()
        conn.close()
        # Re-sync Sheet with updated status
        import contact_sheets_sync
        contact_sheets_sync.sync_contacts()

    mode = "DRY RUN" if dry_run else "LIVE"
    console.print(f"\n[bold]{mode}[/bold]  Sent: {sent}  Skipped: {skipped}")
    if sent > 0:
        console.print(f"[dim]Status updated → linkedin_sent. Sheet re-synced.[/dim]")


@app.command(name="contact-sheets")
def contact_sheets(
    track: str = typer.Option("", "--track", help="Filter: A | B (default: all)"),
    status: str = typer.Option("", "--status", help="Filter: new | contacted | replied"),
):
    """
    Sync contact_leads table → Google Sheets (Contacts tab).

    Sheet: https://docs.google.com/spreadsheets/d/1BCiz3eOGYza0fpENtUpEXJHxYPMce_a3As4ViMly9Og
    Tab:   Contacts (gid=1400798537)

    First run opens browser for one-time OAuth consent (reuses Sheets token).
    Run after contact-find to push fresh contacts to the spreadsheet.

    Examples:
      python cli.py contact-sheets               # sync all
      python cli.py contact-sheets --track A     # Track A only
      python cli.py contact-sheets --track B     # Track B only
    """
    import contact_sheets_sync

    console.print(f"\n[bold]Syncing contacts → Google Sheets[/bold]")
    if track:
        console.print(f"  Track: {track}")
    console.print()

    url = contact_sheets_sync.sync_contacts(track=track, status=status)
    console.print(f"\n[green]Synced.[/green] {url}")


@app.command(name="contact-list")
def contact_list(
    track: str = typer.Option("", "--track", help="Filter: A | B | unknown"),
    status: str = typer.Option("", "--status", help="Filter: new | contacted | replied"),
    fresh: int = typer.Option(0, "--fresh", help="Show contacts from last N hours (0=all)"),
    limit: int = typer.Option(50, "--limit"),
):
    """
    List contacts from the contact_leads table.

    Examples:
      python cli.py contact-list
      python cli.py contact-list --track A
      python cli.py contact-list --track B --status new
      python cli.py contact-list --fresh 24
    """
    import contact_finder

    contacts = contact_finder.list_contacts(
        track=track,
        status=status,
        limit=limit,
        fresh_hours=fresh,
    )

    if not contacts:
        console.print("[yellow]No contacts found. Run: python cli.py contact-find[/yellow]")
        return

    console.print(f"\n[bold]Contacts ({track or 'all'} track, {status or 'all'} status): {len(contacts)}[/bold]\n")
    for c in contacts:
        track_col = "[green]A[/green]" if c["track"] == "A" else "[yellow]B[/yellow]" if c["track"] == "B" else "[dim]?[/dim]"
        email_str = c.get("email") or "—"
        conf = f"[{c.get('email_confidence', '')}]" if c.get("email_confidence") else ""
        date_str = (c.get("created_at") or "")[:10]
        console.print(
            f"  [{track_col}] [{date_str}] {c['name'] or '—':<22} {c['role']:<18} "
            f"{c.get('company','?'):<20} {email_str} {conf}"
        )
        if c.get("sector"):
            console.print(f"           [dim]sector: {c['sector'][:50]}  region: {c.get('region','?')}[/dim]")
    console.print()


if __name__ == "__main__":
    app()
