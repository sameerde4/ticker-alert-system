"""Model choices for the Perplexity alert summary.

ChatGPT and Gemini ids are the ones the Perplexity agent accepts. The OpenAI
group uses the same five GPT models under their direct ids, and the call
rewrites those to the Perplexity id.
"""

from __future__ import annotations

DEFAULT_PERPLEXITY_MODEL = "openai/gpt-5.4-mini"

_CHATGPT = (
    ("openai/gpt-5.4-nano", "Economy"),
    ("openai/gpt-5-mini", "Fast"),
    ("openai/gpt-5.4-mini", "Balanced"),
    ("openai/gpt-5.4", "Advanced"),
    ("openai/gpt-5.6-sol", "Premium"),
)
_OPENAI = (
    ("gpt-5.4-nano", "Economy"),
    ("gpt-5-mini", "Fast"),
    ("gpt-5.4-mini", "Balanced"),
    ("gpt-5.4", "Advanced"),
    ("gpt-5.6-sol", "Premium"),
)
_GEMINI = (
    ("google/gemini-3.5-flash-lite", "Economy"),
    ("google/gemini-3.7-flash", "Fast"),
    ("google/gemini-3.6-flash", "Balanced"),
    ("google/gemini-3.5-flash", "Advanced"),
    ("google/gemini-3.1-pro-preview", "Premium"),
)

_OPENAI_TO_PERPLEXITY = {model_id: f"openai/{model_id}" for model_id, _label in _OPENAI}
_CHOICES = {model_id for model_id, _label in (*_CHATGPT, *_OPENAI, *_GEMINI)}
_ACCEPTED = {model_id for model_id, _label in (*_CHATGPT, *_GEMINI)} | set(_OPENAI_TO_PERPLEXITY.values())


def model_groups() -> list[dict[str, object]]:
    return [
        {"group": "ChatGPT", "models": [_option(model_id, tier) for model_id, tier in _CHATGPT]},
        {"group": "OpenAI", "models": [_option(model_id, tier) for model_id, tier in _OPENAI]},
        {"group": "Gemini", "models": [_option(model_id, tier) for model_id, tier in _GEMINI]},
    ]


def known_model(model_id: str | None) -> str:
    """Keep a dropdown value. An unknown choice falls back to the balanced ChatGPT model."""
    pick = str(model_id or "").strip()
    if pick in _CHOICES:
        return pick
    return DEFAULT_PERPLEXITY_MODEL


def model_label(model_id: str | None) -> str:
    """Dropdown label for the model that wrote an alert, including its group."""
    pick = known_model(model_id)
    for group in model_groups():
        for option in group["models"]:
            if option["id"] == pick:
                return f"{group['group']} · {option['label']}"
    return pick


def resolve_model(model_id: str | None) -> str:
    """Return a Perplexity agent model id. An unknown choice falls back to the balanced GPT model."""
    pick = str(model_id or "").strip()
    if pick in _OPENAI_TO_PERPLEXITY:
        return _OPENAI_TO_PERPLEXITY[pick]
    if pick in _ACCEPTED:
        return pick
    return DEFAULT_PERPLEXITY_MODEL


def _option(model_id: str, tier: str) -> dict[str, str]:
    return {"id": model_id, "label": f"{tier} · {model_id}"}
