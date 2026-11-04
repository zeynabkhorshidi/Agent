CREATE TABLE IF NOT EXISTS voice_requests(
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    created INTEGER NOT NULL,
    PRIMARY KEY(session_id, turn_id)
);
INSERT OR IGNORE INTO schema_version VALUES(2);
