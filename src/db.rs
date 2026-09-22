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
        CREATE TABLE IF NOT EXISTS contributions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id         INTEGER REFERENCES prospects(id),
            repo_owner          TEXT NOT NULL,
            repo_name           TEXT NOT NULL,
            issue_number        INTEGER,
            issue_title         TEXT,
            contribution_type   TEXT NOT NULL DEFAULT 'pr',
            pr_url              TEXT,
            status              TEXT NOT NULL DEFAULT 'drafted',
            notes               TEXT,
            submitted_at        DATETIME,
            acknowledged_at     DATETIME,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_contributions_status ON contributions(status);
        CREATE INDEX IF NOT EXISTS idx_contributions_prospect ON contributions(prospect_id);
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

    // ── Analysis cache — stores GitHub analysis JSON, expires after 7 days ──────
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS analysis_cache (
            org         TEXT PRIMARY KEY,
            company     TEXT,
            analysis    TEXT NOT NULL,
            cached_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        "#,
    )
    .execute(&pool)
    .await?;

    // ── Proposals — generated technical proposals per company ──────────────────
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS proposals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            org         TEXT NOT NULL,
            company     TEXT NOT NULL,
            focus_area  TEXT,
            proposals   TEXT NOT NULL,
            sent_at     DATETIME,
            replied_at  DATETIME,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_proposals_org ON proposals(org);
        "#,
    )
    .execute(&pool)
    .await?;

    // Migrations — ALTER TABLE silently fails if column already exists; that's fine.
    for col_sql in &[
        "ALTER TABLE prospects ADD COLUMN domain TEXT",
        "ALTER TABLE prospects ADD COLUMN email_sent_at DATETIME",
        "ALTER TABLE prospects ADD COLUMN follow_up_sent_at DATETIME",
        "ALTER TABLE prospects ADD COLUMN last_commit_date TEXT",
        "ALTER TABLE prospects ADD COLUMN archived INTEGER DEFAULT 0",
        "ALTER TABLE prospects ADD COLUMN website TEXT",
        "ALTER TABLE prospects ADD COLUMN daily_email_blocked INTEGER DEFAULT 0",
        // 2-direction architecture
        "ALTER TABLE prospects ADD COLUMN direction TEXT DEFAULT 'proposal'",
        "ALTER TABLE prospects ADD COLUMN proposal_id INTEGER",
        "ALTER TABLE prospects ADD COLUMN job_score INTEGER",
        "ALTER TABLE prospects ADD COLUMN routed_at DATETIME",
    ] {
        let _ = sqlx::query(col_sql).execute(&pool).await;
    }

    // Unique index on domain (non-null rows only) for dedup
    let _ = sqlx::query(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_domain ON prospects(domain) WHERE domain IS NOT NULL"
    ).execute(&pool).await;

    Ok(pool)
}

/// Check whether a tool has exceeded its monthly call quota.
/// Queries `tool_call_log` for calls in the last `days` days.
/// Returns Ok(remaining) or Err(blocked message).
pub async fn check_monthly_quota(
    pool: &SqlitePool,
    tool: &str,
    monthly_limit: i64,
    days: i64,
) -> Result<i64> {
    let used: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM tool_call_log WHERE tool_name = ? AND ts >= datetime('now', ? || ' days')"
    )
    .bind(tool)
    .bind(format!("-{days}"))
    .fetch_one(pool)
    .await?;

    if used >= monthly_limit {
        anyhow::bail!(
            "Monthly quota exceeded for '{}': {}/{} calls used in last {} days",
            tool, used, monthly_limit, days
        );
    }
    Ok(monthly_limit - used)
}
