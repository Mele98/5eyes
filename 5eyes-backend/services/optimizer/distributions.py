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
einen Bereich (s in [-1, 1], k in [0, 8]), der jede real beobachtete
Aktien-Kombination (1928-2024 typischerweise s ~ -0.5, k ~ 4-6) weit
uebersteigt.

CORNISH-FISHER-NON-MONOTONIC-CLAMP-BOUNDS-001 (Kontrollrunde 2026-09-27):
Der obige Satz "Wir clampen daher die Inputs auf sichere Bereiche" war
FALSCH -- der Clamp-Bereich selbst schliesst nicht-monotone Kombinationen
NICHT aus. Numerisch verifiziert: bei s=-1.0, k=0.0 (beides innerhalb des
Clamps, k=0 ist sogar der erlaubte Minimalwert) faellt die transformierte
Quantilfunktion ab z~1.8 monoton bis g(5)=-5.25 < g(-3)=-3.25 -- die
Transformation kehrt sich ueber weite Teile der rechten Flanke komplett
um. Ein Fat-Finger-Tippfehler oder eine plausible "stark linksschiefe
Krise"-Annahme in der CMA-Admin-UI haette damit unbemerkt eine invertierte
Ertragsverteilung erzeugt -- P5/P25/Median-Perzentile und darauf
aufbauende VaR/CVaR-Kennzahlen (FIDLEG-Pflichtdokumente) waeren falsch.
`cornish_fisher_is_monotonic()` prueft daher jede (skew, excess_kurt)-
Kombination explizit VOR Verwendung -- der Clamp allein reicht nicht.

Public API:
    cornish_fisher_quantile(z, skew, excess_kurt) -> float
    cornish_fisher_is_monotonic(skew, excess_kurt) -> bool
    sample_cornish_fisher(rng, skew, excess_kurt) -> float
    standard_normal_to_log_return(z, mu_bps, sigma_bps) -> log-return float
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

from services.return_moments import (
    arithmetic_moments_to_log_parameters,
    bounded_cornish_fisher,
)


_MAX_SKEW = 1.0
_MAX_EXCESS_KURT = 8.0

# Bereich + Aufloesung fuer den Monotonie-Check. +-10 Standardabweichungen
# ueberdeckt jeden praktisch vorkommenden Pfad grosszuegig (P(|Z|>10) ~ 1e-23);
# 4001 Stuetzstellen loesen die im Auftrag gefundene Umkehr-Zone (Breite
# typischerweise 0.3-1.5 Standardabweichungen) klar auf, ohne bei jedem
# CMA-Schreibvorgang/Optimizer-Lauf spuerbar Zeit zu kosten (reiner
# Python-Loop, < 1ms).
_MONOTONICITY_CHECK_Z_BOUND = 10.0
_MONOTONICITY_CHECK_STEPS = 4001


def _clamp_skew(skew: float) -> float:
    """Clamp Skewness auf [-_MAX_SKEW, _MAX_SKEW].

    Dieser Bereich allein macht die Transformation NICHT monoton (siehe
    CORNISH-FISHER-NON-MONOTONIC-CLAMP-BOUNDS-001 oben) -- er verhindert nur
    grobe Fat-Finger-Fehler (z.B. Prozent- statt Dezimal-Eingabe). Monotonie
    fuer ein konkretes (skew, excess_kurt)-Paar muss zusaetzlich ueber
    cornish_fisher_is_monotonic() geprueft werden.
    """
    return max(-_MAX_SKEW, min(_MAX_SKEW, float(skew)))


def _clamp_kurt(excess_kurt: float) -> float:
    """Clamp Excess Kurtosis (= Kurtosis - 3) auf [0, _MAX_EXCESS_KURT].
    Negative Excess-Kurt (sub-gaussian) ist theoretisch erlaubt aber
    unrealistisch fuer Asset Returns - daher Floor bei 0.
    """
    return max(0.0, min(_MAX_EXCESS_KURT, float(excess_kurt)))


