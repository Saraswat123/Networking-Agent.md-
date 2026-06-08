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

    Ok(pool)
}
