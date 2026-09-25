"""GESAMTVERMOEGEN-FOUNDATION-LIABILITY-SCOPE-001 (Kontrollrunde 2026-09-25).

services/portfolio_engine.py::generate_target_allocation() (und der
analoge Rebuild-Pfad) speiste in _build_total_wealth_allocation()
(services/portfolio_engine_gesamtvermoegen.py) bisher `total_liabilities_
rappen` ein -- die Summe ALLER Verbindlichkeits-Positionen des Kunden,
nicht nur der Hypothek. Das "Fundament" (netto Hypothek, siehe Docstring
dort) wurde dadurch faelschlich auch von voellig unverbundenen
Verbindlichkeiten (Privatkredit, Geschaeftsdarlehen, etc.) aufgezehrt,
BEVOR ueberhaupt liquide Finanz-Buckets angetastet werden -- eine als
Aktien/Fundament gehaltene Position wurde so im schlimmsten Fall
faelschlich auf 0 gerechnet, obwohl die Immobilie selbst kaum belastet
ist.

Etabliertes Muster an anderer Stelle in genau diesem Modul (PROPERTY-
COLLATERAL-001, services/wealth_position_semantics.py::
is_mortgage_position) unterscheidet Hypotheken-Verbindlichkeiten
explizit von anderen -- diese Unterscheidung fehlte nur hier.

Fix: eine separate `mortgage_liabilities_rappen` (nur position_type==
"Hypothek") wird jetzt an _build_total_wealth_allocation() uebergeben.
total_liabilities_rappen (ALLE Verbindlichkeiten) bleibt fuer
total_wealth_rappen/Simulationspfade unveraendert.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import Base
from models.allocation import OptimizerPolicy
from models.mandates import Mandate
from models.users import User
from models.wealth import WealthPosition

from routers.profiling import create_risk_assessment
from test_current_anchor_uniqueness import (  # noqa: E402
    _policy_row,
    _request_stub,
    _risk_payload,
    _seed_advisor_and_mandate,
)

import services.portfolio_engine as pe


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def orm_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_prereqs(orm_engine, monkeypatch, *, mandate_id="mandate-anchor"):
    # Bewusst KEINE eigene OptimizerPolicy vorab anlegen: ensure_runtime_
    # reference_data() seedet die CH-Default-Policy inkl. vollstaendiger
    # HouseMatrix nur, wenn noch keine Policy existiert.
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    _seed_advisor_and_mandate(orm_engine)
    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-anchor")
        create_risk_assessment(
            mandate_id, _risk_payload(), _request_stub(), db=session, current_user=advisor,
        )
        session.commit()
    return mandate_id


def _add_position(session, **overrides):
    values = dict(
        id="pos",
        client_id="client-anchor",
        label="Position",
        position_type="Depot",
        assignment="Anderes Vermögen",
        current_value_rappen=0,
        currency="CHF",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    values.update(overrides)
    session.add(WealthPosition(**values))


def test_non_mortgage_liability_does_not_erode_the_property_foundation(
    orm_engine, monkeypatch,
):
    """Kern-Repro: Eigenheim 800k, Hypothek 300k (Fundament sollte 500k
    sein) PLUS ein voellig unabhaengiger Privatkredit 200k. Vor dem Fix
    wurde das Fundament faelschlich auf 300k gedrueckt (800k - 300k -
    200k), weil der Privatkredit mitgezaehlt wurde."""
    mandate_id = _seed_prereqs(orm_engine, monkeypatch)
    with Session(orm_engine) as session:
        _add_position(
            session, id="depot", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=100_000_00,
            alloc_equities_bps=10000,
        )
        _add_position(
            session, id="house", position_type="Immobilien",
            current_value_rappen=800_000_00, asset_expected_return_bps=0,
        )
        _add_position(
            session, id="mortgage", position_type="Hypothek",
            assignment="Verbindlichkeit", current_value_rappen=300_000_00,
        )
        _add_position(
            session, id="personal-loan", position_type="Custom",
            assignment="Verbindlichkeit", current_value_rappen=200_000_00,
        )
        session.commit()

    with Session(orm_engine) as session:
        mandate = session.get(Mandate, mandate_id)
        result = pe.generate_target_allocation(session, mandate, "advisor-anchor", preferences=None)

    total_allocation = result["total_allocation"]
    # Vor dem Fix: foundation_rappen == 30_000_000 (800k - 300k - 200k).
    assert total_allocation["foundation_rappen"] == 500_000_00, total_allocation


def test_mortgage_only_liability_still_nets_correctly(orm_engine, monkeypatch):
    """Gegenprobe: ohne unabhaengige Verbindlichkeit bleibt das Verhalten
    unveraendert (reine Hypotheken-Verrechnung, wie vor diesem Fix)."""
    mandate_id = _seed_prereqs(orm_engine, monkeypatch, mandate_id="mandate-anchor")
    with Session(orm_engine) as session:
        _add_position(
            session, id="depot", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=100_000_00,
            alloc_equities_bps=10000,
        )
        _add_position(
            session, id="house", position_type="Immobilien",
            current_value_rappen=800_000_00, asset_expected_return_bps=0,
        )
        _add_position(
            session, id="mortgage", position_type="Hypothek",
            assignment="Verbindlichkeit", current_value_rappen=300_000_00,
        )
        session.commit()

    with Session(orm_engine) as session:
        mandate = session.get(Mandate, mandate_id)
        result = pe.generate_target_allocation(session, mandate, "advisor-anchor", preferences=None)

    assert result["total_allocation"]["foundation_rappen"] == 500_000_00
