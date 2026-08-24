use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

// ─── Deep company analysis ────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct CompanyAnalysis {
    pub org: String,
    pub repos: Vec<RepoSignal>,
    pub open_issues: Vec<IssueSignal>,
    pub recent_commits: Vec<CommitSignal>,
    pub roadmap_hints: Vec<String>,
    pub tech_stack: Vec<String>,
    pub pain_points: Vec<PainPoint>,
    pub discussion_threads: Vec<DiscussionSignal>,
    pub next_move_hypothesis: Vec<NextMove>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RepoSignal {
    pub name: String,
    pub description: Option<String>,
    pub stars: u64,
    pub open_issues: u64,
    pub language: Option<String>,
    pub topics: Vec<String>,
    pub pushed_days_ago: i64,
    pub has_roadmap: bool,
    pub has_contributing: bool,
    pub html_url: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct IssueSignal {
    pub number: u64,
    pub title: String,
    pub labels: Vec<String>,
    pub comments: u64,
    pub repo: String,
    pub url: String,
    pub category: IssueCategory,
    pub age_days: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub enum IssueCategory {
    Scaling,
    Integration,
    Performance,
    AiMl,
    DatabaseStorage,
    ApiDesign,
    Security,
    Documentation,
    Roadmap,
    Other,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CommitSignal {
    pub repo: String,
    pub message: String,
    pub sha_short: String,
    pub date: String,
    pub signal: CommitSignalType,
}

#[derive(Debug, Serialize, Deserialize)]
pub enum CommitSignalType {
    PerformanceFix,
    ScalingWork,
    NewIntegration,
    RefactorOrDebt,
    AiOrMlWork,
    DatabaseChange,
    BreakingChange,
    Regular,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DiscussionSignal {
    pub repo: String,
    pub title: String,
    pub category: String,
    pub url: String,
    pub comments: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct PainPoint {
    pub area: String,
    pub evidence: Vec<String>,
    pub severity: PainSeverity,
}

#[derive(Debug, Serialize, Deserialize)]
pub enum PainSeverity {
    High,
    Medium,
    Low,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct NextMove {
    pub hypothesis: String,
    pub evidence: Vec<String>,
    pub proposal_angle: String,
}

/// Deep-dive a company's GitHub org.
/// Returns structured signals: tech stack, open pain points, recent direction, roadmap hints.
pub async fn analyze_company_github(
    client: &Client,
    token: &str,
    org: &str,
    max_repos: usize,
    max_issues_per_repo: usize,
) -> Result<CompanyAnalysis> {
    let auth = format!("Bearer {}", token);

    // ── 1. Repos ──────────────────────────────────────────────────────────────
    let repos_resp: serde_json::Value = client
        .get(format!("https://api.github.com/orgs/{}/repos", org))
        .header("Authorization", &auth)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[
            ("per_page", max_repos.min(30).to_string().as_str()),
            ("sort", "pushed"),
            ("type", "public"),
        ])
        .send()
        .await?
        .json()
        .await?;

    let repo_list = repos_resp.as_array().cloned().unwrap_or_default();

    let mut repo_signals: Vec<RepoSignal> = Vec::new();
    let mut all_languages: Vec<String> = Vec::new();
    let mut all_topics: Vec<String> = Vec::new();

    for r in &repo_list {
        let name = r["name"].as_str().unwrap_or("").to_string();
        let description = r["description"].as_str().map(|s| s.to_string());
        let language = r["language"].as_str().map(|s| s.to_string());
        let stars = r["stargazers_count"].as_u64().unwrap_or(0);
        let open_issues = r["open_issues_count"].as_u64().unwrap_or(0);
        let pushed_at = r["pushed_at"].as_str().unwrap_or("");
        let pushed_days_ago = days_ago(pushed_at);
        let html_url = r["html_url"].as_str().unwrap_or("").to_string();

        let topics: Vec<String> = r["topics"]
            .as_array()
            .map(|a| a.iter().filter_map(|t| t.as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default();

        if let Some(ref lang) = language {
            if !all_languages.contains(lang) {
                all_languages.push(lang.clone());
            }
        }
        all_topics.extend(topics.iter().cloned());

        // Check for ROADMAP / CONTRIBUTING via contents API (only for top repos)
        let (has_roadmap, has_contributing) = if stars > 10 || open_issues > 5 {
            check_special_files(client, token, org, &name).await
        } else {
            (false, false)
        };

        if pushed_days_ago < 180 {
            repo_signals.push(RepoSignal {
                name,
                description,
                stars,
                open_issues,
                language,
                topics,
                pushed_days_ago,
                has_roadmap,
                has_contributing,
                html_url,
            });
        }
    }

    // Deduplicate and rank tech stack
    all_topics.sort();
    all_topics.dedup();
    all_languages.sort();
    all_languages.dedup();
    let mut tech_stack = all_languages;
    tech_stack.extend(all_topics);

    // ── 2. Issues (top 3 active repos) ───────────────────────────────────────
    let mut issue_signals: Vec<IssueSignal> = Vec::new();
    let top_repos: Vec<&RepoSignal> = repo_signals
        .iter()
        .filter(|r| r.open_issues > 0 && r.pushed_days_ago < 90)
        .take(3)
        .collect();

    for repo in top_repos {
        let issues_resp: serde_json::Value = client
            .get(format!("https://api.github.com/repos/{}/{}/issues", org, repo.name))
            .header("Authorization", &auth)
            .header("User-Agent", "networking-agent/0.1")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .query(&[
                ("state", "open"),
                ("per_page", max_issues_per_repo.min(30).to_string().as_str()),
                ("sort", "comments"),
                ("direction", "desc"),
            ])
            .send()
            .await?
            .json()
            .await?;

        if let Some(issues) = issues_resp.as_array() {
            for issue in issues.iter().take(max_issues_per_repo) {
                // Skip PRs (GitHub issues endpoint returns PRs too)
                if issue["pull_request"].is_object() {
                    continue;
                }

                let title = issue["title"].as_str().unwrap_or("").to_string();
                let number = issue["number"].as_u64().unwrap_or(0);
                let comments = issue["comments"].as_u64().unwrap_or(0);
                let url = issue["html_url"].as_str().unwrap_or("").to_string();
                let created_at = issue["created_at"].as_str().unwrap_or("");
                let age_days = days_ago(created_at);

                let labels: Vec<String> = issue["labels"]
                    .as_array()
                    .map(|a| a.iter().filter_map(|l| l["name"].as_str().map(|s| s.to_string())).collect())
                    .unwrap_or_default();

                let category = classify_issue(&title, &labels);

                issue_signals.push(IssueSignal {
                    number,
                    title,
                    labels,
                    comments,
                    repo: repo.name.clone(),
                    url,
                    category,
                    age_days,
                });
            }
        }
    }

    // ── 3. Recent commits (last 20 across top 2 repos) ────────────────────────
    let mut commit_signals: Vec<CommitSignal> = Vec::new();
    let commit_repos: Vec<&RepoSignal> = repo_signals
        .iter()
        .filter(|r| r.pushed_days_ago < 30)
        .take(2)
        .collect();

    for repo in commit_repos {
        let commits_resp: serde_json::Value = client
            .get(format!("https://api.github.com/repos/{}/{}/commits", org, repo.name))
            .header("Authorization", &auth)
            .header("User-Agent", "networking-agent/0.1")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .query(&[("per_page", "15")])
            .send()
            .await?
            .json()
            .await?;

        if let Some(commits) = commits_resp.as_array() {
            for c in commits.iter().take(15) {
                let message = c["commit"]["message"]
                    .as_str()
                    .unwrap_or("")
                    .lines()
                    .next()
                    .unwrap_or("")
                    .to_string();
                let sha = c["sha"].as_str().unwrap_or("").chars().take(7).collect::<String>();
                let date = c["commit"]["committer"]["date"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                let signal = classify_commit(&message);

                commit_signals.push(CommitSignal {
                    repo: repo.name.clone(),
                    message,
                    sha_short: sha,
                    date,
                    signal,
                });
            }
        }
    }

    // ── 4. GitHub Discussions (if enabled) ───────────────────────────────────
    let mut discussions: Vec<DiscussionSignal> = Vec::new();
    for repo in repo_signals.iter().take(2) {
        if let Ok(mut disc) = fetch_discussions(client, token, org, &repo.name).await {
            discussions.append(&mut disc);
        }
    }

    // ── 5. Synthesize pain points + next moves ────────────────────────────────
    let pain_points = extract_pain_points(&issue_signals, &commit_signals);
    let roadmap_hints = extract_roadmap_hints(&issue_signals, &discussions);
    let next_moves = hypothesize_next_moves(&pain_points, &commit_signals, &tech_stack);

    Ok(CompanyAnalysis {
        org: org.to_string(),
        repos: repo_signals,
        open_issues: issue_signals,
        recent_commits: commit_signals,
        roadmap_hints,
        tech_stack,
        pain_points,
        discussion_threads: discussions,
        next_move_hypothesis: next_moves,
    })
}

async fn check_special_files(
    client: &Client,
    token: &str,
    org: &str,
    repo: &str,
) -> (bool, bool) {
    let auth = format!("Bearer {}", token);
    let roadmap_files = ["ROADMAP.md", "docs/ROADMAP.md", "CHANGELOG.md", ".github/ROADMAP.md"];
    let contrib_files = ["CONTRIBUTING.md", ".github/CONTRIBUTING.md"];

    let mut has_roadmap = false;
    let mut has_contributing = false;

    for file in &roadmap_files {
        let url = format!("https://api.github.com/repos/{}/{}/contents/{}", org, repo, file);
        if let Ok(resp) = client.get(&url).header("Authorization", &auth).header("User-Agent", "networking-agent/0.1").send().await {
            if resp.status().is_success() {
                has_roadmap = true;
                break;
            }
        }
    }

    for file in &contrib_files {
        let url = format!("https://api.github.com/repos/{}/{}/contents/{}", org, repo, file);
        if let Ok(resp) = client.get(&url).header("Authorization", &auth).header("User-Agent", "networking-agent/0.1").send().await {
            if resp.status().is_success() {
                has_contributing = true;
                break;
            }
        }
    }

    (has_roadmap, has_contributing)
}

async fn fetch_discussions(
    client: &Client,
    token: &str,
    org: &str,
    repo: &str,
) -> Result<Vec<DiscussionSignal>> {
    // GitHub Discussions via GraphQL
    let query = format!(
        r#"{{"query": "{{ repository(owner: \"{org}\", name: \"{repo}\") {{ discussions(first: 10, orderBy: {{field: COMMENTS, direction: DESC}}) {{ nodes {{ title category {{ name }} url comments {{ totalCount }} }} }} }} }}"}}"#,
        org = org,
        repo = repo,
    );

    let resp: serde_json::Value = client
        .post("https://api.github.com/graphql")
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("Content-Type", "application/json")
        .body(query)
        .send()
        .await?
        .json()
        .await?;

    let nodes = &resp["data"]["repository"]["discussions"]["nodes"];
    let mut discussions = Vec::new();

    if let Some(arr) = nodes.as_array() {
        for d in arr {
            let title = d["title"].as_str().unwrap_or("").to_string();
            let category = d["category"]["name"].as_str().unwrap_or("General").to_string();
            let url = d["url"].as_str().unwrap_or("").to_string();
            let comments = d["comments"]["totalCount"].as_u64().unwrap_or(0);

            if !title.is_empty() {
                discussions.push(DiscussionSignal {
                    repo: repo.to_string(),
                    title,
                    category,
                    url,
                    comments,
                });
            }
        }
    }

    Ok(discussions)
}

fn classify_issue(title: &str, labels: &[String]) -> IssueCategory {
    let t = title.to_lowercase();
    let l: Vec<String> = labels.iter().map(|s| s.to_lowercase()).collect();
    let label_str = l.join(" ");
    let haystack = format!("{} {}", t, label_str);

    if haystack.contains("scale") || haystack.contains("performance") || haystack.contains("latency")
        || haystack.contains("throughput") || haystack.contains("bottleneck") || haystack.contains("slow")
        || haystack.contains("memory") || haystack.contains("cpu") || haystack.contains("load")
    {
        return IssueCategory::Scaling;
    }
    if haystack.contains("ai") || haystack.contains("ml") || haystack.contains("llm")
        || haystack.contains("embedding") || haystack.contains("vector") || haystack.contains("inference")
        || haystack.contains("model") || haystack.contains("gpt") || haystack.contains("openai")
    {
        return IssueCategory::AiMl;
    }
    if haystack.contains("database") || haystack.contains("postgres") || haystack.contains("mysql")
        || haystack.contains("sqlite") || haystack.contains("redis") || haystack.contains("migration")
        || haystack.contains("schema") || haystack.contains("query") || haystack.contains("index")
        || haystack.contains("storage")
    {
        return IssueCategory::DatabaseStorage;
    }
    if haystack.contains("integrat") || haystack.contains("webhook") || haystack.contains("api")
        || haystack.contains("oauth") || haystack.contains("plugin") || haystack.contains("connector")
        || haystack.contains("import") || haystack.contains("export") || haystack.contains("sync")
    {
        return IssueCategory::Integration;
    }
    if haystack.contains("security") || haystack.contains("auth") || haystack.contains("permission")
        || haystack.contains("cve") || haystack.contains("vulnerability") || haystack.contains("encrypt")
    {
        return IssueCategory::Security;
    }
    if haystack.contains("roadmap") || haystack.contains("rfc") || haystack.contains("proposal")
        || label_str.contains("roadmap") || label_str.contains("enhancement")
    {
        return IssueCategory::Roadmap;
    }
    if haystack.contains("api") || haystack.contains("endpoint") || haystack.contains("rest")
        || haystack.contains("graphql") || haystack.contains("grpc") || haystack.contains("sdk")
    {
        return IssueCategory::ApiDesign;
    }
    if haystack.contains("perf") || haystack.contains("optim") || haystack.contains("cache") {
        return IssueCategory::Performance;
    }
    IssueCategory::Other
}

fn classify_commit(message: &str) -> CommitSignalType {
    let m = message.to_lowercase();
    if m.contains("perf") || m.contains("optim") || m.contains("faster") || m.contains("speed") || m.contains("latency") {
        return CommitSignalType::PerformanceFix;
    }
    if m.contains("scale") || m.contains("shard") || m.contains("cluster") || m.contains("partition") || m.contains("horizontal") {
        return CommitSignalType::ScalingWork;
    }
    if m.contains("ai") || m.contains("llm") || m.contains("embedding") || m.contains("vector") || m.contains("inference") || m.contains("model") {
        return CommitSignalType::AiOrMlWork;
    }
    if m.contains("integrat") || m.contains("webhook") || m.contains("connector") || m.contains("plugin") {
        return CommitSignalType::NewIntegration;
    }
    if m.contains("db") || m.contains("migration") || m.contains("schema") || m.contains("database") || m.contains("index") {
        return CommitSignalType::DatabaseChange;
    }
    if m.contains("refactor") || m.contains("cleanup") || m.contains("debt") || m.contains("todo") {
        return CommitSignalType::RefactorOrDebt;
    }
    if m.contains("breaking") || m.starts_with("!") || m.contains("major:") {
        return CommitSignalType::BreakingChange;
    }
    CommitSignalType::Regular
}

fn extract_pain_points(
    issues: &[IssueSignal],
    commits: &[CommitSignal],
) -> Vec<PainPoint> {
    let mut pain_map: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();

    for issue in issues {
        let area = match &issue.category {
            IssueCategory::Scaling => "Scaling / Performance",
            IssueCategory::AiMl => "AI/ML Integration",
            IssueCategory::DatabaseStorage => "Database / Storage",
            IssueCategory::Integration => "Integrations",
            IssueCategory::Security => "Security / Auth",
            IssueCategory::ApiDesign => "API Design",
            IssueCategory::Roadmap => "Roadmap",
            IssueCategory::Performance => "Performance",
            _ => "General",
        };
        pain_map
            .entry(area.to_string())
            .or_default()
            .push(format!("Issue #{}: {} ({} comments, {} days old)", issue.number, issue.title, issue.comments, issue.age_days));
    }

    for commit in commits {
        let area = match &commit.signal {
            CommitSignalType::PerformanceFix | CommitSignalType::ScalingWork => "Scaling / Performance",
            CommitSignalType::AiOrMlWork => "AI/ML Integration",
            CommitSignalType::DatabaseChange => "Database / Storage",
            CommitSignalType::NewIntegration => "Integrations",
            _ => continue,
        };
        pain_map
            .entry(area.to_string())
            .or_default()
            .push(format!("Commit [{}]: {}", commit.sha_short, commit.message));
    }

    let mut pain_points: Vec<PainPoint> = pain_map
        .into_iter()
        .map(|(area, evidence)| {
            let severity = if evidence.len() >= 4 {
                PainSeverity::High
            } else if evidence.len() >= 2 {
                PainSeverity::Medium
            } else {
                PainSeverity::Low
            };
            PainPoint { area, evidence, severity }
        })
        .collect();

    pain_points.sort_by(|a, b| {
        let score = |s: &PainSeverity| match s { PainSeverity::High => 3, PainSeverity::Medium => 2, PainSeverity::Low => 1 };
        score(&b.severity).cmp(&score(&a.severity))
    });

    pain_points
}

fn extract_roadmap_hints(
    issues: &[IssueSignal],
    discussions: &[DiscussionSignal],
) -> Vec<String> {
    let mut hints = Vec::new();

    for issue in issues.iter().filter(|i| matches!(i.category, IssueCategory::Roadmap)) {
        hints.push(format!("[Issue #{}] {} ({})", issue.number, issue.title, issue.url));
    }
    for d in discussions.iter().filter(|d| d.category.to_lowercase() == "ideas" || d.category.to_lowercase() == "roadmap") {
        hints.push(format!("[Discussion] {} — {} comments ({})", d.title, d.comments, d.url));
    }

    hints
}

fn hypothesize_next_moves(
    pain_points: &[PainPoint],
    commits: &[CommitSignal],
    tech_stack: &[String],
) -> Vec<NextMove> {
    let mut moves = Vec::new();

    // Pattern: heavy perf/scaling pain → distributed systems proposal
    let has_scaling_pain = pain_points.iter().any(|p| p.area.contains("Scaling") && matches!(p.severity, PainSeverity::High | PainSeverity::Medium));
    let has_db_pain = pain_points.iter().any(|p| p.area.contains("Database"));
    let has_ai_work = commits.iter().any(|c| matches!(c.signal, CommitSignalType::AiOrMlWork))
        || pain_points.iter().any(|p| p.area.contains("AI"));
    let has_integration_pain = pain_points.iter().any(|p| p.area.contains("Integration"));

    let stack_lower: Vec<String> = tech_stack.iter().map(|s| s.to_lowercase()).collect();
    let is_rust = stack_lower.contains(&"rust".to_string());
    let is_go = stack_lower.contains(&"go".to_string());
    let _is_python = stack_lower.contains(&"python".to_string());

    if has_scaling_pain {
        let stack_note = if is_rust { "async Rust (tokio) for zero-cost async I/O" }
            else if is_go { "Go goroutines + channels for horizontal fan-out" }
            else { "async processing + queue-based fan-out" };
        moves.push(NextMove {
            hypothesis: "Hitting single-node throughput ceiling — next move is horizontal scale or async processing redesign".to_string(),
            evidence: pain_points.iter().filter(|p| p.area.contains("Scaling")).flat_map(|p| p.evidence.iter().cloned()).take(3).collect(),
            proposal_angle: format!(
                "Proposal: Redesign the [bottleneck component] using {}. Show concrete throughput numbers before/after. Open with: 'I noticed your issue #X around [specific pain] — I mapped out what the bottleneck is and drafted an approach for [their stack]. Happy to discuss the design.'",
                stack_note
            ),
        });
    }

    if has_db_pain {
        moves.push(NextMove {
            hypothesis: "DB layer becoming a bottleneck — likely need read replicas, connection pooling, or schema optimisation".to_string(),
            evidence: pain_points.iter().filter(|p| p.area.contains("Database")).flat_map(|p| p.evidence.iter().cloned()).take(3).collect(),
            proposal_angle: "Proposal: Audit their query patterns from open issues, draft a migration plan or pooling strategy. Open with query analysis + concrete index suggestion, not a sales pitch.".to_string(),
        });
    }

    if has_ai_work {
        let angle = if is_rust {
            "Rust-native AI integration: candle (Hugging Face) or llm.rs for inference without Python dependency"
        } else {
            "LLM integration pattern: streaming responses, structured outputs, cost-per-call budgeting"
        };
        moves.push(NextMove {
            hypothesis: "Adding AI/LLM features — common next challenges: latency, cost, hallucination handling, structured output".to_string(),
            evidence: commits.iter().filter(|c| matches!(c.signal, CommitSignalType::AiOrMlWork)).map(|c| format!("[{}] {}", c.sha_short, c.message)).take(3).collect(),
            proposal_angle: format!(
                "Proposal: {}. Specific angle: pick one open AI issue, write a working prototype with benchmarks, then open discussion.",
                angle
            ),
        });
    }

    if has_integration_pain {
        moves.push(NextMove {
            hypothesis: "Integration surface growing — likely need a plugin/webhook system or unified connector pattern".to_string(),
            evidence: pain_points.iter().filter(|p| p.area.contains("Integration")).flat_map(|p| p.evidence.iter().cloned()).take(3).collect(),
            proposal_angle: "Proposal: Design a typed webhook/event bus or MCP-style connector registry. Draft the interface, show how it solves 3 of their open integration issues at once.".to_string(),
        });
    }

    if moves.is_empty() {
        // Generic fallback: contribution + architecture discussion
        moves.push(NextMove {
            hypothesis: "No dominant pain signal — company is in growth/feature phase, best entry is contributing to highest-star repo".to_string(),
            evidence: Vec::new(),
            proposal_angle: "Find highest-commented open issue → write a design doc → PR that doc first (no code yet) → start a discussion.".to_string(),
        });
    }

    moves
}

// ─── Proposal generator ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct TechnicalProposal {
    pub company: String,
    pub subject: String,
    pub problem_statement: String,
    pub evidence_summary: Vec<String>,
    pub proposed_solution: String,
    pub why_now: String,
    pub open_question: String,
    pub discussion_opener: String,
    pub relevant_issue_urls: Vec<String>,
    pub estimated_impact: String,
}

/// Generate a technical proposal for a company based on deep analysis.
/// This is NOT a job application — it's an engineering discussion opener.
/// Format: problem they're about to hit + concrete solution + open question.
pub fn draft_technical_proposal(
    analysis: &CompanyAnalysis,
    company_name: &str,
    your_focus_area: Option<&str>,
) -> Vec<TechnicalProposal> {
    let mut proposals = Vec::new();

    for next_move in &analysis.next_move_hypothesis {
        // Pick most relevant issues as evidence
        let relevant_issues: Vec<&IssueSignal> = analysis.open_issues.iter()
            .filter(|i| {
                let area = &next_move.hypothesis.to_lowercase();
                let category_match = (area.contains("scal") && matches!(i.category, IssueCategory::Scaling | IssueCategory::Performance))
                    || (area.contains("ai") && matches!(i.category, IssueCategory::AiMl))
                    || (area.contains("db") || area.contains("database")) && matches!(i.category, IssueCategory::DatabaseStorage)
                    || (area.contains("integrat") && matches!(i.category, IssueCategory::Integration));
                category_match || i.comments > 5
            })
            .take(3)
            .collect();

        let issue_urls: Vec<String> = relevant_issues.iter().map(|i| i.url.clone()).collect();

        let evidence_summary: Vec<String> = relevant_issues.iter()
            .map(|i| format!("#{}: {} ({} comments, {} days open)", i.number, i.title, i.comments, i.age_days))
            .chain(next_move.evidence.iter().take(2).cloned())
            .collect();

        // Focus area filter
        if let Some(focus) = your_focus_area {
            let focus_lower = focus.to_lowercase();
            let hypothesis_lower = next_move.hypothesis.to_lowercase();
            let proposal_lower = next_move.proposal_angle.to_lowercase();
            if !hypothesis_lower.contains(&focus_lower) && !proposal_lower.contains(&focus_lower) {
                continue;
            }
        }

        let (subject, problem, solution, why_now, open_q, opener, impact) =
            craft_proposal_content(company_name, &analysis.tech_stack, next_move, &evidence_summary);

        proposals.push(TechnicalProposal {
            company: company_name.to_string(),
            subject,
            problem_statement: problem,
            evidence_summary,
            proposed_solution: solution,
            why_now,
            open_question: open_q,
            discussion_opener: opener,
            relevant_issue_urls: issue_urls,
            estimated_impact: impact,
        });
    }

    proposals
}

fn craft_proposal_content(
    company: &str,
    tech_stack: &[String],
    next_move: &NextMove,
    evidence: &[String],
) -> (String, String, String, String, String, String, String) {
    let stack_str = tech_stack.iter().take(4).cloned().collect::<Vec<_>>().join(", ");
    let evidence_str = evidence.first().map(|e| e.as_str()).unwrap_or("several open issues");

    let h = &next_move.hypothesis;
    let pa = &next_move.proposal_angle;

    // Tailor by hypothesis type
    if h.contains("throughput") || h.contains("horizontal scale") {
        let subject = format!("Scaling idea for {}", company);
        let problem = format!(
            "{company} is hitting a throughput ceiling based on {evidence_str}. At current growth, this becomes a production incident before the next major feature ships."
        );
        let solution = pa.replace("Proposal: ", "");
        let why_now = "Load issues compound — fixing post-incident costs 3-5× more than designing for it now. The pattern in your commit history suggests you're aware of this.".to_string();
        let open_q = format!("What's the current p99 latency target for the bottleneck path, and have you looked at [specific approach] for your {} stack?", stack_str);
        let opener = format!(
            "Hi — I've been going through {company}'s repo and mapped the throughput bottleneck pattern in [{evidence_str}]. I drafted a scale-out approach for your {stack_str} stack — happy to share the design doc and discuss. Would that be useful?"
        );
        let impact = "Potential: 5-10× throughput before next engineering sprint needed. Prevents production incident.".to_string();
        return (subject, problem, solution, why_now, open_q, opener, impact);
    }

    if h.contains("AI") || h.contains("LLM") {
        let subject = format!("AI integration design for {}", company);
        let problem = format!(
            "{company} is adding AI/LLM features ({evidence_str}). The common failure modes at this stage: unbounded latency, hallucination in critical paths, and cost spikes — none of which show up until production load."
        );
        let solution = pa.replace("Proposal: ", "");
        let why_now = "Early AI integration choices are load-bearing — the inference path, retry logic, and cost controls get baked into the architecture. Retrofitting is painful.".to_string();
        let open_q = "Are you streaming responses or batching? And what's the plan for fallback when the model returns malformed structured output?".to_string();
        let opener = format!(
            "Hi — I noticed {company}'s work on AI integration ({evidence_str}). I've been building {stack_str} LLM pipelines and hit the exact failure modes you'll run into at scale. Drafted some notes on the design decisions that actually matter here — would be happy to share and get your thoughts."
        );
        let impact = "Prevents: production hallucination incidents, 10-100× cost overruns, latency regression. Saves weeks of debugging at scale.".to_string();
        return (subject, problem, solution, why_now, open_q, opener, impact);
    }

    if h.contains("DB") || h.contains("database") {
        let subject = format!("Database architecture note for {}", company);
        let problem = format!(
            "Based on {evidence_str}, {company}'s DB layer is showing early scaling stress. This pattern typically precedes write-contention incidents as user volume grows."
        );
        let solution = pa.replace("Proposal: ", "");
        let why_now = "DB migrations under load are high-risk. The window to fix schema/indexing decisions is before the data volume makes it painful.".to_string();
        let open_q = "What's the current read/write ratio, and are you using connection pooling at the application layer or relying on the DB to handle it?".to_string();
        let opener = format!(
            "Hi — went through {company}'s open issues and noticed the DB pattern in {evidence_str}. I've seen this exact bottleneck at this scale before. Happy to share a write-up on what the fix looks like for a {stack_str} stack."
        );
        let impact = "Prevents: connection saturation, query timeout incidents. Extends DB runway 6-12 months without hardware upgrade.".to_string();
        return (subject, problem, solution, why_now, open_q, opener, impact);
    }

    if h.contains("Integration") || h.contains("plugin") {
        let subject = format!("Integration architecture for {}", company);
        let problem = format!(
            "{company} has {evidence_str}. Adding integrations one-by-one creates maintenance debt that scales linearly — each new connector is another surface for breakage."
        );
        let solution = pa.replace("Proposal: ", "");
        let why_now = "The integration tax compounds. Every new connector added without a unified pattern means N tests to maintain, N auth flows to debug, N error surfaces to monitor.".to_string();
        let open_q = "How are you currently handling auth for third-party connectors — per-integration OAuth flows, or is there a centralized token store?".to_string();
        let opener = format!(
            "Hi — I've been looking at {company}'s integration roadmap through the open issues. I designed a typed connector pattern for a {stack_str} system that solved this class of problem — happy to share the design and see if it's relevant to where you're headed."
        );
        let impact = "Converts: O(N) per-connector maintenance to O(1) for new integrations. Unblocks the integration roadmap.".to_string();
        return (subject, problem, solution, why_now, open_q, opener, impact);
    }

    // Generic fallback
    let subject = format!("Technical discussion for {}", company);
    let problem = format!("Based on {evidence_str}, {company} has interesting technical challenges worth discussing.");
    let solution = pa.replace("Proposal: ", "");
    let why_now = "Early discussions on architecture direction compound — getting the design right before scale is easier than retrofitting.".to_string();
    let open_q = "What's the biggest technical constraint you're trying to work around right now?".to_string();
    let opener = format!(
        "Hi — I've been reading through {company}'s repo and have some thoughts on the {stack_str} architecture direction. Would be happy to share notes and discuss."
    );
    let impact = "Opens an engineering discussion that shows depth and genuine interest in the problem space.".to_string();
    (subject, problem, solution, why_now, open_q, opener, impact)
}

// ─── Utility ──────────────────────────────────────────────────────────────────

fn days_ago(iso: &str) -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let ts = parse_iso_to_unix(iso).unwrap_or(0);
    (now - ts) / 86400
}

fn parse_iso_to_unix(s: &str) -> Option<i64> {
    let parts: Vec<&str> = s.splitn(2, 'T').collect();
    let date_parts: Vec<i64> = parts.first()?.split('-')
        .filter_map(|p| p.parse().ok())
        .collect();
    if date_parts.len() != 3 { return None; }
    let (y, m, d) = (date_parts[0], date_parts[1], date_parts[2]);
    let years = y - 1970;
    let leap = years / 4 - years / 100 + years / 400;
    let month_days = [0i64, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    let extra = if m > 2 && (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)) { 1 } else { 0 };
    let days = years * 365 + leap + month_days[(m - 1) as usize] + extra + d - 1;
    Some(days * 86400)
}
