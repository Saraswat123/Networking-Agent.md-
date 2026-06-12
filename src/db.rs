use anyhow::Result;
use sqlx::{SqlitePool, sqlite::SqlitePoolOptions};

pub async fn init_pool(db_path: &str) -> Result<SqlitePool> {
    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect(&format!("sqlite://{}?mode=rwc", db_path))
        .await?;

    sqlx::query(
        r#"
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
        "#,
    )
    .execute(&pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS outreach_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER REFERENCES prospects(id),
            channel TEXT NOT NULL,
            message TEXT,
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        "#,
    )
    .execute(&pool)
    .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS tool_call_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name           TEXT NOT NULL,
            input_preview       TEXT,
            output_len          INTEGER,
            output_fingerprint  INTEGER,
            duration_ms         INTEGER,
            status              TEXT DEFAULT 'ok',
            pii_detected        TEXT DEFAULT '',
            ts                  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tool_log_tool ON tool_call_log(tool_name);
        CREATE INDEX IF NOT EXISTS idx_tool_log_ts   ON tool_call_log(ts);
        "#,
    )
    .execute(&pool)
    .await?;

    Ok(pool)
}
