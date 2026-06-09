# Networking Agent — Full Technical Architecture

> Complete technical reference: every crate, every layer, every wire message, every design decision. Grounded in real source code at `/Users/aitsgroup/networking-agent/`.

---

## Table of Contents

1. [What This Agent Is](#1-what-this-agent-is)
2. [File Structure](#2-file-structure)
3. [Architecture Diagram](#3-architecture-diagram)
4. [How Claude Connects to It](#4-how-claude-connects-to-it)
5. [Full Dependency Stack](#5-full-dependency-stack)
6. [rmcp — The MCP Framework](#6-rmcp--the-mcp-framework)
7. [tokio — The Async Runtime](#7-tokio--the-async-runtime)
8. [reqwest — HTTP Client & TLS Stack](#8-reqwest--http-client--tls-stack)
9. [serde + schemars — Type System Bridge](#9-serde--schemars--type-system-bridge)
10. [sqlx — Async SQLite](#10-sqlx--async-sqlite)
11. [scraper — HTML Parser (Unused but Present)](#11-scraper--html-parser)
12. [MCP Wire Protocol — Real JSON Messages](#12-mcp-wire-protocol--real-json-messages)
13. [End-to-End Data Flow](#13-end-to-end-data-flow)
14. [Design Decisions Explained](#14-design-decisions-explained)
15. [Mental Model Summary](#15-mental-model-summary)

---

## 1. What This Agent Is

A **Model Context Protocol (MCP) server** written in Rust. It exposes 8 tools Claude can call to build a networking/outreach pipeline:

| Tool | What it does |
|------|-------------|
| `search_github_users` | GitHub user search by role + location |
| `get_org_members` | All public members of a GitHub org |
| `find_open_issues` | Open "good first issue" / "help wanted" in any repo |
| `get_yc_companies` | YC companies by batch (W24, S25, W25…) |
| `search_yc_companies` | YC companies by keyword + location |
| `save_prospect` | Write a prospect to SQLite DB |
| `list_prospects` | Read all saved prospects |
| `update_prospect_status` | Move prospect through outreach pipeline |

**It is not a web server.** No port, no HTTP listener. Claude Code spawns it as a subprocess and communicates via **stdin/stdout using JSON-RPC 2.0**.

---

## 2. File Structure

```
networking-agent/
├── Cargo.toml          ← 9 direct dependencies
├── Cargo.lock          ← 150+ pinned transitive deps
├── CLAUDE.md           ← instructions for Claude Code agent
├── Dockerfile          ← containerized deployment
├── docker-compose.yml
├── migrations/         ← (empty, schema done inline in db.rs)
└── src/
    ├── main.rs         ← entry point: init db, build server, start stdio
    ├── server.rs       ← all 8 tools + NetworkingServer struct
    ├── db.rs           ← SQLite pool init + CREATE TABLE
    └── tools/
        ├── mod.rs      ← re-exports github + yc modules
        ├── github.rs   ← GitHub API calls (search, profile, org, issues)
        └── yc.rs       ← YC API calls (batch fetch + keyword search)
```

**Data flows:** `main.rs` → `db.rs` (pool) + `server.rs` (tools) → `tools/github.rs` + `tools/yc.rs`

---

## 3. Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║  CLAUDE (LLM)                                                    ║
║  • Sees tool list + JSON schemas on startup                      ║
║  • Decides which tool to call based on user request              ║
║  • Reads tool result → reasons → may call another tool           ║
╚═══════════════════════╦══════════════════════════════════════════╝
                        ║ JSON-RPC 2.0, newline-delimited
                        ║ over process stdin / stdout
                        ║ (MCP protocol, stdio transport)
╔═══════════════════════╩══════════════════════════════════════════╗
║  networking-agent  (Rust binary, single process)                 ║
║                                                                  ║
║  main.rs                                                         ║
║  ┌─────────────────────────────────────────────────────────┐    ║
║  │ #[tokio::main]                                           │    ║
║  │   read GITHUB_TOKEN + NETWORKING_DB from env            │    ║
║  │   db::init_pool(db_path)  →  SqlitePool                 │    ║
║  │   NetworkingServer::new(pool, token)                     │    ║
║  │   server.serve(stdio())  →  start read loop              │    ║
║  │   service.waiting()      →  block until stdin closes     │    ║
║  └─────────────────────────────────────────────────────────┘    ║
║                                                                  ║
║  server.rs  (NetworkingServer)                                   ║
║  ┌─────────────────────────────────────────────────────────┐    ║
║  │ struct NetworkingServer {                                │    ║
║  │   tool_router: ToolRouter<Self>,  ← rmcp dispatch table  │    ║
║  │   http_client: Client,            ← reqwest, pooled      │    ║
║  │   db: SqlitePool,                 ← sqlx, max 5 conns    │    ║
║  │   github_token: String,                                  │    ║
║  │ }                                                        │    ║
║  │                                                          │    ║
║  │ #[tool_router] impl NetworkingServer {                   │    ║
║  │   search_github_users  ──────────────────────────────►  │    ║
║  │   get_org_members      ──── reqwest ────────────────►   │    ║
║  │   find_open_issues     ──────────────────────────────►  │    ║
║  │   get_yc_companies     ──── reqwest ────────────────►   │    ║
║  │   search_yc_companies  ──────────────────────────────►  │    ║
║  │   save_prospect        ──── sqlx ───────────────────►   │    ║
║  │   list_prospects       ──── sqlx ───────────────────►   │    ║
║  │   update_prospect_status ── sqlx ───────────────────►   │    ║
║  │ }                                                        │    ║
║  └─────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════╝
          │ reqwest                        │ sqlx
          ▼                               ▼
  ┌───────────────────┐         ┌─────────────────────┐
  │  api.github.com   │         │  ~/networking-       │
  │  • /search/users  │         │    agent.db          │
  │  • /users/:login  │         │  (SQLite file)       │
  │  • /orgs/:org/    │         │                      │
  │    members        │         │  tables:             │
  │  • /repos/:o/:r/  │         │  • prospects         │
  │    issues         │         │  • outreach_log      │
  └───────────────────┘         └─────────────────────┘
          │ reqwest
          ▼
  ┌───────────────────────┐
  │  api.ycombinator.com  │
  │  /v0.1/companies      │
  │  ?batch=W25           │
  │  ?q=AI&page=1         │
  └───────────────────────┘
```

---

## 4. How Claude Connects to It

Claude Code reads `~/.claude/projects/.../CLAUDE.md` which points to the MCP server config. Claude Code then:

1. **Spawns** `./networking-agent` as a child process
2. Opens **pipe to its stdin** (for sending requests) and **pipe from its stdout** (for reading responses)
3. Runs **MCP handshake** (initialize → initialized notification → tools/list)
4. Now has tool list in context — available for any conversation in this project

The binary reads `GITHUB_TOKEN` and `NETWORKING_DB` from environment variables set in the MCP config:

```json
{
  "mcpServers": {
    "networking-agent": {
      "command": "/Users/aitsgroup/networking-agent/target/release/networking-agent",
      "env": {
        "GITHUB_TOKEN": "ghp_...",
        "NETWORKING_DB": "/Users/aitsgroup/networking-agent.db"
      }
    }
  }
}
```

---

## 5. Full Dependency Stack

### Direct Dependencies (Cargo.toml)

| Crate | Version | Features used | Role |
|-------|---------|--------------|------|
| `rmcp` | 1.7.0 | server, transport-io, macros, schemars | MCP server framework — framing, routing, macros |
| `tokio` | 1.52.3 | full | Async runtime — threads, I/O reactor, timers |
| `reqwest` | 0.13.4 | json, query | HTTP client — GitHub + YC API |
| `sqlx` | 0.8.6 | sqlite, runtime-tokio, macros | Async SQLite queries + connection pool |
| `serde` | 1.0.228 | derive | Serialize/Deserialize trait derivation |
| `serde_json` | 1.0.150 | — | JSON value type + serialization |
| `schemars` | 1.2.1 | — | JSON Schema generation from Rust types |
| `scraper` | 0.27.0 | — | HTML parser (in dep tree, not currently called) |
| `anyhow` | 1.0.102 | — | Ergonomic `Result<T, anyhow::Error>` + context |

### Critical Transitive Dependencies

| Crate | Version | Pulled by | Role |
|-------|---------|-----------|------|
| `hyper` | — | reqwest | HTTP/1.1 + HTTP/2 framing, keep-alive |
| `tokio-rustls` | 0.26.4 | reqwest | TLS over tokio async streams |
| `aws-lc-rs` | 1.17.0 | rustls | Crypto primitives (AES, ECDH, RSA, SHA) |
| `aws-lc-sys` | 0.41.0 | aws-lc-rs | C bindings to AWS-LC crypto library |
| `webpki-root-certs` | 1.0.7 | reqwest | Mozilla's CA certificate bundle |
| `tower` | 0.5.3 | rmcp | Service/middleware abstraction layer |
| `tower-service` | 0.3.3 | rmcp | Core `Service` trait |
| `tokio-util` | 0.7.18 | rmcp, sqlx | Codec framing, stream adapters |
| `libsqlite3-sys` | — | sqlx | C FFI bindings to SQLite3 |
| `html5ever` | — | scraper | HTML5 spec-compliant parser (from Servo) |
| `selectors` | — | scraper | CSS selector engine |
| `cssparser` | 0.37.0 | selectors | CSS tokenizer |
| `ego-tree` | 0.11.0 | scraper | DOM tree arena allocator |
| `serde_core` | — | serde | Internal proc-macro infrastructure |
| `darling` | 0.23.0 | rmcp macros | Attribute macro argument parsing |
| `thiserror` | 2.0.18 | rmcp, sqlx | `#[derive(Error)]` |
| `tracing` | 0.1.44 | rmcp, tokio | Structured async logging/spans |
| `url` | 2.5.8 | reqwest | RFC 3986 URL parsing |
| `encoding_rs` | 0.8.35 | reqwest | Character encoding (UTF-8, Latin-1) |
| `bytes` | 1.11.1 | hyper, tokio | Zero-copy byte buffer |
| `flume` | 0.11.1 | sqlx | MPMC channel for DB query queue |
| `crossbeam-queue` | 0.3.12 | sqlx | Lock-free connection pool queue |
| `chrono` | 0.4.45 | sqlx | Datetime type for DB timestamps |
| `base64` | 0.22.1 | reqwest | Auth header encoding |
| `tinyvec` | 1.11.0 | html5ever | Stack-allocated small vectors |
| `unicode-normalization` | 0.1.25 | url | IDNA domain normalization |

**Total: ~150 crates in lockfile.** 9 direct → ~150 transitive because each dep brings its own deps recursively.

---

## 6. rmcp — The MCP Framework

`rmcp` is the Rust implementation of the Model Context Protocol server side.

### What the Feature Flags Enable

```toml
rmcp = { version = "1.7.0", features = ["server", "transport-io", "macros", "schemars"] }
```

| Flag | Enables |
|------|---------|
| `server` | `ServerHandler` trait, server-side JSON-RPC dispatch |
| `transport-io` | `stdio()` transport — wraps tokio `AsyncRead`/`AsyncWrite` |
| `macros` | `#[tool_router]`, `#[tool_handler]`, `#[tool(...)]` proc macros |
| `schemars` | Connects `schemars::JsonSchema` → `inputSchema` in tool manifest |

### The Three Macros — What They Generate

**`#[tool_router]`** on the `impl` block:
- Generates `Self::tool_router() -> ToolRouter<Self>`
- `ToolRouter` is a hash map: `tool_name (String) → fn(&Self, serde_json::Value) → Future<String>`
- Called once in `NetworkingServer::new()`, stored in the struct

**`#[tool(description = "...")]`** on each async method:
- Registers the method into the router under its snake_case name
- Captures the description string for the tool manifest
- Captures `schemars::JsonSchema` output from the `Parameters<T>` type

**`#[tool_handler]`** on the `ServerHandler` impl:
- Implements `fn call_tool(&self, name, args) -> Future<ToolResult>`
- Inside: looks up `name` in `tool_router`, deserializes `args` into the matching `Parameters<T>`, calls the method
- Implements `fn list_tools() -> Vec<Tool>` — iterates router, calls `json_schema()` on each param type

### Parameters\<T\> Wrapper

```rust
async fn search_github_users(
    &self,
    Parameters(params): Parameters<SearchUsersParams>,  // ← rmcp wrapper
) -> String
```

`Parameters<T>` is a newtype that implements `serde::Deserialize`. When rmcp receives a `tools/call` message, it takes `arguments` (a `serde_json::Value`) and calls `serde_json::from_value::<T>(args)` via the `Parameters<T>` impl. If deserialization fails, rmcp returns an error to Claude without calling your function.

### Server Startup Sequence

```rust
// main.rs
let server = NetworkingServer::new(pool, github_token);
let service = server.serve(stdio()).await?;  // ← starts the read loop
service.waiting().await?;                    // ← blocks until stdin closes (Claude exits)
```

`stdio()` creates a `tokio::io::stdin()` / `tokio::io::stdout()` pair. rmcp wraps these in a codec that splits on `\n`, decodes JSON, dispatches to the handler, encodes the response, writes back.

---

## 7. tokio — The Async Runtime

### What `#[tokio::main]` Expands To

```rust
// What you write:
#[tokio::main]
async fn main() -> Result<()> { ... }

// What the macro generates:
fn main() -> Result<()> {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async { /* your async main body */ })
}
```

`features = ["full"]` enables: `rt-multi-thread`, `io-util`, `net`, `time`, `sync`, `signal`, `process`, `fs`, `macros`.

### Thread Model

```
Process memory (shared)
├── NetworkingServer { tool_router, http_client, db, github_token }
│   (Arc'd internally by rmcp — safe to share across tasks)
│
├── tokio worker threads  (1 per CPU core, e.g. 8 on M2)
│   Each picks up async tasks from the global work-stealing queue
│   Tasks: MCP read loop, HTTP requests, DB queries (async path)
│
└── blocking thread pool  (separate, grows on demand, capped)
    Tasks: SQLite operations that block the OS thread
    (sqlx routes heavy I/O here via tokio::task::spawn_blocking)
```

### Why Non-Blocking Matters Here

`search_github_users` does **10 sequential GitHub API calls** — one search, then one profile fetch per result:

```rust
for u in resp.items.iter().take(10) {
    if let Ok(profile) = get_user_profile(client, token, &u.login).await {
        users.push(profile);
    }
}
```

Each `.await` is a **yield point**. While waiting for GitHub's response (network RTT ~100-200ms), the tokio executor can run other tasks. If two tool calls arrive simultaneously (unlikely over stdio, but possible in batching), they interleave rather than block each other.

Without async: 10 sequential HTTP calls × 150ms each = 1.5 seconds of blocking the whole server.

### What Runs Where

| Code path | Runs on |
|-----------|---------|
| `rmcp` stdio read loop | tokio worker thread (async) |
| `reqwest` HTTP request | tokio worker thread (async) |
| `sqlx` query (SELECT) | tokio worker thread (async) |
| `sqlx` heavy write (INSERT) | blocking thread pool (via spawn_blocking) |
| JSON serialization | tokio worker thread (synchronous, but fast) |
| `serde_json::to_string_pretty` | tokio worker thread (synchronous) |

---

## 8. reqwest — HTTP Client & TLS Stack

### Client Setup

```rust
http_client: Client::new()  // created once in NetworkingServer::new()
```

One `Client` instance, stored in the struct, reused across all tool calls. This matters because `Client` owns a **connection pool** — if you created a new `Client` per call, every request would open a new TCP connection + TLS handshake (~200ms overhead on first request to a host).

### Request Pattern (from github.rs)

```rust
let resp = client
    .get(format!("{}/search/users", GITHUB_API))         // → builds Request
    .header("Authorization", format!("Bearer {}", token)) // → adds header
    .header("User-Agent", "networking-agent/0.1")         // ← GitHub requires this
    .header("X-GitHub-Api-Version", "2022-11-28")         // ← pins API version
    .query(&[("q", &q), ("per_page", &"30".to_string())]) // → URL query params
    .send()                                                // → Future<Response>
    .await?                                                // → yields to tokio
    .json::<SearchResponse>()                             // → reads body + deserializes
    .await?;                                              // → yields again
```

Two `.await` points: one to get headers back, one to read the full body.

### Full TLS Stack (macOS)

```
reqwest 0.13
  └── uses rustls (not native-tls) based on Cargo.lock
      └── tokio-rustls 0.26.4
          └── rustls (TLS 1.2 / 1.3 implementation, pure Rust)
              └── aws-lc-rs 1.17.0  ← crypto primitives
                  └── aws-lc-sys 0.41.0  ← C bindings
                      └── AWS-LC C library (fork of BoringSSL)
                          └── AES-GCM, ChaCha20, ECDH P-256/P-384,
                              RSA-PSS, SHA-256/384/512
                              (hardware-accelerated on Apple Silicon via ARMv8 crypto extensions)
      └── webpki-root-certs 1.0.7  ← Mozilla CA bundle (hardcoded in binary)
```

**Key difference from system TLS:** rustls + aws-lc-rs brings its own CA certificates (Mozilla's bundle) and its own crypto. Doesn't touch macOS Keychain. More portable but larger binary.

### Connection Pool Behavior

- Pool per `Client` per hostname
- Keeps TCP connections alive (keep-alive header)
- After `search_users`: connection to `api.github.com` stays open → 10 profile fetches reuse it
- Pool has a max idle time — connections are recycled if not used

---

## 9. serde + schemars — Type System Bridge

This is the most architecturally interesting part: **Rust types become Claude's API contract**.

### The Derive Chain

```rust
#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct SearchUsersParams {
    /// Search query e.g. "CTO", "founder", "protocol engineer"
    pub query: String,
    /// Location filter e.g. "San Francisco", "Singapore", "NYC"
    pub location: String,
}
```

| Derive | Crate | Generated trait | What it does |
|--------|-------|----------------|--------------|
| `Serialize` | serde | `Serialize for SearchUsersParams` | struct → JSON bytes |
| `Deserialize` | serde | `Deserialize for SearchUsersParams` | JSON bytes → struct |
| `JsonSchema` | schemars | `JsonSchema for SearchUsersParams` | returns `Schema` describing the type |

### Doc Comments → Claude's Understanding

```rust
/// Search query e.g. "CTO", "founder", "protocol engineer"
pub query: String,
```

The `///` doc comment is captured by schemars at runtime via a `schemars::gen::SchemaGenerator`. It becomes `"description"` in the JSON Schema sent to Claude. **This is how Claude knows what to put in each field.** No separate API docs needed.

### What schemars Generates

```json
{
  "type": "object",
  "title": "SearchUsersParams",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query e.g. \"CTO\", \"founder\", \"protocol engineer\""
    },
    "location": {
      "type": "string",
      "description": "Location filter e.g. \"San Francisco\", \"Singapore\", \"NYC\""
    }
  },
  "required": ["query", "location"]
}
```

**Type mappings:**

| Rust type | JSON Schema |
|-----------|-------------|
| `String` | `{ "type": "string" }` |
| `Option<String>` | `{ "type": ["string", "null"] }` — not required |
| `i64` | `{ "type": "integer" }` |
| `u32` | `{ "type": "integer", "minimum": 0 }` |
| `Vec<String>` | `{ "type": "array", "items": { "type": "string" } }` |
| `bool` | `{ "type": "boolean" }` |

`Option<T>` fields are excluded from `"required"` automatically — Claude can omit them.

### SaveProspectParams — Option Fields in Action

```rust
pub struct SaveProspectParams {
    pub name: String,              // required
    pub github: Option<String>,    // optional — Claude can omit
    pub email: Option<String>,     // optional
    pub company: Option<String>,   // optional
    pub role: Option<String>,      // optional
    pub location: Option<String>,  // optional
    pub notes: Option<String>,     // optional
    pub source: Option<String>,    // optional
}
```

Claude receives this schema, understands `name` is required and everything else optional, and fills in what it knows from context.

---

## 10. sqlx — Async SQLite

### Connection Pool Init (db.rs)

```rust
SqlitePoolOptions::new()
    .max_connections(5)
    .connect("sqlite:///absolute/path/to/file.db?mode=rwc")
    .await?
```

`mode=rwc` = read + write + create if not exists. No separate migration runner — schema is `CREATE TABLE IF NOT EXISTS` run at startup. Idempotent: safe to restart the server anytime.

### Pool Mechanics

```
SqlitePool (max 5 connections)
├── Conn 1  ← available
├── Conn 2  ← available
├── Conn 3  ← in use (list_prospects query)
├── Conn 4  ← available
└── Conn 5  ← available

If all 5 busy: .execute() awaits (yields tokio task) until one frees
```

SQLite itself: concurrent reads fine, writes serialized (WAL mode). 5 connections is plenty — you rarely run >2 concurrent DB queries in this use case.

### Query Style Used

```rust
sqlx::query(
    "INSERT INTO prospects (name, github, ...) VALUES (?, ?, ...)"
)
.bind(&params.name)
.bind(&params.github)
.execute(&self.db)
.await?
```

This is **runtime-checked** SQL (not `sqlx::query!()` which is compile-time). Trade-off:
- ✅ No `DATABASE_URL` env var needed at compile time
- ✅ Simpler build setup
- ❌ SQL typos surface at runtime, not compile time

### UPSERT Pattern (save_prospect)

```sql
INSERT INTO prospects (name, github, ...) VALUES (?, ?, ...)
ON CONFLICT(github) DO UPDATE SET
    name = excluded.name,
    email = COALESCE(excluded.email, email),  -- only overwrite if new value non-null
    company = COALESCE(excluded.company, company),
    notes = COALESCE(excluded.notes, notes)
```

`UNIQUE(github)` constraint → if same GitHub handle saved twice, updates rather than erroring. `COALESCE` preserves existing values when new call doesn't provide them.

### C FFI Layer

```
sqlx (Rust async layer)
  └── sqlx-sqlite (SQLite-specific driver)
      └── libsqlite3-sys (Rust crate — FFI bindings)
          └── build.rs (runs at compile time)
              ├── Option A: link system SQLite (/usr/lib/libsqlite3.dylib on macOS)
              └── Option B: compile SQLite from source (sqlite3.c amalgamation, ~250k lines C)
                  → target/debug/build/libsqlite3-sys-.../out/bindgen.rs
                     (auto-generated unsafe Rust FFI signatures for every C function)
```

`bindgen.rs` in your target dir = ~10,000 lines of generated `extern "C" { fn sqlite3_exec(...); }` declarations. You never touch it — sqlx-sqlite calls these via the safe Rust wrapper.

### Schema

```sql
CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    github TEXT,
    email TEXT,
    company TEXT,
    role TEXT,
    location TEXT,
    notes TEXT,
    source TEXT,
    outreach_status TEXT DEFAULT 'new',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(github)
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id),
    channel TEXT NOT NULL,
    message TEXT,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 11. scraper — HTML Parser

Listed in `Cargo.toml`, not called in current code. YC tool hits `api.ycombinator.com` JSON API directly.

**When it would be used:** If you want to scrape company detail pages (`ycombinator.com/companies/stripe`), LinkedIn profiles, or any HTML source that doesn't have a JSON API.

### How it Works

```rust
use scraper::{Html, Selector};

let html = reqwest.get(url).send().await?.text().await?;
let doc = Html::parse_document(&html);
//        ^^ html5ever parser — handles malformed HTML like browsers do
//           (implicit tag closing, error recovery, full HTML5 tree construction)

let selector = Selector::parse("div.company-card h3 a").unwrap();
//             ^^ CSS selector engine — same syntax as browser DevTools
//                supports: tag, .class, #id, [attr], :first-child, > combinator, etc.

for element in doc.select(&selector) {
    let text = element.text().collect::<String>();
    let href = element.value().attr("href").unwrap_or("");
}
```

### Stack

```
scraper 0.27.0
├── html5ever  ← Mozilla Servo's HTML5 parser, handles tag soup
│   ├── tendril 0.5.0  ← string type for HTML text slices
│   └── web_atoms     ← interned atom strings (common HTML tags as enum variants)
├── ego-tree 0.11.0  ← arena-allocated tree for DOM nodes
└── selectors  ← CSS selector matching engine
    └── cssparser 0.37.0  ← CSS tokenizer/lexer
```

`html5ever` is not a regex parser. It implements the actual HTML5 parsing spec — the same algorithm browsers use. This means it handles `<table><tr><td>text</table>` (missing `</td></tr>`) the same way Chrome does.

---

## 12. MCP Wire Protocol — Real JSON Messages

All messages are newline-terminated JSON-RPC 2.0. No HTTP. No WebSocket. Just bytes on stdin/stdout.

### Full Startup Handshake

```
Claude Code                          networking-agent
    │                                        │
    │──── spawn process ─────────────────────►│ (env: GITHUB_TOKEN, NETWORKING_DB)
    │                                        │ init_pool() → SQLite ready
    │                                        │ server.serve(stdio()) → read loop starts
    │                                        │
    │  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    │    "protocolVersion":"2024-11-05",
    │    "capabilities":{"tools":{}},
    │    "clientInfo":{"name":"claude-code","version":"..."}
    │  }}\n
    │──────────────────────────────────────►│
    │                                        │
    │◄──────────────────────────────────────│
    │  {"jsonrpc":"2.0","id":1,"result":{
    │    "protocolVersion":"2024-11-05",
    │    "capabilities":{"tools":{}},
    │    "serverInfo":{"name":"networking-agent","version":"0.1.0"}
    │  }}\n
    │                                        │
    │  {"jsonrpc":"2.0","method":"notifications/initialized"}\n
    │──────────────────────────────────────►│  (no id = notification, no response expected)
    │                                        │
    │  {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n
    │──────────────────────────────────────►│
    │                                        │ calls list_tools() → iterates tool_router
    │                                        │ calls json_schema() on each param type
    │◄──────────────────────────────────────│
    │  {"jsonrpc":"2.0","id":2,"result":{"tools":[
    │    {
    │      "name":"search_github_users",
    │      "description":"Search GitHub users by role and location...",
    │      "inputSchema":{
    │        "type":"object",
    │        "properties":{
    │          "query":{"type":"string","description":"Search query e.g. \"CTO\"..."},
    │          "location":{"type":"string","description":"Location filter..."}
    │        },
    │        "required":["query","location"]
    │      }
    │    },
    │    { "name":"get_org_members", ... },
    │    { "name":"find_open_issues", ... },
    │    { "name":"get_yc_companies", ... },
    │    { "name":"search_yc_companies", ... },
    │    { "name":"save_prospect", ... },
    │    { "name":"list_prospects", ... },
    │    { "name":"update_prospect_status", ... }
    │  ]}}\n
```

### Tool Call + Response

```
    │  (user: "find protocol engineers in Singapore")
    │  (Claude decides to call search_github_users)
    │
    │  {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
    │    "name":"search_github_users",
    │    "arguments":{"query":"protocol engineer","location":"Singapore"}
    │  }}\n
    │──────────────────────────────────────►│
    │                                        │ rmcp: deserialize → Parameters<SearchUsersParams>
    │                                        │ calls search_github_users(&self, params)
    │                                        │   → github::search_users(...)
    │                                        │   → 1 search API call + 10 profile fetches
    │                                        │   → serde_json::to_string_pretty(&users)
    │◄──────────────────────────────────────│
    │  {"jsonrpc":"2.0","id":3,"result":{
    │    "content":[{"type":"text","text":"[\n  {\n    \"login\": \"alice-xyz\"..."}],
    │    "isError":false
    │  }}\n
```

### Error Response (if tool panics or returns Err)

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "Error: request error: connection refused"}],
    "isError": true
  }
}
```

Note: errors are still `result`, not `error` — MCP wraps tool errors as `isError: true` content so Claude can read and report them gracefully.

---

## 13. End-to-End Data Flow

**Scenario:** User says *"Find AI companies in Singapore from YC W25, save the top 3 to my pipeline"*

```
Step 1 — Claude reasons
  Tool available: search_yc_companies(query, location)
  Decision: call with query="AI", location="Singapore"

Step 2 — MCP call hits stdin
  {"jsonrpc":"2.0","id":4,"method":"tools/call",
   "params":{"name":"search_yc_companies","arguments":{"query":"AI","location":"Singapore"}}}

Step 3 — rmcp dispatch
  Reads line from stdin
  Parses JSON-RPC frame
  Matches "search_yc_companies" in ToolRouter
  Calls serde_json::from_value::<YCSearchParams>(arguments)
  → YCSearchParams { query: "AI", location: "Singapore" }
  Calls NetworkingServer::search_yc_companies(&self, Parameters(params))

Step 4 — yc::search_yc_companies runs
  Loop: page 1..10 (max)
    reqwest GET https://api.ycombinator.com/v0.1/companies
      ?limit=50&page=1&q=AI
    → TLS: tokio-rustls + aws-lc-rs crypto
    → Response body: {"companies": [...]}
    → serde_json::from_str::<YCResponse>(body)
    Filter: keep companies where locations/regions contain "singapore" (case-insensitive)
    Map: YCApiCompany → YCCompany (rename fields, flatten Options)
    If >= 30 results: break early

  Returns Vec<YCCompany>

Step 5 — Result serialized + returned
  serde_json::to_string_pretty(&companies) → JSON string
  rmcp wraps: {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"..."}],"isError":false}}
  Written to stdout

Step 6 — Claude reads result
  Sees 3 relevant companies: "AI Shield", "DataFlow AI", "SingaBot"
  Decides: call save_prospect 3 times

Step 7 — save_prospect × 3 (sequential)
  Each call:
    rmcp deserializes SaveProspectParams
    sqlx::query("INSERT INTO prospects ... ON CONFLICT(github) DO UPDATE ...")
      .bind(name).bind(github)...
      .execute(&self.db).await
    → SqlitePool: acquire connection (1 of 5)
    → libsqlite3-sys C FFI: sqlite3_prepare_v2 + sqlite3_step
    → WAL write to ~/networking-agent.db
    → Returns last_insert_rowid()
  Returns: "Saved prospect 'AI Shield' (row id: 1)"

Step 8 — Claude reports to user
  "Found 3 AI companies in Singapore from YC W25 and saved them to your pipeline:
   1. AI Shield (row 1) — security AI
   2. DataFlow AI (row 2) — data infrastructure
   3. SingaBot (row 3) — workflow automation"

Total: 10 HTTP calls (paginated YC API) + 3 SQLite writes
Latency: ~2-3 seconds (dominated by network)
Concurrent: each YC page request awaits in sequence (could be parallelized with tokio::join!)
```

---

## 14. Design Decisions Explained

### Why stdio transport instead of HTTP/SSE?

- **Zero infrastructure** — no port to open, no firewall rules, no server to keep running
- Claude Code spawns/kills the process automatically
- Process lifecycle tied to conversation — clean shutdown
- SSE transport useful if multiple clients need to connect simultaneously (not the case here)

### Why one `Client` stored in struct?

```rust
pub struct NetworkingServer {
    http_client: Client,  // ← one instance, pooled connections
```

Creating `Client::new()` inside each tool call would discard the connection pool. The stored `Client` keeps TCP connections to `api.github.com` alive between calls — the 10 profile fetches in `search_users` all reuse the same connection.

### Why `sqlx::query()` instead of `sqlx::query!()`?

`query!()` macro requires `DATABASE_URL` set at compile time and runs the query against an actual DB during compilation. Simpler dev setup with runtime queries. Acceptable here since SQL is straightforward and tested manually.

### Why sequential profile fetches instead of concurrent?

```rust
for u in resp.items.iter().take(10) {
    if let Ok(profile) = get_user_profile(...).await { // ← sequential
        users.push(profile);
    }
}
```

Could be `futures::join_all(...)` for ~10x speedup. Not done — likely GitHub rate limiting concern (secondary rate limits on concurrent requests). Sequential is safer and still non-blocking (tokio yields between each).

### Why `anyhow::Result` everywhere?

`anyhow::Result<T>` = `Result<T, anyhow::Error>` where `anyhow::Error` wraps any `std::error::Error`. This means you can `?` across different error types (reqwest errors, sqlx errors, serde errors) without defining custom error enums. Appropriate for an application (vs. a library where you'd want typed errors for callers).

### Why `scraper` in Cargo.toml but unused?

Dep was added for planned HTML scraping of company detail pages. Not yet implemented — YC JSON API is sufficient. Should be removed from `Cargo.toml` to reduce compile time and binary size if it won't be used.

---

## 15. Mental Model Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER STACK                                   │
│                                                                  │
│  Claude (LLM)                                                    │
│    ↕ JSON-RPC 2.0 / newline-delimited / stdio                   │
│  rmcp  ← handles framing, routing, schema generation            │
│    ↕ Rust async traits (tower::Service)                         │
│  tokio ← runs everything concurrently on N worker threads       │
│    ↕                          ↕                                 │
│  reqwest + rustls          sqlx + libsqlite3-sys                │
│  (HTTP + TLS)              (async DB + C FFI)                   │
│    ↕                          ↕                                 │
│  api.github.com            ~/networking-agent.db                │
│  api.ycombinator.com       (SQLite file)                        │
└─────────────────────────────────────────────────────────────────┘

COMPILE TIME:
  serde derive  → generates Serialize/Deserialize impls
  schemars derive → generates json_schema() fn
  rmcp macros   → generates ToolRouter + ServerHandler impl
  tokio macro   → generates multi-thread runtime setup

RUNTIME:
  rmcp reads stdin → deserializes → dispatches
  serde_json::from_value → typed params
  schemars::json_schema() → tool manifest for Claude
  reqwest → HTTP over TLS → external APIs
  sqlx → async SQL → C FFI → SQLite file
  serde_json::to_string_pretty → result back to rmcp → stdout
```

**One sentence:** The `#[tool_router]` + `#[derive(JsonSchema)]` combo is the core insight — it makes a Rust async method callable by Claude with zero glue code, because schemars turns your Rust types into Claude's API contract automatically.

---

*Source code: `/Users/aitsgroup/networking-agent/src/`*
*Last updated: 2026-06-08*
