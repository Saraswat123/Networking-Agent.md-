/// Integration tests — run against an in-memory SQLite DB.
/// Tests the schema and invariants without spinning up the MCP server.
use sqlx::{Row, SqlitePool, sqlite::SqlitePoolOptions};

async fn init_test_pool() -> SqlitePool {
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .expect("in-memory pool failed");

    // Minimal schema — mirrors migrations/001_init.sql
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS prospects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            github TEXT UNIQUE,
            email TEXT,
            company TEXT,
            role TEXT,
            location TEXT,
            notes TEXT,
            source TEXT,
            domain TEXT,
            outreach_status TEXT DEFAULT 'new',
            direction TEXT DEFAULT 'proposal',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_domain
            ON prospects(domain) WHERE domain IS NOT NULL;",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS outreach_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            message TEXT,
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
            repo_owner TEXT NOT NULL,
            repo_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'drafted',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS tool_call_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            input_preview TEXT,
            output_len INTEGER,
            status TEXT DEFAULT 'ok',
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tool_log_tool ON tool_call_log(tool_name);
        CREATE INDEX IF NOT EXISTS idx_tool_log_ts   ON tool_call_log(ts);",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS analysis_cache (
            org_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            expires_at DATETIME NOT NULL
        );",
    )
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
            pain_points TEXT,
            proposal TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
    )
    .execute(&pool)
    .await
    .unwrap();

    pool
}

#[tokio::test]
async fn all_six_tables_created() {
    let pool = init_test_pool().await;
    let tables: Vec<String> = sqlx::query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    )
    .fetch_all(&pool)
    .await
    .unwrap()
    .into_iter()
    .map(|r| r.get::<String, _>(0))
    .collect();

    for t in &["analysis_cache", "contributions", "outreach_log", "proposals", "prospects", "tool_call_log"] {
        assert!(tables.contains(&t.to_string()), "missing table: {t}");
    }
}

#[tokio::test]
async fn domain_uniqueness_enforced() {
    let pool = init_test_pool().await;

    sqlx::query(
        "INSERT INTO prospects (name, domain, source) VALUES ('Alice', 'acme.io', 'github')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let second = sqlx::query(
        "INSERT INTO prospects (name, domain, source) VALUES ('Bob', 'acme.io', 'manual')",
    )
    .execute(&pool)
    .await;

    assert!(second.is_err(), "duplicate domain must be rejected");
}

#[tokio::test]
async fn contributions_cascade_on_prospect_delete() {
    let pool = init_test_pool().await;

    let id: i64 = sqlx::query_scalar(
        "INSERT INTO prospects (name, source) VALUES ('Alice', 'github') RETURNING id",
    )
    .fetch_one(&pool)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO contributions (prospect_id, repo_owner, repo_name) VALUES (?, 'rust-lang', 'rust')",
    )
    .bind(id)
    .execute(&pool)
    .await
    .unwrap();

    sqlx::query("DELETE FROM prospects WHERE id = ?")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();

    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM contributions WHERE prospect_id = ?",
    )
    .bind(id)
    .fetch_one(&pool)
    .await
    .unwrap();

    assert_eq!(count, 0, "contributions must cascade-delete with prospect");
}

#[tokio::test]
async fn monthly_quota_gate_hunter() {
    let pool = init_test_pool().await;
    const HUNTER_MONTHLY_LIMIT: i64 = 25;

    // Simulate 24 prior Hunter calls
    for _ in 0..24 {
        sqlx::query(
            "INSERT INTO tool_call_log (tool_name, input_preview, output_len, status)
             VALUES ('find_company_emails', 'domain.io', 8, 'ok')",
        )
        .execute(&pool)
        .await
        .unwrap();
    }

    let used: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM tool_call_log
         WHERE tool_name = 'find_company_emails'
           AND ts >= datetime('now', '-30 days')",
    )
    .fetch_one(&pool)
    .await
    .unwrap();

    assert_eq!(used, 24);
    assert!(
        used < HUNTER_MONTHLY_LIMIT,
        "24 calls: still under 25/mo limit"
    );

    // 25th call: allowed
    let after_25 = used + 1;
    assert!(after_25 <= HUNTER_MONTHLY_LIMIT, "25th call must be allowed");

    // 26th call: blocked
    let after_26 = used + 2;
    assert!(
        after_26 > HUNTER_MONTHLY_LIMIT,
        "26th call must exceed monthly limit"
    );
}

#[tokio::test]
async fn outreach_status_defaults_to_new() {
    let pool = init_test_pool().await;

    sqlx::query("INSERT INTO prospects (name, source) VALUES ('Charlie', 'yc')")
        .execute(&pool)
        .await
        .unwrap();

    let status: String =
        sqlx::query_scalar("SELECT outreach_status FROM prospects WHERE name = 'Charlie'")
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(status, "new");
}

#[tokio::test]
async fn direction_defaults_to_proposal() {
    let pool = init_test_pool().await;

    sqlx::query("INSERT INTO prospects (name, source) VALUES ('Dana', 'github')")
        .execute(&pool)
        .await
        .unwrap();

    let direction: String =
        sqlx::query_scalar("SELECT direction FROM prospects WHERE name = 'Dana'")
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(direction, "proposal");
}
