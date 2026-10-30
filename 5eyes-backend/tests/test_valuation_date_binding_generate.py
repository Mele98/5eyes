"""ADR-1b/1c End-to-End: der Lauf bindet und persistiert seinen Stichtag.

GOAL-CALENDAR-HORIZON-PARITY-001 (Reparaturvertrag 1, 2, 4, 6):
* ``generate_target_allocation`` bindet den Stichtag einmal und schreibt ihn
  nach ``target_allocations.valuation_date``;
* der Input-Hash enthaelt ihn (gleiche Rohdaten, anderer Stichtag -> anderer
  Hash);
* der Reload (``build_target_payload_from_allocation``) rechnet mit dem
  GESPEICHERTEN Stichtag, auch wenn die Wanduhr inzwischen ein neues Jahr
  zeigt -- die Allokation wird dadurch weder stale noch auf eine andere
  Zeitachse umgerechnet.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import services.portfolio_engine as portfolio_engine
import services.valuation_clock as valuation_clock
from database import Base
from models.allocation import CapitalMarketAssumption, OptimizerPolicy
from models.mandates import Mandate
from models.profiling import RiskAssessment
from services.valuation_clock import bound_valuation_date
from tests.test_golden_snapshot_ch_regression import _seed_ch_mandate


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'valuation_binding.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _NextYear(date):
    @classmethod
    def today(cls):
        real = date.today()
        return date(real.year + 1, 1, 15)


def _reload(s, mandate, allocation):
    policy = s.get(OptimizerPolicy, allocation.policy_id)
    cma = s.get(CapitalMarketAssumption, allocation.capital_market_assumptions_id)
    assessment = s.get(RiskAssessment, allocation.based_on_assessment_id)
    return portfolio_engine.build_target_payload_from_allocation(
        s, mandate, allocation, policy, cma, assessment, None,
        input_snapshot_check_only=True,
    )


def test_generate_persists_the_bound_date_and_reload_replays_it(session_factory, monkeypatch):
    advisor_id, _cid, mid, _aid = _seed_ch_mandate(session_factory, suffix="valbind", score_x10=50)
    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        result = portfolio_engine.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        allocation = result["target_allocation"]
        s.commit()
        stored = allocation.valuation_date
        assert stored == date.today().isoformat()

        # Wanduhr springt ins naechste Jahr: der Reload bindet den gespeicherten
        # Stichtag, die Cashflow-Achse bleibt im Jahr des Laufs, der Hash passt.
        seen_years: list[int] = []
        original_totals = portfolio_engine.totals_for_year

        def _spy(*args, **kwargs):
            seen_years.append(valuation_clock.valuation_date().year)
            return original_totals(*args, **kwargs)

        monkeypatch.setattr(valuation_clock, "date", _NextYear)
        monkeypatch.setattr(portfolio_engine, "totals_for_year", _spy)
        assert _reload(s, mandate, allocation) == {"input_snapshot_current": True}
        assert seen_years and set(seen_years) == {date.fromisoformat(stored).year}


def test_same_inputs_on_a_different_valuation_date_hash_differently(session_factory):
    advisor_id, _cid, mid, _aid = _seed_ch_mandate(session_factory, suffix="valhash", score_x10=50)
    real_today = date.today()
    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        with bound_valuation_date(real_today):
            first = portfolio_engine.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        first_alloc = first["target_allocation"]
        first_hash, first_date = first_alloc.input_snapshot_hash, first_alloc.valuation_date
        s.commit()
        # Gleicher Tag, gleiche Inputs: identischer Hash (Idempotenz bleibt).
        with bound_valuation_date(real_today):
            again = portfolio_engine.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert again["target_allocation"].input_snapshot_hash == first_hash
        s.commit()
        # Anderer Stichtag im selben Kalenderjahr: anderer Hash, anderer Anker.
        other_day = date(real_today.year, 1, 2) if real_today != date(real_today.year, 1, 2) else date(real_today.year, 1, 3)
        with bound_valuation_date(other_day):
            other = portfolio_engine.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert other["target_allocation"].valuation_date == other_day.isoformat()
        assert other["target_allocation"].input_snapshot_hash != first_hash
        assert first_date == real_today.isoformat()
