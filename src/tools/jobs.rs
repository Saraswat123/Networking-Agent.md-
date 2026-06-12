use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct Job {
    pub id: Option<String>,
    pub company: Option<String>,
    pub company_url: Option<String>,
    pub title: Option<String>,
    pub url: Option<String>,
    pub location: Option<String>,
    pub tags: Vec<String>,
    pub salary_min: Option<i64>,
    pub salary_max: Option<i64>,
    pub date: Option<String>,
    pub description_snippet: Option<String>,
}

/// Search RemoteOK jobs — free, no API key, no rate limit
/// tags: comma-separated e.g. "rust,typescript,senior" or "" for all
pub async fn search_remoteok(client: &Client, tags: &str, limit: usize) -> Result<Vec<Job>> {
    let url = if tags.is_empty() {
        "https://remoteok.com/api".to_string()
    } else {
        format!("https://remoteok.com/api?tags={}", tags)
    };

    let raw: Vec<serde_json::Value> = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    // First element is a legal notice object, skip it
    let jobs: Vec<Job> = raw
        .into_iter()
        .skip(1)
        .filter(|j| j.get("company").and_then(|c| c.as_str()).is_some())
        .take(limit)
        .map(|j| {
            let tags_vec: Vec<String> = j
                .get("tags")
                .and_then(|t| t.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|t| t.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();

            let description_snippet = j
                .get("description")
                .and_then(|d| d.as_str())
                .map(|d| {
                    let text = strip_html(d);
                    if text.len() > 400 {
                        format!("{}...", &text[..400])
                    } else {
                        text
                    }
                });

            Job {
                id: j.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()),
                company: j
                    .get("company")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                company_url: j
                    .get("company_website")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                title: j
                    .get("position")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                url: j
                    .get("url")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                location: j
                    .get("location")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                tags: tags_vec,
                salary_min: j.get("salary_min").and_then(|v| v.as_i64()),
                salary_max: j.get("salary_max").and_then(|v| v.as_i64()),
                date: j
                    .get("date")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                description_snippet,
            }
        })
        .collect();

    Ok(jobs)
}

fn strip_html(html: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;
    for c in html.chars() {
        match c {
            '<' => in_tag = true,
            '>' => {
                in_tag = false;
                result.push(' ');
            }
            _ if !in_tag => result.push(c),
            _ => {}
        }
    }
    // Collapse whitespace
    result
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
