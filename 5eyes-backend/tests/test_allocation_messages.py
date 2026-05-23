"""Tests fuer das Konflikt-Messages-Konstanten-Modul (Stage 4 Foundation).

Sichert die finalen Copy-Strings + den format_message-Helper gegen Regression
und gegen Aufnahme verbotener Formulierungen (FINMA-Ethik-Brüche).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.allocation_messages import (
    ALL_CODES,
    CONFLICT_GOAL_INCOMPATIBLE,
    CONFLICT_PROFILE_LIMITS,
    MESSAGE_TEMPLATES,
    OK_COMFORTABLE,
    OK_TIGHT,
    SEVERITY_CONFLICT,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    WARN_FALLBACK,
    WARN_OVERRIDE,
    _FORBIDDEN_SUBSTRINGS,
    format_message,
)


def test_all_codes_have_templates():
    assert set(MESSAGE_TEMPLATES.keys()) == set(ALL_CODES)
    for code, tpl in MESSAGE_TEMPLATES.items():
        assert tpl["severity"] in (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CONFLICT), code
        assert tpl["title"], code
        assert tpl["body_advisor"], code
        assert tpl["body_client"], code
        assert isinstance(tpl["actions"], tuple), code


def test_severity_mapping_matches_spec():
    assert MESSAGE_TEMPLATES[OK_COMFORTABLE]["severity"] == SEVERITY_INFO
    assert MESSAGE_TEMPLATES[OK_TIGHT]["severity"] == SEVERITY_WARNING
    assert MESSAGE_TEMPLATES[CONFLICT_PROFILE_LIMITS]["severity"] == SEVERITY_CONFLICT
    assert MESSAGE_TEMPLATES[CONFLICT_GOAL_INCOMPATIBLE]["severity"] == SEVERITY_CONFLICT
    assert MESSAGE_TEMPLATES[WARN_FALLBACK]["severity"] == SEVERITY_WARNING
    assert MESSAGE_TEMPLATES[WARN_OVERRIDE]["severity"] == SEVERITY_WARNING


def test_format_message_substitutes_placeholders():
    msg = format_message(CONFLICT_PROFILE_LIMITS,
                         goal_label="Pension 2040", profile_label="Wachstum", prob=42,
                         goal_id="g-1")
    assert "Pension 2040" in msg["body_advisor"]
    assert "Wachstum" in msg["body_advisor"]
    assert "42%" in msg["body_advisor"]
    assert msg["code"] == CONFLICT_PROFILE_LIMITS
    assert msg["severity"] == SEVERITY_CONFLICT
    assert msg["goal_id"] == "g-1"
    assert "adjust_goal" in msg["actions"]
    assert "review_riskprofile_with_assessment" in msg["actions"]


def test_format_message_safe_on_missing_placeholder():
    # Defensiver Fallback: fehlende Placeholder bleiben als {name} im Text.
    msg = format_message(OK_TIGHT)  # ohne goal_label, prob
    assert "{goal_label}" in msg["body_advisor"]
    assert "{prob}" in msg["body_client"]


def test_format_message_unknown_code_raises():
    with pytest.raises(ValueError, match="Unbekannter Message-Code"):
        format_message("DOES_NOT_EXIST")


def test_no_forbidden_phrases_in_any_template():
    """FINMA-Ethik: keine Aufforderung zur Risikoerhöhung, keine Garantien."""
    for code, tpl in MESSAGE_TEMPLATES.items():
        full_text = tpl["title"] + " " + tpl["body_advisor"] + " " + tpl["body_client"]
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden.lower() not in full_text.lower(), (
                f"Verbotene Phrase {forbidden!r} in MESSAGE_TEMPLATES[{code!r}]"
            )


def test_warn_override_substitutes_override_and_reason():
    msg = format_message(WARN_OVERRIDE, override_label="Wachstum",
                         reason="Klient explizit höheres Risiko nach FINMA-Gespräch")
    assert "Wachstum" in msg["body_advisor"]
    assert "FINMA-Gespräch" in msg["body_advisor"]
    assert msg["severity"] == SEVERITY_WARNING


def test_goal_incompatible_has_two_goal_placeholders():
    msg = format_message(CONFLICT_GOAL_INCOMPATIBLE,
                         goal_a="Pensionsentnahme", goal_b="Kapitalerhalt")
    assert "Pensionsentnahme" in msg["body_advisor"]
    assert "Kapitalerhalt" in msg["body_advisor"]


def test_actions_are_lists_not_tuples_in_output():
    """Output-Kontrakt: actions als list[str] (JSON-serialisierbar einheitlich)."""
    msg = format_message(OK_COMFORTABLE)
    assert isinstance(msg["actions"], list)
    msg2 = format_message(CONFLICT_PROFILE_LIMITS, goal_label="x", profile_label="y", prob=10)
    assert isinstance(msg2["actions"], list)
