"""Perplexity receives the decided alerts and returns two sentences, or the rule text stays."""

import asyncio
import json
from datetime import date

from fastapi.testclient import TestClient

from app.checks import _reason
from app.engine import AlertDraft
from app.main import app
from app.perplexity import apply_reasoning, complete_reasoning, reasoning_payload


def _draft(symbol: str, kind: str = "news_price") -> AlertDraft:
    return AlertDraft(
        kind=kind,
        symbol=symbol,
        bar_date=date(2026, 11, 16),
        headline_id=None,
        price_change_pct=-0.0418 if kind != "news" else None,
        latest_close=210.0,
        prior_close=219.0,
        volume_ratio=1.2,
        volume_spike=False,
        sentiment_score=23.8,
        headline_title=None,
        summary=f"{symbol} rule sentence.",
        articles=(
            {
                "title": f"{symbol} falls after a forecast cut",
                "url": "https://finance.yahoo.com/news/example",
                "source": "Yahoo Finance",
                "published_at": "2026-11-16T14:30:00+00:00",
                "sentiment_score": 8.0,
                "confidence": 0.91,
                "positive_pct": 4.0,
                "negative_pct": 88.0,
                "neutral_pct": 8.0,
            },
        ),
        sections={"synthesis": f"{symbol} rule sentence."} if kind == "news_price" else {},
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
    )


def test_one_payload_carries_every_symbol_price_headline_and_finbert_detail():
    payload = reasoning_payload([_draft("AVGO"), _draft("LITE", "news")])
    assert "two sentences" in payload["instructions"]
    assert "do not decide" in payload["instructions"].lower()
    symbols = [item["symbol"] for item in payload["alerts"]]
    assert symbols == ["AVGO", "LITE"]
    avgo = payload["alerts"][0]
    assert avgo["price_change_pct"] == -0.0418
    headline = avgo["headlines"][0]
    assert headline["title"].startswith("AVGO")
    assert headline["sentiment_score"] == 8.0
    assert headline["confidence"] == 0.91
    assert headline["positive_pct"] == 4.0
    assert headline["negative_pct"] == 88.0
    assert headline["neutral_pct"] == 8.0
    assert payload["alerts"][1]["price_change_pct"] is None
    assert "pplx-" not in json.dumps(payload)


def test_a_reply_replaces_the_summary_and_keeps_the_rule_sentence():
    drafts = [_draft("AVGO"), _draft("LITE")]
    updated = apply_reasoning(
        drafts,
        {
            "alerts": [
                {
                    "symbol": "avgo",
                    "bar_date": "2026-11-16",
                    "summary": "Broadcom fell 4.18%. The forecast cut is the candidate reason.",
                }
            ]
        },
    )
    assert updated[0].summary.startswith("Broadcom fell")
    assert updated[0].sections["rules"] == "AVGO rule sentence."
    assert updated[0].sections["synthesis"].startswith("Broadcom fell")
    assert updated[1].summary == "LITE rule sentence."
    assert "rules" not in updated[1].sections


def test_a_failed_call_keeps_the_rule_sentence(monkeypatch):
    def explode(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("app.perplexity.request.urlopen", explode)
    drafts = [_draft("AVGO")]
    updated, error = complete_reasoning("pplx-test", drafts)
    assert updated[0].summary == "AVGO rule sentence."
    assert "timed out" in error


def test_a_successful_call_sends_the_json_schema_and_not_the_key(monkeypatch):
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            body = {
                "output_text": json.dumps(
                    {
                        "alerts": [
                            {
                                "symbol": "AVGO",
                                "bar_date": "2026-11-16",
                                "summary": "Broadcom fell 4.18%. The forecast cut is the candidate reason.",
                            }
                        ]
                    }
                )
            }
            return json.dumps(body).encode()

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode())
        return _Response()

    monkeypatch.setattr("app.perplexity.request.urlopen", fake_urlopen)
    updated, error = complete_reasoning("pplx-secret", [_draft("AVGO")])
    assert error is None
    assert captured["url"] == "https://api.perplexity.ai/v1/agent"
    assert captured["auth"] == "Bearer pplx-secret"
    assert captured["body"]["response_format"]["json_schema"]["name"] == "alert_reasoning"
    sent = json.loads(captured["body"]["input"])
    assert sent["alerts"][0]["symbol"] == "AVGO"
    assert "pplx-secret" not in captured["body"]["input"]
    assert updated[0].summary.startswith("Broadcom fell")


class _Acquire:
    def __init__(self, key: str):
        self.key = key

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def fetchrow(self, *_args, **_kwargs):
        return {"perplexity_api_key": self.key}


class _Pool:
    def __init__(self, key: str):
        self.key = key

    def acquire(self):
        return _Acquire(self.key)


def test_a_check_sends_the_saved_key_with_the_decided_alerts(monkeypatch):
    seen = {}

    def fake(key, drafts):
        seen["key"] = key
        seen["symbols"] = [draft.symbol for draft in drafts]
        return drafts, None

    monkeypatch.setattr("app.checks.complete_reasoning", fake)
    drafts, reasoning, error = asyncio.run(_reason(_Pool("pplx-saved"), [_draft("AVGO"), _draft("LITE")]))
    assert reasoning == "perplexity"
    assert error is None
    assert seen == {"key": "pplx-saved", "symbols": ["AVGO", "LITE"]}
    assert drafts[0].symbol == "AVGO"


def test_a_check_without_a_key_keeps_the_rule_sentence(monkeypatch):
    monkeypatch.setattr("app.checks.settings.perplexity_api_key", "")

    def fail(*_args, **_kwargs):
        raise AssertionError("Perplexity was called without a key")

    monkeypatch.setattr("app.checks.complete_reasoning", fail)
    drafts, reasoning, error = asyncio.run(_reason(_Pool(""), [_draft("AVGO")]))
    assert reasoning == "rules"
    assert error is None
    assert drafts[0].summary == "AVGO rule sentence."


def test_a_blank_perplexity_key_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.put("/v1/settings/perplexity", json={"perplexity_api_key": "   "})
    assert response.status_code == 400
    spaced = client.put("/v1/settings/perplexity", json={"perplexity_api_key": "pplx secret"})
    assert spaced.status_code == 400
