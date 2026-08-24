use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const CB_API: &str = "https://api.crunchbase.com/api/v4/searches/organizations";

#[derive(Debug, Serialize, Deserialize)]
pub struct CbOrg {
    pub name: String,
    pub permalink: String,
    pub cb_url: String,
    pub short_description: Option<String>,
    pub website: Option<String>,
    pub total_funding_usd: Option<u64>,
    pub employee_range: Option<String>,
    pub founded_year: Option<u32>,
    pub categories: Vec<String>,
    pub location: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbResponse {
    entities: Option<Vec<CbEntity>>,
    count: Option<u64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbEntity {
    identifier: Option<CbIdentifier>,
    properties: Option<CbProperties>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbIdentifier {
    value: Option<String>,
    permalink: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbProperties {
    short_description: Option<String>,
    website_url: Option<String>,
    funding_total: Option<CbFunding>,
    num_employees_enum: Option<String>,
    founded_on: Option<CbDate>,
    categories: Option<Vec<CbRef>>,
    location_identifiers: Option<Vec<CbRef>>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbFunding {
    value: Option<u64>,
    currency: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbDate {
    value: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CbRef {
    value: Option<String>,
}

/// Map Crunchbase employee enum to human-readable range
fn map_employee_range(e: &str) -> &str {
    match e {
        "c_00001_00010" => "1-10",
        "c_00011_00050" => "11-50",
        "c_00051_00100" => "51-100",
        "c_00101_00250" => "101-250",
        "c_00251_00500" => "251-500",
        _ => e,
    }
}

/// Search Crunchbase organizations by keyword + optional filters
/// - keyword: company name / description search
/// - min_funding_usd: minimum total funding (e.g. 500_000 for $500K)
/// - max_employees: "10", "50", "100", "250" — filters to small startups
/// - category: industry tag e.g. "artificial-intelligence", "data-analytics", "developer-tools"
pub async fn search_organizations(
    client: &Client,
    api_key: &str,
    keyword: &str,
    min_funding_usd: Option<u64>,
    max_employees: Option<&str>,
    category: Option<&str>,
    limit: usize,
) -> Result<Vec<CbOrg>> {
    if api_key.is_empty() {
        anyhow::bail!("CRUNCHBASE_API_KEY not set. Get free key at data.crunchbase.com/profile/basic_api (200 req/mo)");
    }

    let mut predicates: Vec<serde_json::Value> = Vec::new();

    if let Some(min) = min_funding_usd {
        predicates.push(serde_json::json!({
            "type": "predicate",
            "field_id": "funding_total",
            "operator_id": "gte",
            "values": [min.to_string()]
        }));
    }

    // Employee range filter — only include startups up to max_employees
    let emp_values: Vec<&str> = match max_employees.unwrap_or("50") {
        "10"  => vec!["c_00001_00010"],
        "50"  => vec!["c_00001_00010", "c_00011_00050"],
        "100" => vec!["c_00001_00010", "c_00011_00050", "c_00051_00100"],
        "250" => vec!["c_00001_00010", "c_00011_00050", "c_00051_00100", "c_00101_00250"],
        _ =>    vec!["c_00001_00010", "c_00011_00050"],
    };
    predicates.push(serde_json::json!({
        "type": "predicate",
        "field_id": "num_employees_enum",
        "operator_id": "includes",
        "values": emp_values
    }));

    if let Some(cat) = category {
        predicates.push(serde_json::json!({
            "type": "predicate",
            "field_id": "category_groups",
            "operator_id": "includes",
            "values": [cat]
        }));
    }

    if !keyword.is_empty() {
        predicates.push(serde_json::json!({
            "type": "predicate",
            "field_id": "facet_ids",
            "operator_id": "includes",
            "values": ["company"]
        }));
    }

    let body = serde_json::json!({
        "field_ids": [
            "identifier",
            "short_description",
            "website_url",
            "funding_total",
            "num_employees_enum",
            "founded_on",
            "categories",
            "location_identifiers"
        ],
        "query": predicates,
        "sort": [{"field_id": "funding_total", "sort_type": "desc"}],
        "limit": limit.min(25)
    });

    if !keyword.is_empty() {
        return search_by_keyword(client, api_key, keyword, limit).await;
    }

    let resp = client
        .post(CB_API)
        .query(&[("user_key", api_key)])
        .header("Content-Type", "application/json")
        .header("User-Agent", "networking-agent/0.1")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    let text = resp.text().await?;

    if !status.is_success() {
        anyhow::bail!("Crunchbase API error {}: {}", status, &text[..text.len().min(200)]);
    }

    let cb: CbResponse = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("Parse error: {} — response: {}", e, &text[..text.len().min(300)]))?;

    Ok(parse_cb_entities(cb.entities.unwrap_or_default()))
}

/// Keyword-based search via Crunchbase autocomplete + entity lookup
async fn search_by_keyword(
    client: &Client,
    api_key: &str,
    keyword: &str,
    limit: usize,
) -> Result<Vec<CbOrg>> {
    #[derive(Deserialize)]
    struct AutoResp {
        entities: Option<Vec<AutoEntity>>,
    }
    #[derive(Deserialize)]
    struct AutoEntity {
        identifier: Option<AutoId>,
        short_description: Option<String>,
    }
    #[derive(Deserialize)]
    struct AutoId {
        value: Option<String>,
        permalink: Option<String>,
    }

    let url = format!(
        "https://api.crunchbase.com/api/v4/autocompletes?query={}&collection_ids=organizations",
        urlencoding(keyword)
    );

    let resp = client
        .get(&url)
        .query(&[("user_key", api_key)])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    let status = resp.status();
    let text = resp.text().await?;

    if !status.is_success() {
        anyhow::bail!("Crunchbase autocomplete error {}: {}", status, &text[..text.len().min(200)]);
    }

    let auto: AutoResp = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("Parse error: {}", e))?;

    let orgs: Vec<CbOrg> = auto
        .entities
        .unwrap_or_default()
        .into_iter()
        .take(limit)
        .filter_map(|e| {
            let id = e.identifier?;
            let name = id.value?;
            let permalink = id.permalink.clone().unwrap_or_default();
            Some(CbOrg {
                name,
                cb_url: format!("https://www.crunchbase.com/organization/{}", permalink),
                permalink,
                short_description: e.short_description,
                website: None,
                total_funding_usd: None,
                employee_range: None,
                founded_year: None,
                categories: Vec::new(),
                location: None,
            })
        })
        .collect();

    Ok(orgs)
}

fn parse_cb_entities(entities: Vec<CbEntity>) -> Vec<CbOrg> {
    entities
        .into_iter()
        .filter_map(|e| {
            let id = e.identifier?;
            let name = id.value?;
            let permalink = id.permalink.clone().unwrap_or_default();
            let props = e.properties.unwrap_or_else(|| CbProperties {
                short_description: None,
                website_url: None,
                funding_total: None,
                num_employees_enum: None,
                founded_on: None,
                categories: None,
                location_identifiers: None,
            });

            let funding = props.funding_total
                .as_ref()
                .and_then(|f| f.value);

            let founded_year = props.founded_on
                .as_ref()
                .and_then(|d| d.value.as_ref())
                .and_then(|s| s.split('-').next())
                .and_then(|y| y.parse().ok());

            let categories: Vec<String> = props.categories
                .unwrap_or_default()
                .into_iter()
                .filter_map(|c| c.value)
                .take(5)
                .collect();

            let location = props.location_identifiers
                .unwrap_or_default()
                .into_iter()
                .find_map(|l| l.value);

            let employee_range = props.num_employees_enum
                .as_deref()
                .map(|e| map_employee_range(e).to_string());

            Some(CbOrg {
                name,
                cb_url: format!("https://www.crunchbase.com/organization/{}", permalink),
                permalink,
                short_description: props.short_description,
                website: props.website_url,
                total_funding_usd: funding,
                employee_range,
                founded_year,
                categories,
                location,
            })
        })
        .collect()
}

fn urlencoding(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            ' ' => "+".to_string(),
            c => format!("%{:02X}", c as u32),
        })
        .collect()
}
