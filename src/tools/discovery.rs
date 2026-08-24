use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

// ─── Funding News ─────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct FundingNews {
    pub title: String,
    pub company: String,
    pub amount: Option<String>,
    pub round: Option<String>,
    pub description: String,
    pub url: String,
    pub pub_date: String,
    pub source: String,
}

/// Aggregate funding news from TechCrunch + EU-Startups + Sifted RSS.
/// Returns recently-funded companies — these are hiring NOW.
/// filter_round: "seed", "series-a", "series-b", "" for all
pub async fn search_funding_news(
    client: &Client,
    filter_round: &str,
    limit: usize,
) -> Result<Vec<FundingNews>> {
    let feeds = vec![
        ("https://techcrunch.com/category/venture/feed/", "TechCrunch"),
        ("https://eu-startups.com/feed/", "EU-Startups"),
        ("https://sifted.eu/feed/", "Sifted"),
    ];

    let mut all: Vec<FundingNews> = Vec::new();

    for (url, source_name) in feeds {
        match client
            .get(url)
            .header("User-Agent", "networking-agent/0.1")
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                if let Ok(xml) = resp.text().await {
                    let mut items = parse_funding_rss(&xml, source_name, filter_round);
                    all.append(&mut items);
                }
            }
            _ => {} // Skip failed feeds silently
        }
    }

    // Sort by date descending (newest first), take limit
    all.sort_by(|a, b| b.pub_date.cmp(&a.pub_date));
    all.truncate(limit);
    Ok(all)
}

fn parse_funding_rss(xml: &str, source: &str, filter_round: &str) -> Vec<FundingNews> {
    let mut items = Vec::new();
    let q = filter_round.to_lowercase();

    for block in xml.split("<item>").skip(1) {
        let end = block.find("</item>").unwrap_or(block.len());
        let item = &block[..end];

        let title = extract_xml_text(item, "title").unwrap_or_default();
        let link = extract_xml_text(item, "link")
            .or_else(|| extract_xml_text(item, "guid"))
            .unwrap_or_default();
        let pub_date = extract_xml_text(item, "pubDate").unwrap_or_default();
        let description = extract_xml_text(item, "description").unwrap_or_default();
        let description = strip_html(&description);

        // Only funding-related articles
        let haystack = format!("{} {}", title.to_lowercase(), description.to_lowercase());
        let is_funding = haystack.contains("raises")
            || haystack.contains("raised")
            || haystack.contains("funding")
            || haystack.contains("series a")
            || haystack.contains("series b")
            || haystack.contains("series c")
            || haystack.contains("seed round")
            || haystack.contains("million")
            || haystack.contains("investment");

        if !is_funding {
            continue;
        }

        // Round filter
        if !q.is_empty() {
            let round_match = match q.as_str() {
                "seed" => haystack.contains("seed"),
                "series-a" | "series_a" => haystack.contains("series a"),
                "series-b" | "series_b" => haystack.contains("series b"),
                "series-c" | "series_c" => haystack.contains("series c"),
                _ => haystack.contains(&q),
            };
            if !round_match {
                continue;
            }
        }

        let (company, amount, round) = extract_funding_signals(&title, &description);

        let snippet = description.chars().take(400).collect::<String>();
        let snippet = if description.len() > 400 {
            format!("{}...", snippet)
        } else {
            description
        };

        items.push(FundingNews {
            title: title.clone(),
            company,
            amount,
            round,
            description: snippet,
            url: link,
            pub_date,
            source: source.to_string(),
        });
    }

    items
}

/// Heuristic extraction of company name, amount, round from headline.
/// E.g. "Acme raises $12M Series A to build..." → company=Acme, amount=$12M, round=Series A
fn extract_funding_signals(
    title: &str,
    description: &str,
) -> (String, Option<String>, Option<String>) {
    let haystack = format!("{} {}", title, description).to_lowercase();

    // Amount: $XM, $X million, $XB
    let amount = extract_money(title).or_else(|| extract_money(description));

    // Round detection
    let round = if haystack.contains("series c") {
        Some("Series C".into())
    } else if haystack.contains("series b") {
        Some("Series B".into())
    } else if haystack.contains("series a") {
        Some("Series A".into())
    } else if haystack.contains("seed") {
        Some("Seed".into())
    } else if haystack.contains("pre-seed") || haystack.contains("pre seed") {
        Some("Pre-Seed".into())
    } else {
        None
    };

    // Company: take first word(s) before "raises" / "secures" / "announces"
    let company = extract_company_from_headline(title);

    (company, amount, round)
}

