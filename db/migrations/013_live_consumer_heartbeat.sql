-- Heartbeat from python -m app.live so the UI can show "Live alerts on".

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS live_consumer_heartbeat_at TIMESTAMPTZ;
