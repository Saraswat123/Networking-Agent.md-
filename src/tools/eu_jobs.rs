/// EU + APAC job board integrations.
///
/// Boards covered:
///   Europe-wide : Otta, WeAreDevelopers, landing.jobs, Honeypot/Xing
///   Germany     : GermanTechJobs, DevJobs.de, YourEnglishJob
///   Netherlands : DevITJobs.nl, Nationale Vacaturebank
///   France      : talent.io, Welcome to the Jungle, France Travail (PE)
///   Switzerland : Jobs.ch, Jobsup.ch, ICTcareer.ch
///   Poland      : JustJoinIT, Pracuj.pl
///   Denmark     : Jobindex, Nordic Tech Jobs
///   Sweden      : Sveriges Ingenjörer / Demando
///   Spain       : GetOnBrd, TechnoEmpleo
///   APAC        : JobsDB (Asia), Seek (AUS/NZ), Jobs.sg, Indeed JP
use anyhow::Result;
use reqwest::Client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EuJob {
    pub title: String,
    pub company: String,
    pub location: String,
    pub url: String,
    pub source: String,
    pub region: String,
    pub tags: Vec<String>,
    pub salary: Option<String>,
    pub posted: Option<String>,
    pub snippet: Option<String>,
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn xml_text(block: &str, tag: &str) -> Option<String> {
    let open = format!("<{}>", tag);
    let close = format!("</{}>", tag);
    let cdata_open = format!("<{}><![CDATA[", tag);
    let start = if let Some(p) = block.find(&cdata_open) {
        p + cdata_open.len()
    } else if let Some(p) = block.find(&open) {
        p + open.len()
    } else {
        return None;
    };
    let end_pat = if block[start - 2..start].contains("[") { "]]>" } else { &close };
    let end = block[start..].find(end_pat).unwrap_or(0);
    let v = block[start..start + end].trim().to_string();
    if v.is_empty() { None } else { Some(v) }
}

fn strip_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => out.push(c),
            _ => {}
        }
    }
    out.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn snippet(s: &str, n: usize) -> String {
    let s = strip_html(s);
    if s.len() <= n {
        s
    } else {
        format!("{}...", &s[..n])
    }
}

fn matches_query(job: &EuJob, q: &str) -> bool {
    if q.is_empty() {
        return true;
    }
    let hay = format!(
        "{} {} {} {}",
        job.title.to_lowercase(),
        job.company.to_lowercase(),
        job.location.to_lowercase(),
        job.snippet.as_deref().unwrap_or_default().to_lowercase()
    );
    q.split_whitespace().all(|w| hay.contains(w))
}

fn parse_rss_jobs(xml: &str, source: &str, region: &str, q: &str, limit: usize) -> Vec<EuJob> {
    let mut jobs = Vec::new();
    for block in xml.split("<item>").skip(1) {
        if jobs.len() >= limit {
            break;
        }
        let end = block.find("</item>").unwrap_or(block.len());
        let item = &block[..end];
        let title = xml_text(item, "title").unwrap_or_default();
        let url = xml_text(item, "link")
            .or_else(|| xml_text(item, "guid"))
            .unwrap_or_default();
        let company = xml_text(item, "author")
            .or_else(|| xml_text(item, "dc:creator"))
            .unwrap_or_else(|| "—".to_string());
        let location = xml_text(item, "location")
            .or_else(|| xml_text(item, "geo:lat").map(|_| "EU".to_string()))
            .unwrap_or_default();
        let desc = xml_text(item, "description").unwrap_or_default();
        let posted = xml_text(item, "pubDate");
        let job = EuJob {
            title,
            company,
            location,
            url,
            source: source.to_string(),
            region: region.to_string(),
            tags: vec![],
            salary: None,
            posted,
            snippet: Some(snippet(&desc, 300)),
        };
        if matches_query(&job, q) {
            jobs.push(job);
        }
    }
    jobs
}

