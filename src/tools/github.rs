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

#[derive(Debug, Serialize, Deserialize)]
pub struct GitHubOrg {
    pub login: String,
    pub description: Option<String>,
    pub html_url: String,
    pub blog: Option<String>,
    pub email: Option<String>,
    pub location: Option<String>,
    pub public_repos: Option<u32>,
}

#[derive(Debug, Deserialize)]
struct OrgSearchResponse {
    items: Vec<OrgSearchItem>,
}

#[derive(Debug, Deserialize)]
struct OrgSearchItem {
    login: String,
}

/// Find GitHub org for a YC company: tries github_org directly, then searches by name + domain.
/// Returns org info + up to 10 team members with full profiles.
pub async fn find_company_team(
    client: &Client,
    token: &str,
    company_name: &str,
    website: Option<&str>,
    github_org: Option<&str>,
) -> Result<serde_json::Value> {
    // Step 1: resolve org login
    let org_login = if let Some(org) = github_org {
        org.to_string()
    } else {
        // search GitHub orgs by company name
        let query = build_org_query(company_name, website);
        let resp = client
            .get(format!("{}/search/users", GITHUB_API))
            .header("Authorization", format!("Bearer {}", token))
            .header("User-Agent", "networking-agent/0.1")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .query(&[("q", &query), ("type", &"org".to_string()), ("per_page", &"5".to_string())])
            .send()
            .await?
            .json::<OrgSearchResponse>()
            .await?;

        match resp.items.into_iter().next() {
            Some(org) => org.login,
            None => return Ok(serde_json::json!({ "error": format!("No GitHub org found for '{}'", company_name) })),
        }
    };

    // Step 2: get org details
    let org_detail: serde_json::Value = client
        .get(format!("{}/orgs/{}", GITHUB_API, org_login))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await?
        .json()
        .await?;

    // Step 3: get up to 10 members with full profiles
    let logins: Vec<SearchUser> = client
        .get(format!("{}/orgs/{}/members", GITHUB_API, org_login))
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("per_page", "10")])
        .send()
        .await?
        .json()
        .await?;

    let mut members = Vec::new();
    for u in logins.iter().take(10) {
        if let Ok(profile) = get_user_profile(client, token, &u.login).await {
            members.push(profile);
        }
    }

    Ok(serde_json::json!({
        "org": org_login,
        "github_url": format!("https://github.com/{}", org_login),
        "description": org_detail["description"],
        "blog": org_detail["blog"],
        "email": org_detail["email"],
        "location": org_detail["location"],
        "public_repos": org_detail["public_repos"],
        "member_count": org_detail["public_members_url"],
        "team": members,
    }))
}

fn build_org_query(company_name: &str, website: Option<&str>) -> String {
    // try domain first (more precise), fallback to name
    if let Some(url) = website {
        if let Some(domain) = extract_domain(url) {
            return format!("{} type:org", domain);
        }
    }
    format!("{} type:org", company_name)
}

fn extract_domain(url: &str) -> Option<String> {
    // strip scheme and www
    let stripped = url
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.");
    let domain = stripped.split('/').next()?;
    // return just the root name (mentra from mentra.glass)
    Some(domain.split('.').next()?.to_string())
}
