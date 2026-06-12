use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct TechStackResult {
    pub url: String,
    pub technologies: Vec<Technology>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Technology {
    pub name: String,
    pub category: Option<String>,
    pub version: Option<String>,
}

pub async fn lookup_tech_stack(client: &Client, url: &str) -> Result<TechStackResult> {
    let resp: serde_json::Value = client
        .get("https://api.webreveal.io/tech")
        .header("User-Agent", "networking-agent/0.1")
        .query(&[("url", url)])
        .send()
        .await?
        .json()
        .await?;

    let mut technologies = Vec::new();

    if let Some(techs) = resp.get("technologies").and_then(|t| t.as_array()) {
        for tech in techs {
            technologies.push(Technology {
                name: tech
                    .get("name")
                    .and_then(|n| n.as_str())
                    .unwrap_or("Unknown")
                    .to_string(),
                category: tech
                    .get("category")
                    .and_then(|c| c.as_str())
                    .map(|s| s.to_string()),
                version: tech
                    .get("version")
                    .and_then(|v| v.as_str())
                    .filter(|v| !v.is_empty())
                    .map(|s| s.to_string()),
            });
        }
    }

    Ok(TechStackResult {
        url: url.to_string(),
        technologies,
    })
}
