from datetime import date

from app.engine import AlertDraft
from app.evidence import (
    ALIGNMENT_CONTRADICTS,
    ALIGNMENT_LEANS,
    ALIGNMENT_NEUTRAL,
    ALIGNMENT_SUPPORTS,
    attach_evidence_story,
    build_evidence_story,
    price_trigger_note,
    _forest_feature_case_tags,
    _price_gate_case,
)
from app.live_upgrade import should_write_live_alert


def _draft(**kwargs):
    base = dict(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 19),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="AAPL moved +4.00% from the open.",
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
    )
    base.update(kwargs)
    return AlertDraft(**base)


def test_evidence_aligned_price_entry():
    draft = _draft(
        kind="news_price",
        sentiment_score=20.0,
        articles=({"title": "Cuts outlook", "sentiment_score": 20.0},),
        summary="Together text",
        sections={
            "price": "p",
            "news": "n",
            "synthesis": "s",
            "entry": "price",
            "second_supports": True,
        },
    )
    story = build_evidence_story(draft)
    assert "supports the move" in story["headline"]
    assert story["alignment"] == ALIGNMENT_SUPPORTS
    assert story["steps"][-1]["ok"] is True
    assert story["steps"][-1]["tone"] == "ok"
    assert story["steps"][0]["id"] == "price_noticed"


