"""LIQ-INSTRUMENT-KONTOGUTHABEN-001 (Assetallocation-Audit 2026-10-14).

"Kontoguthaben" is one of the three liquidity instruments the Anlagepraeferenzen
dialog offers (schemas/allocation.py accepts it, a BuildingBlock is seeded for
it), but ``_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS`` had no CMA row. Every
strategy calculation with that choice failed -- live, from the real UI:
``409 Invalid CMA model input: sub_allocations[9] has no CMA assumption for
'Kontoguthaben'``.

The added default is deliberately the most conservative one: no interest is
assumed (0 bps), volatility like Festgeld. An investment committee can override
it per CMA; existing CMA rows inherit missing keys from the defaults.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
from models import tenant as _tenant  # noqa: F401

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate
from schemas.allocation import AllocationPreferencesPayload
from test_optimizer_integration import _seed_realistic_mandate


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    engine = create_engine(f"sqlite:///{tmp_path / 'konto.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    adv, _cid, mid, _ = _seed_realistic_mandate(SF, "konto")
    yield SF, adv, mid
    engine.dispose()


def _generate(SF, adv, mid, prefs):
    AllocationPreferencesPayload(**prefs)  # the UI choice is schema-valid
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        try:
            return pe.generate_target_allocation(s, mandate, adv, prefs)
        finally:
            s.rollback()


@pytest.mark.parametrize("instrument", ["Geldmarktfonds", "Kontoguthaben", "Festgeld"])
def test_every_offered_liquidity_instrument_is_generatable(ctx, instrument):
    result = _generate(*ctx, {"assetClasses": {"liquidityInstrument": instrument}})
    ta = result["target_allocation"]
    assert ta.optimization_method == "stochastic"
    assert sum(int(getattr(ta, f"target_{b}_bps")) for b in pe.BUCKET_FIELDS) == 10000


def test_kontoguthaben_default_assumes_no_interest():
    row = pe._DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Kontoguthaben"]
    assert row["asset_class"] == "Liquiditaet"
    # Conservative-values rule: never above the lowest existing liquidity row.
    liquidity_returns = [
        int(v["expected_return_bps"])
        for k, v in pe._DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.items()
        if v["asset_class"] == "Liquiditaet" and k != "Kontoguthaben"
    ]
    assert int(row["expected_return_bps"]) == 0 <= min(liquidity_returns)
