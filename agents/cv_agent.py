"""CV Agent — parses a job description and generates a tailored CV using Claude.

Multi-angle profile system:
  rust_mcp        → Rust MCP Infrastructure Engineer (protocol, agent infra, devtools)
  data_engineering → AI & Data Engineer (Python, PostgreSQL, Power BI, LLM automation)
  protocol_engineer → Protocol & Systems Engineer (distributed systems, async Rust)

CV Agent detects role type from JD, picks matching profile angle, generates tailored CV.
"""

import json
import os
from pathlib import Path
from typing import Optional

import anthropic

PROFILE_PATH = Path(__file__).parent / "profile.json"
OUTPUT_DIR = Path(__file__).parent / "output" / "cvs"

# Map JD role_type strings → profile angle keys
ROLE_TYPE_MAP = {
    "rust":               "rust_mcp",
    "protocol":           "protocol_engineer",
    "infra":              "rust_mcp",
    "devtools":           "rust_mcp",
    "agent_infra":        "rust_mcp",
    "mcp":                "rust_mcp",
    "distributed":        "protocol_engineer",
    "networking":         "protocol_engineer",
    "p2p":                "protocol_engineer",
    "systems":            "protocol_engineer",
    "backend":            "data_engineering",
    "fullstack":          "data_engineering",
    "data":               "data_engineering",
    "analytics":          "data_engineering",
    "ml":                 "data_engineering",
    "bi":                 "data_engineering",
    "etl":                "data_engineering",
    "frontend":           "data_engineering",
    "other":              "rust_mcp",      # default to strongest angle
}


def load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return json.load(f)


def pick_profile_angle(jd_analysis: dict, override: Optional[str] = None) -> tuple[str, dict]:
    """
    Given JD analysis dict, return (angle_key, angle_profile).
    Override: force a specific angle ("rust_mcp" | "data_engineering" | "protocol_engineer").
    """
    profile = load_profile()
    cv_profiles = profile["cv_profiles"]

    if override and override in cv_profiles:
        return override, cv_profiles[override]

    role_type = (jd_analysis.get("role_type") or "other").lower().strip()
    stack = [s.lower() for s in jd_analysis.get("stack", [])]
    must = [s.lower() for s in jd_analysis.get("must_have", [])]

    # Stack-based overrides
    rust_signals = ["rust", "tokio", "mcp", "rmcp", "async", "systems", "protocol", "wasm"]
    data_signals = ["python", "sql", "postgresql", "postgres", "power bi", "pandas", "etl",
                    "airflow", "dbt", "analytics", "dashboard", "mongodb", "node", "react",
                    "javascript", "typescript", "fullstack", "full-stack"]
    proto_signals = ["protocol", "distributed", "p2p", "grpc", "tcp", "udp", "networking",
                     "libp2p", "consensus", "blockchain", "kafka", "pubsub"]

    combined = " ".join(stack + must + [role_type])

    rust_score = sum(1 for s in rust_signals if s in combined)
    data_score = sum(1 for s in data_signals if s in combined)
    proto_score = sum(1 for s in proto_signals if s in combined)

    # Rust/protocol signals + explicit rust/protocol role → rust_mcp or protocol_engineer
    if "protocol" in combined or "p2p" in combined or "distributed" in combined:
        angle = "protocol_engineer"
    elif rust_score >= 2:
        angle = "rust_mcp"
    elif proto_score > rust_score and proto_score >= 2:
        angle = "protocol_engineer"
    else:
        # Fall back to map
        angle = ROLE_TYPE_MAP.get(role_type, "rust_mcp")
        # If data signals dominate, force data angle
        if data_score > rust_score and data_score >= 2:
            angle = "data_engineering"

    print(f"  [cv_agent] angle={angle} (rust={rust_score} data={data_score} proto={proto_score})")
    return angle, cv_profiles[angle]


def generate_cv(job_description: str, company_name: str, role_title: str,
                angle_override: Optional[str] = None) -> str:
    """
    Parse JD → detect role type → pick profile angle → generate tailored CV.
    Streams to terminal, saves to output/cvs/, returns full text.

    angle_override: force "rust_mcp" | "data_engineering" | "protocol_engineer"
    """
    profile = load_profile()
    jd_analysis = analyze_jd(job_description)
    angle_key, angle = pick_profile_angle(jd_analysis, override=angle_override)

    shared_exp = profile.get("shared_experience", [])
    projects_for_angle = [
        p for p in profile.get("projects", [])
        if angle_key in p.get("relevant_for", [angle_key])
    ]

    # Pick opening line
    opening_lines = angle.get("opening_lines", {})
    company_type = _detect_company_type(jd_analysis)
    opening = opening_lines.get(company_type, opening_lines.get("default", ""))

    outreach_angles = profile.get("outreach_angles", {}).get(angle_key, {})

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an expert CV writer for technical engineering roles.

