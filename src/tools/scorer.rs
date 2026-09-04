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

// ─── Repo health check (zombie / dead-maintainer gate) ───────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct RepoHealth {
    pub owner: String,
    pub repo: String,
    pub last_push_days_ago: i64,
    pub open_issues: u64,
    pub open_prs: u64,
    pub closed_prs_30d: u64,
    pub pr_merge_rate_30d: f32,
    pub verdict: String,
    pub signals: Vec<String>,
}

pub async fn check_repo_health(
    client: &Client,
    token: &str,
    owner: &str,
    repo: &str,
) -> Result<RepoHealth> {
    let auth = build_auth(token);

    // Repo metadata
    let repo_data: serde_json::Value = client
        .get(format!("{}/repos/{}/{}", GITHUB_API, owner, repo))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await?
        .json()
        .await?;

    let pushed_at = repo_data["pushed_at"].as_str().unwrap_or("");
    let last_push_days = if pushed_at.is_empty() { 9999 } else { days_ago(pushed_at) };
    let open_issues_raw = repo_data["open_issues_count"].as_u64().unwrap_or(0);

    // Open PRs (GitHub counts PRs in open_issues_count, so query separately)
    let open_prs_data: serde_json::Value = client
        .get(format!("{}/repos/{}/{}/pulls", GITHUB_API, owner, repo))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("state", "open"), ("per_page", "100")])
        .send()
        .await?
        .json()
        .await
        .unwrap_or(serde_json::json!([]));

    let open_prs = open_prs_data.as_array().map(|a| a.len() as u64).unwrap_or(0);
    let open_issues = open_issues_raw.saturating_sub(open_prs);

    // Closed PRs last 30 days
    let since_30d = chrono::Utc::now()
        .checked_sub_signed(chrono::Duration::days(30))
        .unwrap_or(Utc::now())
        .to_rfc3339();

    let closed_prs_data: serde_json::Value = client
        .get(format!("{}/repos/{}/{}/pulls", GITHUB_API, owner, repo))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("state", "closed"), ("per_page", "30"), ("sort", "updated"), ("direction", "desc")])
        .send()
        .await?
        .json()
        .await
        .unwrap_or(serde_json::json!([]));

    let closed_prs_30d = closed_prs_data
        .as_array()
        .map(|prs| {
            prs.iter().filter(|pr| {
                let merged_at = pr["merged_at"].as_str().unwrap_or("");
                let closed_at = pr["closed_at"].as_str().unwrap_or("");
                let ts = if !merged_at.is_empty() { merged_at } else { closed_at };
                !ts.is_empty() && days_ago(ts) <= 30
            }).count() as u64
        })
        .unwrap_or(0);

    let pr_merge_rate_30d = if closed_prs_30d == 0 || open_prs == 0 {
        if closed_prs_30d > 0 { 1.0 } else { 0.0 }
    } else {
        closed_prs_30d as f32 / (closed_prs_30d + open_prs) as f32
    };

    // Verdict
    let mut signals: Vec<String> = Vec::new();
    let mut penalty = 0i32;

    if last_push_days > 90 {
        signals.push(format!("last commit {}d ago — likely stale", last_push_days));
        penalty += 3;
    } else if last_push_days > 30 {
        signals.push(format!("last commit {}d ago", last_push_days));
        penalty += 1;
    } else {
        signals.push(format!("active (last commit {}d ago)", last_push_days));
    }

    if open_prs > 30 && closed_prs_30d == 0 {
        signals.push(format!("{} open PRs, 0 merged in 30d — dead maintainer", open_prs));
        penalty += 3;
    } else if open_prs > 15 && closed_prs_30d < 2 {
        signals.push(format!("{} open PRs, only {} merged in 30d — slow maintainer", open_prs, closed_prs_30d));
        penalty += 1;
    } else if closed_prs_30d > 0 {
        signals.push(format!("{} PRs merged in 30d — active maintainer", closed_prs_30d));
    }

    if open_issues == 0 {
        signals.push("no open issues — nothing to contribute".into());
        penalty += 1;
    }

    let verdict = match penalty {
        0..=1 => "GOOD — contribute here".to_string(),
        2 => "MARGINAL — check before investing time".to_string(),
        _ => "SKIP — zombie or dead maintainer".to_string(),
    };

    Ok(RepoHealth {
        owner: owner.to_string(),
        repo: repo.to_string(),
        last_push_days_ago: last_push_days,
        open_issues,
        open_prs,
        closed_prs_30d,
        pr_merge_rate_30d,
        verdict,
        signals,
    })
}

