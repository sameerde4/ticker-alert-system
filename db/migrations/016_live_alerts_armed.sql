-- User arm switch for Live alerts (Home cue). When false, app.live idles and
-- clears its heartbeat; the Alpaca producer can also pause when it polls status.

ALTER TABLE app_settings
  ADD COLUMN IF NOT EXISTS live_alerts_armed BOOLEAN NOT NULL DEFAULT TRUE;
