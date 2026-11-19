"""Perplexity rewrites news / news+price alerts; price-only keeps the rule text."""

import asyncio
import json
from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient

from app.checks import _reason
from app.engine import AlertDraft
from app.main import _settings_payload, app
from app.perplexity import apply_reasoning, complete_reasoning, reasoning_payload
from app.perplexity_catalog import known_model, model_groups, model_label, resolve_model


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
    payload = reasoning_payload([_draft("AVGO"), _draft("LITE", "news"), _draft("MSFT", "price")])
    instructions = payload["instructions"].lower()
    assert "three to four" in instructions
    assert "do not decide" in instructions
    assert "do not merely restate" in instructions
    assert "forward" in instructions
    assert "url" in instructions
    symbols = [item["symbol"] for item in payload["alerts"]]
    assert symbols == ["AVGO", "LITE"]
    assert "MSFT" not in symbols
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


def test_price_only_drafts_are_skipped_for_reasoning():
    from app.perplexity import drafts_for_reasoning

    price = _draft("MSFT", "price")
    news = _draft("AAPL", "news")
    assert drafts_for_reasoning([price]) == []
    assert [d.symbol for d in drafts_for_reasoning([price, news])] == ["AAPL"]


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
    updated, error = complete_reasoning("pplx-secret", [_draft("AVGO")], "gpt-5.4-mini")
    assert error is None
    assert captured["url"] == "https://api.perplexity.ai/v1/agent"
    assert captured["auth"] == "Bearer pplx-secret"
    assert captured["body"]["model"] == "openai/gpt-5.4-mini"
    assert captured["body"]["max_output_tokens"] == 6000
    assert captured["body"]["temperature"] == 0.3
    assert captured["body"]["response_format"]["json_schema"]["name"] == "alert_reasoning"
    sent = json.loads(captured["body"]["input"])
    assert sent["alerts"][0]["symbol"] == "AVGO"
    assert "pplx-secret" not in captured["body"]["input"]
    assert updated[0].summary.startswith("Broadcom fell")
    assert updated[0].sections["model"] == "gpt-5.4-mini"
    assert updated[0].sections["model_label"] == "OpenAI · Balanced · gpt-5.4-mini"


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

    def fake(key, drafts, model=None):
        seen["key"] = key
        seen["model"] = model
        seen["symbols"] = [draft.symbol for draft in drafts]
        return drafts, None

    monkeypatch.setattr("app.checks.complete_reasoning", fake)
    drafts, reasoning, error = asyncio.run(_reason(_Pool("pplx-saved"), [_draft("AVGO"), _draft("LITE")]))
    assert reasoning == "perplexity"
    assert error is None
    assert seen["key"] == "pplx-saved"
    assert seen["symbols"] == ["AVGO", "LITE"]
    assert seen["model"] == "openai/gpt-5.4-mini"
    assert drafts[0].symbol == "AVGO"


def test_a_large_check_asks_for_reasoning_in_batches(monkeypatch):
    seen = []

    def fake(key, drafts, model=None):
        seen.append([draft.symbol for draft in drafts])
        return drafts, None

    monkeypatch.setattr("app.checks.complete_reasoning", fake)
    drafts = [_draft(f"S{index}") for index in range(9)]
    updated, reasoning, error = asyncio.run(_reason(_Pool("pplx-saved"), drafts))
    assert reasoning == "perplexity"
    assert error is None
    assert seen == [[f"S{index}" for index in range(8)], ["S8"]]
    assert len(updated) == 9


def test_a_dropped_alert_is_sent_again(monkeypatch):
    calls = []

    def fake(key, drafts, model=None):
        from dataclasses import replace

        calls.append([draft.symbol for draft in drafts])
        if len(drafts) > 1:
            first = replace(
                drafts[0],
                summary="AVGO rewritten.",
                sections={**drafts[0].sections, "model_label": "ChatGPT"},
            )
            return [first], None
        kept = drafts[0]
        return [replace(kept, summary="LITE rewritten.", sections={**kept.sections, "model_label": "ChatGPT"})], None

    monkeypatch.setattr("app.checks.complete_reasoning", fake)
    updated, reasoning, error = asyncio.run(_reason(_Pool("pplx-saved"), [_draft("AVGO"), _draft("LITE")]))
    assert reasoning == "perplexity"
    assert error is None
    assert calls == [["AVGO", "LITE"], ["LITE"]]
    assert updated[0].summary == "AVGO rewritten."
    assert updated[1].summary == "LITE rewritten."


def test_a_check_without_a_key_keeps_the_rule_sentence(monkeypatch):
    monkeypatch.setattr("app.checks.settings.perplexity_api_key", "")

    def fail(*_args, **_kwargs):
        raise AssertionError("Perplexity was called without a key")

    monkeypatch.setattr("app.checks.complete_reasoning", fail)
    drafts, reasoning, error = asyncio.run(_reason(_Pool(""), [_draft("AVGO")]))
    assert reasoning == "rules"
    assert error is None
    assert drafts[0].summary == "AVGO rule sentence."


