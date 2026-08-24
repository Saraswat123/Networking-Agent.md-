use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

// ─── We Work Remotely ────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct WwrJob {
    pub title: String,
    pub company: String,
    pub category: String,
    pub job_type: String,
    pub region: String,
    pub url: String,
    pub pub_date: String,
    pub description_snippet: String,
}

/// Parse WWR RSS — free, no key, no auth
/// category RSS feeds: programming, devops, design, product, marketing
/// Pass empty category for all jobs
pub async fn search_wwr(client: &Client, query: &str, category: &str) -> Result<Vec<WwrJob>> {
    let feed_url = if category.is_empty() {
        "https://weworkremotely.com/remote-jobs.rss".to_string()
    } else {
        format!("https://weworkremotely.com/categories/remote-{}-jobs.rss", category)
    };

    let xml = client
        .get(&feed_url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;

    parse_wwr_rss(&xml, query)
}

fn parse_wwr_rss(xml: &str, query: &str) -> Result<Vec<WwrJob>> {
    let q = query.to_lowercase();
    let mut jobs = Vec::new();

    for block in xml.split("<item>").skip(1) {
        let end = block.find("</item>").unwrap_or(block.len());
        let item = &block[..end];

        let title = extract_xml_text(item, "title").unwrap_or_default();
        let link = extract_xml_text(item, "link")
            .or_else(|| extract_xml_text(item, "guid"))
            .unwrap_or_default();
        let region = extract_xml_text(item, "region").unwrap_or_else(|| "Remote".to_string());
        let category = extract_xml_text(item, "category").unwrap_or_default();
        let job_type = extract_xml_text(item, "type").unwrap_or_else(|| "Full-Time".to_string());
        let pub_date = extract_xml_text(item, "pubDate").unwrap_or_default();
        let description = extract_xml_text(item, "description").unwrap_or_default();
        let description = strip_html(&description);

        // Filter by query
        if !q.is_empty() {
            let haystack = format!("{} {} {} {}", title, description, category, region).to_lowercase();
            if !haystack.contains(&q) {
                continue;
            }
        }

        let (role, company) = split_wwr_title(&title);
        let snippet = description.chars().take(300).collect::<String>();
        let snippet = if description.len() > 300 { format!("{}...", snippet) } else { description };

        jobs.push(WwrJob {
            title: role,
            company,
            category,
            job_type,
            region,
            url: link,
            pub_date,
            description_snippet: snippet,
        });
    }

    Ok(jobs)
}

/// WWR title format: "Company Name: Role Title" or "Role Title at Company"
fn split_wwr_title(title: &str) -> (String, String) {
    if let Some(colon) = title.find(": ") {
        let company = title[..colon].trim().to_string();
        let role = title[colon + 2..].trim().to_string();
        return (role, company);
    }
    if let Some(at) = title.rfind(" at ") {
        let role = title[..at].trim().to_string();
        let company = title[at + 4..].trim().to_string();
        return (role, company);
    }
    (title.to_string(), "Unknown".to_string())
}

fn extract_xml_text(xml: &str, tag: &str) -> Option<String> {
    let open = format!("<{}>", tag);
    let close = format!("</{}>", tag);
    let start = xml.find(&open)? + open.len();
    let rest = &xml[start..];
    let end = rest.find(&close)?;
    let raw = rest[..end].trim();
    let raw = raw
        .trim_start_matches("<![CDATA[")
        .trim_end_matches("]]>");
    Some(unescape_html(strip_html(raw).trim()))
}

// ─── Work at a Startup ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct WasJob {
    pub id: u64,
    pub title: String,
    pub company: String,
    pub company_batch: Option<String>,
    pub company_description: Option<String>,
    pub job_type: String,
    pub role_type: Option<String>,
    pub location: String,
    pub salary: Option<String>,
    pub apply_url: String,
    pub was_url: String,
}

/// Search Work at a Startup (YC companies only)
/// The page embeds job data as JSON in the HTML — extract directly.
/// remote_only: if true, appends &remote=only to filter remote positions
pub async fn search_workatastartup(
    client: &Client,
    query: &str,
    remote_only: bool,
) -> Result<Vec<WasJob>> {
    let mut url = format!(
        "https://www.workatastartup.com/jobs?q={}&jobType=fulltime&sortBy=createdAt",
        url_encode(query)
    );
    if remote_only {
        url.push_str("&remote=only");
    }

    let html = client
        .get(&url)
        .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        .header("Accept-Language", "en-US,en;q=0.9")
        .header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        .send()
        .await?
        .text()
        .await?;

    extract_was_jobs(&html)
}

fn extract_was_jobs(html: &str) -> Result<Vec<WasJob>> {
    // The page embeds jobs as HTML-entity-encoded JSON
    let decoded = unescape_html(html);

    // Find "jobs":[ and extract the JSON array via bracket counting
    let marker = "\"jobs\":[";
    let start = decoded.find(marker).ok_or_else(|| anyhow::anyhow!("No jobs data found in page"))?;
    let array_start = start + marker.len() - 1; // points at '['

    let array_json = extract_json_array(&decoded[array_start..])
        .ok_or_else(|| anyhow::anyhow!("Could not extract jobs array"))?;

    let raw: Vec<serde_json::Value> = serde_json::from_str(array_json)
        .map_err(|e| anyhow::anyhow!("JSON parse error: {}", e))?;

    let jobs = raw
        .into_iter()
        .filter_map(|j| {
            let id = j["id"].as_u64()?;
            let title = j["title"].as_str()?.to_string();
            let company = j["companyName"].as_str()?.to_string();
            let _slug = j["companySlug"].as_str().unwrap_or("");
            let job_id = id;
            Some(WasJob {
                id,
                title,
                company,
                company_batch: j["companyBatch"].as_str().map(|s| s.to_string()),
                company_description: j["companyOneLiner"].as_str().map(|s| s.to_string()),
                job_type: j["jobType"].as_str().unwrap_or("Fulltime").to_string(),
                role_type: j["roleType"].as_str().map(|s| s.to_string()),
                location: j["location"].as_str().unwrap_or("Remote").to_string(),
                salary: j["salary"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string()),
                apply_url: j["applyUrl"].as_str().unwrap_or("").to_string(),
                was_url: format!("https://www.workatastartup.com/jobs/{}", job_id),
            })
        })
        .collect();

    Ok(jobs)
}

