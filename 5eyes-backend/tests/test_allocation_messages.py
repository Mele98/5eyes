"""Tests fuer das Konflikt-Messages-Konstanten-Modul (Stage 4 Foundation).

Sichert die finalen Copy-Strings + den format_message-Helper gegen Regression
und gegen Aufnahme verbotener Formulierungen (FINMA-Ethik-Brüche).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.allocation_messages import (
    ALL_CODES,
    CONFLICT_DATA_INSUFFICIENT,
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
    classify_messages,
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


def _allocation(**overrides):
    base = {
        "optimization_status": "converged",
        "limiting_factor": "bandbreite",
        "risky_fraction_bps_at_generation": 6200,
        "risk_budget_bps_at_generation": 7000,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _assessment(**overrides):
    base = {
        "final_profile": "Wachstumsorientiert",
        "is_overridden": 0,
        "override_score_x10": None,
        "override_profile": None,
        "override_reason": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(goal_id, label, probability, status, hardness="hart"):
    return {
        "goal_id": goal_id,
        "label": label,
        "probability": probability,
        "tau": 0.8,
        "status": status,
        "hardness": hardness,
    }


def _codes(messages):
    return [msg["code"] for msg in messages]


def test_classify_messages_ok_comfortable():
    messages = classify_messages(
        _allocation(),
        [_row("g1", "Pension", 0.91, "erreichbar")],
        "converged",
        mandate=None,
        assessment=_assessment(),
    )
    assert _codes(messages) == [OK_COMFORTABLE]


def test_classify_messages_ok_tight():
    messages = classify_messages(
        _allocation(),
        [_row("g1", "Hauskauf", 0.65, "knapp")],
        "converged",
        mandate=None,
        assessment=_assessment(),
    )
    assert _codes(messages) == [OK_TIGHT]
    assert messages[0]["goal_id"] == "g1"
    assert "65%" in messages[0]["body_advisor"]


def test_classify_messages_profile_limits_when_risk_budget_binds():
    messages = classify_messages(
        _allocation(
            limiting_factor="risikoprofil",
            risky_fraction_bps_at_generation=6980,
            risk_budget_bps_at_generation=7000,
        ),
        [_row("g1", "Renditeziel 5%", 0.42, "nicht_erreichbar")],
        "converged",
        mandate=None,
        assessment=_assessment(final_profile="Wachstum"),
    )
    assert _codes(messages) == [CONFLICT_PROFILE_LIMITS]
    assert "Wachstum" in messages[0]["body_advisor"]


def test_classify_messages_goal_incompatible_for_two_hard_conflicts():
    messages = classify_messages(
        _allocation(limiting_factor="zielkonflikt"),
        [
            _row("g1", "Pension", 0.42, "nicht_erreichbar"),
            _row("g2", "Kapitalerhalt", 0.35, "nicht_erreichbar", hardness="primär"),
        ],
        "converged",
        mandate=None,
        assessment=_assessment(),
    )
    assert _codes(messages) == [CONFLICT_GOAL_INCOMPATIBLE]
    assert "Kapitalerhalt" in messages[0]["body_advisor"]
    assert "Pension" in messages[0]["body_advisor"]


def test_classify_messages_data_insufficient_when_not_profile_limited():
    messages = classify_messages(
        _allocation(limiting_factor="liquiditaetsreserve"),
        [_row("g1", "Pensionsluecke", 0.21, "nicht_erreichbar")],
        "converged",
        mandate=None,
        assessment=_assessment(),
    )
    assert _codes(messages) == [CONFLICT_DATA_INSUFFICIENT]


def test_classify_messages_fallback_warning():
    messages = classify_messages(
        _allocation(optimization_status="fallback_house_matrix", limiting_factor="solver_konvergenz"),
        [],
        "fallback_house_matrix",
        mandate=None,
        assessment=_assessment(),
    )
    assert _codes(messages) == [WARN_FALLBACK]


def test_classify_messages_override_warning():
    messages = classify_messages(
        _allocation(),
        [],
        "converged",
        mandate=None,
        assessment=_assessment(
            is_overridden=1,
            override_score_x10=70,
            override_profile="Wachstumsorientiert",
            override_reason="Kundenwunsch dokumentiert",
        ),
    )
    assert _codes(messages) == [WARN_OVERRIDE]
    assert "Kundenwunsch dokumentiert" in messages[0]["body_advisor"]
