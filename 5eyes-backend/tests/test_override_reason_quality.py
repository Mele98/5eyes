"""Sprint U-28 + U-29 (Roadmap-Punkte 28+29, 2026-06-03): Override-
Begruendungs-Qualitaets-Validierung.

services/override_reason_quality.py:
- OVERRIDE_REASON_MIN_LENGTH = 20 (chars nach strip)
- GENERIC_PHRASE_BLACKLIST gegen Floskeln
- MIN_MEANINGFUL_WORDS = 3 (Worte >= 4 chars)
- validate_override_reason_quality(reason) raises auf 4 Codes

Wired in schemas/profiling.py RiskAssessmentOverride.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.override_reason_quality import (  # noqa: E402
    GENERIC_PHRASE_BLACKLIST,
    MIN_MEANINGFUL_WORDS,
    OVERRIDE_REASON_MIN_LENGTH,
    REASON_CODE_EMPTY,
    REASON_CODE_GENERIC_PHRASE,
    REASON_CODE_INSUFFICIENT_WORDS,
    REASON_CODE_TOO_SHORT,
    OverrideReasonQualityError,
    _meaningful_word_count,
    _normalize_for_phrase_check,
    validate_override_reason_quality,
)


# ---------------------------------------------------------------------------
# Konstanten Drift-Schutz
# ---------------------------------------------------------------------------

def test_min_length_is_20():
    assert OVERRIDE_REASON_MIN_LENGTH == 20


def test_min_meaningful_words_is_3():
    assert MIN_MEANINGFUL_WORDS == 3


def test_blacklist_includes_common_generics():
    assert "ok" in GENERIC_PHRASE_BLACKLIST
    assert "kundenwunsch" in GENERIC_PHRASE_BLACKLIST
    assert "siehe oben" in GENERIC_PHRASE_BLACKLIST
    assert "tbd" in GENERIC_PHRASE_BLACKLIST


def test_blacklist_is_frozen():
    assert isinstance(GENERIC_PHRASE_BLACKLIST, frozenset)


# ---------------------------------------------------------------------------
# _normalize_for_phrase_check
# ---------------------------------------------------------------------------

def test_normalize_lowercases():
    assert _normalize_for_phrase_check("OK") == "ok"


def test_normalize_strips_trailing_punctuation():
    assert _normalize_for_phrase_check("ok.") == "ok"
    assert _normalize_for_phrase_check("ok!!") == "ok"
    assert _normalize_for_phrase_check("ok?") == "ok"


def test_normalize_collapses_whitespace():
    assert _normalize_for_phrase_check("siehe   oben") == "siehe oben"
    assert _normalize_for_phrase_check("  siehe oben  ") == "siehe oben"


# ---------------------------------------------------------------------------
# _meaningful_word_count
# ---------------------------------------------------------------------------

def test_meaningful_words_excludes_short_tokens():
    """Worte < 4 Zeichen werden nicht gezaehlt."""
    assert _meaningful_word_count("ich bin da") == 0  # alle < 4
    assert _meaningful_word_count("ich war heute") == 1  # heute (5)


def test_meaningful_words_counts_real_content():
    text = "Kunde hat erhebliche Verluste durch Aktien erlitten"
    # Kunde(5), erhebliche(10), Verluste(8), durch(5), Aktien(6), erlitten(8) = 6
    assert _meaningful_word_count(text) == 6


def test_meaningful_words_handles_umlauts():
    text = "Berater erhöht Anlagebudget zurück"
    assert _meaningful_word_count(text) >= 3


# ---------------------------------------------------------------------------
# Empty / None
# ---------------------------------------------------------------------------

def test_none_raises_empty():
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(None)
    assert exc.value.reason_code == REASON_CODE_EMPTY


def test_empty_string_raises_empty():
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality("")
    assert exc.value.reason_code == REASON_CODE_EMPTY


def test_whitespace_only_raises_empty():
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality("    \n\t  ")
    assert exc.value.reason_code == REASON_CODE_EMPTY


# ---------------------------------------------------------------------------
# Too-Short
# ---------------------------------------------------------------------------

def test_too_short_raises():
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality("zu kurz")
    assert exc.value.reason_code == REASON_CODE_TOO_SHORT


def test_just_below_min_length_raises():
    text = "a" * 19
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(text)
    assert exc.value.reason_code == REASON_CODE_TOO_SHORT


# ---------------------------------------------------------------------------
# Generic-Phrase (mit Trailing-Punctuation auf >= 20 chars getrieben)
# ---------------------------------------------------------------------------

def test_generic_phrase_kundenwunsch_blocked():
    """24 chars stripped, normalize -> 'kundenwunsch' matches blacklist."""
    text = "kundenwunsch!!!!!!!!!!!!"
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(text)
    assert exc.value.reason_code == REASON_CODE_GENERIC_PHRASE


def test_generic_phrase_siehe_oben_blocked():
    text = "siehe oben............"  # 22 chars
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(text)
    assert exc.value.reason_code == REASON_CODE_GENERIC_PHRASE


def test_case_insensitive_phrase_check():
    """Uppercase wird nach normalize lower."""
    text = "SIEHE OBEN!!!!!!!!!!!!"
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(text)
    assert exc.value.reason_code == REASON_CODE_GENERIC_PHRASE


# ---------------------------------------------------------------------------
# Insufficient-Meaningful-Words
# ---------------------------------------------------------------------------

def test_insufficient_meaningful_words():
    """20+ chars, aber alle Tokens < 4 chars."""
    text = "ja ne ich war es so x"  # 21 chars, alle Worte < 4
    with pytest.raises(OverrideReasonQualityError) as exc:
        validate_override_reason_quality(text)
    assert exc.value.reason_code == REASON_CODE_INSUFFICIENT_WORDS


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------

def test_valid_finma_quality_reason_passes():
    text = (
        "Kunde hat umfangreiche Erfahrung mit Aktienmaerkten und "
        "moechte das Profil bewusst aggressiver halten."
    )
    validate_override_reason_quality(text)


def test_minimum_acceptable_reason():
    text = "Kunde hat Aktien-Erfahrung erworben"  # > 20, 3+ meaningful
    validate_override_reason_quality(text)


def test_custom_min_length_override():
    """Override min_length=10 + min_meaningful_words=2 fuer Test."""
    validate_override_reason_quality(
        "Aktien Profil bewusst",  # 22 chars, 3 meaningful
        min_length=10,
        min_meaningful_words=2,
    )


# ---------------------------------------------------------------------------
# Pydantic-Integration
# ---------------------------------------------------------------------------

def test_pydantic_override_rejects_short_reason():
    from pydantic import ValidationError
    from schemas.profiling import RiskAssessmentOverride

    with pytest.raises(ValidationError) as exc:
        RiskAssessmentOverride(
            override_score_x10=50,
            override_profile="Ausgewogen",
            override_reason="zu kurz",
        )
    assert "mindestens 20 Zeichen" in str(exc.value)


def test_pydantic_override_accepts_full_reason():
    from schemas.profiling import RiskAssessmentOverride

    override = RiskAssessmentOverride(
        override_score_x10=50,
        override_profile="Ausgewogen",
        override_reason=(
            "Kunde hat umfangreiche Aktien-Erfahrung "
            "und akzeptiert hoeheres Risiko bewusst."
        ),
    )
    assert override.override_score_x10 == 50


def test_pydantic_override_rejects_generic_phrase():
    from pydantic import ValidationError
    from schemas.profiling import RiskAssessmentOverride

    with pytest.raises(ValidationError) as exc:
        RiskAssessmentOverride(
            override_score_x10=50,
            override_profile="Ausgewogen",
            override_reason="kundenwunsch!!!!!!!!!!!!!",  # > 20 + generic
        )
    assert "generische Floskel" in str(exc.value)


def test_pydantic_override_rejects_empty_reason():
    from pydantic import ValidationError
    from schemas.profiling import RiskAssessmentOverride

    with pytest.raises(ValidationError) as exc:
        RiskAssessmentOverride(
            override_score_x10=50,
            override_profile="Ausgewogen",
            override_reason="",
        )
    assert "Pflicht" in str(exc.value)
