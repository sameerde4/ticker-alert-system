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
        "volume z-score",
        "S&P 500",
        "S&P 500 Radar",
        "planned → landed",
        "Major decisions (planned vs landed)",
    ):
        assert phrase in audit
    assert "architecture.md" in audit
    assert "AWS" in audit and "Local" in audit
    assert "Pull-after-price" in audit or "pull-after-price" in audit.lower()
    assert "Cassandra" in audit and "Drop" in audit
    assert "Historical news archive" in audit or "news lake" in audit.lower()
    assert "FinBERT fine-tune" in audit or "Fine-tuning needs labels" in audit
    assert "VWAP" in audit and "Drop" in audit
    assert "Model never decides" in audit or "never decides whether the alert exists" in audit.lower()
    assert "Near-term news only" in audit
    assert "price/volume" in audit or "price and volume" in audit.lower()
    assert "batch_train" in audit
    assert "live_feature_rows" in audit
    assert "Live plus Watchlist" in audit
    assert "training only" in audit.lower()
    assert "no Kafka news topic" in audit.lower() or "Kafka news topic" in audit
    assert "Home Live alerts" in audit or "Home Recent" in audit
    assert "Watchlist results" in audit
    assert "Screener" not in audit
    assert "/v1/screener/run" not in audit
    assert "Scan today" in audit
    assert "alerts.origin" in audit
    assert "Slide 6" in audit and "Slide 7" in audit and "Slide 8" in audit and "Slide 9" in audit
    assert "What we landed" in audit
    assert "as-built" not in audit.lower() or "Watchlist **as-built**" not in audit