def test_the_model_name_is_stored_on_together_without_rewriting_price_or_news():
    draft = replace(
        _draft("AVGO"),
        sections={"price": "price text", "news": "news text", "synthesis": "AVGO rule sentence."},
    )
    updated = apply_reasoning(
        [draft],
        {"alerts": [{"symbol": "AVGO", "bar_date": "2026-11-16", "summary": "AVGO fell."}]},
        "openai/gpt-5.4-mini",
    )
    sections = updated[0].sections
    assert sections["price"] == "price text"
    assert sections["news"] == "news text"
    assert sections["synthesis"] == "AVGO fell."
    assert sections["rules"] == "AVGO rule sentence."
    assert sections["model"] == "openai/gpt-5.4-mini"
    assert sections["model_label"] == "ChatGPT · Balanced · openai/gpt-5.4-mini"


def test_a_news_only_reply_keeps_the_rule_sentence_and_names_the_model():
    updated = apply_reasoning(
        [_draft("AAPL", "news")],
        {"alerts": [{"symbol": "AAPL", "bar_date": "2026-11-16", "summary": "Apple news only."}]},
        "google/gemini-3.6-flash",
    )
    sections = updated[0].sections
    assert updated[0].summary == "Apple news only."
    assert sections["rules"] == "AAPL rule sentence."
    assert sections["synthesis"] == "Apple news only."
    assert sections["model"] == "google/gemini-3.6-flash"
    assert sections["model_label"] == "Gemini · Balanced · google/gemini-3.6-flash"


def test_a_reply_without_a_model_does_not_invent_a_label():
    updated = apply_reasoning(
        [_draft("AVGO")],
        {"alerts": [{"symbol": "AVGO", "bar_date": "2026-11-16", "summary": "AVGO fell."}]},
    )
    assert updated[0].summary == "AVGO fell."
    assert updated[0].sections["rules"] == "AVGO rule sentence."
    assert "model" not in updated[0].sections
    assert "model_label" not in updated[0].sections


def test_one_failed_batch_keeps_its_rule_sentences(monkeypatch):
    def fake(key, drafts, model=None):
        if len(drafts) > 1:
            return drafts, "timed out"
        done = replace(
            drafts[0],
            summary="done",
            sections={**drafts[0].sections, "model_label": "ChatGPT"},
        )
        return [done], None

    monkeypatch.setattr("app.checks.complete_reasoning", fake)
    drafts = [_draft(f"S{index}") for index in range(9)]
    updated, reasoning, error = asyncio.run(_reason(_Pool("pplx-saved"), drafts))
    assert reasoning == "perplexity"
    assert error == "timed out"
    assert updated[0].summary == "S0 rule sentence."
    assert updated[-1].summary == "done"


def test_public_settings_list_the_models_and_hide_the_key():
    payload = _settings_payload(
        {"price_move_threshold": 0.03, "sentiment_threshold": 25.0},
        perplexity_key_saved=True,
        perplexity_model_id="openai/gpt-5.4-mini",
    )
    assert "perplexity_api_key" not in payload
    assert payload["perplexity_key_saved"] is True
    assert payload["perplexity_model"] == "openai/gpt-5.4-mini"
    groups = {group["group"]: len(group["models"]) for group in payload["perplexity_models"]}
    assert groups == {"ChatGPT": 5, "OpenAI": 5, "Gemini": 5}


def test_the_saved_label_names_the_dropdown_group():
    assert model_label("openai/gpt-5.4-mini") == "ChatGPT · Balanced · openai/gpt-5.4-mini"
    assert model_label("gpt-5.4-mini") == "OpenAI · Balanced · gpt-5.4-mini"
    assert model_label("google/gemini-3.1-pro-preview") == "Gemini · Premium · google/gemini-3.1-pro-preview"


def test_the_model_dropdown_has_five_chatgpt_openai_and_gemini_choices():
    groups = {group["group"]: group["models"] for group in model_groups()}
    assert [len(groups[name]) for name in ("ChatGPT", "OpenAI", "Gemini")] == [5, 5, 5]
    assert known_model("gpt-5.4-mini") == "gpt-5.4-mini"
    assert resolve_model("gpt-5.4-mini") == "openai/gpt-5.4-mini"
    assert resolve_model("google/gemini-3.6-flash") == "google/gemini-3.6-flash"
    assert resolve_model("not-a-model") == "openai/gpt-5.4-mini"


def test_a_blank_perplexity_key_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.put("/v1/settings/perplexity", json={"perplexity_api_key": "   "})
    assert response.status_code == 400
    spaced = client.put("/v1/settings/perplexity", json={"perplexity_api_key": "pplx secret"})
    assert spaced.status_code == 400
