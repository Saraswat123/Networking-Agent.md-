mod compliance;
mod db;
mod server;
mod tools;

use anyhow::Result;
use rmcp::{ServiceExt, transport::stdio};
use server::NetworkingServer;
use std::env;

#[tokio::main]
async fn main() -> Result<()> {
    let github_token = env::var("GITHUB_TOKEN").unwrap_or_default();
    let hunter_api_key = env::var("HUNTER_API_KEY").unwrap_or_default();
    let db_path = env::var("NETWORKING_DB").unwrap_or_else(|_| {
        let home = env::var("HOME").unwrap_or_else(|_| ".".to_string());
        format!("{}/networking-agent.db", home)
    });

    let pool = db::init_pool(&db_path).await?;
    let compliance = compliance::ComplianceLayer::new();
    compliance.apply_tool_limits().await;
    let server = NetworkingServer::new(pool, github_token, hunter_api_key, compliance);

    let service = server.serve(stdio()).await?;
    service.waiting().await?;

    Ok(())
}
