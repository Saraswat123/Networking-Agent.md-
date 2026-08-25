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
    let crunchbase_api_key = env::var("CRUNCHBASE_API_KEY").unwrap_or_default();
    let producthunt_api_token = env::var("PRODUCTHUNT_API_TOKEN").unwrap_or_default();
    let apollo_api_key = env::var("APOLLO_API_KEY").unwrap_or_default();
    let clearbit_api_key = env::var("CLEARBIT_API_KEY").unwrap_or_default();
    let sender_email = env::var("SENDER_EMAIL")
        .unwrap_or_else(|_| "saraswatdas94@gmail.com".to_string());
    let db_path = env::var("NETWORKING_DB").unwrap_or_else(|_| {
        let home = env::var("HOME").unwrap_or_else(|_| ".".to_string());
        format!("{}/networking-agent.db", home)
    });

    let pool = db::init_pool(&db_path).await?;
    let compliance = compliance::ComplianceLayer::new();
    compliance.apply_tool_limits().await;
    let server = NetworkingServer::new(
        pool,
        github_token,
        hunter_api_key,
        crunchbase_api_key,
        producthunt_api_token,
        apollo_api_key,
        clearbit_api_key,
        sender_email,
        compliance,
    );

    let service = server.serve(stdio()).await?;
    service.waiting().await?;

    Ok(())
}
