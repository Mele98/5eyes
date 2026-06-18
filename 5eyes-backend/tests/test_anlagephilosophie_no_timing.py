"""Anlagephilosophie-Lock (#93): KEIN Markt-Timing / keine aktive Markt-Reaktion.

Die strategische Allokation (SAA) wird ausschliesslich aus Risikoprofil, Zielen,
Praeferenzen und den LANGFRISTIGEN Kapitalmarktannahmen (CMA) abgeleitet — nicht aus
kurzfristigen Markt-/Display-Parametern. Beleg: die Anzahl der Monte-Carlo-Pfade
(reiner Darstellungs-/Sampling-Parameter) darf die SAA NICHT veraendern.

Schuetzt die dokumentierte Anlagephilosophie (kein Timing, Re-Balancing nur via
Eignungspruefung/Kundenmeldung) vor stiller Aufweichung.
"""
from __future__ import annotations

from main import app  # noqa: F401 - registriert alle SQLAlchemy-Modelle
from models.mandates import Mandate
import services.portfolio_engine as pe
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _gen(session_factory, mid, advisor_id, mc_runs):
    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {},
        "assetClasses": {}, "simulation": {"monteCarloRuns": mc_runs},
    }
    with session_factory() as s:
        m = s.query(Mandate).filter(Mandate.id == mid).one()
        return pe.generate_target_allocation(s, m, advisor_id, preferences=prefs)


def _bps(result):
    ta = result.get("target_allocation")
    return tuple(int(getattr(ta, k, 0) or 0) for k in (
        "target_equities_bps", "target_bonds_bps", "target_real_estate_bps",
        "target_alternatives_bps", "target_liquidity_bps"))


def test_saa_unabhaengig_von_mc_pfadzahl(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="no-timing")
    a = _gen(session_factory, mid, advisor_id, 250)
    b = _gen(session_factory, mid, advisor_id, 800)
    assert _bps(a) == _bps(b), (
        "SAA haengt von der MC-Pfadzahl ab -> die Strategie reagiert auf einen reinen "
        "Display-/Sampling-Parameter (Hinweis auf unerwuenschte Markt-/Timing-Kopplung)."
    )


def test_reasoning_behauptet_kein_markt_timing(session_factory):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="no-timing-2")
    r = _gen(session_factory, mid, advisor_id, 250)
    reasoning = " ".join(str(x) for x in (r.get("reasoning") or [])).lower()
    for verboten in ("markt-timing", "market timing", "momentum", "taktische umschichtung"):
        assert verboten not in reasoning, f"Reasoning enthaelt Timing-Begriff: {verboten}"
