"""Price, news, and fusion alert rules.

The rules run on stored daily bars and scored headlines. They do not call a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .sentiment import explain_matches


@dataclass(frozen=True)
class AlertDraft:
    kind: str
    symbol: str
    bar_date: date | None
    headline_id: str | None
    price_change_pct: float | None
    latest_close: float | None
    prior_close: float | None
    volume_ratio: float | None
    volume_spike: bool
    sentiment_score: float | None
    headline_title: str | None
    summary: str
    articles: tuple[dict[str, Any], ...] = ()
    sections: dict[str, str] = field(default_factory=dict)
    triggered_at: datetime | None = None
    price_move_threshold: float | None = None
    sentiment_threshold: float | None = None


EASTERN = ZoneInfo("America/New_York")


def price_change_pct(latest_close: float | None, prior_close: float | None) -> float | None:
    if latest_close is None or prior_close is None:
        return None
    if latest_close <= 0 or prior_close <= 0:
        return None
    return (latest_close - prior_close) / prior_close


def volume_ratio(latest_volume: float | None, prior_volumes: list[float | None]) -> float | None:
    vals = [float(v) for v in prior_volumes if v is not None and float(v) > 0]
    if latest_volume is None or float(latest_volume) <= 0 or not vals:
        return None
    avg = sum(vals) / len(vals)
    if avg <= 0:
        return None
    return float(latest_volume) / avg


def eastern_date(moment: datetime) -> date:
    """Calendar date on the US East Coast."""
    return _as_utc(moment).astimezone(EASTERN).date()


def session_close(bar_date: date) -> datetime:
    """US cash-session close on the East Coast. Daily bars do not carry an intraday tick."""
    return datetime.combine(bar_date, time(16, 0), tzinfo=EASTERN)


def cash_session_open(now: datetime) -> bool:
    """True from 9:30 AM to 4:00 PM Eastern on a weekday."""
    moment = _as_utc(now).astimezone(EASTERN)
    if moment.weekday() >= 5:
        return False
    clock = moment.timetz().replace(tzinfo=None)
    return time(9, 30) <= clock < time(16, 0)


def headline_price_slice(published: datetime) -> str:
    """Which part of the session a stock headline can explain.

    Before 9:30 AM Eastern the story can explain the overnight gap. From 9:30 to
    4:00 PM it can explain the regular session. After the close, and on the weekend,
    it can explain that session's close versus the prior close.
    """
    local = _as_utc(published).astimezone(EASTERN)
    if local.weekday() >= 5:
        return "close"
    if local.time() < time(9, 30):
        return "gap"
    if local.time() < time(16, 0):
        return "session"
    return "close"


SLICE_LABEL = {
    "gap": "the overnight gap, from the prior close to the open",
    "session": "the regular session, from the open to the 4:00 PM close",
    "close": "the close versus the prior close",
    "headline": "the four hours after the headline",
    "live": "the regular session so far, from the open to the latest price",
}


def move_after_headline(
    points: list[tuple[datetime, float]],
    published: datetime,
    now: datetime,
    *,
    hours: int = 4,
) -> tuple[float, float, float, datetime] | None:
    """Price change from the print at a headline to the print up to four hours later."""
    start_at = _as_utc(published)
    end_limit = min(_as_utc(now), start_at + timedelta(hours=hours))
    usable: list[tuple[datetime, float]] = []
    for stamp, price in points:
        when = _as_utc(stamp)
        if when <= end_limit and price > 0:
            usable.append((when, float(price)))
    if not usable:
        return None
    earlier = [item for item in usable if item[0] <= start_at]
    if not earlier:
        return None
    start_stamp, start_px = max(earlier, key=lambda item: item[0])
    later = [item for item in usable if item[0] >= start_stamp + timedelta(minutes=30)]
    if not later:
        return None
    end_stamp, end_px = max(later, key=lambda item: item[0])
    change = price_change_pct(end_px, start_px)
    if change is None:
        return None
    return change, end_px, start_px, end_stamp


def headline_session(published: datetime) -> date:
    """Trading day a headline belongs to, from its US Eastern publish time.

    A story published on a weekday belongs to that calendar day, including premarket.
    A weekend story belongs to the Friday session it is recapping. It does not
    travel onto the next session's price move.
    """
    day = _as_utc(published).astimezone(EASTERN).date()
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day - timedelta(days=2)
    return day


def earliest_published(items: list[dict[str, Any]]) -> datetime:
    return min(_as_utc(item["published_at"]) for item in items)


def condition_met_at(
    *,
    kind: str,
    bar_date: date,
    headlines: list[dict[str, Any]] | None = None,
) -> datetime:
    """When the rule became true in the data, not when a person ran the check.

    A price move is known at the 4:00 PM Eastern close. A news alert is known at the
    earliest qualifying headline. Both are known at the later of those two times.
    """
    if kind == "price":
        return session_close(bar_date)
    published = earliest_published(headlines or [])
    if kind == "news":
        return published
    return max(session_close(bar_date), published)


def _fmt_pct(value: float) -> str:
    points = value * 100
    sign = "+" if points > 0 else ""
    return f"{sign}{points:.2f}%"


def _direction(value: float) -> str:
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def combined_sentiment(scores: list[float]) -> float:
    if not scores:
        return 50.0
    return sum(scores) / len(scores)


def _tone(score: float) -> str:
    if score >= 57.5:
        return "bullish"
    if score <= 42.5:
        return "bearish"
    return "mixed"


def _score(value: float) -> str:
    return f"{value:.0f}/100"


def article_view(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    body = item.get("body") or ""
    published = item.get("published_at")
    if isinstance(published, datetime):
        published = published.isoformat()
    return {
        "title": title,
        "url": item.get("url"),
        "source": item.get("source"),
        "published_at": published,
        "sentiment_score": float(item["sentiment_score"]),
        "confidence": item.get("confidence"),
        "positive_pct": item.get("positive_pct"),
        "negative_pct": item.get("negative_pct"),
        "neutral_pct": item.get("neutral_pct"),
        "reason": item.get("reason") or explain_matches(f"{title} {body}"),
    }


def price_summary(
    symbol: str,
    change: float,
    latest_close: float,
    prior_close: float,
    ratio: float | None,
    spiked: bool,
    *,
    price_move_threshold: float,
    volume_spike_threshold: float,
    trailing_24h: bool = False,
    from_open: bool = False,
    move_label: str | None = None,
) -> str:
    if move_label:
        comparison = (
            f"{symbol} moved {_direction(change)} {_fmt_pct(change)}, "
            f"from {_money(prior_close)} to {_money(latest_close)}, over {move_label}. "
            f"This fired because the move is at or beyond the {price_move_threshold * 100:.1f}% rule."
        )
    elif trailing_24h:
        comparison = (
            f"{symbol} is at {_money(latest_close)}, {_direction(change)} {_fmt_pct(change)} "
            f"from {_money(prior_close)} 24 hours before this check. "
            f"This fired because the move is at or beyond the {price_move_threshold * 100:.1f}% rule "
            "over the last 24 hours."
        )
    elif from_open:
        comparison = (
            f"{symbol} is at {_money(latest_close)}, {_direction(change)} {_fmt_pct(change)} "
            f"from the open of {_money(prior_close)}. "
            f"This fired because the move is at or beyond the {price_move_threshold * 100:.1f}% rule "
            "from the open while the market is open."
        )
        return comparison + " The volume spike is measured at the close."
    else:
        comparison = (
            f"{symbol} closed at {_money(latest_close)}, {_direction(change)} {_fmt_pct(change)} "
            f"from the prior close of {_money(prior_close)}. "
            f"This fired because the move is at or beyond the {price_move_threshold * 100:.1f}% rule "
            "versus the prior close."
        )
    if move_label:
        return comparison
    if trailing_24h:
        return comparison + " Volume uses the cash-session average, so the spike rule was not applied."
    if ratio is None:
        return comparison + " Volume was not available, so the spike rule was not applied."
    if spiked:
        volume = (
            f" Volume was {ratio:.2f}x the recent average, which also clears the "
            f"{volume_spike_threshold:.1f}x spike rule."
        )
    else:
        volume = (
            f" Volume was {ratio:.2f}x the recent average, under the "
            f"{volume_spike_threshold:.1f}x spike rule."
        )
    return comparison + volume


def news_summary(
    symbol: str,
    articles: list[dict[str, Any]],
    *,
    sentiment_threshold: float,
    news_lookback_hours: int,
) -> str:
    scores = [float(article["sentiment_score"]) for article in articles]
    combined = combined_sentiment(scores)
    count = len(articles)
    story = "headline" if count == 1 else "headlines"
    text = (
        f"{symbol} news alert covers {count} {story} published on this trading day. "
        f"Each cleared the {sentiment_threshold:.0f}-point distance from 50 on its own. "
        f"Combined sentiment is {_score(combined)} ({_tone(combined)}), the average of the headline scores."
    )
    positive = sum(1 for score in scores if score > 50)
    negative = sum(1 for score in scores if score < 50)
    if positive and negative:
        text += (
            f" The headlines disagree ({positive} positive, {negative} negative), so the average "
            "can sit near 50 even though every story was strong enough to alert."
        )
    elif count > 1:
        text += " The headlines agree in direction."
    return text


def together_summary(symbol: str, change: float, news_score: float, move_label: str) -> str:
    """How a headline sits next to the price slice it can explain."""
    price_side = f"the move was {_direction(change)} {_fmt_pct(change)}"
    news_side = f"news sentiment is {_score(news_score)} ({_tone(news_score)})"
    if change > 0 and news_score > 57.5 or change < 0 and news_score < 42.5:
        relation = "The two sides agree in direction."
    elif change > 0 and news_score < 42.5 or change < 0 and news_score > 57.5:
        relation = "The two sides disagree: the price move and the news tone point in opposite directions."
    else:
        relation = "The news side is mixed, so it does not clearly confirm or contradict the price move."
    return (
        f"Both the price rule and the news rule fired for {symbol}, so this is one news + price alert. "
        f"The headline is a candidate reason for {move_label}. On price, {price_side}. "
        f"On news, {news_side}. {relation}"
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate_symbol(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
    now: datetime,
    price_move_threshold: float,
    volume_spike_threshold: float,
    volume_lookback: int,
    sentiment_threshold: float,
    news_lookback_hours: int,
    fusion_window_hours: int,
    trailing_24h: dict[str, float] | None = None,
    live_session: dict[str, float] | None = None,
) -> list[AlertDraft]:
    """Build the one alert a symbol should show for this check.

    A symbol gets a single row: price, news, or news plus price.
    ``bars`` are daily rows with dt, close, and volume, oldest first.
    ``headlines`` include id, title, source, published_at, and sentiment_score.
    """
    ordered = sorted(bars, key=lambda row: row["dt"])
    price_draft: AlertDraft | None = None
    change: float | None = None
    session_day = eastern_date(now)
    latest_close: float | None = None
    prior_close: float | None = None
    if trailing_24h is not None:
        latest_close = float(trailing_24h["price"])
        prior_close = float(trailing_24h["prior_price"])
        change = price_change_pct(latest_close, prior_close)
        if change is not None and abs(change) >= price_move_threshold:
            price_draft = AlertDraft(
                kind="price",
                symbol=symbol,
                bar_date=session_day,
                headline_id=None,
                price_change_pct=change,
                latest_close=latest_close,
                prior_close=prior_close,
                volume_ratio=None,
                volume_spike=False,
                sentiment_score=None,
                headline_title=None,
                summary=price_summary(
                    symbol,
                    change,
                    latest_close,
                    prior_close,
                    None,
                    False,
                    price_move_threshold=price_move_threshold,
                    volume_spike_threshold=volume_spike_threshold,
                    trailing_24h=True,
                ),
                triggered_at=_as_utc(now),
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )
    elif live_session is not None:
        latest_close = float(live_session["price"])
        prior_close = float(live_session["open"])
        change = price_change_pct(latest_close, prior_close)
        if change is not None and abs(change) >= price_move_threshold:
            price_draft = AlertDraft(
                kind="price",
                symbol=symbol,
                bar_date=session_day,
                headline_id=None,
                price_change_pct=change,
                latest_close=latest_close,
                prior_close=prior_close,
                volume_ratio=None,
                volume_spike=False,
                sentiment_score=None,
                headline_title=None,
                summary=price_summary(
                    symbol,
                    change,
                    latest_close,
                    prior_close,
                    None,
                    False,
                    price_move_threshold=price_move_threshold,
                    volume_spike_threshold=volume_spike_threshold,
                    from_open=True,
                ),
                triggered_at=_as_utc(now),
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )
    elif len(ordered) >= 2:
        latest = ordered[-1]
        prior = ordered[-2]
        change = price_change_pct(float(latest["close"]), float(prior["close"]))
        lookback = ordered[-(volume_lookback + 1) : -1]
        ratio = volume_ratio(latest.get("volume"), [row.get("volume") for row in lookback])
        spiked = ratio is not None and ratio >= volume_spike_threshold
        # Only today's session can open or replace a price alert. An older close stays as it was saved.
        if (
            change is not None
            and latest["dt"] == session_day
            and abs(change) >= price_move_threshold
        ):
            price_draft = AlertDraft(
                kind="price",
                symbol=symbol,
                bar_date=latest["dt"],
                headline_id=None,
                price_change_pct=change,
                latest_close=float(latest["close"]),
                prior_close=float(prior["close"]),
                volume_ratio=ratio,
                volume_spike=spiked,
                sentiment_score=None,
                headline_title=None,
                summary=price_summary(
                    symbol,
                    change,
                    float(latest["close"]),
                    float(prior["close"]),
                    ratio,
                    spiked,
                    price_move_threshold=price_move_threshold,
                    volume_spike_threshold=volume_spike_threshold,
                ),
                triggered_at=session_close(latest["dt"]),
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )

    news_cutoff = _as_utc(now) - timedelta(hours=news_lookback_hours)
    news_items = _qualifying_headlines(
        headlines,
        sentiment_threshold,
        lambda published: published >= news_cutoff and headline_session(published) == session_day,
    )
    measured = _headline_windows(
        news_items,
        ordered=ordered,
        session_day=session_day,
        trailing_24h=trailing_24h,
        live_session=live_session,
        now=now,
    )
    clearing = [row for row in measured if abs(row["change"]) >= price_move_threshold]
    if clearing:
        clearing.sort(key=lambda row: abs(row["change"]), reverse=True)
        chosen_change = clearing[0]["change"]
        chosen_name = clearing[0]["name"]
        matched = [row for row in clearing if row["name"] == chosen_name]
        articles = tuple(article_view(row["item"]) for row in matched)
        news_score = combined_sentiment([article["sentiment_score"] for article in articles])
        move_label = SLICE_LABEL["live"] if live_session is not None and chosen_name == "session" else SLICE_LABEL[chosen_name]
        end_px = matched[0]["end"] if chosen_name != "close" else float(matched[0]["end"])
        start_px = matched[0]["start"]
        # The close slice keeps the daily price write-up, including the volume note.
        if chosen_name == "close" and price_draft is not None:
            price_text = price_draft.summary
            shown_change = price_draft.price_change_pct if price_draft.price_change_pct is not None else chosen_change
            shown_end = price_draft.latest_close if price_draft.latest_close is not None else end_px
            shown_start = price_draft.prior_close if price_draft.prior_close is not None else start_px
            volume_ratio_value = price_draft.volume_ratio
            volume_spike_value = price_draft.volume_spike
        else:
            shown_change = chosen_change
            shown_end = end_px
            shown_start = start_px
            volume_ratio_value = None
            volume_spike_value = False
            price_text = price_summary(
                symbol,
                shown_change,
                shown_end,
                shown_start,
                None,
                False,
                price_move_threshold=price_move_threshold,
                volume_spike_threshold=volume_spike_threshold,
                move_label=move_label,
            )
        news_text = news_summary(
            symbol,
            list(articles),
            sentiment_threshold=sentiment_threshold,
            news_lookback_hours=news_lookback_hours,
        )
        synthesis = together_summary(symbol, shown_change, news_score, move_label)
        left_out = len(news_items) - len(matched)
        if left_out:
            synthesis += (
                f" {left_out} other headline(s) from a different part of the day were left off, "
                "because they line up with a different price."
            )
        known_at = max(row["known_at"] for row in matched)
        return [
            AlertDraft(
                kind="news_price",
                symbol=symbol,
                bar_date=session_day,
                headline_id=None,
                price_change_pct=shown_change,
                latest_close=shown_end,
                prior_close=shown_start,
                volume_ratio=volume_ratio_value,
                volume_spike=volume_spike_value,
                sentiment_score=news_score,
                headline_title=None,
                summary=synthesis,
                articles=articles,
                sections={"price": price_text, "news": news_text, "synthesis": synthesis},
                triggered_at=known_at,
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )
        ]

    if price_draft is not None and news_items:
        articles = tuple(article_view(item) for item in news_items)
        note = " No headline lined up with this move."
        return [
            replace(
                price_draft,
                summary=price_draft.summary + note,
                articles=articles,
            )
        ]
    if price_draft is not None:
        return [price_draft]
    if news_items:
        articles = tuple(article_view(item) for item in news_items)
        news_score = combined_sentiment([article["sentiment_score"] for article in articles])
        return [
            AlertDraft(
                kind="news",
                symbol=symbol,
                bar_date=session_day,
                headline_id=None,
                price_change_pct=None,
                latest_close=None,
                prior_close=None,
                volume_ratio=None,
                volume_spike=False,
                sentiment_score=news_score,
                headline_title=None,
                summary=news_summary(
                    symbol,
                    list(articles),
                    sentiment_threshold=sentiment_threshold,
                    news_lookback_hours=news_lookback_hours,
                ),
                articles=articles,
                triggered_at=earliest_published(news_items),
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )
        ]
    return []


def _headline_windows(
    headlines: list[dict[str, Any]],
    *,
    ordered: list[dict[str, Any]],
    session_day: date,
    trailing_24h: dict[str, Any] | None,
    live_session: dict[str, float] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """One measured price window for each headline that has prices to compare."""
    if live_session is not None:
        moves = _live_slices(ordered, session_day, live_session)
    elif trailing_24h is None:
        moves = _session_slices(ordered, session_day)
    else:
        moves = None
    points = list((trailing_24h or {}).get("points") or [])
    measured = []
    for item in headlines:
        if trailing_24h is not None:
            window = move_after_headline(points, item["published_at"], now)
            if window is None:
                continue
            change, end_px, start_px, known_at = window
            measured.append(
                {
                    "item": item,
                    "name": "headline",
                    "change": change,
                    "end": end_px,
                    "start": start_px,
                    "known_at": known_at,
                }
            )
            continue
        if moves is None:
            continue
        name = headline_price_slice(item["published_at"])
        change, end_px, start_px = moves[name]
        if change is None:
            continue
        bar_date = session_day if live_session is not None else ordered[-1]["dt"]
        if name == "gap":
            known_at = datetime.combine(bar_date, time(9, 30), tzinfo=EASTERN)
        elif live_session is not None and name == "session":
            known_at = now
        else:
            known_at = session_close(bar_date)
        known_at = max(_as_utc(known_at), _as_utc(item["published_at"]))
        measured.append(
            {
                "item": item,
                "name": name,
                "change": change,
                "end": end_px,
                "start": start_px,
                "known_at": known_at,
            }
        )
    return measured


def _live_slices(
    ordered: list[dict[str, Any]], session_day: date, live: dict[str, float]
) -> dict[str, tuple[float | None, float, float]]:
    """Gap from the prior close, and the session so far from the open to the latest price."""
    open_px = float(live["open"])
    last = float(live["price"])
    completed = [row for row in ordered if row["dt"] < session_day]
    prior_px = float(completed[-1]["close"]) if completed else None
    gap = price_change_pct(open_px, prior_px) if prior_px is not None else None
    baseline = prior_px if prior_px is not None else open_px
    return {
        "gap": (gap, open_px, baseline),
        "session": (price_change_pct(last, open_px), last, open_px),
        "close": (None, last, baseline),
    }


def _session_slices(
    ordered: list[dict[str, Any]], session_day: date
) -> dict[str, tuple[float | None, float, float]] | None:
    if len(ordered) < 2 or ordered[-1]["dt"] != session_day:
        return None
    today = ordered[-1]
    prior_px = float(ordered[-2]["close"])
    open_px = float(today.get("open") or today["close"])
    close_px = float(today["close"])
    return {
        "gap": (price_change_pct(open_px, prior_px), open_px, prior_px),
        "session": (price_change_pct(close_px, open_px), close_px, open_px),
        "close": (price_change_pct(close_px, prior_px), close_px, prior_px),
    }


def _qualifying_headlines(headlines, sentiment_threshold: float, in_window) -> list[dict[str, Any]]:
    kept = []
    for item in headlines:
        score = float(item["sentiment_score"])
        if abs(score - 50.0) < sentiment_threshold:
            continue
        if not in_window(_as_utc(item["published_at"])):
            continue
        kept.append(item)
    kept.sort(key=lambda item: _as_utc(item["published_at"]), reverse=True)
    return kept
