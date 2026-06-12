use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::Instant;

use sqlx::SqlitePool;

/// One audit record — written to tool_call_log for every tool invocation.
pub struct CallRecord {
    pub tool: String,
    pub input_preview: String,   // PII-redacted, max 256 chars
    pub output_len: usize,
    pub output_fingerprint: u64, // DefaultHasher of output — integrity check only
    pub duration_ms: i64,
    pub status: String,          // "ok" | "error"
    pub pii_detected: String,    // comma-separated types found e.g. "email,api_key"
}

#[derive(Debug)]
pub struct AuditLogger {
    pub enabled: bool,
}

impl AuditLogger {
    pub fn new(enabled: bool) -> Self {
        Self { enabled }
    }

    pub fn start(&self) -> Instant {
        Instant::now()
    }

    pub async fn log(
        &self,
        db: &SqlitePool,
        tool: &str,
        input_preview: &str,
        output: &str,
        started: Instant,
        pii_types: &[&str],
    ) {
        if !self.enabled {
            return;
        }

        let duration_ms = started.elapsed().as_millis() as i64;
        let status = if output.starts_with("Error:") { "error" } else { "ok" };
        let output_fingerprint = fingerprint(output);
        let preview = if input_preview.len() > 256 {
            &input_preview[..256]
        } else {
            input_preview
        };
        let pii_str = pii_types.join(",");

        let _ = sqlx::query(
            "INSERT INTO tool_call_log \
             (tool_name, input_preview, output_len, output_fingerprint, duration_ms, status, pii_detected) \
             VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(tool)
        .bind(preview)
        .bind(output.len() as i64)
        .bind(output_fingerprint as i64)
        .bind(duration_ms)
        .bind(status)
        .bind(&pii_str)
        .execute(db)
        .await;
    }
}

fn fingerprint(s: &str) -> u64 {
    let mut h = DefaultHasher::new();
    s.hash(&mut h);
    h.finish()
}
