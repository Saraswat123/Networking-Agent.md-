use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct EmailVerifyResult {
    pub email: String,
    pub deliverable: bool,
    pub confidence: u32,
    pub source: String,
    pub mx_found: bool,
    pub disposable: bool,
    pub result: String,
}

// ── Hunter.io verifier ───────────────────────────────────────────────────────

#[derive(Deserialize)]
struct HunterVerifyResp {
    data: HunterVerifyData,
}

#[derive(Deserialize)]
struct HunterVerifyData {
    result: String,
    score: u32,
    disposable: Option<bool>,
    #[serde(rename = "mx_records")]
    mx_records: Option<bool>,
}

pub async fn verify_hunter(client: &Client, email: &str) -> Result<EmailVerifyResult> {
    let api_key = std::env::var("HUNTER_API_KEY").unwrap_or_default();
    if api_key.is_empty() {
        return Err(anyhow::anyhow!("HUNTER_API_KEY not set"));
    }

    let resp: HunterVerifyResp = client
        .get("https://api.hunter.io/v2/email-verifier")
        .query(&[("email", email), ("api_key", &api_key)])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let d = resp.data;
    Ok(EmailVerifyResult {
        email: email.to_string(),
        deliverable: d.result == "deliverable",
        confidence: d.score,
        source: "hunter".to_string(),
        mx_found: d.mx_records.unwrap_or(false),
        disposable: d.disposable.unwrap_or(false),
        result: d.result,
    })
}

// ── Email pattern generator ──────────────────────────────────────────────────

pub fn email_patterns(first: &str, last: &str, domain: &str) -> Vec<String> {
    let f = first.to_lowercase().replace(' ', "");
    let l = last.to_lowercase().replace(' ', "");
    let fi = f.chars().next().unwrap_or('x');

    vec![
        format!("{}@{}", f, domain),
        format!("{}.{}@{}", f, l, domain),
        format!("{}{}@{}", fi, l, domain),
        format!("{}_{}@{}", f, l, domain),
        format!("{}@{}", l, domain),
        format!("{}.{}@{}", fi, l, domain),
    ]
}

// ── Verify waterfall: try all patterns, return first deliverable ─────────────

pub async fn verify_waterfall(
    client: &Client,
    candidates: Vec<String>,
) -> Result<Option<EmailVerifyResult>> {
    for email in candidates {
        match verify_hunter(client, &email).await {
            Ok(r) if r.deliverable => return Ok(Some(r)),
            _ => continue,
        }
    }
    Ok(None)
}

// ── Bulk verify ──────────────────────────────────────────────────────────────

pub async fn bulk_verify(
    client: &Client,
    emails: Vec<String>,
) -> Vec<EmailVerifyResult> {
    let mut results = vec![];
    for email in emails {
        if let Ok(r) = verify_hunter(client, &email).await {
            results.push(r);
        }
    }
    results
}