fn extract_money(text: &str) -> Option<String> {
    // Match $XM, $X.YM, $XB patterns
    let bytes = text.as_bytes();
    for i in 0..bytes.len() {
        if bytes[i] == b'$' {
            let rest = &text[i..];
            let end = rest
                .chars()
                .take_while(|c| c.is_ascii_digit() || *c == '.' || *c == 'M' || *c == 'B' || *c == 'K')
                .count();
            if end > 1 {
                return Some(rest[..end].to_string());
            }
        }
    }
    // "X million" fallback
    if let Some(pos) = text.to_lowercase().find(" million") {
        let prefix: String = text[..pos].split_whitespace().last().unwrap_or("").to_string();
        if !prefix.is_empty() {
            return Some(format!("{}M", prefix));
        }
    }
    None
}

fn extract_company_from_headline(title: &str) -> String {
    let keywords = ["raises", "secures", "closes", "announces", "lands", "gets", "nabs"];
    for kw in &keywords {
        if let Some(pos) = title.to_lowercase().find(kw) {
            return title[..pos].trim().to_string();
        }
    }
    // Take first 3 words as fallback
    title.split_whitespace().take(3).collect::<Vec<_>>().join(" ")
}

// ─── Remotive (global remote jobs) ───────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct RemotiveJob {
    pub title: String,
    pub company: String,
    pub category: String,
    pub url: String,
    pub pub_date: String,
    pub location: String,
    pub description_snippet: String,
}

/// Fetch Remotive.io RSS — global remote jobs, covers EU/Asia/LATAM companies YC misses.
/// category: "software-dev", "devops-sysadmin", "all" (empty = all)
/// query: keyword filter applied to title + description
pub async fn search_remotive(
    client: &Client,
    query: &str,
    category: &str,
    limit: usize,
) -> Result<Vec<RemotiveJob>> {
    let feed_url = if category.is_empty() || category == "all" {
        "https://remotive.com/remote-jobs/feed/".to_string()
    } else {
        format!("https://remotive.com/remote-jobs/{}/feed/", category)
    };

    let xml = client
        .get(&feed_url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;

    parse_remotive_rss(&xml, query, limit)
}

fn parse_remotive_rss(xml: &str, query: &str, limit: usize) -> Result<Vec<RemotiveJob>> {
    let q = query.to_lowercase();
    let mut jobs = Vec::new();

    for block in xml.split("<item>").skip(1) {
        if jobs.len() >= limit {
            break;
        }
        let end = block.find("</item>").unwrap_or(block.len());
        let item = &block[..end];

        let title = extract_xml_text(item, "title").unwrap_or_default();
        let link = extract_xml_text(item, "link")
            .or_else(|| extract_xml_text(item, "guid"))
            .unwrap_or_default();
        let pub_date = extract_xml_text(item, "pubDate").unwrap_or_default();
        let description = extract_xml_text(item, "description").unwrap_or_default();
        let description = strip_html(&description);
        let category = extract_xml_text(item, "category").unwrap_or_else(|| "General".to_string());

        // Company is often in <author> or embedded in title "Role at Company"
        let company = extract_xml_text(item, "author")
            .or_else(|| extract_company_from_job_title(&title))
            .unwrap_or_else(|| "Unknown".to_string());

        // Query filter
        if !q.is_empty() {
            let haystack = format!("{} {} {}", title, description, category).to_lowercase();
            if !haystack.contains(&q) {
                continue;
            }
        }

        let snippet: String = description.chars().take(350).collect();
        let snippet = if description.len() > 350 {
            format!("{}...", snippet)
        } else {
            description
        };

        jobs.push(RemotiveJob {
            title,
            company,
            category,
            url: link,
            pub_date,
            location: "Remote (Worldwide)".to_string(),
            description_snippet: snippet,
        });
    }

    Ok(jobs)
}

fn extract_company_from_job_title(title: &str) -> Option<String> {
    if let Some(pos) = title.rfind(" at ") {
        return Some(title[pos + 4..].trim().to_string());
    }
    None
}

// ─── GitHub Trending ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct TrendingRepo {
    pub name: String,
    pub owner: String,
    pub full_name: String,
    pub description: Option<String>,
    pub language: Option<String>,
    pub stars: u64,
    pub forks: u64,
    pub stars_today: Option<u64>,
    pub html_url: String,
    pub homepage: Option<String>,
    pub topics: Vec<String>,
    pub open_issues: u64,
}

