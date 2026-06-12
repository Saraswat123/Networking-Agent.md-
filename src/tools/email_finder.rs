use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct EmailResult {
    pub domain: String,
    pub organization: Option<String>,
    pub pattern: Option<String>,
    pub emails: Vec<EmailEntry>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EmailEntry {
    pub value: String,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub position: Option<String>,
    pub confidence: Option<u32>,
    pub linkedin: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HunterResponse {
    data: Option<HunterData>,
    errors: Option<Vec<serde_json::Value>>,
}

#[derive(Debug, Deserialize)]
struct HunterData {
    domain: String,
    organization: Option<String>,
    pattern: Option<String>,
    emails: Vec<HunterEmail>,
}

#[derive(Debug, Deserialize)]
struct HunterEmail {
    value: String,
    first_name: Option<String>,
    last_name: Option<String>,
    position: Option<String>,
    confidence: Option<u32>,
    linkedin: Option<String>,
}

pub async fn find_emails(
    client: &Client,
    api_key: &str,
    domain: &str,
    limit: u32,
) -> Result<EmailResult> {
    if api_key.is_empty() {
        return Err(anyhow!("HUNTER_API_KEY not set — get free key at hunter.io (25 searches/mo free)"));
    }

    let resp = client
        .get("https://api.hunter.io/v2/domain-search")
        .header("User-Agent", "networking-agent/0.1")
        .query(&[
            ("domain", domain),
            ("api_key", api_key),
            ("limit", &limit.to_string()),
        ])
        .send()
        .await?
        .json::<HunterResponse>()
        .await?;

    if let Some(errors) = resp.errors {
        if !errors.is_empty() {
            return Err(anyhow!("Hunter.io error: {}", serde_json::to_string(&errors)?));
        }
    }

    let data = resp.data.ok_or_else(|| anyhow!("No data returned from Hunter.io"))?;

    Ok(EmailResult {
        domain: data.domain,
        organization: data.organization,
        pattern: data.pattern,
        emails: data
            .emails
            .into_iter()
            .map(|e| EmailEntry {
                value: e.value,
                first_name: e.first_name,
                last_name: e.last_name,
                position: e.position,
                confidence: e.confidence,
                linkedin: e.linkedin,
            })
            .collect(),
    })
}
