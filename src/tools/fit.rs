use serde::{Deserialize, Serialize};

/// Direction A = proposal (you build something for them)
/// Direction B = job (you apply as candidate)
/// Skip = wrong fit
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub enum Direction {
    A,
    B,
    Skip,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RoleFit {
    pub direction: String,
    pub fit_score: i32,      // 0-100
    pub stack_match: bool,
    pub remote_ok: bool,
    pub compensation_ok: bool,
    pub signals: Vec<String>,
    pub skip_reason: Option<String>,
}

/// Score role fit from title + description text.
/// Returns direction (A/B/skip), score, and signals.
/// Compensation filter: INR/₹/LPA → flag as non-remote-budget.
/// Stack filter: frontend/mobile/design/PM → skip.
/// Direction A trigger: "founding engineer", "head of", "staff", "principal", "infra" at a company.
/// Direction B trigger: explicit "we're hiring", "apply", job description format.
pub fn score_role_fit(title: &str, description: &str) -> RoleFit {
    let title_l = title.to_lowercase();
    let desc_l = description.to_lowercase();
    let combined = format!("{} {}", title_l, desc_l);

    let mut score = 0i32;
    let mut signals: Vec<String> = Vec::new();
    let mut skip_reason: Option<String> = None;

    // ── Hard skips ──────────────────────────────────────────────────────────────

    let skip_roles = [
        "frontend", "front-end", "react native", "ios developer", "android developer",
        "mobile developer", "flutter", "ux designer", "ui designer", "product designer",
        "graphic designer", "marketing", "growth hacker", "sales", "account executive",
        "customer success", "hr ", "recruiter", "legal", "finance analyst",
        "product manager", "project manager", "scrum master", "business analyst",
    ];
    for kw in &skip_roles {
        if combined.contains(kw) {
            skip_reason = Some(format!("role type '{}' — not infra/backend/data", kw));
            return RoleFit {
                direction: "skip".into(),
                fit_score: 0,
                stack_match: false,
                remote_ok: false,
                compensation_ok: false,
                signals: vec![format!("skip: {}", kw)],
                skip_reason,
            };
        }
    }

    // Junior/intern skip
    if combined.contains("intern") || combined.contains("junior developer")
        || combined.contains("junior engineer") && !combined.contains("senior")
    {
        skip_reason = Some("junior/intern role — below target seniority".into());
        return RoleFit {
            direction: "skip".into(),
            fit_score: 0,
            stack_match: false,
            remote_ok: false,
            compensation_ok: false,
            signals: vec!["skip: junior/intern".into()],
            skip_reason,
        };
    }

    // ── Compensation filter ──────────────────────────────────────────────────────

    let compensation_ok = !combined.contains("₹")
        && !combined.contains("inr")
        && !combined.contains(" lpa")
        && !combined.contains("lakhs")
        && !combined.contains("lakh per")
        && !combined.contains("rupee");

    if !compensation_ok {
        signals.push("INR/₹ salary — likely no remote USD budget".into());
        score -= 30;
    } else {
        // Check for USD signals
        if combined.contains("$") || combined.contains("usd") || combined.contains("salary range") {
            signals.push("explicit USD compensation".into());
            score += 10;
        }
    }

    // ── Remote check ─────────────────────────────────────────────────────────────

    let remote_ok = combined.contains("remote")
        || combined.contains("work from anywhere")
        || combined.contains("distributed team")
        || combined.contains("fully remote")
        || combined.contains("async");

    let onsite_only = (combined.contains("on-site") || combined.contains("onsite")
        || combined.contains("in-office") || combined.contains("in office"))
        && !combined.contains("remote");

    if onsite_only {
        signals.push("on-site only — remote not possible".into());
        score -= 20;
    } else if remote_ok {
        signals.push("remote-friendly".into());
        score += 15;
    } else {
        signals.push("remote status unclear — assume possible".into());
        score += 5;
    }

    // ── Stack match ──────────────────────────────────────────────────────────────

    let stack_signals = [
        ("rust", 25),
        ("golang", 20), ("go lang", 20),
        ("distributed systems", 20),
        ("protocol", 18),
        ("infrastructure", 15), ("infra", 15),
        ("data engineering", 15), ("data pipeline", 15),
        ("backend", 12),
        ("python", 12),
        ("llm", 12), ("ml infra", 15), ("mlops", 12),
        ("systems programming", 18),
        ("networking", 15),
        ("database", 12), ("postgres", 10),
        ("typescript", 8),
        ("kubernetes", 10), ("k8s", 10),
        ("platform engineer", 15),
        ("devops", 8), ("sre", 10),
        ("open source", 10),
    ];

    let mut stack_score = 0i32;
    for (kw, pts) in &stack_signals {
        if combined.contains(kw) {
            signals.push(format!("stack match: {}", kw));
            stack_score += pts;
        }
    }
    stack_score = stack_score.min(30);
    score += stack_score;
    let stack_match = stack_score > 0;

    // ── Seniority boost ──────────────────────────────────────────────────────────

    let seniority_signals = [
        ("founding engineer", 20),
        ("staff engineer", 15),
        ("principal engineer", 15),
        ("senior engineer", 10),
        ("head of engineering", 15),
        ("engineering lead", 15),
        ("tech lead", 12),
        ("senior software", 10),
        ("senior backend", 10),
        ("early team", 12),
        ("first engineer", 15),
    ];
    for (kw, pts) in &seniority_signals {
        if combined.contains(kw) {
            signals.push(format!("seniority: {}", kw));
            score += pts;
            break; // one seniority signal enough
        }
    }

    // ── Team size context ────────────────────────────────────────────────────────

    let small_team = combined.contains("seed") || combined.contains("series a")
        || combined.contains("early stage") || combined.contains("small team")
        || combined.contains("startup");
    if small_team {
        signals.push("early-stage company".into());
        score += 10;
    }

    // ── Direction routing ────────────────────────────────────────────────────────

    // Direction A signals: company has a problem we can build for them
    let dir_a_signals = [
        "founding engineer", "first engineer", "early team",
        "build from scratch", "greenfield", "architect", "0 to 1",
        "staff", "principal", "head of",
    ];
    let is_dir_a = dir_a_signals.iter().any(|kw| combined.contains(kw));

    // Direction B: standard job application
    let dir_b_signals = ["apply", "we're hiring", "join our team", "job description"];
    let is_dir_b = dir_b_signals.iter().any(|kw| combined.contains(kw)) || !is_dir_a;

    let direction = if score < 20 || !compensation_ok && score < 40 {
        "skip".into()
    } else if is_dir_a && stack_match {
        "A".into() // proposal
    } else if is_dir_b {
        "B".into() // job application
    } else {
        "B".into()
    };

    let skip_reason = if direction == "skip" {
        Some(format!("low fit score ({}) — not worth pursuing", score))
    } else {
        None
    };

    RoleFit {
        direction,
        fit_score: score.max(0).min(100),
        stack_match,
        remote_ok,
        compensation_ok,
        signals,
        skip_reason,
    }
}
