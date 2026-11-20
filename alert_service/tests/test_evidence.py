from datetime import date

from app.engine import AlertDraft
from app.evidence import (
    AGREEMENT_AGREES,
    AGREEMENT_DISAGREES,
    ALIGNMENT_CONTRADICTS,
    ALIGNMENT_LEANS,
    ALIGNMENT_LEANS_AGAINST,
    ALIGNMENT_NEUTRAL,
    ALIGNMENT_SUPPORTS,
    attach_evidence_story,
    build_evidence_story,
    price_trigger_note,
    resolve_direction_agreement,
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
    assert "No near-term headlines were found" in story["steps"][-1]["detail"]
    assert story["agreement"] == "no_news"
    tagged = attach_evidence_story(draft)
    assert tagged.sections["agreement"] == "no_news"


def test_evidence_price_led_below_gate_soft_lean_supports():
    draft = _draft(
        price_change_pct=-0.04,
        sentiment_score=40.0,
        articles=(
            {"title": "Slightly softer guidance tone", "sentiment_score": 42.0},
            {"title": "Peers ease in afternoon", "sentiment_score": 38.0},
        ),
        sections={
            "entry": "price",
            "second_supports": False,
            "news_gate_cleared": False,
        },
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_LEANS
    assert "soft news lean supports" in story["headline"]
    assert "soft evidence only" in story["steps"][1]["detail"] or "climate average" in story["steps"][1]["detail"]
    assert story["agreement"] == AGREEMENT_AGREES
    assert resolve_direction_agreement(draft) == AGREEMENT_AGREES


def test_evidence_price_led_below_gate_soft_lean_disagrees():
    draft = _draft(
        price_change_pct=-0.04,
        sentiment_score=58.0,
        articles=({"title": "Mildly constructive note", "sentiment_score": 58.0},),
        sections={
            "entry": "price",
            "second_supports": False,
            "news_gate_cleared": False,
        },
    )
    story = build_evidence_story(draft)
    assert story["alignment"] == ALIGNMENT_LEANS_AGAINST
    assert "soft news lean disagrees" in story["headline"]
    assert story["agreement"] == AGREEMENT_DISAGREES


def test_evidence_polarized_climate_forces_mixed_direction():
    draft = _draft(
        price_change_pct=-0.04,
        sentiment_score=50.0,
        articles=(
            {"title": "Bull", "sentiment_score": 90.0},
            {"title": "Bear", "sentiment_score": 10.0},
        ),
        sections={
            "entry": "price",
            "second_supports": True,
            "news_gate_cleared": True,
            "news_join_path": "headline",
            "sentiment_split": {
                "positive": 1,
                "negative": 1,
                "neutral": 0,
                "polarized": True,
            },
        },
    )
    assert resolve_direction_agreement(draft) == "mixed"
    story = build_evidence_story(draft)
    assert story["agreement"] == "mixed"


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
    assert "under the 3.0% percent rule" in story["steps"][1]["detail"]
    assert "(not volatile)" in story["steps"][1]["detail"]
    assert story["price_gate"] == "neither gate"
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
    assert "(volatile)" in detail
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
    details = story["steps"][0]["details"]
    assert details[0].endswith("(volatile).")
    assert "(not volatile)" not in details[0]
    assert any("vol z" in line or "close vs prior" in line or "gap" in line for line in details[1:])
    assert "#1 percent" in story["price_triggers"]
    assert "#2 forest" in story["price_triggers"]
    assert story["price_gate"] == "volatile + anomalous"
    assert story.get("price_shape") == "volatile_anomalous"


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
    story = build_evidence_story(draft)
    details = story["steps"][0]["details"]
    assert details[0].endswith("(not volatile).")
    assert "stayed under" in details[0]
    assert any("vol z" in line or "gap" in line for line in details[1:])
    assert "#2 forest" in story["price_triggers"]
    assert "#6 volume z" in story["price_triggers"] or "#3 gap" in story["price_triggers"]


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
    details = story["steps"][1]["details"]
    assert details[0].endswith("(not volatile).") or "(not volatile)" in details[0]
    assert "stayed under the 3.0% percent rule" in details[0]
    assert story["price_gate"] == "neither gate"
    assert "triggers: none (price under both gates)" in story["price_triggers"]


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
    # Forest-anomalous doors are price-first even when the kind chip is news-led.
    story = build_evidence_story(draft)
    assert story["entry"] == "price"
    assert story["steps"][0]["id"] == "price_noticed"
    details = story["steps"][0]["details"]
    assert details[0].endswith("(not volatile).")
    assert any("vol z" in line or "gap" in line for line in details[1:])
    assert "#2 forest" in story["price_triggers"]


def test_live_news_kind_forces_price_first_what_happened():
    draft = _draft(
        kind="news",
        origin="live",
        price_change_pct=None,
        sentiment_score=80.0,
        articles=({"title": "Beats", "sentiment_score": 80.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.0039,
            "forest": {
                "anomalous": True,
                "model_id": "isolation_forest_v1",
                "forest_score": -0.21,
                "score_cutoff": 0.0,
                "features": {
                    "gap_return": -0.0601,
                    "session_return": 0.0015,
                    "close_return": -0.058,
                    "volume_zscore": -4.29,
                },
            },
        },
    )
    story = build_evidence_story(draft)
    assert story["entry"] == "price"
    assert story["headline"].startswith("Price noticed")
    assert [step["id"] for step in story["steps"]][:2] == ["price_noticed", "news_checked"]
    details = story["steps"][0]["details"]
    assert len(details) >= 2
    assert details[0].endswith("(not volatile).")
    assert "(anomalous)" not in details[0]
    assert any("vol z" in line for line in details[1:])
    assert any("gap" in line for line in details[1:])
    out = attach_evidence_story(draft)
    assert out.sections["entry"] == "price"
    assert out.sections["evidence"]["entry"] == "price"


def test_price_noticed_bullets_keep_volatile_separate_from_anomalous():
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
                    "gap_return": 0.02,
                    "session_return": 0.04,
                    "close_return": 0.05,
                    "volume_zscore": 3.0,
                },
            },
        },
    )
    details = build_evidence_story(draft)["steps"][0]["details"]
    assert details[0].endswith("(volatile).")
    assert all("(anomalous)" not in line for line in details)
    assert len(details) >= 2


