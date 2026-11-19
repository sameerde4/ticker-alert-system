"""Docs agree on the S&P 500 plan: local lake, near-term news, forest on price/volume."""

from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
ROOT = DOCS.parent


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_audit_keeps_batch_streaming_a_model_and_perplexity():
    audit = _text(DOCS / "proposal-pipeline-audit.md")
    for phrase in (
        "Kafka",
        "Flink",
        "TimescaleDB",
        "Spark",
        "Isolation Forest",
        "Model registry",
        "FinBERT",
        "Perplexity",
        "three to four short sentences",
        "deterministic sentence",
        "news-only and price-only",
        "volume z-score",
        "S&P 500",
        "| Cassandra | Drop |",
        "| Historical news archive | Drop |",
        "| FinBERT aggregates in training rows | Drop |",
        "| News archive | Drop |",
    ):
        assert phrase in audit
    assert "Fit Isolation Forest" in audit
    assert "Fine-tuning needs labels this project does not have" in audit
    assert "The model never decides whether the alert exists" in audit
    assert "Near-term news only" in audit
    assert "price/volume" in audit or "price and volume" in audit.lower()
    assert "Historical headlines are not part of the design" in audit
    assert "| Cassandra | Drop |" in audit
    assert "VWAP is not a feature the forest uses" in audit
    assert "stored headlines" not in audit
    assert "Desktop (OS) notification and tab badge" in audit
    assert "Desktop notification and tab badge" in audit
    assert "desktop notifications and a tab badge" in audit
    assert "Slack or email" not in audit
    assert "Slack and email are not used" in audit
    assert "batch_train" in audit
    assert "Local stand-in" in audit
    assert "AWS production deploy is out of scope" in audit or "AWS production is not part of the final target" in audit
    assert "as-built and local final target diagrams" in audit
    assert "price first, then news" in audit.lower() or "Price first, then news" in audit
    assert "live price → near-term news" in audit.lower() or "price → near-term news" in audit.lower()
    assert "live_feature_rows" in audit
    assert "Three to four sentences for news" in audit or "three to four short sentences" in audit
    assert "Live plus Watchlist" in audit
    assert "Watchlist **as-built**" in audit or "Watchlist **as-built**:" in audit
    assert "training only" in audit.lower()
    assert "Home Recent" in audit
    assert "Today's results" in audit
    assert "Scan today" in audit
    assert "alerts.origin" in audit


def test_architecture_points_at_the_audit_and_names_the_target():
    architecture = _text(DOCS / "architecture.md")
    assert "# S&P 500 Alert System architecture" in architecture
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in architecture
    assert "Perplexity richer news / news+price reasoning" in architecture
    assert "focus set" in architecture
    assert "As-built: Live and Watchlist side by side" in architecture
    assert "As-built Watchlist Scan today" in architecture
    assert "Today's results" in architecture
    assert "Recent alerts" in architecture
    assert "S&P 500 / Watchlist" in architecture or "scope: full S&P 500 or Watchlist" in architecture
    assert "Home Recent" in architecture
    assert "alerts.origin" in architecture
    assert "training lake" in architecture.lower() or "training only" in architecture.lower()
    assert "Spark-role curated feature table" in architecture
    assert "Live scorer Flink role" in architecture or "Flink role" in architecture
    assert "Cassandra" in architecture and "Dropped" in architecture
    assert "As-built: system overview" in architecture
    assert "Local final target: high-level lambda architecture" in architecture
    assert "Local final target: batch historical ELT" in architecture
    assert "Local final target: streaming ETL" in architecture
    assert "Local final target: end-to-end alert sequence" in architecture
    assert "Local stand-ins (no AWS required)" in architecture
    assert "does **not** require an AWS production deploy" in architecture or "AWS production deploy" in architecture
    assert "As-built live price stream" in architecture
    assert "As-built batch lake land" in architecture
    assert "As-built curated features and Isolation Forest" in architecture
    assert "batch_train" in architecture
    assert "python -m app.live" in architecture
    assert "Live alerts on" in architecture
    assert "Mac/Chrome desktop notification" in architecture
    assert "Desktop notification and tab badge" in architecture
    assert "ui/sw-notifications.js" in architecture
    assert "Enable desktop notifications" in architecture
    assert "Slack or email" not in architecture
    assert "Slack and email are not used" in architecture
    assert "prices.raw.bars" in architecture
    assert "live_consumer_heartbeat_at" in architecture
    assert "Perplexity richer reasoning" in architecture
    assert "price-only stays deterministic" in architecture
    assert "batches of eight" in architecture
    assert "model name under Together" in architecture
    assert "Fit Isolation Forest and pick the cutoff" in architecture
    assert "FinBERT is not fine-tuned" in architecture
    assert "Postgres alerts" in architecture
    assert "optional Perplexity API key" in architecture
    assert "Historical headlines are not landed" in architecture
    assert "No historical headlines" in architecture
    assert "percent rule" in architecture.lower() or "percent-rule" in architecture
    assert "live_feature_rows" in architecture
    assert "not scored live yet" not in architecture
    assert "price noticed → news looked up → alignment grade" in architecture
    assert "Live price → near-term news" in architecture
    assert "Upgrade to news or news_price" in architecture or "upgrade to news or news_price" in architecture.lower()
    assert "Fetch near-term headlines for symbol" in architecture or "fetches near-term Yahoo headlines" in architecture
    assert "Evidence story with granular second-side alignment" in architecture
    assert "somewhat supports" in architecture
    assert "**As-built**" in architecture
    assert "evidence story" in architecture.lower()
    assert "HIST_NEWS" not in architecture
    assert "Persisted scored headlines" not in architecture
    assert "HN[Persisted scored headlines]" not in architecture
    assert "Feature rows: gap, session, close, volume z-score, FinBERT" not in architecture
    assert "LLM explanation of an alert" not in architecture
    assert "Cassandra alert store" not in architecture
    assert "CASS[(" not in architecture
    assert "TRAIN --> BERT[FinBERT fine-tune]" not in architecture
    assert "windowed VWAP" not in architecture
    assert "GenAI summarizer" not in architecture
    assert "LLM summarizer" not in architecture
    assert "last 24 hours" not in architecture
    assert "BTC-USD" not in architecture
    assert "Revised target: high-level lambda architecture" not in architecture


