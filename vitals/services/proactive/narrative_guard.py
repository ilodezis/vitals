"""Check the morning brief's LLM paragraph against the numbers it was given.

The model writes prose from a Garmin block; nothing stops it from saying "HRV is
low" when HRV is above the baseline. ``contradictions`` is a conservative,
pure-text check: it only flags a sentence clause when a metric alias and a
direction word appear in the same clause and the number disagrees with the
baseline. Anything ambiguous is left alone.

Rules (see ``contradictions``):
  * a "down" word (ниже, просел, упал, снизил, хуже, низкий) about a metric
    whose value is >= its baseline is a contradiction;
  * an "up" word (выше, вырос, повысил, поднял, лучше, высокий) about a metric
    whose value is <= its baseline is a contradiction;
  * any comparative word about a metric that has no baseline is a contradiction
    (the prompt forbids comparing without a norm);
  * a Body Battery clause that quotes a number equal to ``body_battery_low`` but
    not ``body_battery_high`` is a contradiction (the morning charge is the high).
"""
from __future__ import annotations

import re
from typing import Any

# metric key -> (English label, Russian/English alias patterns on normalized text)
_ALIASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "hrv_avg": ("HRV", (r"\bhrv\b", r"\bвср\b", r"вариабельност")),
    "sleep_score": ("sleep", (r"\bсон\b", r"\bсна\b", r"\bсну\b", r"\bсне\b", r"\bсном\b", r"\bсны\b", r"\bsleep\b")),
    "resting_hr": ("resting HR", (r"\bпульс\w*", r"\bчсс\b", r"\bresting\s+hr\b")),
    "body_battery_high": ("body_battery_high", (r"body\s*battery", r"\bбатаре\w*", r"\bbb\b")),
    "spo2_lowest": ("spo2_lowest", (r"\bspo2\b", r"сатурац", r"кислород")),
}

# Normalized (lowercase, ё -> е) forms; word stems use prefix matches.
_DOWN = (
    r"\bниже\b",
    r"\bпросел\w*",
    r"\bупал\w*",
    r"\bснизил\w*",
    r"\bснижен\w*",
    r"\bхуже\b",
    r"\bнизк\w*",
)
_UP = (
    r"\bвыше\b",
    r"\bвырос\w*",
    r"\bповыс\w*",
    r"\bповышен\w*",
    r"\bподнял\w*",
    r"\bлучше\b",
    r"\bвысок\w*",
)
_DOWN_RE = re.compile("|".join(f"(?:{p})" for p in _DOWN))
_UP_RE = re.compile("|".join(f"(?:{p})" for p in _UP))
_NEGATION_BEFORE = re.compile(r"\bне\s*(?:очень\s*|слишком\s*|так\s*)?$")
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")
_CLAUSE_SPLIT = re.compile(r",|:|;|\s+а\s+|\s+но\s+|\s+и\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics_in(clause: str) -> list[str]:
    found = []
    for key, (_label, patterns) in _ALIASES.items():
        if any(re.search(p, clause) for p in patterns):
            found.append(key)
    return found


def _direction_words(clause: str) -> list[tuple[str, str]]:
    """Return (direction, matched word) for comparative words not negated by 'не'."""
    hits: list[tuple[str, str]] = []
    for direction, regex in (("down", _DOWN_RE), ("up", _UP_RE)):
        for m in regex.finditer(clause):
            if _NEGATION_BEFORE.search(clause[: m.start()]):
                continue
            hits.append((direction, m.group(0)))
    return hits


def _clause_reasons(clause: str, key: str, garmin: dict, baseline: dict) -> list[str]:
    """Reasons this clause contradicts the data for one metric (empty = fine)."""
    reasons: list[str] = []

    directions = _direction_words(clause)
    kinds = {d for d, _ in directions}
    # Mixed up/down words in one clause are ambiguous; skip the direction check.
    if len(kinds) == 1:
        direction, word = directions[0]
        base = _num(baseline.get(key))
        value = _num(garmin.get(key))
        if base is None:
            reasons.append(f"comparative claim '{word}' but no baseline to compare against")
        elif value is not None:
            if direction == "down" and value >= base:
                reasons.append(f"claimed '{word}' (down) but value {value:g} >= baseline {base:g}")
            elif direction == "up" and value <= base:
                reasons.append(f"claimed '{word}' (up) but value {value:g} <= baseline {base:g}")

    if key == "body_battery_high":
        low = _num(garmin.get("body_battery_low"))
        high = _num(garmin.get("body_battery_high"))
        if low is not None and high is not None and low != high:
            for token in _NUMBER.findall(clause):
                if float(token.replace(",", ".")) == low:
                    reasons.append(
                        f"quotes {token}, which is body_battery_low, not body_battery_high ({high:g})"
                    )
                    break

    return reasons


def contradictions(text: str, garmin: dict) -> list[str]:
    """Return short English descriptions of claims in ``text`` that contradict ``garmin``.

    ``garmin`` is the brief's garmin block: metric values at the top level and
    ``garmin["baseline"]`` as ``{metric: mean}``. Missing or None values make a
    claim unverifiable, which is not flagged (except the no-baseline rule).
    Empty list means no contradiction was found.
    """
    if not text:
        return []
    garmin = garmin or {}
    baseline = garmin.get("baseline") or {}

    problems: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(_normalize(text)):
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            metrics = _metrics_in(clause)
            # A clause naming two metrics is ambiguous about which one a word refers to.
            if len(metrics) != 1:
                continue
            key = metrics[0]
            reasons = _clause_reasons(clause, key, garmin, baseline)
            if reasons:
                problems.append(f"{_ALIASES[key][0]}: " + "; ".join(reasons))
    return problems


def is_clean(text: str, garmin: dict) -> bool:
    """True when ``contradictions`` finds nothing in ``text``."""
    return not contradictions(text, garmin)