/// GitHub trending repos — active companies building NOW.
/// language: "rust", "go", "python", etc. or "" for all.
/// since: "daily", "weekly", "monthly" (default: weekly for better signal)
/// Uses unofficial trending API via github-trending-api alternative approach:
/// scrapes https://github.com/trending/{lang}?since={since}
pub async fn search_github_trending(
    client: &Client,
    token: &str,
    language: &str,
    since: &str,
    limit: usize,
) -> Result<Vec<TrendingRepo>> {
    // Use GitHub search API as reliable trending proxy:
    // sort by stars, pushed in last 7 days, filter by language
    let since_days = match since {
        "daily" => 1,
        "monthly" => 30,
        _ => 7, // weekly default
    };

    // Calculate date cutoff
    let cutoff = {
        use std::time::{SystemTime, UNIX_EPOCH};
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let cutoff_secs = now.saturating_sub(since_days * 86400);
        // Format as YYYY-MM-DD
        let days_since_epoch = cutoff_secs / 86400;
        let (y, m, d) = unix_days_to_ymd(days_since_epoch as i64);
        format!("{:04}-{:02}-{:02}", y, m, d)
    };

    let mut q = format!("pushed:>{}", cutoff);
    if !language.is_empty() {
        q.push_str(&format!(" language:{}", language));
    }
    q.push_str(" archived:false stars:>10");

    let mut req = client
        .get("https://api.github.com/search/repositories")
        .header("User-Agent", "networking-agent/0.1")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .query(&[
            ("q", q.as_str()),
            ("sort", "stars"),
            ("order", "desc"),
            ("per_page", &limit.min(30).to_string()),
        ]);

    if !token.is_empty() {
        req = req.header("Authorization", format!("Bearer {}", token));
    }

    let resp: serde_json::Value = req.send().await?.json().await?;

    let items = resp["items"].as_array().cloned().unwrap_or_default();
    let repos = items
        .into_iter()
        .filter_map(|r| {
            let full_name = r["full_name"].as_str()?.to_string();
            let parts: Vec<&str> = full_name.splitn(2, '/').collect();
            let owner = parts.first().unwrap_or(&"").to_string();
            let name = parts.get(1).unwrap_or(&"").to_string();

            Some(TrendingRepo {
                name,
                owner,
                full_name,
                description: r["description"].as_str().map(|s| s.to_string()),
                language: r["language"].as_str().map(|s| s.to_string()),
                stars: r["stargazers_count"].as_u64().unwrap_or(0),
                forks: r["forks_count"].as_u64().unwrap_or(0),
                stars_today: None, // GitHub API doesn't expose daily delta
                html_url: r["html_url"].as_str().unwrap_or("").to_string(),
                homepage: r["homepage"].as_str().filter(|s| !s.is_empty()).map(|s| s.to_string()),
                topics: r["topics"]
                    .as_array()
                    .map(|a| a.iter().filter_map(|t| t.as_str().map(|s| s.to_string())).collect())
                    .unwrap_or_default(),
                open_issues: r["open_issues_count"].as_u64().unwrap_or(0),
            })
        })
        .collect();

    Ok(repos)
}

// ─── Wellfound / AngelList ────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct WellfoundJob {
    pub title: String,
    pub company: String,
    pub company_size: Option<String>,
    pub company_stage: Option<String>,
    pub remote: bool,
    pub locations: Vec<String>,
    pub salary: Option<String>,
    pub equity: Option<String>,
    pub url: String,
    pub tags: Vec<String>,
    pub description_snippet: String,
}

/// Search Wellfound (AngelList) startup jobs.
/// Wellfound embeds job data as JSON in the page HTML.
/// role: "engineer", "backend", "frontend", "fullstack", "data", "devops"
/// remote: filter to remote-only positions
pub async fn search_wellfound(
    client: &Client,
    role: &str,
    keywords: &str,
    remote_only: bool,
    limit: usize,
) -> Result<Vec<WellfoundJob>> {
    // Wellfound job search URL
    let mut url = format!(
        "https://wellfound.com/role/r/{}?keywords={}",
        url_encode(role),
        url_encode(keywords),
    );
    if remote_only {
        url.push_str("&remote=true");
    }

    let html = client
        .get(&url)
        .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        .header("Accept-Language", "en-US,en;q=0.9")
        .header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        .header("Referer", "https://wellfound.com/")
        .send()
        .await?
        .text()
        .await?;

    extract_wellfound_jobs(&html, limit)
}

