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
import x_agent

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


if __name__ == "__main__":
    app()
