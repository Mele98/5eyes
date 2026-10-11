from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _baseline_target_bands, _rebalance_to_total  # noqa: E402


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


def test_policy_real_estate_cap_below_house_minimum_must_not_invert_band():
    """Hausmatrix-Minimum 500 bps, Mandats-Policy begrenzt auf 300 bps.

    Vorher klemmte ``_baseline_target_bands`` nur das Maximum auf den
    Policy-Cap (300) und liess das Minimum beim Hausmatrix-Wert (500) stehen
    -- das zurueckgegebene Dict hatte also min(500) > max(300), bevor
    ``_rebalance_to_total`` ueberhaupt lief. Dessen Klemmung
    ``max(min, min(max, wert))`` loest bei invertiertem Band immer zum
    (hoeheren) Minimum auf: die Policy-Obergrenze wurde praktisch ignoriert,
    und zwar lautlos.

    Aufgeloest wird zugunsten der Policy -- sie ist die mandatsspezifische
    Anweisung, die Hausmatrix die firmenweite Standard-Bandbreite.
    """
    house_matrix = _house_matrix()
    policy = SimpleNamespace(
        max_real_estate_bps=300,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )

    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)

    # Die Policy-Obergrenze gilt, und das Minimum folgt ihr nach unten.
    assert maximums["real_estate"] == 300
    assert minimums["real_estate"] == 300
    assert minimums["real_estate"] <= maximums["real_estate"]

    # Und das wirkt sich bis in die effektive Allokation aus: vorher gewann
    # das Minimum mit 500 bps ueber die Obergrenze von 300.
    final_targets = _rebalance_to_total(targets, minimums, maximums)
    assert final_targets["real_estate"] == 300


def test_no_bucket_band_ever_inverts_under_any_policy_cap():
    """Die eigentliche Zusicherung: KEIN Bucket darf je min > max liefern.

    Breiter als die zwei dokumentierten Reproduktionen -- geprueft wird die
    Invariante selbst, ueber ein Raster von Policy-Werten einschliesslich der
    Randfaelle 0 (voller Ausschluss) und Werten ueber dem Hausmatrix-Maximum.
    Ein kuenftiger Pfad, der die Bandbreite auf eine andere Weise invertiert,
    faellt hier auf, statt still eine kaputte Allokation zu erzeugen.
    """
    house_matrix = _house_matrix()
    for real_estate_cap in (0, 100, 300, 500, 2000, 10000):
        for alternatives_cap in (0, 200, 300, 1000, 10000):
            for liquidity_min in (0, 100, 300, 900):
                policy = SimpleNamespace(
                    max_real_estate_bps=real_estate_cap,
                    max_alternatives_bps=alternatives_cap,
                    min_liquidity_bps=liquidity_min,
                )
                _targets, minimums, maximums = _baseline_target_bands(
                    house_matrix, policy
                )
                for bucket in minimums:
                    assert minimums[bucket] <= maximums[bucket], (
                        f"Invertierte Bandbreite fuer {bucket} bei "
                        f"Immobilien-Cap={real_estate_cap}, "
                        f"Alternative-Cap={alternatives_cap}, "
                        f"Liquiditaets-Minimum={liquidity_min}: "
                        f"min={minimums[bucket]} > max={maximums[bucket]}"
                    )


def test_policy_liquidity_minimum_above_house_maximum_does_not_invert():
    """Derselbe Defekt in der anderen Richtung -- von den Reproduktionen nicht gedeckt.

    Eine Policy-Mindestquote UEBER dem Hausmatrix-Maximum invertiert die
    Bandbreite genauso. Aufgeloest wird symmetrisch: das Maximum wird
    angehoben. Fuer Liquiditaet ist die hoehere Quote die konservativere
    Richtung, hier gewinnt also ebenfalls die mandatsspezifische Anweisung.
    """
    house_matrix = _house_matrix()  # liq_max_bps = 300
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=900,
    )
    _targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    assert minimums["liquidity"] == 900
    assert maximums["liquidity"] >= 900


def test_house_matrix_internal_band_inversion_is_rejected_not_clamped():
    """Korrupte Referenzdaten werden abgelehnt, nicht stillschweigend geklemmt.

    Die Policy-Konflikte oben sind legitime Konfigurationen mit einer
    dokumentierten Aufloesungsregel. Ein ``min > max`` in der Hausmatrix-Zeile
    selbst ist kein Konflikt, sondern ein kaputter Datensatz -- dafuer gibt es
    keine sinnvolle Aufloesung, und zu klemmen hiesse, eine kaputte
    Bandbreite in eine Allokation zu uebersetzen.
    """
    broken = _house_matrix(equity_min_bps=5500, equity_max_bps=4000)
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )
    with pytest.raises(ValueError, match="invertierte Bandbreite"):
        _baseline_target_bands(broken, policy)


def test_policy_alternatives_cap_below_house_minimum_must_not_invert_band():
    """Zweite dokumentierte Reproduktion: Hausmatrix-Minimum 300, Policy-Cap 200."""
    house_matrix = _house_matrix(alt_min_bps=300, alt_target_bps=300, alt_max_bps=1000)
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=200,
        min_liquidity_bps=0,
    )

    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)

    assert maximums["alternatives"] == 200
    assert minimums["alternatives"] == 200
    assert minimums["alternatives"] <= maximums["alternatives"]

    final_targets = _rebalance_to_total(targets, minimums, maximums)
    assert final_targets["alternatives"] == 200

    assert minimums["alternatives"] <= maximums["alternatives"], (
        f"Inverted alternatives band persisted: "
        f"min={minimums['alternatives']} > max={maximums['alternatives']}"
    )
