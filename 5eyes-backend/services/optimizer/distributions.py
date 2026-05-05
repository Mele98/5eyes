"""Distribution-Engine fuer Optimizer-Szenarien.

Cornish-Fisher 4-Term-Erweiterung erlaubt nicht-normale Stichproben aus
einem Standard-Normal Z plus Skewness s und Excess-Kurtosis k. Vorteil
gegenueber externer Lib: keine zusaetzliche Dependency und mathematisch
stabil im erlaubten Parameter-Bereich.

Quelle: Cornish/Fisher 1937 "Moments and Cumulants in the Specification
of Distributions"; modern: Boudt/Peterson/Croux 2008 "Estimation and
decomposition of downside risk".

Wichtige Limitation: Cornish-Fisher kann nicht-monoton werden bei
extremen Skew/Kurt-Kombinationen. Wir clampen daher die Inputs auf
sichere Bereiche (s in [-1, 1], k in [0, 8]). Aktien-Realdaten 1928-2024
liegen typischerweise bei s ~ -0.5, k ~ 4-6.

Public API:
    cornish_fisher_quantile(z, skew, excess_kurt) -> float
    sample_cornish_fisher(rng, skew, excess_kurt) -> float
    standard_normal_to_log_return(z, mu_bps, sigma_bps) -> log-return float
"""
from __future__ import annotations

import math
import random


_MAX_SKEW = 1.0
_MAX_EXCESS_KURT = 8.0


def _clamp_skew(skew: float) -> float:
    """Clamp Skewness auf den Bereich wo Cornish-Fisher monoton bleibt."""
    return max(-_MAX_SKEW, min(_MAX_SKEW, float(skew)))


def _clamp_kurt(excess_kurt: float) -> float:
    """Clamp Excess Kurtosis (= Kurtosis - 3) auf [0, _MAX_EXCESS_KURT].
    Negative Excess-Kurt (sub-gaussian) ist theoretisch erlaubt aber
    unrealistisch fuer Asset Returns - daher Floor bei 0.
    """
    return max(0.0, min(_MAX_EXCESS_KURT, float(excess_kurt)))


def cornish_fisher_quantile(z: float, skew: float, excess_kurt: float) -> float:
    """Mappt Standard-Normal-Quantil z auf nicht-normales Quantil.

    z_tilde = z + (z^2-1)*s/6 + (z^3-3z)*k/24 - (2z^3-5z)*s^2/36

    Wenn skew=0 und excess_kurt=0 -> z_tilde = z (Normalverteilung).
    Verteilungs-Mean bleibt 0 erhalten, Vol bleibt ~1 (zur 1. Ordnung).
    """
    s = _clamp_skew(skew)
    k = _clamp_kurt(excess_kurt)
    z2 = z * z
    z3 = z2 * z
    return (
        z
        + (z2 - 1.0) * s / 6.0
        + (z3 - 3.0 * z) * k / 24.0
        - (2.0 * z3 - 5.0 * z) * s * s / 36.0
    )


def sample_cornish_fisher(rng: random.Random, skew: float, excess_kurt: float) -> float:
    """Zieht eine Cornish-Fisher-adjustierte Standard-Stichprobe."""
    z = rng.gauss(0.0, 1.0)
    return cornish_fisher_quantile(z, skew, excess_kurt)


def standard_normal_to_log_return(
    z: float,
    mu_bps: int,
    sigma_bps: int,
    *,
    skew: float = 0.0,
    excess_kurt: float = 0.0,
) -> float:
    """Konvertiert Standard-Normal-Stichprobe in Log-Return mit Itô-Korrektur.

    log(R) = mu - 0.5 * sigma^2 + sigma * z_tilde

    mu_bps und sigma_bps sind in basis points (z.B. 700 = 7%). Itô-Korrektur
    sorgt dafuer dass E[R] = exp(mu) auch unter der Log-Normal-Verteilung gilt.
    Quelle: Hull "Options, Futures and Other Derivatives" Ch. 14.

    Wenn skew=0 und excess_kurt=0: identisch zur klassischen Log-Normal-MC,
    konsistent zu services.portfolio_engine._run_allocation_monte_carlo.
    """
    mu = mu_bps / 10000.0
    sigma = sigma_bps / 10000.0
    z_tilde = cornish_fisher_quantile(z, skew, excess_kurt)
    return math.exp(mu - 0.5 * sigma * sigma + sigma * z_tilde)


def estimate_distribution_moments(samples: list[float]) -> dict[str, float]:
    """Schaetzt Mean, Vol, Skewness, Excess-Kurtosis aus Sample-Liste.

    Wird in Calibration-Tests genutzt um zu pruefen dass unsere Cornish-Fisher
    Output ungefaehr die Input-Parameter reproduziert.

    Definition Excess-Kurtosis = Kurtosis - 3 (Pearson-Definition).
    Normal-Distribution hat Kurtosis = 3 also Excess-Kurtosis = 0.
    """
    n = len(samples)
    if n < 2:
        return {"mean": 0.0, "vol": 0.0, "skew": 0.0, "excess_kurt": 0.0}
    mean = sum(samples) / n
    centered = [x - mean for x in samples]
    m2 = sum(c * c for c in centered) / n
    m3 = sum(c * c * c for c in centered) / n
    m4 = sum(c * c * c * c for c in centered) / n
    vol = math.sqrt(m2) if m2 > 0 else 0.0
    skew = m3 / (vol ** 3) if vol > 0 else 0.0
    kurt = m4 / (vol ** 4) if vol > 0 else 3.0
    return {
        "mean": mean,
        "vol": vol,
        "skew": skew,
        "excess_kurt": kurt - 3.0,
    }
