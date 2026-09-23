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

Kontrollrunde 2026-09-21 (Heuristik-Haertung)
----------------------------------------------
Der urspruengliche "meaningful word"-Test zaehlte jedes >= 4 Zeichen
lange `\\w`-Token -- `\\w` matcht aber auch Ziffern und Unterstrich, nicht
nur Buchstaben. Dadurch bestanden reine Ziffern-/Unterstrich-Fuellungen
("111111 222222 333333", "_______ _______ _______") sowie reine
Zeichen-Wiederholung ("aaaa aaaa aaaa") die Pruefung, obwohl sie keine
einzige echte Silbe enthalten. Zusaetzlich pruefte der Blacklist-Check
nur exakte Gleichheit mit einer Floskel -- eine Floskel drei Mal
aneinandergereiht ("kundenwunsch kundenwunsch kundenwunsch") umging ihn
und erfuellte gleichzeitig zufaellig die Wortanzahl-Schwelle. Fix:
- Wort-Tokenizer zaehlt nur Buchstaben (`[^\\W\\d_]+`, keine Ziffern/
  Unterstriche mehr), UND verlangt >= 2 verschiedene Zeichen pro Token
  (blockt reine Wiederholung wie "aaaa").
- Blacklist-Check erkennt zusaetzlich Text, der ausschliesslich aus
  Wiederholungen EINER Blacklist-Floskel besteht.
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
    """Anzahl Worte mit mindestens 4 Buchstaben UND mindestens 2
    verschiedenen Zeichen.

    `[^\\W\\d_]+` matcht Unicode-Buchstaben (inkl. Umlaute) und schliesst
    Ziffern/Unterstrich aus -- reine Ziffern-/Unterstrich-Fuellungen
    zaehlen damit nicht mehr als "Wort". Der Distinct-Zeichen-Check
    blockt zusaetzlich reine Zeichen-Wiederholung ("aaaa"), die technisch
    die Laengenschwelle erfuellt aber kein Wort ist.
    """
    tokens = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
    return sum(
        1 for t in tokens
        if len(t) >= 4 and len(set(t.lower())) >= 2
    )


def _is_pure_repetition_of_blacklisted_phrase(normalized: str) -> bool:
    """True wenn der (bereits normalisierte) Text ausschliesslich aus
    einer oder mehreren Wiederholungen EINER Floskel aus der Blacklist
    besteht (z.B. "kundenwunsch kundenwunsch kundenwunsch") -- umgeht
    sonst den reinen Exact-Match-Vergleich und erfuellt durch die
    Wiederholung zufaellig auch die Wortanzahl-Schwelle."""
    if not normalized:
        return False
    for phrase in GENERIC_PHRASE_BLACKLIST:
        pattern = re.compile(
            rf"(?:{re.escape(phrase)})(?:\s+{re.escape(phrase)})*"
        )
        if pattern.fullmatch(normalized):
            return True
    return False


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
    if (
        normalized in GENERIC_PHRASE_BLACKLIST
        or _is_pure_repetition_of_blacklisted_phrase(normalized)
    ):
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
