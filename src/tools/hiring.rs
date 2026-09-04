use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const HN_ALGOLIA: &str = "https://hn.algolia.com/api/v1/search";
const HN_ALGOLIA_DATE: &str = "https://hn.algolia.com/api/v1/search_by_date";

#[derive(Debug, Serialize, Deserialize)]
pub struct HiringPost {
    pub comment_text: String,
    pub author: String,
    pub created_at: String,
    pub story_id: u64,
    pub object_id: String,
    pub hn_url: String,
}

#[derive(Debug, Deserialize)]
struct AlgoliaResp {
    hits: Vec<AlgoliaHit>,
}

#[derive(Debug, Deserialize)]
struct AlgoliaHit {
    #[serde(rename = "objectID")]
    object_id: String,
    #[serde(rename = "comment_text")]
    comment_text: Option<String>,
    author: Option<String>,
    #[serde(rename = "created_at")]
    created_at: Option<String>,
    #[serde(rename = "story_id")]
    story_id: Option<u64>,
    #[serde(rename = "storyId")]
    story_id_alt: Option<u64>,
}

/// Find the most recent "Ask HN: Who is Hiring?" post ID
async fn get_latest_hiring_story_id(client: &Client) -> Result<u64> {
    let resp: AlgoliaResp = client
        .get(HN_ALGOLIA_DATE)
        .query(&[
            ("query", "Ask HN: Who is Hiring?"),
            ("tags", "story,ask_hn"),
            ("hitsPerPage", "1"),
        ])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    resp.hits
        .into_iter()
        .next()
        .and_then(|h| h.object_id.parse::<u64>().ok())
        .ok_or_else(|| anyhow::anyhow!("No HN hiring post found"))
}

/// Search HN "Who is Hiring" comments for a tech/role keyword
/// e.g. "Rust", "data engineer", "remote", "AI infra"
pub async fn search_hn_hiring(client: &Client, query: &str, limit: usize) -> Result<Vec<HiringPost>> {
    let story_id = get_latest_hiring_story_id(client).await?;

    let resp: AlgoliaResp = client
        .get(HN_ALGOLIA)
        .query(&[
            ("query", query),
            ("tags", &format!("comment,story_{}", story_id)),
            ("hitsPerPage", &limit.to_string()),
        ])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let posts: Vec<HiringPost> = resp
        .hits
        .into_iter()
        .filter_map(|h| {
            let text = h.comment_text?;
            let sid = h.story_id.or(h.story_id_alt).unwrap_or(story_id);
            Some(HiringPost {
                comment_text: strip_html_basic(&text),
                author: h.author.unwrap_or_default(),
                created_at: h.created_at.unwrap_or_default(),
                story_id: sid,
                object_id: h.object_id.clone(),
                hn_url: format!("https://news.ycombinator.com/item?id={}", h.object_id),
            })
        })
        .collect();

    Ok(posts)
}

fn strip_html_basic(html: &str) -> String {
    let mut out = String::with_capacity(html.len());
    let mut in_tag = false;
    for c in html.chars() {
        match c {
            '<' => in_tag = true,
            '>' => {
                in_tag = false;
                out.push('\n');
            }
            _ if !in_tag => out.push(c),
            _ => {}
        }
    }
    // Decode basic HTML entities
    out.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#x27;", "'")
        .replace("&nbsp;", " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