fn extract_wellfound_jobs(html: &str, limit: usize) -> Result<Vec<WellfoundJob>> {
    let mut jobs = Vec::new();

    // Wellfound embeds data in __NEXT_DATA__ JSON script tag
    let marker = "\"__NEXT_DATA__\"";
    let json_start_marker = "<script id=\"__NEXT_DATA__\" type=\"application/json\">";

    if let Some(start) = html.find(json_start_marker) {
        let after = &html[start + json_start_marker.len()..];
        if let Some(end) = after.find("</script>") {
            let json_str = &after[..end];
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(json_str) {
                // Navigate: props.pageProps.jobListings or similar
                let listings = find_job_listings(&data);
                for listing in listings.into_iter().take(limit) {
                    if let Some(job) = parse_wellfound_listing(&listing) {
                        jobs.push(job);
                    }
                }
            }
        }
    }

    // If NEXT_DATA parse failed, return a meaningful message as a single entry
    if jobs.is_empty() {
        // Wellfound may require JS rendering; return partial info
        jobs.push(WellfoundJob {
            title: "Wellfound requires JS rendering".to_string(),
            company: "N/A".to_string(),
            company_size: None,
            company_stage: None,
            remote: true,
            locations: vec!["Remote".to_string()],
            salary: None,
            equity: None,
            url: "https://wellfound.com/jobs".to_string(),
            tags: vec![],
            description_snippet: format!(
                "Wellfound/AngelList uses client-side rendering. Use direct URL: {}",
                marker
            ),
        });
    }

    Ok(jobs)
}

fn find_job_listings(data: &serde_json::Value) -> Vec<serde_json::Value> {
    // Try common paths in Next.js data structure
    let paths = [
        &data["props"]["pageProps"]["jobListings"],
        &data["props"]["pageProps"]["jobs"],
        &data["props"]["pageProps"]["startupJobs"],
        &data["props"]["pageProps"]["data"]["jobListings"],
    ];
    for path in &paths {
        if let Some(arr) = path.as_array() {
            return arr.clone();
        }
    }
    Vec::new()
}

fn parse_wellfound_listing(j: &serde_json::Value) -> Option<WellfoundJob> {
    let title = j["title"].as_str()?.to_string();
    let company = j["startup"]["name"].as_str()
        .or_else(|| j["companyName"].as_str())
        .unwrap_or("Unknown")
        .to_string();

    let tags: Vec<String> = j["skills"]
        .as_array()
        .map(|a| a.iter().filter_map(|t| t["name"].as_str().map(|s| s.to_string())).collect())
        .or_else(|| {
            j["tags"].as_array()
                .map(|a| a.iter().filter_map(|t| t.as_str().map(|s| s.to_string())).collect())
        })
        .unwrap_or_default();

    let description = j["description"].as_str().unwrap_or("");
    let snippet: String = strip_html(description).chars().take(350).collect();

    Some(WellfoundJob {
        title,
        company,
        company_size: j["startup"]["companySize"].as_str().map(|s| s.to_string()),
        company_stage: j["startup"]["stage"].as_str().map(|s| s.to_string()),
        remote: j["remote"].as_bool().unwrap_or(false),
        locations: j["locations"]
            .as_array()
            .map(|a| a.iter().filter_map(|l| l.as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default(),
        salary: j["salary"].as_str().map(|s| s.to_string()),
        equity: j["equity"].as_str().map(|s| s.to_string()),
        url: j["url"].as_str()
            .map(|u| if u.starts_with("http") { u.to_string() } else { format!("https://wellfound.com{}", u) })
            .unwrap_or_else(|| "https://wellfound.com/jobs".to_string()),
        tags,
        description_snippet: snippet,
    })
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

fn unescape_html(s: &str) -> String {
    s.replace("&quot;", "\"")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
        .replace("&#x2F;", "/")
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

fn unix_days_to_ymd(days: i64) -> (i64, i64, i64) {
    // Simplified Gregorian calendar
    let mut remaining = days;
    let mut year = 1970i64;
    loop {
        let days_in_year = if is_leap(year) { 366 } else { 365 };
        if remaining < days_in_year {
            break;
        }
        remaining -= days_in_year;
        year += 1;
    }
    let month_days = [
        31i64,
        if is_leap(year) { 29 } else { 28 },
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ];
    let mut month = 1i64;
    for &md in &month_days {
        if remaining < md {
            break;
        }
        remaining -= md;
        month += 1;
    }
    (year, month, remaining + 1)
}

fn is_leap(y: i64) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}
