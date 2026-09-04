"""Outreach Agent — generates signal-based cold emails and LinkedIn messages.

Angle-aware: reads cv_agent.pick_profile_angle() to match outreach positioning
to the right CV angle (rust_mcp / data_engineering / ai_ml_infra / protocol_engineer).
"""

import json
import os
from pathlib import Path
from typing import Optional

import claude_cli as anthropic

PROFILE_PATH = Path(__file__).parent / "profile.json"
OUTPUT_DIR = Path(__file__).parent / "output" / "emails"


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return json.load(f)


def _pick_angle(jd_analysis: Optional[dict], tech_stack: list[str]) -> tuple[str, dict, dict]:
    """Return (angle_key, cv_profile, outreach_angles) for this prospect."""
    profile = load_profile()
    # Try to import cv_agent for angle detection
    try:
        import cv_agent
        if jd_analysis:
            angle_key, cv_prof = cv_agent.pick_profile_angle(jd_analysis)
        else:
            # Fallback: detect from tech stack
            fake_jd = {"role_type": "other", "stack": tech_stack, "must_have": tech_stack}
            angle_key, cv_prof = cv_agent.pick_profile_angle(fake_jd)
    except Exception:
        angle_key = "rust_mcp"
        cv_prof = profile["cv_profiles"]["rust_mcp"]

    outreach_angles = profile.get("outreach_angles", {}).get(angle_key, {})
    return angle_key, cv_prof, outreach_angles


def generate_outreach(
    company_name: str,
    contact_name: str,
    contact_role: str,
    contact_email: str,
    tech_stack: list[str],
    signal: str,
    job_description: str = "",
    jd_analysis: Optional[dict] = None,
    angle_override: Optional[str] = None,
) -> dict:
    """
    Generate cold email + LinkedIn message for one prospect.

    Auto-picks positioning angle from JD/tech stack.
    angle_override: force "rust_mcp" | "data_engineering" | "ai_ml_infra" | "protocol_engineer"
    """
    profile = load_profile()

    if angle_override:
        angle_key = angle_override
        cv_prof = profile["cv_profiles"].get(angle_key, profile["cv_profiles"]["rust_mcp"])
        outreach_angles = profile.get("outreach_angles", {}).get(angle_key, {})
    else:
        angle_key, cv_prof, outreach_angles = _pick_angle(jd_analysis, tech_stack)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    stack_str = ", ".join(tech_stack) if tech_stack else "their stack"
    jd_context = ""
    if jd_analysis:
        jd_context = f"\nJD ANALYSIS: {json.dumps(jd_analysis, indent=2)}"
    elif job_description:
        jd_context = f"\nJOB DESCRIPTION:\n{job_description[:1000]}"

    # Build angle-specific pitch lines
    angle_lines = "\n".join(f'{k.upper()}: "{v}"' for k, v in outreach_angles.items())

    prompt = f"""You are an expert outreach strategist. Write hyper-personalized cold outreach for a job seeker.

SENDER PROFILE:
Name: {profile['name']}
Email: {profile['email']}
LinkedIn: {profile['linkedin']}
GitHub: {profile['github']}

SELECTED ANGLE: {angle_key}
TITLE: {cv_prof['title']}
WEDGE: {cv_prof['positioning']['wedge']}
MACHINE STATEMENT: {cv_prof['positioning']['machine_statement']}

TOP SKILLS (this angle):
{chr(10).join(f'- {s}' for s in cv_prof['skills_priority'][:5])}

KEY PROOF POINTS (this angle):
{chr(10).join(f'- {b[:120]}' for b in cv_prof['experience_bullets'][:3])}

OUTREACH ANGLES — pick the most relevant one:
{angle_lines}

TARGET:
- Company: {company_name}
- Contact: {contact_name} ({contact_role})
- Email: {contact_email}
- Tech Stack: {stack_str}
- Signal (why reaching out NOW): {signal}
{jd_context}

RULES — non-negotiable:
- Email: 100-140 words MAX. Shorter = stronger. Every word earns its place.
- Subject: under 7 words. Internal Slack tone, not a sales pitch.
- Never start with "I". Start with a number, their company name, or a direct technical statement.
- No: "hope this finds you", "I'm reaching out", "I'm passionate", "love what you're building".
- Yes: one specific technical observation → one concrete proof point → one ask.
- One sentence under 5 words somewhere. Creates rhythm. Signals confidence.
- LinkedIn: 40-55 words. End with a technical question, not a compliment.
- Follow-ups add NEW information — a benchmark, GitHub link, new angle. Never just "bumping this".
- Match the SELECTED ANGLE above — do not drift into generic software engineer positioning.

Return ONLY valid JSON (no markdown fences):
{{
  "subject": "email subject line",
  "email": "full email body — plain text, no HTML",
  "linkedin_message": "short LinkedIn message",
  "follow_up_1": "7-day follow-up email (50 words, add new value/angle)",
  "follow_up_2": "14-day follow-up email (30 words, soft bump)",
  "angle_used": "{angle_key}"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("No text response from Claude")

    text = text_block.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    result = json.loads(text.strip())
    result["to"] = contact_email
    result["contact"] = contact_name
    result["company"] = company_name
    result["angle"] = angle_key

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f"{company_name}_{contact_name}" if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"outreach_{safe}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"[Saved → {out_path}]")

    return result


def generate_track_b_outreach(
    company_name: str,
    sector: str,
    location: str,
    contact_name: str,
    contact_role: str,
    contact_email: str,
    pain_points: list,
    solution_title: str,
    solution_description: str,
    hook: str,
    estimated_value: str,
    deliverables: list,
    hunger_score: int,
) -> dict:
    """
    Generate Track B (AI proposal) outreach: cold email + LinkedIn + 2 follow-ups.
    Positions Saraswat as an AI automation builder/consultant, not a job seeker.
    """
    profile = load_profile()
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    # Use data_engineering angle proof points — most relevant for Track B
    de = profile["cv_profiles"]["data_engineering"]
    bullets = de["experience_bullets"][:3]

    deliverables_str = "\n".join(f"- {d}" for d in deliverables[:5])
    pain_str = "\n".join(f"- {p}" for p in pain_points[:4])

    prompt = f"""You are an expert B2B cold outreach writer. Write hyper-personalized outreach from an AI builder to a non-technical company decision maker.