// ─── CONTRIBUTING.md fetcher ─────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct ContributingGuide {
    pub found: bool,
    pub source_path: String,
    pub content: String,          // decoded markdown content
    pub key_rules: Vec<String>,   // extracted rules (PR format, test requirements, etc.)
    pub has_cla: bool,
    pub has_test_requirement: bool,
    pub has_format_requirement: bool,
}

pub async fn fetch_contributing_guide(
    client: &Client,
    token: &str,
    owner: &str,
    repo: &str,
) -> Result<ContributingGuide> {
    let auth = build_auth(token);

    let candidates = [
        "CONTRIBUTING.md",
        ".github/CONTRIBUTING.md",
        "CONTRIBUTING.rst",
        "docs/CONTRIBUTING.md",
        ".github/contributing.md",
    ];

    for path in &candidates {
        let url = format!("{}/repos/{}/{}/contents/{}", GITHUB_API, owner, repo, path);
        let resp = client
            .get(&url)
            .header("Authorization", &auth)
            .header("User-Agent", "networking-agent/0.1")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .send()
            .await?;

        if resp.status().as_u16() == 404 {
            continue;
        }
        if !resp.status().is_success() {
            continue;
        }

        let data: serde_json::Value = resp.json().await?;
        let b64 = data["content"].as_str().unwrap_or("").replace('\n', "");

        use std::io::Read;
        let decoded_bytes = {
            let mut buf = Vec::new();
            let mut decoder = base64_decoder(b64.as_bytes());
            let mut tmp = [0u8; 4096];
            loop {
                match decoder.read(&mut tmp) {
                    Ok(0) => break,
                    Ok(n) => buf.extend_from_slice(&tmp[..n]),
                    Err(_) => break,
                }
            }
            buf
        };
        let content = String::from_utf8_lossy(&decoded_bytes).to_string();

        let content_l = content.to_lowercase();
        let has_cla = content_l.contains("cla") || content_l.contains("contributor license");
        let has_test_requirement = content_l.contains("test") && (
            content_l.contains("add test") || content_l.contains("include test")
            || content_l.contains("write test") || content_l.contains("unit test")
        );
        let has_format_requirement = content_l.contains("rustfmt")
            || content_l.contains("cargo fmt")
            || content_l.contains("clippy")
            || content_l.contains("format")
            || content_l.contains("lint");

        // Extract bullet-point rules (lines starting with - or *)
        let key_rules: Vec<String> = content
            .lines()
            .filter(|l| {
                let t = l.trim();
                (t.starts_with("- ") || t.starts_with("* ") || t.starts_with("1."))
                    && t.len() > 10 && t.len() < 200
            })
            .take(10)
            .map(|l| l.trim().to_string())
            .collect();

        return Ok(ContributingGuide {
            found: true,
            source_path: path.to_string(),
            content: if content.len() > 3000 {
                format!("{}... [truncated]", &content[..3000])
            } else {
                content
            },
            key_rules,
            has_cla,
            has_test_requirement,
            has_format_requirement,
        });
    }

    Ok(ContributingGuide {
        found: false,
        source_path: String::new(),
        content: "No CONTRIBUTING.md found — check README for contribution guidelines".into(),
        key_rules: Vec::new(),
        has_cla: false,
        has_test_requirement: false,
        has_format_requirement: false,
    })
}

fn base64_decoder(input: &[u8]) -> impl std::io::Read + '_ {
    struct B64Decoder<'a> {
        input: &'a [u8],
        pos: usize,
        buf: Vec<u8>,
        buf_pos: usize,
    }

    impl<'a> std::io::Read for B64Decoder<'a> {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            while self.buf_pos >= self.buf.len() {
                if self.pos + 4 > self.input.len() {
                    return Ok(0);
                }
                let chunk = &self.input[self.pos..self.pos + 4];
                self.pos += 4;
                let d = [decode_b64(chunk[0]), decode_b64(chunk[1]),
                          decode_b64(chunk[2]), decode_b64(chunk[3])];
                self.buf.clear();
                self.buf_pos = 0;
                self.buf.push((d[0] << 2) | (d[1] >> 4));
                if chunk[2] != b'=' { self.buf.push((d[1] << 4) | (d[2] >> 2)); }
                if chunk[3] != b'=' { self.buf.push((d[2] << 6) | d[3]); }
            }
            let n = out.len().min(self.buf.len() - self.buf_pos);
            out[..n].copy_from_slice(&self.buf[self.buf_pos..self.buf_pos + n]);
            self.buf_pos += n;
            Ok(n)
        }
    }

    B64Decoder { input, pos: 0, buf: Vec::new(), buf_pos: 0 }
}

