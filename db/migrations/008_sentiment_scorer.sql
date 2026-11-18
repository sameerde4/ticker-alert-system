-- Which headline scorer a check uses. FinBERT is the default. Custom is the keyword lexicon.

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS sentiment_scorer TEXT NOT NULL DEFAULT 'finbert';

ALTER TABLE app_settings
  DROP CONSTRAINT IF EXISTS app_settings_sentiment_scorer_check;

ALTER TABLE app_settings
  ADD CONSTRAINT app_settings_sentiment_scorer_check
  CHECK (sentiment_scorer IN ('finbert', 'custom'));
