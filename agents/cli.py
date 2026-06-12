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

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

import cv_agent
import orchestrator
import outreach_agent
import prospect_bridge

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


if __name__ == "__main__":
    app()
