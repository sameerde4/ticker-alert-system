-- Show FinBERT on a 0–100 scale. 50 is neutral.
-- The threshold is how far a score must sit from 50. 0.50 on the old scale is 25 points.

UPDATE headlines
SET sentiment_score = 50 + 50 * sentiment_score
WHERE sentiment_score BETWEEN -1 AND 1;

UPDATE alerts
SET sentiment_score = 50 + 50 * sentiment_score
WHERE sentiment_score IS NOT NULL
  AND sentiment_score BETWEEN -1 AND 1;

UPDATE alerts
SET articles = (
  SELECT COALESCE(jsonb_agg(
    CASE
      WHEN jsonb_typeof(elem->'sentiment_score') = 'number'
        AND (elem->>'sentiment_score')::numeric BETWEEN -1 AND 1
      THEN jsonb_set(
        elem,
        '{sentiment_score}',
        to_jsonb(50 + 50 * (elem->>'sentiment_score')::numeric)
      )
      ELSE elem
    END
  ), '[]'::jsonb)
  FROM jsonb_array_elements(COALESCE(articles, '[]'::jsonb)) elem
)
WHERE articles IS NOT NULL;

UPDATE alerts
SET sentiment_threshold = sentiment_threshold * 50
WHERE sentiment_threshold IS NOT NULL
  AND sentiment_threshold <= 1;

UPDATE app_settings
SET sentiment_threshold = sentiment_threshold * 50,
    updated_at = NOW()
WHERE sentiment_threshold <= 1;
