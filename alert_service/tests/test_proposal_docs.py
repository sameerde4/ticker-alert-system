"""The class-proposal docs agree on the revised batch, stream, model, and AI plan."""

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
        "S3 raw zone",
        "Spark",
        "Isolation Forest",
        "Model registry",
        "FinBERT",
        "Perplexity",
        "two sentences",
        "deterministic sentence",
        "news-only and price-only",
        "volume z-score",
        "| Cassandra | Drop |",
    ):
        assert phrase in audit
    assert "Fit Isolation Forest on the curated table" in audit
    assert "Fine-tuning needs labels this project does not have" in audit
    assert "The model does not decide whether the alert exists" in audit or "The model never decides whether the alert exists" in audit
    assert "| Cassandra | Drop |" in audit


def test_architecture_points_at_the_audit_and_names_the_target():
    architecture = _text(DOCS / "architecture.md")
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in architecture
    assert "Perplexity two-sentence summary, with the deterministic sentence as fallback" in architecture
    assert "Spark feature table on S3, Isolation Forest fit on that table, model registry" in architecture
    assert "Flink session features scored with the registered Isolation Forest" in architecture
    assert "Correlation on the price slice (gap, session, or close), including news-only and price-only" in architecture
    assert "Cassandra is not part of the target" in architecture
    assert "Revised target: high-level lambda architecture" in architecture
    assert "Revised target: batch historical ELT" in architecture
    assert "Revised target: streaming ETL" in architecture
    assert "Revised target: end-to-end alert sequence" in architecture
    assert "Perplexity two sentences" in architecture
    assert "batches of eight" in architecture
    assert "model name under Together" in architecture
    assert "Fit Isolation Forest and pick the cutoff" in architecture
    assert "FinBERT is not fine-tuned here" in architecture
    assert "Postgres alerts" in architecture
    assert "optional Perplexity API key" in architecture
    assert "LLM explanation of an alert" not in architecture
    assert "Cassandra alert store" not in architecture
    assert "CASS[(" not in architecture
    assert "TRAIN --> BERT[FinBERT fine-tune]" not in architecture
    assert "windowed VWAP" not in architecture
    assert "GenAI summarizer" not in architecture
    assert "LLM summarizer" not in architecture


def test_data_sources_and_readmes_name_the_same_target():
    sources = _text(DOCS / "data-sources.md")
    assert "[proposal-pipeline-audit.md](proposal-pipeline-audit.md)" in sources
    assert "[architecture.md](architecture.md)" in sources
    assert "Isolation Forest" in sources
    assert "Perplexity writes two sentences" in sources
    assert "deterministic sentence" in sources
    assert "Rule stays under Rule" in sources
    readme = _text(ROOT / "README.md")
    assert "[docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md)" in readme
    assert "revised target diagrams" in readme
    assert "Isolation Forest" in readme
    assert "Perplexity" in readme
    service = _text(ROOT / "alert_service" / "README.md")
    assert "docs/proposal-pipeline-audit.md" in service
    assert "docs/architecture.md" in service
    assert "This process does not run the Kafka, Flink, or Spark stack" in service
    assert "A saved Perplexity key writes the two-sentence alert reasoning" in service
    assert "five ChatGPT, five OpenAI, or five Gemini" in service
    assert "at most eight alerts" in service
    assert "the field shows dots" in readme
    assert "at most eight alerts in one reply" in readme
    architecture = _text(DOCS / "architecture.md")
    assert "The model name is shown under Together" in architecture
    assert "batches of eight" in sources
    audit = _text(DOCS / "proposal-pipeline-audit.md")
    assert "Together shows the name of the model that wrote it" in audit
    assert "batches of eight" in audit
    assert "revised target diagrams" in audit