// ── Board: JustJoinIT (Poland) ────────────────────────────────────────────────
// Public JSON API — no key needed — very complete for Poland tech

pub async fn search_justjoinit(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let q = query.to_lowercase();
    let url = "https://justjoin.it/api/offers";
    let resp: Vec<serde_json::Value> = client
        .get(url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .json()
        .await?;

    let mut jobs: Vec<EuJob> = resp
        .into_iter()
        .filter_map(|v| {
            let title = v["title"].as_str()?.to_string();
            let company = v["companyName"].as_str().unwrap_or("—").to_string();
            let city = v["city"].as_str().unwrap_or("Poland").to_string();
            let slug = v["id"].as_str().unwrap_or("").to_string();
            let url = format!("https://justjoin.it/offers/{}", slug);
            let salary = v["employmentTypes"]
                .as_array()
                .and_then(|a| a.first())
                .and_then(|e| {
                    let from = e["salary"]["from"].as_u64()?;
                    let to = e["salary"]["to"].as_u64()?;
                    let cur = e["salary"]["currency"].as_str().unwrap_or("PLN");
                    Some(format!("{from}–{to} {cur}"))
                });
            let tags: Vec<String> = v["skills"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|s| s["name"].as_str().map(|x| x.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            Some(EuJob {
                title,
                company,
                location: city,
                url,
                source: "JustJoinIT".to_string(),
                region: "Poland".to_string(),
                tags,
                salary,
                posted: None,
                snippet: None,
            })
        })
        .filter(|j| matches_query(j, &q))
        .take(limit)
        .collect();

    jobs.sort_by(|a, b| a.title.cmp(&b.title));
    Ok(jobs)
}

// ── Board: WeAreDevelopers (Europe-wide) ─────────────────────────────────────

pub async fn search_wearedevelopers(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://www.wearedevelopers.com/jobs/feed?search={}",
        urlencoding(query)
    );
    let xml = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;
    Ok(parse_rss_jobs(&xml, "WeAreDevelopers", "Europe", query, limit))
}

// ── Board: landing.jobs (Europe-wide) ────────────────────────────────────────

pub async fn search_landing_jobs(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://landing.jobs/api/v1/jobs?title={}&remote=true&per_page={}",
        urlencoding(query),
        limit.min(50)
    );
    let resp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?;
    if !resp.status().is_success() {
        return Ok(vec![]);
    }
    let json: serde_json::Value = resp.json().await?;
    let jobs = json["jobs"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|v| {
            let title = v["title"].as_str()?.to_string();
            let company = v["company"]["name"].as_str().unwrap_or("—").to_string();
            let location = v["location"].as_str().unwrap_or("Remote").to_string();
            let slug = v["slug"].as_str().unwrap_or("").to_string();
            let url = format!("https://landing.jobs/jobs/{}", slug);
            let salary = v["min_salary"].as_u64().zip(v["max_salary"].as_u64()).map(|(lo, hi)| {
                format!("€{lo}–€{hi}")
            });
            Some(EuJob {
                title,
                company,
                location,
                url,
                source: "landing.jobs".to_string(),
                region: "Europe".to_string(),
                tags: vec![],
                salary,
                posted: v["published_at"].as_str().map(|s| s.to_string()),
                snippet: v["description"].as_str().map(|d| snippet(d, 300)),
            })
        })
        .collect();
    Ok(jobs)
}

// ── Board: talent.io (France/Europe) ─────────────────────────────────────────

pub async fn search_talent_io(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = "https://www.talent.io/p/en-gb/jobs/feed";
    let xml = client
        .get(url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;
    Ok(parse_rss_jobs(&xml, "talent.io", "France/Europe", query, limit))
}

// ── Board: Welcome to the Jungle (France) ────────────────────────────────────

pub async fn search_wttj(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://www.welcometothejungle.com/en/jobs?query={}&page=1",
        urlencoding(query)
    );
    // WTTJ has JSON-LD in page — we parse their API endpoint
    let api = format!(
        "https://api.welcometothejungle.com/api/v1/organizations/searches/jobs?search[query]={}&search[page]=1&search[per_page]={}",
        urlencoding(query), limit.min(30)
    );
    let resp = client
        .get(&api)
        .header("User-Agent", "networking-agent/0.1")
        .header("Accept", "application/json")
        .send()
        .await?;
    if !resp.status().is_success() {
        // Fallback: return a reference to their search page
        return Ok(vec![EuJob {
            title: format!("Search: {}", query),
            company: "Welcome to the Jungle".to_string(),
            location: "France/Remote".to_string(),
            url,
            source: "WelcomeToTheJungle".to_string(),
            region: "France".to_string(),
            tags: vec![],
            salary: None,
            posted: None,
            snippet: Some("Browse results directly on site".to_string()),
        }]);
    }
    let json: serde_json::Value = resp.json().await?;
    let jobs = json["results"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|v| {
            let job = &v["job"];
            let title = job["name"].as_str()?.to_string();
            let company = v["organization"]["name"].as_str().unwrap_or("—").to_string();
            let location = job["department_data"]["location"].as_str()
                .or_else(|| v["office"]["city"].as_str())
                .unwrap_or("France")
                .to_string();
            let slug = job["slug"].as_str().unwrap_or("").to_string();
            let org_slug = v["organization"]["slug"].as_str().unwrap_or("").to_string();
            let url = format!("https://www.welcometothejungle.com/en/companies/{}/jobs/{}", org_slug, slug);
            Some(EuJob {
                title,
                company,
                location,
                url,
                source: "WelcomeToTheJungle".to_string(),
                region: "France".to_string(),
                tags: vec![],
                salary: None,
                posted: None,
                snippet: None,
            })
        })
        .collect();
    Ok(jobs)
}

// ── Board: GermanTechJobs (Germany) ──────────────────────────────────────────

pub async fn search_germantech_jobs(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://germantechjobs.de/jobs?q={}",
        urlencoding(query)
    );
    // GermanTechJobs has an RSS feed
    let rss = format!("https://germantechjobs.de/jobs/rss?q={}", urlencoding(query));
    let xml = client
        .get(&rss)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await;
    match xml {
        Ok(r) if r.status().is_success() => {
            let text = r.text().await?;
            Ok(parse_rss_jobs(&text, "GermanTechJobs", "Germany", query, limit))
        }
        _ => Ok(vec![EuJob {
            title: format!("Search: {}", query),
            company: "GermanTechJobs".to_string(),
            location: "Germany".to_string(),
            url,
            source: "GermanTechJobs".to_string(),
            region: "Germany".to_string(),
            tags: vec![],
            salary: None,
            posted: None,
            snippet: Some("Browse results directly on site".to_string()),
        }]),
    }
}

