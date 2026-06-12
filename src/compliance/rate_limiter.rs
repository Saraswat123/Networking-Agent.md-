use std::collections::HashMap;
use std::collections::VecDeque;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

struct ToolWindow {
    calls: VecDeque<Instant>,
    limit: usize,
    window: Duration,
}

impl ToolWindow {
    fn new(limit: usize, window: Duration) -> Self {
        Self {
            calls: VecDeque::new(),
            limit,
            window,
        }
    }

    /// Returns true if call is allowed, false if rate limit exceeded.
    fn allow(&mut self) -> bool {
        let now = Instant::now();
        // Evict expired calls
        while self
            .calls
            .front()
            .map(|t| now.duration_since(*t) > self.window)
            .unwrap_or(false)
        {
            self.calls.pop_front();
        }
        if self.calls.len() >= self.limit {
            return false;
        }
        self.calls.push_back(now);
        true
    }

    fn remaining(&mut self) -> usize {
        let now = Instant::now();
        while self
            .calls
            .front()
            .map(|t| now.duration_since(*t) > self.window)
            .unwrap_or(false)
        {
            self.calls.pop_front();
        }
        self.limit.saturating_sub(self.calls.len())
    }
}

pub struct RateLimiter {
    windows: Mutex<HashMap<String, ToolWindow>>,
    default_limit: usize,
    default_window: Duration,
}

impl std::fmt::Debug for RateLimiter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RateLimiter")
            .field("default_limit", &self.default_limit)
            .finish()
    }
}

impl RateLimiter {
    pub fn new(calls_per_minute: usize) -> Self {
        Self {
            windows: Mutex::new(HashMap::new()),
            default_limit: calls_per_minute,
            default_window: Duration::from_secs(60),
        }
    }

    /// Override limit for a specific tool. Call before server starts.
    pub async fn set_tool_limit(&self, tool: &str, calls_per_minute: usize) {
        let mut map = self.windows.lock().await;
        map.insert(
            tool.to_string(),
            ToolWindow::new(calls_per_minute, Duration::from_secs(60)),
        );
    }

    /// Returns Ok(remaining) if allowed, Err(msg) if rate limited.
    pub async fn check(&self, tool: &str) -> Result<usize, String> {
        let mut map = self.windows.lock().await;
        let window = map
            .entry(tool.to_string())
            .or_insert_with(|| ToolWindow::new(self.default_limit, self.default_window));

        if window.allow() {
            Ok(window.remaining())
        } else {
            Err(format!(
                "Rate limit exceeded for '{}': max {} calls/min",
                tool, self.default_limit
            ))
        }
    }
}
