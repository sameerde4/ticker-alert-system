"""Keyword headline sentiment.

Local copy of the weighted lexicon and negation window. This repository does not
import Vajra Astra Capital. Scores are in [-1, 1].
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# Number of matched keywords required to reach full-confidence (|score| = 1.0).
# Articles with fewer matches are scaled down proportionally so that a single
# stray keyword in a long body doesn't force a false ±1.00.
_MIN_HITS_FOR_FULL_CONFIDENCE = 3

# Weighted financial lexicon (signed). Stronger words get |weight| > 1 for granularity.
_SENTIMENT_WEIGHTS: dict[str, float] = {
    # Positive
    "beat": 1.0,
    "beats": 1.0,
    "surge": 2.0,
    "surges": 2.0,
    "soar": 2.0,
    "soars": 2.0,
    "rally": 1.5,
    "rallies": 1.5,
    "growth": 1.0,
    "upgrade": 1.5,
    "upgraded": 1.5,
    "record": 1.0,
    "strong": 1.0,
    "profit": 1.0,
    "profits": 1.0,
    "buy": 1.0,
    "buys": 1.0,
    "bought": 0.5,
    "outperform": 1.5,
    "outperforms": 1.5,
    "raises": 1.0,
    "raised": 1.0,
    "bullish": 1.5,
    "gain": 1.0,
    "gains": 1.0,
    "jump": 1.5,
    "jumps": 1.5,
    "boom": 1.5,
    "optimistic": 1.0,
    "exceeds": 1.5,
    "exceeded": 1.5,
    # Negative
    "miss": -1.0,
    "misses": -1.0,
    "missed": -1.0,
    "cut": -1.0,
    "cuts": -1.0,
    "downgrade": -1.5,
    "downgraded": -1.5,
    "loss": -1.0,
    "losses": -1.0,
    "weak": -1.0,
    "fall": -1.0,
    "falls": -1.0,
    "drop": -1.0,
    "drops": -1.0,
    "plunge": -2.0,
    "plunges": -2.0,
    "slump": -1.5,
    "slumps": -1.5,
    "crash": -2.0,
    "crashes": -2.0,
    "lawsuit": -1.5,
    "probe": -1.5,
    "investigation": -1.5,
    "recall": -1.5,
    "bearish": -1.5,
    "warning": -1.0,
    "warns": -1.0,
    "warned": -1.0,
    "decline": -1.0,
    "declines": -1.0,
    "sink": -1.5,
    "sinks": -1.5,
    "sank": -1.5,
    "sunk": -1.5,
    "tumble": -1.5,
    "tumbles": -1.5,
    "dip": -1.0,
    "dips": -1.0,
    "dipped": -1.0,
    "slid": -1.0,
    "slide": -1.0,
    "slides": -1.0,
    "sliding": -1.0,
    "selloff": -1.5,
    "sold": -0.5,
    "layoff": -1.5,
    "layoffs": -1.5,
    "fraud": -2.0,
    "bankruptcy": -2.0,
}

# Cleaned expansion: 77 single-word terms, zero collisions with the
# base _SENTIMENT_WEIGHTS dict above. Multi-word phrases from an earlier
# draft were either dropped (ambiguous / not whitespace-matchable, e.g.
# "chapter_11", "sec_investigation") or merged into a single-word
# equivalent (e.g. "dividend_suspended" -> "suspended").
_SENTIMENT_WEIGHTS_EXPANSION: dict[str, float] = {
    # --- Guidance / outlook ---
    "reaffirms": 0.5,
    "reaffirmed": 0.5,
    "withdraws": -1.5,
    "withdrew": -1.5,
    "tops": 1.0,
    "topped": 1.0,
    "shortfall": -1.5,
    "underperform": -1.5,
    "underperforms": -1.5,

    # --- M&A / corporate actions ---
    "acquires": 1.0,
    "acquisition": 0.5,
    "merger": 0.5,
    "buyout": 1.0,
    "takeover": 0.5,
    "divests": 0.5,
    "divestiture": 0.0,
    "spinoff": 0.5,
    "spinoffs": 0.5,
    "ipo": 0.5,
    "buyback": 1.5,
    "buybacks": 1.5,
    "dividend": 1.0,
    "dividends": 1.0,
    "suspended": -1.5,

    # --- Credit / ratings / solvency ---
    "junk": -1.5,
    "default": -2.0,
    "defaults": -2.0,
    "insolvency": -2.0,
    "insolvent": -2.0,
    "restructuring": -1.0,
    "delisted": -2.0,
    "delisting": -2.0,

    # --- Macro ---
    "tariff": -1.0,
    "tariffs": -1.0,
    "sanctions": -1.5,
    "inflation": -0.5,
    "recession": -1.5,
    "stimulus": 1.0,

    # --- Short-selling / activism ---
    "shortseller": -1.5,
    "squeeze": 1.5,
    "activist": 0.5,
    "proxy": -0.5,
    "hostile": -0.5,

    # --- Governance ---
    "resigns": -1.0,
    "resignation": -1.0,
    "ousted": -1.5,
    "fired": -1.5,
    "appointed": 0.5,
    "interim": -0.5,

    # --- Legal / regulatory / cyber ---
    "settlement": -0.5,
    "settles": -0.5,
    "subpoena": -1.5,
    "antitrust": -1.0,
    "monopoly": -1.0,
    "breach": -1.5,
    "hack": -1.5,
    "hacked": -1.5,
    "cyberattack": -1.5,
    "fined": -1.5,
    "fine": -1.0,
    "penalty": -1.0,
    "violation": -1.0,
    "restatement": -2.0,
    "restates": -2.0,

    # --- Supply chain / labor ---
    "strike": -1.5,
    "shortage": -1.0,
    "shutdown": -1.5,
    "halted": -1.5,
    "delays": -1.0,
    "delayed": -1.0,

    # --- Product / demand ---
    "launch": 0.5,
    "launches": 0.5,
    "expands": 1.0,
    "expansion": 1.0,
    "partnership": 0.5,

    # --- Misc ---
    "dilution": -1.0,
    "diluted": -1.0,
}
_SENTIMENT_WEIGHTS.update(_SENTIMENT_WEIGHTS_EXPANSION)

_NEGATION_TOKENS = frozenset({"not", "no", "without", "never", "neither", "nor"})
_NEGATION_WINDOW = 3
def score_sentiment(text: str) -> float:
    """Public wrapper around the keyword scorer."""
    return _simple_sentiment(text)


def _parse_pub_date(raw: str | float | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().replace(".", "", 1).isdigit()):
        try:
            ts = float(raw)
            # Yahoo Search uses seconds; some feeds send milliseconds.
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC)
        except (ValueError, OSError, OverflowError):
            if not isinstance(raw, str):
                return None
    if not str(raw).strip():
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _is_negation_token(token: str) -> bool:
    return token in _NEGATION_TOKENS or token.endswith("n't")


def _keyword_negated(tokens: list[str], index: int) -> bool:
    """True if a negation appears within the lookback window before ``index``."""
    start = max(0, index - _NEGATION_WINDOW)
    return any(_is_negation_token(tokens[j]) for j in range(start, index))


def _simple_sentiment(text: str) -> float:
    """Weighted keyword sentiment in [-1, 1] for headline/body text.

    - Lexicon entries carry signed weights (e.g. plunge=-2, miss=-1).
    - The raw score is normalized by the number of MATCHED keywords, not
      total token count, so a strong headline signal isn't diluted by a
      long, mostly-neutral article body.
    - A confidence multiplier (hits / _MIN_HITS_FOR_FULL_CONFIDENCE,
      capped at 1.0) then dampens articles with very few keyword hits, so
      a single stray word doesn't force a false ±1.00 on an otherwise
      neutral or mixed story. Articles with 3+ matched keywords can reach
      full-strength ±1.00; 1-hit articles cap out around ±0.33.
    - A small negation window flips keyword polarity (not/no/without/n't).
    """
    tokens = re.findall(r"[a-z']+", (text or "").lower())
    if not tokens:
        return 0.0
    signed = 0.0
    hits = 0
    for i, token in enumerate(tokens):
        weight = _SENTIMENT_WEIGHTS.get(token)
        if weight is None:
            continue
        hits += 1
        if _keyword_negated(tokens, i):
            weight = -weight
        signed += weight
    if hits == 0 or signed == 0.0:
        return 0.0
    raw_score = signed / hits
    confidence = min(1.0, hits / _MIN_HITS_FOR_FULL_CONFIDENCE)
    score = raw_score * confidence
    return max(-1.0, min(1.0, float(score)))


def sentiment_matches(text: str) -> list[tuple[str, float]]:
    """Lexicon hits as (token, signed weight), in headline order. Negation flips the sign."""
    tokens = re.findall(r"[a-z']+", (text or "").lower())
    found: list[tuple[str, float]] = []
    for index, token in enumerate(tokens):
        weight = _SENTIMENT_WEIGHTS.get(token)
        if weight is None:
            continue
        if _keyword_negated(tokens, index):
            weight = -weight
        found.append((token, weight))
    return found


def explain_matches(text: str, *, limit: int = 3) -> str:
    """Short reason naming the strongest matched words."""
    found = sentiment_matches(text)
    if not found:
        return "no lexicon keywords were matched"
    ranked = sorted(found, key=lambda pair: abs(pair[1]), reverse=True)[:limit]
    bits = []
    for token, weight in ranked:
        side = "positive" if weight > 0 else "negative"
        bits.append(f'"{token}" ({side})')
    return "matched " + ", ".join(bits)
