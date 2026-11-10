-- Postgres schema for review embeddings. Safe to re-run: nothing here deletes data.
-- The HNSW index is created separately in pipeline/store.py, after the rows are loaded,
-- because building it once at the end is much faster than updating it on every insert.

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS review_embeddings (
  review_id TEXT PRIMARY KEY,
  app_id TEXT NOT NULL,
  embedding extensions.vector(384) NOT NULL,
  rating SMALLINT NOT NULL,
  review_date TIMESTAMP NOT NULL,
  app_version TEXT,
  theme_id TEXT,
  snippet TEXT NOT NULL
);

-- Supabase publishes tables in the public schema through its REST API. With row-level
-- security on and no policies, that API returns nothing, while our own database login
-- (the table owner) still has full access.
ALTER TABLE review_embeddings ENABLE ROW LEVEL SECURITY;

-- These let vector search be filtered by app, version, or date.
CREATE INDEX IF NOT EXISTS review_embeddings_app_id_idx ON review_embeddings (app_id);
CREATE INDEX IF NOT EXISTS review_embeddings_app_version_idx ON review_embeddings (app_version);
CREATE INDEX IF NOT EXISTS review_embeddings_review_date_idx ON review_embeddings (review_date);
