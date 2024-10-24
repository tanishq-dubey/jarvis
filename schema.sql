CREATE TABLE IF NOT EXISTS Keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    api_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Queries (
    id TEXT PRIMARY KEY,
    ip TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    query TEXT NOT NULL,
    api_key_id INTEGER,
    status TEXT NOT NULL,
    conversation_history TEXT,
    FOREIGN KEY (api_key_id) REFERENCES Keys (id)
);