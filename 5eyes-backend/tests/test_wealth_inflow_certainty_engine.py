"""INFLOW-CERTAINTY-001: unsichere Vermoegenszufluesse (CIO-Entscheid 2026-10-21).

Vorher galt jeder WealthInflow als sicher: er senkte die Liquiditaetsreserve
(services/portfolio_engine_reserve.py, near_term_inflow_series) und floss voll
in die Simulation. Konservativ gilt jetzt:

- ``sicher`` (Default; NULL-Bestand = sicher) -> unveraendertes Verhalten.
- ``unsicher`` -> weder Reserve noch Simulation; nur Reasoning
  "nicht eingerechnet (unsicher)" + Info-Sensitivitaet "mit Zufluss".
- verknuepfter Vorsorgebezug (linked_position_id) -> immer sicher.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

import services.portfolio_engine as pe
from models.allocation import CapitalMarketAssumption, TargetAllocation
from models.mandates import Mandate
from models.wealth import Cashflow, WealthInflow
from services.wealth_inflow_certainty import (
    effective_certainty,
    split_by_certainty,
)
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _reload_payload,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)

FINAL_WEIGHTS = {
    "equities": 5000,
    "bonds": 3000,
    "real_estate": 500,
    "alternatives": 1000,
    "liquidity": 500,
}
INFLOW_AMOUNT = 400_000_00


@pytest.fixture(autouse=True)
def _fast_reporting_layers(monkeypatch):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _seed(session_factory, suffix: str, *, certainty):
    """Realistisches Mandat + negativer Netto-Cashflow + optional ein Zufluss.

    Der Ausgaben-Cashflow macht den Reserve-Effekt eines Zuflusses sichtbar:
    ein sicherer Zufluss im Startjahr deckt den Nahbedarf und senkt die
    Reserve; ein unsicherer darf das nicht.
    """
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=suffix,
    )
    with session_factory() as session:
        session.add(Cashflow(
            id=f"cf-expense-{suffix}", client_id=client_id, label="Lebenshaltung",
            cashflow_type="Expense", amount_rappen=90_000_00, currency="CHF",
            frequency="jährlich", nature="wiederkehrend", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        if certainty != "none":
            kwargs = {} if certainty == "legacy-null" else {"certainty": certainty}
            inflow = WealthInflow(
                id=f"inflow-{suffix}-{uuid.uuid4()}", client_id=client_id,
                mandate_id=mandate_id, label="Erbschaft Tante",
                source_type="Erbschaft", amount_rappen=INFLOW_AMOUNT,
                expected_year=date.today().year, is_recurring=0,
                frequency="einmalig", value_mode="nominal", is_active=1,
                created_at=_now(), updated_at=_now(), **kwargs,
            )
            session.add(inflow)
            session.flush()
            if certainty == "legacy-null":
                # Bestandszeile vor der Migration: Spalte NULL.
                session.execute(
                    WealthInflow.__table__.update()
                    .where(WealthInflow.id == inflow.id)
                    .values(certainty=None)
                )
        session.commit()
    return advisor_id, mandate_id


def _loaded(session_factory, mandate_id):
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).one()
        return pe._load_allocation_inputs(
            session, mandate, simulation_prefs=_preferences()["simulation"], cma=cma,
        )


def test_effective_certainty_null_is_certain_and_linked_is_always_certain():
    assert effective_certainty(SimpleNamespace(certainty=None)) == "sicher"
    assert effective_certainty(SimpleNamespace()) == "sicher"
    assert effective_certainty(SimpleNamespace(certainty="unsicher")) == "unsicher"
    assert effective_certainty(
        SimpleNamespace(certainty="unsicher", linked_position_id="pos-3a")
    ) == "sicher"
    with pytest.raises(ValueError, match="certainty"):
        effective_certainty(SimpleNamespace(certainty="vielleicht"))
    rows = [SimpleNamespace(id=i, certainty=c) for i, c in enumerate(["sicher", "unsicher", None])]
    certain, uncertain = split_by_certainty(rows)
    assert [r.id for r in certain] == [0, 2]
    assert [r.id for r in uncertain] == [1]


@pytest.mark.parametrize("certainty", ["sicher", "legacy-null"])
def test_certain_and_legacy_inflows_keep_feeding_the_simulation(session_factory, certainty):
    _advisor, mandate_id = _seed(session_factory, f"cert-{certainty}", certainty=certainty)
    loaded = _loaded(session_factory, mandate_id)
    assert len(loaded["wealth_inflows"]) == 1
    assert loaded["uncertain_wealth_inflows"] == []
    assert loaded["inflow_projection_series_rappen"][0] == INFLOW_AMOUNT


def test_uncertain_inflow_is_not_in_simulation_series(session_factory):
    _advisor, mandate_id = _seed(session_factory, "unc-load", certainty="unsicher")
    _advisor0, baseline_mandate_id = _seed(session_factory, "unc-load-base", certainty="none")
    loaded = _loaded(session_factory, mandate_id)
    baseline = _loaded(session_factory, baseline_mandate_id)
    assert loaded["wealth_inflows"] == []
    assert [i.label for i in loaded["uncertain_wealth_inflows"]] == ["Erbschaft Tante"]
    assert not any(loaded["inflow_projection_series_rappen"])
    # Simulation sieht exakt die Cashflows ohne Zufluss.
    assert loaded["cashflow_projection_series_rappen"] == baseline["cashflow_projection_series_rappen"]
    assert (
        loaded["optimizer_cashflow_projection_series_rappen"]
        == baseline["optimizer_cashflow_projection_series_rappen"]
    )


def test_uncertain_inflow_does_not_lower_reserve_and_is_reported(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    results = {}
    for certainty in ("none", "sicher", "unsicher"):
        advisor_id, mandate_id = _seed(session_factory, f"res-{certainty}", certainty=certainty)
        _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
        results[certainty] = (
            _generate(session_factory, mandate_id, advisor_id, _preferences()),
            mandate_id,
        )
    baseline = results["none"][0]
    certain = results["sicher"][0]
    uncertain, uncertain_mandate_id = results["unsicher"]

    # Positivkontrolle: der Testaufbau hat einen reservewirksamen Zufluss --
    # ein SICHERER Zufluss senkt die Reserve wirklich.
    assert baseline["reserve_needed_rappen"] > 0
    assert certain["reserve_needed_rappen"] < baseline["reserve_needed_rappen"]
    assert certain["uncertain_inflow_sensitivity"] is None

    # Kern: der unsichere Zufluss aendert weder Reserve noch Projektion.
    assert uncertain["reserve_needed_rappen"] == baseline["reserve_needed_rappen"]
    assert uncertain["external_reserve_rappen"] == baseline["external_reserve_rappen"]
    assert (
        uncertain["cashflow_projection_series_rappen"]
        == baseline["cashflow_projection_series_rappen"]
    )

    joined = "\n".join(uncertain["reasoning"])
    assert "Erbschaft Tante" in joined
    assert "nicht eingerechnet (unsicher)" in joined
    assert "Info-Sensitivitaet 'mit Zufluss'" in joined

    info = uncertain["uncertain_inflow_sensitivity"]
    assert info["informational_only"] is True
    assert info["label"] == "mit Zufluss"
    assert info["in_horizon_amount_rappen"] == INFLOW_AMOUNT
    assert info["without_inflow"]["reserve_needed_rappen"] == baseline["reserve_needed_rappen"]
    # "mit Zufluss" entspricht der Reserve, die ein SICHERER Zufluss ergaebe.
    assert info["with_inflow"]["reserve_needed_rappen"] == certain["reserve_needed_rappen"]

    # Reload (rebuild-Pfad) rechnet dieselbe Reserve -> keine Drift.
    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == uncertain["target_allocation"].id
        ).one()
        payload = _reload_payload(session, allocation)
        assert payload["reserve_needed_rappen"] == uncertain["reserve_needed_rappen"]
    assert uncertain_mandate_id
