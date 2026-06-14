# CV Agent

**Role:** JD-to-CV tailoring with multi-angle profile system  
**Runtime:** Python (`cv_agent.py`)  
**Model:** `claude-opus-4-8` with adaptive thinking + streaming  
**Triggered by:** `python cli.py cv` or internally by Job Agent

---

## Three CV Angles

`profile.json` contains three complete CV profiles. CV Agent auto-detects which one to use from the JD.

| Angle | Title | Use When |
|---|---|---|
| `rust_mcp` | Rust Systems Engineer — AI Agent Infrastructure | JD asks for Rust, MCP, agent infra, devtools |
| `data_engineering` | AI & Data Engineer — LLM Automation + Full-Stack | JD asks for Python, SQL, data pipelines, analytics, full-stack |
| `protocol_engineer` | Protocol & Systems Engineer — Rust + Distributed Infra | JD asks for protocol design, distributed systems, p2p, async Rust |

Override: `--angle rust_mcp | data_engineering | protocol_engineer`

---

## Model Configuration

```python
client.messages.stream(
    model="claude-opus-4-8",
    max_tokens=3000,
    thinking={"type": "adaptive"},
    messages=[{"role": "user", "content": prompt}]
)
```

Adaptive thinking — Claude reasons longer for complex JDs before writing. Streaming renders live.

---

## Auto-Detection Logic (`pick_profile_angle`)

1. `analyze_jd()` extracts `role_type`, `stack`, `must_have`
2. Score rust/data/protocol signals across extracted terms
3. Pick angle with highest match score

```
rust signals:     rust, tokio, mcp, rmcp, async, wasm, systems   → rust_mcp
data signals:     python, sql, postgresql, pandas, power bi, node, react → data_engineering
protocol signals: protocol, distributed, p2p, grpc, kafka, libp2p → protocol_engineer
```

Terminal output shows which angle was chosen and why.

---

## Two Functions

### `generate_cv(jd_text, company, role, angle_override?) → str`

Full tailored CV as Markdown. What Claude does:

1. Reads selected angle's `skills_priority`, `experience_bullets`, `opening_lines`
2. Opens with 2-sentence technical summary — angle-specific, JD-adapted
3. Reorders skills: JD must-haves first
4. Rewrites experience bullets in JD language with numbers
5. Shows most relevant projects for that angle
6. Ends with one-line fit summary

Output saved: `agents/output/cvs/cv_<company>_<role>_<angle>.md`

### `analyze_jd(jd_text) → dict`

```json
{
  "role_type": "rust | protocol | data | backend | fullstack | ...",
  "seniority": "junior | mid | senior | staff | lead",
  "must_have": ["Rust", "async", "MCP"],
  "nice_to_have": ["WASM", "Kubernetes"],
  "stack": ["Rust", "Postgres", "Docker"],
  "hiring_signals": ["Series B", "10-person team"],
  "culture_tags": ["remote-first", "open-source"],
  "company_type": "rust_company | ai_company | infra_company | data_company | ..."
}
```

Used by: CV Agent (angle selection), Outreach Agent (positioning pick), Job Agent (scoring).

---

## Opening Lines Per Angle

### rust_mcp
| Company Type | Opening |
|---|---|
| Default | "I build fast AI agent infrastructure in Rust — because at agent scale, every millisecond compounds and Python's garbage collector doesn't care about your SLA." |
| Rust company | "Rust engineer focused on zero-latency AI agent tooling. Production MCP server, 11 tools, tokio async, zero GC pauses." |
| AI company | "I ship the performance layer that makes AI agents fast. Most teams run Python MCP servers. Mine runs in Rust — deterministic, zero-overhead, production-ready." |
| Protocol company | "Protocol engineer who ships in Rust. Built production MCP server, rate limiter, PII filter, audit layer — the full compliance stack for agent tool use." |

### data_engineering
| Company Type | Opening |
|---|---|
| Default | "I build AI systems that automate data workflows — from API integration pipelines to LLM-powered analysis layers that turn raw data into structured, actionable output." |
| Data company | "Data engineer who builds AI automation on top of existing data stacks. PostgreSQL, Power BI, 15 API integrations, Claude-powered analysis — all production." |
| AI company | "I use Claude API to build real automation: document extraction, structured data analysis, multi-agent pipelines. Not demos — deployed systems replacing manual workflows." |

### protocol_engineer
| Company Type | Opening |
|---|---|
| Default | "Protocol engineer who ships in Rust. I work at the wire level — transport design, serialization, async dispatch, rate limiting. Production MCP server live." |
| Infra company | "Systems engineer with production Rust protocol work. Built MCP server, sliding-window rate limiter, PII pipeline — the full compliance stack for agent tool use at scale." |

---

## Usage

```bash
# Auto-detect angle from JD
python cli.py cv --jd stripe_jd.txt --company "Stripe" --role "Backend Engineer"

# Force specific angle
python cli.py cv --jd cloudflare_jd.txt --company "Cloudflare" --role "Rust Engineer" --angle rust_mcp
python cli.py cv --jd dbt_jd.txt --company "dbt Labs" --role "Data Engineer" --angle data_engineering
python cli.py cv --jd fly_jd.txt --company "Fly.io" --role "Protocol Engineer" --angle protocol_engineer

# Just analyze JD (no CV)
python cli.py analyze --jd path/to/jd.txt
```

---

## Output

`agents/output/cvs/cv_<company>_<role>_<angle>.md`

Example: `cv_cloudflare_rust-engineer_rust_mcp.md`

Convert to PDF:
```bash
pandoc agents/output/cvs/cv_cloudflare_rust-engineer_rust_mcp.md -o cv_cloudflare.pdf
```

---

## What "Tailored" Means in Practice

**Before (generic):**
```
Skills: Rust, Python, JavaScript, React, Node.js, Docker, MongoDB
Experience: Built multi-agent networking system in Rust
```

**After — rust_mcp angle for "Rust Protocol Engineer at FinTech":**
```
Skills: Rust (tokio, serde, sqlx, rmcp) · MCP protocol (JSON-RPC 2.0 over stdio) ·
        zero-GC async runtime · PII detection pipeline · sliding-window rate limiter

Experience:
- Designed production MCP server in Rust: 11 tool handlers, rmcp macro-based dispatch,
  tokio multi-thread runtime — deterministic memory, zero GC pauses under financial data load
- Built sliding-window rate limiter: tokio::sync::Mutex + VecDeque<Instant>, per-tool limits,
  O(1) eviction — 5/min Hunter.io, 60/min DB writes, 20/min WebReveal
```

Same facts. Different angle. Matches exactly what the JD asks for.

---

## Updating Profile

Edit `agents/profile.json → cv_profiles → <angle>`:
- `skills_priority` — reorder to change emphasis
- `experience_bullets` — add new accomplishments
- `opening_lines` — add new company type variants
- `target_roles` / `target_companies` — adjust Job Agent scoring
