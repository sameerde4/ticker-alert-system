from fastapi.testclient import TestClient

from app.main import app


def test_health_and_ui_without_a_database():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/ui")
    assert page.status_code == 200
    assert "Ticker Alert System" in page.text
    assert "Ticker or company name" in page.text
    assert "function rankSymbolUniverseMatches" in page.text
    assert "tickerAlertLastClosedAt" in page.text
    assert "tickerAlertHomeWatermark" not in page.text
    assert "sessionStorage" not in page.text
    assert "function homeWatermark" in page.text
    assert "homeOpenedAt" in page.text
    assert "scrollbar-gutter: stable" in page.text
    assert "overflow-x: clip" in page.text
    assert ".tab-panel { display: flex; flex-direction: column; gap: 16px; width: 100%; min-width: 0; }" in page.text
    universe = client.get("/ui/symbol_universe.json")
    assert universe.status_code == 200
    payload = universe.json()
    assert payload["counts"]["total"] >= 2000
    assert any(row["symbol"] == "AAPL" and "Apple" in row["name"] for row in payload["symbols"])
    assert "historyTab" in page.text
    assert "Alert History" in page.text
    assert "https://finance.yahoo.com/quote/" in page.text
    assert 'link.target = "_blank"' in page.text
    assert "function symbolLink" in page.text
    form = page.text.split('id="add-form"', 1)[1].split("</form>", 1)[0]
    assert form.index('id="run"') < form.index('id="status"')
    assert "Added " in page.text
    assert "is already on the watchlist." in page.text
    assert "Enter a ticker." in page.text
    assert "requestSubmit" not in page.text
    for column in ("symbol", "sector", "type", "when", "price", "sentiment"):
        assert f'data-sort="{column}"' in page.text


def test_watchlist_reports_database_down():
    client = TestClient(app)
    response = client.get("/v1/watchlist")
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
    assert rules.index('id="rulesBefore"') < rules.index('id="finbertExplain"') < rules.index('id="rulesAfter"')
    assert "news when the `;" in page.text
    assert "score is at least ${sentiment} points from 50, or news + price" in page.text
    assert "<h2>Watchlist</h2>" in page.text
    assert "<h2>Recent</h2>" in page.text
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


def test_unknown_ticker_is_rejected_before_the_database(monkeypatch):
    monkeypatch.setattr("app.main.yahoo_lists_symbol", lambda symbol: False)
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "ZZZZ"})
    assert response.status_code == 400
    assert "not a ticker" in response.json()["detail"]


def test_a_known_ticker_is_not_rejected_as_missing(monkeypatch):
    monkeypatch.setattr("app.main.yahoo_lists_symbol", lambda symbol: False)
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "AAPL"})
    assert response.status_code == 503


def test_a_yahoo_listed_ticker_is_not_rejected_as_missing(monkeypatch):
    monkeypatch.setattr("app.main.yahoo_lists_symbol", lambda symbol: True)
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "ZZZZ"})
    assert response.status_code == 503
