"""Sprint U-28 + U-29 (2026-06-03): Override-Begruendung-Qualitaets-Check.

Pre-U-28: nur strip()-Check (nicht-leer).
Pre-U-29: keine Phrase-Blacklist.

Post-U-28+29
------------
- OVERRIDE_REASON_MIN_LENGTH = 20 chars (NACH strip)
- GENERIC_PHRASE_BLACKLIST gegen typische Floskeln
- MIN_MEANINGFUL_WORDS = 3 (Worte >= 4 chars)
- validate_override_reason_quality(reason) raises auf 4 Codes

FIDLEG Art. 13 verlangt nachvollziehbare Dokumentation.
"""
from __future__ import annotations

import re
from typing import Optional


OVERRIDE_REASON_MIN_LENGTH = 20

GENERIC_PHRASE_BLACKLIST = frozenset({
    "ok", "o.k.", "okay", "ja", "passt", "fine", "good", "geht",
    "n/a", "na", "keine", "kein grund", "test", "tbd", "todo",
    "siehe oben", "wie besprochen", "siehe protokoll",
    "kunde will", "kundenwunsch", "siehe akten", "weiss nicht",
})

MIN_MEANINGFUL_WORDS = 3


class OverrideReasonQualityError(ValueError):
    def __init__(self, message: str, *, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


REASON_CODE_EMPTY = "empty"
REASON_CODE_TOO_SHORT = "too_short"
REASON_CODE_GENERIC_PHRASE = "generic_phrase"
REASON_CODE_INSUFFICIENT_WORDS = "insufficient_words"


def _normalize_for_phrase_check(text: str) -> str:
    """Lowercase + collapse whitespace + strip trailing punctuation."""
    s = text.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\.\!\?\,\;\:]+$", "", s)
    return s


def _meaningful_word_count(text: str) -> int:
    """Anzahl Worte mit mindestens 4 Zeichen."""
    tokens = re.findall(r"[\wäöüÄÖÜß]+", text, flags=re.UNICODE)
    return sum(1 for t in tokens if len(t) >= 4)


def validate_override_reason_quality(
    reason: Optional[str],
    *,
    min_length: int = OVERRIDE_REASON_MIN_LENGTH,
    min_meaningful_words: int = MIN_MEANINGFUL_WORDS,
) -> None:
    """Wirft OverrideReasonQualityError wenn Begruendung nicht
    FINMA-tauglich ist.

    Reasons: empty / too_short / generic_phrase / insufficient_words.
    """
    if reason is None:
        raise OverrideReasonQualityError(
            "override_reason ist Pflicht (FIDLEG Art. 13).",
            reason_code=REASON_CODE_EMPTY,
        )
    text = str(reason).strip()
    if not text:
        raise OverrideReasonQualityError(
            "override_reason ist Pflicht (FIDLEG Art. 13).",
            reason_code=REASON_CODE_EMPTY,
        )
    if len(text) < min_length:
        raise OverrideReasonQualityError(
            f"override_reason muss mindestens {min_length} Zeichen "
            f"haben (FIDLEG-Audit-tauglich). Aktuell: {len(text)} Zeichen.",
            reason_code=REASON_CODE_TOO_SHORT,
        )

    normalized = _normalize_for_phrase_check(text)
    if normalized in GENERIC_PHRASE_BLACKLIST:
        raise OverrideReasonQualityError(
            f"override_reason '{text!r}' ist eine generische Floskel. "
            f"Bitte konkret begruenden warum das Profil vom Fragebogen "
            f"abweicht (FIDLEG Art. 13).",
            reason_code=REASON_CODE_GENERIC_PHRASE,
        )

    if _meaningful_word_count(text) < min_meaningful_words:
        raise OverrideReasonQualityError(
            f"override_reason braucht mindestens {min_meaningful_words} "
            f"bedeutungsvolle Worte (>= 4 Zeichen). Bitte konkreter "
            f"begruenden.",
            reason_code=REASON_CODE_INSUFFICIENT_WORDS,
        )
