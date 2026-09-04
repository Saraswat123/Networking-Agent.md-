use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AtsJob {
    pub title: String,
    pub department: Option<String>,
    pub location: String,
    pub remote: bool,
    pub url: Option<String>,
    pub posted_at: Option<String>,
    pub ats: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AtsBoard {
    pub ats: String,
    pub board_slug: String,
    pub total_jobs: usize,
    pub eng_roles: usize,
    pub remote_roles: usize,
    pub jobs: Vec<AtsJob>,
}

fn is_eng(title: &str) -> bool {
    let t = title.to_lowercase();
    [
        "engineer",
        "developer",
        "backend",
        "frontend",
        "fullstack",
        "full-stack",
        "platform",
        "infrastructure",
        "devops",
        "sre",
        "data",
        "ml",
        "ai",
        "rust",
        "python",
        "golang",
        "software",
        "reliability",
    ]
    .iter()
    .any(|k| t.contains(k))
}

fn is_remote(location: &str) -> bool {
    let l = location.to_lowercase();
    l.contains("remote") || l.contains("anywhere") || l.contains("distributed")
}

// ── Greenhouse ───────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct GhResp {
    jobs: Vec<GhJob>,
}

#[derive(Deserialize)]
struct GhJob {
    title: String,
    location: GhLoc,
    absolute_url: Option<String>,
    updated_at: Option<String>,
    departments: Option<Vec<GhDept>>,
}

#[derive(Deserialize)]
struct GhLoc {
    name: String,
}

#[derive(Deserialize)]
struct GhDept {
    name: String,
}

pub async fn fetch_greenhouse(client: &Client, board: &str) -> Result<AtsBoard> {
    let url = format!("https://boards-api.greenhouse.io/v1/boards/{}/jobs", board);
    let resp: GhResp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let jobs: Vec<AtsJob> = resp
        .jobs
        .into_iter()
        .map(|j| AtsJob {
            remote: is_remote(&j.location.name),
            department: j.departments.and_then(|d| d.into_iter().next().map(|d| d.name)),
            location: j.location.name,
            url: j.absolute_url,
            posted_at: j.updated_at,
            ats: "greenhouse".to_string(),
            title: j.title,
        })
        .collect();

    let eng_roles = jobs.iter().filter(|j| is_eng(&j.title)).count();
    let remote_roles = jobs.iter().filter(|j| j.remote).count();
    let total_jobs = jobs.len();

    Ok(AtsBoard {
        ats: "greenhouse".to_string(),
        board_slug: board.to_string(),
        total_jobs,
        eng_roles,
        remote_roles,
        jobs,
    })
}

// ── Lever ────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct LeverPosting {
    text: String,
    categories: LeverCats,
    #[serde(rename = "hostedUrl")]
    hosted_url: Option<String>,
    #[serde(rename = "createdAt")]
    created_at: Option<u64>,
}

#[derive(Deserialize)]
struct LeverCats {
    location: Option<String>,
    team: Option<String>,
    #[serde(rename = "allLocations")]
    all_locations: Option<Vec<String>>,
}

pub async fn fetch_lever(client: &Client, company: &str) -> Result<AtsBoard> {
    let url = format!("https://api.lever.co/v0/postings/{}?mode=json", company);
    let resp: Vec<LeverPosting> = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let jobs: Vec<AtsJob> = resp
        .into_iter()
        .map(|p| {
            let loc = p
                .categories
                .all_locations
                .and_then(|l| l.into_iter().next())
                .or(p.categories.location)
                .unwrap_or_default();
            AtsJob {
                remote: is_remote(&loc),
                department: p.categories.team,
                location: loc,
                url: p.hosted_url,
                posted_at: p.created_at.map(|t| t.to_string()),
                ats: "lever".to_string(),
                title: p.text,
            }
        })
        .collect();

    let eng_roles = jobs.iter().filter(|j| is_eng(&j.title)).count();
    let remote_roles = jobs.iter().filter(|j| j.remote).count();
    let total_jobs = jobs.len();

    Ok(AtsBoard {
        ats: "lever".to_string(),
        board_slug: company.to_string(),
        total_jobs,
        eng_roles,
        remote_roles,
        jobs,
    })
}

// ── Ashby ────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct AshbyResp {
    #[serde(rename = "jobPostings")]
    job_postings: Vec<AshbyJob>,
}

#[derive(Deserialize)]
struct AshbyJob {
    title: String,
    #[serde(rename = "locationName")]
    location_name: Option<String>,
    #[serde(rename = "isRemote")]
    is_remote: Option<bool>,
    #[serde(rename = "teamName")]
    team_name: Option<String>,
    #[serde(rename = "jobUrl")]
    job_url: Option<String>,
}

pub async fn fetch_ashby(client: &Client, board: &str) -> Result<AtsBoard> {
    let url = format!("https://api.ashbyhq.com/posting-api/job-board/{}", board);
    let resp: AshbyResp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let jobs: Vec<AtsJob> = resp
        .job_postings
        .into_iter()
        .map(|j| {
            let loc = j.location_name.unwrap_or_default();
            let remote = j.is_remote.unwrap_or(false) || is_remote(&loc);
            AtsJob {
                remote,
                department: j.team_name,
                location: loc,
                url: j.job_url,
                posted_at: None,
                ats: "ashby".to_string(),
                title: j.title,
            }
        })
        .collect();

    let eng_roles = jobs.iter().filter(|j| is_eng(&j.title)).count();
    let remote_roles = jobs.iter().filter(|j| j.remote).count();
    let total_jobs = jobs.len();

    Ok(AtsBoard {
        ats: "ashby".to_string(),
        board_slug: board.to_string(),
        total_jobs,
        eng_roles,
        remote_roles,
        jobs,
    })
}

// ── Auto-detect + search ─────────────────────────────────────────────────────

pub async fn search_ats_jobs(
    client: &Client,
    board_slug: &str,
    preferred_ats: Option<&str>,
) -> Result<AtsBoard> {
    match preferred_ats {
        Some("ashby") => return fetch_ashby(client, board_slug).await,
        Some("greenhouse") => return fetch_greenhouse(client, board_slug).await,
        Some("lever") => return fetch_lever(client, board_slug).await,
        _ => {}
    }

    // Auto-detect: Ashby first (AI/dev-tool sweet spot), then Greenhouse, then Lever
    if let Ok(b) = fetch_ashby(client, board_slug).await {
        if !b.jobs.is_empty() {
            return Ok(b);
        }
    }
    if let Ok(b) = fetch_greenhouse(client, board_slug).await {
        if !b.jobs.is_empty() {
            return Ok(b);
        }
    }
    if let Ok(b) = fetch_lever(client, board_slug).await {
        if !b.jobs.is_empty() {
            return Ok(b);
        }
    }

    Err(anyhow::anyhow!(
        "No ATS board found for '{}' — try ashby/greenhouse/lever with explicit ats param",
        board_slug
    ))
}
