use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const GITHUB_API: &str = "https://api.github.com";

#[derive(Debug, Serialize, Deserialize)]
pub struct GitHubUser {
    pub login: String,
    pub name: Option<String>,
    pub email: Option<String>,
    pub company: Option<String>,
    pub location: Option<String>,
    pub bio: Option<String>,
    pub blog: Option<String>,
    pub public_repos: u32,
    pub followers: u32,
    pub html_url: String,
}

#[derive(Debug, Deserialize)]
struct SearchResponse {
    items: Vec<SearchUser>,
}

#[derive(Debug, Deserialize)]
struct SearchUser {
    login: String,
    html_url: String,
}

pub async fn search_users(
    client: &Client,
    token: &str,
    query: &str,
    location: &str,
) -> Result<Vec<GitHubUser>> {
    let q = if location.is_empty() {
        query.to_string()
    } else {
        format!("{} location:{}", query, location)
    };

    let resp = client
        .get(format!("{}/search/users", GITHUB_API))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("q", &q), ("per_page", &"30".to_string())])
        .send()
        .await?
        .json::<SearchResponse>()
        .await?;

    let mut users = Vec::new();
    for u in resp.items.iter().take(10) {
        if let Ok(profile) = get_user_profile(client, token, &u.login).await {
            users.push(profile);
        }
    }
    Ok(users)
}

pub async fn get_org_members(
    client: &Client,
    token: &str,
    org: &str,
) -> Result<Vec<GitHubUser>> {
    let logins = client
        .get(format!("{}/orgs/{}/members", GITHUB_API, org))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("per_page", "30")])
        .send()
        .await?
        .json::<Vec<SearchUser>>()
        .await?;

    let mut users = Vec::new();
    for u in logins.iter().take(10) {
        if let Ok(profile) = get_user_profile(client, token, &u.login).await {
            users.push(profile);
        }
    }
    Ok(users)
}

pub async fn find_open_issues(
    client: &Client,
    token: &str,
    owner: &str,
    repo: &str,
) -> Result<Vec<serde_json::Value>> {
    let issues = client
        .get(format!("{}/repos/{}/{}/issues", GITHUB_API, owner, repo))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("state", "open"), ("per_page", "20"), ("labels", "good first issue,help wanted")])
        .send()
        .await?
        .json::<Vec<serde_json::Value>>()
        .await?;

    Ok(issues
        .into_iter()
        .map(|i| {
            serde_json::json!({
                "title": i["title"],
                "url": i["html_url"],
                "labels": i["labels"].as_array().map(|l| l.iter().map(|x| &x["name"]).collect::<Vec<_>>()),
                "created_at": i["created_at"],
            })
        })
        .collect())
}

async fn get_user_profile(client: &Client, token: &str, login: &str) -> Result<GitHubUser> {
    let user: GitHubUser = client
        .get(format!("{}/users/{}", GITHUB_API, login))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await?
        .json()
        .await?;
    Ok(user)
}