SENDER: Saraswat Das — AI & Data Engineer who builds automation systems for non-technical orgs.
PROOF POINTS (real, verified):
- Built multi-model LLM pipeline (Ollama + cloud APIs + Vector DB): auto-generates call scripts, emails, performance summaries — 80% reduction in manual comms prep across 50+ staff
- Designed centralized PostgreSQL data warehouse replacing 15 disconnected spreadsheets across 15 locations — 95% data accuracy, 85% overhead reduction
- Shipped OCR + handwriting recognition pipeline: handwritten documents → structured data extraction → dashboard in minutes
- Built production Rust MCP server + autonomous AI agent pipeline — GitHub: github.com/Saraswat123
Contact: saraswatdas94@gmail.com | Portfolio: saraswat.in

TARGET COMPANY:
Company: {company_name}
Sector: {sector}
Location: {location}
Contact: {contact_name} ({contact_role})
AI Hunger Score: {hunger_score}/10

THEIR PAIN POINTS:
{pain_str}

PROPOSED SOLUTION: {solution_title}
{solution_description}

KEY DELIVERABLES:
{deliverables_str}

ESTIMATED VALUE: {estimated_value}

HOOK (use this or improve it):
"{hook}"

RULES — non-negotiable:
- Email: 100-130 words MAX. Shorter = stronger. No fluff.
- Subject: under 8 words. Direct, specific to their pain. Not a sales pitch title.
- Never start with "I" or "My name is". Start with their pain point or a number.
- No: "hope this finds you well", "I'm reaching out", "revolutionize", "game-changing", "seamlessly".
- Yes: one specific pain observation (from their sector) → one concrete proof point from sender → one clear ask (20-min call / demo).
- One sentence under 6 words somewhere — creates rhythm, signals confidence.
- LinkedIn note: 40-55 words. End with specific question about their current workflow.
- Follow-up 1 (day 5): 50 words. Add NEW info — a specific benchmark, metric, or workflow angle not in email 1.
- Follow-up 2 (day 12): 25-30 words. Soft close — acknowledge busy, leave door open. No groveling.
- Tone: peer-to-peer, technical credibility without jargon, confident not pushy.

Return ONLY valid JSON (no markdown fences):
{{
  "subject": "email subject line",
  "email": "full plain text email body",
  "linkedin_message": "short LinkedIn message",
  "follow_up_1": "day-5 follow-up email",
  "follow_up_2": "day-12 follow-up email"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("No text response from Claude")

    text = text_block.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    # Extract first valid JSON object (handles trailing text after closing brace)
    try:
        result, _ = json.JSONDecoder().raw_decode(text.strip())
    except json.JSONDecodeError:
        # Find first { ... } block
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])

    result.update({
        "to": contact_email,
        "contact": contact_name,
        "contact_role": contact_role,
        "company": company_name,
        "sector": sector,
        "track": "B",
        "hook": hook,
        "estimated_value": estimated_value,
    })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f"trackb_{company_name}" if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"outreach_{safe}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"  [saved → {out_path.name}]")
    return result


def print_outreach(result: dict) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"TO:      {result.get('contact')} <{result.get('to')}>")
    print(f"COMPANY: {result.get('company')}")
    print(f"ANGLE:   {result.get('angle', '?')}")
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