def _cornish_fisher_raw(z: float, skew: float, excess_kurt: float) -> float:
    """Unclamped, unclipped Cornish-Fisher polynomial -- fuer den
    Monotonie-Check muss die ROHE Transformation geprueft werden: der
    Output-Clip in bounded_cornish_fisher() (+-8) greift oft erst NACH der
    Umkehr-Zone und wuerde eine bereits invertierte Flanke kuenstlich als
    flach/monoton erscheinen lassen."""
    z2 = z * z
    z3 = z2 * z
    return (
        z
        + (skew / 6.0) * (z2 - 1.0)
        + (excess_kurt / 24.0) * (z3 - 3.0 * z)
        - (skew * skew / 36.0) * (2.0 * z3 - 5.0 * z)
    )


@lru_cache(maxsize=256)
def cornish_fisher_is_monotonic(skew: float, excess_kurt: float) -> bool:
    """True, wenn die Cornish-Fisher-Transformation fuer dieses (geclampte)
    Skew/Kurt-Paar ueber den praktisch relevanten z-Bereich streng monoton
    steigend bleibt -- also eine gueltige Quantilfunktion darstellt.

    Prueft die tatsaechlich zur Laufzeit verwendeten (geclampten) Werte,
    nicht die vom Aufrufer uebergebenen Rohwerte: ein ausserhalb [-1,1]/
    [0,8] liegender Rohwert wird ohnehin auf den Clamp-Rand gezogen, und
    genau diese Rand-Kombination muss sicher sein.

    Gecached (reine Funktion zweier Floats, aufgerufen bei jeder CMA-
    Validierung/jedem Optimizer-Lauf -- in der Praxis wiederholen sich
    wenige (skew, excess_kurt)-Paare pro Mandat/CMA-Version haeufig,
    z.B. (0.0, 0.0) fuer jeden Bucket ohne Fat-Tail-Annahme).
    """
    s = _clamp_skew(skew)
    k = _clamp_kurt(excess_kurt)
    n = _MONOTONICITY_CHECK_STEPS
    bound = _MONOTONICITY_CHECK_Z_BOUND
    step = (2.0 * bound) / (n - 1)
    previous = _cornish_fisher_raw(-bound, s, k)
    for i in range(1, n):
        current = _cornish_fisher_raw(-bound + i * step, s, k)
        if current < previous:
            return False
        previous = current
    return True


def cornish_fisher_quantile(z: float, skew: float, excess_kurt: float) -> float:
    """Mappt Standard-Normal-Quantil z auf nicht-normales Quantil.

    z_tilde = z + (z^2-1)*s/6 + (z^3-3z)*k/24 - (2z^3-5z)*s^2/36

    Wenn skew=0 und excess_kurt=0 -> z_tilde = z (Normalverteilung).
    Verteilungs-Mean bleibt 0 erhalten, Vol bleibt ~1 (zur 1. Ordnung).
    """
    s = _clamp_skew(skew)
    k = _clamp_kurt(excess_kurt)
    return float(bounded_cornish_fisher(z, s, k))


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
    """Mappt arithmetische CMA-Momente auf einen Log-Return.

    Fuer Normal-Innovationen gilt mit
    ``v = log(1 + (sigma / (1 + mu))**2)``:
    ``log(R) = log(1 + mu) - v/2 + sqrt(v) * z``.
    Der Tail-Pfad kalibriert Location und Scale numerisch auf dieselben beiden
    einfachen Return-Momente.

    mu_bps ist eine arithmetische erwartete Rendite in Basispunkten
    (z.B. 700 = 7%). Die Umrechnung sorgt dafür, dass E[R] = 1 + mu unter
    der Log-Normal-Verteilung gilt und die einfache Return-Volatilitaet
    ebenfalls ``sigma`` entspricht.
    Quelle: Hull "Options, Futures and Other Derivatives" Ch. 14.

    Wenn skew=0 und excess_kurt=0: identisch zur klassischen Log-Normal-MC,
    konsistent zu services.portfolio_engine._run_allocation_monte_carlo.
    """
    mu = mu_bps / 10000.0
    sigma = sigma_bps / 10000.0
    s = _clamp_skew(skew)
    k = _clamp_kurt(excess_kurt)
    location, scale = arithmetic_moments_to_log_parameters(
        mu,
        sigma,
        skew=s,
        excess_kurtosis=k,
        use_cornish_fisher=True,
    )
    z_tilde = cornish_fisher_quantile(z, skew, excess_kurt)
    return math.exp(location + scale * z_tilde)


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
