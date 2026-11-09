CREATE TABLE IF NOT EXISTS stores(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL,
 address TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS store_buyers(
 store_id TEXT REFERENCES stores(id), customer_id TEXT REFERENCES customers(id),
 PRIMARY KEY(store_id,customer_id)
);
CREATE TABLE IF NOT EXISTS demo_customers(customer_id TEXT PRIMARY KEY REFERENCES customers(id));
CREATE TABLE IF NOT EXISTS catalog_images(
 sku TEXT PRIMARY KEY REFERENCES products(sku), source_url TEXT NOT NULL,
 local_url TEXT, status TEXT NOT NULL, checked_at INTEGER
);
CREATE INDEX IF NOT EXISTS conversations_session_id ON conversations(session_id,id);
CREATE INDEX IF NOT EXISTS sessions_customer ON sessions(customer_id);
INSERT OR IGNORE INTO schema_version VALUES(3);