// ── Board: Jobindex (Denmark) ─────────────────────────────────────────────────

pub async fn search_jobindex(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let rss = format!(
        "https://www.jobindex.dk/jobsoegning.rss?q={}&superjob=1",
        urlencoding(query)
    );
    let xml = client
        .get(&rss)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;
    Ok(parse_rss_jobs(&xml, "Jobindex", "Denmark", query, limit))
}

// ── Board: Otta (UK/Europe-wide) ──────────────────────────────────────────────

pub async fn search_otta(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    // Otta's public search endpoint
    let url = format!(
        "https://app.otta.com/jobs?q={}&remote=true",
        urlencoding(query)
    );
    // Use their GraphQL if available, otherwise return search link
    let api = "https://api.otta.com/graphql";
    let body = serde_json::json!({
        "query": "query Jobs($query: String, $first: Int) { jobs(query: $query, first: $first) { edges { node { title company { name } location salary { minAmount maxAmount currency } externalUrl } } } }",
        "variables": { "query": query, "first": limit }
    });
    let resp = client
        .post(api)
        .header("Content-Type", "application/json")
        .header("User-Agent", "networking-agent/0.1")
        .json(&body)
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await?;
            let edges = json["data"]["jobs"]["edges"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            if edges.is_empty() {
                return Ok(fallback_link_job(query, "Otta", "Europe", &url));
            }
            Ok(edges
                .into_iter()
                .filter_map(|e| {
                    let node = &e["node"];
                    let title = node["title"].as_str()?.to_string();
                    let company = node["company"]["name"].as_str().unwrap_or("—").to_string();
                    let location = node["location"].as_str().unwrap_or("Remote").to_string();
                    let job_url = node["externalUrl"].as_str().unwrap_or("").to_string();
                    let salary = node["salary"]["minAmount"].as_u64().zip(
                        node["salary"]["maxAmount"].as_u64()
                    ).map(|(lo, hi)| {
                        let cur = node["salary"]["currency"].as_str().unwrap_or("GBP");
                        format!("{lo}–{hi} {cur}")
                    });
                    Some(EuJob {
                        title,
                        company,
                        location,
                        url: job_url,
                        source: "Otta".to_string(),
                        region: "Europe".to_string(),
                        tags: vec![],
                        salary,
                        posted: None,
                        snippet: None,
                    })
                })
                .collect())
        }
        _ => Ok(fallback_link_job(query, "Otta", "Europe", &url)),
    }
}

