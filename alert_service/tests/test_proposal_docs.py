"""Docs agree on the S&P 500 plan: price lake, near-term news, forest on price/volume."""

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
        "two sentences",
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


def test_architecture_points_at_the_audit_and_names_the_target():
    architecture = _text(DOCS / "architecture.md")
    assert "# S&P 500 Alert System architecture" in architecture
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in architecture
    assert "Perplexity two-sentence summary, with the deterministic sentence as fallback" in architecture or "Perplexity two sentences when a key is saved" in architecture
    assert "focus set for Run check" in architecture
    assert "Spark curated feature table" in architecture or "Spark curated feature table (gap, session, close, volume z-score)" in architecture
    assert "Flink session features scored with the registered Isolation Forest" in architecture or "Flink scores the registered forest" in architecture
    assert "Cassandra" in architecture and "Dropped" in architecture
    assert "Revised target: high-level lambda architecture" in architecture
    assert "Revised target: batch historical ELT" in architecture
    assert "Revised target: streaming ETL" in architecture
    assert "Revised target: end-to-end alert sequence" in architecture
    assert "As-built live price stream" in architecture
    assert "As-built batch lake land" in architecture
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
    assert "Perplexity two sentences" in architecture
    assert "batches of eight" in architecture
    assert "model name under Together" in architecture
    assert "Fit Isolation Forest and pick the cutoff" in architecture
    assert "FinBERT is not fine-tuned" in architecture
    assert "Postgres alerts" in architecture
    assert "optional Perplexity API key" in architecture
    assert "Historical headlines are not landed" in architecture
    assert "No historical headlines" in architecture
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
    assert "Perplexity writes two sentences" in sources
    assert "deterministic sentence" in sources
    assert "Rule stays under Rule" in sources
    assert "python -m app.live" in sources
    assert "stream_ingest" in sources
    assert "S&P 500" in sources
    assert "Historical headlines are not pulled into the lake" in sources
    assert "Mac/Chrome desktop notification" in sources
    assert "Slack and email are not used" in sources
    assert "Slack or email" not in sources
    assert "BTC-USD" not in sources
    readme = _text(ROOT / "README.md")
    assert "[docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md)" in readme
    assert "Isolation Forest" in readme
    assert "Perplexity" in readme
    assert "docker compose up -d" in readme
    assert "Live alerts on" in readme
    assert "Mac desktop notification" in readme
    assert "Enable desktop notifications" in readme
    assert "013_live_consumer_heartbeat.sql" in readme
    assert "S&P 500" in readme
    assert "S&P 500 Alert System" in readme
    assert "focus set" in readme
    assert "about 5,400 symbols" not in readme
    assert "only for now" not in readme
    assert "Ticker Alert System" not in readme
    service = _text(ROOT / "alert_service" / "README.md")
    assert "docs/proposal-pipeline-audit.md" in service
    assert "docs/architecture.md" in service
    assert "This process runs a Kafka consumer for session-move price alerts" in service
    assert "Flink and Spark are the stream and batch engines on the class diagrams" in service
    assert "A saved Perplexity key writes the two-sentence alert reasoning" in service
    assert "live price stream" in service
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
    assert "revised target diagrams" in audit
    assert "Historical headlines are not part of the design" in audit
    batch = _text(ROOT / "batch_ingest" / "README.md")
    assert "Headlines stay on the near-term check path" in batch
    lake = _text(ROOT / "data" / "lake" / "README.md")
    assert "No historical headlines are stored here" in lake
