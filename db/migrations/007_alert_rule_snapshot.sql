-- Thresholds in force when the alert was saved. Later setting changes do not rewrite them.

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS price_move_threshold NUMERIC(8, 6);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS sentiment_threshold NUMERIC(8, 4);

UPDATE alerts
SET price_move_threshold = (
  substring(
    coalesce(sections->>'price', '') || ' ' || coalesce(summary, '')
    from 'beyond the ([0-9.]+)% rule'
  )
)::numeric / 100
WHERE price_move_threshold IS NULL
  AND substring(
    coalesce(sections->>'price', '') || ' ' || coalesce(summary, '')
    from 'beyond the ([0-9.]+)% rule'
  ) IS NOT NULL;

UPDATE alerts
SET sentiment_threshold = (
  substring(
    coalesce(sections->>'news', '') || ' ' || coalesce(summary, '')
    from 'cleared the ([0-9.]+) absolute-sentiment'
  )
)::numeric
WHERE sentiment_threshold IS NULL
  AND substring(
    coalesce(sections->>'news', '') || ' ' || coalesce(summary, '')
    from 'cleared the ([0-9.]+) absolute-sentiment'
  ) IS NOT NULL;
