"""BAND-PARTIAL-OVERRIDE-001 (P2, Audit 2026-10-04-manual-target-band-and-
publication-semantics-integrity-audit.md, nicht in diesem Repo committed).

Befund: Das oeffentliche Preferences-Schema (`AllocationBandOverridePayload`,
`schemas/allocation.py`) erlaubt bewusst feldweise Teil-Overrides einer Band
(min_bps/target_bps/max_bps sind alle `Optional`) -- ein Berater kann also nur
`equities.max_bps=2000` setzen und target/min unangetastet lassen.

Der tatsaechliche Compiler (`_apply_band_preferences`,
`services/portfolio_engine_house_matrix.py`, re-exportiert ueber
`services.portfolio_engine`) uebernimmt einen solchen Teil-Override jedoch in
ein `targets`/`minimums`/`maximums`-Tripel, das VORHER bereits mit der
Haus-Matrix-Baseline (`_baseline_target_bands`) gefuellt wurde. Der
unveraendert gebliebene Baseline-`target_bps` (z.B. 5000 bps Aktien) wird NICHT
automatisch in die neue, engere `max_bps`-Grenze (2000 bps) hinein
neu-optimiert -- stattdessen prueft `_apply_band_preferences` sofort
`minimums[key] <= targets[key] <= maximums[key]` und wirft einen ValueError,
weil der nun irrelevante alte Baseline-Target nicht mehr in die neue Grenze
passt. Der Berater muesste also zusaetzlich ZWINGEND ein komplettes,
100%-summierendes Target-Set fuer ALLE Buckets mitliefern, nur weil er eine
einzelne max_bps-Grenze verschaerft hat -- obwohl der Solver (`_rebalance_to_
total`, derselbe Modul) genau dafuer gebaut ist, targets automatisch wieder
auf 10000 bps zu bringen, sobald die harten Grenzen stehen.

Erwuenschtes Verhalten (dieser Test dokumentiert es als REGRESSION/rot): ein
bindender max_bps-Teil-Override, der nur den Baseline-Target unbeteiligter/
derselben Bucket ueberschreitet, sollte vom Compiler AKZEPTIERT werden -- der
Solver re-optimiert das Target anschliessend innerhalb der neuen, engeren
Grenze. Heute wird die Anfrage stattdessen rein wegen des veralteten
Baseline-Targets abgelehnt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import (  # noqa: E402
    _apply_band_preferences,
    _baseline_target_bands,
    _normalize_preferences,
)


def _baseline_house_matrix_and_policy() -> tuple[SimpleNamespace, SimpleNamespace]:
    """Haus-Matrix-Baseline mit Aktien-Target 5000 bps (50%), Summe 10000 bps.

    Aktien-Minimum bewusst auf 0 gesetzt, damit der rote Befund sauber auf
    das Target-vs-neues-Max-Problem isoliert ist (keine Ueberlagerung mit
    einem zusaetzlichen Min-vs-Max-Konflikt).
    """
    house_matrix = SimpleNamespace(
        equity_target_bps=5000,
        bonds_target_bps=3500,
        real_estate_target_bps=1000,
        alt_target_bps=300,
        liq_target_bps=200,
        equity_min_bps=0,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=500,
        alt_min_bps=0,
        liq_min_bps=0,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        real_estate_max_bps=2000,
        alt_max_bps=800,
        liq_max_bps=300,
    )
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )
    return house_matrix, policy


def test_binding_max_only_override_should_be_accepted_not_rejected_for_stale_target():
    house_matrix, policy = _baseline_house_matrix_and_policy()
    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)

    # Baseline-Vorbedingung des Befunds: der unangetastete Aktien-Target
    # (5000 bps) liegt heute weit UEBER der neuen, engeren max_bps-Grenze
    # (2000 bps), die der Berater gleich als alleinigen Override setzt.
    assert targets["equities"] == 5000
    assert minimums["equities"] == 0

    # Oeffentliches Preferences-Schema laeuft durch den echten Validierungspfad
    # (schemas.allocation.AllocationPreferencesPayload via _normalize_preferences):
    # ein reiner max_bps-Teil-Override ist dort explizit erlaubt (min_bps/
    # target_bps bleiben None/unset).
    prefs = _normalize_preferences({"bands": {"equities": {"max_bps": 2000}}})
    assert prefs["bands"]["equities"]["max_bps"] == 2000
    assert prefs["bands"]["equities"]["target_bps"] is None
    assert prefs["bands"]["equities"]["min_bps"] is None

    reasoning: list[str] = []

    # Erwuenschtes Verhalten: der Compiler akzeptiert den bindenden Teil-
    # Override und laesst dem Solver die neu-optimierte Aktien-Quote
    # innerhalb der neuen, engeren 0..2000-bps-Grenze -- KEIN ValueError nur
    # weil der jetzt irrelevante alte Baseline-Target (5000 bps) nicht mehr
    # in die neue Grenze passt.
    _apply_band_preferences(prefs["bands"], targets, minimums, maximums, reasoning)

    assert maximums["equities"] == 2000
    assert targets["equities"] <= 2000
