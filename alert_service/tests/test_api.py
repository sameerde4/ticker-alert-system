from fastapi.testclient import TestClient

from app.main import app


def test_health_and_ui_without_a_database():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/ui")
    assert page.status_code == 200
    assert "no-store" in page.headers.get("cache-control", "")
    assert "S&amp;P 500 Radar" in page.text
    assert "<span>S&amp;P 500</span> Radar" in page.text
    assert 'id="liveStatus"' in page.text
    assert "Live alerts off" in page.text
    assert "Live alerts starting…" in page.text
    assert "/v1/live/armed" in page.text
    assert "/v1/live/ws-symbols" in page.text
    assert "Live WebSocket" in page.text
    assert 'id="ws-add-form"' in page.text
    assert "toggleLiveArmed" in page.text
    assert 'aria-pressed="false"' in page.text
    assert "live-pulse" in page.text
    assert 'id="lakeHeaderStatus"' in page.text
    assert 'id="lakeHeaderProgress"' in page.text
    assert 'id="lakeSettingsProgress"' in page.text
    assert "lake-run-status" in page.text
    assert "Loading historical prices" in page.text
    assert "function lakeHeaderCopy" in page.text
    assert "!status.running && (status.ok === true || status.has_raw_prices === true)" in page.text
    assert ".lake-status[hidden] { display: none !important; }" in page.text
    assert "alert.updated_at || alert.created_at" in page.text

    assert "daily schedule" in page.text
    assert "manual overrides" in page.text
    assert "function applyLakeProgressBar" in page.text
    assert "progress_pct" in page.text
    assert "/v1/live/status" in page.text
    assert "S&amp;P 500 ticker or company name" in page.text
    assert "Choose S&amp;P 500 constituents" in page.text
    assert "only for now" not in page.text
    assert "Historical prices (lake)" in page.text
    assert "Land S&amp;P 500 prices" in page.text
    assert "/v1/admin/lake/land" in page.text
    assert "/v1/admin/lake/refresh" in page.text
    assert "Refresh lake + retrain" in page.text
    assert "formatWhen(status.finished_at)" in page.text
    assert "last completed" in page.text
    assert 'id="refreshLake"' in page.text
    assert "function rankSymbolUniverseMatches" in page.text
    assert "tickerAlertLastClosedAt" in page.text
    assert "tickerAlertHomeClearedAt" in page.text
    assert "tickerAlertHomeWatermark" not in page.text
    assert "sessionStorage" not in page.text
    assert "function homeClearedAt" in page.text
    assert "function clearRecentAlerts" in page.text
    assert "homeOpenedAt" not in page.text
    assert "function homeWatermark" not in page.text
    assert "scrollbar-gutter: stable" in page.text
    assert "overflow-x: clip" in page.text
    assert ".tab-panel { display: flex; flex-direction: column; gap: 16px; width: 100%; min-width: 0; }" in page.text
    assert "enableNotify" in page.text
    assert "showOsNotifications" in page.text
    assert "sw-notifications.js" in page.text
    assert "function alertMetrics" in page.text
    assert "alert-metric-value" in page.text
    assert "Price change" in page.text
    assert "appendStoryAndShapePills(tags, alert)" in page.text
    assert "alert-head-primary" in page.text
    assert "alert-head-tags" in page.text
    assert "detail-title-primary" in page.text
    assert "detail-title-tags" in page.text
    assert "PRICE_SHAPE_LABELS" in page.text
    assert "if (company) primary.append(company)" in page.text
    assert "function alertHeadMetrics" in page.text
    assert "for (const bit of alertHeadMetrics(alert)) head.append(bit)" in page.text
    assert "function badgeClass" not in page.text
    worker = client.get("/ui/sw-notifications.js")
    assert worker.status_code == 200
    assert "notificationclick" in worker.text
    assert "javascript" in worker.headers.get("content-type", "")
    universe = client.get("/ui/symbol_universe.json")
    assert universe.status_code == 200
    payload = universe.json()
    assert payload.get("universe") == "sp500"
    assert payload["counts"]["total"] == 503
    assert any(row["symbol"] == "AAPL" and "Apple" in row["name"] for row in payload["symbols"])
    assert not any(row["symbol"] == "BTC-USD" for row in payload["symbols"])
    lake = client.get("/v1/admin/lake/status")
    assert lake.status_code == 200
    assert "running" in lake.json()
    assert "historyTab" in page.text
    assert "watchlistTab" in page.text
    assert "screenerTab" in page.text
    assert 'id="screenerTabBtn"' in page.text
    assert 'id="enableScreener"' in page.text
    assert "Enable Screener" in page.text
    assert "<h2>Screener</h2>" in page.text
    assert "tickerAlertScreenerEnabled" in page.text
    assert "function applyScreenerVisibility" in page.text
    assert ".tab-btn[hidden] { display: none; }" in page.text
    assert "Alert History" in page.text
    assert "Watchlist results" in page.text
    assert "Scan today" in page.text
    assert "renderWatchlistCheckAlerts" in page.text
    assert "renderScreenerAlerts" in page.text
    assert "/v1/screener/run" in page.text
    assert 'id="screenerChange"' in page.text
    # Screener tab button is hidden by default (Settings opt-in for demos).
    btn_chunk = page.text.split('id="screenerTabBtn"', 1)[1].split("</button>", 1)[0]
    assert "hidden" in btn_chunk
    assert "function selectTab" in page.text
    assert "DEFAULT_HISTORY_COLS" in page.text
    assert 'id="historyHead"' in page.text
    assert "function buildHistoryHeaders" in page.text
    assert "function originLabel" in page.text
    assert "tickerAlertHistoryColumns" in page.text
    assert "https://finance.yahoo.com/quote/" in page.text
    assert 'link.target = "_blank"' in page.text
    assert "function symbolLink" in page.text
    form = page.text.split('id="add-form"', 1)[1].split("</form>", 1)[0]
    assert form.index('id="run"') < form.index('id="status"')
    assert "Added " in page.text
    assert "is already on the watchlist." in page.text
    assert "Enter a ticker." in page.text
    assert "requestSubmit" not in page.text
    for column in ("symbol", "company", "origin", "type", "when"):
        assert f'"{column}"' in page.text
    assert "DEFAULT_HISTORY_COLS" in page.text
    assert 'label: "Alert type"' in page.text
    assert 'label: "Price shape"' in page.text
    assert 'label: "Direction"' in page.text
    assert 'news_price: "price + news"' in page.text
    assert 'label: "Price change"' in page.text
    assert 'label: "Sentiment score"' in page.text
    assert "function alertDisplayPriceChange" in page.text
    assert "Anomaly \"why\" lives in What happened" in page.text or "alertDisplayPriceChange(alert)" in page.text
    assert 'return "flat"' in page.text
    assert ".badge.origin-live" in page.text
    assert "#5eead4" in page.text
    assert "#ffb070" in page.text
    assert "function countArticleSentiments" in page.text
    assert "function sentimentBreakdownDetail" in page.text
    assert "function priceBreakdownDetail" in page.text
    assert "function priceSpanCaption" in page.text
    assert "alert-metric-detail" in page.text
    assert "alert-metric-span" in page.text
    assert 'label: "Company"' in page.text
    assert 'label: "Sector"' not in page.text
    assert 'label: "Alert type"' in page.text
    assert 'label: "Alert details"' not in page.text
    assert 'label: "Origin"' in page.text
    assert "history-row" in page.text
    assert "Click a row for the full write-up" in page.text
    assert "Click a column heading to sort" in page.text
    assert "Combined news sentiment " not in page.text
    assert 'label.textContent = "Sentiment"' in page.text
    assert "type-stat-label" in page.text
    assert "FinBERT sentiment score (0–100)" in page.text
    assert "function historyTypePriceStat" in page.text
    assert "function historyTypeSentimentStat" in page.text
    assert "function alertDisplayPriceChange" in page.text
    assert "type-stat" in page.text
    assert "detailParts.push(...alertHeadMetrics(alert))" not in page.text
    assert "modal-header h3 .company-name" in page.text
    assert "font-size: 18px" in page.text
    assert "tickerAlertWatchlistResults" in page.text
    assert "tickerAlertScreenerResults" in page.text
    assert "function restoreToolResults" in page.text
    assert 'id="watchlistRunStamp"' in page.text
    assert 'id="screenerRunStamp"' in page.text
    assert "historyTypePriceStat(alert), historyTypeSentimentStat(alert)" in page.text
    assert 'if (key === "price")' in page.text
    assert 'if (key === "sentiment")' in page.text
    assert "kind-news" in page.text and "kind-price" in page.text and "kind-fusion" in page.text
    assert "companyNameEl(alert.symbol)" in page.text
    assert "function companyNameForSymbol" in page.text
    assert "Good news" not in page.text
    assert "Bad price" not in page.text


