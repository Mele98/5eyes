"""GOAL-REAL-SPENDING-INFLATION-PARITY-001 (Kontrollrunde 40) -- reale Ausgabenziele.

Befund: der Solver (``goal_liabilities``) hob ein ``value_mode='real'``-
Ausgabenziel mit der CMA-Inflation auf das Faelligkeitsjahr; Reserve,
deterministische Zielanalyse und Haupt-Monte-Carlo nahmen den Rohbetrag.
Audit-Repro: reale Einmalausgabe CHF 100 (hier 10'000 Rappen) in genau zwei
Kalenderjahren, Inflation 10 %/10 %, Vermoegen 11'000 -> Solver 'nicht
erreichbar' (braucht 12'100), Reserve 'gedeckt' (braucht 10'000).

GESCHLOSSEN 2026-10-25 (Owner-Entscheid 7b): Reserve, Zielanalyse und
Haupt-MC rufen dieselben Helfer wie der Solver
(``portfolio_engine_reserve._real_expense_value_rappen`` ->
``_is_real_value_mode`` / ``_inflate_at_year`` / ``_calendar_bucket_index``).
Ohne Inflationspfad gibt es fuer ein reales Ziel keine Zahl (fail-closed).

Der fruehere Reproducer pinnte den Defekt als Zwischenschritt (``reserve ==
Rohbetrag``) und lag mit Horizont 2 zudem ausserhalb des Liability-Pfads
(Faelligkeit im Kalenderjahr-Bucket 3); beides ist hier korrigiert.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: F401
from models import allocation as _alloc_models  # noqa: F401
from models import clients as _client_models  # noqa: F401
from models import mandates as _mandate_models  # noqa: F401
from models import profiling as _prof_models  # noqa: F401
from models import review as _review_models  # noqa: F401
from models import snapshots as _snap_models  # noqa: F401
from models import users as _user_models  # noqa: F401
from models import wealth as _wealth_models  # noqa: F401
from sqlalchemy.orm import configure_mappers

configure_mappers()

from models.wealth import Goal  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402
from services.optimizer.objective import goal_probability_per_path  # noqa: E402
from services.portfolio_engine import _goal_reserve_for_goal  # noqa: E402
from services.portfolio_engine_mc_simulation import _recurring_outflow_total_rappen  # noqa: E402
from services.portfolio_engine_reserve import (  # noqa: E402
    RealGoalInflationMissingError,
    _real_expense_value_rappen,
)
from services.valuation_clock import bound_valuation_date  # noqa: E402

VALUATION = datetime.date(2026, 10, 25)
_INFLATION_SERIES_BPS = [1000, 1000, 1000]
_AVAILABLE_WEALTH_RAPPEN = 11_000
_HORIZON_YEARS = 3
_RAW_TARGET_RAPPEN = 10_000
_INFLATED_RAPPEN = 12_100  # 10'000 * 1.10 * 1.10 (zwei Jahre, Faktor 1.0 im laufenden Jahr)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _goal(*, value_mode: str = "real", goal_type: str = "Einmalige_Ausgabe", **extra) -> Goal:
    fields = dict(
        id="g-real-expense-1",
        mandate_id="m-1",
        client_id="c-1",
        goal_family="Konsum",
        goal_type=goal_type,
        label="Reale Einmalausgabe (Kueche)",
        rank=1,
        weight_bps=10_000,
        goal_scope="Beratungsvermoegen",
        value_mode=value_mode,
        target_amount_rappen=_RAW_TARGET_RAPPEN,
        target_date=VALUATION.replace(year=VALUATION.year + 2).isoformat(),
        is_ongoing=0,
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    fields.update(extra)
    return Goal(**fields)


def test_optimizer_and_reserve_consumers_agree_on_real_expense_goal_achievability():
    goal = _goal()
    with bound_valuation_date(VALUATION):
        liability = goal_to_liability(
            goal, horizon_years=_HORIZON_YEARS, inflation_series_bps=_INFLATION_SERIES_BPS,
        )
        reserve_needed = _goal_reserve_for_goal(goal, _INFLATION_SERIES_BPS)
        analysis_target = _real_expense_value_rappen(goal, _RAW_TARGET_RAPPEN, _INFLATION_SERIES_BPS)

    # Dieselbe Zahl in allen Kanaelen.
    assert liability.target_amount_rappen == _INFLATED_RAPPEN
    assert liability.liability_path_rappen == [0, 0, _INFLATED_RAPPEN]
    assert reserve_needed == _INFLATED_RAPPEN
    assert analysis_target == _INFLATED_RAPPEN

    # Dasselbe Verdikt: 11'000 reichen fuer 12'100 nicht.
    wealth = [float(_AVAILABLE_WEALTH_RAPPEN)]
    for outflow in liability.liability_path_rappen:
        wealth.append(wealth[-1] - outflow)
    optimizer_achievable = bool(
        goal_probability_per_path(np.array([wealth]), liability, _AVAILABLE_WEALTH_RAPPEN)[0]
    )
    reserve_achievable = _AVAILABLE_WEALTH_RAPPEN >= reserve_needed
    assert optimizer_achievable is False
    assert optimizer_achievable == reserve_achievable


def test_recurring_real_goal_matches_the_solver_path_in_the_main_mc():
    goal = _goal(
        goal_type="Wiederkehrende_Ausgabe",
        frequency="jaehrlich",
        start_date=VALUATION.replace(year=VALUATION.year + 1).isoformat(),
        target_date=VALUATION.replace(year=VALUATION.year + 2).isoformat(),
        target_amount_rappen=1_000,
    )
    with bound_valuation_date(VALUATION):
        liability = goal_to_liability(
            goal, horizon_years=_HORIZON_YEARS, inflation_series_bps=_INFLATION_SERIES_BPS,
        )
        mc_total = _recurring_outflow_total_rappen(
            goal, VALUATION.year, _HORIZON_YEARS, _INFLATION_SERIES_BPS,
        )
        reserve = _goal_reserve_for_goal(goal, _INFLATION_SERIES_BPS)
    assert liability.liability_path_rappen == [0, 1_100, 1_210]
    assert mc_total == sum(liability.liability_path_rappen)
    # Reserve: Jahresbetrag zur ersten Faelligkeit (ein Jahr Inflation).
    assert reserve == 1_100


def test_nominal_goal_is_unchanged_in_every_channel():
    goal = _goal(value_mode="nominal")
    with bound_valuation_date(VALUATION):
        assert goal_to_liability(goal, horizon_years=_HORIZON_YEARS, inflation_series_bps=_INFLATION_SERIES_BPS).target_amount_rappen == _RAW_TARGET_RAPPEN
        assert _goal_reserve_for_goal(goal, _INFLATION_SERIES_BPS) == _RAW_TARGET_RAPPEN
        assert _goal_reserve_for_goal(goal) == _RAW_TARGET_RAPPEN


def test_real_goal_without_inflation_path_fails_closed():
    with bound_valuation_date(VALUATION):
        with pytest.raises(RealGoalInflationMissingError):
            _goal_reserve_for_goal(_goal())
