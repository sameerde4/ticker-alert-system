from fastapi.testclient import TestClient

from app.main import app


def test_health_and_ui_without_a_database():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/ui")
    assert page.status_code == 200
    assert "S&amp;P 500 Alert System" in page.text
    assert "<span>S&amp;P 500</span> Alert System" in page.text
    assert 'id="liveStatus"' in page.text
    assert "Live alerts off" in page.text
    assert "live-pulse" in page.text
    assert "/v1/live/status" in page.text
    assert "S&amp;P 500 ticker or company name" in page.text
    assert "Choose S&amp;P 500 constituents" in page.text
    assert "only for now" not in page.text
    assert "Historical prices (lake)" in page.text
    assert "Land S&amp;P 500 prices" in page.text
    assert "/v1/admin/lake/land" in page.text
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
    assert "head.append(kindPill(alert.kind), symbol, when)" in page.text
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
    assert "Alert History" in page.text
    assert "Today's results" in page.text
    assert "Scan today" in page.text
    assert "renderWatchlistCheckAlerts" in page.text
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
    for column in ("symbol", "sector", "origin", "type", "when"):
        assert f'"{column}"' in page.text
    assert 'DEFAULT_HISTORY_COLS = ["symbol", "sector", "origin", "when", "type"]' in page.text
    assert 'label: "Alert details"' in page.text
    assert 'label: "Origin"' in page.text
    assert ">Type</button>" not in page.text
    assert "Combined news sentiment " not in page.text
    assert 'metric.textContent = formatScore(alert.sentiment_score) + "/100"' in page.text
    assert "kind-news" in page.text and "kind-price" in page.text and "kind-fusion" in page.text
    assert "title.replaceChildren(kindPill(alert.kind), symbolLink(alert.symbol), when)" in page.text
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
    assert "Rebuild history" in page.text
    assert "Wipe and rebuild" in page.text
    assert "finbertExplain" in page.text
    rules = page.text.split('id="rules"', 1)[1].split("</p>", 1)[0]
    assert rules.index('id="rulesBefore"') < rules.index('id="finbertExplain"') < rules.index('id="priceExplain"') < rules.index('id="rulesAfter"')
    assert "matches the price move" in page.text
    assert "price at ${move}% from the open during market hours, or from the prior close after the close, news when the " in page.text
    assert "or both when a headline " in page.text
    assert "When a headline matches the price move" in page.text
    assert "The price rule" in page.text
    assert "While the market is open, a stock is compared with its opening price" in page.text
    assert "does not wait for the close" in page.text
    assert 'id="perplexity-form"' in page.text
    assert "/v1/settings/perplexity" in page.text
    assert 'id="perplexityModel"' in page.text
    assert "The selected model writes three to four short sentences." in page.text
    assert "Dots in the field mean a key is saved." in page.text
    assert "••••••••••••" in page.text
    assert "key !== SAVED_KEY_DOTS" in page.text
    assert "function showSavedKey" in page.text
    assert "function togetherModel" in page.text
    assert "sections.model_label" in page.text
    assert "width: 22ch" in page.text
    assert "width: 36ch" in page.text
    assert "wrote Together." not in page.text
    assert "The percent still applies" not in page.text
    assert "<h2>Watchlist</h2>" in page.text
    assert "<h2>Recent alerts</h2>" in page.text
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
    assert 'data-scope="sp500"' in page.text
    assert 'data-scope="watchlist"' in page.text
    assert "scope-toggle" in page.text
    assert 'id="homeScope"' not in page.text
    home_panel = page.text.split('id="homeTab"', 1)[1].split('id="watchlistTab"', 1)[0]
    watch_panel = page.text.split('id="watchlistTab"', 1)[1].split('id="historyTab"', 1)[0]
    assert 'id="add-form"' not in home_panel
    assert 'id="alerts"' in home_panel
    assert "scope-toggle" in home_panel
    assert "When new live alerts arrive" not in home_panel.split('id="recentTip"', 1)[0]
    assert 'id="add-form"' in watch_panel
    assert 'id="run"' in watch_panel
    assert 'id="watchlistAlerts"' in watch_panel
    assert "Sentiment score " in page.text
    assert "(Positive " in page.text
    actions = page.text.split('class="settings-actions"', 1)[1].split("</div>", 1)[0]
    assert 'id="resetSettings"' in actions and 'id="settingsStatus"' in actions
    assert actions.index('id="resetSettings"') < actions.index('id="settingsStatus"')
    assert "positive probability minus the negative" in page.text
    assert "not a hosted analysis API" in page.text
    assert "Why the default threshold is 25" in page.text
    assert 'name="sentimentScorer"' not in page.text


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