def test_watchlist_reports_database_down():
    client = TestClient(app)
    response = client.get("/v1/watchlist")
    assert response.status_code == 503


def test_live_status_reports_database_down():
    client = TestClient(app)
    response = client.get("/v1/live/status")
    assert response.status_code == 503


def test_rebuild_rejects_a_bad_day_count_before_the_database():
    client = TestClient(app)
    response = client.post("/v1/admin/rebuild", json={"days": 0})
    assert response.status_code == 400
    page = client.get("/ui")
    assert "Alert history" in page.text
    assert "Rebuild Watchlist history" in page.text
    assert "Clear Watchlist history" in page.text
    assert "Clear Live history" in page.text
    assert "Wipe and rebuild" not in page.text
    assert "evidence-bullets" in page.text
    assert "(not volatile)" in page.text or "not volatile" in page.text or 'return "flat"' in page.text
    assert 'id="clear-below-form"' in page.text
    assert 'id="clearAllAlerts"' in page.text
    assert 'id="clearWatchlistAlerts"' in page.text
    assert 'id="clearLiveAlerts"' in page.text
    assert "/v1/admin/alerts/clear" in page.text
    clear_reject = client.post("/v1/admin/alerts/clear", json={})
    assert clear_reject.status_code in (400, 503)
    assert "finbertExplain" in page.text
    rules = page.text.split('id="rules"', 1)[1].split("</p>", 1)[0]
    assert rules.index('id="rulesBefore"') < rules.index('id="finbertExplain"') < rules.index('id="priceExplain"') < rules.index('id="rulesAfter"')
    assert "homeLede" in page.text
    assert "S&amp;P 500 Radar monitors the index for price movements and anomalies" in page.text
    assert "grade how well the news explains the session" in page.text
    assert ".modal-header h3" in page.text
    modal_h3 = page.text.split(".modal-header h3 {", 1)[1].split("}", 1)[0]
    assert "font-family: ui-sans-serif, system-ui, sans-serif" in modal_h3
    assert "matches the " in page.text or 'id="priceExplain">price move' in page.text
    assert "Price move threshold" in page.text
    assert "Isolation Forest" in page.text
    assert "Price: ${move}% move threshold" in page.text
    assert "Both when a headline matches the " in page.text
    assert "Price gates and when news matches" in page.text
    assert "Two price gates" in page.text
    assert "Price alert percentage" not in page.text
    assert "Isolation Forest from the lake registry" in page.text
    assert "open→last" in page.text
    assert 'id="perplexity-form"' in page.text
    assert "/v1/settings/perplexity" in page.text
    assert 'id="perplexityModel"' in page.text
    assert "Dots mean a key is saved" in page.text or "Dots in the field mean a key is saved" in page.text
    assert "Isolation Forest wording" in page.text or "richer Isolation Forest" in page.text
    assert "••••••••••••" in page.text
    assert "key !== SAVED_KEY_DOTS" in page.text
    assert "function showSavedKey" in page.text
    assert "function togetherModel" in page.text
    assert "sections.model_label" in page.text
    assert "function appendLinkedSummary" in page.text
    assert "function normalizeCitationUrl" in page.text
    assert "function priceBreakdownDetail" in page.text
    assert "alert-metric-levels" in page.text
    assert "alert-metric-lead" in page.text
    assert 'layout !== "below"' in page.text or 'layout !== \'below\'' in page.text
    assert "width: 22ch" in page.text
    assert "width: 36ch" in page.text
    assert "wrote Together." not in page.text
    assert "The percent still applies" not in page.text
    assert "<h2>Watchlist</h2>" in page.text
    assert "<h2>Live alerts</h2>" in page.text
    assert "About Live alerts:" in page.text
    assert "live Kafka stream" in page.text
    assert 'id="clearRecent"' in page.text
    assert "Clear alerts" in page.text
    assert "tip-btn" in page.text
    assert "openHomeAlertKeys" in page.text
    assert "openWatchAlertKeys" in page.text
    assert "homeAlertFingerprint" in page.text
    assert 'id="watchlistAlerts"' in page.text
    assert 'id="homeStatus"' in page.text
    assert 'id="recentTip"' in page.text
    assert 'id="notifyHint"' not in page.text
    assert "function setRecentTip" in page.text
    assert "function setHomeScope" in page.text
    assert "tickerAlertHomeScope" in page.text
    assert 'data-scope="all"' in page.text
    assert 'data-scope="watchlist"' in page.text
    assert 'data-scope="others"' in page.text
    assert "scope-toggle" in page.text
    scope_css = page.text.split(".scope-toggle {", 1)[1].split("}", 1)[0]
    assert "border-radius: 8px" in scope_css
    assert "font-family: ui-sans-serif, system-ui, sans-serif" in page.text.split(".scope-toggle .scope-opt {", 1)[1].split("}", 1)[0]
    assert 'id="homeScope"' not in page.text
    home_panel = page.text.split('id="homeTab"', 1)[1].split('id="watchlistTab"', 1)[0]
    watch_panel = page.text.split('id="watchlistTab"', 1)[1].split('id="screenerTab"', 1)[0]
    screener_panel = page.text.split('id="screenerTab"', 1)[1].split('id="historyTab"', 1)[0]
    assert 'id="add-form"' not in home_panel
    assert 'id="alerts"' in home_panel
    assert "scope-toggle" in home_panel
    assert "When new live alerts arrive" not in home_panel.split('id="recentTip"', 1)[0]
    assert 'id="add-form"' in watch_panel
    assert 'id="run"' in watch_panel
    assert 'id="watchlistAlerts"' in watch_panel
    assert 'id="screener-form"' in screener_panel
    assert 'id="screenerAlerts"' in screener_panel
    assert "Screener results" in screener_panel
    assert "Sentiment score " in page.text
    assert "(Positive " in page.text
    actions = page.text.split('class="settings-actions"', 1)[1].split("</div>", 1)[0]
    assert 'id="resetSettings"' in actions and 'id="settingsStatus"' in actions
    assert actions.index('id="resetSettings"') < actions.index('id="settingsStatus"')
    assert "positive probability minus the negative" in page.text
    assert "not a hosted analysis API" in page.text
    assert "Why the default threshold is 25" in page.text
    assert 'name="sentimentScorer"' not in page.text


def test_screener_rejects_zero_percent_without_a_database():
    client = TestClient(app)
    response = client.post("/v1/screener/run", json={"change_percent": 0})
    assert response.status_code == 400
    assert "non-zero" in response.json()["detail"].lower()


def test_removed_scorer_switch_is_not_an_endpoint():
    client = TestClient(app)
    response = client.put("/v1/settings/scorer", json={"sentiment_scorer": "custom"})
    assert response.status_code == 404


def test_bad_symbol_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "not a ticker"})
    assert response.status_code == 400


def test_unknown_ticker_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "ZZZZ"})
    assert response.status_code == 400
    assert "S&P 500 constituent" in response.json()["detail"]


def test_a_known_sp500_ticker_is_not_rejected_as_missing():
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "AAPL"})
    assert response.status_code == 503


def test_non_sp500_ticker_is_rejected_even_if_it_looks_valid():
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "BTC-USD"})
    assert response.status_code == 400
    assert "S&P 500 constituent" in response.json()["detail"]
