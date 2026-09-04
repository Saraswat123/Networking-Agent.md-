"""CV Agent — parses a job description and generates a tailored CV using Claude.

Multi-angle profile system:
  rust_mcp         → Rust MCP Infrastructure Engineer (protocol, agent infra, devtools)
  data_engineering → Data Engineer (PostgreSQL, Power BI, ETL, API pipelines, LLM automation)
  ai_ml_infra      → AI Infrastructure Engineer (LLM pipelines, multi-agent, Ollama, Claude)
  protocol_engineer → Protocol & Systems Engineer (distributed systems, BFT consensus, async Rust)

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
    "agent_infra":        "ai_ml_infra",
    "mcp":                "rust_mcp",
    "distributed":        "protocol_engineer",
    "networking":         "protocol_engineer",
    "p2p":                "protocol_engineer",
    "systems":            "protocol_engineer",
    "backend":            "rust_mcp",
    "fullstack":          "data_engineering",
    "data":               "data_engineering",
    "data_engineering":   "data_engineering",
    "analytics":          "data_engineering",
    "ml":                 "ai_ml_infra",
    "ai_infra":           "ai_ml_infra",
    "mlops":              "ai_ml_infra",
    "genai":              "ai_ml_infra",
    "llm":                "ai_ml_infra",
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
    ai_signals = ["llm", "ml", "pytorch", "tensorflow", "embedding", "vector", "inference",
                  "rag", "mlops", "genai", "fine-tuning", "ollama", "agent", "langchain",
                  "multi-agent", "anthropic", "openai", "huggingface"]
    proto_signals = ["protocol", "distributed", "p2p", "grpc", "tcp", "udp", "networking",
                     "libp2p", "consensus", "blockchain", "kafka", "pubsub", "bft"]

    combined = " ".join(stack + must + [role_type])

    rust_score = sum(1 for s in rust_signals if s in combined)
    data_score = sum(1 for s in data_signals if s in combined)
    ai_score = sum(1 for s in ai_signals if s in combined)
    proto_score = sum(1 for s in proto_signals if s in combined)

    # Protocol/consensus signals → protocol_engineer
    if "protocol" in combined or "p2p" in combined or "distributed" in combined or "consensus" in combined:
        angle = "protocol_engineer"
    elif ai_score >= 2:
        angle = "ai_ml_infra"
    elif rust_score >= 2:
        angle = "rust_mcp"
    elif proto_score > rust_score and proto_score >= 2:
        angle = "protocol_engineer"
    else:
        # Fall back to map
        angle = ROLE_TYPE_MAP.get(role_type, "rust_mcp")
        # If data/AI signals dominate, override
        if ai_score > rust_score and ai_score >= 2:
            angle = "ai_ml_infra"
        elif data_score > rust_score and data_score >= 2:
            angle = "data_engineering"

    print(f"  [cv_agent] angle={angle} (rust={rust_score} data={data_score} ai={ai_score} proto={proto_score})")
    return angle, cv_profiles[angle]


def generate_cv(job_description: str, company_name: str, role_title: str,
                angle_override: Optional[str] = None) -> str:
    """
    Parse JD → detect role type → pick profile angle → generate tailored CV.
    Streams to terminal, saves to output/cvs/, returns full text.

    angle_override: force "rust_mcp" | "data_engineering" | "ai_ml_infra" | "protocol_engineer"
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

    # Writing/publications from profile
    pubs = profile.get("publications", [])
    writing_section = ""
    for pub in pubs:
        title = pub.get("title", "")
        url = pub.get("url", "")
        platform = pub.get("platform", "")
        if url:
            writing_section += f"- [{title}]({url}) — {platform}\n"
        else:
            writing_section += f"- {title} — {platform}\n"

    # Achievements from profile
    ach_list = profile.get("achievements", [])
    achievements_md = ""
    for a in ach_list:
        line = f"- {a.get('title','')} — {a.get('result','')}"
        if a.get("context"):
            line += f" · {a['context']}"
        achievements_md += line + "\n"
    # Add patent (hardcoded, not in profile yet)
    achievements_md += "- Patent Filed — ML-based marine pollution detection (OCF Ocean Tech)\n"

    BASE_CV_LAYOUT = f"""# SARASWAT DAS

**[ROLE TITLE — match exact wording from JD]**

saraswatdas94@gmail.com · [GitHub](https://github.com/Saraswat123) · [LinkedIn](https://linkedin.com/in/saraswatdas) · [X / @SaraswatDas13](https://x.com/SaraswatDas13) · [saraswat.vercel.app](https://saraswat.vercel.app)

---

## SUMMARY

[2 sentences. Start with what you build, not who you are. Use exact terms from JD. Include one production number. No "passionate", no "team player", no "eager to".]

---

## TECHNICAL SKILLS

| Area | Technologies |
|------|-------------|
[2–4 rows. JD must-haves in FIRST row. Strip skills not relevant to this JD. Use exact tool names from JD where applicable.]

---

## PROJECTS

### [Most JD-Relevant Project Name] · [github.com/Saraswat123/repo-name](https://github.com/Saraswat123/repo-name)
*[Stack — exact tech names, comma separated]*

- [What problem it solves + specific technical approach — 1 sentence]
- [Core implementation detail that proves engineering depth — 1 sentence]
- [Outcome, scale, or signal — e.g. "deployed in production", "500+ teams", "one of first public X implementations"]

### [Second Most Relevant Project] · [github.com/Saraswat123/repo-name](https://github.com/Saraswat123/repo-name)
*[Stack]*

- [Problem + approach]
- [Technical depth]
- [Outcome/signal]

[Add 1–2 more projects if JD-relevant. Remove any project not relevant to this role. Always include GitHub link.]

---

## EXPERIENCE

### R&D Lead — Founders Office · AITS Group · Jun 2025 – Present
*15 locations · 50+ staff · Full-time*

- [Rewrite using JD language. Include the number: 80% reduction, 50+ staff, 30 tables, 15 APIs, 11 parameters. Lead with outcome not task.]
- [Second most relevant bullet — e.g. LLM pipeline, Claude Vision, PostgreSQL warehouse depending on JD]
- [Third bullet if space — Power BI, SMTP dispatch, or other relevant infrastructure]

### System Architect · Coddle Technologies Pvt. Ltd. · Nov 2024 – Apr 2025
- [1 bullet. Keep if it adds signal. Drop if it doesn't.]

---

## WRITING & PUBLICATIONS

{writing_section.strip()}

---

## ACHIEVEMENTS

{achievements_md.strip()}

---

## EDUCATION

**B.Tech — Computer Engineering**
Odisha University of Technology and Research (OUTR)"""

    prompt = f"""You are rewriting Saraswat Das's CV for a specific job application. Output pure Markdown only — no commentary, no preamble, no code fences.

STRUCTURE: Follow this template EXACTLY. Fill in all [bracketed placeholders]. Keep all section headers, dividers, and links:

{BASE_CV_LAYOUT}

─────────────────────────────────────────────────────
RULES — READ CAREFULLY:

1. ROLE TITLE: Derive from JD title exactly. Not "AI Engineer" if JD says "Founding Engineer, Inference Infrastructure".

2. SUMMARY: 2 sentences max.
   - Sentence 1: what you build (systems, not feelings). Must include one production number.
   - Sentence 2: what you're looking to do, referencing the specific domain from JD.
   - BANNED PHRASES: passionate, excited, eager, team player, fast learner, love, enjoy, motivated

3. SKILLS TABLE: 2-4 rows only. First row = JD must-haves. Use exact tool names from JD. Remove skills irrelevant to this role entirely.

4. PROJECTS: 2-4 projects. Each project MUST have:
   - H3 header with project name + clickable GitHub link
   - Italic stack line
   - 3 bullets: (a) problem+approach, (b) technical depth, (c) outcome/scale/signal
   - Pick projects most relevant to JD. For AI/LLM JDs: Networking Agent + Student Assessment Portal.
     For protocol/blockchain JDs: Axiom Engine + DVT-FOCIL + FOCIL + p2pflow.
     For data engineering JDs: Student Assessment Portal + Networking Agent.
   - DO NOT use a table for projects. Always H3 subsections.

5. EXPERIENCE bullets: rewrite using exact vocabulary from JD. Keep all numbers. Cut anything off-topic for this role.

6. WRITING section: Keep exactly as provided — do not modify the links.

7. ACHIEVEMENTS: Keep exactly as provided.

8. LENGTH: Aim for 1.5-2 pages when printed at 8.5pt font. Dense, no padding, no extra blank lines between bullets.

─────────────────────────────────────────────────────
INPUT DATA:

ANGLE: {angle_key}
TARGET ROLE: {role_title} @ {company_name}

JD ANALYSIS:
{json.dumps(jd_analysis, indent=2)}

EXPERIENCE BULLETS (use these as raw material, rewrite for this JD):
{json.dumps(angle.get('experience_bullets', []), indent=2)}

AVAILABLE PROJECTS (pick 2-4 most relevant):
{json.dumps(projects_for_angle, indent=2)}

SKILLS PRIORITY FOR THIS ANGLE:
{json.dumps(angle.get('skills_priority', []), indent=2)}

FULL JD:
{job_description[:2500]}"""

    full_response = ""
    print(f"\n  [Generating CV — angle: {angle_key}]\n")

    import subprocess as _sp
    env_clean = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = _sp.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=300, env=env_clean,
    )
    if result.returncode == 0:
        full_response = result.stdout.strip()
        # Strip markdown code fences if Claude wraps output
        if full_response.startswith("```"):
            lines = full_response.split("\n")
            lines = lines[1:]  # drop opening ```markdown or ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            full_response = "\n".join(lines).strip()
        print(full_response)
    else:
        # Fallback: try direct API if claude CLI fails
        try:
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            with client.messages.stream(
                model="claude-opus-4-8",
                max_tokens=3000,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                    full_response += text
        except Exception as e:
            print(f"  [cv_agent] both claude CLI and API failed: {e}")
            full_response = f"# CV generation failed\nError: {result.stderr}"

    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = "".join(c for c in company_name if c.isalnum() or c in "-_").lower()
    safe_role = "".join(c for c in role_title if c.isalnum() or c in "-_").lower()
    out_path = OUTPUT_DIR / f"cv_{safe_company}_{safe_role}_{angle_key}.md"
    out_path.write_text(full_response)
    print(f"\n[Saved → {out_path}]")

    return full_response


def analyze_jd(job_description: str) -> dict:
    """Quick JD parse — returns structured signal dict via claude -p subprocess."""
    import subprocess as _sp

    prompt = f"""Parse this job description and return ONLY valid JSON (no markdown, no explanation):

JD:
{job_description[:3000]}

Return:
{{
  "role_type": "rust|protocol|infra|devtools|backend|fullstack|data|data_engineering|analytics|ml|ai_infra|mlops|genai|llm|bi|etl|distributed|networking|p2p|systems|agent_infra|frontend|other",
  "seniority": "junior|mid|senior|staff|lead",
  "must_have": ["list of required tech/skills"],
  "nice_to_have": ["list of preferred tech/skills"],
  "stack": ["detected tech stack"],
  "hiring_signals": ["growth stage signals, team size mentions, etc."],
  "culture_tags": ["remote-first|fast-paced|research|open-source|etc"],
  "company_type": "rust_company|ai_company|infra_company|data_company|fullstack_company|protocol_company|other"
}}"""

    env_clean = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = _sp.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=60, env=env_clean,
    )
    if result.returncode == 0:
        text = result.stdout.strip()
    else:
        # Fallback to API if CLI fails
        try:
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            resp = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
        except Exception:
            return {"role_type": "other", "seniority": "mid", "must_have": [], "stack": []}

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
    if role in ("protocol", "distributed", "p2p", "networking", "systems"):
        return "protocol_company"
    if role in ("ml", "ai_infra", "mlops", "genai", "llm", "agent_infra"):
        return "llm_company"
    if "rust" in stack or role in ("rust", "infra"):
        return "rust_company"
    if role in ("data", "analytics", "bi", "etl", "data_engineering"):
        return "data_company"
    if "ai" in stack or "llm" in stack or "agent" in stack:
        return "llm_company"
    return "default"