def test_architecture_points_at_the_audit_and_names_the_target():
    architecture = _text(DOCS / "architecture.md")
    assert "# S&P 500 Radar architecture" in architecture
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in architecture
    assert "How to read the diagrams below" in architecture
    assert "Batch historical ELT" in architecture
    assert "Streaming ETL" in architecture
    assert "End-to-end alert sequence" in architecture
    assert "High-level lambda architecture" in architecture
    assert architecture.count("```mermaid") >= 11
    assert "Perplexity richer news / news+price reasoning" in architecture
    assert "focus set" in architecture
    assert "## Live and Watchlist side by side" in architecture
    assert "## Watchlist Scan today" in architecture
    assert "Watchlist results" in architecture
    assert "Screener" not in architecture
    assert "Live alerts" in architecture
    assert "<h2>Recent alerts</h2>" not in architecture
    assert "All / Watchlist / Others" in architecture or "scope: All, Watchlist, or Others" in architecture
    assert "Home Live alerts" in architecture
    assert "alerts.origin" in architecture
    assert "training lake" in architecture.lower() or "training only" in architecture.lower()
    assert "Spark-role curated feature table" in architecture
    assert "Live scorer Flink role" in architecture or "Flink role" in architecture
    assert "Cassandra" in architecture and "Out of scope" in architecture
    assert "## System overview" in architecture
    assert "## System overview with ML + AI" in architecture
    assert "System overview with ML + AI" in architecture
    assert "FinBERT headline grade" in architecture
    assert "LLM wording API" in architecture
    assert "## High-level lambda architecture" in architecture
    assert "## Batch historical ELT" in architecture
    assert "## Streaming ETL" in architecture
    assert "## End-to-end alert sequence" in architecture
    assert "Deck names → what we actually run" in architecture or "Local stand-ins" in architecture
    assert "production deploy" in architecture.lower()
    assert "optional class AWS demo" in architecture or "aws-deployment" in architecture
    assert "AWS class demo host" in architecture
    assert "CloudWatch Logs" in architecture
    assert "market-radar-lake" in architecture
    assert "Managed MSK" in architecture or "not MSK" in architecture
    assert "## Live price stream" in architecture
    assert "## Batch lake land and refresh" in architecture
    assert "## Curated features and Isolation Forest" in architecture
    assert "batch_train" in architecture
    assert "python -m app.live" in architecture
    assert "full S&P 500 universe" in architecture
    assert "S&P 500 universe?" in architecture
    assert "origin=live" in architecture
    assert "clickable headline" in architecture.lower() or "clickable headline titles" in architecture
    assert "price_span" in architecture
    assert "Live alerts on" in architecture
    assert "arm switch" in architecture
    assert "live_alerts_armed" in architecture
    assert "Background heartbeat" in architecture or "background task" in architecture
    assert "backfill" in architecture.lower() and "9:30" in architecture
    assert "cash-open" in architecture.lower() or "open+last" in architecture.lower()
    assert "Live WebSocket" in architecture
    assert "Clear alerts" in architecture
    assert "Alert history" in architecture
    assert "Rebuild Watchlist history" in architecture
    assert "price → news" in architecture or "price then news" in architecture
    assert "not volatile" in architecture
    assert "updated_at" in architecture
    assert "re-enter" in architecture.lower() or "reenter" in architecture.lower()
    assert "schema_migrations" in architecture
    assert "has_raw_prices" in architecture
    assert "TICKER_ALERT_LAKE_S3_BUCKET" in architecture or "S3" in architecture
    assert "aws-deployment.md" in architecture
    assert "Mac/Chrome desktop notification" in architecture
    assert "Desktop notification" in architecture and "tab badge" in architecture
    assert "ui/sw-notifications.js" in architecture
    assert "Enable desktop notifications" in architecture
    assert "Slack or email" not in architecture
    assert "Slack and email are not used" in architecture
    assert "not AWS Lambda" in architecture or "*not* AWS Lambda" in architecture
    assert "data lake" in architecture.lower()
    assert "Flink-role" in architecture
    assert "technical role" in architecture.lower()
    assert "prices.raw.bars" in architecture
    assert "live_consumer_heartbeat_at" in architecture
    assert "Perplexity richer reasoning" in architecture
    assert "price-only stays deterministic" in architecture
    assert "forest-aware price-only wording" in architecture
    assert "percent floor" in architecture.lower() or "forest as enricher" in architecture.lower()
    assert "Watchlist Scan today / rebuild uses the same Isolation Forest" in architecture
    assert "Price gates (percent" in architecture
    assert "no news support" in architecture.lower() or "without news" in architecture.lower()
    assert "volatile" in architecture and "anomalous" in architecture
    assert "price-led" in architecture and "news-led" in architecture
    assert "price + news" in architecture and "agrees" in architecture and "disagrees" in architecture
    assert "climate average" in architecture.lower()
    assert "climate join" in architecture.lower()
    assert "polarized" in architecture.lower()
    assert "volatile + anomalous" in architecture or "volatile_anomalous" in architecture
    assert "(neither gate)" in architecture or "omit shape" in architecture.lower() or "omit" in architecture
    assert "What can trigger a price-led alert" in architecture
    assert "#1" in architecture and "Price move threshold" in architecture
    assert "Volume z-score" in architecture
    assert "Volume spike note" in architecture
    assert "triggers: #1 percent" in architecture or "[triggers:" in architecture
    assert "Incremental lake refresh" in architecture
    assert "Refresh lake + retrain" in architecture or "refresh" in architecture.lower()
    assert "Auto first-boot lake land" in architecture
    assert "Loading historical prices" in architecture
    assert "Daily auto schedule" in architecture or "daily auto" in architecture.lower()
    assert "Settings Refresh merge" in architecture or "Refresh merge" in architecture
    assert "union by dt keep newest" in architecture
    assert "Skip Yahoo and retrain" in architecture or "skips Yahoo + retrain" in architecture
    assert "last completed session" in architecture
    assert "Kafka minute bars do **not** write the lake" in architecture or "do **not** write the lake" in architecture
    assert "US Eastern" in architecture
    assert "Focus session" in architecture and "last completed" in architecture
    assert "Watchlist Scan today focus session" in architecture
    assert "Price change" in architecture and "Sentiment score" in architecture
    assert "Origin" in architecture and "Company" in architecture and "Type" in architecture
    assert "20 rows" in architecture or "20 rows per page" in architecture
    assert "First / Previous / Next / Last" in architecture
    assert "Collapsed Live / Watchlist cards" in architecture
    assert "one-line head" in architecture
    assert "Details popup" in architecture and "frozen header" in architecture
    assert "Alert History table" in architecture and "20 rows / page" in architecture
    assert "story pills sit on the collapsed card" in architecture
    assert "REG --> SCAN" in architecture
    assert "Watchlist Scan today" in architecture and "percent or forest" in architecture
    assert "finished local system" in architecture.lower() or "finished-system" in architecture.lower() or "finished** local" in architecture
    assert "no separate Kafka news topic" in architecture or "Kafka news topic" in architecture
    assert "Richer forest-aware price-only wording" in architecture
    assert "as-built" not in architecture.lower()
    assert "local final" not in architecture.lower()
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
    assert "price noticed → headlines checked → grade how well the news explains the session" in architecture
    assert "Live price → same-day headline grade" in architecture
    assert "Upgrade to news or news_price" in architecture or "upgrade to news or news_price" in architecture.lower() or "news or news+price" in architecture
    assert "Fetch near-term headlines for symbol" in architecture or "fetches near-term Yahoo headlines" in architecture or "fetches near-term headlines" in architecture
    assert "Evidence story with granular second-side alignment" in architecture
    assert "decision-support" not in architecture.lower()
    assert "grade how well the news explains the session" in architecture
    assert "somewhat supports" in architecture
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


