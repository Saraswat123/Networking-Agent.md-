use anyhow::Result;
use chrono::{Duration, Utc};
use reqwest::Client;
use serde::{Deserialize, Serialize};

const YC_TAG_API: &str = "https://yc-oss.github.io/api/tags";
const SEC_FTS: &str = "https://efts.sec.gov/LATEST/search-index";
const GDELT_DOC: &str = "https://api.gdeltproject.org/api/v2/doc/doc";

// ── YC tag API ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct YcTagCompany {
    pub name: String,
    pub batch: String,
    #[serde(rename = "team_size")]
    pub team_size: Option<u32>,
    pub location: Option<String>,
    pub website: Option<String>,
    #[serde(rename = "short_description")]
    pub short_description: Option<String>,
    pub tags: Option<Vec<String>>,
    pub founders: Option<Vec<YcFounder>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct YcFounder {
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub title: Option<String>,
}

pub async fn get_yc_by_tag(
    client: &Client,
    tag: &str,
    limit: usize,
    batch_filter: Option<&str>,
) -> Result<Vec<YcTagCompany>> {
    let url = format!("{}/{}.json", YC_TAG_API, tag);
    let companies: Vec<YcTagCompany> = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let filtered: Vec<YcTagCompany> = companies
        .into_iter()
        .filter(|c| {
            if let Some(bf) = batch_filter {
                c.batch.to_uppercase().contains(&bf.to_uppercase())
            } else {
                true
            }
        })
        .take(limit)
        .collect();

    Ok(filtered)
}

// ── SEC EDGAR Form D ─────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct FormDFiling {
    pub entity_name: String,
    pub filed_at: String,
    pub amount_offered: Option<f64>,
    pub state: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SecResp {
    hits: SecHits,
}

#[derive(Debug, Deserialize)]
struct SecHits {
    hits: Vec<SecHit>,
}

#[derive(Debug, Deserialize)]
struct SecHit {
    #[serde(rename = "_source")]
    source: SecSource,
}

#[derive(Debug, Deserialize)]
struct SecSource {
    #[serde(rename = "entity_name")]
    entity_name: Option<String>,
    #[serde(rename = "file_date")]
    file_date: Option<String>,
    #[serde(rename = "biz_location")]
    biz_location: Option<String>,
}

pub async fn search_form_d(client: &Client, query: &str, days_back: u32) -> Result<Vec<FormDFiling>> {
    let since = (Utc::now() - Duration::days(days_back as i64))
        .format("%Y-%m-%d")
        .to_string();

    let resp = client
        .get(SEC_FTS)
        .query(&[
            ("q", query),
            ("forms", "D"),
            ("dateRange", "custom"),
            ("startdt", &since),
        ])
        .header("User-Agent", "saraswatdas94@gmail.com networking-agent")
        .send()
        .await?;

    let text = resp.text().await?;
    let parsed: Result<SecResp, _> = serde_json::from_str(&text);

    match parsed {
        Ok(data) => {
            let filings = data
                .hits
                .hits
                .into_iter()
                .filter_map(|h| {
                    Some(FormDFiling {
                        entity_name: h.source.entity_name?,
                        filed_at: h.source.file_date.unwrap_or_default(),
                        amount_offered: None,
                        state: h.source.biz_location,
                    })
                })
                .collect();
            Ok(filings)
        }
        Err(_) => Ok(vec![]),
    }
}

// ── GDELT funding news ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct GdeltArticle {
    pub title: String,
    pub url: String,
    pub seen_date: String,
    pub domain: String,
}

#[derive(Debug, Deserialize)]
struct GdeltResp {
    articles: Option<Vec<GdeltArticleRaw>>,
}

#[derive(Debug, Deserialize)]
struct GdeltArticleRaw {
    title: Option<String>,
    url: Option<String>,
    seendate: Option<String>,
    domain: Option<String>,
}

pub async fn search_gdelt_funding(
    client: &Client,
    query: &str,
    max: u32,
) -> Result<Vec<GdeltArticle>> {
    let resp = client
        .get(GDELT_DOC)
        .query(&[
            ("query", query),
            ("mode", "artlist"),
            ("format", "json"),
            ("maxrecords", &max.to_string()),
            ("sort", "datedesc"),
        ])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    let text = resp.text().await?;
    let parsed: Result<GdeltResp, _> = serde_json::from_str(&text);

    match parsed {
        Ok(data) => Ok(data
            .articles
            .unwrap_or_default()
            .into_iter()
            .filter_map(|a| {
                Some(GdeltArticle {
                    title: a.title?,
                    url: a.url?,
                    seen_date: a.seendate.unwrap_or_default(),
                    domain: a.domain.unwrap_or_default(),
                })
            })
            .collect()),
        Err(_) => Ok(vec![]),
    }
}

// ── Fund signal scorer ───────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct FundSignal {
    pub score: u32,
    pub tier: &'static str,
    pub signals: Vec<String>,
}

pub fn compute_fund_signal(
    form_d_days_ago: Option<u32>,
    crunchbase_days_ago: Option<u32>,
    open_eng_roles: u32,
    yc_batches_old: Option<u32>,
    ph_days_ago: Option<u32>,
    github_active_days: Option<u32>,
    team_size: Option<u32>,
) -> FundSignal {
    let mut score: u32 = 0;
    let mut signals = vec![];

    if form_d_days_ago.map(|d| d <= 90).unwrap_or(false)
        || crunchbase_days_ago.map(|d| d <= 90).unwrap_or(false)
    {
        score += 40;
        signals.push("recent funding (<90d)".to_string());
    }
    if open_eng_roles >= 3 {
        score += 20;
        signals.push(format!("{} open eng roles (hiring signal)", open_eng_roles));
    }
    if yc_batches_old.map(|b| b <= 2).unwrap_or(false) {
        score += 15;
        signals.push("YC batch ≤2 old".to_string());
    }
    if ph_days_ago.map(|d| d <= 60).unwrap_or(false) {
        score += 15;
        signals.push("Product Hunt launch <60d".to_string());
    }
    if github_active_days.map(|d| d <= 14).unwrap_or(false) {
        score += 15;
        signals.push("GitHub active <14d".to_string());
    }
    if team_size.map(|s| (2..=20).contains(&s)).unwrap_or(false) {
        score += 10;
        signals.push(format!("team size {} (2-20 sweet spot)", team_size.unwrap()));
    }

    let tier = if score >= 60 {
        "HUNT NOW"
    } else if score >= 35 {
        "WARM"
    } else {
        "WATCH"
    };

    FundSignal { score, tier, signals }
}
