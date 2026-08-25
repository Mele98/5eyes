"""Tests fuer die PDF-Komponente sollist_vergleich.py (Roadmap #57/#58,
Standpunkt 2026-08-07): SOLL/IST-Vergleich + Risiko-Kennzahlen im gedruckten
Beratungsprotokoll.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from reportlab.platypus import Paragraph, Table

from services.pdf.components.sollist_vergleich import (
    _sharpe_ratio,
    make_sollist_goal_comparison_table,
    make_sollist_kennzahlen_table,
)


# --------------------------------------------------------------------------
# _sharpe_ratio — muss exakt der Frontend-Formel entsprechen
# (5eyes_v2.html aaShowProjection() `_sharpe`)
# --------------------------------------------------------------------------


def test_sharpe_ratio_matches_frontend_formula():
    # (700 - 80) / 1200 = 0.516666...
    assert _sharpe_ratio(700, 1200, 80) == (700 - 80) / 1200


def test_sharpe_ratio_none_when_vol_missing():
    assert _sharpe_ratio(700, None, 80) is None


def test_sharpe_ratio_none_when_vol_zero_or_negative():
    assert _sharpe_ratio(700, 0, 80) is None
    assert _sharpe_ratio(700, -10, 80) is None


def test_sharpe_ratio_none_when_cagr_missing():
    assert _sharpe_ratio(None, 1200, 80) is None


def test_sharpe_ratio_can_be_negative():
    assert _sharpe_ratio(20, 1200, 80) < 0


# --------------------------------------------------------------------------
# make_sollist_kennzahlen_table
# --------------------------------------------------------------------------


def _sample_kennzahlen_kwargs(**overrides) -> dict:
    defaults = dict(
        target_median_end_rappen=250_000_00,
        target_p90_end_rappen=320_000_00,
        target_p10_end_rappen=190_000_00,
        current_median_end_rappen=210_000_00,
        current_p90_end_rappen=260_000_00,
        current_p10_end_rappen=170_000_00,
        target_cagr_bps=650,
        current_cagr_bps=420,
        target_volatility_1y_bps=1200,
        current_volatility_1y_bps=900,
        currency="CHF",
    )
    defaults.update(overrides)
    return defaults


def test_kennzahlen_table_returns_table_when_data_present():
    result = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs())
    assert len(result) == 1
    assert isinstance(result[0], Table)


def test_kennzahlen_table_empty_when_no_data_at_all():
    result = make_sollist_kennzahlen_table(
        target_median_end_rappen=None, target_p90_end_rappen=None, target_p10_end_rappen=None,
        current_median_end_rappen=None, current_p90_end_rappen=None, current_p10_end_rappen=None,
        target_cagr_bps=None, current_cagr_bps=None,
        target_volatility_1y_bps=None, current_volatility_1y_bps=None,
    )
    assert result == []


def test_kennzahlen_table_has_header_plus_five_metric_rows():
    table = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs())[0]
    # Header + Median/P90/P10/Rendite/Vol/Sharpe = 7 Zeilen
    assert len(table._cellvalues) == 7


def test_kennzahlen_table_header_columns():
    table = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs())[0]
    header_texts = [cell.text for cell in table._cellvalues[0]]
    assert "SOLL" in header_texts[1]
    assert "IST" in header_texts[2]


def test_kennzahlen_table_shows_chf_amounts_with_currency():
    table = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs(currency="EUR"))[0]
    median_row = table._cellvalues[1]
    assert "EUR" in median_row[1].text
    assert "EUR" in median_row[2].text


def test_kennzahlen_table_sharpe_row_present_and_formatted():
    table = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs())[0]
    sharpe_row = table._cellvalues[-1]
    assert "Sharpe" in sharpe_row[0].text
    # (650-80)/1200 = 0.475, current (420-80)/900 = 0.3778...
    assert sharpe_row[1].text == f"{(650 - 80) / 1200:.2f}"
    assert sharpe_row[2].text == f"{(420 - 80) / 900:.2f}"


def test_kennzahlen_table_renders_with_only_target_side_present():
    """IST fehlt komplett (z.B. kein Beratungsvermoegen erfasst) -- Tabelle
    rendert trotzdem, mit '—' auf der IST-Seite, kein Crash."""
    table = make_sollist_kennzahlen_table(**_sample_kennzahlen_kwargs(
        current_median_end_rappen=None, current_p90_end_rappen=None, current_p10_end_rappen=None,
        current_cagr_bps=None, current_volatility_1y_bps=None,
    ))[0]
    median_row = table._cellvalues[1]
    assert median_row[2].text == "—"


# --------------------------------------------------------------------------
# make_sollist_goal_comparison_table
# --------------------------------------------------------------------------


def _sample_goal_analysis() -> list[dict]:
    return [
        {"goal_id": "g-1", "label": "Pensionsentnahme 2035", "median_achievement_pct": 92},
        {"goal_id": "g-2", "label": "Hauskauf 2032", "median_achievement_pct": 71},
    ]


def _sample_current_goal_analysis() -> list[dict]:
    return [
        {"goal_id": "g-1", "label": "Pensionsentnahme 2035", "median_achievement_pct": 68},
        {"goal_id": "g-2", "label": "Hauskauf 2032", "median_achievement_pct": 55},
    ]


def test_goal_comparison_returns_table_when_both_sides_present():
    result = make_sollist_goal_comparison_table(_sample_goal_analysis(), _sample_current_goal_analysis())
    assert len(result) == 1
    assert isinstance(result[0], Table)


def test_goal_comparison_empty_when_both_sides_empty():
    assert make_sollist_goal_comparison_table([], []) == []


def test_goal_comparison_header_plus_one_row_per_goal():
    table = make_sollist_goal_comparison_table(_sample_goal_analysis(), _sample_current_goal_analysis())[0]
    assert len(table._cellvalues) == 3  # Header + 2 Ziele


def test_goal_comparison_matches_by_goal_id_not_position():
    """SOLL und IST in unterschiedlicher Reihenfolge -- muss trotzdem korrekt matchen."""
    soll = [{"goal_id": "g-2", "label": "Hauskauf 2032", "median_achievement_pct": 71}]
    ist = [{"goal_id": "g-2", "label": "Hauskauf 2032", "median_achievement_pct": 55}]
    table = make_sollist_goal_comparison_table(soll, ist)[0]
    row = table._cellvalues[1]
    assert row[1].text == "71%"
    assert row[2].text == "55%"


def test_goal_comparison_shows_dash_for_ist_only_missing_soll_side():
    soll = [{"goal_id": "g-1", "label": "Ziel A", "median_achievement_pct": 80}]
    ist = []  # IST-Simulation lieferte fuer dieses Ziel kein Ergebnis
    table = make_sollist_goal_comparison_table(soll, ist)[0]
    row = table._cellvalues[1]
    assert row[1].text == "80%"
    assert row[2].text == "—"


def test_goal_comparison_includes_ist_only_goals():
    """Ein Ziel, das nur im current_goal_analysis auftaucht, wird trotzdem
    gelistet (Vollstaendigkeit vor Kompaktheit) statt stillschweigend
    weggelassen."""
    soll = []
    ist = [{"goal_id": "g-9", "label": "Nur-IST-Ziel", "median_achievement_pct": 40}]
    table = make_sollist_goal_comparison_table(soll, ist)[0]
    assert len(table._cellvalues) == 2
    row = table._cellvalues[1]
    assert "Nur-IST-Ziel" in row[0].text
    assert row[1].text == "—"
    assert row[2].text == "40%"
