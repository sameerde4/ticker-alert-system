"""Price, news, and fusion alert rules.

The rules run on stored daily bars and scored headlines. They do not call a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
        return 0.0
    return sum(scores) / len(scores)


def _tone(score: float) -> str:
    if score >= 0.15:
        return "bullish"
    if score <= -0.15:
        return "bearish"
    return "mixed"


def _score(value: float) -> str:
    return f"{value:+.2f}"


def article_view(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    body = item.get("body") or ""
    return {
        "title": title,
        "url": item.get("url"),
        "source": item.get("source"),
        "sentiment_score": float(item["sentiment_score"]),
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
) -> str:
    sentence = (
        f"{symbol} closed at {_money(latest_close)}, {_direction(change)} {_fmt_pct(change)} "
        f"from the prior close of {_money(prior_close)}. "
        f"This fired because the move is at or beyond the {price_move_threshold * 100:.1f}% rule "
        "versus the prior close."
    )
    if ratio is None:
        return sentence + " Volume was not available, so the spike rule was not applied."
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
    return sentence + volume


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
        f"Each cleared the {sentiment_threshold:.2f} absolute-sentiment rule on its own. "
        f"Combined sentiment is {_score(combined)} ({_tone(combined)}), the average of the headline scores."
    )
    positive = sum(1 for score in scores if score > 0)
    negative = sum(1 for score in scores if score < 0)
    if positive and negative:
        text += (
            f" The headlines disagree ({positive} positive, {negative} negative), so the average "
            "can sit near zero even though every story was strong enough to alert."
        )
    elif count > 1:
        text += " The headlines agree in direction."
    return text


def together_summary(symbol: str, change: float, news_score: float) -> str:
    """How the price move and the news score sit next to each other."""
    price_side = f"the close moved {_direction(change)} {_fmt_pct(change)}"
    news_side = f"news sentiment is {_score(news_score)} ({_tone(news_score)})"
    if change > 0 and news_score > 0.15 or change < 0 and news_score < -0.15:
        relation = "The two sides agree in direction."
    elif change > 0 and news_score < -0.15 or change < 0 and news_score > 0.15:
        relation = "The two sides disagree: the price move and the news tone point in opposite directions."
    else:
        relation = "The news side is mixed, so it does not clearly confirm or contradict the price move."
    return (
        f"Both the price rule and the news rule fired for {symbol}, so this is one news + price alert "
        f"for the day. On price, {price_side}. On news, {news_side}. {relation}"
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
    if len(ordered) >= 2:
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
    session_change = change if ordered and ordered[-1]["dt"] == session_day else None
    news_draft: AlertDraft | None = None
    if news_items:
        articles = tuple(article_view(item) for item in news_items)
        news_score = combined_sentiment([article["sentiment_score"] for article in articles])
        news_draft = AlertDraft(
            kind="news",
            symbol=symbol,
            bar_date=price_draft.bar_date if price_draft else session_day,
            headline_id=None,
            price_change_pct=session_change,
            latest_close=float(ordered[-1]["close"]) if session_change is not None else None,
            prior_close=float(ordered[-2]["close"]) if session_change is not None and len(ordered) >= 2 else None,
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

    if price_draft is not None and news_draft is not None and change is not None:
        synthesis = together_summary(symbol, change, float(news_draft.sentiment_score or 0.0))
        return [
            AlertDraft(
                kind="news_price",
                symbol=symbol,
                bar_date=price_draft.bar_date,
                headline_id=None,
                price_change_pct=price_draft.price_change_pct,
                latest_close=price_draft.latest_close,
                prior_close=price_draft.prior_close,
                volume_ratio=price_draft.volume_ratio,
                volume_spike=price_draft.volume_spike,
                sentiment_score=news_draft.sentiment_score,
                headline_title=None,
                summary=synthesis,
                articles=news_draft.articles,
                sections={
                    "price": price_draft.summary,
                    "news": news_draft.summary,
                    "synthesis": synthesis,
                },
                triggered_at=condition_met_at(
                    kind="news_price",
                    bar_date=price_draft.bar_date,
                    headlines=news_items,
                ),
                price_move_threshold=price_move_threshold,
                sentiment_threshold=sentiment_threshold,
            )
        ]
    if price_draft is not None:
        return [price_draft]
    if news_draft is not None:
        return [news_draft]
    return []


def _qualifying_headlines(headlines, sentiment_threshold: float, in_window) -> list[dict[str, Any]]:
    kept = []
    for item in headlines:
        score = float(item["sentiment_score"])
        if abs(score) < sentiment_threshold:
            continue
        if not in_window(_as_utc(item["published_at"])):
            continue
        kept.append(item)
    kept.sort(key=lambda item: _as_utc(item["published_at"]), reverse=True)
    return kept
