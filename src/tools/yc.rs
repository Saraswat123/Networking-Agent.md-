use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const YC_API: &str = "https://api.ycombinator.com/v0.1/companies";

#[derive(Debug, Serialize, Deserialize)]
pub struct YCCompany {
    pub name: String,
    pub slug: Option<String>,
    pub batch: Option<String>,
    pub description: Option<String>,
    pub url: Option<String>,
    pub website: Option<String>,
    pub tags: Vec<String>,
    pub locations: Vec<String>,
    pub regions: Vec<String>,
    pub team_size: Option<u32>,
    pub status: Option<String>,
    pub yc_url: Option<String>,
}

#[derive(Debug, Deserialize)]
struct YCResponse {
    companies: Vec<YCApiCompany>,
}

#[derive(Debug, Deserialize)]
struct YCApiCompany {
    name: String,
    slug: String,
    batch: Option<String>,
    #[serde(rename = "oneLiner")]
    one_liner: Option<String>,
    website: Option<String>,
    #[serde(rename = "teamSize")]
    team_size: Option<u32>,
    url: Option<String>,
    tags: Option<Vec<String>>,
    locations: Option<Vec<String>>,
    regions: Option<Vec<String>>,
    status: Option<String>,
}

pub async fn scrape_yc_companies(client: &Client, batch: &str) -> Result<Vec<YCCompany>> {
    let resp = client
        .get(YC_API)
        .header("User-Agent", "networking-agent/0.1")
        .query(&[("batch", batch), ("limit", "100")])
        .send()
        .await?
        .json::<YCResponse>()
        .await?;

    let companies = resp
        .companies
        .into_iter()
        .map(|c| YCCompany {
            name: c.name,
            slug: Some(c.slug),
            batch: c.batch,
            description: c.one_liner,
            url: c.url.clone(),
            website: c.website,
            tags: c.tags.unwrap_or_default(),
            locations: c.locations.unwrap_or_default(),
            regions: c.regions.unwrap_or_default(),
            team_size: c.team_size,
            status: c.status,
            yc_url: c.url,
        })
        .collect();

    Ok(companies)
}

pub async fn search_yc_companies(
    client: &Client,
    query: &str,
    location: &str,
) -> Result<Vec<YCCompany>> {
    let location_lower = location.to_lowercase();
    let mut all_companies: Vec<YCCompany> = Vec::new();
    let max_pages = 10; // cap at 10 pages = ~500 companies scanned

    for page in 1..=max_pages {
        let mut params = vec![
            ("limit", "50".to_string()),
            ("page", page.to_string()),
        ];
        if !query.is_empty() {
            params.push(("q", query.to_string()));
        }

        let resp = client
            .get(YC_API)
            .header("User-Agent", "networking-agent/0.1")
            .query(&params)
            .send()
            .await?
            .json::<YCResponse>()
            .await?;

        if resp.companies.is_empty() {
            break;
        }

        let filtered: Vec<YCCompany> = resp
            .companies
            .into_iter()
            .filter(|c| {
                if location.is_empty() {
                    return true;
                }
                c.locations
                    .as_ref()
                    .map(|locs| locs.iter().any(|l| l.to_lowercase().contains(&location_lower)))
                    .unwrap_or(false)
                    || c.regions
                        .as_ref()
                        .map(|r| r.iter().any(|reg| reg.to_lowercase().contains(&location_lower)))
                        .unwrap_or(false)
            })
            .map(|c| YCCompany {
                name: c.name,
                slug: Some(c.slug),
                batch: c.batch,
                description: c.one_liner,
                url: c.url.clone(),
                website: c.website,
                tags: c.tags.unwrap_or_default(),
                locations: c.locations.unwrap_or_default(),
                regions: c.regions.unwrap_or_default(),
                team_size: c.team_size,
                status: c.status,
                yc_url: c.url,
            })
            .collect();

        all_companies.extend(filtered);

        // stop early if we have enough results
        if all_companies.len() >= 30 {
            break;
        }
    }

    Ok(all_companies)
}
