use anyhow::Result;
use chrono;
use reqwest::Client;
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    tool, tool_handler, tool_router,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

use crate::compliance::ComplianceLayer;
use crate::tools::{apollo, clearbit, crunchbase, email_finder, github, hiring, jobs, platforms, producthunt, scorer, tech_stack, yc};

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct SearchUsersParams {
    /// Search query e.g. "CTO", "founder", "protocol engineer"
    pub query: String,
    /// Location filter e.g. "San Francisco", "Singapore", "NYC"
    pub location: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct OrgMembersParams {
    /// GitHub org name e.g. "openai", "vercel", "paradigm-xyz"
    pub org: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct OpenIssuesParams {
    /// Repo owner e.g. "rust-lang"
    pub owner: String,
    /// Repo name e.g. "rust"
    pub repo: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct YCBatchParams {
    /// YC batch e.g. "W24", "S25", "W25"
    pub batch: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct YCSearchParams {
    /// Keyword search e.g. "AI", "fintech", "protocol", "crypto"
    pub query: String,
    /// Location filter e.g. "San Francisco", "New York", "Singapore", "London", "" for all
    pub location: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct SaveProspectParams {
    pub name: String,
    pub github: Option<String>,
    pub email: Option<String>,
    pub company: Option<String>,
    pub role: Option<String>,
    pub location: Option<String>,
    pub notes: Option<String>,
    pub source: Option<String>,
}

#[derive(Debug, Clone)]
pub struct NetworkingServer {
    tool_router: ToolRouter<Self>,
    http_client: Client,
    db: SqlitePool,
    github_token: String,
    hunter_api_key: String,
    crunchbase_api_key: String,
    producthunt_api_token: String,
    apollo_api_key: String,
    clearbit_api_key: String,
    compliance: ComplianceLayer,
}

impl NetworkingServer {
    pub fn new(
        db: SqlitePool,
        github_token: String,
        hunter_api_key: String,
        crunchbase_api_key: String,
        producthunt_api_token: String,
        apollo_api_key: String,
        clearbit_api_key: String,
        compliance: ComplianceLayer,
    ) -> Self {
        Self {
            tool_router: Self::tool_router(),
            http_client: Client::new(),
            db,
            github_token,
            hunter_api_key,
            crunchbase_api_key,
            producthunt_api_token,
            apollo_api_key,
            clearbit_api_key,
            compliance,
        }
    }
}

#[tool_router]
impl NetworkingServer {
    #[tool(description = "Search GitHub users by role and location. Returns profile data including email, company, repos.")]
    async fn search_github_users(
        &self,
        Parameters(params): Parameters<SearchUsersParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_github_users").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("query={} location={}", params.query, params.location);
        let result = match github::search_users(&self.http_client, &self.github_token, &params.query, &params.location).await {
            Ok(users) => serde_json::to_string_pretty(&users).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let clean = self.compliance.pii.redact(&input);
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "search_github_users", &clean, &result, t, &pii).await;
        result
    }

    #[tool(description = "Get all public members of a GitHub organization. Good for finding engineers at target companies.")]
    async fn get_org_members(&self, Parameters(params): Parameters<OrgMembersParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("get_org_members").await { return e; }
        let t = self.compliance.audit.start();
        let result = match github::get_org_members(&self.http_client, &self.github_token, &params.org).await {
            Ok(users) => serde_json::to_string_pretty(&users).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "get_org_members", &params.org, &result, t, &pii).await;
        result
    }

    #[tool(description = "Find open issues in a GitHub repo tagged 'good first issue' or 'help wanted'. These are warm entry points.")]
    async fn find_open_issues(&self, Parameters(params): Parameters<OpenIssuesParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("find_open_issues").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{}/{}", params.owner, params.repo);
        let result = match github::find_open_issues(&self.http_client, &self.github_token, &params.owner, &params.repo).await {
            Ok(issues) => serde_json::to_string_pretty(&issues).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "find_open_issues", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Get YC companies from a specific batch e.g. W25, S24, W24. Returns name, description, website, location, tags.")]
    async fn get_yc_companies(&self, Parameters(params): Parameters<YCBatchParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("get_yc_companies").await { return e; }
        let t = self.compliance.audit.start();
        let result = match yc::scrape_yc_companies(&self.http_client, &params.batch).await {
            Ok(companies) => serde_json::to_string_pretty(&companies).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "get_yc_companies", &params.batch, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search YC companies by keyword and location. Works globally: USA, Singapore, London, NYC, SF, etc.")]
    async fn search_yc_companies(&self, Parameters(params): Parameters<YCSearchParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_yc_companies").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("query={} location={}", params.query, params.location);
        let result = match yc::search_yc_companies(&self.http_client, &params.query, &params.location).await {
            Ok(companies) => serde_json::to_string_pretty(&companies).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_yc_companies", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Save a prospect to the local database for tracking outreach.")]
    async fn save_prospect(&self, Parameters(params): Parameters<SaveProspectParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("save_prospect").await { return e; }
        let t = self.compliance.audit.start();
        let input = self.compliance.pii.redact(&format!("name={} company={:?}", params.name, params.company));
        let result = sqlx::query(
            r#"
            INSERT INTO prospects (name, github, email, company, role, location, notes, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(github) DO UPDATE SET
                name = excluded.name,
                email = COALESCE(excluded.email, email),
                company = COALESCE(excluded.company, company),
                notes = COALESCE(excluded.notes, notes)
            "#,
        )
        .bind(&params.name)
        .bind(&params.github)
        .bind(&params.email)
        .bind(&params.company)
        .bind(&params.role)
        .bind(&params.location)
        .bind(&params.notes)
        .bind(&params.source)
        .execute(&self.db)
        .await;

        let out = match result {
            Ok(r) => format!("Saved prospect '{}' (row id: {})", params.name, r.last_insert_rowid()),
            Err(e) => format!("Error saving prospect: {}", e),
        };
        self.compliance.audit.log(&self.db, "save_prospect", &input, &out, t, &[]).await;
        out
    }

    #[tool(description = "List all saved prospects from the database.")]
    async fn list_prospects(&self) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("list_prospects").await { return e; }
        let t = self.compliance.audit.start();
        let rows: Result<Vec<serde_json::Value>, _> = sqlx::query_as::<_, (i64, String, Option<String>, Option<String>, Option<String>, Option<String>, String)>(
            "SELECT id, name, github, email, company, role, outreach_status FROM prospects ORDER BY created_at DESC"
        )
        .fetch_all(&self.db)
        .await
        .map(|rows| rows.into_iter().map(|(id, name, github, email, company, role, status)| {
            serde_json::json!({ "id": id, "name": name, "github": github, "email": email, "company": company, "role": role, "status": status })
        }).collect());

        let result = match rows {
            Ok(data) => serde_json::to_string_pretty(&data).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "list_prospects", "all", &result, t, &pii).await;
        result
    }

    #[tool(description = "Find GitHub team members for a YC company. Searches GitHub for the company org by name/website domain, returns up to 10 team members with full profiles (email, bio, repos, followers). Use this after get_yc_companies to find the actual people to reach out to.")]
    async fn get_yc_company_team(
        &self,
        Parameters(params): Parameters<YCCompanyTeamParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("get_yc_company_team").await { return e; }
        let t = self.compliance.audit.start();
        let result = match github::find_company_team(&self.http_client, &self.github_token, &params.company_name, params.website.as_deref(), params.github_org.as_deref()).await {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "get_yc_company_team", &params.company_name, &result, t, &pii).await;
        result
    }

    #[tool(description = "Update outreach status for a prospect. Status values: new, researched, github_engaged, x_engaged, emailed, replied, meeting_scheduled.")]
    async fn update_prospect_status(
        &self,
        Parameters(params): Parameters<UpdateStatusParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("update_prospect_status").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("id={} status={}", params.id, params.status);
        let result = sqlx::query("UPDATE prospects SET outreach_status = ? WHERE id = ?")
            .bind(&params.status)
            .bind(params.id)
            .execute(&self.db)
            .await;
        let out = match result {
            Ok(_) => format!("Updated prospect {} status to '{}'", params.id, params.status),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "update_prospect_status", &input, &out, t, &[]).await;
        out
    }

    #[tool(description = "Detect tech stack used by a company website. Uses WebReveal API (free, live detection, no cache). Pass the full website URL e.g. 'https://stripe.com'. Returns technologies grouped by category (framework, analytics, CDN, language, etc).")]
    async fn lookup_tech_stack(
        &self,
        Parameters(params): Parameters<TechStackParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("lookup_tech_stack").await { return e; }
        let t = self.compliance.audit.start();
        let result = match tech_stack::lookup_tech_stack(&self.http_client, &params.url).await {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "lookup_tech_stack", &params.url, &result, t, &[]).await;
        result
    }

    #[tool(description = "Find email addresses for a company domain using Hunter.io. Returns emails with name, role, confidence score. Requires HUNTER_API_KEY env var (free tier: 25 searches/mo at hunter.io). Pass domain without protocol e.g. 'stripe.com'.")]
    async fn find_company_emails(
        &self,
        Parameters(params): Parameters<FindEmailsParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("find_company_emails").await { return e; }
        let t = self.compliance.audit.start();
        let result = match email_finder::find_emails(&self.http_client, &self.hunter_api_key, &params.domain, params.limit.unwrap_or(10)).await {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "find_company_emails", &params.domain, &result, t, &pii).await;
        result
    }

    #[tool(description = "Search remote job listings from RemoteOK. Free, no API key needed. Filter by tags e.g. 'rust', 'typescript,senior', 'python,ml'. Leave tags empty for all remote jobs. Returns title, company, url, salary, description snippet.")]
    async fn search_jobs(
        &self,
        Parameters(params): Parameters<SearchJobsParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_jobs").await { return e; }
        let t = self.compliance.audit.start();
        let tags = params.tags.as_deref().unwrap_or("");
        let limit = params.limit.unwrap_or(20);
        let result = match jobs::search_remoteok(&self.http_client, tags, limit).await {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_jobs", tags, &result, t, &[]).await;
        result
    }

    #[tool(description = "Score and rank open GitHub issues in a repo by contribution opportunity. Scoring factors: no linked PR (+30), unassigned (+20), stack match Rust/Python/Go/TS (+5-20), recent (<14 days +15), repo active (+10), has description (+5). Returns issues ranked best-first with score and signals explaining why. Use list_org_repos first to find which repos to scan.")]
    async fn score_repo_issues(
        &self,
        Parameters(params): Parameters<ScoreIssuesParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("score_repo_issues").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{}/{}", params.owner, params.repo);
        let result = match scorer::score_repo_issues(&self.http_client, &self.github_token, &params.owner, &params.repo).await {
            Ok(issues) => serde_json::to_string_pretty(&issues).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "score_repo_issues", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "List public repos for a GitHub org, sorted by most recently active. Filters out archived repos and repos with zero open issues. Use this before score_repo_issues to find which repos are worth scanning. min_stars filters noisy forks (recommend 0 for small startups, 5+ for large orgs).")]
    async fn list_org_repos(
        &self,
        Parameters(params): Parameters<ListOrgReposParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("list_org_repos").await { return e; }
        let t = self.compliance.audit.start();
        let min_stars = params.min_stars.unwrap_or(0);
        let result = match scorer::list_org_repos(&self.http_client, &self.github_token, &params.org, min_stars).await {
            Ok(repos) => serde_json::to_string_pretty(&repos).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "list_org_repos", &params.org, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search the latest HN 'Ask HN: Who is Hiring?' thread for companies matching a query. Free, no API key. Good queries: 'Rust remote', 'data engineer', 'AI infra', 'protocol', 'founding engineer'. Returns raw job posts with company context and HN link. Use this to find companies actively hiring RIGHT NOW.")]
    async fn search_hn_hiring(
        &self,
        Parameters(params): Parameters<HnHiringParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_hn_hiring").await { return e; }
        let t = self.compliance.audit.start();
        let limit = params.limit.unwrap_or(15);
        let result = match hiring::search_hn_hiring(&self.http_client, &params.query, limit).await {
            Ok(posts) => serde_json::to_string_pretty(&posts).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_hn_hiring", &params.query, &result, t, &[]).await;
        result
    }

    #[tool(description = "Track a contribution (PR or issue comment) you submitted to a company's repo. Links to a prospect by ID. status: drafted | submitted | acknowledged | merged | rejected. Call this after opening a PR or posting a meaningful issue comment so you know when to follow up with an email.")]
    async fn track_contribution(
        &self,
        Parameters(params): Parameters<TrackContributionParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("track_contribution").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("prospect={:?} repo={}/{} issue={:?}", params.prospect_id, params.repo_owner, params.repo_name, params.issue_number);
        let submitted_at = if params.status.as_deref().unwrap_or("drafted") == "submitted" {
            Some(chrono::Utc::now().to_rfc3339())
        } else {
            None
        };
        let result = sqlx::query(
            r#"
            INSERT INTO contributions
                (prospect_id, repo_owner, repo_name, issue_number, issue_title, contribution_type, pr_url, status, notes, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(params.prospect_id)
        .bind(&params.repo_owner)
        .bind(&params.repo_name)
        .bind(params.issue_number.map(|n| n as i64))
        .bind(&params.issue_title)
        .bind(params.contribution_type.as_deref().unwrap_or("pr"))
        .bind(&params.pr_url)
        .bind(params.status.as_deref().unwrap_or("drafted"))
        .bind(&params.notes)
        .bind(&submitted_at)
        .execute(&self.db)
        .await;

        let out = match result {
            Ok(r) => format!("Tracked contribution (id: {})", r.last_insert_rowid()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "track_contribution", &input, &out, t, &[]).await;
        out
    }

    #[tool(description = "Search Crunchbase for funded startups. Filters: keyword (company name/description), min_funding_usd (e.g. 500000 for $500K+), max_employees ('10','50','100','250'), category slug (e.g. 'artificial-intelligence','developer-tools','data-analytics'). Returns company name, funding total, team size, website, description. Requires CRUNCHBASE_API_KEY env var (free: 200 req/mo at data.crunchbase.com).")]
    async fn search_crunchbase(
        &self,
        Parameters(params): Parameters<CrunchbaseParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_crunchbase").await { return e; }
        let t = self.compliance.audit.start();
        let keyword = params.keyword.as_deref().unwrap_or("");
        let input = format!("kw={} funding>={:?} emp={:?}", keyword, params.min_funding_usd, params.max_employees);
        let result = match crunchbase::search_organizations(
            &self.http_client,
            &self.crunchbase_api_key,
            keyword,
            params.min_funding_usd,
            params.max_employees.as_deref(),
            params.category.as_deref(),
            params.limit.unwrap_or(15),
        ).await {
            Ok(orgs) => serde_json::to_string_pretty(&orgs).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_crunchbase", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search ProductHunt for recently launched products. Good for finding companies that just shipped — they need engineers RIGHT NOW. topic: 'developer-tools','artificial-intelligence','data-science','open-source','productivity'. days_back: how far back to search (default 30). Returns product name, tagline, website, votes, and maker profiles with Twitter/GitHub handles. Requires PRODUCTHUNT_API_TOKEN env var.")]
    async fn search_producthunt(
        &self,
        Parameters(params): Parameters<ProductHuntParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_producthunt").await { return e; }
        let t = self.compliance.audit.start();
        let topic = params.topic.as_deref();
        let days_back = params.days_back.unwrap_or(30);
        let input = format!("topic={:?} days={}", topic, days_back);
        let result = match producthunt::search_posts(
            &self.http_client,
            &self.producthunt_api_token,
            topic,
            days_back,
            params.limit.unwrap_or(20),
        ).await {
            Ok(posts) => serde_json::to_string_pretty(&posts).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_producthunt", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search We Work Remotely job listings. Free RSS feed, no API key. category: 'programming', 'devops', 'design', 'product', 'marketing' or empty for all. query filters by keyword in title+description. Returns real remote jobs posted in last 30 days.")]
    async fn search_wwr(
        &self,
        Parameters(params): Parameters<WwrParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_wwr").await { return e; }
        let t = self.compliance.audit.start();
        let category = params.category.as_deref().unwrap_or("");
        let query = params.query.as_deref().unwrap_or("");
        let result = match platforms::search_wwr(&self.http_client, query, category).await {
            Ok(jobs) => serde_json::to_string_pretty(&jobs).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_wwr", query, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search Work at a Startup — YC companies actively hiring. Extracts live job listings from the site. Returns company name, YC batch, one-liner, role, salary, location, and direct apply URL. remote_only=true filters to fully remote positions. This is the highest-signal job source: YC companies vetted, founders often reply personally.")]
    async fn search_workatastartup(
        &self,
        Parameters(params): Parameters<WasParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_workatastartup").await { return e; }
        let t = self.compliance.audit.start();
        let query = params.query.as_deref().unwrap_or("");
        let remote_only = params.remote_only.unwrap_or(true);
        let result = match platforms::search_workatastartup(&self.http_client, query, remote_only).await {
            Ok(jobs) => serde_json::to_string_pretty(&jobs).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_workatastartup", query, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search GitHub repos by language and/or topics to find companies building in your stack. Returns org name, stars, open issues, last active date. Pipe org into list_org_repos + score_repo_issues to find contribution targets. topics examples: 'data-pipeline', 'llm', 'distributed-systems', 'cli', 'protocol'. language examples: 'Rust', 'Python', 'Go'.")]
    async fn search_github_repos(
        &self,
        Parameters(params): Parameters<GitHubRepoSearchParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_github_repos").await { return e; }
        let t = self.compliance.audit.start();
        let language = params.language.as_deref().unwrap_or("");
        let topics: Vec<&str> = params.topics.as_ref()
            .map(|t| t.iter().map(|s| s.as_str()).collect())
            .unwrap_or_default();
        let limit = params.limit.unwrap_or(20);
        let min_stars = params.min_stars.unwrap_or(0);
        let input = format!("lang={} topics={:?}", language, topics);
        let result = match platforms::search_github_repos(&self.http_client, &self.github_token, language, &topics, min_stars, limit).await {
            Ok(repos) => serde_json::to_string_pretty(&repos).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_github_repos", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search Apollo.io for people (founders, CTOs, engineers) by job title, company keywords, seniority level, and location. Returns verified emails, LinkedIn/GitHub/Twitter URLs, company info. Best for finding the right person at a target company after you've identified it. Requires APOLLO_API_KEY (free tier: 50 credits/mo, 10 email exports/mo at app.apollo.io). seniority: 'c_suite','founder','vp','director','manager','senior'. employee_range: '1,10','1,50','1,100'.")]
    async fn search_apollo_people(
        &self,
        Parameters(params): Parameters<ApolloParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_apollo_people").await { return e; }
        let t = self.compliance.audit.start();
        let titles: Vec<&str> = params.titles.iter().map(|s| s.as_str()).collect();
        let seniority: Vec<&str> = params.seniority.iter().map(|s| s.as_str()).collect();
        let input = format!("titles={:?} keywords={:?} emp={:?}", titles, params.keywords, params.employee_range);
        let result = match apollo::search_people(
            &self.http_client,
            &self.apollo_api_key,
            &titles,
            params.keywords.as_deref(),
            params.employee_range.as_deref(),
            &seniority,
            params.location.as_deref(),
            params.limit.unwrap_or(10),
        ).await {
            Ok(people) => serde_json::to_string_pretty(&people).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "search_apollo_people", &input, &result, t, &pii).await;
        result
    }

    #[tool(description = "Enrich a company by domain — FREE, no Clearbit key needed. Combines WebReveal (tech stack), Crunchbase autocomplete (description/meta), and Hunter.io (LinkedIn/Twitter social links). Returns: tech stack, description, logo URL, social links. Uses HUNTER_API_KEY and CRUNCHBASE_API_KEY if set (both optional — degrades gracefully). Pass domain without protocol e.g. 'stripe.com', 'notion.so'.")]
    async fn enrich_company(
        &self,
        Parameters(params): Parameters<ClearbitParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("enrich_company").await { return e; }
        let t = self.compliance.audit.start();
        let result = match clearbit::enrich_company(
            &self.http_client,
            &self.clearbit_api_key,
            &params.domain,
            Some(&self.hunter_api_key),
            Some(&self.crunchbase_api_key),
        ).await {
            Ok(company) => serde_json::to_string_pretty(&company).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "enrich_company", &params.domain, &result, t, &[]).await;
        result
    }

    #[tool(description = "Find email for a specific person using waterfall: (1) Hunter person-finder, (2) GitHub public profile, (3) pattern-guess verified by Hunter. Returns best email + confidence score + source. Required: first_name, last_name, domain. Optional: github_username speeds up step 2. Uses HUNTER_API_KEY (25 searches/mo free). Confidence: 95=GitHub, 85=Hunter finder, 70+=pattern verified, 20=unverified guess.")]
    async fn find_person_email(
        &self,
        Parameters(params): Parameters<FindPersonEmailParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("find_person_email").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{} {} @{}", params.first_name, params.last_name, params.domain);
        let result = match email_finder::find_person_email(
            &self.http_client,
            &self.hunter_api_key,
            &params.first_name,
            &params.last_name,
            &params.domain,
            params.github_username.as_deref(),
        ).await {
            Ok(r) => serde_json::to_string_pretty(&r).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let pii = self.compliance.pii.detect_types(&result);
        self.compliance.audit.log(&self.db, "find_person_email", &input, &result, t, &pii).await;
        result
    }

    #[tool(description = "Draft a warm outreach email after a PR/contribution is acknowledged. Pulls contribution + prospect data from DB, generates a 3-sentence email: (1) reference specific PR and what it fixed, (2) why you care about what they build, (3) one direct ask. No fluff, no 'Dear Name', no AI slop. contribution_id from list_contributions. prospect_id from list_prospects.")]
    async fn draft_warm_email(
        &self,
        Parameters(params): Parameters<DraftEmailParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("draft_warm_email").await { return e; }
        let t = self.compliance.audit.start();

        // Load contribution
        let contrib = sqlx::query_as::<_, (String, String, Option<i64>, Option<String>, String, Option<String>, String)>(
            "SELECT repo_owner, repo_name, issue_number, issue_title, contribution_type, pr_url, notes FROM contributions WHERE id = ?"
        )
        .bind(params.contribution_id)
        .fetch_optional(&self.db)
        .await;

        // Load prospect
        let prospect = sqlx::query_as::<_, (String, Option<String>, Option<String>, Option<String>)>(
            "SELECT name, company, role, email FROM prospects WHERE id = ?"
        )
        .bind(params.prospect_id)
        .fetch_optional(&self.db)
        .await;

        let result = match (contrib, prospect) {
            (Ok(Some((owner, repo, issue_num, issue_title, ctype, pr_url, notes))), Ok(Some((name, company, role, email)))) => {
                let first_name = name.split_whitespace().next().unwrap_or(&name);
                let company_str = company.as_deref().unwrap_or("your company");
                let role_str = role.as_deref().unwrap_or("engineering");

                let contribution_ref = match ctype.as_str() {
                    "pr" => {
                        let pr_ref = pr_url.as_deref().unwrap_or("the PR");
                        let issue_ref = issue_title.as_deref()
                            .map(|t| format!(" (#{} — {})", issue_num.unwrap_or(0), t))
                            .unwrap_or_default();
                        format!("I opened a PR on {}/{}{}: {}", owner, repo, issue_ref, pr_ref)
                    }
                    "issue_comment" => format!("I commented on issue #{} in {}/{}", issue_num.unwrap_or(0), owner, repo),
                    _ => format!("I contributed to {}/{}", owner, repo),
                };

                let context_note = if notes.is_empty() {
                    format!("fixing an issue in {}/{}", owner, repo)
                } else {
                    notes.clone()
                };

                let email_draft = format!(
r#"To: {email_addr}
Subject: Re: {repo} contribution

{first_name},

{contribution_ref} — {context_note}.

I've been following {company}'s work on {repo_name} and it's the kind of {role_area} infrastructure I want to be building — the problem you're solving around [what they build] is real and your approach is interesting.

Open to a quick call if you're looking for engineers who can contribute from day one?

[Your name]

---
DRAFT NOTES:
- Replace [what they build] with 1 specific thing from their docs/README
- Verify email: {email_addr}
- Send only after PR is acknowledged/merged (status: acknowledged)
- Subject line: keep short, reference repo name
"#,
                    email_addr = email.as_deref().unwrap_or("[EMAIL NEEDED — run find_person_email first]"),
                    first_name = first_name,
                    contribution_ref = contribution_ref,
                    context_note = context_note,
                    company = company_str,
                    repo_name = repo,
                    role_area = if role_str.to_lowercase().contains("data") { "data" } else { "systems" },
                );

                serde_json::to_string_pretty(&serde_json::json!({
                    "draft": email_draft,
                    "to": email,
                    "subject": format!("Re: {}/{}", owner, repo),
                    "prospect": { "name": name, "company": company_str, "role": role_str },
                    "contribution": { "repo": format!("{}/{}", owner, repo), "pr_url": pr_url, "type": ctype },
                    "status": "ready_to_send — verify [what they build] placeholder before sending"
                })).unwrap_or_else(|e| e.to_string())
            }
            (Ok(None), _) => format!("Error: contribution_id {} not found", params.contribution_id),
            (_, Ok(None)) => format!("Error: prospect_id {} not found", params.prospect_id),
            (Err(e), _) | (_, Err(e)) => format!("DB error: {}", e),
        };

        self.compliance.audit.log(&self.db, "draft_warm_email", &format!("contrib={} prospect={}", params.contribution_id, params.prospect_id), &result, t, &[]).await;
        result
    }

    #[tool(description = "Export full pipeline as sheet-ready JSON: two arrays — 'prospects' and 'contributions' — with consistent columns. Claude then writes these to Google Sheets via google-workspace MCP. Call this before syncing to sheets. Returns column headers + row data for each table.")]
    async fn export_pipeline(&self) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("export_pipeline").await { return e; }
        let t = self.compliance.audit.start();

        let prospects = sqlx::query_as::<_, (i64, String, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>, String, Option<String>, String)>(
            "SELECT id, name, company, role, email, github, location, outreach_status, source, created_at FROM prospects ORDER BY created_at DESC"
        )
        .fetch_all(&self.db)
        .await;

        let contributions = sqlx::query_as::<_, (i64, Option<i64>, String, String, Option<i64>, Option<String>, String, Option<String>, String, Option<String>, String)>(
            r#"
            SELECT c.id, c.prospect_id, c.repo_owner, c.repo_name, c.issue_number, c.issue_title,
                   c.contribution_type, c.pr_url, c.status, c.notes, c.created_at
            FROM contributions c
            ORDER BY c.created_at DESC
            "#
        )
        .fetch_all(&self.db)
        .await;

        let result = match (prospects, contributions) {
            (Ok(pp), Ok(cc)) => {
                let prospect_headers = vec!["ID","Name","Company","Role","Email","GitHub","Location","Status","Source","Created"];
                let prospect_rows: Vec<Vec<serde_json::Value>> = pp.into_iter().map(|(id,name,company,role,email,github,location,status,source,created)| {
                    vec![
                        serde_json::json!(id), serde_json::json!(name),
                        serde_json::json!(company.unwrap_or_default()),
                        serde_json::json!(role.unwrap_or_default()),
                        serde_json::json!(email.unwrap_or_default()),
                        serde_json::json!(github.unwrap_or_default()),
                        serde_json::json!(location.unwrap_or_default()),
                        serde_json::json!(status),
                        serde_json::json!(source.unwrap_or_default()),
                        serde_json::json!(created),
                    ]
                }).collect();

                let contrib_headers = vec!["ID","Prospect ID","Repo","Issue #","Issue Title","Type","PR URL","Status","Notes","Created"];
                let contrib_rows: Vec<Vec<serde_json::Value>> = cc.into_iter().map(|(id,pid,owner,repo,issue_num,issue_title,ctype,pr_url,status,notes,created)| {
                    vec![
                        serde_json::json!(id),
                        serde_json::json!(pid.unwrap_or_default()),
                        serde_json::json!(format!("{}/{}", owner, repo)),
                        serde_json::json!(issue_num.unwrap_or_default()),
                        serde_json::json!(issue_title.unwrap_or_default()),
                        serde_json::json!(ctype),
                        serde_json::json!(pr_url.unwrap_or_default()),
                        serde_json::json!(status),
                        serde_json::json!(notes.unwrap_or_default()),
                        serde_json::json!(created),
                    ]
                }).collect();

                let n_prospects = prospect_rows.len();
                let n_contribs = contrib_rows.len();
                serde_json::to_string_pretty(&serde_json::json!({
                    "prospects": {
                        "headers": prospect_headers,
                        "rows": prospect_rows,
                        "count": n_prospects
                    },
                    "contributions": {
                        "headers": contrib_headers,
                        "rows": contrib_rows,
                        "count": n_contribs
                    },
                    "sync_instructions": "Write prospects.headers+rows to Sheet1, contributions.headers+rows to Sheet2. Use google-workspace modify_sheet_values tool with range A1."
                })).unwrap_or_else(|e| e.to_string())
            }
            (Err(e), _) | (_, Err(e)) => format!("Error: {}", e),
        };

        self.compliance.audit.log(&self.db, "export_pipeline", "full", &result, t, &[]).await;
        result
    }

    #[tool(description = "List tracked contributions, optionally filtered by status. status values: drafted | submitted | acknowledged | merged | rejected | (empty for all). Use this to find which PRs have been acknowledged and are ready for warm email follow-up.")]
    async fn list_contributions(
        &self,
        Parameters(params): Parameters<ListContributionsParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("list_contributions").await { return e; }
        let t = self.compliance.audit.start();

        let rows: Result<Vec<serde_json::Value>, _> = if let Some(ref status) = params.status {
            sqlx::query_as::<_, (i64, Option<i64>, String, String, Option<i64>, Option<String>, String, Option<String>, String, Option<String>, String)>(
                "SELECT id, prospect_id, repo_owner, repo_name, issue_number, issue_title, contribution_type, pr_url, status, notes, created_at FROM contributions WHERE status = ? ORDER BY created_at DESC"
            )
            .bind(status)
            .fetch_all(&self.db)
            .await
        } else {
            sqlx::query_as::<_, (i64, Option<i64>, String, String, Option<i64>, Option<String>, String, Option<String>, String, Option<String>, String)>(
                "SELECT id, prospect_id, repo_owner, repo_name, issue_number, issue_title, contribution_type, pr_url, status, notes, created_at FROM contributions ORDER BY created_at DESC"
            )
            .fetch_all(&self.db)
            .await
        }.map(|rows| rows.into_iter().map(|(id, prospect_id, owner, repo, issue_num, issue_title, ctype, pr_url, status, notes, created_at)| {
            serde_json::json!({
                "id": id,
                "prospect_id": prospect_id,
                "repo": format!("{}/{}", owner, repo),
                "issue_number": issue_num,
                "issue_title": issue_title,
                "type": ctype,
                "pr_url": pr_url,
                "status": status,
                "notes": notes,
                "created_at": created_at,
            })
        }).collect());

        let result = match rows {
            Ok(data) => serde_json::to_string_pretty(&data).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "list_contributions", params.status.as_deref().unwrap_or("all"), &result, t, &[]).await;
        result
    }
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct YCCompanyTeamParams {
    /// YC company name e.g. "Mentra", "Red Barn Robotics"
    pub company_name: String,
    /// Company website e.g. "https://mentra.glass" — used to find GitHub org by domain
    pub website: Option<String>,
    /// Direct GitHub org login if already known e.g. "mentra-ar" — skips search if provided
    pub github_org: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct UpdateStatusParams {
    /// Prospect ID from list_prospects
    pub id: i64,
    /// new | researched | github_engaged | x_engaged | emailed | replied | meeting_scheduled
    pub status: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct TechStackParams {
    /// Full website URL e.g. "https://stripe.com"
    pub url: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FindEmailsParams {
    /// Company domain without protocol e.g. "stripe.com"
    pub domain: String,
    /// Max emails to return (default 10, max 100)
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct SearchJobsParams {
    /// Comma-separated tags e.g. "rust", "typescript,senior", "python,ml" — leave empty for all
    pub tags: Option<String>,
    /// Max results to return (default 20)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ScoreIssuesParams {
    /// GitHub org or username e.g. "rust-lang", "tokio-rs"
    pub owner: String,
    /// Repo name e.g. "tokio", "axum"
    pub repo: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ListOrgReposParams {
    /// GitHub org login e.g. "vercel", "supabase"
    pub org: String,
    /// Minimum stars filter — use 0 for small startups, 5+ for large orgs (default 0)
    pub min_stars: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct HnHiringParams {
    /// Search query e.g. "Rust remote", "data engineer", "AI infra", "founding engineer"
    pub query: String,
    /// Max results (default 15)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct TrackContributionParams {
    /// Prospect ID from list_prospects (optional if company not yet saved)
    pub prospect_id: Option<i64>,
    /// GitHub repo owner e.g. "vercel"
    pub repo_owner: String,
    /// GitHub repo name e.g. "next.js"
    pub repo_name: String,
    /// GitHub issue number e.g. 1234
    pub issue_number: Option<u64>,
    /// Issue title for reference
    pub issue_title: Option<String>,
    /// pr | issue_comment | issue
    pub contribution_type: Option<String>,
    /// URL of the PR or comment
    pub pr_url: Option<String>,
    /// drafted | submitted | acknowledged | merged | rejected
    pub status: Option<String>,
    /// Any notes e.g. what you fixed, how complex it was
    pub notes: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ListContributionsParams {
    /// Filter by status: drafted | submitted | acknowledged | merged | rejected — leave empty for all
    pub status: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct CrunchbaseParams {
    /// Keyword to search company name/description e.g. "data infrastructure", "AI ops", "developer tools"
    pub keyword: Option<String>,
    /// Minimum total funding in USD e.g. 500000 for $500K+, 1000000 for $1M+
    pub min_funding_usd: Option<u64>,
    /// Max team size: "10", "50", "100", "250" (default "50")
    pub max_employees: Option<String>,
    /// Industry category slug e.g. "artificial-intelligence", "developer-tools", "data-analytics", "fintech"
    pub category: Option<String>,
    /// Max results (default 15, max 25)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ProductHuntParams {
    /// Topic slug e.g. "developer-tools", "artificial-intelligence", "data-science", "open-source"
    pub topic: Option<String>,
    /// Days back to search (default 30)
    pub days_back: Option<u32>,
    /// Max results (default 20, max 50)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct WwrParams {
    /// Keyword to filter jobs e.g. "rust", "data engineer", "python backend"
    pub query: Option<String>,
    /// RSS category: "programming", "devops", "design", "product", "marketing" — empty for all
    pub category: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct WasParams {
    /// Search query e.g. "data engineer", "backend", "rust", "ML infrastructure"
    pub query: Option<String>,
    /// Filter for fully remote positions only (default: true)
    pub remote_only: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct GitHubRepoSearchParams {
    /// Programming language e.g. "Rust", "Python", "Go", "TypeScript" — optional
    pub language: Option<String>,
    /// Topics to filter by e.g. ["data-pipeline", "llm", "protocol"] — optional, can be empty
    pub topics: Option<Vec<String>>,
    /// Minimum star count (default 0 — include all, use 10+ for established projects)
    pub min_stars: Option<u32>,
    /// Max results to return (default 20, max 30)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FindPersonEmailParams {
    /// First name e.g. "John"
    pub first_name: String,
    /// Last name e.g. "Smith"
    pub last_name: String,
    /// Company domain without protocol e.g. "stripe.com"
    pub domain: String,
    /// GitHub username if known — checks public profile email (free, no API key)
    pub github_username: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct DraftEmailParams {
    /// Contribution ID from list_contributions (must be status: acknowledged or merged)
    pub contribution_id: i64,
    /// Prospect ID from list_prospects
    pub prospect_id: i64,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ApolloParams {
    /// Job titles to search e.g. ["CTO", "Head of Engineering", "Founder"]
    pub titles: Vec<String>,
    /// Company keyword/industry tags e.g. "data infrastructure", "AI", "developer tools"
    pub keywords: Option<String>,
    /// Employee range: "1,10" | "1,50" | "1,100" | "1,200"
    pub employee_range: Option<String>,
    /// Seniority levels: "c_suite", "founder", "vp", "director", "manager", "senior"
    pub seniority: Vec<String>,
    /// Location filter e.g. "United States", "Singapore", "London"
    pub location: Option<String>,
    /// Max results (default 10, max 25)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ClearbitParams {
    /// Company domain without protocol e.g. "stripe.com", "notion.so", "openai.com"
    pub domain: String,
}

#[tool_handler]
impl rmcp::ServerHandler for NetworkingServer {}
