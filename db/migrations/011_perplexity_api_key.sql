-- Perplexity key for the two-sentence alert reasoning. Empty means the deterministic sentence is used.

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS perplexity_api_key TEXT NOT NULL DEFAULT '';
