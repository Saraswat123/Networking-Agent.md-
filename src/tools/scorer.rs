use anyhow::Result;
use chrono::{DateTime, Utc};
use regex::Regex;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

const GITHUB_API: &str = "https://api.github.com";

fn stack_score(language: Option<&str>, topics: &[String]) -> (u32, String) {
    let lang = language.unwrap_or("").to_lowercase();
    let topics_str = topics.join(" ").to_lowercase();
    if lang == "rust" || topics_str.contains("rust") {
        return (20, "Rust".to_string());
    }
    if lang == "python" || topics_str.contains("python") {
        return (15, "Python".to_string());
    }
    if lang == "typescript" || topics_str.contains("typescript") {
        return (10, "TypeScript".to_string());
    }
    if lang == "javascript" {
        return (8, "JavaScript".to_string());
    }
    if lang == "go" || topics_str.contains("golang") {
        return (10, "Go".to_string());
    }
    if topics_str.contains("postgres") || topics_str.contains("database") || topics_str.contains("sql") {
        return (10, "SQL/Data".to_string());
    }
    (5, lang.to_string())
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ScoredIssue {
    pub number: u64,
    pub title: String,
    pub url: String,
    pub score: u32,
    pub signals: Vec<String>,
    pub repo: String,
    pub repo_language: Option<String>,
    pub created_days_ago: i64,
    pub comment_count: u32,
    pub has_assignee: bool,
    pub has_linked_pr: bool,
    pub labels: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RepoSummary {
    pub name: String,
    pub full_name: String,
    pub language: Option<String>,
    pub stars: u64,
    pub open_issues: u64,
    pub pushed_at: Option<String>,
    pub topics: Vec<String>,
    pub description: Option<String>,
    pub html_url: String,
}

#[derive(Debug, Deserialize)]
struct RepoInfo {
    language: Option<String>,
    #[serde(default)]
    topics: Vec<String>,
    pushed_at: Option<String>,
    full_name: String,
}

#[derive(Debug, Deserialize)]
struct RawIssue {
    number: u64,
    title: String,
    html_url: String,
    body: Option<String>,
    created_at: String,
    comments: u64,
    #[serde(default)]
    assignees: Vec<serde_json::Value>,
    #[serde(default)]
    labels: Vec<serde_json::Value>,
    pull_request: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct PrSearchResp {
    items: Vec<PrItem>,
}

#[derive(Debug, Deserialize)]
struct PrItem {
    title: String,
    body: Option<String>,
}

fn days_ago(iso: &str) -> i64 {
    DateTime::parse_from_rfc3339(iso)
        .map(|dt| {
            let now: DateTime<Utc> = Utc::now();
            (now - dt.with_timezone(&Utc)).num_days()
        })
        .unwrap_or(999)
}

fn is_repo_active(pushed_at: Option<&str>) -> bool {
    pushed_at.map(|p| days_ago(p) < 90).unwrap_or(false)
}

fn build_auth(token: &str) -> String {
    format!("Bearer {}", token)
}

pub async fn score_repo_issues(
    client: &Client,
    token: &str,
    owner: &str,
    repo: &str,
) -> Result<Vec<ScoredIssue>> {
    let auth = build_auth(token);
    let agent = "networking-agent/0.1";
    let api_ver = "2022-11-28";

    // 1. Repo metadata
    let repo_info: RepoInfo = client
        .get(format!("{}/repos/{}/{}", GITHUB_API, owner, repo))
        .header("Authorization", &auth)
        .header("User-Agent", agent)
        .header("X-GitHub-Api-Version", api_ver)
        .send()
        .await?
        .json()
        .await?;

    let (s_score, stack_label) = stack_score(repo_info.language.as_deref(), &repo_info.topics);
    let active = is_repo_active(repo_info.pushed_at.as_deref());

    // 2. Open issues (includes PRs — filter below)
    let raw_issues: Vec<RawIssue> = client
        .get(format!("{}/repos/{}/{}/issues", GITHUB_API, owner, repo))
        .header("Authorization", &auth)
        .header("User-Agent", agent)
        .header("X-GitHub-Api-Version", api_ver)
        .query(&[("state", "open"), ("per_page", "50"), ("sort", "created"), ("direction", "desc")])
        .send()
        .await?
        .json()
        .await?;

    let issues: Vec<RawIssue> = raw_issues.into_iter().filter(|i| i.pull_request.is_none()).collect();

    // 3. Open PRs to detect linked issues
    let pr_resp: PrSearchResp = client
        .get(format!("{}/search/issues", GITHUB_API))
        .header("Authorization", &auth)
        .header("User-Agent", agent)
        .header("X-GitHub-Api-Version", api_ver)
        .query(&[
            ("q", format!("repo:{}/{} is:pr is:open", owner, repo).as_str()),
            ("per_page", "50"),
        ])
        .send()
        .await?
        .json()
        .await?;

    let re = Regex::new(r"#(\d+)").unwrap();
    let mut linked: HashSet<u64> = HashSet::new();
    for pr in &pr_resp.items {
        let text = format!("{} {}", pr.title, pr.body.as_deref().unwrap_or(""));
        for cap in re.captures_iter(&text) {
            if let Ok(n) = cap[1].parse::<u64>() {
                linked.insert(n);
            }
        }
    }

    let scored: Vec<ScoredIssue> = issues
        .into_iter()
        .map(|issue| {
            let mut score: u32 = 0;
            let mut signals: Vec<String> = Vec::new();

            let age = days_ago(&issue.created_at);
            let has_assignee = !issue.assignees.is_empty();
            let has_linked_pr = linked.contains(&issue.number);
            let has_body = issue.body.as_ref().map(|b| b.len() > 80).unwrap_or(false);

            let label_names: Vec<String> = issue.labels.iter()
                .filter_map(|l| l["name"].as_str().map(|s| s.to_lowercase()))
                .collect();

            let is_beginner_friendly = label_names.iter().any(|l| {
                l.contains("good first") || l.contains("help wanted") || l.contains("beginner")
            });

            if !has_linked_pr {
                score += 30;
                signals.push("no linked PR — open slot".to_string());
            } else {
                signals.push("has linked PR — may be claimed".to_string());
            }

            if !has_assignee {
                score += 20;
                signals.push("unassigned".to_string());
            } else {
                signals.push("already assigned".to_string());
            }

            score += s_score;
            if s_score >= 15 {
                signals.push(format!("strong stack match: {}", stack_label));
            } else if s_score >= 8 {
                signals.push(format!("partial stack match: {}", stack_label));
            } else {
                signals.push(format!("weak stack match: {}", stack_label));
            }

            if age < 14 {
                score += 15;
                signals.push(format!("{} days old — very fresh", age));
            } else if age < 45 {
                score += 10;
                signals.push(format!("{} days old — recent", age));
            } else if age < 120 {
                score += 4;
                signals.push(format!("{} days old", age));
            } else {
                signals.push(format!("{} days old — stale", age));
            }

            if active {
                score += 10;
                signals.push("repo active (pushed <90 days)".to_string());
            } else {
                signals.push("repo inactive".to_string());
            }

            if has_body {
                score += 5;
                signals.push("has description".to_string());
            } else {
                signals.push("no description".to_string());
            }

            if is_beginner_friendly {
                score += 5;
                signals.push("labeled help-wanted/good-first".to_string());
            }

            // Penalize contested issues
            if issue.comments > 15 {
                let penalty = 15u32;
                score = score.saturating_sub(penalty);
                signals.push(format!("contested ({} comments)", issue.comments));
            } else if issue.comments > 5 {
                score = score.saturating_sub(5);
                signals.push(format!("active discussion ({} comments)", issue.comments));
            }

            ScoredIssue {
                number: issue.number,
                title: issue.title,
                url: issue.html_url,
                score,
                signals,
                repo: repo_info.full_name.clone(),
                repo_language: repo_info.language.clone(),
                created_days_ago: age,
                comment_count: issue.comments as u32,
                has_assignee,
                has_linked_pr,
                labels: label_names,
            }
        })
        .collect();

    let mut scored = scored;
    scored.sort_by(|a, b| b.score.cmp(&a.score));
    Ok(scored)
}

pub async fn list_org_repos(
    client: &Client,
    token: &str,
    org: &str,
    min_stars: u32,
) -> Result<Vec<RepoSummary>> {
    let auth = build_auth(token);

    let raw: Vec<serde_json::Value> = client
        .get(format!("{}/orgs/{}/repos", GITHUB_API, org))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("per_page", "50"), ("sort", "pushed"), ("type", "public")])
        .send()
        .await?
        .json()
        .await?;

    let mut repos: Vec<RepoSummary> = raw
        .into_iter()
        .filter(|r| {
            let stars = r["stargazers_count"].as_u64().unwrap_or(0);
            let archived = r["archived"].as_bool().unwrap_or(false);
            let open_issues = r["open_issues_count"].as_u64().unwrap_or(0);
            !archived && stars >= min_stars as u64 && open_issues > 0
        })
        .map(|r| RepoSummary {
            name: r["name"].as_str().unwrap_or("").to_string(),
            full_name: r["full_name"].as_str().unwrap_or("").to_string(),
            language: r["language"].as_str().map(|s| s.to_string()),
            stars: r["stargazers_count"].as_u64().unwrap_or(0),
            open_issues: r["open_issues_count"].as_u64().unwrap_or(0),
            pushed_at: r["pushed_at"].as_str().map(|s| s.to_string()),
            topics: r["topics"].as_array()
                .map(|a| a.iter().filter_map(|t| t.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default(),
            description: r["description"].as_str().map(|s| s.to_string()),
            html_url: r["html_url"].as_str().unwrap_or("").to_string(),
        })
        .collect();

    // Sort: active repos with issues first
    repos.sort_by(|a, b| {
        let a_days = a.pushed_at.as_deref().map(days_ago).unwrap_or(9999);
        let b_days = b.pushed_at.as_deref().map(days_ago).unwrap_or(9999);
        a_days.cmp(&b_days)
    });

    Ok(repos)
}