CANDIDATE NAME: {profile['name']}
EMAIL: {profile['email']}
LINKEDIN: {profile['linkedin']}
GITHUB: {profile['github']}
LOCATION: {profile['location']}

SELECTED CV ANGLE: {angle_key}
TITLE: {angle['title']}
POSITIONING SUMMARY: {angle['summary']}
WEDGE: {angle['positioning']['wedge']}

SKILLS (in priority order for this role type):
{json.dumps(angle['skills_priority'], indent=2)}

EXPERIENCE BULLETS (for this angle):
{json.dumps(angle['experience_bullets'], indent=2)}

SHARED COMPANY EXPERIENCE:
{json.dumps(shared_exp, indent=2)}

RELEVANT PROJECTS:
{json.dumps(projects_for_angle, indent=2)}

OPENING LINE OPTIONS:
{json.dumps(opening_lines, indent=2)}
RECOMMENDED OPENING: {opening}

OUTREACH POSITIONING ANGLES:
{json.dumps(outreach_angles, indent=2)}

JD ANALYSIS (auto-detected):
{json.dumps(jd_analysis, indent=2)}

TARGET COMPANY: {company_name}
TARGET ROLE: {role_title}

FULL JOB DESCRIPTION:
{job_description}

TASK — Generate a tailored CV in Markdown:

1. Header: name, email, github, linkedin, location on same line or two
2. Opening: 2-sentence technical summary — use the RECOMMENDED OPENING as starting point,
   adapt it to reference something specific in this JD. NO soft language ("passionate about",
   "team player"). Sound like an engineer writing for engineers.
3. Skills: list from skills_priority, reorder to put what JD must-haves first
4. Experience: use experience_bullets + shared_experience, rewrite with JD language.
   Numbers everywhere possible. No vague verbs like "worked on" or "helped with".
5. Projects: most JD-relevant first. Include tech stack + one concrete metric or signal.
6. Education: include degree/institution/year from profile
7. Fit summary: one line, no filler — pure signal on why this exact candidate for this exact role.

Keep it tight — 1 page equivalent. Every line earns its place or it's cut.
Output: pure Markdown only, no commentary before or after."""

    full_response = ""
    print(f"\n  [Generating CV — angle: {angle_key}]\n")
    with client.messages.stream(
        model="claude-opus-4-8",
        max_tokens=3000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_response += text

    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = "".join(c for c in company_name if c.isalnum() or c in "-_").lower()
    safe_role = "".join(c for c in role_title if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"cv_{safe_company}_{safe_role}_{angle_key}.md"
    out_path.write_text(full_response)
    print(f"\n[Saved → {out_path}]")

    return full_response


def analyze_jd(job_description: str) -> dict:
    """Quick JD parse — returns structured signal dict."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""Parse this job description and return ONLY valid JSON (no markdown, no explanation):

JD:
{job_description}

Return:
{{
  "role_type": "rust|protocol|infra|devtools|backend|fullstack|data|analytics|ml|bi|etl|distributed|networking|p2p|systems|frontend|other",
  "seniority": "junior|mid|senior|staff|lead",
  "must_have": ["list of required tech/skills"],
  "nice_to_have": ["list of preferred tech/skills"],
  "stack": ["detected tech stack"],
  "hiring_signals": ["growth stage signals, team size mentions, etc."],
  "culture_tags": ["remote-first|fast-paced|research|open-source|etc"],
  "company_type": "rust_company|ai_company|infra_company|data_company|fullstack_company|protocol_company|other"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text.strip())
    except Exception:
        return {"role_type": "other", "seniority": "mid", "must_have": [], "stack": []}


def _detect_company_type(jd_analysis: dict) -> str:
    """Map JD analysis → opening line variant key."""
    ct = jd_analysis.get("company_type", "")
    role = jd_analysis.get("role_type", "")
    stack = " ".join(jd_analysis.get("stack", [])).lower()

    if ct:
        return ct
    if "rust" in stack or role in ("rust", "protocol", "infra"):
        return "rust_company"
    if role in ("data", "analytics", "bi", "ml", "etl"):
        return "data_company"
    if role in ("protocol", "distributed", "p2p", "networking"):
        return "protocol_company"
    if "ai" in stack or "llm" in stack or "agent" in stack:
        return "ai_company"
    return "default"
