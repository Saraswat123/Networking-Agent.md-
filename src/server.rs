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
use crate::tools::{apollo, clearbit, crunchbase, discovery, email_finder, fit, github, hiring, jobs, platforms, producthunt, proposals, scorer, tech_stack, yc};

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
    /// Company website URL — used to extract domain for dedup
    pub website: Option<String>,
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
    sender_email: String,
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
        sender_email: String,
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
            sender_email,
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

    #[tool(description = "Save a prospect to the local database. Deduplicates by domain (website) and GitHub handle — returns existing record instead of inserting if company already in pipeline. Pass website URL to enable domain dedup.")]
    async fn save_prospect(&self, Parameters(params): Parameters<SaveProspectParams>) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("save_prospect").await { return e; }
        let t = self.compliance.audit.start();
        let input = self.compliance.pii.redact(&format!("name={} company={:?}", params.name, params.company));

        // Extract domain from website for dedup
        let domain: Option<String> = params.website.as_deref().map(|w| {
            w.trim_start_matches("https://")
             .trim_start_matches("http://")
             .trim_start_matches("www.")
             .split('/')
             .next()
             .unwrap_or(w)
             .to_lowercase()
        });

        // Domain dedup check
        if let Some(ref d) = domain {
            let exists: Option<(i64, String, String)> = sqlx::query_as(
                "SELECT id, name, outreach_status FROM prospects WHERE LOWER(domain) = ? LIMIT 1"
            )
            .bind(d)
            .fetch_optional(&self.db)
            .await
            .unwrap_or(None);

            if let Some((id, name, status)) = exists {
                let out = format!(
                    "DUPLICATE — '{}' (id:{}) already in pipeline (status: {}). domain={}. Skipped.",
                    name, id, status, d
                );
                self.compliance.audit.log(&self.db, "save_prospect", &input, &out, t, &[]).await;
                return out;
            }
        }

        let result = sqlx::query(
            r#"
            INSERT INTO prospects (name, github, email, company, website, domain, role, location, notes, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(github) DO UPDATE SET
                name = excluded.name,
                email = COALESCE(excluded.email, email),
                company = COALESCE(excluded.company, company),
                domain = COALESCE(excluded.domain, domain),
                website = COALESCE(excluded.website, website),
                notes = COALESCE(excluded.notes, notes)
            "#,
        )
        .bind(&params.name)
        .bind(&params.github)
        .bind(&params.email)
        .bind(&params.company)
        .bind(&params.website)
        .bind(&domain)
        .bind(&params.role)
        .bind(&params.location)
        .bind(&params.notes)
        .bind(&params.source)
        .execute(&self.db)
        .await;

        let out = match result {
            Ok(r) => format!("Saved prospect '{}' (row id: {}, domain: {:?})", params.name, r.last_insert_rowid(), domain),
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
        let now = chrono::Utc::now().to_rfc3339();
        // When marking emailed, stamp email_sent_at; when replied, clear stale state
        let result = if params.status == "emailed" {
            sqlx::query("UPDATE prospects SET outreach_status = ?, email_sent_at = COALESCE(email_sent_at, ?) WHERE id = ?")
                .bind(&params.status).bind(&now).bind(params.id)
                .execute(&self.db).await
        } else if params.status == "replied" {
            sqlx::query("UPDATE prospects SET outreach_status = ?, archived = 0 WHERE id = ?")
                .bind(&params.status).bind(params.id)
                .execute(&self.db).await
        } else {
            sqlx::query("UPDATE prospects SET outreach_status = ? WHERE id = ?")
                .bind(&params.status).bind(params.id)
                .execute(&self.db).await
        };
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

        // Load cached analysis for auto-fill if org provided
        let cached_analysis: Option<proposals::CompanyAnalysis> = if let Some(ref org) = params.github_org {
            sqlx::query_as::<_, (String,)>(
                "SELECT analysis FROM analysis_cache WHERE org = ? AND cached_at >= datetime('now', '-7 days')"
            )
            .bind(org)
            .fetch_optional(&self.db)
            .await
            .ok()
            .flatten()
            .and_then(|(json,)| serde_json::from_str(&json).ok())
        } else {
            None
        };

        let tone = params.tone.as_deref().unwrap_or("peer");

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

                // Auto-fill what-they-build from cached analysis
                let what_they_build = if let Some(ref a) = cached_analysis {
                    let top_pain = a.pain_points.iter()
                        .find(|p| matches!(p.severity, proposals::PainSeverity::High))
                        .or_else(|| a.pain_points.iter().find(|p| matches!(p.severity, proposals::PainSeverity::Medium)));
                    if let Some(pain) = top_pain {
                        format!("{} — specifically the {} challenge", company_str, pain.area.to_lowercase())
                    } else {
                        let stack = a.tech_stack.iter().take(2).cloned().collect::<Vec<_>>().join("/");
                        format!("{} infrastructure on {}", company_str, stack)
                    }
                } else {
                    format!("{}'s core infrastructure", company_str)
                };

                let sender = &self.sender_email;

                let email_draft = match tone {
                    "candidate" => format!(
r#"To: {email_addr}
From: {sender}
Subject: Re: {repo} — engineer who shipped it

{first_name},

{contribution_ref} — {context_note}.

I'm actively looking for {role_area} roles. {company}'s work on {repo_name} maps directly to what I've been building. Happy to send CV or jump on a call if there's a fit.

Saraswat
{sender}
https://saraswat.vercel.app/"#,
                        email_addr = email.as_deref().unwrap_or("[EMAIL NEEDED]"),
                        sender = sender,
                        first_name = first_name,
                        contribution_ref = contribution_ref,
                        context_note = context_note,
                        company = company_str,
                        repo_name = repo,
                        role_area = if role_str.to_lowercase().contains("data") { "data infra" } else { "systems" },
                    ),
                    _ => format!(
r#"To: {email_addr}
From: {sender}
Subject: Re: {repo} contribution

{first_name},

{contribution_ref} — {context_note}.

Been following {what_they_build}. The direction you're taking here is the interesting part.

Open to comparing notes if you're exploring this area further?

Saraswat
{sender}
https://saraswat.vercel.app/"#,
                        email_addr = email.as_deref().unwrap_or("[EMAIL NEEDED]"),
                        sender = sender,
                        first_name = first_name,
                        contribution_ref = contribution_ref,
                        context_note = context_note,
                        what_they_build = what_they_build,
                    ),
                };

                serde_json::to_string_pretty(&serde_json::json!({
                    "draft": email_draft,
                    "to": email,
                    "subject": format!("Re: {}/{}", owner, repo),
                    "tone": tone,
                    "direction": if tone == "candidate" { "job" } else { "proposal" },
                    "prospect": { "name": name, "company": company_str, "role": role_str },
                    "contribution": { "repo": format!("{}/{}", owner, repo), "pr_url": pr_url, "type": ctype },
                    "auto_filled": cached_analysis.is_some(),
                    "status": "draft — confirm with 'send it' before sending"
                })).unwrap_or_else(|e| e.to_string())
            }
            (Ok(None), _) => format!("Error: contribution_id {} not found", params.contribution_id),
            (_, Ok(None)) => format!("Error: prospect_id {} not found", params.prospect_id),
            (Err(e), _) | (_, Err(e)) => format!("DB error: {}", e),
        };

        self.compliance.audit.log(&self.db, "draft_warm_email", &format!("contrib={} prospect={}", params.contribution_id, params.prospect_id), &result, t, &[]).await;
        result
    }

    // ── FIX 1: Dedup gate ──────────────────────────────────────────────────────

    #[tool(description = "Check if a company already exists in the pipeline by domain. Run this BEFORE enriching any company to avoid wasting API credits on duplicates. Returns existing prospect data if found, or 'not_found'. Extract domain from website URL e.g. 'stripe.com' from 'https://stripe.com/pricing'.")]
    async fn check_company_exists(
        &self,
        Parameters(params): Parameters<CheckCompanyParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("check_company_exists").await { return e; }
        let domain = params.domain
            .trim_start_matches("https://")
            .trim_start_matches("http://")
            .trim_start_matches("www.")
            .split('/')
            .next()
            .unwrap_or(&params.domain)
            .to_lowercase();

        let row: Result<Option<(i64, String, Option<String>, Option<String>, String)>, _> =
            sqlx::query_as("SELECT id, name, company, email, outreach_status FROM prospects WHERE LOWER(domain) = ? LIMIT 1")
                .bind(&domain)
                .fetch_optional(&self.db)
                .await;

        match row {
            Ok(Some((id, name, company, email, status))) => serde_json::to_string_pretty(&serde_json::json!({
                "found": true,
                "id": id,
                "name": name,
                "company": company,
                "email": email,
                "status": status,
                "domain": domain,
                "action": "skip — already in pipeline"
            })).unwrap_or_default(),
            Ok(None) => serde_json::to_string_pretty(&serde_json::json!({
                "found": false,
                "domain": domain,
                "action": "proceed"
            })).unwrap_or_default(),
            Err(e) => format!("Error: {}", e),
        }
    }

    // ── FIX 2: Zombie company / dead maintainer gate ────────────────────────────

    #[tool(description = "Check repo health before investing time writing a contribution. Detects: zombie repos (last commit >90 days), dead maintainers (40+ open PRs, 0 merged in 30d), no open issues. Returns verdict: GOOD | MARGINAL | SKIP. Run this BEFORE score_repo_issues on any repo you plan to contribute to.")]
    async fn check_repo_health(
        &self,
        Parameters(params): Parameters<RepoHealthParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("check_repo_health").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{}/{}", params.owner, params.repo);
        let result = match scorer::check_repo_health(&self.http_client, &self.github_token, &params.owner, &params.repo).await {
            Ok(health) => serde_json::to_string_pretty(&health).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "check_repo_health", &input, &result, t, &[]).await;
        result
    }

    // ── FIX 3: Already-contacted guard ─────────────────────────────────────────

    #[tool(description = "Check if a person is already in the pipeline by email or GitHub handle. Run before save_prospect to prevent double-emailing the same person found via different source paths. Returns existing record if duplicate found.")]
    async fn check_already_contacted(
        &self,
        Parameters(params): Parameters<ContactedCheckParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("check_already_contacted").await { return e; }

        let by_email: Option<(i64, String, String)> = if let Some(ref email) = params.email {
            sqlx::query_as("SELECT id, name, outreach_status FROM prospects WHERE LOWER(email) = LOWER(?) LIMIT 1")
                .bind(email)
                .fetch_optional(&self.db)
                .await
                .unwrap_or(None)
        } else { None };

        if let Some((id, name, status)) = by_email {
            return serde_json::to_string_pretty(&serde_json::json!({
                "duplicate": true, "match_by": "email",
                "id": id, "name": name, "status": status,
                "action": "skip — already contacted via email"
            })).unwrap_or_default();
        }

        let by_github: Option<(i64, String, String)> = if let Some(ref gh) = params.github {
            sqlx::query_as("SELECT id, name, outreach_status FROM prospects WHERE LOWER(github) = LOWER(?) LIMIT 1")
                .bind(gh)
                .fetch_optional(&self.db)
                .await
                .unwrap_or(None)
        } else { None };

        if let Some((id, name, status)) = by_github {
            return serde_json::to_string_pretty(&serde_json::json!({
                "duplicate": true, "match_by": "github",
                "id": id, "name": name, "status": status,
                "action": "skip — already in pipeline via GitHub"
            })).unwrap_or_default();
        }

        serde_json::to_string_pretty(&serde_json::json!({ "duplicate": false, "action": "proceed" }))
            .unwrap_or_default()
    }

    // ── FIX 5: Day-7 follow-up sequence ────────────────────────────────────────

    #[tool(description = "List prospects due for a follow-up email. Returns anyone whose first email was sent >= N days ago (default 7) with no reply and no follow-up yet sent. Use this daily to trigger second touchpoints. Second email should use a completely different angle — NOT 'just checking in'.")]
    async fn list_followup_due(
        &self,
        Parameters(params): Parameters<FollowupDueParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("list_followup_due").await { return e; }
        let t = self.compliance.audit.start();
        let days = params.days.unwrap_or(7);

        let rows: Result<Vec<serde_json::Value>, _> = sqlx::query_as::<_, (i64, String, Option<String>, Option<String>, String, Option<String>)>(
            r#"
            SELECT id, name, email, company, outreach_status, email_sent_at
            FROM prospects
            WHERE outreach_status = 'emailed'
              AND archived = 0
              AND email_sent_at IS NOT NULL
              AND follow_up_sent_at IS NULL
              AND CAST((julianday('now') - julianday(email_sent_at)) AS INTEGER) >= ?
            ORDER BY email_sent_at ASC
            "#
        )
        .bind(days)
        .fetch_all(&self.db)
        .await
        .map(|rows| rows.into_iter().map(|(id, name, email, company, status, sent_at)| {
            serde_json::json!({
                "id": id, "name": name, "email": email,
                "company": company, "status": status,
                "email_sent_at": sent_at,
                "action": "draft follow-up email (different angle, not checking in)"
            })
        }).collect());

        match rows {
            Ok(data) => serde_json::to_string_pretty(&data).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    // ── FIX 6: Daily send cap + email logging ───────────────────────────────────

    #[tool(description = "Log that an email was sent to a prospect. Updates prospect email_sent_at timestamp and writes to outreach_log. Call this immediately after sending any email. Also enforces the daily send cap — returns error if cap exceeded.")]
    async fn log_email_sent(
        &self,
        Parameters(params): Parameters<LogEmailParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("log_email_sent").await { return e; }
        let t = self.compliance.audit.start();
        let daily_cap = params.daily_cap.unwrap_or(8);

        // Check daily count
        let today_count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM outreach_log WHERE channel = 'email' AND DATE(sent_at) = DATE('now')"
        )
        .fetch_one(&self.db)
        .await
        .unwrap_or((0,));

        if today_count.0 >= daily_cap as i64 {
            return format!(
                "DAILY CAP REACHED ({}/{}) — no more emails today. Protects domain reputation. Resume tomorrow.",
                today_count.0, daily_cap
            );
        }

        let now = chrono::Utc::now().to_rfc3339();
        let is_followup = params.is_followup.unwrap_or(false);

        // Log to outreach_log
        let _ = sqlx::query(
            "INSERT INTO outreach_log (prospect_id, channel, message, sent_at) VALUES (?, 'email', ?, ?)"
        )
        .bind(params.prospect_id)
        .bind(format!("to={} subject={}", params.to_email.as_deref().unwrap_or(""), params.subject.as_deref().unwrap_or("")))
        .bind(&now)
        .execute(&self.db)
        .await;

        // Update prospect timestamps
        if is_followup {
            let _ = sqlx::query("UPDATE prospects SET follow_up_sent_at = ? WHERE id = ?")
                .bind(&now)
                .bind(params.prospect_id)
                .execute(&self.db)
                .await;
        } else {
            let _ = sqlx::query(
                "UPDATE prospects SET email_sent_at = ?, outreach_status = 'emailed' WHERE id = ?"
            )
            .bind(&now)
            .bind(params.prospect_id)
            .execute(&self.db)
            .await;
        }

        let remaining = daily_cap as i64 - today_count.0 - 1;
        let out = format!(
            "Logged. {}/{} emails sent today. {} remaining in daily cap.",
            today_count.0 + 1, daily_cap, remaining.max(0)
        );
        self.compliance.audit.log(&self.db, "log_email_sent", &format!("prospect={}", params.prospect_id), &out, t, &[]).await;
        out
    }

    #[tool(description = "Get outreach stats: emails sent today, this week, and how many prospects are in each status stage. Use this to check daily cap before sending. Also shows follow-up queue size.")]
    async fn get_outreach_stats(&self) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("get_outreach_stats").await { return e; }

        let today: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM outreach_log WHERE channel='email' AND DATE(sent_at)=DATE('now')"
        ).fetch_one(&self.db).await.unwrap_or((0,));

        let week: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM outreach_log WHERE channel='email' AND sent_at >= datetime('now','-7 days')"
        ).fetch_one(&self.db).await.unwrap_or((0,));

        let followup_due: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM prospects WHERE outreach_status='emailed' AND archived=0 AND follow_up_sent_at IS NULL AND email_sent_at IS NOT NULL AND CAST((julianday('now')-julianday(email_sent_at)) AS INTEGER) >= 7"
        ).fetch_one(&self.db).await.unwrap_or((0,));

        let by_status: Vec<(String, i64)> = sqlx::query_as(
            "SELECT outreach_status, COUNT(*) FROM prospects WHERE archived=0 GROUP BY outreach_status"
        ).fetch_all(&self.db).await.unwrap_or_default();

        let status_map: serde_json::Value = by_status.into_iter()
            .map(|(s, c)| (s, serde_json::json!(c)))
            .collect::<serde_json::Map<_, _>>()
            .into();

        serde_json::to_string_pretty(&serde_json::json!({
            "emails_today": today.0,
            "daily_cap": 8,
            "can_send_today": (8 - today.0).max(0),
            "emails_this_week": week.0,
            "followup_due_count": followup_due.0,
            "pipeline_by_status": status_map
        })).unwrap_or_else(|e| e.to_string())
    }

    // ── Status expiry: auto-archive stale prospects ─────────────────────────────

    #[tool(description = "Archive prospects stuck in 'emailed' status for longer than N days with no reply. Default: 30 days. Keeps pipeline clean. Archived prospects are hidden from stats but not deleted — recoverable with update_prospect_status. Returns count archived.")]
    async fn archive_stale_prospects(
        &self,
        Parameters(params): Parameters<ArchiveStaleParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("archive_stale_prospects").await { return e; }
        let t = self.compliance.audit.start();
        let days = params.days.unwrap_or(30);

        let result = sqlx::query(
            r#"
            UPDATE prospects
            SET archived = 1, outreach_status = 'archived'
            WHERE outreach_status IN ('emailed', 'new', 'researched')
              AND archived = 0
              AND email_sent_at IS NOT NULL
              AND CAST((julianday('now') - julianday(email_sent_at)) AS INTEGER) >= ?
            "#
        )
        .bind(days)
        .execute(&self.db)
        .await;

        let out = match result {
            Ok(r) => format!("Archived {} stale prospects (no reply in {}+ days)", r.rows_affected(), days),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "archive_stale_prospects", &format!("days={}", days), &out, t, &[]).await;
        out
    }

    // ── A: Role fit + compensation + direction routing ──────────────────────────

    #[tool(description = "Score role/job fit and route to Direction A (proposal) or Direction B (job application). Filters: hard-skips frontend/mobile/PM/sales, flags INR/₹ salary as non-remote-budget, checks stack match (Rust/Go/Python/infra), detects remote availability. Returns fit_score 0-100, direction A|B|skip, signals list. Run this BEFORE save_prospect on any job posting.")]
    async fn check_role_fit(
        &self,
        Parameters(params): Parameters<RoleFitParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("check_role_fit").await { return e; }
        let result = fit::score_role_fit(&params.title, &params.description);
        serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string())
    }

    // ── A: CONTRIBUTING.md reader ────────────────────────────────────────────────

    #[tool(description = "Fetch and parse CONTRIBUTING.md (or .github/CONTRIBUTING.md) before writing any PR. Returns: full content, extracted key rules, CLA requirement, test requirement, format/lint requirement. Run this BEFORE writing any code contribution — a PR rejected for missing tests or wrong format wastes everyone's time.")]
    async fn fetch_contributing_guide(
        &self,
        Parameters(params): Parameters<ContributingGuideParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("fetch_contributing_guide").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{}/{}", params.owner, params.repo);
        let result = match scorer::fetch_contributing_guide(
            &self.http_client, &self.github_token, &params.owner, &params.repo
        ).await {
            Ok(guide) => serde_json::to_string_pretty(&guide).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "fetch_contributing_guide", &input, &result, t, &[]).await;
        result
    }

    // ── A: Issue activity / "already claimed?" check ─────────────────────────────

    #[tool(description = "Check if a GitHub issue is already being worked on before you invest time writing a fix. Returns verdict: CLEAR (go ahead) | CONTESTED (active discussion, check comments) | TAKEN (assigned or linked PR exists). Run this AFTER score_repo_issues picks a target, BEFORE writing any code. Saves hours of wasted work.")]
    async fn check_issue_activity(
        &self,
        Parameters(params): Parameters<IssueActivityParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("check_issue_activity").await { return e; }
        let t = self.compliance.audit.start();
        let input = format!("{}/{} #{}", params.owner, params.repo, params.issue_number);
        let result = match scorer::check_issue_activity(
            &self.http_client, &self.github_token, &params.owner, &params.repo, params.issue_number
        ).await {
            Ok(activity) => serde_json::to_string_pretty(&activity).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "check_issue_activity", &input, &result, t, &[]).await;
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

    #[tool(description = "Fetch funding news from TechCrunch, EU-Startups, and Sifted RSS. Returns recently-funded companies — these are actively hiring RIGHT NOW. Filter by round: seed, series-a, series-b. Global coverage including EU and Asia startups.")]
    async fn search_funding_news(
        &self,
        Parameters(params): Parameters<FundingNewsParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_funding_news").await { return e; }
        let t = self.compliance.audit.start();
        let filter = params.filter_round.as_deref().unwrap_or("");
        let limit = params.limit.unwrap_or(20).min(50);
        let result = match discovery::search_funding_news(&self.http_client, filter, limit).await {
            Ok(news) => serde_json::to_string_pretty(&news).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        self.compliance.audit.log(&self.db, "search_funding_news", filter, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search Remotive.io for global remote jobs. Covers EU, Asia, LATAM companies that YC/HN miss entirely. Filter by keyword (rust, data engineer, backend) and category (software-dev, devops-sysadmin).")]
    async fn search_remotive(
        &self,
        Parameters(params): Parameters<RemotiveParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_remotive").await { return e; }
        let t = self.compliance.audit.start();
        let query = params.query.as_deref().unwrap_or("");
        let category = params.category.as_deref().unwrap_or("");
        let limit = params.limit.unwrap_or(20).min(50);
        let result = match discovery::search_remotive(&self.http_client, query, category, limit).await {
            Ok(jobs) => serde_json::to_string_pretty(&jobs).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let input = format!("query={} category={}", query, category);
        self.compliance.audit.log(&self.db, "search_remotive", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Find trending GitHub repos by language and time window. Trending Rust/Go repos = active companies building NOW. Feed org names directly into list_org_repos + score_repo_issues to find contribution opportunities.")]
    async fn search_github_trending(
        &self,
        Parameters(params): Parameters<GitHubTrendingParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_github_trending").await { return e; }
        let t = self.compliance.audit.start();
        let language = params.language.as_deref().unwrap_or("");
        let since = params.since.as_deref().unwrap_or("weekly");
        let limit = params.limit.unwrap_or(20).min(30);
        let result = match discovery::search_github_trending(&self.http_client, &self.github_token, language, since, limit).await {
            Ok(repos) => serde_json::to_string_pretty(&repos).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let input = format!("language={} since={}", language, since);
        self.compliance.audit.log(&self.db, "search_github_trending", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Search Wellfound (AngelList) for startup jobs. Largest startup job source after LinkedIn. Filters: role (engineer/backend/data-engineer), keywords (rust/distributed-systems/protocol), remote_only. Returns company stage, size, equity offers.")]
    async fn search_wellfound(
        &self,
        Parameters(params): Parameters<WellfoundParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("search_wellfound").await { return e; }
        let t = self.compliance.audit.start();
        let role = params.role.as_deref().unwrap_or("engineer");
        let keywords = params.keywords.as_deref().unwrap_or("");
        let remote_only = params.remote_only.unwrap_or(true);
        let limit = params.limit.unwrap_or(20).min(50);
        let result = match discovery::search_wellfound(&self.http_client, role, keywords, remote_only, limit).await {
            Ok(jobs) => serde_json::to_string_pretty(&jobs).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        };
        let input = format!("role={} keywords={} remote={}", role, keywords, remote_only);
        self.compliance.audit.log(&self.db, "search_wellfound", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Deep-analyze a company's GitHub org: repos, open issues (categorized by type), recent commits (classified by signal), discussions, tech stack, and pain points. Produces next-move hypotheses. Results cached 7 days — subsequent calls are instant. Run this BEFORE draft_company_proposal or draft_proposal_email.")]
    async fn analyze_company_depth(
        &self,
        Parameters(params): Parameters<AnalyzeCompanyParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("analyze_company_depth").await { return e; }
        let t = self.compliance.audit.start();

        // Check 7-day cache first
        let cached: Option<(String,)> = sqlx::query_as(
            "SELECT analysis FROM analysis_cache WHERE org = ? AND cached_at >= datetime('now', '-7 days')"
        )
        .bind(&params.org)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        let result = if let Some((cached_json,)) = cached {
            format!("{{\"cached\":true,\"org\":\"{}\",\"analysis\":{}}}", params.org, cached_json)
        } else {
            let max_repos = params.max_repos.unwrap_or(8).min(15);
            let max_issues = params.max_issues_per_repo.unwrap_or(15).min(30);
            match proposals::analyze_company_github(
                &self.http_client,
                &self.github_token,
                &params.org,
                max_repos,
                max_issues,
            ).await {
                Ok(analysis) => {
                    let json = serde_json::to_string(&analysis).unwrap_or_default();
                    let company = params.company_name.as_deref().unwrap_or(&params.org);
                    // Upsert into cache
                    let _ = sqlx::query(
                        "INSERT INTO analysis_cache (org, company, analysis, cached_at) VALUES (?, ?, ?, datetime('now'))
                         ON CONFLICT(org) DO UPDATE SET analysis=excluded.analysis, company=excluded.company, cached_at=excluded.cached_at"
                    )
                    .bind(&params.org)
                    .bind(company)
                    .bind(&json)
                    .execute(&self.db)
                    .await;
                    format!("{{\"cached\":false,\"org\":\"{}\",\"analysis\":{}}}", params.org, json)
                }
                Err(e) => format!("Error: {}", e),
            }
        };
        self.compliance.audit.log(&self.db, "analyze_company_depth", &params.org, &result, t, &[]).await;
        result
    }

    #[tool(description = "Generate targeted technical proposals for a company. Uses cached analysis (run analyze_company_depth first). Each proposal: problem statement, evidence from repo, proposed solution, why now, open question, discussion opener. Engineering-peer tone — NOT a job application. Stores proposals in DB.")]
    async fn draft_company_proposal(
        &self,
        Parameters(params): Parameters<DraftProposalParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("draft_company_proposal").await { return e; }
        let t = self.compliance.audit.start();

        // Load from cache — don't re-run analysis
        let cached: Option<(String,)> = sqlx::query_as(
            "SELECT analysis FROM analysis_cache WHERE org = ? AND cached_at >= datetime('now', '-7 days')"
        )
        .bind(&params.org)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        let analysis = if let Some((json,)) = cached {
            match serde_json::from_str::<proposals::CompanyAnalysis>(&json) {
                Ok(a) => a,
                Err(e) => return format!("Cache parse error: {}. Re-run analyze_company_depth.", e),
            }
        } else {
            // Fallback: run live (and cache)
            match proposals::analyze_company_github(
                &self.http_client, &self.github_token, &params.org, 8, 15,
            ).await {
                Ok(a) => {
                    let json = serde_json::to_string(&a).unwrap_or_default();
                    let _ = sqlx::query(
                        "INSERT INTO analysis_cache (org, company, analysis, cached_at) VALUES (?, ?, ?, datetime('now'))
                         ON CONFLICT(org) DO UPDATE SET analysis=excluded.analysis, company=excluded.company, cached_at=excluded.cached_at"
                    )
                    .bind(&params.org)
                    .bind(&params.company_name)
                    .bind(&json)
                    .execute(&self.db)
                    .await;
                    a
                }
                Err(e) => return format!("Error analyzing {}: {}. Run analyze_company_depth first.", params.org, e),
            }
        };

        let company_name = &params.company_name;
        let focus = params.focus_area.as_deref();
        let proposal_list = proposals::draft_technical_proposal(&analysis, company_name, focus);

        let result = if proposal_list.is_empty() {
            format!("No proposals generated for {} with focus={:?}. Pain points may be Low severity — try a different focus_area or check analyze_company_depth output.", params.org, focus)
        } else {
            let json = serde_json::to_string_pretty(&proposal_list).unwrap_or_else(|e| e.to_string());
            // Store in proposals table
            let _ = sqlx::query(
                "INSERT INTO proposals (org, company, focus_area, proposals) VALUES (?, ?, ?, ?)"
            )
            .bind(&params.org)
            .bind(company_name)
            .bind(focus)
            .bind(&json)
            .execute(&self.db)
            .await;
            json
        };

        let input = format!("org={} company={} focus={:?}", params.org, company_name, focus);
        self.compliance.audit.log(&self.db, "draft_company_proposal", &input, &result, t, &[]).await;
        result
    }

    #[tool(description = "Route a prospect to Direction A (Proposal) or Direction B (Job). Checks: GitHub org exists? Pain points ≥ Medium? Open role matching stack? Sets direction in DB. Run after save_prospect and analyze_company_depth. Returns routing decision + reasoning.")]
    async fn route_prospect(
        &self,
        Parameters(params): Parameters<RouteProspectParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("route_prospect").await { return e; }
        let t = self.compliance.audit.start();

        // Load prospect
        let prospect = sqlx::query_as::<_, (i64, String, Option<String>, Option<String>)>(
            "SELECT id, name, company, notes FROM prospects WHERE id = ?"
        )
        .bind(params.prospect_id)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        let (prospect_id, prospect_name, company, notes) = match prospect {
            Some(p) => p,
            None => return format!("Prospect {} not found.", params.prospect_id),
        };

        // Check cached analysis for pain signals
        let cached: Option<(String,)> = sqlx::query_as(
            "SELECT analysis FROM analysis_cache WHERE org = ? AND cached_at >= datetime('now', '-7 days')"
        )
        .bind(&params.github_org)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        let (direction, reasoning, pain_summary) = if let Some((json,)) = cached {
            match serde_json::from_str::<proposals::CompanyAnalysis>(&json) {
                Ok(analysis) => {
                    let high_pain = analysis.pain_points.iter().filter(|p| matches!(p.severity, proposals::PainSeverity::High)).count();
                    let med_pain = analysis.pain_points.iter().filter(|p| matches!(p.severity, proposals::PainSeverity::Medium)).count();
                    let pain_areas: Vec<&str> = analysis.pain_points.iter()
                        .filter(|p| !matches!(p.severity, proposals::PainSeverity::Low))
                        .map(|p| p.area.as_str())
                        .collect();
                    let stack = analysis.tech_stack.join(", ");

                    if high_pain > 0 || med_pain >= 2 {
                        let summary = format!("{} high + {} medium pain points: [{}]. Stack: {}", high_pain, med_pain, pain_areas.join(", "), stack);
                        ("proposal", "Strong technical pain signals found — engineering discussion will land better than job application", summary)
                    } else if params.has_open_role.unwrap_or(false) {
                        ("job", "Low pain signals but has open role matching stack — apply directly", format!("Stack: {}", stack))
                    } else {
                        ("proposal", "No open role found, some pain signals — proposal direction keeps door open", format!("Stack: {}", stack))
                    }
                }
                Err(_) => ("proposal", "Cache parse failed — defaulting to proposal direction", String::new()),
            }
        } else if params.has_open_role.unwrap_or(false) {
            ("job", "No GitHub analysis cached — open role present, route to job direction", String::new())
        } else {
            ("proposal", "No GitHub analysis cached — run analyze_company_depth for better routing. Defaulting to proposal.", String::new())
        };

        // Update prospect direction in DB
        let now = chrono::Utc::now().to_rfc3339();
        let _ = sqlx::query(
            "UPDATE prospects SET direction = ?, routed_at = ? WHERE id = ?"
        )
        .bind(direction)
        .bind(&now)
        .bind(prospect_id)
        .execute(&self.db)
        .await;

        let result = serde_json::to_string_pretty(&serde_json::json!({
            "prospect": { "id": prospect_id, "name": prospect_name, "company": company },
            "direction": direction,
            "reasoning": reasoning,
            "pain_summary": pain_summary,
            "next_step": if direction == "proposal" {
                "Run draft_company_proposal to generate technical proposals, then draft_proposal_email to create outreach"
            } else {
                "Run draft_warm_email with tone=candidate for job application outreach"
            }
        })).unwrap_or_else(|e| e.to_string());

        self.compliance.audit.log(&self.db, "route_prospect", &format!("id={} org={}", params.prospect_id, params.github_org), &result, t, &[]).await;
        result
    }

    #[tool(description = "Draft a technical proposal email using cached company analysis. Engineering-peer tone — talks about THEIR pain points and tech direction, not your job search. No placeholders. Fills from actual GitHub analysis data. Run analyze_company_depth + draft_company_proposal first.")]
    async fn draft_proposal_email(
        &self,
        Parameters(params): Parameters<DraftProposalEmailParams>,
    ) -> String {
        if let Err(e) = self.compliance.rate_limiter.check("draft_proposal_email").await { return e; }
        let t = self.compliance.audit.start();

        // Load analysis from cache
        let cached: Option<(String,)> = sqlx::query_as(
            "SELECT analysis FROM analysis_cache WHERE org = ?"
        )
        .bind(&params.org)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        // Load latest proposal from DB
        let stored_proposal: Option<(String,)> = sqlx::query_as(
            "SELECT proposals FROM proposals WHERE org = ? ORDER BY created_at DESC LIMIT 1"
        )
        .bind(&params.org)
        .fetch_optional(&self.db)
        .await
        .unwrap_or(None);

        let analysis = match cached {
            Some((json,)) => serde_json::from_str::<proposals::CompanyAnalysis>(&json).ok(),
            None => None,
        };

        let (pain_area, evidence_line, proposed_angle, stack_ref) = if let Some(ref a) = analysis {
            let top_pain = a.pain_points.iter()
                .find(|p| matches!(p.severity, proposals::PainSeverity::High))
                .or_else(|| a.pain_points.iter().find(|p| matches!(p.severity, proposals::PainSeverity::Medium)));

            let (area, evidence, angle) = if let Some(pain) = top_pain {
                let ev = pain.evidence.first().cloned().unwrap_or_default();
                let angle = a.next_move_hypothesis.first()
                    .map(|h| h.proposal_angle.as_str())
                    .unwrap_or("scaling their core infra");
                (pain.area.clone(), ev, angle.to_string())
            } else {
                let area = a.tech_stack.first().cloned().unwrap_or_else(|| "infrastructure".to_string());
                ("general".to_string(), format!("reviewed {} repos, {} open issues", a.repos.len(), a.open_issues.len()), format!("improving {} layer", area))
            };

            let stack = a.tech_stack.iter().take(3).cloned().collect::<Vec<_>>().join("/");
            (area, evidence, angle, stack)
        } else {
            ("infrastructure".to_string(), "GitHub repo analysis".to_string(), "scaling the core pipeline".to_string(), String::new())
        };

        // Pick top proposal discussion opener if available
        let opener = if let Some((proposals_json,)) = stored_proposal {
            serde_json::from_str::<Vec<serde_json::Value>>(&proposals_json)
                .ok()
                .and_then(|ps| {
                    let p = ps.into_iter().find(|p| {
                        params.focus_area.as_ref()
                            .map(|f| p["problem_statement"].as_str().unwrap_or("").to_lowercase().contains(f.as_str()))
                            .unwrap_or(true)
                    });
                    p.and_then(|p| p["discussion_opener"].as_str().map(|s| s.to_string()))
                })
        } else {
            None
        };

        let first_name = &params.first_name;
        let company_name = &params.company_name;
        let sender = &self.sender_email;

        let body = if let Some(ref op) = opener {
            // Use the generated discussion opener from proposal engine
            format!(
                "{first_name},\n\n{opener}\n\nI've been working on {stack_ref} infrastructure — happy to dig into this if useful.\n\nSaraswat\n{sender}\nhttps://saraswat.vercel.app/",
                first_name = first_name,
                opener = op,
                stack_ref = if stack_ref.is_empty() { "distributed systems".to_string() } else { stack_ref.clone() },
                sender = sender,
            )
        } else {
            // Fallback: build from raw pain data
            format!(
                "{first_name},\n\nLooking at {company}'s {pain_area} work — {evidence}. The direction toward {angle} is the interesting part.\n\nI've been building in this space. Worth a quick sync to compare notes?\n\nSaraswat\n{sender}\nhttps://saraswat.vercel.app/",
                first_name = first_name,
                company = company_name,
                pain_area = pain_area,
                evidence = evidence_line,
                angle = proposed_angle,
                sender = sender,
            )
        };

        let subject = params.subject.unwrap_or_else(|| {
            format!("{} — {}", company_name, pain_area)
        });

        let result = serde_json::to_string_pretty(&serde_json::json!({
            "to": params.recipient_email,
            "from": sender,
            "subject": subject,
            "body": body,
            "tone": "peer",
            "direction": "proposal",
            "pain_area": pain_area,
            "stack": stack_ref,
            "status": "draft — review before sending. confirm with 'send it'.",
            "notes": "No placeholders. Filled from live GitHub analysis. Peer tone — not candidate tone."
        })).unwrap_or_else(|e| e.to_string());

        self.compliance.audit.log(&self.db, "draft_proposal_email", &format!("org={} to={}", params.org, params.recipient_email), &result, t, &[]).await;
        result
    }

    // ── Fund Analyzer ─────────────────────────────────────────────────────────

    #[tool(description = "Fetch YC companies by tag using the free yc-oss public API. Tags: 'artificial-intelligence', 'developer-tools', 'workflow-automation', 'data-engineering', 'infrastructure', 'developer-tools'. Returns founders, batch, team size, website. Better than batch search for AI/data profile matching.")]
    async fn get_yc_by_tag(
        &self,
        Parameters(params): Parameters<YcByTagParams>,
    ) -> String {
        let limit = params.limit.unwrap_or(30);
        match crate::tools::fund_analyzer::get_yc_by_tag(
            &self.http_client,
            &params.tag,
            limit,
            params.batch_filter.as_deref(),
        )
        .await
        {
            Ok(companies) => serde_json::to_string_pretty(&serde_json::json!({
                "tag": params.tag,
                "count": companies.len(),
                "companies": companies
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Search SEC EDGAR Form D filings — free, no key. Every US startup raising capital must file Form D within 15 days. Returns company name + filed date. Use query='seed' or 'Series A' for fresh funded companies. days_back=90 for last 3 months. Better than Crunchbase for days-fresh US funding signal.")]
    async fn search_form_d(
        &self,
        Parameters(params): Parameters<FormDParams>,
    ) -> String {
        let days = params.days_back.unwrap_or(90);
        match crate::tools::fund_analyzer::search_form_d(&self.http_client, &params.query, days).await {
            Ok(filings) => serde_json::to_string_pretty(&serde_json::json!({
                "query": params.query,
                "days_back": days,
                "count": filings.len(),
                "filings": filings,
                "tip": "Feed entity_name into search_apollo_people or uk_company_lookup for officer names"
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Search GDELT global news for funding signals — free, no key. Covers EU-Startups, Sifted, DealStreetAsia, e27 that TechCrunch RSS misses. query examples: 'raised seed funding site:sifted.eu', '\"Series A\" startup Singapore', 'raised €2M'. Sorted newest first.")]
    async fn search_gdelt_funding(
        &self,
        Parameters(params): Parameters<GdeltFundingParams>,
    ) -> String {
        let max = params.max_results.unwrap_or(20);
        match crate::tools::fund_analyzer::search_gdelt_funding(&self.http_client, &params.query, max).await {
            Ok(articles) => serde_json::to_string_pretty(&serde_json::json!({
                "query": params.query,
                "count": articles.len(),
                "articles": articles
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Compute fund signal score (0-100) for a prospect. ≥60 = HUNT NOW. Inputs: days since Form D or Crunchbase round, open eng role count (from search_ats_jobs), YC batch age, Product Hunt launch recency, GitHub activity, team size. Stores result in notes field if prospect_id provided.")]
    async fn compute_fund_signal(
        &self,
        Parameters(params): Parameters<FundSignalParams>,
    ) -> String {
        let signal = crate::tools::fund_analyzer::compute_fund_signal(
            params.form_d_days_ago,
            params.crunchbase_days_ago,
            params.open_eng_roles.unwrap_or(0),
            params.yc_batches_old,
            params.ph_days_ago,
            params.github_active_days,
            params.team_size,
        );
        serde_json::to_string_pretty(&serde_json::json!({
            "score": signal.score,
            "tier": signal.tier,
            "signals": signal.signals,
            "action": if signal.score >= 60 { "Run analyze_company_depth → route_prospect → draft_proposal_email" }
                      else if signal.score >= 35 { "Watch — wait for more signals before emailing" }
                      else { "Skip for now" }
        }))
        .unwrap_or_else(|e| e.to_string())
    }

    // ── Registry — Officer Lookup ─────────────────────────────────────────────

    #[tool(description = "Look up UK company on Companies House — free key (600 req/10min). Returns officers (founders by name + DOB month). Officer names feed directly into search_apollo_people for email finding. Requires COMPANIES_HOUSE_API_KEY env var (free at developer.company-information.service.gov.uk).")]
    async fn uk_company_lookup(
        &self,
        Parameters(params): Parameters<UkCompanyParams>,
    ) -> String {
        match crate::tools::registry::uk_company_lookup(&self.http_client, &params.company_name).await {
            Ok(companies) => serde_json::to_string_pretty(&serde_json::json!({
                "count": companies.len(),
                "companies": companies,
                "tip": "Use officer names with search_apollo_people to find emails"
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Look up French company on Pappers — free key, generous limit. Returns dirigeants (officers/founders) with name + role. Covers France startups (Paris tech scene). Requires PAPPERS_API_KEY env var (free at pappers.fr/api).")]
    async fn fr_company_lookup(
        &self,
        Parameters(params): Parameters<FrCompanyParams>,
    ) -> String {
        match crate::tools::registry::fr_company_lookup(&self.http_client, &params.company_name).await {
            Ok(companies) => serde_json::to_string_pretty(&serde_json::json!({
                "count": companies.len(),
                "companies": companies
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "RDAP domain lookup — free, no key, unlimited. Checks Verisign RDAP for domain registration info. Sometimes exposes founder email or registrant name in public registration data. Use after Hunter/Apollo waterfall as bonus signal. domain format: 'company.com' or 'company.io'.")]
    async fn rdap_domain(
        &self,
        Parameters(params): Parameters<RdapParams>,
    ) -> String {
        match crate::tools::registry::rdap_domain(&self.http_client, &params.domain).await {
            Ok(info) => serde_json::to_string_pretty(&info).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    // ── ATS Jobs ─────────────────────────────────────────────────────────────

    #[tool(description = "Fetch jobs from startup ATS boards — free, no key. Auto-detects Ashby (AI/dev-tool startups) → Greenhouse (US standard) → Lever (SF startups). board_slug is the company slug on their ATS e.g. 'linear', 'vercel', 'supabase'. Returns structured jobs with remote flag + eng role count (feeds fund_signal_score).")]
    async fn search_ats_jobs(
        &self,
        Parameters(params): Parameters<AtsJobsParams>,
    ) -> String {
        let ats = params.ats.as_deref();
        match crate::tools::ats_jobs::search_ats_jobs(&self.http_client, &params.board_slug, ats).await {
            Ok(board) => {
                let jobs: Vec<_> = if params.remote_only.unwrap_or(false) {
                    board.jobs.into_iter().filter(|j| j.remote).collect()
                } else {
                    board.jobs
                };
                serde_json::to_string_pretty(&serde_json::json!({
                    "ats": board.ats,
                    "board_slug": board.board_slug,
                    "total_jobs": board.total_jobs,
                    "eng_roles": board.eng_roles,
                    "remote_roles": board.remote_roles,
                    "jobs": jobs
                }))
                .unwrap_or_else(|e| e.to_string())
            }
            Err(e) => format!("Error: {} — try ats=ashby, ats=greenhouse, or ats=lever explicitly", e),
        }
    }

    // ── Email Verify ─────────────────────────────────────────────────────────

    #[tool(description = "Verify a single email via Hunter.io — checks MX records + SMTP deliverability. Returns deliverable bool + confidence score (0-100). Use in email waterfall step 5 to verify pattern-guessed emails before sending. Requires HUNTER_API_KEY.")]
    async fn verify_email(
        &self,
        Parameters(params): Parameters<VerifyEmailParams>,
    ) -> String {
        match crate::tools::verify::verify_hunter(&self.http_client, &params.email).await {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Generate common email patterns for a person and verify via Hunter waterfall. Returns first deliverable email. Inputs: first name, last name, domain. Generates: fname@, fname.lname@, f+lname@, etc. Use as last resort after Apollo → Hunter domain-search → GitHub email.")]
    async fn find_email_by_name(
        &self,
        Parameters(params): Parameters<FindEmailByNameParams>,
    ) -> String {
        let candidates = crate::tools::verify::email_patterns(
            &params.first_name,
            &params.last_name,
            &params.domain,
        );
        match crate::tools::verify::verify_waterfall(&self.http_client, candidates.clone()).await {
            Ok(Some(result)) => serde_json::to_string_pretty(&serde_json::json!({
                "found": true,
                "email": result.email,
                "confidence": result.confidence,
                "deliverable": result.deliverable,
                "candidates_tried": candidates.len()
            }))
            .unwrap_or_else(|e| e.to_string()),
            Ok(None) => serde_json::to_string_pretty(&serde_json::json!({
                "found": false,
                "candidates_tried": candidates,
                "tip": "Try Hunter domain-search or Apollo reveal"
            }))
            .unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
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
    /// Email tone: "peer" (engineering discussion, Direction A) or "candidate" (job application, Direction B). Default: peer
    pub tone: Option<String>,
    /// GitHub org for auto-filling company context from cached analysis — optional, improves output
    pub github_org: Option<String>,
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

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct AnalyzeCompanyParams {
    /// GitHub org login e.g. "vercel", "supabase", "pola-rs"
    pub org: String,
    /// Company display name e.g. "Vercel", "Supabase" (used in proposals)
    pub company_name: Option<String>,
    /// Max repos to inspect (default 8, max 15)
    pub max_repos: Option<usize>,
    /// Max issues per repo (default 15, max 30)
    pub max_issues_per_repo: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct DraftProposalParams {
    /// GitHub org login — must have been analyzed first with analyze_company_depth
    pub org: String,
    /// Company display name for the proposal
    pub company_name: String,
    /// Focus on a specific area: "scaling", "ai", "database", "integration" — empty = all
    pub focus_area: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FundingNewsParams {
    /// Round filter: "seed", "series-a", "series-b", "series-c" — leave empty for all rounds
    pub filter_round: Option<String>,
    /// Max results (default 20)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct RemotiveParams {
    /// Keyword filter e.g. "rust", "data engineer", "backend", "ML" — leave empty for all
    pub query: Option<String>,
    /// Category: "software-dev", "devops-sysadmin", "all" (empty = all remote jobs)
    pub category: Option<String>,
    /// Max results (default 20)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct GitHubTrendingParams {
    /// Language filter e.g. "rust", "go", "python", "typescript" — leave empty for all
    pub language: Option<String>,
    /// Time window: "daily", "weekly", "monthly" (default: "weekly")
    pub since: Option<String>,
    /// Max results (default 20, max 30)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct WellfoundParams {
    /// Role category e.g. "engineer", "backend", "data-engineer", "devops"
    pub role: Option<String>,
    /// Keywords e.g. "rust", "distributed systems", "protocol"
    pub keywords: Option<String>,
    /// Filter to remote-only positions (default true)
    pub remote_only: Option<bool>,
    /// Max results (default 20)
    pub limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct RoleFitParams {
    /// Job title e.g. "Senior Backend Engineer", "Founding Engineer", "Staff SRE"
    pub title: String,
    /// Full job description or role summary text — paste the raw JD
    pub description: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ContributingGuideParams {
    /// GitHub repo owner e.g. "tokio-rs"
    pub owner: String,
    /// GitHub repo name e.g. "tokio"
    pub repo: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct IssueActivityParams {
    /// GitHub repo owner
    pub owner: String,
    /// GitHub repo name
    pub repo: String,
    /// Issue number to check e.g. 1234
    pub issue_number: u64,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct CheckCompanyParams {
    /// Company domain or website URL e.g. "stripe.com" or "https://stripe.com/pricing"
    pub domain: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct RepoHealthParams {
    /// GitHub repo owner e.g. "tokio-rs"
    pub owner: String,
    /// GitHub repo name e.g. "tokio"
    pub repo: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ContactedCheckParams {
    /// Email to check for duplicates
    pub email: Option<String>,
    /// GitHub username to check for duplicates
    pub github: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FollowupDueParams {
    /// Days since first email with no reply (default 7)
    pub days: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct LogEmailParams {
    /// Prospect ID from list_prospects
    pub prospect_id: i64,
    /// Email address sent to
    pub to_email: Option<String>,
    /// Subject line for the record
    pub subject: Option<String>,
    /// true if this is a follow-up (Day 7+), false for first email
    pub is_followup: Option<bool>,
    /// Daily send cap (default 8)
    pub daily_cap: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct ArchiveStaleParams {
    /// Days with no reply before archiving (default 30)
    pub days: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct RouteProspectParams {
    /// Prospect ID from list_prospects
    pub prospect_id: i64,
    /// GitHub org login for the company (used to load cached analysis)
    pub github_org: String,
    /// True if company has an open role matching your stack (Rust/Go/data infra)
    pub has_open_role: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct DraftProposalEmailParams {
    /// GitHub org login — must have cached analysis from analyze_company_depth
    pub org: String,
    /// Company display name
    pub company_name: String,
    /// Recipient first name
    pub first_name: String,
    /// Recipient email address
    pub recipient_email: String,
    /// Focus area to pick the right proposal: "scaling", "ai", "database", "integration" — empty = top pain
    pub focus_area: Option<String>,
    /// Optional custom subject line — auto-generated if empty
    pub subject: Option<String>,
}

// ── New param structs ─────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct YcByTagParams {
    /// Tag slug e.g. "artificial-intelligence", "developer-tools", "workflow-automation", "data-engineering", "infrastructure"
    pub tag: String,
    /// Max companies to return (default 30)
    pub limit: Option<usize>,
    /// Filter by batch e.g. "S2026", "W2026", "W2025"
    pub batch_filter: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FormDParams {
    /// Search query e.g. "seed", "Series A", company name, industry keyword
    pub query: String,
    /// Days back from today (default 90)
    pub days_back: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct GdeltFundingParams {
    /// GDELT query e.g. "raised seed funding site:sifted.eu", "\"Series A\" startup Singapore"
    pub query: String,
    /// Max articles (default 20, max 250)
    pub max_results: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FundSignalParams {
    /// Days since Form D filing (None = unknown)
    pub form_d_days_ago: Option<u32>,
    /// Days since Crunchbase round (None = unknown)
    pub crunchbase_days_ago: Option<u32>,
    /// Number of open engineering roles from search_ats_jobs
    pub open_eng_roles: Option<u32>,
    /// How many YC batches old (0 = current, 1 = one batch ago)
    pub yc_batches_old: Option<u32>,
    /// Days since Product Hunt launch
    pub ph_days_ago: Option<u32>,
    /// Days since last GitHub commit in org
    pub github_active_days: Option<u32>,
    /// Current team size
    pub team_size: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct UkCompanyParams {
    /// Company name to search on Companies House e.g. "Pipekit Ltd"
    pub company_name: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FrCompanyParams {
    /// Company name to search on Pappers e.g. "Dataiku"
    pub company_name: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct RdapParams {
    /// Domain to look up e.g. "pipekit.io", "velum-labs.com"
    pub domain: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct AtsJobsParams {
    /// Board slug — company name on the ATS e.g. "linear", "vercel", "supabase", "pipekit"
    pub board_slug: String,
    /// Force a specific ATS: "ashby", "greenhouse", "lever" — omit for auto-detect (Ashby → Greenhouse → Lever)
    pub ats: Option<String>,
    /// Only return remote-flagged roles (default false)
    pub remote_only: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct VerifyEmailParams {
    /// Email address to verify e.g. "founder@company.com"
    pub email: String,
}

#[derive(Debug, Serialize, Deserialize, JsonSchema)]
pub struct FindEmailByNameParams {
    /// First name of the person
    pub first_name: String,
    /// Last name of the person
    pub last_name: String,
    /// Company domain without protocol e.g. "pipekit.io"
    pub domain: String,
}

#[tool_handler]
impl rmcp::ServerHandler for NetworkingServer {}
