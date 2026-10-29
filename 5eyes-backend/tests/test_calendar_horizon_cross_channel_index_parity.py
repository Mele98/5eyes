"""GOAL-CALENDAR-HORIZON-PARITY-001 (round 38) -- Kanal-Paritaet von Index und Verdikt.

Harness: Stichtag 2024-01-01 (Schaltjahr), Zieldatum 2025-01-01. Fixer
Vermoegenspfad (Rappen): t0=100, t1=50, t2=150, Ziel=100.

Zwei verschiedene Fragen, beide kanonisch beantwortet (Owner-Entscheide 1a/2,
Nachtrag 2026-10-11 im ADR-Dokument):

* "Wie viele Jahre bis zum Ziel?" -- Kunde, Router (``horizon_years``):
  ``calendar_years_until`` (ADR-1a). Hier 1.
* "Auf welcher Pfadspalte wird das Ziel bewertet?" -- jede Bewertung gegen
  den Vermoegenspfad: KALENDERJAHR-Bucket (ADR-2). Spalte t = Vermoegen am
  Ende des Kalenderjahres Stichjahr + t - 1. Hier 2 (Ende 2025).

Befund (Stand vor dem Fix, nach ADR-1a/ADR-2): der Solver bewertete auf dem
Bucket (2 -> 150 >= 100 -> erreicht), Haupt-Monte-Carlo und PDF/React auf
Spalte 1 (50 < 100 -> verfehlt) -- dasselbe Ziel, dasselbe Mandat, zwei
Verdikte. Der urspruengliche Reproducer verlangte zusaetzlich Gleichheit von
Router-Horizont und Pfadspalte; das ist seit ADR-2 eine Kategorie-
Verwechslung (siehe test_calendar_horizon_leap_anniversary_matrix.py) und
wird hier als die +0/+1-Beziehung geprueft.

GESCHLOSSEN 2026-10-25: Haupt-MC (``_year_index_for_goal``) und PDF/React
(``goal_classification``) lesen dieselbe Bucket-Spalte wie der Solver.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from routers import wealth as wealth_router
from services.calendar_horizon import calendar_years_until
from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine_mc_simulation import _year_index_for_goal
from services.pdf.components.goal_classification import (
    GOAL_STATUS_NICHT_ERREICHBAR,
    classify_goals,
)
from services.valuation_clock import bound_valuation_date


AS_OF = date(2024, 1, 1)
WEALTH_PATH = [100, 50, 150, 160]
TARGET_AMOUNT_RAPPEN = 100
HORIZON_YEARS = 3


def _make_goal(target_date: date) -> SimpleNamespace:
    return SimpleNamespace(
        id="goal-parity-1",
        label="Vermoegensziel Parity",
        goal_type="Vermoegensziel",
        target_amount_rappen=None,
        target_wealth_rappen=TARGET_AMOUNT_RAPPEN,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _pdf_react_index_and_status(goal: SimpleNamespace) -> tuple[int, str]:
    time_axis = [str(AS_OF.year + offset) for offset in range(len(WEALTH_PATH))]
    mc_payload = {
        "time_axis": time_axis,
        "p5": list(WEALTH_PATH),
        "p50": list(WEALTH_PATH),
        "p75": list(WEALTH_PATH),
    }
    [result] = classify_goals(
        [{"goal_id": goal.id, "target_date": goal.target_date, "target_amount_rappen": TARGET_AMOUNT_RAPPEN}],
        mc_payload,
    )
    return result["t_index"], result["status"]


def _channels(target_date: date) -> dict:
    goal = _make_goal(target_date)
    with bound_valuation_date(AS_OF):
        horizon = wealth_router._goal_horizon_from_date(target_date)
        optimizer = goal_to_liability(goal, horizon_years=HORIZON_YEARS).target_year_index
        main_mc = _year_index_for_goal(goal, AS_OF.year, HORIZON_YEARS)
    pdf_index, pdf_status = _pdf_react_index_and_status(goal)
    return {
        "horizon": horizon,
        "optimizer": optimizer,
        "main_mc": main_mc,
        "pdf_react": pdf_index,
        "pdf_status": pdf_status,
    }


@pytest.mark.parametrize(
    ("target_date", "expected_bucket"),
    [
        (date(2025, 1, 1), 2),   # exakter Jahrestag im Schaltjahr (Audit-Harness)
        (date(2025, 6, 30), 2),  # unterjaehrig im Folgejahr
        (date(2024, 11, 30), 1), # laufendes Kalenderjahr
        (date(2026, 1, 1), 3),   # zwei Jahre, letzter bewertbarer Bucket
    ],
)
def test_cross_channel_target_year_index_and_verdict_parity(target_date, expected_bucket):
    out = _channels(target_date)

    # Alle Bewertungen gegen den Pfad lesen dieselbe Spalte ...
    assert out["optimizer"] == out["main_mc"] == out["pdf_react"] == expected_bucket, out

    # ... und kommen damit zum selben Verdikt.
    column_success = WEALTH_PATH[expected_bucket] >= TARGET_AMOUNT_RAPPEN
    pdf_success = out["pdf_status"] != GOAL_STATUS_NICHT_ERREICHBAR
    assert pdf_success is column_success

    # Der kundenseitige Horizont ist die kanonische Jahreszahl (ADR-1a) und
    # liegt 0 oder 1 unter dem Bucket.
    with bound_valuation_date(AS_OF):
        assert out["horizon"] == max(1, calendar_years_until(target_date))
    assert expected_bucket - out["horizon"] in (0, 1)


def test_audit_harness_verdict_is_success_in_every_channel():
    """Das konkrete Audit-Beispiel: vorher Solver 'erreicht', Haupt-MC und
    PDF/React 'verfehlt'. Jetzt ueberall Spalte 2 (150 >= 100)."""
    out = _channels(date(2025, 1, 1))
    assert out["pdf_status"] != GOAL_STATUS_NICHT_ERREICHBAR
    assert WEALTH_PATH[out["main_mc"]] >= TARGET_AMOUNT_RAPPEN
    assert WEALTH_PATH[out["optimizer"]] >= TARGET_AMOUNT_RAPPEN
