pub mod audit;
pub mod pii;
pub mod rate_limiter;

use std::sync::Arc;

pub use audit::AuditLogger;
pub use pii::PiiFilter;
pub use rate_limiter::RateLimiter;

/// Shared compliance layer — Arc-wrapped so NetworkingServer can Clone.
#[derive(Clone, Debug)]
pub struct ComplianceLayer {
    pub audit: Arc<AuditLogger>,
    pub pii: Arc<PiiFilter>,
    pub rate_limiter: Arc<RateLimiter>,
}

impl ComplianceLayer {
    /// Production: all features on, 30 calls/min per tool default.
    pub fn new() -> Self {
        Self {
            audit: Arc::new(AuditLogger::new(true)),
            pii: Arc::new(PiiFilter::new(true)),
            rate_limiter: Arc::new(RateLimiter::new(30)),
        }
    }

    /// Tighter limits for sensitive tools (email finder, external write ops).
    pub async fn apply_tool_limits(&self) {
        // Hunter.io has 25 free searches/month — cap hard
        self.rate_limiter.set_tool_limit("find_company_emails", 5).await;
        // External write — slow it down
        self.rate_limiter.set_tool_limit("save_prospect", 60).await;
        // WebReveal — be respectful
        self.rate_limiter.set_tool_limit("lookup_tech_stack", 20).await;
    }
}
