-- Model used when a saved Perplexity key writes the alert reasoning.

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS perplexity_model TEXT NOT NULL DEFAULT 'openai/gpt-5.4-mini';
