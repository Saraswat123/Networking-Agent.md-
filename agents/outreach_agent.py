"""Outreach Agent — generates signal-based cold emails and LinkedIn messages."""

import json
import os
from pathlib import Path

import anthropic

PROFILE_PATH = Path(__file__).parent / "profile.json"
OUTPUT_DIR = Path(__file__).parent / "output" / "emails"


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return json.load(f)


def generate_outreach(
    company_name: str,
    contact_name: str,
    contact_role: str,
    contact_email: str,
    tech_stack: list[str],
    signal: str,
    job_description: str = "",
    jd_analysis: dict | None = None,
) -> dict:
    """
    Generate cold email + LinkedIn message for one prospect.

    Args:
        company_name:   Target company name
        contact_name:   Decision maker name (from Hunter.io / GitHub)
        contact_role:   Their title
        contact_email:  Their email
        tech_stack:     List of tech detected (from lookup_tech_stack)
        signal:         Specific signal e.g. "just raised Series A", "posted Rust engineer job", "shipped v2 of X"
        job_description: Full JD text if applying to a specific role
        jd_analysis:    Pre-parsed JD dict from cv_agent.analyze_jd()
    """
    profile = load_profile()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    stack_str = ", ".join(tech_stack) if tech_stack else "their stack"
    jd_context = ""
    if jd_analysis:
        jd_context = f"\nJD ANALYSIS: {json.dumps(jd_analysis, indent=2)}"
    elif job_description:
        jd_context = f"\nJOB DESCRIPTION:\n{job_description[:1000]}"

    prompt = f"""You are an expert outreach strategist. Write hyper-personalized cold outreach for a job seeker.

SENDER PROFILE:
{json.dumps(profile, indent=2)}

TARGET:
- Company: {company_name}
- Contact: {contact_name} ({contact_role})
- Email: {contact_email}
- Tech Stack: {stack_str}
- Signal (why reaching out NOW): {signal}
{jd_context}

IDENTITY TO PROJECT (sender is a performance-obsessed systems engineer):
- Not a generalist. A specialist. Rust. MCP. Zero-latency agent infra. That's it.
- The core tension to exploit: "Most AI infra runs on Python. Python has a GC. GCs pause. Agents don't wait."
- Shipped proof: production rmcp MCP server, 11 live tools, tokio async runtime, zero GC pauses, running now.

PICK ONE ANGLE PER EMAIL (match to company's specific pain):
A) PERFORMANCE: "Python MCP = 50-200ms per tool call. At 1000 tool calls in an agentic loop, that's 3 dead minutes. My Rust server doesn't pause."
B) RARITY: "Most AI engineers can't write systems code. Most systems engineers don't understand LLM tool use. I work both layers."
C) TIMING: "MCP is 6 months old. I shipped a production Rust implementation 5 months ago. You're still deciding — I already know what breaks."
D) SHIPPED: "Not theory. Production MCP server. 11 tools. Async. SQLite persistence. Running now. Show me your stack."

RULES — non-negotiable:
- Email: 100-140 words MAX. Shorter = stronger. Every word earns its place.
- Subject: under 7 words. Make it sound like internal Slack, not a sales pitch.
- Never start with "I". Start with a number, their company name, or a direct technical statement.
- No: "hope this finds you", "I'm reaching out", "I'm passionate", "I'm excited", "love what you're building".
- Yes: one specific technical observation about their product/stack → one concrete proof point → one ask.
- One sentence under 5 words somewhere. Creates rhythm. Signals confidence.
- LinkedIn: 40-55 words. End with a technical question, not a compliment.
- Follow-ups add NEW information — a benchmark, a GitHub link, a new angle. Never just "bumping this".

Return ONLY valid JSON (no markdown fences):
{{
  "subject": "email subject line",
  "email": "full email body — plain text, no HTML",
  "linkedin_message": "short LinkedIn message",
  "follow_up_1": "7-day follow-up email (50 words, add new value/angle)",
  "follow_up_2": "14-day follow-up email (30 words, soft bump)"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text block (skip thinking blocks)
    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("No text response from Claude")

    text = text_block.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    result = json.loads(text)
    result["to"] = contact_email
    result["contact"] = contact_name
    result["company"] = company_name

    # Save output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f"{company_name}_{contact_name}" if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"outreach_{safe}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"[Saved → {out_path}]")

    return result


def print_outreach(result: dict) -> None:
    """Pretty-print outreach package to terminal."""
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"TO:      {result.get('contact')} <{result.get('to')}>")
    print(f"COMPANY: {result.get('company')}")
    print(f"{sep}")
    print(f"SUBJECT: {result['subject']}\n")
    print(result["email"])
    print(f"\n{sep}")
    print("LINKEDIN:")
    print(result["linkedin_message"])
    print(f"\n{sep}")
    print("FOLLOW-UP 1 (day 7):")
    print(result["follow_up_1"])
    print(f"\n{sep}")
    print("FOLLOW-UP 2 (day 14):")
    print(result["follow_up_2"])
    print(sep)