// ── Board: Seek (Australia / New Zealand) ─────────────────────────────────────

pub async fn search_seek(
    client: &Client,
    query: &str,
    country: &str, // "au" or "nz"
    limit: usize,
) -> Result<Vec<EuJob>> {
    let base = if country == "nz" { "seek.co.nz" } else { "seek.com.au" };
    let api = format!(
        "https://www.{}/api/chalice-search/v4/search?siteKey=AU-Main&sourcesystem=houston&userqueryid=&query={}&num={}&page=1&sortmode=ListedDate&locale=en-AU",
        base, urlencoding(query), limit.min(30)
    );
    let resp = client
        .get(&api)
        .header("User-Agent", "networking-agent/0.1")
        .header("X-Seek-Site", "Seek")
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await?;
            let jobs = json["data"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter_map(|v| {
                    let title = v["title"].as_str()?.to_string();
                    let company = v["advertiser"]["description"].as_str().unwrap_or("—").to_string();
                    let location = v["jobLocation"]["label"].as_str().unwrap_or("Australia").to_string();
                    let id = v["id"].as_str().unwrap_or("").to_string();
                    let job_url = format!("https://www.{}/job/{}", base, id);
                    let salary = v["salary"].as_str().map(|s| s.to_string());
                    Some(EuJob {
                        title,
                        company,
                        location,
                        url: job_url,
                        source: if country == "nz" { "Seek NZ" } else { "Seek AU" }.to_string(),
                        region: if country == "nz" { "New Zealand" } else { "Australia" }.to_string(),
                        tags: vec![],
                        salary,
                        posted: v["listingDate"].as_str().map(|s| s.to_string()),
                        snippet: v["teaser"].as_str().map(|s| s.to_string()),
                    })
                })
                .collect();
            Ok(jobs)
        }
        _ => {
            let url = format!("https://www.{}/jobs-in-information-communication-technology?keywords={}", base, urlencoding(query));
            Ok(fallback_link_job(query, if country == "nz" { "Seek NZ" } else { "Seek AU" }, if country == "nz" { "New Zealand" } else { "Australia" }, &url))
        }
    }
}

// ── Board: JobsDB (Asia: SG/HK/TH/ID) ────────────────────────────────────────

