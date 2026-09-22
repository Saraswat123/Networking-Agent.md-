-- Prospect pipeline
CREATE TABLE IF NOT EXISTS prospects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    github          TEXT UNIQUE,
    email           TEXT,
    company         TEXT,
    role            TEXT,
    location        TEXT,
    notes           TEXT,
    source          TEXT,           -- github | yc | x | linkedin | manual
    outreach_status TEXT DEFAULT 'new',
                                    -- new | researched | github_engaged |
                                    -- x_engaged | emailed | replied | meeting_scheduled
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Track every outreach touch
CREATE TABLE IF NOT EXISTS outreach_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id     INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,  -- github | email | x | discord | linkedin
    message         TEXT,
    sent_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Auto-update updated_at on prospect change
CREATE TRIGGER IF NOT EXISTS prospects_updated_at
    AFTER UPDATE ON prospects
BEGIN
    UPDATE prospects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_prospects_status   ON prospects(outreach_status);
CREATE INDEX IF NOT EXISTS idx_prospects_location ON prospects(location);
CREATE INDEX IF NOT EXISTS idx_prospects_company  ON prospects(company);
CREATE INDEX IF NOT EXISTS idx_outreach_prospect  ON outreach_log(prospect_id);

-- OSS contributions (Dir B gate: PR must be acked before email)
CREATE TABLE IF NOT EXISTS contributions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id         INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
    repo_owner          TEXT NOT NULL,
    repo_name           TEXT NOT NULL,
    issue_number        INTEGER,
    issue_title         TEXT,
    contribution_type   TEXT NOT NULL DEFAULT 'pr',
    pr_url              TEXT,
    status              TEXT NOT NULL DEFAULT 'drafted',
    -- drafted | submitted | acknowledged | merged | rejected
    notes               TEXT,
    submitted_at        DATETIME,
    acknowledged_at     DATETIME,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Dir A proposals — generated from analyze_company_depth cache
CREATE TABLE IF NOT EXISTS proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
    pain_points TEXT,
    proposal    TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- analyze_company_depth cache — 7-day TTL, keyed by GitHub org slug
CREATE TABLE IF NOT EXISTS analysis_cache (
    org_key    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,  -- JSON blob
    expires_at DATETIME NOT NULL
);

-- Tool call log for debugging and audit
CREATE TABLE IF NOT EXISTS tool_call_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    args      TEXT,
    called_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contributions_prospect ON contributions(prospect_id);
CREATE INDEX IF NOT EXISTS idx_contributions_status   ON contributions(status);
CREATE INDEX IF NOT EXISTS idx_proposals_prospect     ON proposals(prospect_id);
CREATE INDEX IF NOT EXISTS idx_cache_expires          ON analysis_cache(expires_at);
