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
