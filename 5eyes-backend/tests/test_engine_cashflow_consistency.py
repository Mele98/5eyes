"""2026-06-14 (Roadmap #94 + #6): Regressions-Lock nach Kontroll-Audit.

#94: BEIDE Engine-Cashflow-Ladepfade (_load_allocation_inputs UND
     build_target_payload_from_allocation) MÜSSEN die vermögensgetriebenen
     Cashflows einspeisen. Der Audit fand, dass der Rebuild-Pfad das nicht tat
     (gefixt). Dieser Quellen-Guard verhindert einen Rückfall.
#6:  Die IST-Risikometriken (current_*) müssen vorhanden, nicht-negativ,
     symmetrisch zu target_* und deterministisch sein.
"""
from __future__ import annotations
import inspect
import sys
import uuid
import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401  — registriert ALLE Models (inkl. tenants) für create_all
import services.portfolio_engine as pe
from models.wealth import WealthPosition
from models.mandates import Mandate
# Harness aus dem Shadow-Test wiederverwenden (seedet Mandat + Depot + Goals + RP).
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# ── #94: Quellen-Guard — beide Ladepfade speisen derive_wealth_cashflows ein ──

def test_both_engine_paths_feed_derived_cashflows():
    src_load = inspect.getsource(pe._load_allocation_inputs)
    src_build = inspect.getsource(pe.build_target_payload_from_allocation)
    assert "derive_wealth_cashflows(all_positions)" in src_load, (
        "_load_allocation_inputs speist die vermögensgetriebenen Cashflows nicht mehr ein"
    )
    assert "derive_wealth_cashflows(all_positions)" in src_build, (
        "build_target_payload_from_allocation speist die vermögensgetriebenen "
        "Cashflows nicht ein (Audit-Bug 2026-06-14 wäre zurück!)"
    )


# ── Roadmap #39 (2026-08-07): dito fuer die optionale Steuer-Schaetzung ──

def test_both_engine_paths_feed_tax_estimate_cashflow():
    """Gleiche Bugklasse wie #94 oben: wenn nur EIN Ladepfad derive_tax_cashflow
    aufruft, sehen Cashflow-Ansicht und Strategie-Verzehr/Reserve wieder
    unterschiedliche Netto-Cashflows -- genau der Fehler, den #94 fuer die
    vermögensgetriebenen Cashflows bereits einmal gefixt hat."""
    src_load = inspect.getsource(pe._load_allocation_inputs)
    src_build = inspect.getsource(pe.build_target_payload_from_allocation)
    assert "derive_tax_cashflow(mandate, total_wealth_rappen)" in src_load, (
        "_load_allocation_inputs speist die geschätzte Vermögenssteuer nicht ein"
    )
    assert "derive_tax_cashflow(mandate, total_wealth_rappen)" in src_build, (
        "build_target_payload_from_allocation speist die geschätzte "
        "Vermögenssteuer nicht ein (inkonsistent zu _load_allocation_inputs)"
    )


def test_advisory_report_reserve_recompute_also_feeds_tax_estimate_cashflow():
    """Dritter Pfad (services/advisory_report.py::_recompute_reserve_reasoning)
    dokumentiert sich selbst als 'dieselben Inputs wie build_target_payload_
    from_allocation' -- muss die geschätzte Vermögenssteuer also ebenfalls
    einspeisen, sonst driftet die Reserve-Nachrechnung im Report von der
    Engine-Reserve ab."""
    import services.advisory_report as ar
    src = inspect.getsource(ar._recompute_reserve_reasoning)
    assert "derive_tax_cashflow(mandate, total_wealth_rappen)" in src, (
        "_recompute_reserve_reasoning speist die geschätzte Vermögenssteuer nicht ein"
    )