def test_watchlist_news_without_forest_can_stay_news_first():
    draft = _draft(
        kind="news",
        origin="watchlist",
        price_change_pct=None,
        sentiment_score=80.0,
        articles=({"title": "Beats", "sentiment_score": 80.0},),
        sections={
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.01,
        },
    )
    story = build_evidence_story(draft)
    assert story["entry"] == "news"
    assert story["steps"][0]["id"] == "news_checked"
    assert story["steps"][1]["id"] == "price_checked"
    assert "(not volatile)" in story["steps"][1]["details"][0]


def test_should_write_live_alert_upgrade_rules():
    price = _draft(kind="price")
    live_price = _draft(kind="price", origin="live")
    news_price = _draft(kind="news_price", sentiment_score=20.0)
    assert should_write_live_alert(None, price)
    assert should_write_live_alert({"kind": "price"}, news_price)
    assert should_write_live_alert({"kind": "price"}, price)
    # Watchlist-origin price must not clobber an existing news row.
    assert not should_write_live_alert({"kind": "news"}, price)
    assert should_write_live_alert({"kind": "news_price"}, news_price)
    # Live price drafts must re-enter upgrade so session moves can refresh news_price.
    assert should_write_live_alert({"kind": "news_price", "origin": "live"}, live_price)
    assert should_write_live_alert({"kind": "news", "origin": "live"}, live_price)


def test_price_gate_case_matrix():
    assert _price_gate_case(percent_cleared=True, forest_anomalous=False) == "(volatile)"
    assert _price_gate_case(percent_cleared=True, forest_anomalous=True) == "(volatile + anomalous)"
    assert _price_gate_case(percent_cleared=False, forest_anomalous=True) == "(anomalous)"
    assert _price_gate_case(percent_cleared=False, forest_anomalous=False) == "(neither gate)"
    assert _price_gate_case(percent_cleared=None, forest_anomalous=False) == "(neither gate)"


def test_resolve_price_shape_keys():
    from app.evidence import resolve_price_shape, PRICE_SHAPE_BOTH, PRICE_SHAPE_VOLATILE, PRICE_SHAPE_ANOMALOUS

    assert resolve_price_shape(percent_cleared=True, forest_anomalous=False) == PRICE_SHAPE_VOLATILE
    assert resolve_price_shape(percent_cleared=True, forest_anomalous=True) == PRICE_SHAPE_BOTH
    assert resolve_price_shape(percent_cleared=False, forest_anomalous=True) == PRICE_SHAPE_ANOMALOUS
    assert resolve_price_shape(percent_cleared=False, forest_anomalous=False) is None


def test_resolve_direction_agreement_compares_move_to_sentiment():
    from app.evidence import (
        AGREEMENT_AGREES,
        AGREEMENT_DISAGREES,
        resolve_direction_agreement,
    )

    agrees = attach_evidence_story(
        _draft(kind="news_price", price_change_pct=0.04, sentiment_score=80.0)
    )
    assert agrees.sections["agreement"] == AGREEMENT_AGREES
    assert resolve_direction_agreement(agrees) == AGREEMENT_AGREES

    disagrees = attach_evidence_story(
        _draft(kind="news_price", price_change_pct=-0.04, sentiment_score=80.0)
    )
    assert disagrees.sections["agreement"] == AGREEMENT_DISAGREES
    assert resolve_direction_agreement(disagrees) == AGREEMENT_DISAGREES


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
