"""Delta-Pruefung #859 (Dok. 86): D-1 (gemeinsamer Kontext siehe unten).

D-1: Einzelziel-Kappung im Hausmatrix-Modus (Aktien-Ziel 75 % + Berater-
Minimum Obligationen 20 %): die Liquiditaet sinkt von 2 % auf 0 %, das
Reasoning sagte aber zugleich "Die SAA-Liquiditaet bleibt auf 2.0%." (Satz
der Reserve-Berechnung VOR der Projektion). Im Hausmatrix-Modus gilt die
Liquiditaets-Untergrenze der Hausmatrix (hier 0 %), nicht die globale
2-%-Untergrenze des stochastischen Modells -- das wird jetzt ausgewiesen.

D-2: systembedingte Erweiterung des Liquiditaetsbands ueber das
Hausmatrix-Maximum (M2) wird als Reasoning-Satz und Info-Meldung
ausgewiesen.

D-4: H-859-1 ohne Fallback -- gekapptes Einzelziel, Warnung und
body_client nennen die gespeicherte Quote, in beiden Modi.
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
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

SINGLE_CAPPED = {"bands": {"equities": {"target_bps": 7500}, "bonds": {"min_bps": 2000}}}


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def test_d1_house_mode_reasoning_states_actual_liquidity_and_floor_scope(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="d1")
    result = _generate(session_factory, mid, adv, SINGLE_CAPPED)
    ta = result["target_allocation"]
    final_liq = int(ta.target_liquidity_bps)
    assert final_liq == 0  # Hausmatrix-Minimum 0 % eingehalten
    reasoning = result["reasoning"]
    stale = [r for r in reasoning if "SAA-Liquiditaet bleibt auf 2.0%" in r]
    assert stale == [], stale
    assert any("Die SAA-Liquiditaet betraegt 0.00 %" in r for r in reasoning), reasoning
    assert any(
        "globale Mindestliquiditaet von 2.00 % gilt nur im stochastischen Modell" in r for r in reasoning
    ), reasoning


def test_d1_stochastic_keeps_global_floor(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="d1s")
    result = _generate(session_factory, mid, adv, SINGLE_CAPPED)
    liq = int(result["target_allocation"].target_liquidity_bps)
    assert liq >= 200  # globale 2-%-Untergrenze gilt im stochastischen Modell
    for line in result["reasoning"]:
        if "SAA-Liquiditaet bleibt auf" in line:
            assert f"bleibt auf {liq / 100:.1f}%" in line, line


