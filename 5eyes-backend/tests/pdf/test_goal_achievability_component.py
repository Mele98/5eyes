"""Tests fuer Stage-7 PDF-Komponente goal_achievability.py.

Sichert Struktur, Sprache (keine verbotenen Phrasen), und korrekte
Status-/Hardness-/Goal-Type-Aufloesung. Stage 7 (Integration in
anlagestrategie.py) baut auf diesem Test auf.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from reportlab.platypus import Paragraph, Table

from services.pdf.components.goal_achievability import (
    LIMITING_FACTOR_LABELS,
    _norm_hardness,
    _prob_cell,
    make_goal_achievability_table,
    make_limiting_factor_line,
)


# --------------------------------------------------------------------------
# make_limiting_factor_line
# --------------------------------------------------------------------------


def test_limiting_factor_line_returns_paragraph_for_known_factor():
    para = make_limiting_factor_line("risikoprofil")
    assert isinstance(para, Paragraph)
    # Berater-Sprache, nicht der Code-Schluessel
    assert "Risikoprofil limitiert" in para.text


def test_limiting_factor_line_handles_all_five_known_factors():
    for code in ("risikoprofil", "liquiditaetsreserve", "bandbreite",
                 "zielkonflikt", "solver_konvergenz"):
        para = make_limiting_factor_line(code)
        assert isinstance(para, Paragraph)
        assert LIMITING_FACTOR_LABELS[code] in para.text


def test_limiting_factor_line_empty_for_none():
    para = make_limiting_factor_line(None)
    assert isinstance(para, Paragraph)
    assert para.text == ""


def test_limiting_factor_line_empty_for_empty_string():
    para = make_limiting_factor_line("")
    assert isinstance(para, Paragraph)
    assert para.text == ""


def test_limiting_factor_line_unknown_factor_falls_back_to_raw():
    """Unbekannter Code -> roher Wert (Forward-Compat fuer kuenftige Codes)."""
    para = make_limiting_factor_line("future_unknown_factor")
    assert "future_unknown_factor" in para.text


# --------------------------------------------------------------------------
# make_goal_achievability_table — Struktur
# --------------------------------------------------------------------------


def _sample_achievability() -> list[dict]:
    return [
        {
            "goal_id": "g-1",
            "label": "Pensionsentnahme 2035",
            "goal_type": "Pensionsausgabe",
            "probability": 0.92,
            "status": "erreichbar",
            "hardness": "hart",
        },
        {
            "goal_id": "g-2",
            "label": "Hauskauf 2032",
            "goal_type": "Vermoegensziel",
            "probability": 0.71,
            "status": "knapp",
            "hardness": "primaer",
        },
        {
            "goal_id": "g-3",
            "label": "Renditeziel 5% p.a.",
            "goal_type": "Renditeziel",
            "probability": 0.42,
            "status": "nicht_erreichbar",
            "hardness": "primär",
        },
    ]


def test_achievability_table_returns_table():
    table = make_goal_achievability_table(_sample_achievability())
    assert isinstance(table, Table)


def test_achievability_table_has_header_plus_one_row_per_goal():
    table = make_goal_achievability_table(_sample_achievability())
    # Header + 3 Goals = 4 Zeilen
    assert len(table._cellvalues) == 4


def test_achievability_table_header_has_expected_columns():
    table = make_goal_achievability_table(_sample_achievability())
    header = table._cellvalues[0]
    assert header == ["Ziel", "Typ", "Hardness", "Wahrscheinlichkeit", "Status"]


def test_achievability_table_empty_list_renders_placeholder_row():
    """Keine Goals -> Hinweistext-Zeile, kein Render-Bruch."""
    table = make_goal_achievability_table([])
    # Header + 1 Hinweis-Zeile
    assert len(table._cellvalues) == 2
    # Hinweis-Text erwaehnt "Vermögensmaximierung" oder "keine Ziele"
    hint_cell = table._cellvalues[1][0]
    text = hint_cell.text if isinstance(hint_cell, Paragraph) else str(hint_cell)
    assert "Vermögensmaximierung" in text or "Keine" in text or "keine" in text


def test_achievability_table_renders_goal_type_in_advisor_language():
    """Pensionsausgabe (Code) -> 'Pensionsausgabe' (Label sind hier gleich,
    aber Vermoegensziel -> 'Vermögensziel' mit ä)."""
    achievability = [{
        "goal_id": "g-x", "label": "Test",
        "goal_type": "Vermoegensziel",
        "probability": 0.5, "status": "knapp", "hardness": "primaer",
    }]
    table = make_goal_achievability_table(achievability)
    typ_cell = table._cellvalues[1][1]
    assert "Vermögensziel" in str(typ_cell)


def test_achievability_table_handles_target_kind_alias():
    """Auch target_kind (Optimizer-intern) wird akzeptiert."""
    achievability = [{
        "goal_id": "g-x", "label": "Test",
        "target_kind": "return_rate",  # statt goal_type
        "probability": 0.6, "status": "knapp", "hardness": "primär",
    }]
    table = make_goal_achievability_table(achievability)
    typ_cell = table._cellvalues[1][1]
    assert "Renditeziel" in str(typ_cell)


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------


def test_norm_hardness_normalizes_aliases():
    assert _norm_hardness("hart") == "hart"
    assert _norm_hardness("HART") == "hart"
    assert _norm_hardness("primaer") == "primär"
    assert _norm_hardness("primär") == "primär"
    assert _norm_hardness("primary") == "primär"
    assert _norm_hardness("opportunistisch") == "opportunistisch"
    assert _norm_hardness("opp") == "opportunistisch"


@pytest.mark.parametrize("prob,expected", [
    (0.92, "92%"),
    (0.715, "71.5%"),  # genauer als 0.05% von round → 1 decimal
    (0.5, "50%"),
    (0.0, "0%"),
    (1.0, "100%"),
    (None, "—"),
])
def test_prob_cell_format(prob, expected):
    assert _prob_cell(prob) == expected


def test_prob_cell_clamps_overflow():
    """Defensive: Werte >1 oder <0 werden geclamped."""
    assert _prob_cell(1.5) == "100%"
    assert _prob_cell(-0.2) == "0%"


# --------------------------------------------------------------------------
# Sprachliche Absicherung — keine verbotenen Phrasen
# --------------------------------------------------------------------------


def test_no_forbidden_phrases_in_limiting_factor_labels():
    """FINMA-Ethik: keine Garantieversprechen, keine Aufforderung zur
    Risikoerhoehung — auch nicht in den Limiting-Factor-Labels."""
    forbidden = (
        "Erhöhen Sie Ihr Risiko",
        "garantiert",
        "Garantie",
        "wird erreicht",
        "perfekt",
    )
    for code, label in LIMITING_FACTOR_LABELS.items():
        for phrase in forbidden:
            assert phrase.lower() not in label.lower(), (
                f"Verbotene Phrase '{phrase}' in LIMITING_FACTOR_LABELS[{code!r}]"
            )
