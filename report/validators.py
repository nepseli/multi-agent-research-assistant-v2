import re
from typing import Literal

from core.config import SizePreset

_REFERENCES = re.compile(r"(?im)^#{1,6}\s*references\b.*\Z", re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_IMAGE = re.compile(r"(?m)^\s*!\[.*?\]\(.*?\)\s*$")


def strip_references(text: str) -> str:
    return _REFERENCES.sub("", text)


def count_words(text: str) -> int:
    """Count body words, excluding the references section onward, code fences and image lines."""
    body = strip_references(text)
    body = _FENCE.sub("", body)
    body = _IMAGE.sub("", body)
    return sum(1 for token in body.split() if any(ch.isalnum() for ch in token))


def word_status(count: int, preset: SizePreset, tol: float = 0.15) -> Literal["ok", "short", "long"]:
    low = round(preset.words_min * (1 - tol), 6)
    high = round(preset.words_max * (1 + tol), 6)
    if count < low:
        return "short"
    if count > high:
        return "long"
    return "ok"