@pytest.mark.parametrize(
    ("assignment", "expected_solver_interest_bps"),
    [
        pytest.param("Beratungsvermögen", 0, id="advisory-interest-is-return"),
        pytest.param("Anderes Vermögen", 10000, id="external-interest-is-cashflow"),
    ],
)
def test_liquidity_interest_is_not_double_counted_in_solver_cashflows(
    session_factory,
    assignment,
    expected_solver_interest_bps,
):
    """Portfolio interest stays visible, but only external interest funds goals.

    The advised portfolio's CMA total return already contains its liquidity
    return. Its derived interest remains part of reporting/reserve cashflows,
    but must not enter the stochastic solver a second time. Interest from
    assets outside the advised portfolio is genuine external funding and must
    therefore remain in both series.
    """
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory,
        suffix=f"interest-{expected_solver_interest_bps}",
    )
    interest_rappen = 1_000_00
    position_id = f"pos-interest-{uuid.uuid4().hex[:8]}"

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.tax_estimate_in_cashflow_enabled = 0
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        session.add(WealthPosition(
            id=position_id,
            client_id=client_id,
            label=f"Zinskonto {assignment}",
            position_type="Liquidität",
            assignment=assignment,
            current_value_rappen=100_000_00,
            currency="CHF",
            valuation_date=datetime.date.today().isoformat(),
            liquidity_interest_rate_bps=100,
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        session.flush()
        with_interest = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    reporting_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_interest["cashflow_projection_series_rappen"],
            baseline["cashflow_projection_series_rappen"],
        )
    ]
    solver_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_interest["optimizer_cashflow_projection_series_rappen"],
            baseline["optimizer_cashflow_projection_series_rappen"],
        )
    ]
    assert reporting_delta and set(reporting_delta) == {interest_rappen}
    assert solver_delta == [
        interest_rappen * expected_solver_interest_bps // 10000
    ] * len(reporting_delta)
    derived_interest = next(
        cashflow
        for cashflow in with_interest["cashflows"]
        if getattr(cashflow, "origin_position_id", None) == position_id
    )
    assert derived_interest.amount_rappen == interest_rappen
    assert derived_interest.origin_assignment == assignment


def test_solver_removes_only_advisory_share_of_total_wealth_tax(
    session_factory,
):
    """External wealth tax remains a solver cashflow when only advisory wealth grows."""
    from services.wealth_cashflows import derive_tax_cashflow

    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory,
        suffix="tax-scope-500-500",
    )
    with session_factory() as session:
        session.add(WealthPosition(
            id=f"pos-external-tax-{uuid.uuid4().hex[:8]}",
            client_id=client_id,
            label="Externes Vermögen",
            position_type="Depot",
            assignment="Anderes Vermögen",
            current_value_rappen=500_000_00,
            currency="CHF",
            valuation_date=datetime.date.today().isoformat(),
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.tax_jurisdiction = "CH"
        mandate.tax_overrides_json = None
        mandate.tax_estimate_in_cashflow_enabled = 0
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        session.flush()
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        assert baseline["advisory_wealth_rappen"] == 500_000_00
        assert baseline["total_wealth_rappen"] == 1_000_000_00
        mandate.tax_estimate_in_cashflow_enabled = 1
        with_tax = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        total_tax_rappen = derive_tax_cashflow(
            mandate,
            with_tax["total_wealth_rappen"],
        )[0].amount_rappen
        advisory_tax_rappen = derive_tax_cashflow(
            mandate,
            with_tax["advisory_wealth_rappen"],
        )[0].amount_rappen

    external_tax_rappen = total_tax_rappen - advisory_tax_rappen
    assert total_tax_rappen == 400_000
    assert advisory_tax_rappen == 200_000
    assert external_tax_rappen == 200_000
    reporting_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_tax["cashflow_projection_series_rappen"],
            baseline["cashflow_projection_series_rappen"],
        )
    ]
    solver_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_tax["optimizer_cashflow_projection_series_rappen"],
            baseline["optimizer_cashflow_projection_series_rappen"],
        )
    ]
    assert reporting_delta and set(reporting_delta) == {-total_tax_rappen}
    assert solver_delta == [-external_tax_rappen] * len(reporting_delta)
    persisted_reporting_tax = next(
        cashflow
        for cashflow in with_tax["cashflows"]
        if getattr(cashflow, "source", None) == "tax_estimate"
    )
    assert persisted_reporting_tax.amount_rappen == total_tax_rappen


