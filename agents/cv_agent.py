"""CV Agent — parses a job description and generates a tailored CV using Claude."""

import json
import os
from pathlib import Path

import anthropic

PROFILE_PATH = Path(__file__).parent / "profile.json"
OUTPUT_DIR = Path(__file__).parent / "output" / "cvs"


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return json.load(f)


def generate_cv(job_description: str, company_name: str, role_title: str) -> str:
    """
    Parse JD, match against profile, return tailored CV as markdown.
    Streams internally, returns final text.
    """
    profile = load_profile()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an expert CV writer and career coach.

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

TARGET COMPANY: {company_name}
TARGET ROLE: {role_title}

JOB DESCRIPTION:
{job_description}

TASK:
1. First, extract from the JD:
   - Must-have skills/tech
   - Nice-to-have skills
   - Key responsibilities
   - Culture/team signals (startup, scale, research, etc.)

2. Then generate a tailored CV in Markdown that:
   - Opens with a 2-sentence summary that is TECHNICAL and SPECIFIC — reference actual systems, runtimes, and performance characteristics. No "passionate about", no soft language. Sound like an engineer writing for engineers.
   - Use the candidate's core identity: performance-obsessed Rust systems engineer at the AI agent infrastructure layer
   - Reorders skills to lead with what the JD emphasizes most
   - Rewrites experience bullet points using JD language and NUMBERS where possible (11 tools, async, zero GC, etc.)
   - Highlights the most relevant project first with concrete technical detail
   - Keeps it to 1 page equivalent (tight, no filler — every line earns its place)
   - Uses the candidate's real name, email, and links from their profile
   - CV opening lines from profile.json (cv_opening_lines) are your starting templates — pick the most relevant variant

3. End with a one-line "Fit summary" — one sentence, no filler, pure signal.

Output format: pure Markdown, no extra commentary before or after."""

    full_response = ""
    with client.messages.stream(
        model="claude-opus-4-8",
        max_tokens=3000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_response += text

    print()  # newline after stream

    # Save to file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = "".join(c for c in company_name if c.isalnum() or c in "-_").lower()
    safe_role = "".join(c for c in role_title if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"cv_{safe_company}_{safe_role}.md"
    out_path.write_text(full_response)
    print(f"\n[Saved → {out_path}]")

    return full_response


def analyze_jd(job_description: str) -> dict:
    """Quick JD parse — returns structured signal dict for Outreach Agent."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""Parse this job description and return ONLY valid JSON (no markdown, no explanation):

JD:
{job_description}

Return:
{{
  "role_type": "backend|frontend|fullstack|ml|devtools|protocol|infra|other",
  "seniority": "junior|mid|senior|staff|lead",
  "must_have": ["list of required tech/skills"],
  "nice_to_have": ["list of preferred tech/skills"],
  "stack": ["detected tech stack"],
  "hiring_signals": ["growth stage signals, team size mentions, etc."],
  "culture_tags": ["remote-first|fast-paced|research|open-source|etc"]
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
