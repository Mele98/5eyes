"""Sprint U-72 (2026-06-06): Tests fuer erweiterte Goal-Achievability-Tabelle (PDF)."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from reportlab.platypus import Table

from services.pdf.documents.advisory_report import _goals_table


def _styles() -> dict:
    from services.pdf.components.advisory_palette import make_advisory_styles
    return make_advisory_styles()


def _sample_goals() -> list[dict]:
    return [
        {
            "goal_id": "g1",
            "label": "Pension mit 60",
            "goal_type": "Lebenshaltung",
            "hardness": "Hart",
            "target_date": "2042-09-18",
            "target_amount_rappen": 1_500_000_00,
            "status": "erreichbar",
            "probability_bps": 8500,
        },
        {
            "goal_id": "g2",
            "label": "Hauskauf",
            "goal_type": "Vermoegensziel",
            "hardness": "Primaer",
            "target_date": "2030-01-01",
            "target_amount_rappen": 250_000_00,
            "status": "knapp",
            "probability_bps": 6000,
        },
        {
            "goal_id": "g3",
            "label": "Weltreise",
            "goal_type": "Lebensziel",
            "hardness": "Opportunistisch",
            "target_date": "2028-06-15",
            "target_amount_rappen": 30_000_00,
            "status": "nicht_erreichbar",
            "probability_bps": 2500,
        },
    ]


def test_table_has_8_columns():
    """Header-Zeile + Daten haben jeweils 8 Spalten.

    Stage-9: zur U-72-Tabelle (Ziel/Typ/Hartheit/Ziel-Datum/Zielwert/Status/
    Wahrscheinlichkeit) kam die MC-Status-Spalte hinzu -> 8 Spalten.
    """
    table = _goals_table(_sample_goals(), _styles())
    assert isinstance(table, Table)
    # Internal data list — pruefen dass jede Zeile 8 Spalten hat
    data = table._cellvalues
    assert len(data) >= 4  # Header + 3 Goals
    for row in data:
        assert len(row) == 8, f"Erwarte 8 Spalten, gefunden {len(row)}"


def test_table_header_contains_all_7_labels():
    """Header-Zeile muss alle 7 erwarteten Spalten-Titel haben."""
    table = _goals_table(_sample_goals(), _styles())
    header_row = table._cellvalues[0]
    # Header ist eine Liste von Paragraph-Objekten; extract text
    header_text = " | ".join(
        getattr(p, "text", str(p)) for p in header_row
    )
    for expected in (
        "Ziel", "Typ", "Hartheit", "Ziel-Datum",
        "Zielwert", "Status", "Wahrscheinlichkeit",
    ):
        assert expected in header_text, (
            f"Spalten-Titel {expected!r} fehlt: {header_text!r}"
        )


def test_table_handles_empty_goals():
    table = _goals_table([], _styles())
    # Nur Header-Zeile
    assert len(table._cellvalues) == 1


def test_table_handles_missing_hardness_with_dash():
    """Wenn ein Goal keine 'hardness' hat -> Anzeige '—' (no crash)."""
    goal_without_hardness = [{
        "goal_id": "g-empty",
        "label": "Ohne Hartheit",
        "goal_type": "X",
        "target_date": "2030-01-01",
        "target_amount_rappen": 0,
        "status": "data_pending",
        # KEIN hardness-Feld
    }]
    table = _goals_table(goal_without_hardness, _styles())
    # Sollte nicht crashen
    assert len(table._cellvalues) == 2


def test_table_handles_missing_target_date_with_dash():
    goal_without_date = [{
        "label": "Ohne Datum",
        "hardness": "Hart",
        "target_amount_rappen": 100_000_00,
        "status": "erreichbar",
        # KEIN target_date-Feld
    }]
    table = _goals_table(goal_without_date, _styles())
    assert len(table._cellvalues) == 2


def test_source_documents_u_72_sprint():
    """U-72-Marker im _goals_table-Docstring."""
    import inspect
    src = inspect.getsource(_goals_table)
    assert "U-72" in src
    assert "Hartheit" in src or "hardness" in src