def test_ui_uses_desktop_notifications_and_tab_badge():
    ui = _text(ROOT / "alert_service" / "ui" / "index.html")
    assert "ensureNotificationPermission" in ui
    assert "showOsNotifications" in ui
    assert "updateTabBadge" in ui
    assert "noticeNewAlerts" in ui
    assert "Notification.requestPermission" in ui
    assert "clearUnreadBadge" in ui
    assert "requireInteraction: true" in ui
    assert "enableNotify" in ui
    assert "registerNotificationWorker" in ui
    assert "sw-notifications.js" in ui
    assert "Enable desktop notifications" in ui
    assert "Mac notification" in ui
    assert "function alertMetrics" in ui
    assert "head.append(kindPill(alert.kind), symbol, when)" in ui
    assert "renderEvidenceStory" in ui
    assert "What happened" in ui
    assert '"Summary"' in ui
    assert "evidence-story" in ui
    assert "alert-card" in ui
    assert "addCollapsibleSection" in ui
    assert 'price: "price-led"' in ui
    assert 'news: "news-led"' in ui
    assert 'news_price: "aligned"' in ui
    assert "kindPill(alert.kind)" in ui
    assert "function badgeClass" not in ui
    assert 'appendPlain("Together"' not in ui
    assert 'id="clearRecent"' in ui
    assert "Clear alerts" in ui
    assert "tickerAlertHomeClearedAt" in ui
    assert "clearRecentAlerts" in ui
    assert "openHomeAlertKeys" in ui
    assert "openWatchAlertKeys" in ui
    assert "homeAlertFingerprint" in ui
    assert "renderWatchlistCheckAlerts" in ui
    assert "watchlistTab" in ui
    assert "tip-btn" in ui
    assert "<h2>Recent alerts</h2>" in ui
    assert "Incoming alerts stay here across refresh until you clear" in ui
    assert "When new live alerts arrive, this tab gets a count badge" in ui
    assert "Desktop notifications: on. Mac/Chrome will pop up when new alerts arrive." in ui
    assert "function setRecentTip" in ui
    assert "function setHomeScope" in ui
    assert "function alertsForHome" in ui
    assert "homeScope === \"watchlist\"" in ui or "homeScope === 'watchlist'" in ui
    assert "tickerAlertHomeScope" in ui
    assert "scope-toggle" in ui
    assert 'data-scope="sp500"' in ui
    assert 'data-scope="watchlist"' in ui
    assert 'id="recentTip"' in ui
    assert 'id="notifyHint"' not in ui
    assert "Choose S&amp;P 500 constituents, then Scan today" in ui
    assert "Scan today" in ui
    assert "Today's results" in ui
    assert "buildHistoryHeaders" in ui
    assert "originLabel" in ui
    assert 'id="homeScope"' not in ui
    assert 'id="watchlistAlerts"' in ui
    assert 'id="watchlistTab"' in ui
    sw = _text(ROOT / "alert_service" / "ui" / "sw-notifications.js")
    assert "notificationclick" in sw
    assert "clients.openWindow" in sw
    main = _text(ROOT / "alert_service" / "app" / "main.py")
    assert "sw-notifications.js" in main
    assert "Service-Worker-Allowed" in main


