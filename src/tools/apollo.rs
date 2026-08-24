use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const APOLLO_BASE: &str = "https://api.apollo.io/api/v1";

// ─── Output types ─────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct ApolloPerson {
    pub name: String,
    pub title: Option<String>,
    pub email: Option<String>,
    pub email_status: Option<String>,
    pub linkedin_url: Option<String>,
    pub github_url: Option<String>,
    pub twitter_url: Option<String>,
    pub city: Option<String>,
    pub country: Option<String>,
    pub company: Option<String>,
    pub company_website: Option<String>,
    pub company_size: Option<String>,
    pub seniority: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ApolloOrg {
    pub name: String,
    pub website: Option<String>,
    pub linkedin_url: Option<String>,
    pub estimated_employees: Option<u64>,
    pub industry: Option<String>,
    pub city: Option<String>,
    pub country: Option<String>,
    pub short_description: Option<String>,
    pub technology_names: Vec<String>,
    pub annual_revenue: Option<String>,
}

// ─── Raw API shapes ────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct PeopleResp {
    people: Option<Vec<RawPerson>>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RawPerson {
    name: Option<String>,
    title: Option<String>,
    email: Option<String>,
    email_status: Option<String>,
    linkedin_url: Option<String>,
    github_url: Option<String>,
    twitter_url: Option<String>,
    city: Option<String>,
    country: Option<String>,
    seniority: Option<String>,
    organization: Option<RawOrg>,
}

#[derive(Debug, Deserialize)]
struct OrgResp {
    organizations: Option<Vec<RawOrg>>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RawOrg {
    name: Option<String>,
    website_url: Option<String>,
    linkedin_url: Option<String>,
    estimated_num_employees: Option<u64>,
    industry: Option<String>,
    city: Option<String>,
    country: Option<String>,
    short_description: Option<String>,
    #[serde(default)]
    technology_names: Vec<String>,
    annual_revenue_printed: Option<String>,
}

// ─── People search ─────────────────────────────────────────────────────────────

/// Search people by title, company keywords, employee range.
/// seniority: "c_suite", "founder", "vp", "director", "manager", "senior"
/// employee_range: "1,10" | "1,50" | "1,100" — comma-separated min,max
pub async fn search_people(
    client: &Client,
    api_key: &str,
    titles: &[&str],
    keywords: Option<&str>,
    employee_range: Option<&str>,
    seniority: &[&str],
    location: Option<&str>,
    limit: usize,
) -> Result<Vec<ApolloPerson>> {
    if api_key.is_empty() {
        anyhow::bail!(
            "APOLLO_API_KEY not set. Get free key at app.apollo.io — free tier: 50 credits/mo, 10 email exports/mo"
        );
    }

    let mut body = serde_json::json!({
        "api_key": api_key,
        "page": 1,
        "per_page": limit.min(25),
        "contact_email_status": ["verified", "likely to engage"],
    });

    if !titles.is_empty() {
        body["person_titles"] = serde_json::json!(titles);
    }
    if !seniority.is_empty() {
        body["person_seniority"] = serde_json::json!(seniority);
    }
    if let Some(kw) = keywords {
        body["q_organization_keyword_tags"] = serde_json::json!([kw]);
    }
    if let Some(range) = employee_range {
        body["organization_num_employees_ranges"] = serde_json::json!([range]);
    }
    if let Some(loc) = location {
        body["person_locations"] = serde_json::json!([loc]);
    }

    let resp = client
        .post(format!("{}/mixed_people/search", APOLLO_BASE))
        .header("Content-Type", "application/json")
        .header("User-Agent", "networking-agent/0.1")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    let text = resp.text().await?;

    if !status.is_success() {
        anyhow::bail!("Apollo API error {}: {}", status, &text[..text.len().min(200)]);
    }

    let pr: PeopleResp = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("Parse error: {}", e))?;

    if let Some(err) = pr.error {
        anyhow::bail!("Apollo error: {}", err);
    }

    let people = pr
        .people
        .unwrap_or_default()
        .into_iter()
        .map(|p| {
            let (company, company_website, company_size) = p
                .organization
                .map(|o| {
                    let size = o.estimated_num_employees.map(|n| n.to_string());
                    (o.name, o.website_url, size)
                })
                .unwrap_or((None, None, None));

            ApolloPerson {
                name: p.name.unwrap_or_else(|| "Unknown".to_string()),
                title: p.title,
                email: p.email,
                email_status: p.email_status,
                linkedin_url: p.linkedin_url,
                github_url: p.github_url,
                twitter_url: p.twitter_url,
                city: p.city,
                country: p.country,
                seniority: p.seniority,
                company,
                company_website,
                company_size,
            }
        })
        .collect();

    Ok(people)
}

// ─── Company/org search ────────────────────────────────────────────────────────

/// Search companies by keyword, size, industry, location.
/// employee_range: "1,10" | "1,50" | "1,100"
pub async fn search_organizations(
    client: &Client,
    api_key: &str,
    keywords: Option<&str>,
    employee_range: Option<&str>,
    industry: Option<&str>,
    location: Option<&str>,
    technology: Option<&str>,
    limit: usize,
) -> Result<Vec<ApolloOrg>> {
    if api_key.is_empty() {
        anyhow::bail!(
            "APOLLO_API_KEY not set. Get free key at app.apollo.io"
        );
    }

    let mut body = serde_json::json!({
        "api_key": api_key,
        "page": 1,
        "per_page": limit.min(25),
    });

    if let Some(kw) = keywords {
        body["q_organization_keyword_tags"] = serde_json::json!([kw]);
    }
    if let Some(range) = employee_range {
        body["organization_num_employees_ranges"] = serde_json::json!([range]);
    }
    if let Some(ind) = industry {
        body["organization_industries"] = serde_json::json!([ind]);
    }
    if let Some(loc) = location {
        body["organization_locations"] = serde_json::json!([loc]);
    }
    if let Some(tech) = technology {
        body["currently_using_any_of_technology_uids"] = serde_json::json!([tech]);
    }

    let resp = client
        .post(format!("{}/mixed_companies/search", APOLLO_BASE))
        .header("Content-Type", "application/json")
        .header("User-Agent", "networking-agent/0.1")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    let text = resp.text().await?;

    if !status.is_success() {
        anyhow::bail!("Apollo API error {}: {}", status, &text[..text.len().min(200)]);
    }

    let or_: OrgResp = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("Parse error: {}", e))?;

    if let Some(err) = or_.error {
        anyhow::bail!("Apollo error: {}", err);
    }

    let orgs = or_
        .organizations
        .unwrap_or_default()
        .into_iter()
        .map(|o| ApolloOrg {
            name: o.name.unwrap_or_else(|| "Unknown".to_string()),
            website: o.website_url,
            linkedin_url: o.linkedin_url,
            estimated_employees: o.estimated_num_employees,
            industry: o.industry,
            city: o.city,
            country: o.country,
            short_description: o.short_description,
            technology_names: o.technology_names,
            annual_revenue: o.annual_revenue_printed,
        })
        .collect();

    Ok(orgs)
}
