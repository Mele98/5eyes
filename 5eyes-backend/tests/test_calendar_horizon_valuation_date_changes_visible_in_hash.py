"""GOAL-CALENDAR-HORIZON-PARITY-001 (round 38) / ADR-1c -- Stichtag im Input-Hash.

Befund: ``_compute_input_snapshot_hash()`` hatte keinen Eingang fuer den
Bewertungsstichtag. Zwei Laeufe mit identischen Rohdaten an verschiedenen
Stichtagen -- deren Liabilities sich unterscheiden -- bekamen denselben Hash;
ein Staleness-Detektor auf diesem Hash konnte den Unterschied nicht sehen.

GESCHLOSSEN 2026-10-25 (ADR-1b/1c): ``generate_target_allocation`` legt den
gebundenen Stichtag in den Projektionskontext des Input-Hashes und persistiert
ihn an der Allokation; der Reload rechnet den Hash mit dem GESPEICHERTEN
Stichtag nach (gebunden per ``binds_allocation_valuation_date``). Bestand ohne
Stichtag behaelt den Hash ohne Stichtag. End-to-End-Nachweis mit echtem
Generate: ``tests/test_valuation_date_binding_generate.py``.

Der urspruengliche Reproducer verglich zwei aufeinanderfolgende Tage; seit
ADR-2 (Kalenderjahr-Buckets) flippt die Liability dort nicht mehr, die
Vorbedingung war damit veraltet. Der Flip liegt jetzt am Jahreswechsel.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import Base  # noqa: E402,F401
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402
from services.portfolio_engine import _compute_input_snapshot_hash  # noqa: E402

NEW_YEARS_EVE = date(2026, 12, 31)
NEW_YEAR = date(2027, 1, 1)
TARGET_DATE = date(2027, 10, 5)


def _make_wealth_goal() -> SimpleNamespace:
    return SimpleNamespace(
        id="g-valuation-date-hash",
        mandate_id="mandate-1",
        client_id="client-1",
        goal_family="Vermoegen",
        goal_type="Vermoegensziel",
        label="Vermoegensziel Valuation-Date Hash",
        rank=1,
        weight_bps=None,
        goal_scope="Beratungsvermoegen",
        value_mode="nominal",
        target_amount_rappen=None,
        target_wealth_rappen=100_00,
        target_return_bps=None,
        success_probability_min_x100=None,
        start_date=None,
        horizon_years=None,
        target_date=TARGET_DATE.isoformat(),
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        probability_pct=None,
        pension_pillar=None,
        linked_position_id=None,
        is_active=1,
    )


def _hash(goal, valuation_date: date | None) -> str:
    context = {} if valuation_date is None else {"valuation_date": valuation_date.isoformat()}
    return _compute_input_snapshot_hash(
        advisory_positions=[],
        all_positions=[],
        cashflows=[],
        goals=[goal],
        advisory_wealth_rappen=0,
        total_wealth_rappen=0,
        projection_context=context,
    )


def test_valuation_date_change_that_flips_the_liability_also_changes_the_hash():
    goal = _make_wealth_goal()
    before = goal_to_liability(goal, horizon_years=10, as_of=NEW_YEARS_EVE)
    after = goal_to_liability(goal, horizon_years=10, as_of=NEW_YEAR)
    # Vorbedingung: die Wirtschaftlichkeit unterscheidet sich wirklich.
    assert before.target_year_index != after.target_year_index

    assert _hash(goal, NEW_YEARS_EVE) != _hash(goal, NEW_YEAR)


def test_same_valuation_date_reproduces_the_hash():
    goal = _make_wealth_goal()
    assert _hash(goal, NEW_YEARS_EVE) == _hash(goal, NEW_YEARS_EVE)


def test_snapshot_hash_is_a_pure_function_of_its_inputs():
    """Ohne Stichtag-Eintrag (Bestand vor ADR-1b) bleibt der Hash, was er war:
    deterministisch und ohne Stichtag -- der Reload rechnet fuer solche
    Allokationen genau diese Form nach."""
    goal = _make_wealth_goal()
    assert _hash(goal, None) == _hash(goal, None)
    assert _hash(goal, None) != _hash(goal, NEW_YEARS_EVE)
