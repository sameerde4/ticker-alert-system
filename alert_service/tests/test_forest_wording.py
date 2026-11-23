"""Forest-aware deterministic price-only wording (#13)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.engine import AlertDraft
from app.evidence import attach_evidence_story
from app.forest_live import ForestScore
from app.forest_wording import (
    enrich_price_draft_with_forest_wording,
    forest_driver_explanations,
    forest_driver_sentence,
    forest_evidence_detail,
    forest_price_summary,
)
from app.live_alerts import forest_price_draft_from_session
from app.live_session import SessionState


def _weird_score(**overrides) -> ForestScore:
    base = dict(
        features={
            "gap_return": 0.05,
            "session_return": -0.04,
            "close_return": 0.01,
            "volume_zscore": 4.0,
        },
        forest_score=-0.1,
        score_cutoff=0.0,
        anomalous=True,
        model_id="isolation_forest_v1",
    )
    base.update(overrides)
    return ForestScore(**base)


def test_forest_summary_says_percent_stayed_under_when_move_small():
    text = forest_price_summary(
        "AAPL",
        model_id="isolation_forest_v1",
        forest_score=-0.1,
        score_cutoff=0.0,
        features={
            "gap_return": 0.05,
            "session_return": 0.01,
            "close_return": 0.06,
            "volume_zscore": 4.0,
        },
        open_px=100.0,
        last_px=101.0,
        price_move_threshold=0.03,
        change=0.01,
    )
    assert "stayed under the 3.0% percent rule" in text
    assert "not the percent alone" in text
    assert "volume" in text.lower()
    assert "Isolation Forest" in text


def test_forest_summary_mentions_percent_when_both_clear():
    text = forest_price_summary(
        "MSFT",
        model_id="isolation_forest_v1",
        forest_score=-0.2,
        score_cutoff=0.0,
        features={
            "gap_return": 0.02,
            "session_return": 0.04,
            "close_return": 0.06,
            "volume_zscore": 1.2,
        },
        open_px=100.0,
        last_px=104.0,
        price_move_threshold=0.03,
        change=0.04,
    )
    assert "also cleared the 3.0% percent rule" in text
    assert "open→last" in text


def test_forest_driver_prefers_loudest_features():
    sentence = forest_driver_sentence(
        {
            "gap_return": 0.01,
            "session_return": 0.01,
            "close_return": 0.01,
            "volume_zscore": 5.0,
        }
    )
    assert "volume" in sentence.lower()


def test_forest_evidence_detail_explains_drivers_not_raw_score():
    text = forest_evidence_detail(
        {
            "anomalous": True,
            "model_id": "isolation_forest_v1",
            "forest_score": -0.0531,
            "score_cutoff": 0.0,
            "features": {
                "gap_return": -0.1151,
                "session_return": 0.0021,
                "close_return": -0.1133,
                "volume_zscore": -2.18,
            },
        }
    )
    assert "Marked anomalous:" in text
    assert "gap" in text and "-11.51%" in text
    assert "prior close" in text
    assert "vol z" in text and "-2.18" in text
    assert "far below" in text
    assert "score" not in text.lower()
    assert "cutoff" not in text.lower()
    bits = forest_driver_explanations(
        {
            "gap_return": -0.1151,
            "session_return": 0.0021,
            "close_return": -0.1133,
            "volume_zscore": -2.18,
        }
    )
    assert len(bits) == 2
    assert any(bit.startswith("gap") for bit in bits)
    assert any(bit.startswith("vol z") for bit in bits)


def test_forest_draft_uses_richer_wording_and_sections():
    state = SessionState(
        symbol="AAPL",
        session_day=date(2026, 11, 18),
        open=100.0,
        last=101.0,
        last_ts=datetime(2026, 11, 18, 16, 0, tzinfo=UTC),
        volume=1_000_000,
    )
    draft = forest_price_draft_from_session(
        state,
        _weird_score(
            features={
                "gap_return": 0.01,
                "session_return": 0.01,
                "close_return": 0.02,
                "volume_zscore": 4.0,
            }
        ),
        price_move_threshold=0.03,
        sentiment_threshold=25,
        now=state.last_ts,
        prior_close=99.0,
    )
    assert draft is not None
    assert draft.sections["synthesis"]
    assert draft.sections["price"]
    assert "stayed under" in draft.summary
    assert "What stood out" in draft.summary
    assert draft.summary == draft.sections["synthesis"]


def test_enrich_rewrites_generic_price_synthesis_after_news_check():
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 18),
        headline_id=None,
        price_change_pct=0.01,
        latest_close=101.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="Price led for AAPL: the move cleared the rule, and news was checked with no qualifying headlines.",
        sections={
            "price": "generic percent sentence",
            "news": "No near-term headlines for AAPL cleared the FinBERT gate on this trading day.",
            "synthesis": "Price led for AAPL: the move cleared the rule, and news was checked with no qualifying headlines.",
            "entry": "price",
            "second_supports": False,
            "price_span": "open → last",
            "forest": {
                "model_id": "isolation_forest_v1",
                "forest_score": -0.1,
                "score_cutoff": 0.0,
                "anomalous": True,
                "product_span": "live",
                "session_open": 100.0,
                "session_last": 101.0,
                "features": {
                    "gap_return": 0.01,
                    "session_return": 0.01,
                    "close_return": 0.02,
                    "volume_zscore": 4.0,
                },
            },
        },
        triggered_at=datetime(2026, 11, 18, 16, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
        origin="live",
    )
    out = enrich_price_draft_with_forest_wording(draft)
    assert "Isolation Forest" in out.summary
    assert "stayed under" in out.summary
    assert "no qualifying headlines" in out.summary.lower()
    assert "generic percent sentence" not in out.sections["price"]
    assert "anomalous" in out.sections["price"].lower()


def test_enrich_news_price_keeps_together_text_but_updates_price_section():
    day = date(2026, 11, 18)
    draft = AlertDraft(
        kind="news_price",
        symbol="AAPL",
        bar_date=day,
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=70.0,
        headline_title="Apple rises",
        summary="Perplexity together text stays",
        sections={
            "synthesis": "Perplexity together text stays",
            "price": "old price",
            "entry": "price",
            "second_supports": True,
            "forest": {
                "model_id": "isolation_forest_v1",
                "forest_score": -0.2,
                "score_cutoff": 0.0,
                "anomalous": True,
                "features": {
                    "gap_return": 0.01,
                    "session_return": 0.04,
                    "close_return": 0.05,
                    "volume_zscore": 2.0,
                },
                "session_open": 100.0,
                "session_last": 104.0,
            },
        },
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    out = enrich_price_draft_with_forest_wording(draft)
    assert out.summary == "Perplexity together text stays"
    assert "Isolation Forest" in out.sections["price"]
    assert "also cleared" in out.sections["price"] or "cleared the 3.0%" in out.sections["price"]


def test_evidence_price_noticed_is_forest_aware_when_under_percent():
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 18),
        headline_id=None,
        price_change_pct=0.01,
        latest_close=101.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="forest",
        sections={
            "entry": "price",
            "second_supports": False,
            "forest": {
                "model_id": "isolation_forest_v1",
                "forest_score": -0.1,
                "score_cutoff": 0.0,
                "anomalous": True,
                "features": {
                    "gap_return": 0.05,
                    "session_return": 0.01,
                    "close_return": 0.06,
                    "volume_zscore": 4.0,
                },
            },
        },
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    story = attach_evidence_story(draft).sections["evidence"]
    price_step = next(step for step in story["steps"] if step["id"] == "price_noticed")
    details = price_step["details"]
    assert "stayed under the 3.0% percent rule" in details[0]
    assert details[0].endswith("(not volatile).")
    assert any("vol z" in line or "gap" in line for line in details[1:])
    assert "score -0.1" not in price_step["detail"]
    assert "cleared the product gate" not in price_step["detail"]