fn decode_b64(c: u8) -> u8 {
    match c {
        b'A'..=b'Z' => c - b'A',
        b'a'..=b'z' => c - b'a' + 26,
        b'0'..=b'9' => c - b'0' + 52,
        b'+' => 62,
        b'/' => 63,
        _ => 0,
    }
}

// ─── Issue activity check ────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct IssueActivity {
    pub issue_number: u64,
    pub is_assigned: bool,
    pub assignees: Vec<String>,
    pub recent_comments: u64,     // comments in last 7 days
    pub has_linked_pr: bool,
    pub linked_pr_url: Option<String>,
    pub verdict: String,          // CLEAR | CONTESTED | TAKEN
    pub signals: Vec<String>,
}

pub async fn check_issue_activity(
    client: &Client,
    token: &str,
    owner: &str,
    repo: &str,
    issue_number: u64,
) -> Result<IssueActivity> {
    let auth = build_auth(token);

    // Issue detail
    let issue: serde_json::Value = client
        .get(format!("{}/repos/{}/{}/issues/{}", GITHUB_API, owner, repo, issue_number))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await?
        .json()
        .await?;

    let is_assigned = !issue["assignees"].as_array()
        .map(|a| a.is_empty())
        .unwrap_or(true);

    let assignees: Vec<String> = issue["assignees"]
        .as_array()
        .unwrap_or(&vec![])
        .iter()
        .filter_map(|a| a["login"].as_str().map(|s| s.to_string()))
        .collect();

    // Comments in last 7 days
    let comments: Vec<serde_json::Value> = client
        .get(format!("{}/repos/{}/{}/issues/{}/comments", GITHUB_API, owner, repo, issue_number))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[("per_page", "30"), ("sort", "created"), ("direction", "desc")])
        .send()
        .await?
        .json()
        .await
        .unwrap_or_default();

    let recent_comments = comments.iter().filter(|c| {
        let created = c["created_at"].as_str().unwrap_or("");
        !created.is_empty() && days_ago(created) <= 7
    }).count() as u64;

    // Check comments for "working on it" signals
    let working_keywords = ["working on", "i'll fix", "i will fix", "wip", "in progress",
                            "taking this", "i'll take", "assigned to me", "pr incoming",
                            "submitting", "i'll submit"];
    let has_claimed = comments.iter().any(|c| {
        let body = c["body"].as_str().unwrap_or("").to_lowercase();
        working_keywords.iter().any(|kw| body.contains(kw))
    });

    // Check for linked PRs (search PRs mentioning this issue)
    let pr_search: serde_json::Value = client
        .get(format!("{}/search/issues", GITHUB_API))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[
            ("q", format!("repo:{}/{} type:pr #{}", owner, repo, issue_number).as_str()),
            ("per_page", "5"),
        ])
        .send()
        .await?
        .json()
        .await
        .unwrap_or(serde_json::json!({"items": []}));

    let linked_prs = pr_search["items"].as_array().cloned().unwrap_or_default();
    let has_linked_pr = !linked_prs.is_empty();
    let linked_pr_url = linked_prs.first()
        .and_then(|pr| pr["html_url"].as_str().map(|s| s.to_string()));

    // Verdict
    let mut signals: Vec<String> = Vec::new();
    let verdict = if has_linked_pr {
        signals.push(format!("linked PR exists: {}", linked_pr_url.as_deref().unwrap_or("")));
        "TAKEN".into()
    } else if is_assigned {
        signals.push(format!("assigned to: {}", assignees.join(", ")));
        "TAKEN".into()
    } else if has_claimed {
        signals.push("someone claimed in comments".into());
        "CONTESTED".into()
    } else if recent_comments > 3 {
        signals.push(format!("{} comments in last 7 days — active discussion", recent_comments));
        "CONTESTED".into()
    } else {
        signals.push("no assignee, no linked PR, low recent activity".into());
        "CLEAR".into()
    };

    Ok(IssueActivity {
        issue_number,
        is_assigned,
        assignees,
        recent_comments,
        has_linked_pr,
        linked_pr_url,
        verdict,
        signals,
    })
}