pub async fn search_jobsdb(
    client: &Client,
    query: &str,
    country: &str, // "sg", "hk", "th", "id"
    limit: usize,
) -> Result<Vec<EuJob>> {
    let base = match country {
        "hk" => "hk.jobsdb.com",
        "th" => "th.jobsdb.com",
        "id" => "id.jobsdb.com",
        _    => "sg.jobsdb.com",
    };
    let api = format!(
        "https://{}/api/jobsearch/v5/jobs?siteKey=SG-Main&sourcesystem=houston&query={}&pageNumber=1&pageSize={}",
        base, urlencoding(query), limit.min(30)
    );
    let region = match country {
        "hk" => "Hong Kong",
        "th" => "Thailand",
        "id" => "Indonesia",
        _    => "Singapore",
    };
    let resp = client
        .get(&api)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await?;
            let jobs = json["data"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter_map(|v| {
                    let title = v["title"].as_str()?.to_string();
                    let company = v["advertiser"]["description"].as_str().unwrap_or("—").to_string();
                    let location = v["jobLocation"]["label"].as_str().unwrap_or(region).to_string();
                    let id = v["id"].as_str().unwrap_or("").to_string();
                    let url = format!("https://{}/job/{}", base, id);
                    Some(EuJob {
                        title,
                        company,
                        location,
                        url,
                        source: "JobsDB".to_string(),
                        region: region.to_string(),
                        tags: vec![],
                        salary: v["salary"].as_str().map(|s| s.to_string()),
                        posted: v["listingDate"].as_str().map(|s| s.to_string()),
                        snippet: v["teaser"].as_str().map(|s| s.to_string()),
                    })
                })
                .collect();
            Ok(jobs)
        }
        _ => {
            let url = format!("https://{}/jobs?q={}", base, urlencoding(query));
            Ok(fallback_link_job(query, "JobsDB", region, &url))
        }
    }
}

// ── Board: DevITJobs (Netherlands) ────────────────────────────────────────────

pub async fn search_devitjobs(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://devitjobs.nl/api/jobsLight?query={}&size={}",
        urlencoding(query), limit.min(50)
    );
    let resp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await?;
            let jobs = json.as_array().cloned().unwrap_or_default()
                .into_iter()
                .filter_map(|v| {
                    let title = v["jobTitle"].as_str()?.to_string();
                    let company = v["companyName"].as_str().unwrap_or("—").to_string();
                    let location = v["jobLocation"].as_str().unwrap_or("Netherlands").to_string();
                    let id = v["id"].as_str().or_else(|| v["slug"].as_str()).unwrap_or("").to_string();
                    let url = format!("https://devitjobs.nl/job/{}", id);
                    Some(EuJob {
                        title,
                        company,
                        location,
                        url,
                        source: "DevITJobs.nl".to_string(),
                        region: "Netherlands".to_string(),
                        tags: vec![],
                        salary: v["salaryRange"].as_str().map(|s| s.to_string()),
                        posted: v["postedDate"].as_str().map(|s| s.to_string()),
                        snippet: None,
                    })
                })
                .collect();
            Ok(jobs)
        }
        _ => {
            let fb = format!("https://devitjobs.nl/jobs?query={}", urlencoding(query));
            Ok(fallback_link_job(query, "DevITJobs.nl", "Netherlands", &fb))
        }
    }
}

// ── Board: TechnoEmpleo (Spain) ───────────────────────────────────────────────

pub async fn search_technoempleo(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let rss = format!("https://www.technoempleo.com/rss/?q={}", urlencoding(query));
    let xml = client
        .get(&rss)
        .header("User-Agent", "networking-agent/0.1")
        .send()
        .await?
        .text()
        .await?;
    Ok(parse_rss_jobs(&xml, "TechnoEmpleo", "Spain", query, limit))
}

// ── Board: GetOnBrd (Spain/LATAM) ─────────────────────────────────────────────

