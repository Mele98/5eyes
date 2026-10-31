"""End-to-End-Regressionslocks fuer die Methodik-Aenderungen vom 2026-06-17.

Nagelt ueber generate_target_allocation (echter Lauf auf geseedetem Mandat) fest:
  1. Determinismus  — gleiche Eingaben -> identische SAA + identische Verlaufsserien.
  2. Itô-Median-Konsistenz — der deterministische Hauptpfad (target_mix_series) liegt
     beim MC-Median (target_p50), nicht optimistisch darueber (war der arithmetische
     1+r-Bug). Schuetzt die SOLL/IST-Hauptlinie vor erneutem Auseinanderlaufen.
  3. Zielerreichungs-Kontrakt — median_achievement_pct in [0,100], shortfall >= 0.

Reiner Test (keine Produktionsaenderung). Nutzt die bestehende Seed-Fixture.
"""
from __future__ import annotations

from main import app  # noqa: F401 - registriert alle SQLAlchemy-Modelle
from models.mandates import Mandate
import services.portfolio_engine as pe
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


_PREFS = {
    "policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
    "assetClasses": {}, "simulation": {"monteCarloRuns": 250},
}


def _generate(session_factory, mandate_id, advisor_id):
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        return pe.generate_target_allocation(session, mandate, advisor_id, preferences=_PREFS)


def _alloc_bps(result):
    # target_allocation ist ein ORM-Objekt (TargetAllocation), kein dict.
    ta = result.get("target_allocation")
    return tuple(int(getattr(ta, k, 0) or 0) for k in (
        "target_equities_bps", "target_bonds_bps", "target_real_estate_bps",
        "target_alternatives_bps", "target_liquidity_bps"))


def test_determinismus_identische_saa_und_serien(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="methodik-det")
    a = _generate(session_factory, mid, advisor_id)
    b = _generate(session_factory, mid, advisor_id)
    assert _alloc_bps(a) == _alloc_bps(b), "SAA nicht deterministisch"
    sa = (a.get("simulation") or {}).get("target_mix_series_rappen") or []
    sb = (b.get("simulation") or {}).get("target_mix_series_rappen") or []
    assert sa == sb and len(sa) > 1, "Hauptpfad nicht deterministisch"
    ma = (a.get("monte_carlo") or {}).get("target_p50_series_rappen") or []
    mb = (b.get("monte_carlo") or {}).get("target_p50_series_rappen") or []
    assert ma == mb, "MC-Median nicht deterministisch"


def test_hauptpfad_liegt_beim_mc_median_nicht_darueber(session_factory):
    """Itô-Konsistenz: deterministischer Endwert ~ MC-p50-Endwert (nicht arithmetisch
    darueber). Toleranz grosszuegig gegen MC-Rauschen, aber eng genug, um eine
    Rueckkehr zur 1+r-Linie (die ueber dem Median laege) zu fangen."""
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="methodik-ito")
    r = _generate(session_factory, mid, advisor_id)
    det = (r.get("simulation") or {}).get("target_mix_series_rappen") or []
    p50 = (r.get("monte_carlo") or {}).get("target_p50_series_rappen") or []
    assert len(det) > 1 and len(p50) > 1
    det_end, p50_end = float(det[-1]), float(p50[-1])
    assert p50_end > 0
    rel = abs(det_end - p50_end) / p50_end
    assert rel < 0.20, f"Hauptpfad {det_end:.0f} weicht {rel:.0%} vom MC-Median {p50_end:.0f} ab (Itô-Konsistenz verletzt?)"


def test_zielerreichungs_kontrakt(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="methodik-goal")
    r = _generate(session_factory, mid, advisor_id)
    goals = r.get("goal_analysis") or []
    assert goals, "keine Zielanalyse"
    for g in goals:
        assert "median_achievement_pct" in g, "PAR-3-Kontrakt: median_achievement_pct fehlt"
        assert 0 <= int(g.get("median_achievement_pct", 0)) <= 100
        assert int(g.get("pessimistic_shortfall_rappen", 0)) >= 0
