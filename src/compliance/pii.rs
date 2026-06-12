use regex::Regex;
use std::sync::OnceLock;

static PATTERNS: OnceLock<Vec<(&'static str, Regex)>> = OnceLock::new();

fn patterns() -> &'static Vec<(&'static str, Regex)> {
    PATTERNS.get_or_init(|| {
        vec![
            // Email addresses
            ("email", Regex::new(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}").unwrap()),
            // API keys — common prefixes (Anthropic, GitHub, OpenAI, AWS)
            ("api_key", Regex::new(r"(sk-ant-|ghp_|gho_|github_pat_|sk-|AKIA|Bearer\s+)[A-Za-z0-9_\-]{8,}").unwrap()),
            // Credit card numbers (basic Luhn-pattern)
            ("cc", Regex::new(r"\b(?:\d[ \-]?){13,16}\b").unwrap()),
            // US phone numbers
            ("phone", Regex::new(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b").unwrap()),
            // IPv4 addresses
            ("ip", Regex::new(r"\b(?:\d{1,3}\.){3}\d{1,3}\b").unwrap()),
            // SSN (US)
            ("ssn", Regex::new(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b").unwrap()),
        ]
    })
}

#[derive(Clone, Debug)]
pub struct PiiFilter {
    /// If true, replace matched values with [REDACTED:<type>]. If false, pass through.
    pub enabled: bool,
}

impl PiiFilter {
    pub fn new(enabled: bool) -> Self {
        Self { enabled }
    }

    /// Redact all detected PII from input string.
    pub fn redact(&self, input: &str) -> String {
        if !self.enabled {
            return input.to_string();
        }
        let mut result = input.to_string();
        for (label, pattern) in patterns() {
            result = pattern
                .replace_all(&result, format!("[REDACTED:{}]", label).as_str())
                .to_string();
        }
        result
    }

    /// Returns list of detected PII types (for audit metadata, no values exposed).
    pub fn detect_types(&self, input: &str) -> Vec<&'static str> {
        if !self.enabled {
            return vec![];
        }
        patterns()
            .iter()
            .filter(|(_, re)| re.is_match(input))
            .map(|(label, _)| *label)
            .collect()
    }
}
