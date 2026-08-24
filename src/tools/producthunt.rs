use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const PH_GRAPHQL: &str = "https://api.producthunt.com/v2/api/graphql";

#[derive(Debug, Serialize, Deserialize)]
pub struct PhProduct {
    pub name: String,
    pub tagline: String,
    pub ph_url: String,
    pub website: Option<String>,
    pub votes: u64,
    pub comments: u64,
    pub created_at: String,
    pub topics: Vec<String>,
    pub makers: Vec<PhMaker>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct PhMaker {
    pub name: String,
    pub username: String,
    pub twitter: Option<String>,
    pub website: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GqlResponse {
    data: Option<GqlData>,
    errors: Option<Vec<GqlError>>,
}

#[derive(Debug, Deserialize)]
struct GqlError {
    message: String,
}

#[derive(Debug, Deserialize)]
struct GqlData {
    posts: Option<PostsConnection>,
}

#[derive(Debug, Deserialize)]
struct PostsConnection {
    edges: Vec<PostEdge>,
}

#[derive(Debug, Deserialize)]
struct PostEdge {
    node: PostNode,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PostNode {
    name: String,
    tagline: String,
    url: String,
    website: Option<String>,
    votes_count: u64,
    comments_count: u64,
    created_at: String,
    topics: Option<TopicsConnection>,
    makers: Option<Vec<MakerNode>>,
}

#[derive(Debug, Deserialize)]
struct TopicsConnection {
    edges: Vec<TopicEdge>,
}

#[derive(Debug, Deserialize)]
struct TopicEdge {
    node: TopicNode,
}

#[derive(Debug, Deserialize)]
struct TopicNode {
    name: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MakerNode {
    name: String,
    username: String,
    twitter_username: Option<String>,
    website_url: Option<String>,
}

/// Search ProductHunt posts by topic and/or keyword
/// topic: "developer-tools", "artificial-intelligence", "data-science", etc.
/// days_back: how many days to look back (default 30)
pub async fn search_posts(
    client: &Client,
    api_token: &str,
    topic: Option<&str>,
    days_back: u32,
    limit: usize,
) -> Result<Vec<PhProduct>> {
    if api_token.is_empty() {
        anyhow::bail!(
            "PRODUCTHUNT_API_TOKEN not set. Get free token at producthunt.com/v2/oauth/applications"
        );
    }

    // Build topic filter clause
    let topic_filter = topic
        .map(|t| format!(", topic: \"{}\"", t))
        .unwrap_or_default();

    // Date filter: posted in last N days
    let posted_after = days_ago_iso(days_back as i64);

    let query = format!(
        r#"{{
            posts(first: {limit}, order: VOTES{topic_filter}, postedAfter: "{posted_after}") {{
                edges {{
                    node {{
                        name
                        tagline
                        url
                        website
                        votesCount
                        commentsCount
                        createdAt
                        topics {{
                            edges {{
                                node {{ name }}
                            }}
                        }}
                        makers {{
                            name
                            username
                            twitterUsername
                            websiteUrl
                        }}
                    }}
                }}
            }}
        }}"#,
        limit = limit.min(50),
        topic_filter = topic_filter,
        posted_after = posted_after,
    );

    let body = serde_json::json!({ "query": query });

    let resp = client
        .post(PH_GRAPHQL)
        .header("Authorization", format!("Bearer {}", api_token))
        .header("Content-Type", "application/json")
        .header("User-Agent", "networking-agent/0.1")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    let text = resp.text().await?;

    if !status.is_success() {
        anyhow::bail!("ProductHunt API error {}: {}", status, &text[..text.len().min(300)]);
    }

    let gql: GqlResponse = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("Parse error: {} — raw: {}", e, &text[..text.len().min(300)]))?;

    if let Some(errors) = gql.errors {
        let msg = errors.into_iter().map(|e| e.message).collect::<Vec<_>>().join(", ");
        anyhow::bail!("GraphQL errors: {}", msg);
    }

    let posts = gql
        .data
        .and_then(|d| d.posts)
        .map(|p| p.edges)
        .unwrap_or_default()
        .into_iter()
        .map(|edge| {
            let n = edge.node;
            let topics: Vec<String> = n
                .topics
                .map(|t| t.edges.into_iter().map(|e| e.node.name).collect())
                .unwrap_or_default();

            let makers: Vec<PhMaker> = n
                .makers
                .unwrap_or_default()
                .into_iter()
                .map(|m| PhMaker {
                    name: m.name,
                    username: m.username,
                    twitter: m.twitter_username,
                    website: m.website_url,
                })
                .collect();

            PhProduct {
                name: n.name,
                tagline: n.tagline,
                ph_url: n.url,
                website: n.website,
                votes: n.votes_count,
                comments: n.comments_count,
                created_at: n.created_at,
                topics,
                makers,
            }
        })
        .collect();

    Ok(posts)
}

fn days_ago_iso(days: i64) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let target = now - days * 86400;
    unix_to_iso(target)
}

fn unix_to_iso(ts: i64) -> String {
    // Convert unix timestamp to ISO 8601 date string YYYY-MM-DD
    let days_total = ts / 86400;
    let mut y = 1970i64;
    let mut d = days_total;

    loop {
        let days_in_year = if is_leap(y) { 366 } else { 365 };
        if d < days_in_year {
            break;
        }
        d -= days_in_year;
        y += 1;
    }

    let months = [31i64, if is_leap(y) { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut m = 0usize;
    for &days_in_month in &months {
        if d < days_in_month {
            break;
        }
        d -= days_in_month;
        m += 1;
    }

    format!("{:04}-{:02}-{:02}T00:00:00Z", y, m + 1, d + 1)
}

fn is_leap(y: i64) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}
