use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

// ── Companies House UK ────────────────────────────────────────────────────────

const CH_BASE: &str = "https://api.company-information.service.gov.uk";

#[derive(Debug, Serialize, Deserialize)]
pub struct UkOfficer {
    pub name: String,
    pub role: String,
    pub appointed_on: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UkCompany {
    pub company_name: String,
    pub company_number: String,
    pub date_of_creation: Option<String>,
    pub address: Option<String>,
    pub officers: Vec<UkOfficer>,
}

#[derive(Debug, Deserialize)]
struct ChSearchResp {
    items: Vec<ChItem>,
}

#[derive(Debug, Deserialize)]
struct ChItem {
    company_name: String,
    company_number: String,
    date_of_creation: Option<String>,
    address: Option<ChAddr>,
}

#[derive(Debug, Deserialize)]
struct ChAddr {
    locality: Option<String>,
    country: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ChOfficersResp {
    items: Vec<ChOfficerItem>,
}

#[derive(Debug, Deserialize)]
struct ChOfficerItem {
    name: String,
    officer_role: String,
    appointed_on: Option<String>,
}

pub async fn uk_company_lookup(client: &Client, company_name: &str) -> Result<Vec<UkCompany>> {
    let api_key = std::env::var("COMPANIES_HOUSE_API_KEY").unwrap_or_default();
    if api_key.is_empty() {
        return Err(anyhow::anyhow!(
            "COMPANIES_HOUSE_API_KEY not set — free key at developer.company-information.service.gov.uk"
        ));
    }

    let search: ChSearchResp = client
        .get(format!("{}/search/companies", CH_BASE))
        .query(&[("q", company_name), ("items_per_page", "5")])
        .basic_auth(&api_key, Some(""))
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let mut results = vec![];
    for item in search.items.into_iter().take(3) {
        let officers: Vec<UkOfficer> = match client
            .get(format!("{}/company/{}/officers", CH_BASE, item.company_number))
            .basic_auth(&api_key, Some(""))
            .header("User-Agent", "networking-agent/0.1")
            .send()
            .await
        {
            Ok(resp) => match resp.json::<ChOfficersResp>().await {
                Ok(o) => o
                    .items
                    .into_iter()
                    .map(|o| UkOfficer {
                        name: o.name,
                        role: o.officer_role,
                        appointed_on: o.appointed_on,
                    })
                    .collect(),
                Err(_) => vec![],
            },
            Err(_) => vec![],
        };

        let address = item.address.as_ref().map(|a| {
            [a.locality.as_deref(), a.country.as_deref()]
                .iter()
                .filter_map(|s| *s)
                .collect::<Vec<_>>()
                .join(", ")
        });

        results.push(UkCompany {
            company_name: item.company_name,
            company_number: item.company_number,
            date_of_creation: item.date_of_creation,
            address,
            officers,
        });
    }

    Ok(results)
}

// ── Pappers — France ─────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct FrOfficer {
    pub name: String,
    pub role: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FrCompany {
    pub name: String,
    pub siren: String,
    pub city: Option<String>,
    pub creation_date: Option<String>,
    pub officers: Vec<FrOfficer>,
}

#[derive(Debug, Deserialize)]
struct PappersSearchResp {
    resultats: Vec<PappersResult>,
}

#[derive(Debug, Deserialize)]
struct PappersResult {
    nom_entreprise: Option<String>,
    siren: Option<String>,
    ville: Option<String>,
    date_creation: Option<String>,
    dirigeants: Option<Vec<PappersDirigeant>>,
}

#[derive(Debug, Deserialize)]
struct PappersDirigeant {
    nom: Option<String>,
    prenom: Option<String>,
    qualite: Option<String>,
}

pub async fn fr_company_lookup(client: &Client, company_name: &str) -> Result<Vec<FrCompany>> {
    let api_key = std::env::var("PAPPERS_API_KEY").unwrap_or_default();
    if api_key.is_empty() {
        return Err(anyhow::anyhow!(
            "PAPPERS_API_KEY not set — free key at pappers.fr/api"
        ));
    }

    let resp: PappersSearchResp = client
        .get("https://api.pappers.fr/v2/recherche")
        .query(&[
            ("q", company_name),
            ("api_token", &api_key),
            ("_fields", "nom_entreprise,siren,ville,date_creation,dirigeants"),
        ])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let companies = resp
        .resultats
        .into_iter()
        .take(5)
        .filter_map(|r| {
            let name = r.nom_entreprise?;
            let siren = r.siren?;
            let officers = r
                .dirigeants
                .unwrap_or_default()
                .into_iter()
                .filter_map(|d| {
                    let first = d.prenom.unwrap_or_default();
                    let last = d.nom.unwrap_or_default();
                    let full = format!("{} {}", first, last).trim().to_string();
                    if full.is_empty() {
                        None
                    } else {
                        Some(FrOfficer {
                            name: full,
                            role: d.qualite.unwrap_or_default(),
                        })
                    }
                })
                .collect();
            Some(FrCompany {
                name,
                siren,
                city: r.ville,
                creation_date: r.date_creation,
                officers,
            })
        })
        .collect();

    Ok(companies)
}

// ── RDAP domain lookup ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct RdapInfo {
    pub domain: String,
    pub registrant: Option<String>,
    pub emails: Vec<String>,
    pub creation_date: Option<String>,
    pub registrar: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RdapResp {
    entities: Option<Vec<RdapEntity>>,
    events: Option<Vec<RdapEvent>>,
}

#[derive(Debug, Deserialize)]
struct RdapEntity {
    roles: Option<Vec<String>>,
    #[serde(rename = "vcardArray")]
    vcard_array: Option<serde_json::Value>,
    #[serde(rename = "publicIds")]
    public_ids: Option<Vec<serde_json::Value>>,
    entities: Option<Vec<RdapEntity>>,
}

#[derive(Debug, Deserialize)]
struct RdapEvent {
    #[serde(rename = "eventAction")]
    event_action: Option<String>,
    #[serde(rename = "eventDate")]
    event_date: Option<String>,
}

fn extract_vcard(vcard: &serde_json::Value, emails: &mut Vec<String>, name: &mut Option<String>) {
    if let Some(arr) = vcard.as_array() {
        if arr.len() >= 2 {
            if let Some(entries) = arr[1].as_array() {
                for entry in entries {
                    if let Some(e) = entry.as_array() {
                        if e.len() < 4 {
                            continue;
                        }
                        let field = e[0].as_str().unwrap_or("");
                        let value = e[3].as_str().unwrap_or("");
                        match field {
                            "email" => {
                                if !value.contains("privacy")
                                    && !value.contains("protect")
                                    && !value.is_empty()
                                {
                                    emails.push(value.to_string());
                                }
                            }
                            "fn" => {
                                if name.is_none() && !value.is_empty() {
                                    *name = Some(value.to_string());
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
        }
    }
}

fn walk_entities(entities: &[RdapEntity], emails: &mut Vec<String>, name: &mut Option<String>) {
    for entity in entities {
        if let Some(vc) = &entity.vcard_array {
            extract_vcard(vc, emails, name);
        }
        if let Some(children) = &entity.entities {
            walk_entities(children, emails, name);
        }
    }
}

pub async fn rdap_domain(client: &Client, domain: &str) -> Result<RdapInfo> {
    let tld = domain.rsplit('.').next().unwrap_or("com");
    let rdap_url = match tld {
        "com" | "net" => format!("https://rdap.verisign.com/{}/v1/domain/{}", tld, domain),
        _ => format!("https://rdap.iana.org/domain/{}", domain),
    };

    let resp = client
        .get(&rdap_url)
        .header("User-Agent", "networking-agent/0.1")
        .header("Accept", "application/rdap+json")
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok(RdapInfo {
            domain: domain.to_string(),
            registrant: None,
            emails: vec![],
            creation_date: None,
            registrar: None,
        });
    }

    let data: RdapResp = resp.json().await.unwrap_or(RdapResp {
        entities: None,
        events: None,
    });

    let mut emails = vec![];
    let mut registrant = None;

    if let Some(entities) = &data.entities {
        walk_entities(entities, &mut emails, &mut registrant);
    }

    let creation_date = data
        .events
        .unwrap_or_default()
        .into_iter()
        .find(|e| e.event_action.as_deref() == Some("registration"))
        .and_then(|e| e.event_date);

    Ok(RdapInfo {
        domain: domain.to_string(),
        registrant,
        emails,
        creation_date,
        registrar: None,
    })
}