def test_data_sources_and_readmes_name_the_same_target():
    sources = _text(DOCS / "data-sources.md")
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in sources
    assert "[architecture.md](architecture.md)" in sources
    assert "Isolation Forest" in sources
    assert "Perplexity writes three to four short sentences" in sources
    assert "Price-only alerts keep the rule sentence" in sources
    assert "deterministic sentence" in sources
    assert "Rule stays under Rule" in sources
    assert "python -m app.live" in sources
    assert "stream_ingest" in sources
    assert "S&P 500" in sources
    assert "price first, then news" in sources.lower()
    assert "live_feature_rows" in sources
    assert "Historical headlines are not pulled into the lake" in sources
    assert "Mac/Chrome desktop notification" in sources
    assert "Slack and email are not used" in sources
    assert "Slack or email" not in sources
    assert "demo stack is **local**" in sources or "demo stack is local" in sources.lower()
    assert "BTC-USD" not in sources
    assert "Watchlist Scan today" in sources
    assert "Home Recent" in sources
    assert "training only" in sources.lower() or "Isolation Forest training" in sources
    assert "Origin" in sources
    readme = _text(ROOT / "README.md")
    assert "[docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md)" in readme
    assert "Isolation Forest" in readme
    assert "Perplexity" in readme
    assert "docker compose up -d" in readme
    assert "Live alerts on" in readme
    assert "Mac desktop notification" in readme
    assert "Enable desktop notifications" in readme
    assert "015_alert_origin.sql" in readme
    assert "alerts.origin" in readme
    assert "live_feature_rows" in readme
    assert "./dev.sh start" in readme
    assert "./dev.sh restart" in readme
    assert "S&P 500" in readme
    assert "S&P 500 Alert System" in readme
    assert "focus set" in readme
    assert "batch_train" in readme
    assert "AWS production deploy is not required" in readme
    assert "As-built vs local final target" in readme
    assert "Home" in readme and "Watchlist" in readme and "History" in readme
    assert "Origin" in readme
    assert "Today's results" in readme
    assert "Scan today" in readme
    assert "Two product paths sit side by side" in readme
    assert "about 5,400 symbols" not in readme
    assert "only for now" not in readme
    assert "Ticker Alert System" not in readme
    batch_train = _text(ROOT / "batch_train" / "README.md")
    assert "Isolation Forest" in batch_train
    assert "gap_return" in batch_train
    assert "volume_zscore" in batch_train
    assert "registry/isolation_forest/current" in batch_train
    assert "Not a Dataproc" in batch_train or "scikit-learn" in batch_train
    lake = _text(ROOT / "data" / "lake" / "README.md")
    assert "registry/isolation_forest/current" in lake
    assert "batch_train" in lake
    service = _text(ROOT / "alert_service" / "README.md")
    assert "docs/proposal-pipeline-audit.md" in service
    assert "docs/architecture.md" in service
    assert "Kafka consumer for session-move price alerts" in service
    assert "Watchlist Scan today" in service or "Watchlist (focus set" in service
    assert "Flink and Spark are the stream and batch engines on the class diagrams" in service
    assert "A saved Perplexity key writes richer news / news + price reasoning" in service
    assert "live price stream" in service or "Live vs Watchlist" in service
    assert "five ChatGPT, five OpenAI, or five Gemini" in service
    assert "at most eight alerts" in service
    assert "ui/sw-notifications.js" in service
    assert "Mac/Chrome desktop notification" in service
    assert "Slack and email are not used" in service
    assert "Slack or email" not in service
    assert "the field shows dots" in readme
    assert "at most eight alerts in one reply" in readme
    architecture = _text(DOCS / "architecture.md")
    assert "The model name is shown under Together" in architecture or "model name under Together" in architecture
    assert "batches of eight" in sources
    audit = _text(DOCS / "proposal-pipeline-audit.md")
    assert "Together shows the name of the model that wrote it" in audit
    assert "batches of eight" in audit
    assert "Historical headlines are not part of the design" in audit
    assert "batch_train" in audit
    assert "local model registry" in audit
    batch = _text(ROOT / "batch_ingest" / "README.md")
    assert "Headlines stay on the near-term check path" in batch
    assert "batch_train" in batch
    lake_readme = _text(ROOT / "data" / "lake" / "README.md")
    assert "No historical headlines are stored here" in lake_readme
