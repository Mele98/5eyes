"""H-859-2 (Pruefrunde #859): fixierte Berater-Ziele + Minima > 100 %.

Vorher: Aktien-Ziel 75 % + Obligationen-Ziel 25 % (Score 8, Minima
Immobilien 5 % / Alternative 3 %, zusammen 108 %) wurde nicht abgelehnt,
sondern still in fester Reihenfolge gekappt: Hausmatrix 6700/2500/500/300/0
mit WARN_TARGET_ADJUSTED, stochastisch 6624/2347/522/306/201. Vorher wurde im
Hausmatrix-Modus ausserdem die freie Liquiditaet ohne Hinweis von 2 % auf
das Haus-Minimum 0 % abgesenkt.

Nachher: deutsche 422 (BandEnvelopeInfeasibleError), die die kollidierenden
Ziele und Mindestquoten mit Herkunft nennt -- auch wenn erst die globale
Liquiditaets-Untergrenze des stochastischen Modells die Summe ueber 100 %
hebt. Ein zulaessiges Absenken der Liquiditaet wird im Reasoning ausgewiesen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from services.portfolio_engine_house_matrix import BandEnvelopeInfeasibleError  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402


def _run(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def _error(SF, mid, adv, prefs) -> str:
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
            pe.generate_target_allocation(s, mandate, adv, prefs)
        s.rollback()
    return str(exc_info.value)


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_locked_targets_plus_minimums_over_100_is_german_422(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"h2{mode[:3]}")
    msg = _error(session_factory, mid, adv, {"bands": {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 2500}}})
    assert "fixierten Berater-Ziele (Aktien 75.00 %, Obligationen 25.00 %)" in msg, msg
    assert "Immobilien 5.00 % (Hausmatrix-Minimum)" in msg, msg
    assert "Alternative 3.00 % (Hausmatrix-Minimum)" in msg, msg
    assert "108.00 %" in msg, msg


def test_global_liquidity_floor_makes_locked_targets_infeasible_in_stochastic(session_factory, monkeypatch):
    """75 % + 17 % + Minima 5 % / 3 % = 100 % ist im Hausmatrix-Modus
    zulaessig; im stochastischen Modus hebt die globale Untergrenze 2 % die
    Summe auf 102 % -- 422 mit dieser Herkunft statt stiller Kappung."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="h2floor")
    msg = _error(session_factory, mid, adv, {"bands": {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 1700}}})
    assert "Liquiditaet 2.00 % (globale Liquiditaets-Untergrenze des Modells)" in msg, msg
    assert "102.00 %" in msg, msg


def test_liquidity_lowered_by_locked_targets_is_disclosed_in_house_mode(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="h2liq")
    result = _run(session_factory, mid, adv, {"bands": {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 1700}}})
    ta = result["target_allocation"]
    assert (ta.target_equities_bps, ta.target_bonds_bps, ta.target_liquidity_bps) == (7500, 1700, 0)
    assert "WARN_TARGET_ADJUSTED" not in [w.get("code") for w in result["warnings"]]
    assert any("sinkt wegen der fixierten Berater-Ziele von 2.00 % auf 0.00 %" in r for r in result["reasoning"]), result["reasoning"]