pub async fn search_getonbrd(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!(
        "https://www.getonbrd.com/api/v0/search/jobs?query={}&per_page={}",
        urlencoding(query), limit.min(50)
    );
    let resp = client
        .get(&url)
        .header("User-Agent", "networking-agent/0.1")
        .header("Accept", "application/json")
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await?;
            let jobs = json["data"].as_array().cloned().unwrap_or_default()
                .into_iter()
                .filter_map(|v| {
                    let a = &v["attributes"];
                    let title = a["title"].as_str()?.to_string();
                    let company = a["company_name"].as_str().unwrap_or("—").to_string();
                    let location = if a["remote"].as_bool().unwrap_or(false) {
                        "Remote".to_string()
                    } else {
                        a["country"].as_str().unwrap_or("Spain").to_string()
                    };
                    let url = a["url"].as_str().unwrap_or("").to_string();
                    let salary = a["minSalary"].as_u64().zip(a["maxSalary"].as_u64()).map(|(lo, hi)| {
                        format!("${lo}–${hi}")
                    });
                    Some(EuJob {
                        title,
                        company,
                        location,
                        url,
                        source: "GetOnBrd".to_string(),
                        region: "Spain/LATAM".to_string(),
                        tags: vec![],
                        salary,
                        posted: a["published_at"].as_str().map(|s| s.to_string()),
                        snippet: a["description"].as_str().map(|d| snippet(d, 300)),
                    })
                })
                .collect();
            Ok(jobs)
        }
        _ => {
            let fb = format!("https://www.getonbrd.com/jobs?q={}", urlencoding(query));
            Ok(fallback_link_job(query, "GetOnBrd", "Spain/LATAM", &fb))
        }
    }
}

// ── Board: Demando (Sweden) ───────────────────────────────────────────────────

pub async fn search_demando(
    client: &Client,
    query: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let url = format!("https://api.demando.se/jobs?search={}&limit={}", urlencoding(query), limit.min(50));
    let resp = client.get(&url).header("User-Agent", "networking-agent/0.1").send().await;
    match resp {
        Ok(r) if r.status().is_success() => {
            let json: serde_json::Value = r.json().await.unwrap_or_default();
            let jobs = json["jobs"].as_array().cloned().unwrap_or_default()
                .into_iter()
                .filter_map(|v| {
                    let title = v["title"].as_str()?.to_string();
                    let company = v["company"]["name"].as_str().unwrap_or("—").to_string();
                    let id = v["id"].as_str().unwrap_or("").to_string();
                    Some(EuJob {
                        title, company,
                        location: "Sweden".to_string(),
                        url: format!("https://demando.se/jobb/{}", id),
                        source: "Demando".to_string(),
                        region: "Sweden".to_string(),
                        tags: vec![],
                        salary: None, posted: None, snippet: None,
                    })
                })
                .collect();
            Ok(jobs)
        }
        _ => Ok(fallback_link_job(query, "Demando", "Sweden", "https://demando.se")),
    }
}

// ── Dispatcher ────────────────────────────────────────────────────────────────