def _add_mortgage(session_factory, client_id, value=400_000_00, rate_bps=200,
                  amort_rappen=0, amort_type=None):
    with session_factory() as s:
        s.add(WealthPosition(
            id=f"pos-hyp-{uuid.uuid4().hex[:8]}", client_id=client_id,
            label="Hypothek EFH", position_type="Hypothek", assignment="Verbindlichkeit",
            current_value_rappen=value, mortgage_interest_rate_bps=rate_bps,
            mortgage_amortization_rappen=amort_rappen, mortgage_amortization_type=amort_type,
            mortgage_type="Festhypothek",
            currency="CHF", is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_generate_path_includes_mortgage_interest(session_factory):
    """Verhaltens-Gegenprobe: mit Hypothek steigt die wiederkehrende Ausgabe um
    den Zins (Beleg, dass der Generate-Pfad die abgeleiteten Cashflows nutzt)."""
    advisor_id, cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="cfc-gen")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        base = pe.generate_target_allocation(s, mandate, advisor_id, None)
    _add_mortgage(session_factory, cid)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        withmort = pe.generate_target_allocation(s, mandate, advisor_id, None)
    base_exp = int(base.get("recurring_expense_rappen", 0) or 0)
    mort_exp = int(withmort.get("recurring_expense_rappen", 0) or 0)
    assert mort_exp - base_exp >= 800_000, (base_exp, mort_exp)


# ── #6: IST-Risikometriken vorhanden, symmetrisch, deterministisch ──

def test_direct_amortization_improves_projection_vs_indirect(session_factory):
    """#31 Schritt B: direkte Amortisation baut die Schuld ab → sinkende Zinslast
    → die Projektions-Cashflow-Serie liegt höher als bei indirekter (Schuld bleibt).
    Differenz isoliert genau den Amortisations-Effekt (sonst identisches Setup)."""
    # Mandat A: direkte Amortisation 100k/J auf 500k @ 2%.
    advA, cidA, midA, _, _ = _seed_realistic_mandate(session_factory, suffix="amrt-dir")
    _add_mortgage(session_factory, cidA, value=500_000_00, rate_bps=200,
                  amort_rappen=100_000_00, amort_type="Direkt")
    # Mandat B: indirekte Amortisation (Schuld bleibt).
    advB, cidB, midB, _, _ = _seed_realistic_mandate(session_factory, suffix="amrt-indir")
    _add_mortgage(session_factory, cidB, value=500_000_00, rate_bps=200,
                  amort_rappen=100_000_00, amort_type="Indirekt")
    with session_factory() as s:
        rA = pe.generate_target_allocation(s, s.query(Mandate).filter(Mandate.id == midA).first(), advA, None)
    with session_factory() as s:
        rB = pe.generate_target_allocation(s, s.query(Mandate).filter(Mandate.id == midB).first(), advB, None)
    serA = rA.get("cashflow_projection_series_rappen") or []
    serB = rB.get("cashflow_projection_series_rappen") or []
    assert len(serA) > 3 and len(serB) > 3
    # Jahr 3: direkte Amort hat die Schuld auf 200k gesenkt -> Zins 4000 statt 10000
    # -> adj[3] = 6000 CHF = 600'000 Rappen mehr Netto als indirekt.
    delta = int(serA[3]) - int(serB[3])
    assert delta >= 400_000, (serA[:4], serB[:4], delta)


_RISK_FIELDS = [
    "var_95_1y_bps", "cvar_95_1y_bps", "max_drawdown_p50_bps",
    "loss_probability_1y_pct", "volatility_1y_bps",
]


def test_ist_risk_metrics_present_and_symmetric(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="cfc-risk")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = pe.generate_target_allocation(s, mandate, advisor_id, None)
    mc = result.get("monte_carlo") or {}
    for base in _RISK_FIELDS:
        for side in ("target", "current"):
            key = f"{side}_{base}"
            assert key in mc, f"MC-Feld fehlt: {key}"
            assert mc[key] is not None and int(mc[key]) >= 0, (key, mc[key])


def test_ist_risk_metrics_deterministic(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="cfc-det")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        mc1 = (pe.generate_target_allocation(s, mandate, advisor_id, None).get("monte_carlo") or {})
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        mc2 = (pe.generate_target_allocation(s, mandate, advisor_id, None).get("monte_carlo") or {})
    for base in _RISK_FIELDS:
        key = f"current_{base}"
        assert mc1.get(key) == mc2.get(key), (key, mc1.get(key), mc2.get(key))