def test_evidence_price_led_news_tone_leans_same_direction():
    draft = _draft(
        price_change_pct=-0.04,
        sentiment_score=20.0,
        articles=({"title": "Cuts outlook", "sentiment_score": 20.0},),
        sections={
            "price": "price text",
            "news": "news text",
            "entry": "price",
            "second_supports": False,
        },
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_LEANS
    assert "somewhat supports" in story["headline"]
    assert story["steps"][-1]["tone"] == "partial"
    assert "exact price slice" in story["steps"][-1]["detail"]


def test_evidence_price_led_news_contradicts_direction():
    draft = _draft(
        price_change_pct=-0.04,
        sentiment_score=80.0,
        articles=({"title": "Beats estimates", "sentiment_score": 80.0},),
        sections={
            "entry": "price",
            "second_supports": False,
        },
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_CONTRADICTS
    assert "contradicts" in story["headline"]
    assert story["steps"][-1]["tone"] == "no"


def test_evidence_price_led_no_news_is_neutral():
    draft = _draft(
        sections={
            "entry": "price",
            "second_supports": False,
        }
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_NEUTRAL
    assert "no news evidence" in story["headline"]
    assert story["steps"][-1]["ok"] is False


def test_evidence_news_led_price_somewhat_supports_same_direction():
    draft = _draft(
        kind="news",
        price_change_pct=None,
        latest_close=None,
        prior_close=None,
        sentiment_score=18.0,
        articles=({"title": "Probe opens", "sentiment_score": 18.0},),
        summary="News summary",
        sections={
            "price": (
                "LLY price was checked against today's session. The observed move was "
                "down -2.30%, under the 3.0% rule."
            ),
            "news": "News text",
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": -0.023,
        },
    )
    story = build_evidence_story(draft)
    assert story["steps"][0]["id"] == "news_checked"
    assert story["steps"][1]["id"] == "price_checked"
    # Step 2 is measurement only — no duplicated verdict language.
    assert "does not support" not in story["steps"][1]["detail"]
    assert "does not line up" not in story["steps"][1]["detail"]
    assert "under the 3.0% rule" in story["steps"][1]["detail"]
    assert "(neither gate)" in story["steps"][1]["detail"]
    assert story["alignment"] == ALIGNMENT_LEANS
    assert "somewhat supports" in story["steps"][-1]["label"].lower()
    assert story["steps"][-1]["detail"] != story["steps"][1]["detail"]


def test_evidence_news_led_price_contradicts():
    draft = _draft(
        kind="news",
        price_change_pct=None,
        sentiment_score=15.0,
        articles=({"title": "Probe opens", "sentiment_score": 15.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.02,
        },
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_CONTRADICTS
    assert "contradicts" in story["headline"]


def test_evidence_news_led_price_soft_disagreement():
    from app.evidence import ALIGNMENT_LEANS_AGAINST

    draft = _draft(
        kind="news",
        price_change_pct=None,
        sentiment_score=15.0,
        articles=({"title": "Probe opens", "sentiment_score": 15.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.01,
        },
        price_move_threshold=0.03,
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_LEANS_AGAINST
    assert "somewhat disagrees" in story["steps"][-1]["label"].lower()
    assert story["steps"][1]["detail"] != story["steps"][-1]["detail"]


def test_evidence_news_led_full_price_support():
    draft = _draft(
        kind="news_price",
        price_change_pct=-0.04,
        sentiment_score=18.0,
        articles=({"title": "Probe opens", "sentiment_score": 18.0},),
        sections={
            "entry": "news",
            "second_supports": True,
        },
        price_move_threshold=0.03,
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_SUPPORTS
    assert story["steps"][0]["id"] == "news_checked"
    assert "supports the news" in story["headline"]


def test_attach_evidence_preserves_other_sections():
    draft = _draft(
        sections={"forest": {"anomalous": True}, "price": "p", "entry": "price", "second_supports": False}
    )
    out = attach_evidence_story(draft)
    assert out.sections["forest"]["anomalous"] is True
    assert "evidence" in out.sections
    assert out.sections["evidence"]["alignment"]


def test_price_checked_tags_percent_only():
    draft = _draft(
        price_change_pct=0.04,
        sections={"entry": "price", "second_supports": False},
    )
    story = build_evidence_story(draft)
    detail = story["steps"][0]["detail"]
    assert "(percent only)" in detail
    assert "[triggers: #1 percent]" in detail
    assert story["price_triggers"] == "triggers: #1 percent"
    assert "cleared the 3.0% percent rule" in detail or "cleared the 3.0% rule" in detail


def test_price_checked_tags_percent_plus_forest():
    draft = _draft(
        price_change_pct=0.04,
        sections={
            "entry": "price",
            "second_supports": False,
            "forest": {
                "anomalous": True,
                "model_id": "isolation_forest_v1",
                "forest_score": -0.1,
                "score_cutoff": 0.0,
                "features": {
                    "gap_return": 0.01,
                    "session_return": 0.04,
                    "close_return": 0.05,
                    "volume_zscore": 1.0,
                },
            },
        },
    )
    story = build_evidence_story(draft)
    detail = story["steps"][0]["detail"]
    assert "(percent + forest)" in detail
    assert "#1 percent" in detail
    assert "#2 forest" in detail
    assert story["price_gate"] == "percent + forest"


def test_price_checked_tags_forest_only():
    draft = _draft(
        price_change_pct=0.01,
        sections={
            "entry": "price",
            "second_supports": False,
            "forest": {
                "anomalous": True,
                "model_id": "isolation_forest_v1",
                "forest_score": -0.2,
                "score_cutoff": 0.0,
                "features": {
                    "gap_return": 0.05,
                    "session_return": 0.01,
                    "close_return": 0.06,
                    "volume_zscore": 4.0,
                },
            },
        },
    )
    detail = build_evidence_story(draft)["steps"][0]["detail"]
    assert "(forest only)" in detail
    assert "stayed under" in detail
    assert "#2 forest" in detail
    assert "#6 volume z" in detail or "#3 gap" in detail


def test_price_checked_notes_volume_spike_as_case_7():
    draft = _draft(
        price_change_pct=0.04,
        volume_spike=True,
        sections={"entry": "price", "second_supports": False},
    )
    detail = build_evidence_story(draft)["steps"][0]["detail"]
    assert "#1 percent" in detail
    assert "#7 volume spike noted" in detail


def test_news_led_price_checked_tags_neither_when_under_and_forest_normal():
    draft = _draft(
        kind="news",
        price_change_pct=None,
        sentiment_score=80.0,
        articles=({"title": "Beats", "sentiment_score": 80.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.012,
            "forest": {"anomalous": False, "model_id": "isolation_forest_v1"},
        },
    )
    story = build_evidence_story(draft)
    detail = story["steps"][1]["detail"]
    assert "(neither gate)" in detail
    assert "stayed under the 3.0% rule" in detail
    assert "triggers: none (price under both gates)" in detail


def test_news_led_price_checked_tags_forest_only_when_under_but_anomalous():
    draft = _draft(
        kind="news",
        price_change_pct=None,
        sentiment_score=80.0,
        articles=({"title": "Beats", "sentiment_score": 80.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.012,
            "forest": {
                "anomalous": True,
                "model_id": "isolation_forest_v1",
                "forest_score": -0.2,
                "score_cutoff": 0.0,
                "features": {
                    "gap_return": 0.05,
                    "session_return": 0.01,
                    "close_return": 0.06,
                    "volume_zscore": 4.0,
                },
            },
        },
    )
    detail = build_evidence_story(draft)["steps"][1]["detail"]
    assert "(forest only)" in detail
    assert "#2 forest" in detail


def test_should_write_live_alert_upgrade_rules():
    price = _draft(kind="price")
    news_price = _draft(kind="news_price", sentiment_score=20.0)
    assert should_write_live_alert(None, price)
    assert should_write_live_alert({"kind": "price"}, news_price)
    assert should_write_live_alert({"kind": "price"}, price)
    assert not should_write_live_alert({"kind": "news"}, price)
    assert should_write_live_alert({"kind": "news_price"}, news_price)


def test_price_gate_case_matrix():
    assert _price_gate_case(percent_cleared=True, forest_anomalous=False) == "(percent only)"
    assert _price_gate_case(percent_cleared=True, forest_anomalous=True) == "(percent + forest)"
    assert _price_gate_case(percent_cleared=False, forest_anomalous=True) == "(forest only)"
    assert _price_gate_case(percent_cleared=False, forest_anomalous=False) == "(neither gate)"
    assert _price_gate_case(percent_cleared=None, forest_anomalous=False) == "(neither gate)"


def test_forest_feature_case_tags_rank_loudest():
    tags = _forest_feature_case_tags(
        {
            "gap_return": 0.01,
            "session_return": 0.02,
            "close_return": 0.08,
            "volume_zscore": 5.0,
        }
    )
    assert tags[0] == "#5 close" or tags[0] == "#6 volume z"
    assert len(tags) <= 2
    assert _forest_feature_case_tags(None) == []
    assert _forest_feature_case_tags({}) == []


def test_price_trigger_note_combines_cases():
    draft = _draft(volume_spike=True)
    forest = {
        "anomalous": True,
        "features": {
            "gap_return": 0.06,
            "session_return": 0.01,
            "close_return": 0.02,
            "volume_zscore": 3.0,
        },
    }
    note = price_trigger_note(
        draft, forest, percent_cleared=True, forest_anomalous=True
    )
    assert note.startswith("triggers:")
    assert "#1 percent" in note
    assert "#2 forest" in note
    assert "#7 volume spike noted" in note
    none = price_trigger_note(
        _draft(volume_spike=False),
        {"anomalous": False},
        percent_cleared=False,
        forest_anomalous=False,
    )
    assert none == "triggers: none (price under both gates)"