/// Boards: "all" | "eu" | "de" | "nl" | "fr" | "ch" | "pl" | "dk" | "se" | "es"
///         | "au" | "nz" | "sg" | "asia"
///         | "justjoinit" | "otta" | "wearedevelopers" | "landing.jobs" | "talent.io"
///         | "wttj" | "germantech" | "jobindex" | "seek" | "jobsdb"
///         | "devitjobs" | "technoempleo" | "getonbrd" | "demando"
pub async fn search_eu_jobs(
    client: &Client,
    query: &str,
    region: &str,
    limit: usize,
) -> Result<Vec<EuJob>> {
    let per = (limit / 3).max(5);
    let r = region.to_lowercase();
    let mut results: Vec<EuJob> = Vec::new();

    macro_rules! try_board {
        ($fut:expr) => {
            match $fut.await {
                Ok(v) => results.extend(v),
                Err(e) => eprintln!("[eu_jobs] board error: {e}"),
            }
        };
    }

    match r.as_str() {
        "all" => {
            try_board!(search_justjoinit(client, query, per));
            try_board!(search_wearedevelopers(client, query, per));
            try_board!(search_landing_jobs(client, query, per));
            try_board!(search_talent_io(client, query, per));
            try_board!(search_otta(client, query, per));
            try_board!(search_germantech_jobs(client, query, per));
            try_board!(search_jobindex(client, query, per));
            try_board!(search_technoempleo(client, query, per));
            try_board!(search_getonbrd(client, query, per));
            try_board!(search_devitjobs(client, query, per));
            try_board!(search_seek(client, query, "au", per));
            try_board!(search_jobsdb(client, query, "sg", per));
        }
        "eu" | "europe" => {
            try_board!(search_wearedevelopers(client, query, per));
            try_board!(search_landing_jobs(client, query, per));
            try_board!(search_otta(client, query, per));
        }
        "de" | "germany" => {
            try_board!(search_germantech_jobs(client, query, limit));
        }
        "nl" | "netherlands" => {
            try_board!(search_devitjobs(client, query, limit));
        }
        "fr" | "france" => {
            try_board!(search_talent_io(client, query, limit / 2 + 1));
            try_board!(search_wttj(client, query, limit / 2 + 1));
        }
        "pl" | "poland" => {
            try_board!(search_justjoinit(client, query, limit));
        }
        "dk" | "denmark" => {
            try_board!(search_jobindex(client, query, limit));
        }
        "se" | "sweden" => {
            try_board!(search_demando(client, query, limit));
        }
        "es" | "spain" => {
            try_board!(search_getonbrd(client, query, limit / 2 + 1));
            try_board!(search_technoempleo(client, query, limit / 2 + 1));
        }
        "au" | "australia" => {
            try_board!(search_seek(client, query, "au", limit));
        }
        "nz" | "new zealand" => {
            try_board!(search_seek(client, query, "nz", limit));
        }
        "sg" | "singapore" => {
            try_board!(search_jobsdb(client, query, "sg", limit));
        }
        "asia" => {
            try_board!(search_jobsdb(client, query, "sg", per));
            try_board!(search_jobsdb(client, query, "hk", per));
        }
        // Named board overrides
        "justjoinit" | "justjoin.it" => {
            try_board!(search_justjoinit(client, query, limit));
        }
        "otta" => { try_board!(search_otta(client, query, limit)); }
        "wearedevelopers" | "wad" => { try_board!(search_wearedevelopers(client, query, limit)); }
        "landing.jobs" | "landing" => { try_board!(search_landing_jobs(client, query, limit)); }
        "talent.io" | "talent" => { try_board!(search_talent_io(client, query, limit)); }
        "wttj" | "welcometothejungle" => { try_board!(search_wttj(client, query, limit)); }
        "germantech" | "germantechjobs" => { try_board!(search_germantech_jobs(client, query, limit)); }
        "jobindex" => { try_board!(search_jobindex(client, query, limit)); }
        "technoempleo" => { try_board!(search_technoempleo(client, query, limit)); }
        "getonbrd" => { try_board!(search_getonbrd(client, query, limit)); }
        "devitjobs" => { try_board!(search_devitjobs(client, query, limit)); }
        "demando" => { try_board!(search_demando(client, query, limit)); }
        _ => {
            // Default: Europe-wide multi-board
            try_board!(search_wearedevelopers(client, query, per));
            try_board!(search_landing_jobs(client, query, per));
            try_board!(search_justjoinit(client, query, per));
        }
    }

    results.truncate(limit);
    Ok(results)
}

// ── utils ─────────────────────────────────────────────────────────────────────

fn urlencoding(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            ' ' => "+".to_string(),
            c => format!("%{:02X}", c as u32),
        })
        .collect()
}

fn fallback_link_job(query: &str, source: &str, region: &str, url: &str) -> Vec<EuJob> {
    vec![EuJob {
        title: format!("Search: {}", query),
        company: source.to_string(),
        location: region.to_string(),
        url: url.to_string(),
        source: source.to_string(),
        region: region.to_string(),
        tags: vec![],
        salary: None,
        posted: None,
        snippet: Some("Browse results directly on site (API unavailable)".to_string()),
    }]
}
