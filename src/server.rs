use anyhow::Result;
use reqwest::Client;
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    tool, tool_handler, tool_router,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

use crate::compliance::ComplianceLayer;
use crate::tools::{email_finder, github, jobs, tech_stack, yc};

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
    compliance: ComplianceLayer,
}

impl NetworkingServer {
    pub fn new(db: SqlitePool, github_token: String, hunter_api_key: String, compliance: ComplianceLayer) -> Self {
        Self {
            tool_router: Self::tool_router(),
            http_client: Client::new(),
            db,
            github_token,
            hunter_api_key,
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

#[tool_handler]
impl rmcp::ServerHandler for NetworkingServer {}
