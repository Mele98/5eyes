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


def test_house_mode_locked_targets_respect_reserve_floor(session_factory, monkeypatch):
    """75 % + 17 % + Minima 5 % / 3 % = 100 % war im Hausmatrix-Modus
    zulaessig und senkte die Liquiditaet auf 0 %. Seit E-1 gilt auch dort die
    Untergrenze aus Zielreserve/globaler Mindestliquiditaet (2.01 %) -- 422
    mit dieser Herkunft. Das Absenken bis zur Untergrenze (mit Ausweis)
    deckt test_audit_2026_11_d859_d1.py ab."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="h2liq")
    msg = _error(session_factory, mid, adv, {"bands": {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 1700}}})
    assert "Liquiditaet 2.01 % (zwingend vorzuhaltende Zielreserve)" in msg, msg


def test_rule_needs_two_locked_targets_and_uses_effective_maximums():
    """Nachbesserung (CI #859): ein einzelnes fixiertes Ziel (Aktien 80 %
    in Berater-Band 76-85 %, Reserve 2.01 %) und ein Ziel ueber einer
    Modell-Obergrenze (Alternative 30 % bei globaler Obergrenze 10 %) sind
    keine 422, sondern werden sichtbar gekappt
    (test_band_override_house_matrix_disclosure)."""
    from services.portfolio_engine_house_matrix import raise_if_locked_targets_infeasible

    labels = pe.BUCKET_LABELS
    minimums = {"equities": 6000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 201}
    targets = {"equities": 8000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 201}
    raise_if_locked_targets_infeasible(targets, minimums, {"equities"}, bucket_labels=labels)
    maximums = {"equities": 7500, "bonds": 2500, "real_estate": 2000, "alternatives": 1000, "liquidity": 201}
    raise_if_locked_targets_infeasible(
        {**targets, "alternatives": 3000, "bonds": 1000}, minimums, {"alternatives", "bonds"},
        bucket_labels=labels, maximums=maximums,
    )
    with pytest.raises(BandEnvelopeInfeasibleError):
        raise_if_locked_targets_infeasible(
            {**targets, "alternatives": 3000, "bonds": 1000}, minimums, {"alternatives", "bonds"},
            bucket_labels=labels,
        )
