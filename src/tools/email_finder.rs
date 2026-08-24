use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct EmailResult {
    pub domain: String,
    pub organization: Option<String>,
    pub pattern: Option<String>,
    pub emails: Vec<EmailEntry>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EmailEntry {
    pub value: String,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub position: Option<String>,
    pub confidence: Option<u32>,
    pub linkedin: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HunterResponse {
    data: Option<HunterData>,
    errors: Option<Vec<serde_json::Value>>,
}

#[derive(Debug, Deserialize)]
struct HunterData {
    domain: String,
    organization: Option<String>,
    pattern: Option<String>,
    emails: Vec<HunterEmail>,
}

#[derive(Debug, Deserialize)]
struct HunterEmail {
    value: String,
    first_name: Option<String>,
    last_name: Option<String>,
    position: Option<String>,
    confidence: Option<u32>,
    linkedin: Option<String>,
}

// ─── Person email waterfall ───────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct PersonEmail {
    pub email: Option<String>,
    pub confidence: u8,      // 0-100
    pub source: String,      // hunter_finder | github | pattern_verified | pattern_guess
    pub pattern_used: Option<String>,
    pub all_guesses: Vec<String>,
    pub note: String,
}

/// Waterfall: Hunter person-finder → GitHub profile → pattern-guess → Hunter verify best guess.
/// first_name + last_name required. domain required. github_username optional (speeds up GitHub step).
pub async fn find_person_email(
    client: &Client,
    hunter_key: &str,
    first_name: &str,
    last_name: &str,
    domain: &str,
    github_username: Option<&str>,
) -> Result<PersonEmail> {
    let domain = domain
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.")
        .split('/')
        .next()
        .unwrap_or(domain);

    // ── 1. Hunter person-level finder ─────────────────────────────────────────
    if !hunter_key.is_empty() {
        if let Ok(Some(email)) = hunter_find_person(client, hunter_key, first_name, last_name, domain).await {
            return Ok(PersonEmail {
                email: Some(email),
                confidence: 85,
                source: "hunter_finder".into(),
                pattern_used: None,
                all_guesses: Vec::new(),
                note: "Hunter.io person-level finder".into(),
            });
        }
    }

    // ── 2. GitHub profile public email ────────────────────────────────────────
    if let Some(username) = github_username {
        if let Ok(Some(email)) = github_profile_email(client, username).await {
            return Ok(PersonEmail {
                email: Some(email),
                confidence: 95,
                source: "github".into(),
                pattern_used: None,
                all_guesses: Vec::new(),
                note: "Public GitHub profile email".into(),
            });
        }
    }

    // ── 3. Pattern generation ─────────────────────────────────────────────────
    let f = first_name.to_lowercase();
    let l = last_name.to_lowercase();
    let f1 = f.chars().next().unwrap_or('x').to_string();
    let _l1 = l.chars().next().unwrap_or('x').to_string();

    let patterns = vec![
        format!("{}@{}", f, domain),
        format!("{}.{}@{}", f, l, domain),
        format!("{}{}@{}", f, l, domain),
        format!("{}{}@{}", f1, l, domain),
        format!("{}.{}@{}", f1, l, domain),
        format!("{}_{}@{}", f, l, domain),
    ];

    // ── 4. Verify best guess via Hunter verifier ──────────────────────────────
    if !hunter_key.is_empty() {
        for pattern in &patterns {
            match hunter_verify(client, hunter_key, pattern).await {
                Ok(score) if score >= 70 => {
                    return Ok(PersonEmail {
                        email: Some(pattern.clone()),
                        confidence: score,
                        source: "pattern_verified".into(),
                        pattern_used: Some(pattern.clone()),
                        all_guesses: patterns.clone(),
                        note: format!("Pattern verified by Hunter (score {})", score),
                    });
                }
                _ => continue,
            }
        }
    }

    // ── 5. Best-guess unverified ──────────────────────────────────────────────
    Ok(PersonEmail {
        email: patterns.first().cloned(),
        confidence: 20,
        source: "pattern_guess".into(),
        pattern_used: patterns.first().cloned(),
        all_guesses: patterns,
        note: "Unverified pattern — Hunter key missing or all patterns scored <70. Verify manually before sending.".into(),
    })
}

async fn hunter_find_person(
    client: &Client,
    api_key: &str,
    first_name: &str,
    last_name: &str,
    domain: &str,
) -> Result<Option<String>> {
    #[derive(Deserialize)]
    struct Resp {
        data: Option<Data>,
    }
    #[derive(Deserialize)]
    struct Data {
        email: Option<String>,
        score: Option<u32>,
    }

    let resp = client
        .get("https://api.hunter.io/v2/email-finder")
        .query(&[
            ("domain", domain),
            ("first_name", first_name),
            ("last_name", last_name),
            ("api_key", api_key),
        ])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok(None);
    }

    let r: Resp = resp.json().await?;
    Ok(r.data.and_then(|d| if d.score.unwrap_or(0) >= 50 { d.email } else { None }))
}

async fn github_profile_email(client: &Client, username: &str) -> Result<Option<String>> {
    #[derive(Deserialize)]
    struct User {
        email: Option<String>,
    }

    let resp = client
        .get(format!("https://api.github.com/users/{}", username))
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok(None);
    }

    let u: User = resp.json().await?;
    Ok(u.email.filter(|e| !e.is_empty()))
}

async fn hunter_verify(client: &Client, api_key: &str, email: &str) -> Result<u8> {
    #[derive(Deserialize)]
    struct Resp {
        data: Option<Data>,
    }
    #[derive(Deserialize)]
    struct Data {
        score: Option<u32>,
        status: Option<String>,
    }

    let resp = client
        .get("https://api.hunter.io/v2/email-verifier")
        .query(&[("email", email), ("api_key", api_key)])
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok(0);
    }

    let r: Resp = resp.json().await?;
    let d = r.data.unwrap_or(Data { score: None, status: None });
    let status_ok = matches!(d.status.as_deref(), Some("valid") | Some("accept_all"));
    let score = d.score.unwrap_or(0) as u8;
    Ok(if status_ok { score.max(70) } else { score })
}

pub async fn find_emails(
    client: &Client,
    api_key: &str,
    domain: &str,
    limit: u32,
) -> Result<EmailResult> {
    if api_key.is_empty() {
        return Err(anyhow!("HUNTER_API_KEY not set — get free key at hunter.io (25 searches/mo free)"));
    }

    let resp = client
        .get("https://api.hunter.io/v2/domain-search")
        .header("User-Agent", "networking-agent/0.1")
        .query(&[
            ("domain", domain),
            ("api_key", api_key),
            ("limit", &limit.to_string()),
        ])
        .send()
        .await?
        .json::<HunterResponse>()
        .await?;

    if let Some(errors) = resp.errors {
        if !errors.is_empty() {
            return Err(anyhow!("Hunter.io error: {}", serde_json::to_string(&errors)?));
        }
    }

    let data = resp.data.ok_or_else(|| anyhow!("No data returned from Hunter.io"))?;

    Ok(EmailResult {
        domain: data.domain,
        organization: data.organization,
        pattern: data.pattern,
        emails: data
            .emails
            .into_iter()
            .map(|e| EmailEntry {
                value: e.value,
                first_name: e.first_name,
                last_name: e.last_name,
                position: e.position,
                confidence: e.confidence,
                linkedin: e.linkedin,
            })
            .collect(),
    })
}