def test_aws_deployment_doc_matches_as_built_demo():
    aws = _text(DOCS / "aws-deployment.md")
    assert "# AWS deployment" in aws
    assert "deployed on EC2" in aws
    assert "market-radar-" in aws
    assert "i-0e437ba8984153370" in aws or "market-radar" in aws
    assert "sync-and-deploy.sh" in aws
    assert "schema_migrations" in aws
    assert "live_alerts_armed" in aws or "Live alerts" in aws
    assert "backfill" in aws.lower()
    assert "cash-open + latest" in aws.lower() or "open+last" in aws.lower()
    assert "updated_at" in aws
    assert "ALPACA_WS_SYMBOL_LIMIT" in aws or "Live WebSocket" in aws
    assert "WebSocket" in aws
    assert "Forest under floor" in aws or "without news" in aws.lower()
    assert "Clear alerts" in aws or "/v1/admin/alerts/clear" in aws
    assert "Cache-Control" in aws or "no-store" in aws
    assert "Postgres container" in aws
    assert "not EKS" in aws
    assert "Secrets Manager" in aws
    assert "8010/ui" in aws
    assert "98.94.232.101" in aws
    assert "unsafely-treat-insecure-origin-as-secure" in aws
    assert "market-radar-lake" in aws
    assert "TICKER_ALERT_LAKE_S3_BUCKET" in aws
    assert "Durable" in aws or "durable" in aws
    assert "/market-radar/demo" in aws
    assert "awslogs" in aws
    assert "CloudWatch Logs" in aws
    assert "Elastic IP" in aws
    assert "release" in aws.lower()
    assert "infra/eip.tf" in aws or "aws_eip" in aws or "elastic_ip" in aws
    assert "infra/" in aws and "CloudWatch" in aws
    assert "[architecture.md](architecture.md)" in aws


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
    assert "appendStoryAndShapePills(primary, alert)" in ui
    assert "alert-head-primary" in ui
    assert "detail-title-primary" in ui
    assert "HISTORY_PAGE_SIZE = 20" in ui
    assert 'id="historyPager"' in ui
    assert "function setHistoryPage" in ui
    assert "header.insertBefore(when, closeBtn)" in ui
    assert "width: min(960px, 100%)" in ui
    assert "border-bottom: 1px solid rgba(243, 239, 228, 0.08)" in ui
    assert "Twenty rows per page" in ui
    assert "companyNameEl(alert.symbol)" in ui
    assert "function historyTypePriceStat" in ui
    assert "function alertHeadMetrics" not in ui
    assert '"type"' in ui and '"shape"' in ui and '"direction"' in ui
    assert 'label: "Alert type"' in ui
    assert 'label: "Price shape"' in ui
    assert 'label: "Direction"' in ui
    assert "DEFAULT_HISTORY_COLS" in ui
    assert "renderEvidenceStory" in ui
    assert "renderEvidenceOutcome" in ui
    assert "evidence-outcome-chip" in ui
    assert "alignment-emphasis" in ui
    assert "What happened" in ui
    assert '"Summary"' in ui
    assert "appendForestUnderPrice" in ui
    assert 'appendPlain("Price"' in ui
    assert "Refresh lake + retrain" in ui
    assert 'id="refreshLake"' in ui
    assert 'id="lakeHeaderStatus"' in ui
    assert "Loading historical prices" in ui
    assert "function lakeHeaderCopy" in ui
    assert "has_raw_prices === true" in ui
    assert "Live alerts starting…" in ui
    assert "manual overrides" in ui
    assert "/v1/admin/lake/refresh" in ui
    main = _text(ROOT / "alert_service" / "app" / "main.py")
    assert "Cache-Control" in main and "no-store" in main
    assert "Price move threshold" in ui
    assert "Price alert percentage" not in ui
    assert "Two price gates" in ui
    assert "Isolation Forest (trained on the lake)" in ui or "Isolation Forest" in ui
    assert 'id="homeLede"' in ui
    assert "S&amp;P 500 Radar monitors the index for price movements and anomalies" in ui
    assert "grade how well the news explains the session" in ui
    assert "S&amp;P 500 Radar" in ui
    assert "Alert System" not in ui
    assert "Decision-support" not in ui
    modal_h3 = ui.split(".modal-header h3 {", 1)[1].split("}", 1)[0]
    assert "font-family: ui-sans-serif, system-ui, sans-serif" in modal_h3
    assert "Price: ${move}% move threshold" in ui
    assert "evidence-story" in ui
    assert "alert-card" in ui
    assert "addCollapsibleSection" in ui
    assert 'price: "price-led"' in ui
    assert 'news: "news-led"' in ui
    assert 'news_price: "price + news"' in ui
    assert "Climate sentiment" in ui
    assert "climate join" in ui
    assert "polarized" in ui
    assert "Rule & history" in ui
    assert "function alertWhenStamp" in ui
    assert "function buildAlertTimeline" in ui
    assert "update_history" in ui
    assert 'no_news: "no recent news"' in ui
    assert "kindPill(alert.kind, alert)" in ui
    assert "PRICE_SHAPE_LABELS" in ui
    assert "priceShapePill" in ui
    assert "AGREEMENT_LABELS" in ui
    assert "agreementPill" in ui
    assert "appendStoryAndShapePills" in ui
    assert "function badgeClass" not in ui
    assert 'appendPlain("Together"' not in ui
    assert 'id="clearRecent"' in ui
    assert "Clear alerts" in ui
    assert "Alert history" in ui
    assert "Rebuild Watchlist history" in ui
    assert "Clear Watchlist history" in ui
    assert "Clear Live history" in ui
    assert "evidence-bullets" in ui
    assert 'return "flat"' in ui
    assert "#5eead4" in ui and "#ffb070" in ui
    assert "tickerAlertHomeClearedAt" in ui
    assert "alert.updated_at || alert.created_at" in ui
    assert "clearRecentAlerts" in ui
    assert "openHomeAlertKeys" in ui
    assert "openWatchAlertKeys" in ui
    assert "homeAlertFingerprint" in ui
    assert "renderWatchlistCheckAlerts" in ui
    assert "watchlistTab" in ui
    assert "tip-btn" in ui
    assert "<h2>Live alerts</h2>" in ui
    assert "About Live alerts:" in ui
    assert "live Kafka stream" in ui
    assert "Alerts from the live Kafka stream" in ui
    assert "stay here across refresh until you clear" in ui
    assert "Alert History has the full list" in ui
    assert "When new live alerts arrive, this tab gets a count badge" not in ui
    assert "Desktop notifications: on. Mac/Chrome will pop up when new alerts arrive." not in ui
    assert "function setRecentTip" in ui
    assert "border-bottom: 1px solid var(--line)" in ui
    assert "max-width: none" in ui
    assert "function setHomeScope" in ui
    assert "function alertsForHome" in ui
    assert "homeScope === \"watchlist\"" in ui or "homeScope === 'watchlist'" in ui
    assert "homeScope === \"others\"" in ui or "homeScope === 'others'" in ui
    assert "filterAlertsByHomeScope" in ui
    assert "tickerAlertHomeScope" in ui
    assert "scope-toggle" in ui
    assert 'data-scope="all"' in ui
    assert 'data-scope="watchlist"' in ui
    assert 'data-scope="others"' in ui
    assert "All, Watchlist, or Others" in ui
    assert "border-radius: 8px" in ui.split(".scope-toggle {", 1)[1].split("}", 1)[0]
    assert "font-family: ui-sans-serif, system-ui, sans-serif" in ui.split(".scope-toggle .scope-opt {", 1)[1].split("}", 1)[0]
    assert 'id="recentTip"' in ui
    assert 'id="notifyHint"' not in ui
    assert "Choose S&amp;P 500 constituents, then Scan today" in ui
    assert "last completed session" in ui
    assert "Scan today" in ui
    assert "Watchlist results" in ui
    assert 'id="enableScreener"' in ui
    assert "Enable Screener" in ui
    assert "<h2>Screener</h2>" in ui
    assert ".tab-btn[hidden] { display: none; }" in ui
    assert "function applyScreenerVisibility" in ui
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
    assert "Price-only alerts stay deterministic" in sources
    assert "forest-aware" in sources
    assert "Incremental lake refresh" in sources
    assert "Refresh lake + retrain" in sources
    assert "skips Yahoo + retrain" in sources or "skip Yahoo" in sources.lower()
    assert "last completed session" in sources
    assert "focus-session" in sources or "Focus session" in sources or "focus session" in sources.lower()
    assert "Percent floor + forest enricher" in sources or "forest enricher" in sources
    assert "Alert history" in sources
    assert "Rebuild Watchlist history" in sources
    assert "20 rows" in sources
    assert "First / Previous / Next / Last" in sources
    assert "one-line head" in sources
    assert "frozen strip" in sources or "end-to-end rule" in sources
    assert "climate join" in sources.lower() or "climate average" in sources.lower()
    assert "not volatile" in sources or "Price noticed" in sources
    assert "Price-trigger cases" in sources
    assert "Isolation Forest anomalous" in sources
    assert "without news" in sources.lower() or "No** under" in sources
    assert "Volume z-score" in sources
    assert "deterministic sentence" in sources
    assert "Rule stays under Rule" in sources
    assert "python -m app.live" in sources
    assert "stream_ingest" in sources
    assert "S&P 500" in sources
    assert "headline grade" in sources.lower() or "grade how well the news explains" in sources.lower()
    assert "live_feature_rows" in sources
    assert "Historical headlines are not pulled into the lake" in sources
    assert "decision-support" not in sources.lower()
    assert "Mac/Chrome desktop notification" in sources
    assert "Slack and email are not used" in sources
    assert "Slack or email" not in sources
    assert "local" in sources.lower() and "aws-deployment.md" in sources
    assert "cash-open + latest" in sources.lower() or "backfill cash-open" in sources.lower()
    assert "updated_at" in sources
    assert "CloudWatch" in sources or "Elastic IP" in sources
    assert "background task" in sources
    assert "BTC-USD" not in sources
    assert "Watchlist Scan today" in sources
    assert "Home Live alerts" in sources or "Home Recent" in sources
    assert "training only" in sources.lower() or "Isolation Forest training" in sources
    assert "Origin" in sources
    assert "Screener" not in sources
    readme = _text(ROOT / "README.md")
    assert "[docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md)" in readme
    assert "price movements and anomalies" in readme
    assert "grade how well the news explains the session" in readme
    assert "Decision-support" not in readme
    assert "Screener" not in readme
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
    assert "S&P 500 Radar" in readme
    assert "focus set" in readme
    assert "batch_train" in readme
    assert "Managed MSK" in readme or "AWS production deploy is not required" in readme
    assert "aws-deployment.md" in readme
    assert "updated_at" in readme
    assert "Live WebSocket" in readme
    assert "Clear alerts" in readme
    assert "Alert history" in readme or "Rebuild Watchlist history" in readme
    assert "Finished-system diagrams" in readme
    assert "planned → landed" in readme.lower() or "keep / change / drop" in readme.lower()
    assert "As-built vs local final" not in readme
    assert "Home" in readme and "Watchlist" in readme and "History" in readme
    assert "20-row" in readme or "20 rows" in readme
    assert "First / Previous / Next / Last" in readme
    assert "story pills" in readme
    assert "full-width rule" in readme
    assert "Origin" in readme
    assert "Watchlist results" in readme
    assert "Scan today" in readme
    assert "Refresh lake + retrain" in readme
    assert "--days 14 --merge" in readme
    assert "skips Yahoo + retrain" in readme or "already current" in readme
    assert "last completed session" in readme
    assert "Company" in readme
    assert "Two product paths sit side by side" in readme
    assert "about 5,400 symbols" not in readme
    assert "only for now" not in readme
    assert "Ticker Alert System" not in readme
    assert "Alert System" not in readme
    assert "S&P 500 Radar" in _text(DOCS / "architecture.md")
    assert "Alert System" not in _text(DOCS / "architecture.md")
    assert "S&P 500 Radar" in _text(DOCS / "proposal-pipeline-audit.md")
    assert "S&P 500 Radar" in _text(DOCS / "data-sources.md")
    batch_train = _text(ROOT / "batch_train" / "README.md")
    assert "Isolation Forest" in batch_train
    assert "gap_return" in batch_train
    assert "volume_zscore" in batch_train
    assert "registry/isolation_forest/current" in batch_train
    assert "Not a Dataproc" in batch_train or "scikit-learn" in batch_train
    assert "Refresh lake + retrain" in batch_train
    assert "Watchlist Scan today" in batch_train
    lake = _text(ROOT / "data" / "lake" / "README.md")
    assert "registry/isolation_forest/current" in lake
    assert "batch_train" in lake
    assert "Refresh lake + retrain" in lake or "Refresh" in lake
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
    assert "forest_wording.py" in service
    assert "watchlist_forest.py" in service
    assert "the field shows dots" in readme
    assert "at most eight alerts in one reply" in readme
    architecture = _text(DOCS / "architecture.md")
    assert "The model name is shown under Together" in architecture or "model name under Together" in architecture
    assert "batches of eight" in sources
    audit = _text(DOCS / "proposal-pipeline-audit.md")
    assert "Together shows the name of the model that wrote it" in audit
    assert "batches of eight" in audit.lower()
    assert "Historical headlines are not part of the design" in audit
    assert "batch_train" in audit
    assert "local model registry" in audit
    assert "percent or forest" in audit.lower()
    assert "Refresh lake + retrain" in audit
    assert "skips Yahoo" in audit.lower() or "already current" in audit.lower() or "skip when current" in audit.lower()
    assert "focus session" in audit.lower()
    assert "Kafka news topic" in audit
    assert "Watchlist forest parity" in audit or "forest parity" in audit
    assert "Major decisions (planned vs landed)" in audit
    batch = _text(ROOT / "batch_ingest" / "README.md")
    assert "Headlines stay on the near-term check path" in batch
    assert "batch_train" in batch
    assert "--days 14 --merge" in batch
    assert "Refresh lake + retrain" in batch
    lake_readme = _text(ROOT / "data" / "lake" / "README.md")
    assert "No historical headlines are stored here" in lake_readme
