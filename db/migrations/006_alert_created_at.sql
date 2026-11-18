-- When the alert first showed up. Re-checks update the row but do not move this clock,
-- so Home can list what arrived since the app was last open.

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

UPDATE alerts
SET created_at = COALESCE(updated_at, triggered_at, NOW())
WHERE created_at IS NULL;

ALTER TABLE alerts ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE alerts ALTER COLUMN created_at SET NOT NULL;
