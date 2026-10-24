"""RETIREMENT-ALLOCATION-BASIS-001 -- auf welcher Allokation eine Kennzahl steht.

Mehrere Verbraucher leiteten ihre Zahlen aus ``_baseline_target_bands()`` ab,
also aus der ROHEN Hausmatrix-Bandbreite des Risiko-Buckets, und haben die
tatsaechlich genehmigte ``TargetAllocation`` des Mandats nie geladen. Weicht
die freigegebene Strategie von der Baseline ab -- etwa weil eine
Aktien-Untergrenze gegriffen hat und Immobilien/Alternative gedeckelt wurden
--, rechnet der Verbraucher auf einer Allokation, die so nie beschlossen
wurde.

``approved_or_baseline_targets()`` kapselt die Entscheidung und gibt die
verwendete Basis mit zurueck. Diese Suite prueft beide Zweige, die
Bandprojektion des Fallbacks und dass die Basis im Nachweis landet.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine_house_matrix import (
    APPROVED_ALLOCATION_BASIS,
    HOUSE_MATRIX_BASELINE_BASIS,
    allocation_basis_note,
    approved_or_baseline_targets,
)

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def _house_matrix(**overrides) -> SimpleNamespace:
    base = dict(
        equity_target_bps=4800,
        bonds_target_bps=3500,
        real_estate_target_bps=1000,
        alt_target_bps=500,
        liq_target_bps=200,
        equity_min_bps=4000,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=0,
        alt_min_bps=0,
        liq_min_bps=200,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        real_estate_max_bps=2000,
        alt_max_bps=1000,
        liq_max_bps=1000,
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


def _allocation(**bps) -> SimpleNamespace:
    base = dict(
        target_equities_bps=7000,
        target_bonds_bps=1800,
        target_real_estate_bps=600,
        target_alternatives_bps=400,
        target_liquidity_bps=200,
    )
    base.update(bps)
    return SimpleNamespace(**base)


def test_approved_allocation_wins_over_the_house_matrix_baseline() -> None:
    """Der eigentliche Befund: die freigegebene Strategie gilt, nicht die Baseline.

    Die Fixture-Allokation (70/18/6/4/2) weicht bewusst von der
    Hausmatrix-Baseline (48/35/10/5/2) ab -- so wie es in Produktion
    entsteht, wenn eine Aktien-Untergrenze greift und Immobilien/Alternative
    gedeckelt werden.
    """
    targets, basis = approved_or_baseline_targets(
        _allocation(), _house_matrix(), _policy()
    )
    assert basis == APPROVED_ALLOCATION_BASIS
    assert targets == {
        "equities": 7000, "bonds": 1800, "real_estate": 600,
        "alternatives": 400, "liquidity": 200,
    }


def test_without_an_approved_allocation_the_baseline_is_used() -> None:
    """Ohne freigegebene Strategie bleibt die Hausmatrix-Baseline -- benannt."""
    targets, basis = approved_or_baseline_targets(
        None, _house_matrix(), _policy()
    )
    assert basis == HOUSE_MATRIX_BASELINE_BASIS
    assert sum(targets.values()) == 10000


def test_the_baseline_fallback_is_projected_into_its_own_bands() -> None:
    """Der Fallback gibt die rohen Targets NICHT ungeklemmt weiter.

    Die rohen ``*_target_bps`` koennen ihre eigenen Bandbreiten verletzen
    (dokumentiert als AB-MODEL-001). Hier ueberschreitet der rohe
    Immobilien-Zielwert (1000) die verschaerfte Policy-Obergrenze (300); der
    Fallback muss ihn auf 300 projizieren, sonst rechnet der Verbraucher mit
    einer Allokation, die das System in der Generierung nie zulassen wuerde.
    """
    house = _house_matrix()
    policy = _policy(max_real_estate_bps=300)
    targets, basis = approved_or_baseline_targets(None, house, policy)

    assert basis == HOUSE_MATRIX_BASELINE_BASIS
    assert house.real_estate_target_bps == 1000, "Fixture-Annahme"
    assert targets["real_estate"] <= 300, (
        f"roher Immobilien-Zielwert nicht in die Policy-Obergrenze projiziert: "
        f"{targets['real_estate']}"
    )
    assert sum(targets.values()) == 10000


def test_a_full_exclusion_survives_the_fallback_projection() -> None:
    """Ein Policy-Cap von 0 bleibt auch im Fallback ein echter Ausschluss.

    Verbindet diesen Fix mit ZERO-CONSTRAINT-SEMANTICS-001: die Projektion
    darf die dort behobene Semantik nicht wieder aufweichen.
    """
    targets, _basis = approved_or_baseline_targets(
        None, _house_matrix(), _policy(max_alternatives_bps=0)
    )
    assert targets["alternatives"] == 0
    assert sum(targets.values()) == 10000


def test_an_approved_allocation_is_taken_verbatim() -> None:
    """Die genehmigte Allokation wird NICHT nachgeklemmt.

    Sie ist der Strategieentscheid; sie nachtraeglich gegen heutige
    Hausmatrix-Bandbreiten zu projizieren wuerde einen freigegebenen Beschluss
    stillschweigend veraendern -- genau die Richtung, die der Replay-Vertrag
    des Nachweises verbietet. Driftet die Hausmatrix, muss das auffallen,
    nicht geglaettet werden.
    """
    # Allokation ausserhalb der heutigen Hausmatrix-Bandbreite (Aktien 70 %
    # gegen ein Maximum von 55 %).
    targets, basis = approved_or_baseline_targets(
        _allocation(target_equities_bps=7000),
        _house_matrix(equity_max_bps=5500),
        _policy(),
    )
    assert basis == APPROVED_ALLOCATION_BASIS
    assert targets["equities"] == 7000


def test_missing_bps_columns_are_read_as_zero_not_as_a_crash() -> None:
    """Eine Altbestands-Zeile mit NULL-Spalten darf die Kennzahl nicht sprengen."""
    targets, basis = approved_or_baseline_targets(
        _allocation(target_alternatives_bps=None), _house_matrix(), _policy()
    )
    assert basis == APPROVED_ALLOCATION_BASIS
    assert targets["alternatives"] == 0


def test_both_bases_have_a_distinguishable_note() -> None:
    """Die Begruendung benennt die Basis -- und die zwei Faelle sind verschieden.

    Ohne diesen Unterschied waere die Angabe im Nachweis wertlos: der Berater
    koennte nicht erkennen, ob die Zahl auf der freigegebenen Strategie oder
    auf einer Risikoprofil-Bandbreite steht.
    """
    approved = allocation_basis_note(APPROVED_ALLOCATION_BASIS)
    baseline = allocation_basis_note(HOUSE_MATRIX_BASELINE_BASIS)
    assert approved != baseline
    assert "genehmigte" in approved
    assert "Hausmatrix" in baseline
    assert "keine Soll-Allokation" in baseline


def test_the_endpoint_publishes_the_basis_in_its_reasoning() -> None:
    """Der Hinweis erreicht die Antwort des Endpunkts.

    Isoliert geprueft waere der Helfer korrekt und trotzdem unsichtbar -- und
    genau diese Falle (eine korrekte, aber nirgends aufgerufene Funktion) ist
    in dieser Runde schon zweimal zugeschlagen.
    """
    source = (BACKEND_ROOT / "routers" / "wealth.py").read_text(encoding="utf-8")
    marker = "def calculate_max_pension_spending("
    assert marker in source
    body = source[source.index(marker) :]
    # Nur der Rumpf DIESES Endpunkts, nicht die ganze Datei: andere Endpunkte
    # duerfen die Hausmatrix-Bandbreite legitim direkt verwenden.
    end = body.find("\n@router.", 1)
    if end > 0:
        body = body[:end]
    # Kommentarzeilen ausblenden -- die Begruendung im Code zitiert die alte
    # Aufrufform, und darauf darf die Pruefung nicht anschlagen.
    code_lines = [
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)

    assert "allocation_basis_note(allocation_basis_id)" in code, (
        "Die Basis-Angabe landet nicht in der reasoning-Liste des "
        "Max-Pension-Spending-Endpunkts"
    )
    assert "approved_or_baseline_targets(" in code
    assert "_baseline_target_bands(" not in code, (
        "Der Endpunkt leitet seine Targets wieder direkt aus der rohen "
        "Hausmatrix-Bandbreite ab"
    )
