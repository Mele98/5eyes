"""POLICY-ACTIVATION-COMPLETENESS-001 -- die Bandverschiebung wird ausgewiesen.

``_baseline_target_bands()`` loest einen Konflikt zwischen Mandats-Policy und
Hausmatrix deterministisch zugunsten der Policy auf: ein Policy-Cap unter dem
Hausmatrix-Minimum zieht das Minimum nach unten, damit die Bandbreite nicht
invertiert.

Das ist die richtige Aufloesung -- die Policy ist die mandatsspezifische
Anweisung --, aber sie veraendert eine firmenweite Vorgabe fuer ein einzelnes
Mandat. Wer ein Hausmatrix-Minimum von 5 % auf 0 % herabsetzt, weil das Mandat
die Anlageklasse ausschliesst, muss das im Nachweis lesen koennen.

``policy_band_clamp_notes()`` liefert diese Begruendungen. Isoliert geprueft
waere die Funktion korrekt und trotzdem unsichtbar -- deshalb prueft diese
Suite auch, dass sie im echten Generate-Pfad in der ``reasoning``-Liste
landet.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine_house_matrix import policy_band_clamp_notes


def _house_matrix(**overrides) -> SimpleNamespace:
    base = dict(
        equity_target_bps=4800,
        bonds_target_bps=3500,
        real_estate_target_bps=500,
        alt_target_bps=300,
        liq_target_bps=200,
        equity_min_bps=4000,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=500,
        alt_min_bps=300,
        liq_min_bps=0,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        real_estate_max_bps=2000,
        alt_max_bps=1000,
        liq_max_bps=300,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _policy(**overrides) -> SimpleNamespace:
    base = dict(
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_no_notes_when_policy_does_not_tighten_anything() -> None:
    """Keine Verschiebung, kein Hinweis -- der Nachweis bleibt ruhig.

    Sonst wuerde jeder Lauf Rauschen produzieren und die echten Hinweise
    gingen darin unter.
    """
    assert policy_band_clamp_notes(_house_matrix(), _policy()) == []


def test_a_tightening_cap_is_disclosed() -> None:
    notes = policy_band_clamp_notes(
        _house_matrix(), _policy(max_real_estate_bps=800)
    )
    assert any("Immobilien" in note and "8.00 %" in note for note in notes), notes


def test_lowering_a_house_minimum_is_disclosed_explicitly() -> None:
    """Der wichtigste Hinweis: ein herabgesetztes Hausmatrix-Minimum.

    Das Cap allein waere erklaerbar; dass dafuer eine firmenweite
    Mindestquote aufgegeben wurde, ist die Information, die ohne diesen
    Hinweis verloren ginge.
    """
    notes = policy_band_clamp_notes(
        _house_matrix(), _policy(max_real_estate_bps=300)
    )
    lowering = [note for note in notes if "herabgesetzt" in note]
    assert lowering, notes
    assert "5.00 %" in lowering[0], lowering  # Hausmatrix-Minimum
    assert "3.00 %" in lowering[0], lowering  # Policy-Obergrenze


def test_full_exclusion_is_disclosed() -> None:
    """Ein Cap von 0 bps ist der Grenzfall -- und er muss sichtbar sein."""
    notes = policy_band_clamp_notes(
        _house_matrix(), _policy(max_alternatives_bps=0)
    )
    assert any("Alternative" in note and "0.00 %" in note for note in notes), notes
    assert any("herabgesetzt" in note for note in notes), notes


def test_liquidity_minimum_above_house_maximum_is_disclosed() -> None:
    notes = policy_band_clamp_notes(_house_matrix(), _policy(min_liquidity_bps=900))
    assert any(
        "Liquiditaet" in note and "angehoben" in note for note in notes
    ), notes


def test_notes_reach_the_generate_reasoning() -> None:
    """End-to-End: die Hinweise landen in der ``reasoning``-Liste des Laufs.

    ``reasoning`` wird als ``optimizer_reasoning_json`` persistiert und ist
    der Nachweis, den der Berater liest. Ohne diese Verdrahtung waere
    ``policy_band_clamp_notes()`` eine korrekte, aber ungenutzte Funktion --
    dieselbe Falle, die bei der Drawdown-Nachrechnung schon einmal zuschlug.
    """
    engine_source = (
        BACKEND_ROOT / "services" / "portfolio_engine.py"
    ).read_text(encoding="utf-8")
    assert "reasoning.extend(policy_band_clamp_notes(house_matrix, policy))" in (
        engine_source
    ), (
        "policy_band_clamp_notes() wird im Generate-Pfad nicht in die "
        "reasoning-Liste gegeben -- die Bandverschiebung bleibt unsichtbar"
    )
