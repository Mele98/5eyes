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


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_e1_capped_single_target_never_breaks_liquidity_floor(session_factory, monkeypatch, mode):
    """E-1 (Entscheid Owner-Vertretung, AA-7.2): in beiden Modi gilt als
    harte Untergrenze max(Hausmatrix-Minimum, Zielreserve, globale
    Mindestliquiditaet). Vorher sank die Liquiditaet im Hausmatrix-Modus bei
    der Einzelziel-Kappung auf 0 % ("Mindestquote eingehalten"), obwohl eine
    interne Reserve zu halten war. Das Testmandat traegt eine interne
    Reserve (stochastisch: Untergrenze 2.01 %)."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"e1{mode[:3]}")
    result = _generate(session_factory, mid, adv, SINGLE_CAPPED)
    ta = result["target_allocation"]
    liq = int(ta.target_liquidity_bps)
    floor = int(ta.band_liquidity_min_bps)
    assert floor >= 200 and liq >= floor, (liq, floor)
    assert floor == 201  # Zielreserve ueber der globalen 2 %, gleich in beiden Modi
    # Das Ziel wird weiter (sichtbar) gekappt, nicht die Untergrenze verletzt.
    assert int(ta.target_equities_bps) < 7500
    assert "WARN_TARGET_ADJUSTED" in [w.get("code") for w in result["warnings"]]
    reasoning = result["reasoning"]
    for line in reasoning:
        if "Mindestquote eingehalten" in line or "eingehalten)" in line:
            assert "NICHT eingehalten" not in line, line
        if "SAA-Liquiditaet bleibt auf" in line:
            assert f"bleibt auf {liq / 100:.1f}%" in line, line
    assert not any("gilt nur im stochastischen Modell" in r for r in reasoning), reasoning


def test_d1_restate_sentence_names_actual_liquidity():
    """D-1: weicht die gespeicherte Liquiditaet vom Satz der Reserve-
    Berechnung ab, nennt der Satz die tatsaechliche Liquiditaet."""
    from services.portfolio_engine_house_matrix import restate_saa_liquidity_sentence

    reasoning = ["Ein Liquiditaetsbedarf von CHF 2'352 wird ... empfohlen. Die SAA-Liquiditaet bleibt auf 2.0%."]
    restate_saa_liquidity_sentence(reasoning, 0)
    assert "bleibt auf 2.0%" not in reasoning[0]
    assert "Die SAA-Liquiditaet betraegt 0.00 %" in reasoning[0]
    unchanged = ["Die SAA-Liquiditaet bleibt auf 2.0%."]
    restate_saa_liquidity_sentence(unchanged, 201)
    assert unchanged == ["Die SAA-Liquiditaet bleibt auf 2.0%."]


def test_e1_drain_sentence_says_eingehalten_only_when_true():
    from services.portfolio_engine_house_matrix import disclose_manual_target_deviations

    targets = {"equities": 7300, "bonds": 2000, "real_estate": 500, "alternatives": 300, "liquidity": 201}
    reasoning: list[str] = []
    disclose_manual_target_deviations(
        {"equities": 7500}, targets, targets, {k: 0 for k in targets}, {k: 10000 for k in targets},
        reasoning, [], bucket_labels=pe.BUCKET_LABELS, liquidity_before_projection_bps=400,
        liquidity_floor_bps=201, liquidity_floor_source="zwingend vorzuhaltende Zielreserve",
    )
    line = [r for r in reasoning if "sinkt wegen" in r][0]
    assert "Untergrenze 2.01 % (zwingend vorzuhaltende Zielreserve) eingehalten" in line, line
    reasoning = []
    disclose_manual_target_deviations(
        {"equities": 7500}, targets, {**targets, "liquidity": 100, "bonds": 2101},
        {k: 0 for k in targets}, {k: 10000 for k in targets}, reasoning, [],
        bucket_labels=pe.BUCKET_LABELS, liquidity_before_projection_bps=400,
        liquidity_floor_bps=201, liquidity_floor_source="zwingend vorzuhaltende Zielreserve",
    )
    line = [r for r in reasoning if "sinkt wegen" in r][0]
    assert "NICHT eingehalten" in line, line