// ─── GitHub Repo Search ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct GitHubRepo {
    pub full_name: String,
    pub org: String,
    pub description: Option<String>,
    pub language: Option<String>,
    pub stars: u64,
    pub open_issues: u64,
    pub pushed_days_ago: i64,
    pub topics: Vec<String>,
    pub html_url: String,
    pub homepage: Option<String>,
}

/// Search GitHub repos by language + topic — finds companies building in your stack.
/// Feed results into list_org_repos + score_repo_issues for contribution targets.
pub async fn search_github_repos(
    client: &Client,
    token: &str,
    language: &str,
    topics: &[&str],
    min_stars: u32,
    limit: usize,
) -> Result<Vec<GitHubRepo>> {
    let mut q = Vec::new();
    if !language.is_empty() {
        q.push(format!("language:{}", language));
    }
    for topic in topics {
        q.push(format!("topic:{}", topic));
    }
    q.push("archived:false".to_string());
    if min_stars > 0 {
        q.push(format!("stars:>={}", min_stars));
    }
    let query = q.join("+");

    let resp: serde_json::Value = client
        .get("https://api.github.com/search/repositories")
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[
            ("q", query.as_str()),
            ("sort", "updated"),
            ("order", "desc"),
            ("per_page", &limit.min(30).to_string()),
        ])
        .send()
        .await?
        .json()
        .await?;

    let items = resp["items"].as_array().cloned().unwrap_or_default();

    let repos = items
        .into_iter()
        .filter_map(|r| {
            let full_name = r["full_name"].as_str()?.to_string();
            let org = full_name.split('/').next().unwrap_or("").to_string();
            let pushed_at = r["pushed_at"].as_str().unwrap_or("");
            let pushed_days_ago = days_ago_from_iso(pushed_at);

            Some(GitHubRepo {
                full_name,
                org,
                description: r["description"].as_str().map(|s| s.to_string()),
                language: r["language"].as_str().map(|s| s.to_string()),
                stars: r["stargazers_count"].as_u64().unwrap_or(0),
                open_issues: r["open_issues_count"].as_u64().unwrap_or(0),
                pushed_days_ago,
                topics: r["topics"]
                    .as_array()
                    .map(|a| a.iter().filter_map(|t| t.as_str().map(|s| s.to_string())).collect())
                    .unwrap_or_default(),
                html_url: r["html_url"].as_str().unwrap_or("").to_string(),
                homepage: r["homepage"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string()),
            })
        })
        .collect();

    Ok(repos)
}

// ─── Shared utilities ─────────────────────────────────────────────────────────

fn strip_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => {
                in_tag = false;
                out.push(' ');
            }
            _ if !in_tag => out.push(c),
            _ => {}
        }
    }
    out.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn unescape_html(s: &str) -> String {
    s.replace("&quot;", "\"")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
        .replace("&#x2F;", "/")
        .replace("&#x60;", "`")
        .replace("&#x3D;", "=")
}

fn url_encode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            ' ' => "+".to_string(),
            c => format!("%{:02X}", c as u32),
        })
        .collect()
}

/// Extract a JSON array starting at '[', using bracket counting
fn extract_json_array(s: &str) -> Option<&str> {
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escape_next = false;
    let bytes = s.as_bytes();

    for (i, &b) in bytes.iter().enumerate() {
        if escape_next {
            escape_next = false;
            continue;
        }
        match b {
            b'\\' if in_string => escape_next = true,
            b'"' => in_string = !in_string,
            b'[' if !in_string => {
                depth += 1;
            }
            b']' if !in_string => {
                depth -= 1;
                if depth == 0 {
                    return Some(&s[..=i]);
                }
            }
            _ => {}
        }
    }
    None
}

fn days_ago_from_iso(iso: &str) -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let ts = parse_iso_to_unix(iso).unwrap_or(0);
    (now - ts) / 86400
}

fn parse_iso_to_unix(s: &str) -> Option<i64> {
    // "2024-01-15T10:30:00Z"
    let parts: Vec<&str> = s.splitn(2, 'T').collect();
    let date_parts: Vec<i64> = parts.first()?.split('-')
        .filter_map(|p| p.parse().ok())
        .collect();
    if date_parts.len() != 3 { return None; }
    let (y, m, d) = (date_parts[0], date_parts[1], date_parts[2]);
    let years = y - 1970;
    let leap = years / 4 - years / 100 + years / 400;
    let month_days = [0i64, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    let extra = if m > 2 && (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)) { 1 } else { 0 };
    let days = years * 365 + leap + month_days[(m - 1) as usize] + extra + d - 1;
    Some(days * 86400)
}
