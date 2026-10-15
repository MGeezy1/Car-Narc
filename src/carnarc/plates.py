"""Plate text normalization and plausibility rules."""

from __future__ import annotations

import re

from .config import PlateRulesConfig

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize(text: str) -> str:
    """Uppercase and strip everything except A-Z and 0-9."""
    return _NON_ALNUM.sub("", text.upper())


def levenshtein(a: str, b: str) -> int:
    """Minimum single-character edits (insert, delete, substitute) to turn a into b."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_plausible(plate: str, rules: PlateRulesConfig) -> bool:
    """Cheap sanity filter for US plates (length bounds, at least one character).

    This deliberately does not try to validate state-specific formats; that needs
    per-state patterns and belongs in a later, opt-in stage.
    """
    if not plate:
        return False
    return rules.min_length <= len(plate) <= rules.max_length
