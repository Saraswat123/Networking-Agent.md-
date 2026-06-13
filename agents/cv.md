# CV Agent

**Role:** JD-to-CV tailoring, skill reordering, bullet point rewriting  
**Runtime:** Python (`cv_agent.py`)  
**Model:** `claude-opus-4-8` with adaptive thinking + streaming  
**Triggered by:** `python cli.py cv` or internally by Job Agent

---

## Responsibility

Takes a job description + candidate profile → outputs a tailored CV in Markdown. Not generic — every CV is rewritten to match the exact language and priorities of the target role.

Core principle: **one CV per application**. The base profile (`profile.json`) is the raw material. The CV Agent shapes it for each specific job.

---

## Model Configuration

```python
client.messages.stream(
    model="claude-opus-4-8",
    max_tokens=3000,
    thinking={"type": "adaptive"},   # reasons before writing
    messages=[{"role": "user", "content": prompt}]
)
```

Adaptive thinking matters here — Claude decides how much reasoning to apply. For complex JDs (multiple required skills, unclear seniority), it thinks longer. For simple ones, it writes fast.

Streaming: CV renders to terminal live as it generates. Saves to `output/cvs/` on completion.

---

## Two Functions

### `generate_cv(jd_text, company_name, role_title) → str`

Full tailored CV as Markdown.

**What Claude does (from prompt):**
1. Extract from JD: must-haves, nice-to-haves, responsibilities, culture signals
2. Open with 2-sentence summary — technical, specific, references this exact role
3. Reorder skills: put what JD emphasizes most at top
4. Rewrite experience bullets using JD language (no lying — just emphasis shift)
5. Lead with most relevant project
6. End with one-line "Fit summary"
7. Keep it 1-page equivalent — every line earns its place

**CV opening line variants** (from `profile.json → cv_opening_lines`):

| Company Type | Opening |
|---|---|
| Rust companies | "Rust engineer focused on zero-latency AI agent tooling. Production MCP server, 11 tools, tokio async, zero GC pauses." |
| AI companies | "I ship the performance layer that makes AI agents fast. Most teams run Python MCP servers. Mine runs in Rust — deterministic, zero-overhead, production-ready." |
| Infra companies | "Systems engineer who crossed over into AI infrastructure. I build MCP servers in Rust because the protocol deserves a runtime that won't pause mid-tool-call." |
| Default | "I build fast AI agent infrastructure in Rust — because at agent scale, every millisecond compounds and Python's garbage collector doesn't care about your SLA." |

---

### `analyze_jd(jd_text) → dict`

Quick structured parse of any JD. No streaming — returns JSON immediately.

```json
{
  "role_type": "backend",
  "seniority": "senior",
  "must_have": ["Rust", "async", "distributed systems"],
  "nice_to_have": ["MCP", "WASM"],
  "stack": ["Rust", "Postgres", "Kafka"],
  "hiring_signals": ["Series B", "remote-first"],
  "culture_tags": ["open-source", "research"]
}
```

Used by:
- CV Agent itself (context for generation)
- Outreach Agent (picks right positioning angle)
- Job Agent (opportunity scoring)

---

## Profile Input (`profile.json`)

Key fields CV Agent reads:

```json
{
  "name", "email", "linkedin", "github",
  "title",          → used in CV header
  "summary",        → starting point for role-specific rewrite
  "skills",         → reordered per JD emphasis
  "experience",     → bullet points rewritten with JD language
  "projects",       → most relevant shown first
  "cv_opening_lines" → pre-written variants by company type
}
```

**Fill in before first use:**
- `education → institution + year`
- `linkedin → actual URL`

---

## Output

Saved to: `agents/output/cvs/cv_<company>_<role>.md`

Example: `cv_stripe_backend-engineer.md`

Format: pure Markdown — paste into Notion, convert to PDF via `pandoc`, or copy to Google Docs.

**To convert to PDF:**
```bash
pip install pandoc
pandoc agents/output/cvs/cv_stripe_backend-engineer.md -o cv_stripe.pdf
```

---

## Configuration

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Generate CV
python cli.py cv --jd path/to/jd.txt --company "Stripe" --role "Backend Engineer"

# Just analyze JD (no CV generated)
python cli.py analyze --jd path/to/jd.txt
```

---

## What "Tailored" Means in Practice

**Before (generic):**
```
Skills: Rust, Python, JavaScript, React, Node.js, Docker, MongoDB

Experience:
- Built multi-agent networking system in Rust
- Developed student assessment portal
- Architected MCP server
```

**After (tailored for "Rust Protocol Engineer at a FinTech"):**
```
Skills: Rust (tokio, serde, sqlx, rmcp) · async systems · MCP protocol ·
        zero-GC runtime design · Python · Node.js

Experience:
- Architected production rmcp MCP server processing 11 concurrent tool types;
  zero-copy serde deserialization, tokio multi-thread runtime, deterministic
  memory — no GC pauses under financial data load
- Built Hunter.io + WebReveal enrichment pipeline: 50ms avg latency per
  enrichment call, rate-limited to protect API quotas
```

Same facts. Different emphasis. Matches what the JD is actually asking for.

---

## Future: CV Agent v2

- PDF output directly (weasyprint or puppeteer)
- Multiple format variants: technical resume vs executive summary
- ATS optimization: keyword density analysis against JD requirements
- Version tracking: `cv_stripe_v1.md`, `cv_stripe_v2.md` with diff
