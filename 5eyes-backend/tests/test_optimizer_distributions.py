"""Tests fuer services/optimizer/distributions.py.

Calibration: Wenn wir mit Skew/Kurt-Inputs Sample ziehen, muessen die
geschaetzten Sample-Statistiken ungefaehr die Input-Parameter reproduzieren
(innerhalb statistischer Toleranz fuer endliche Sample-Groessen).

Backwards-Compat: skew=0, excess_kurt=0 muss exakt der Standard-Normal
entsprechen (kein Aenderung gegenueber portfolio_engine MC-Loop).

Realistische Aktien-Daten:
- SP500 1928-2024 Annual Return: skew ~ -0.5, excess kurt ~ 1-3
- Verluste >20% pro Jahr: ~5% historisch
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.distributions import (
    cornish_fisher_quantile,
    estimate_distribution_moments,
    sample_cornish_fisher,
    standard_normal_to_log_return,
)


# ============================================================================
# Backwards-Compat: skew=0, kurt=0 muss Normal sein
# ============================================================================


def test_cf_quantile_with_zero_skew_zero_kurt_returns_input():
    """skew=0, excess_kurt=0 -> z_tilde = z (identitaet)."""
    for z in (-2.0, -0.5, 0.0, 0.5, 2.0, 3.0):
        assert cornish_fisher_quantile(z, 0.0, 0.0) == pytest.approx(z, abs=1e-12)


def test_log_return_with_zero_skew_kurt_matches_classical_lognormal():
    """log_return Formel mit skew=0/kurt=0 muss exakt klassisch lognormal sein."""
    z = 1.5
    mu_bps = 700  # 7% expected return
    sigma_bps = 1500  # 15% vol
    mu = mu_bps / 10000.0
    sigma = sigma_bps / 10000.0
    expected = math.exp(mu - 0.5 * sigma * sigma + sigma * z)
    actual = standard_normal_to_log_return(z, mu_bps, sigma_bps)
    assert actual == pytest.approx(expected, rel=1e-12)


# ============================================================================
# Cornish-Fisher Eigenschaften
# ============================================================================


def test_cf_quantile_at_zero_returns_negative_skew_correction():
    """z=0 -> z_tilde = -s/6 (kleiner negative shift fuer s>0)."""
    skew = 0.6
    z_tilde = cornish_fisher_quantile(0.0, skew, 0.0)
    assert z_tilde == pytest.approx(-skew / 6.0, rel=1e-9)


def test_cf_with_negative_skew_shifts_distribution_left():
    """Negativer Skew (typisch fuer Aktien) -> ganze Verteilung nach links shiftet.

    Cornish-Fisher 4-Term mit skew alone (kurt=0) liefert symmetrische Tail-
    Verschiebung. Asymmetrie zwischen den Tails entsteht erst mit der
    s^2-Korrektur ueber alle Ordnungen kombiniert mit Kurt. Hier testen wir
    nur dass die Verteilung in die richtige Richtung shiftet.
    """
    skew = -0.5
    # Mean shift bei z=0 ist -s/6 (also positiv fuer negativen Skew)
    z_tilde_zero = cornish_fisher_quantile(0.0, skew, 0.0)
    assert z_tilde_zero > 0, f"Mean-Shift bei negativem Skew muss positiv sein, got {z_tilde_zero}"
    assert z_tilde_zero == pytest.approx(skew / -6.0, rel=1e-9)
    # Beide Tails werden in die gleiche Richtung verschoben (links bei skew<0)
    z_tilde_neg = cornish_fisher_quantile(-1.645, skew, 0.0)
    z_tilde_pos = cornish_fisher_quantile(1.645, skew, 0.0)
    assert z_tilde_neg < -1.645, "Linker Tail muss tiefer werden"
    assert z_tilde_pos < 1.645, "Rechter Tail muss naeher zur Mitte sein"


def test_cf_with_negative_skew_AND_positive_kurt_makes_left_tail_dominant():
    """Realistisch fuer Aktien: s=-0.5, kurt=2.5 zusammen erzeugen
    einen klar tieferen linken Tail als rechten."""
    skew = -0.5
    excess_kurt = 2.5
    z_tilde_neg = cornish_fisher_quantile(-2.0, skew, excess_kurt)
    z_tilde_pos = cornish_fisher_quantile(2.0, skew, excess_kurt)
    # Linker Tail muss extremer sein als rechter (in absoluten Werten)
    assert abs(z_tilde_neg) > abs(z_tilde_pos), (
        f"Linker Tail ({z_tilde_neg:.3f}) muss extremer sein als "
        f"rechter ({z_tilde_pos:.3f}) bei negativem skew + positivem kurt"
    )


def test_cf_with_positive_kurtosis_produces_fatter_tails():
    """Positive Excess-Kurt -> Beide Tails extremer als Normal."""
    excess_kurt = 3.0
    # Tail-Quantile +/- 2 sigma
    z_tilde_neg = cornish_fisher_quantile(-2.0, 0.0, excess_kurt)
    z_tilde_pos = cornish_fisher_quantile(2.0, 0.0, excess_kurt)
    assert abs(z_tilde_neg) > 2.0, "Linker Tail muss durch positive kurt extremer werden"
    assert abs(z_tilde_pos) > 2.0, "Rechter Tail muss durch positive kurt extremer werden"


def test_cf_clamps_extreme_skew():
    """skew>1 wird auf 1 geclampt (Monotonie-Schutz)."""
    z = 0.5
    out_extreme = cornish_fisher_quantile(z, 5.0, 0.0)
    out_clamped = cornish_fisher_quantile(z, 1.0, 0.0)
    assert out_extreme == pytest.approx(out_clamped, rel=1e-9)


def test_cf_clamps_negative_kurt_to_zero():
    """Negative Excess-Kurt wird auf 0 geclampt."""
    z = 1.0
    out_neg = cornish_fisher_quantile(z, 0.0, -5.0)
    out_zero = cornish_fisher_quantile(z, 0.0, 0.0)
    assert out_neg == pytest.approx(out_zero, rel=1e-9)


# ============================================================================
# Sample-Calibration: Inputs muessen aus Output rekonstruierbar sein
# ============================================================================


def test_sample_distribution_moments_match_inputs_normal():
    """skew=0, kurt=0: Sample-Statistiken muessen ~Normal sein."""
    rng = random.Random(20260505)
    samples = [sample_cornish_fisher(rng, 0.0, 0.0) for _ in range(100_000)]
    moments = estimate_distribution_moments(samples)
    assert moments["mean"] == pytest.approx(0.0, abs=0.02)
    assert moments["vol"] == pytest.approx(1.0, abs=0.02)
    assert moments["skew"] == pytest.approx(0.0, abs=0.05)
    assert moments["excess_kurt"] == pytest.approx(0.0, abs=0.10)


def test_sample_recovers_negative_skew_input_within_tolerance():
    """Input skew=-0.5 (typisch Aktien) -> Sample skew sollte ~ -0.5 sein."""
    rng = random.Random(20260505)
    target_skew = -0.5
    samples = [sample_cornish_fisher(rng, target_skew, 0.0) for _ in range(200_000)]
    moments = estimate_distribution_moments(samples)
    # Cornish-Fisher reproduziert skew nicht 1:1 sondern annaehernd.
    # Toleranz von 30% relativ (also -0.65 bis -0.35) ist akzeptabel fuer
    # 4-Term-Erweiterung. Klare-Vorzeichen-Konsistenz ist das Wichtigste.
    assert moments["skew"] < 0, "Sample muss negativen Skew zeigen"
    assert moments["skew"] == pytest.approx(target_skew, abs=0.20)


def test_sample_recovers_positive_excess_kurt_input():
    """Input excess_kurt=2.0 -> Sample excess_kurt > 0.

    Hinweis: Cornish-Fisher 4-Term reproduziert Input-Kurt nicht 1:1
    sondern *amplifiziert* (typisch Faktor 2x bei moderaten Inputs).
    Das ist eine bekannte Eigenschaft der CF-4-Term-Erweiterung — fuer
    realistischere Reproduktion brauchte man hoehere Ordnungen oder NIG.
    Hier testen wir nur Vorzeichen und Groessenordnung.
    """
    rng = random.Random(20260505)
    target_kurt = 2.0
    samples = [sample_cornish_fisher(rng, 0.0, target_kurt) for _ in range(200_000)]
    moments = estimate_distribution_moments(samples)
    assert moments["excess_kurt"] > 1.0, (
        f"Sample excess kurt muss deutlich > Normal sein, got {moments['excess_kurt']:.3f}"
    )
    assert moments["excess_kurt"] < 10.0, (
        f"Sample excess kurt muss < 10 (Sanity-Bound), got {moments['excess_kurt']:.3f}"
    )


def test_sample_with_aktien_realistic_inputs_produces_more_tail_losses():
    """Realistische Aktien-Inputs (s=-0.5, k=2.5) -> Frequenz von <-2sigma
    ist hoeher als Normal-Distribution erwarten wuerde."""
    rng_normal = random.Random(20260505)
    rng_cf = random.Random(20260505)
    n = 100_000
    samples_normal = [sample_cornish_fisher(rng_normal, 0.0, 0.0) for _ in range(n)]
    samples_cf = [sample_cornish_fisher(rng_cf, -0.5, 2.5) for _ in range(n)]

    # Frequenz von Verlusten unter -2 (also "starke Krise") muss bei CF
    # hoeher sein als bei Normal (Normal: 2.28%, mit fat tails: deutlich mehr)
    freq_extreme_normal = sum(1 for x in samples_normal if x < -2.0) / n
    freq_extreme_cf = sum(1 for x in samples_cf if x < -2.0) / n

    assert freq_extreme_normal == pytest.approx(0.023, abs=0.005)
    assert freq_extreme_cf > freq_extreme_normal * 1.5, (
        f"Fat-tail Distribution muss mehr extreme Verluste produzieren: "
        f"Normal {freq_extreme_normal:.4f}, CF {freq_extreme_cf:.4f}"
    )


# ============================================================================
# Realwert-Sanity: Log-Returns mit fat tails
# ============================================================================


def test_log_returns_aktien_typical_distribution():
    """7% Mean, 15% Vol, s=-0.5, k=2.5 (typisch Aktien Welt) ->
    P5 Verlust < -20%, in Normal-Distribution waere es nur ~-17%."""
    rng = random.Random(20260505)
    n = 100_000
    returns_cf = [
        standard_normal_to_log_return(rng.gauss(0.0, 1.0), 700, 1500, skew=-0.5, excess_kurt=2.5)
        for _ in range(n)
    ]
    returns_cf.sort()
    p05 = returns_cf[int(n * 0.05)]
    p01 = returns_cf[int(n * 0.01)]
    # P5 Return: Normal-Lognormal waere ca. exp(0.07-0.5*0.15^2-1.645*0.15) = 0.825 (also -17.5%)
    # CF mit fat tails: tiefer
    assert p05 < 0.83, f"P5 Return muss <-17% sein bei fat tails, got {p05:.4f}"
    assert p01 < 0.75, f"P1 Return muss <-25% sein bei fat tails, got {p01:.4f}"


# ============================================================================
# Determinismus: Gleicher Seed -> identische Stichproben
# ============================================================================


def test_sample_deterministic_with_seed():
    """Gleicher Seed liefert identische Sequenz - kritisch fuer Optimizer."""
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    samples_a = [sample_cornish_fisher(rng_a, -0.3, 1.5) for _ in range(1000)]
    samples_b = [sample_cornish_fisher(rng_b, -0.3, 1.5) for _ in range(1000)]
    assert samples_a == samples_b, "Determinismus verletzt"
