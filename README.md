# Networking Agent

A Rust MCP (Model Context Protocol) server that builds a global prospect pipeline — finding CEOs, CTOs, VCs, and founders across GitHub, YC, and other sources. Runs locally, integrates directly with Claude Code. No API billing — works with Claude Premium.

---

## Table of Contents

- [What It Does](#what-it-does)
- [Architecture](#architecture)
- [Full Technical Stack](#full-technical-stack)
- [Dependency Deep Dive](#dependency-deep-dive)
- [MCP Protocol Layer](#mcp-protocol-layer)
- [Async Runtime](#async-runtime)
- [HTTP Networking Stack](#http-networking-stack)
- [Database Layer](#database-layer)
- [Tool Registration System](#tool-registration-system)
- [Data Flow](#data-flow-end-to-end)
- [Setup](#setup)
- [Docker](#docker)
- [Tools Reference](#tools-reference)
- [Database Schema](#database-schema)
- [Usage Examples](#usage-examples)

---

## What It Does

- **Search GitHub** for engineers and founders by role + location (global — SF, NYC, Singapore, London, Berlin, Tokyo, etc.)
- **Find org members** at target companies on GitHub
- **Discover open issues** in target repos (warm entry points for contribution)
- **Browse YC companies** by batch (W25, S24, W24…) or keyword + location
- **Track prospects** in local SQLite pipeline — status from `new` → `meeting_scheduled`

---

## Architecture

```
┌─────────────────────────────────────────┐
│           Claude Code (Premium)          │
│         claude.ai/code or CLI           │
└──────────────────┬──────────────────────┘
                   │
                   │  JSON-RPC 2.0 over stdin/stdout
                   │  (MCP Protocol — modelcontextprotocol.io)
                   │
┌──────────────────▼──────────────────────┐
│         networking-agent (Rust binary)   │
│                                          │
│  ┌────────────┐   ┌───────────────────┐ │
│  │  rmcp 1.7  │   │  tool_router macro│ │
│  │ MCP Server │──▶│  dispatches calls │ │
│  └─────┬──────┘   └───────────────────┘ │
│        │                                 │
│  ┌─────▼──────────────────────────────┐ │
│  │         NetworkingServer struct     │ │
│  │  http_client │ db pool │ gh_token  │ │
│  └──────┬───────────────┬─────────────┘ │
│         │               │               │
│  ┌──────▼──────┐ ┌──────▼──────┐       │
│  │ tools/      │ │  sqlx pool  │       │
│  │ github.rs   │ │  SQLite DB  │       │
│  │ yc.rs       │ └─────────────┘       │
│  └──────┬──────┘                       │
└─────────┼────────────────────────────--┘
          │
          │  HTTPS (TLS 1.3 via rustls)
          │
┌─────────▼──────────────────────────────┐
│  External APIs                          │
│  ├── api.github.com  (REST API v3)      │
│  └── api.ycombinator.com/v0.1          │
└────────────────────────────────────────┘
```

---

## Full Technical Stack

| Layer | Library | Version | Role |
|-------|---------|---------|------|
| **MCP Protocol** | `rmcp` | 1.7.0 | JSON-RPC 2.0 server, tool routing |
| **MCP Macros** | `rmcp-macros` | 1.7.0 | `#[tool]`, `#[tool_router]`, `#[tool_handler]` proc macros |
| **Async Runtime** | `tokio` | 1.52.3 | Multi-threaded async executor |
| **HTTP Client** | `reqwest` | 0.13.4 | Async HTTP/1.1 + HTTP/2 client |
| **HTTP Engine** | `hyper` | 1.x | Low-level HTTP protocol |
| **TLS** | `rustls` | 0.23 | Pure-Rust TLS 1.2/1.3 (no OpenSSL) |
| **Crypto** | `aws-lc-rs` | 1.x | FIPS-compatible crypto primitives |
| **Database** | `sqlx` | 0.8.6 | Async SQLite with compile-time queries |
| **SQLite C binding** | `libsqlite3-sys` | 0.30 | Bundled C SQLite3 |
| **Serialization** | `serde` | 1.0.228 | Derive macros for Serialize/Deserialize |
| **JSON** | `serde_json` | 1.0.150 | JSON encode/decode, Value type |
| **JSON Schema** | `schemars` | 1.2.1 | Auto-generate JSON Schema from Rust types |
| **HTML Parsing** | `scraper` | 0.27.0 | CSS selector engine (html5ever backend) |
| **Error Handling** | `anyhow` | 1.0.102 | Ergonomic error propagation with `?` |

### Transitive Key Dependencies

| Library | Version | Why It Exists |
|---------|---------|--------------|
| `hyper` | 1.10 | HTTP engine under reqwest |
| `tokio-rustls` | 0.26 | Bridges tokio async I/O + rustls TLS |
| `h2` | 0.4 | HTTP/2 support inside hyper |
| `tower` | 0.5 | Middleware layer for hyper/tower-http |
| `futures` | 0.3 | Async combinators (`join!`, `select!`, etc.) |
| `html5ever` | 0.39 | HTML5 spec-compliant parser (used by scraper) |
| `ego-tree` | 0.11 | Arena-allocated tree for DOM (used by scraper) |
| `url` | 2.5 | URL parsing and validation |
| `percent-encoding` | 2.3 | URL encoding for query params |
| `base64` | 0.22 | Used in auth headers |
| `ring` / `aws-lc-rs` | — | Crypto for TLS (AES, SHA, ECDSA, RSA) |

---

## Dependency Deep Dive

### `rmcp = "1.7.0"` — Official Rust MCP SDK

**Features enabled:** `server`, `transport-io`, `macros`, `schemars`

```
rmcp
├── server     → ServerHandler trait, serve() method
├── transport-io → stdio() transport (reads stdin, writes stdout)
├── macros     → #[tool], #[tool_router], #[tool_handler] proc macros
└── schemars   → JSON Schema generation for tool input parameters
```

**What it provides:**
- `rmcp::ServiceExt` — `.serve(transport)` method on any `ServerHandler`
- `rmcp::transport::stdio()` — returns a `(AsyncRead, AsyncWrite)` pair bound to stdin/stdout
- `rmcp::handler::server::router::tool::ToolRouter<T>` — routes tool name strings to async fn calls
- `rmcp::handler::server::wrapper::Parameters<T>` — wrapper that deserializes JSON tool args into `T`
- `rmcp::ServerHandler` trait — MCP server lifecycle (initialize, list tools, call tool)

**Wire protocol handled by rmcp:**
```
MCP Initialize → negotiate protocol version, advertise capabilities
MCP tools/list → return all registered tools with their JSON schemas
MCP tools/call → deserialize args, call matching fn, return result
```

---

### `tokio = "1.52.3"` — Async Runtime

**Features enabled:** `full` (includes rt-multi-thread, net, fs, time, macros, sync, io-util)

```rust
#[tokio::main]           // transforms main() into async, spins up multi-thread scheduler
async fn main() -> Result<()> {
    // everything here is non-blocking
}
```

**Key components used:**
| Component | Usage |
|-----------|-------|
| `tokio::runtime` | Multi-threaded work-stealing scheduler |
| `tokio::net` | Async TCP sockets (used by reqwest/hyper) |
| `tokio::io` | AsyncRead/AsyncWrite traits for stdio transport |
| `tokio::sync` | Mutex, RwLock for shared state |
| `tokio::time` | Timeouts on HTTP requests |
| `tokio::task` | Spawn concurrent futures |

**Why multi-threaded:** GitHub API fetches profiles one-by-one; tokio can interleave these concurrently on thread pool without blocking.

---

### `reqwest = "0.13.4"` — HTTP Client

**Features enabled:** `json`, `query`

```
reqwest::Client
├── json    → .json::<T>() to deserialize response body
├── query   → .query(&[("key","val")]) to append URL query params
└── default → rustls TLS (no OpenSSL dependency)
```

**Internal stack:**
```
reqwest::Client
  └── hyper::Client (HTTP/1.1 + HTTP/2)
       └── tokio-rustls connector
            └── rustls::ClientConfig
                 └── aws-lc-rs (crypto: AES-GCM, SHA-256, ECDH)
                      └── system trust store (ca-certificates on Linux)
```

**TLS handshake flow per GitHub API call:**
```
1. DNS resolve api.github.com  (tokio async resolver)
2. TCP connect port 443         (tokio::net::TcpStream)
3. TLS ClientHello              (rustls negotiates TLS 1.3)
4. Certificate verify           (rustls-platform-verifier → system trust store)
5. ECDH key exchange            (aws-lc-rs)
6. HTTP/2 or HTTP/1.1 request   (hyper)
7. Response stream              (reqwest deserializes JSON via serde_json)
```

**Connection pooling:** `reqwest::Client` is cloned (not recreated) per tool call — pool reuses open TLS connections across multiple GitHub API requests in one tool invocation.

---

### `serde = "1.0.228"` + `serde_json = "1.0.150"` — Serialization

**Feature enabled:** `derive`

```rust
// Input: GitHub API JSON bytes
// Derive macro generates Deserialize impl at compile time
#[derive(Deserialize)]
struct GitHubUser {
    login: String,
    email: Option<String>,   // null → None, string → Some(String)
    company: Option<String>,
    // ...
}

// serde_json parses without intermediate HashMap — goes directly to struct
let user: GitHubUser = response.json::<GitHubUser>().await?;

// Output: format struct back to JSON string for Claude
serde_json::to_string_pretty(&user) // → indented JSON string
```

**Zero-copy parsing:** serde_json's `from_slice` can reference bytes in-place for string fields (via `&str` borrows), though we use owned `String` for simplicity.

---

### `schemars = "1.2.1"` — JSON Schema Generation

**Feature enabled:** `derive`

Schemars generates JSON Schema 2020-12 from Rust types at compile time. rmcp uses this to tell Claude what parameters each tool expects.

```rust
#[derive(JsonSchema, Deserialize, Serialize)]
pub struct SearchUsersParams {
    /// Search query e.g. "CTO", "founder", "protocol engineer"
    pub query: String,       // → { "type": "string", "description": "..." }
    /// Location filter e.g. "San Francisco", "Singapore", "NYC"
    pub location: String,    // → { "type": "string", "description": "..." }
}
```

**Generated schema Claude sees:**
```json
{
  "type": "object",
  "properties": {
    "query":    { "type": "string", "description": "Search query..." },
    "location": { "type": "string", "description": "Location filter..." }
  },
  "required": ["query", "location"]
}
```

**`Option<T>` fields** → schema gets `"type": ["string", "null"]` automatically.

---

### `sqlx = "0.8.6"` — Async Database

**Features enabled:** `sqlite`, `runtime-tokio`, `macros`

```
sqlx
├── sqlite          → SQLitePool, SQLite query execution
├── runtime-tokio   → async queries run on tokio runtime
└── macros          → sqlx::query!() compile-time query checking (optional)
```

**Connection pool lifecycle:**
```rust
SqlitePoolOptions::new()
    .max_connections(5)          // max 5 concurrent DB connections
    .connect("sqlite://path?mode=rwc")  // rwc = read/write/create
    .await?
// → returns SqlitePool (cloneable handle, shared across tool calls)
```

**Query execution (async, non-blocking):**
```rust
sqlx::query("INSERT INTO prospects (...) VALUES (?, ?, ?)")
    .bind(&name)     // parameterized — no SQL injection possible
    .bind(&github)
    .bind(&email)
    .execute(&self.db)   // &SqlitePool
    .await?
// → tokio threadpool runs SQLite C library, yields back to async runtime while waiting
```

**C binding:** `libsqlite3-sys` bundles SQLite 3.x source and compiles it during `cargo build` — no system SQLite required.

---

### `scraper = "0.27.0"` — HTML Parsing

**Purpose:** CSS selector engine for scraping HTML pages (backup for sites with no API).

**Internal stack:**
```
scraper
├── html5ever  → HTML5 spec-compliant tokenizer + tree builder
├── ego-tree   → arena-allocated DOM tree
└── selectors  → CSS selector parsing + matching (Servo's engine)
```

```rust
let document = Html::parse_document(&html_string);
let selector = Selector::parse("div.company-name").unwrap();
for element in document.select(&selector) {
    let text = element.text().collect::<String>();
}
```

Currently used as fallback. YC now served via `api.ycombinator.com/v0.1` (JSON API — no scraping needed).

---

### `anyhow = "1.0.102"` — Error Handling

Provides `anyhow::Result<T>` (= `Result<T, anyhow::Error>`) — any `std::error::Error` type can be propagated with `?`.

```rust
pub async fn get_user_profile(client: &Client, login: &str) -> Result<GitHubUser> {
    let user = client.get(url)
        .send().await?          // reqwest::Error auto-converted to anyhow::Error
        .json::<GitHubUser>().await?;  // serde_json::Error auto-converted
    Ok(user)
}
```

No manual `match` or `map_err` needed for standard error types.

---

## MCP Protocol Layer

**Protocol:** Model Context Protocol v2024-11-05 (JSON-RPC 2.0 subset)

**Transport:** stdio (stdin → server reads, server writes → stdout)

**Message flow:**

```
┌─ Claude Code ─────────────────────────────────────────────────────┐

1. INITIALIZE (handshake)
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2024-11-05","capabilities":{},
              "clientInfo":{"name":"claude-code","version":"x.x"}}}

← {"jsonrpc":"2.0","id":1,"result":
    {"protocolVersion":"2024-11-05",
     "capabilities":{"tools":{}},
     "serverInfo":{"name":"rmcp","version":"1.7.0"}}}

2. LIST TOOLS (discovery)
→ {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}

← {"jsonrpc":"2.0","id":2,"result":{"tools":[
    {"name":"search_github_users",
     "description":"Search GitHub users by role and location...",
     "inputSchema":{"type":"object","properties":{...}}},
    ...7 tools total
  ]}}

3. CALL TOOL (execution)
→ {"jsonrpc":"2.0","id":3,"method":"tools/call",
    "params":{"name":"search_github_users",
              "arguments":{"query":"CTO","location":"Singapore"}}}

← {"jsonrpc":"2.0","id":3,"result":
    {"content":[{"type":"text","text":"[{...json prospects...}]"}]}}

└───────────────────────────────────────────────────────────────────┘
```

**rmcp dispatches tool calls:**
```
"search_github_users" string
        │
        ▼ ToolRouter<NetworkingServer>
NetworkingServer::search_github_users()
        │
        ▼ Parameters<SearchUsersParams>
serde_json deserialize {"query":"CTO","location":"Singapore"}
        │
        ▼
github::search_users(&self.http_client, &self.github_token, "CTO", "Singapore")
        │
        ▼
String (JSON) → rmcp wraps in content block → stdout
```

---

## Async Runtime

```
tokio multi-thread runtime
│
├── Thread 0 (main)    → MCP message loop (stdio read/write)
├── Thread 1           → HTTP connection pool / TLS I/O
├── Thread 2           → SQLite blocking calls (via spawn_blocking)
└── Thread N           → more HTTP requests (concurrent profile fetches)
```

**Key: nothing blocks.** When reqwest sends an HTTP request:
1. tokio hands the socket to the OS (epoll/kqueue)
2. Current thread picks up another task
3. OS notifies when data arrives
4. tokio wakes the waiting future

Result: 10 GitHub profile fetches happen concurrently on a small thread pool, not sequentially.

---

## HTTP Networking Stack

```
reqwest::Client::get(url)
    │
    ├── .header()       → HashMap<HeaderName, HeaderValue>
    ├── .query()        → serialized to URL query string via serde_urlencoded
    └── .send()
         │
         ▼
    hyper::Client
         │
         ├── HTTP/2 (preferred, negotiated via ALPN in TLS handshake)
         │   └── h2 crate — frame multiplexing, flow control, HPACK headers
         │
         └── HTTP/1.1 fallback
              └── httparse — response parser
         │
         ▼
    tokio-rustls (AsyncRead + AsyncWrite adapter)
         │
         ├── rustls::ClientConnection
         │   ├── TLS 1.3 (preferred): ECDH-P256 key exchange, AES-256-GCM AEAD
         │   └── TLS 1.2 fallback: RSA/ECDSA cert verify
         │
         └── aws-lc-rs (crypto)
              ├── AES-256-GCM   → record encryption
              ├── SHA-256/384   → HMAC, cert fingerprint
              ├── ECDH P-256    → key exchange
              └── RSA/ECDSA     → certificate signature verify
         │
         ▼
    tokio::net::TcpStream → OS TCP socket → api.github.com:443
```

---

## Database Layer

```
SqlitePool (5 connections max)
    │
    ├── sqlx::query() → parameterized SQL → libsqlite3-sys (C FFI)
    │                                              │
    │                                     SQLite C library 3.x
    │                                     (bundled, compiled via cc crate)
    │                                              │
    └── .await?  ← tokio::task::spawn_blocking ←──┘
                   (SQLite is sync C — offloaded to blocking threadpool)
```

**Tables:**
```
prospects      → main pipeline (id, name, github, email, company, role,
                                location, notes, source, outreach_status,
                                created_at, updated_at)

outreach_log   → every touch recorded (prospect_id, channel, message, sent_at)
```

**Indexes:**
```sql
idx_prospects_status    ON prospects(outreach_status)   -- filter by pipeline stage
idx_prospects_location  ON prospects(location)          -- filter by city/country
idx_prospects_company   ON prospects(company)           -- filter by company
idx_outreach_prospect   ON outreach_log(prospect_id)    -- join prospects → log
```

**Trigger:**
```sql
-- Auto-sets updated_at on every prospect UPDATE
CREATE TRIGGER prospects_updated_at
    AFTER UPDATE ON prospects
BEGIN
    UPDATE prospects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
```

---

## Tool Registration System

**Three macros work together:**

```rust
// 1. #[tool_router] — generates ToolRouter<Self> + dispatch table
#[tool_router]
impl NetworkingServer {

    // 2. #[tool(...)] — registers fn as MCP tool, generates JSON Schema from params
    #[tool(description = "Search GitHub users by role and location...")]
    async fn search_github_users(
        &self,
        Parameters(params): Parameters<SearchUsersParams>,
        // Parameters<T> = rmcp wrapper that deserializes JSON args → T
    ) -> String {
        // return value becomes the tool result text content
    }
}

// 3. #[tool_handler] — implements ServerHandler trait, wires ToolRouter
#[tool_handler]
impl rmcp::ServerHandler for NetworkingServer {}
```

**What the proc macros generate (simplified):**
```rust
// Generated by #[tool_router]:
impl NetworkingServer {
    fn tool_router() -> ToolRouter<Self> {
        ToolRouter::new()
            .add_tool("search_github_users", Self::search_github_users, schema)
            .add_tool("get_org_members", Self::get_org_members, schema)
            // ... all tools
    }
}

// Generated by #[tool_handler]:
impl ServerHandler for NetworkingServer {
    async fn call_tool(&self, name: &str, args: JsonObject) -> CallToolResult {
        self.tool_router.call(self, name, args).await
    }
    fn list_tools(&self) -> Vec<Tool> {
        self.tool_router.list()
    }
}
```

---

## Data Flow: End-to-End

```
User → Claude Code: "Find CTOs in Singapore, save top 3"

Claude Code → networking-agent stdin:
  tools/call search_github_users {"query":"CTO","location":"Singapore"}

networking-agent:
  1. serde_json deserialize args → SearchUsersParams { query, location }
  2. github::search_users(client, token, "CTO", "Singapore")
     a. reqwest GET api.github.com/search/users?q=CTO+location:Singapore
        → TLS handshake (rustls) → HTTP/2 request (hyper)
        → response body → serde_json → SearchResponse { items: Vec<SearchUser> }
     b. For each login (up to 10):
        reqwest GET api.github.com/users/{login}
        → GitHubUser { login, name, email, company, location, ... }
  3. serde_json::to_string_pretty(&users) → JSON string

networking-agent → Claude Code stdout: tool result (JSON)

Claude picks top 3, calls save_prospect 3 times:
  tools/call save_prospect {"name":"...", "github":"...", "company":"..."}
  → sqlx INSERT INTO prospects ... → SQLite file on disk

Claude → User: "Saved 3 CTOs from Singapore:
  1. @awalias — company, bio, github URL
  2. ...
  Next step: find their open repos to contribute to"
```

---

## Setup

### Prerequisites

- Rust 1.70+ (`rustup update`)
- Claude Code with Premium subscription
- GitHub Personal Access Token

```bash
# Get GitHub token: github.com/settings/tokens
# Scopes needed: read:user, read:org (read-only, no write access)
```

### Build from Source

```bash
git clone https://github.com/Saraswat123/Networking-Agent.md-.git
cd Networking-Agent.md-

cp .env.example .env
# Edit .env → add your GITHUB_TOKEN

cargo build --release
# binary: ./target/release/networking-agent
```

### Register with Claude Code

```bash
claude mcp add networking-agent \
  -s user \
  -e GITHUB_TOKEN="ghp_yourtoken" \
  -e NETWORKING_DB="$HOME/networking-agent.db" \
  -- ./target/release/networking-agent
```

Restart Claude Code. All 7 tools are now available in every session.

---

## Docker

### Build and Run

```bash
docker build -t networking-agent .

docker run --rm \
  --env-file .env \
  -v "$HOME/networking-agent.db:/data/networking.db" \
  -e NETWORKING_DB=/data/networking.db \
  networking-agent
```

### Docker Compose

```bash
docker compose up
```

**Dockerfile stages:**
1. `rust:1.93-slim` — compiles release binary (dependency layer cached separately)
2. `debian:bookworm-slim` — runtime only (adds ca-certificates for TLS, copies binary)

Final image size: ~15 MB (vs 1.5 GB full Rust image).

---

## Tools Reference

| Tool | Parameters | Returns |
|------|-----------|---------|
| `search_github_users` | `query: String`, `location: String` | JSON array of user profiles |
| `get_org_members` | `org: String` | JSON array of org member profiles |
| `find_open_issues` | `owner: String`, `repo: String` | JSON array of open issues |
| `get_yc_companies` | `batch: String` | JSON array of YC companies |
| `search_yc_companies` | `query: String`, `location: String` | JSON array of YC companies |
| `save_prospect` | `name`, `github?`, `email?`, `company?`, `role?`, `location?`, `notes?`, `source?` | Confirmation string |
| `list_prospects` | _(none)_ | JSON array of all prospects |
| `update_prospect_status` | `id: i64`, `status: String` | Confirmation string |

**Outreach status values:**
`new` → `researched` → `github_engaged` → `x_engaged` → `emailed` → `replied` → `meeting_scheduled`

---

## Database Schema

```sql
-- migrations/001_init.sql

CREATE TABLE prospects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    github          TEXT UNIQUE,      -- dedup key
    email           TEXT,
    company         TEXT,
    role            TEXT,             -- CTO / founder / VC / engineer
    location        TEXT,
    notes           TEXT,
    source          TEXT,             -- github | yc | x | linkedin | manual
    outreach_status TEXT DEFAULT 'new',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE outreach_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,        -- github | email | x | discord | linkedin
    message     TEXT,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Usage Examples

```
"Find CTOs in Singapore on GitHub and save top 5 as prospects"

"Get all W25 YC companies in fintech and save the founders"

"Find open issues in modelcontextprotocol/rust-sdk"

"Search for AI infra founders in New York on GitHub"

"List all prospects with status 'github_engaged'"

"Update prospect 3 status to emailed"

"Find engineers at the Paradigm org on GitHub"
```

---

## Project Structure

```
networking-agent/
├── src/
│   ├── main.rs           # Entry point — init db, register server, run stdio MCP loop
│   ├── server.rs         # NetworkingServer struct + all 7 tool definitions
│   ├── db.rs             # SqlitePool init, schema creation
│   └── tools/
│       ├── mod.rs        # Module declarations
│       ├── github.rs     # GitHub REST API v3 calls (search, org, issues, profiles)
│       └── yc.rs         # YC public API (batch fetch, keyword+location search)
├── migrations/
│   └── 001_init.sql      # Full schema: tables, indexes, trigger
├── Dockerfile            # Multi-stage: rust:1.93-slim → debian:bookworm-slim
├── docker-compose.yml    # Persistent db volume, stdio-compatible config
├── .env.example          # GITHUB_TOKEN + NETWORKING_DB template
├── CLAUDE.md             # Agent workflow instructions for Claude
├── Cargo.toml            # Dependencies + feature flags
└── Cargo.lock            # Locked dependency versions (239 crates total)
```

---

## Contributing

```bash
git checkout -b feature/your-feature
cargo clippy      # must pass
cargo build       # must compile
git push origin feature/your-feature
# open PR
```

No secrets in commits. `.env` and `*.db` files are gitignored.

---

## License

MIT
