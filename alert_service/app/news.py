"""Yahoo headline fetch. Scoring happens later, with the selected scorer."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .sentiment import _parse_pub_date, _strip_html

SOURCE = "yahoo_finance"
_NAME_STOP = frozenset(
    {
        "inc",
        "corp",
        "corporation",
        "company",
        "co",
        "holdings",
        "group",
        "limited",
        "ltd",
        "plc",
        "class",
        "common",
        "stock",
        "shares",
        "the",
    }
)


_NEWS_PAGE = 40
_NEWS_LIMIT = 200


def fetch_headlines(symbol: str, *, count: int = 15, through: date | None = None) -> list[dict[str, Any]]:
    """Return headlines for one symbol. Empty when the vendor returns nothing.

    Quote news is preferred. A headline is kept only when the title names the
    ticker or the company, because Yahoo also tags unrelated market stories.
    ``through`` pages the quote list until a story is on or before that date,
    or until Yahoo has no older page. A live check leaves it unset and takes
    the newest page only.
    """
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("yfinance is not installed. Install requirements first.") from exc

    tokens = company_tokens(symbol, yf)
    if through is None:
        ticker_raw = _safe_ticker_news(yf, symbol, count)
        search_raw = [] if parse_yahoo_news_items(ticker_raw) else _safe_search_news(yf, symbol)
        return choose_headline_items(symbol, ticker_raw, search_raw, mention_tokens=tokens)

    asked = _NEWS_PAGE
    chosen: list[dict[str, Any]] = []
    while asked <= _NEWS_LIMIT:
        ticker_raw = _safe_ticker_news(yf, symbol, asked)
        parsed = parse_yahoo_news_items(ticker_raw)
        if not parsed:
            return choose_headline_items(symbol, [], _safe_search_news(yf, symbol), mention_tokens=tokens)
        chosen = choose_headline_items(symbol, ticker_raw, [], mention_tokens=tokens)
        if not _need_older_headlines(_oldest_session(parsed), through, len(ticker_raw), asked):
            break
        asked += _NEWS_PAGE
    return chosen


def _need_older_headlines(oldest: date | None, through: date, received: int, asked: int) -> bool:
    """True when this page is full and every story is newer than ``through``."""
    if asked >= _NEWS_LIMIT or received < asked or oldest is None:
        return False
    return oldest > through


def _oldest_session(items: list[dict[str, Any]]) -> date | None:
    from .engine import headline_session

    days = [headline_session(item["published_at"]) for item in items if item.get("published_at")]
    return min(days) if days else None


def _safe_ticker_news(yf: Any, symbol: str, count: int) -> list[Any]:
    try:
        return _ticker_news_raw(yf, symbol, count)
    except Exception:
        return []


def _safe_search_news(yf: Any, symbol: str) -> list[Any]:
    try:
        return _search_news_raw(yf, symbol)
    except Exception:
        return []


def company_tokens(symbol: str, yf: Any | None = None) -> set[str]:
    """Ticker plus the first distinctive word of the Yahoo short name."""
    tokens = {symbol.strip().upper()}
    if yf is None:
        return tokens
    name = ""
    try:
        info = yf.Ticker(symbol).info or {}
        name = str(info.get("shortName") or info.get("longName") or "")
    except Exception:
        name = ""
    for word in re.findall(r"[A-Za-z]{3,}", name):
        if word.lower() in _NAME_STOP:
            continue
        tokens.add(word.upper())
        break
    return tokens


def choose_headline_items(
    symbol: str,
    ticker_raw: list[Any] | None,
    search_raw: list[Any] | None,
    *,
    mention_tokens: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Prefer quote news. Every kept headline title must name the ticker or company."""
    tokens = {token.strip().upper() for token in (mention_tokens or set()) if token.strip()}
    tokens.add(symbol.strip().upper())
    scoped = parse_yahoo_news_items(ticker_raw)
    pool = scoped or parse_yahoo_news_items(search_raw)
    return [item for item in pool if _title_mentions(item["title"], tokens)]


def _title_mentions(title: str, tokens: set[str]) -> bool:
    text = title.upper()
    return any(token in text for token in tokens if token)


def _ticker_news_raw(yf: Any, symbol: str, count: int) -> list[Any]:
    ticker = yf.Ticker(symbol)
    get_news = getattr(ticker, "get_news", None)
    if not callable(get_news):
        return list(getattr(ticker, "news", None) or [])
    try:
        raw = get_news(count=count)
    except TypeError:
        raw = get_news()
    return list(raw or [])


def _search_news_raw(yf: Any, symbol: str) -> list[Any]:
    search_cls = getattr(yf, "Search", None)
    if search_cls is None:
        return []
    try:
        search = search_cls(query=symbol, news_count=15)
    except TypeError:
        search = search_cls(symbol)
    return list(getattr(search, "news", None) or [])


def parse_yahoo_news_items(raw: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize yfinance quote-news and search-news payloads."""
    items: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, dict):
            content = entry
        title = str(content.get("title") or "").strip()
        if not title:
            continue
        published_at = _parse_pub_date(
            content.get("pubDate")
            or content.get("displayTime")
            or content.get("providerPublishTime")
            or entry.get("providerPublishTime")
        )
        if published_at is None:
            continue
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        source = (
            str(provider.get("displayName") or provider.get("sourceId") or "").strip()
            or str(content.get("publisher") or entry.get("publisher") or SOURCE).strip()
            or SOURCE
        )
        body = _strip_html(str(content.get("summary") or content.get("description") or ""))
        items.append(
            {
                "title": title[:500],
                "body": body[:4000] if body else None,
                "published_at": published_at,
                "source": source[:120],
                "url": _http_url(content, entry),
            }
        )
    return items


def _http_url(content: dict[str, Any], entry: dict[str, Any]) -> str | None:
    for key in ("canonicalUrl", "clickThroughUrl"):
        nested = content.get(key)
        if isinstance(nested, dict):
            found = _plain_url(nested.get("url"))
            if found:
                return found
        found = _plain_url(nested)
        if found:
            return found
    for key in ("link", "url"):
        found = _plain_url(content.get(key)) or _plain_url(entry.get(key))
        if found:
            return found
    return None


def _plain_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower().startswith(("http://", "https://")):
        return text[:2000]
    return None
