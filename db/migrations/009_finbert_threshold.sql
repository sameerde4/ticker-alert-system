-- FinBERT is the only headline scorer. 0.50 means the positive and negative
-- probabilities differ by at least half, which is the gate for a news alert.

UPDATE app_settings
SET sentiment_scorer = 'finbert',
    sentiment_threshold = 0.5000,
    updated_at = NOW()
WHERE id;
