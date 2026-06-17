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
