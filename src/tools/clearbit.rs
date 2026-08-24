use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

/// Free multi-source company enrichment.
/// Combines: WebReveal (tech stack) + Crunchbase autocomplete (funding/size) + Hunter (email patterns)
#[derive(Debug, Serialize, Deserialize)]
pub struct ClearbitCompany {
    pub name: String,
    pub domain: String,
    pub description: Option<String>,
    pub founded_year: Option<u32>,
    pub location: Option<String>,
    pub employees: Option<u64>,
    pub raised_usd: Option<u64>,
    pub tech_stack: Vec<String>,
    pub linkedin: Option<String>,
    pub twitter: Option<String>,
    pub industry: Option<String>,
    pub sector: Option<String>,
    pub tags: Vec<String>,
    pub logo: Option<String>,
    pub sources: Vec<String>,
}

/// Enrich company from domain — free, no API key required.
/// Sources: WebReveal (tech), Crunchbase autocomplete (meta), Hunter domain search (email patterns).
/// hunter_key and crunchbase_key are optional — enrichment degrades gracefully without them.
pub async fn enrich_company(
    client: &Client,
    _api_key: &str,
    domain: &str,
    hunter_key: Option<&str>,
    crunchbase_key: Option<&str>,
) -> Result<ClearbitCompany> {
    let domain = domain
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.")
        .split('/')
        .next()
        .unwrap_or(domain);

    let company_name = domain.split('.').next().unwrap_or(domain);
    let mut sources: Vec<String> = Vec::new();

    // ── WebReveal: tech stack ──────────────────────────────────────────────────
    let tech_stack = match fetch_webreveal(client, domain).await {
        Ok(techs) => { sources.push("webreveal".into()); techs }
        Err(_) => Vec::new(),
    };

    // ── Crunchbase autocomplete: name, description, funding, size ──────────────
    let (cb_name, description, founded_year, employees, raised_usd, location, tags) =
        if let Some(cb_key) = crunchbase_key.filter(|k| !k.is_empty()) {
            match fetch_crunchbase_meta(client, cb_key, company_name).await {
                Ok(meta) => { sources.push("crunchbase".into()); meta }
                Err(_) => default_meta(company_name),
            }
        } else {
            default_meta(company_name)
        };

    // ── Hunter: email pattern + LinkedIn/Twitter ───────────────────────────────
    let (linkedin, twitter) =
        if let Some(h_key) = hunter_key.filter(|k| !k.is_empty()) {
            match fetch_hunter_social(client, h_key, domain).await {
                Ok(social) => { sources.push("hunter".into()); social }
                Err(_) => (None, None),
            }
        } else {
            (None, None)
        };

    Ok(ClearbitCompany {
        name: cb_name,
        domain: domain.to_string(),
        description,
        founded_year,
        location,
        employees,
        raised_usd,
        tech_stack,
        linkedin,
        twitter,
        industry: None,
        sector: None,
        tags,
        logo: Some(format!("https://logo.clearbit.com/{}", domain)),
        sources,
    })
}

// ── WebReveal ─────────────────────────────────────────────────────────────────

async fn fetch_webreveal(client: &Client, domain: &str) -> Result<Vec<String>> {
    #[derive(Deserialize)]
    struct WrResp {
        technologies: Option<Vec<WrTech>>,
    }
    #[derive(Deserialize)]
    struct WrTech {
        name: Option<String>,
    }

    let url = format!(
        "https://api.webreveal.com/v1/lookup?url=https://{}",
        domain
    );
    let resp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("WebReveal {}", resp.status());
    }

    let wr: WrResp = resp.json().await?;
    let techs: Vec<String> = wr
        .technologies
        .unwrap_or_default()
        .into_iter()
        .filter_map(|t| t.name)
        .collect();

    Ok(techs)
}

// ── Crunchbase autocomplete ────────────────────────────────────────────────────

async fn fetch_crunchbase_meta(
    client: &Client,
    api_key: &str,
    company_name: &str,
) -> Result<(String, Option<String>, Option<u32>, Option<u64>, Option<u64>, Option<String>, Vec<String>)> {
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
    }

    let query: String = company_name
        .chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' => c.to_string(),
            ' ' => "+".to_string(),
            c => format!("%{:02X}", c as u32),
        })
        .collect();

    let url = format!(
        "https://api.crunchbase.com/api/v4/autocompletes?query={}&collection_ids=organizations",
        query
    );

    let resp = client
        .get(&url)
        .query(&[("user_key", api_key)])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("Crunchbase {}", resp.status());
    }

    let ar: AutoResp = resp.json().await?;
    let first = ar.entities.unwrap_or_default().into_iter().next();

    let (name, desc) = first
        .map(|e| (e.identifier.and_then(|i| i.value), e.short_description))
        .unwrap_or((None, None));

    Ok((
        name.unwrap_or_else(|| company_name.to_string()),
        desc,
        None, None, None, None,
        Vec::new(),
    ))
}

// ── Hunter social links ────────────────────────────────────────────────────────

async fn fetch_hunter_social(
    client: &Client,
    api_key: &str,
    domain: &str,
) -> Result<(Option<String>, Option<String>)> {
    #[derive(Deserialize)]
    struct HunterResp {
        data: Option<HunterData>,
    }
    #[derive(Deserialize)]
    struct HunterData {
        linkedin: Option<String>,
        twitter: Option<String>,
    }

    let resp = client
        .get("https://api.hunter.io/v2/domain-search")
        .query(&[("domain", domain), ("api_key", api_key), ("limit", "1")])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        anyhow::bail!("Hunter {}", resp.status());
    }

    let hr: HunterResp = resp.json().await?;
    let (linkedin, twitter) = hr
        .data
        .map(|d| (d.linkedin, d.twitter))
        .unwrap_or((None, None));

    Ok((linkedin, twitter))
}

fn default_meta(name: &str) -> (String, Option<String>, Option<u32>, Option<u64>, Option<u64>, Option<String>, Vec<String>) {
    (name.to_string(), None, None, None, None, None, Vec::new())
}
