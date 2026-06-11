use anyhow::Result;
use reqwest::Client;
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    tool, tool_handler, tool_router,
};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

use crate::tools::{github, yc};

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
}

impl NetworkingServer {
    pub fn new(db: SqlitePool, github_token: String) -> Self {
        Self {
            tool_router: Self::tool_router(),
            http_client: Client::new(),
            db,
            github_token,
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
        match github::search_users(
            &self.http_client,
            &self.github_token,
            &params.query,
            &params.location,
        )
        .await
        {
            Ok(users) => serde_json::to_string_pretty(&users).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Get all public members of a GitHub organization. Good for finding engineers at target companies.")]
    async fn get_org_members(&self, Parameters(params): Parameters<OrgMembersParams>) -> String {
        match github::get_org_members(&self.http_client, &self.github_token, &params.org).await {
            Ok(users) => serde_json::to_string_pretty(&users).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Find open issues in a GitHub repo tagged 'good first issue' or 'help wanted'. These are warm entry points.")]
    async fn find_open_issues(&self, Parameters(params): Parameters<OpenIssuesParams>) -> String {
        match github::find_open_issues(
            &self.http_client,
            &self.github_token,
            &params.owner,
            &params.repo,
        )
        .await
        {
            Ok(issues) => serde_json::to_string_pretty(&issues).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Get YC companies from a specific batch e.g. W25, S24, W24. Returns name, description, website, location, tags.")]
    async fn get_yc_companies(&self, Parameters(params): Parameters<YCBatchParams>) -> String {
        match yc::scrape_yc_companies(&self.http_client, &params.batch).await {
            Ok(companies) => {
                serde_json::to_string_pretty(&companies).unwrap_or_else(|e| e.to_string())
            }
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Search YC companies by keyword and location. Works globally: USA, Singapore, London, NYC, SF, etc.")]
    async fn search_yc_companies(&self, Parameters(params): Parameters<YCSearchParams>) -> String {
        match yc::search_yc_companies(&self.http_client, &params.query, &params.location).await {
            Ok(companies) => {
                serde_json::to_string_pretty(&companies).unwrap_or_else(|e| e.to_string())
            }
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Save a prospect to the local database for tracking outreach.")]
    async fn save_prospect(&self, Parameters(params): Parameters<SaveProspectParams>) -> String {
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

        match result {
            Ok(r) => format!("Saved prospect '{}' (row id: {})", params.name, r.last_insert_rowid()),
            Err(e) => format!("Error saving prospect: {}", e),
        }
    }

    #[tool(description = "List all saved prospects from the database.")]
    async fn list_prospects(&self) -> String {
        let rows: Result<Vec<serde_json::Value>, _> = sqlx::query_as::<_, (i64, String, Option<String>, Option<String>, Option<String>, Option<String>, String)>(
            "SELECT id, name, github, email, company, role, outreach_status FROM prospects ORDER BY created_at DESC"
        )
        .fetch_all(&self.db)
        .await
        .map(|rows| rows.into_iter().map(|(id, name, github, email, company, role, status)| {
            serde_json::json!({
                "id": id,
                "name": name,
                "github": github,
                "email": email,
                "company": company,
                "role": role,
                "status": status,
            })
        }).collect());

        match rows {
            Ok(data) => serde_json::to_string_pretty(&data).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Find GitHub team members for a YC company. Searches GitHub for the company org by name/website domain, returns up to 10 team members with full profiles (email, bio, repos, followers). Use this after get_yc_companies to find the actual people to reach out to.")]
    async fn get_yc_company_team(
        &self,
        Parameters(params): Parameters<YCCompanyTeamParams>,
    ) -> String {
        match github::find_company_team(
            &self.http_client,
            &self.github_token,
            &params.company_name,
            params.website.as_deref(),
            params.github_org.as_deref(),
        )
        .await
        {
            Ok(result) => serde_json::to_string_pretty(&result).unwrap_or_else(|e| e.to_string()),
            Err(e) => format!("Error: {}", e),
        }
    }

    #[tool(description = "Update outreach status for a prospect. Status values: new, researched, github_engaged, x_engaged, emailed, replied, meeting_scheduled.")]
    async fn update_prospect_status(
        &self,
        Parameters(params): Parameters<UpdateStatusParams>,
    ) -> String {
        let result = sqlx::query(
            "UPDATE prospects SET outreach_status = ? WHERE id = ?"
        )
        .bind(&params.status)
        .bind(params.id)
        .execute(&self.db)
        .await;

        match result {
            Ok(_) => format!("Updated prospect {} status to '{}'", params.id, params.status),
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

#[tool_handler]
impl rmcp::ServerHandler for NetworkingServer {}
