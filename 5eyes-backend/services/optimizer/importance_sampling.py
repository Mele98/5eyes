"""Mean-Shift Importance Sampling fuer Tail-Risk im Monte-Carlo-Optimizer.

Phase 5 der Stochastic-Optimizer-Spec (docs/planning/2026-05-05-stochastic-
optimizer-spec.md §5). Verbessert die Stichproben-Effizienz fuer
Tail-Events (Black-Swan-Verluste), bei denen Standard-MC zu wenige
relevante Szenarien liefert.

## Ansatz

Mean-Shift Importance Sampling (Glasserman 2004, "Monte Carlo Methods in
Financial Engineering", Ch. 4.6):

Statt Z ~ N(0, I) zu sampeln, sampeln wir aus N(-mu, I) wobei mu > 0
ein Shift-Vector pro Asset ist (default: Shift in Richtung negativer
Aktien-Returns, weil das die kritische Tail-Region fuer Shortfall ist).
Die Pfade laufen also "von Natur aus" haeufiger in den Tail.

Die likelihood ratio (Radon-Nikodym derivative) korrigiert den Bias:

    w_i = exp(mu^T Z_i + 0.5 * |mu|^2)

So dass fuer beliebige integrable f gilt:

    E_{N(0,I)}[f(Z)] = E_{N(-mu,I)}[f(Z) * w(Z)]

In der Praxis: jeder Pfad bekommt ein Gewicht w_i, und Objektiv-
Funktionen muessen die gewichtete Erwartung berechnen statt der
ungewichteten Sample-Mean.

## Wichtige Eigenschaften (verifiziert in Tests)

- Sum-of-weights / N ~= 1.0 (asymptotisch, MC-Fehler O(1/sqrt(N)))
- Gewichtete Mean-Estimator unverzerrt: E[f * w] = E_{original}[f]
- Bei f(Z) := 1{Z < -3} (Tail-Indikator) reduziert sich die Varianz
  des Estimators um 5-50x je nach Shift-Magnitude
- Bei Symmetric f wie Mean(Z) bleibt Estimator unverzerrt aber liefert
  keine Varianz-Reduktion (Standard-MC ist hier optimal)

## Defaults

Aus Methodik-Schulung Slide 19 (Skew/Kurt-Modelle) wissen wir, dass die
kritischen Tails fuer goal-based Allocation in den Aktien-Renditen liegen.
Default-Shift trifft daher den Aktien-Bucket. MC-2 (2026-06-29): der Shift-Index
wird aus der KANONISCHEN scenario_engine.BUCKET_ORDER abgeleitet
(equities, bonds, real_estate, alternatives, liquidity) — also Index 0 — und
NICHT mehr als [2,3] hartcodiert (das traf in der realen Reihenfolge
real_estate+alternatives statt der Aktien und biaste den falschen Tail).

    mu[BUCKET_ORDER.index("equities")] = -shift_strength

mit shift_strength = 0.5 (entspricht 0.5 Standard-Deviationen Shift,
moderat genug um Bias-Variance-Tradeoff im sweet spot zu halten).

Opt-in via Config-Flag `mc_importance_sampling_enabled` in config.py.
Default: False (Phase 5 ist optional laut Spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# Default-Shift-Vector in der KANONISCHEN BUCKET_ORDER
# (equities, bonds, real_estate, alternatives, liquidity): nur der Aktien-Bucket
# (Index 0) wird um -0.5 (halbe Standard-Deviation) negativ geshiftet
# (= mehr Drawdown-Szenarien). MC-2-Fix: vorher [0,0,-0.5,-0.5,0], was
# real_estate+alternatives traf statt der Aktien.
DEFAULT_TAIL_SHIFT_VECTOR = np.array([-0.5, 0.0, 0.0, 0.0, 0.0])
DEFAULT_TAIL_SHIFT_STRENGTH = 0.5  # einheitenlose Standard-Deviation-Multiplikator


@dataclass(frozen=True)
class ImportanceSamplingResult:
    """Bundle aus geshifteten Pfaden + Likelihood-Ratio-Gewichten.

    Attributes
    ----------
    paths : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — log-normal return
        factors, kompatibel zum Output von build_scenario_paths().
    weights : np.ndarray
        Shape (n_paths,) — Likelihood-Ratio pro Pfad. Sum/N -> 1.0.
        Bei Standard-MC (kein IS) sind alle Gewichte = 1.0.
    is_active : bool
        True wenn Importance Sampling aktiv ist (Gewichte nicht-trivial).
    shift_vector : np.ndarray
        Der angewandte Mean-Shift-Vector pro Bucket. Shape (n_buckets,).
        Falls is_active=False: zero-vector.
    """

    paths: np.ndarray
    weights: np.ndarray
    is_active: bool
    shift_vector: np.ndarray


def compute_likelihood_weights(
    z_uncorrelated: np.ndarray,
    shift_vector: np.ndarray,
) -> np.ndarray:
    """Likelihood-Ratio fuer Mean-Shift Importance Sampling.

    Parameters
    ----------
    z_uncorrelated : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — die *unkorrelierten*
        Standard-Normals BEVOR Cholesky-Multiplikation. Diese sind die
        eigentlichen Quellen-Zufallszahlen, an denen die Likelihood
        gemessen wird.
    shift_vector : np.ndarray
        Shape (n_buckets,) — der angewandte Mean-Shift pro Bucket.

    Returns
    -------
    np.ndarray
        Shape (n_paths,) — w_i = exp(-mu^T sum_t Z_it - 0.5 * T * |mu|^2)

        Note: wir berechnen ueber alle Jahre + alle Buckets aggregiert,
        weil jeder Jahres-Schritt unabhaengig geshiftet wird. Die finale
        Likelihood ueber den vollen Pfad ist das Produkt der Jahres-
        Likelihoods, das wir per Summen in den Exponenten berechnen.
    """
    # Sum von Z * shift_vector ueber Bucket-Achse → (n_paths, horizon_years)
    z_dot_mu = np.einsum("phb,b->ph", z_uncorrelated, shift_vector)
    # Summe ueber Jahre → (n_paths,)
    cum_z_dot_mu = z_dot_mu.sum(axis=1)
    # |mu|^2 * horizon (gleicher Shift jedes Jahr)
    horizon_years = int(z_uncorrelated.shape[1])
    mu_sq_norm = float(np.dot(shift_vector, shift_vector))
    # Likelihood-Ratio per (z aus proposal N(mu, I), gewichtet gegen target N(0, I)):
    # p(z)/q(z) = exp(-z²/2) / exp(-(z-mu)²/2) = exp(-z·mu + |mu|²/2)
    # Multi-step (T years, IID): w = exp(-Σ_t z_t·mu + T·|mu|²/2)
    log_weights = -cum_z_dot_mu + 0.5 * horizon_years * mu_sq_norm
    return np.exp(log_weights)


def apply_mean_shift(
    z_uncorrelated: np.ndarray,
    shift_vector: np.ndarray,
) -> np.ndarray:
    """Verschiebt die unkorrelierten Standard-Normals um -shift_vector pro Bucket.

    Wenn die ursprünglichen Z ~ N(0, I) sind, dann sind die geshifteten
    (Z + shift_vector) ~ N(shift_vector, I). Wir geben die geshifteten zurueck,
    sodass die Folge-Pipeline (Cornish-Fisher, Cholesky, log-normal) auf den
    geshifteten Werten arbeitet.

    Note: wir verschieben um +shift_vector (nicht -), damit shift_vector mit
    negativen Komponenten (default fuer Tail) tatsaechlich nach negativen
    Returns biased.

    Parameters
    ----------
    z_uncorrelated : np.ndarray
        Shape (n_paths, horizon_years, n_buckets).
    shift_vector : np.ndarray
        Shape (n_buckets,).

    Returns
    -------
    np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — Z + shift_vector
        (broadcasted ueber Path- und Year-Achse).
    """
    return z_uncorrelated + shift_vector[np.newaxis, np.newaxis, :]


def make_default_weights(n_paths: int) -> np.ndarray:
    """Liefert ein neutrales Gewichts-Array (alle 1.0) fuer Standard-MC ohne IS.

    Wird verwendet wenn IS deaktiviert ist, damit downstream-Code immer
    mit einem Weights-Array arbeiten kann (auch ohne IS-Code-Pfad).
    """
    return np.ones(int(max(1, n_paths)), dtype=np.float64)


def _default_equity_tail_indices(n_buckets: int) -> list[int]:
    """MC-2: Default-Tail-Index = Position des Aktien-Buckets in der kanonischen
    scenario_engine.BUCKET_ORDER. Lazy-Import (kein Modul-Zirkel: scenario_engine
    importiert build_shift_vector, ruft es aber nicht beim Import auf). Fallback 0,
    da equities in der bekannten Order an Index 0 steht."""
    try:
        from .scenario_engine import BUCKET_ORDER
        idx = BUCKET_ORDER.index("equities")
    except Exception:
        idx = 0
    return [idx] if 0 <= idx < n_buckets else []


def build_shift_vector(
    n_buckets: int,
    *,
    target_indices: Optional[list[int]] = None,
    strength: float = DEFAULT_TAIL_SHIFT_STRENGTH,
) -> np.ndarray:
    """Konstruiert einen Shift-Vector fuer Mean-Shift IS.

    Default (target_indices=None): shiftet den Aktien-Bucket negativ. Der Index
    wird aus der kanonischen scenario_engine.BUCKET_ORDER abgeleitet (MC-2-Fix),
    nicht hartcodiert. Das biased die Stichproben in den fuer Shortfall-
    Optimierung wichtigen Drawdown-Tail.

    Parameters
    ----------
    n_buckets : int
        Anzahl Asset-Buckets (typisch 5).
    target_indices : list of int, optional
        Welche Buckets shiften. Default = [BUCKET_ORDER.index("equities")].
    strength : float
        Shift-Magnitude in Standard-Deviationen. Default 0.5.
        Empfohlen: 0.3-1.0. >1.5 fuehrt zu starkem Bias-Variance-Tradeoff.

    Returns
    -------
    np.ndarray
        Shape (n_buckets,) — Shift-Vector mit -strength an target_indices.
    """
    n_buckets = int(max(1, n_buckets))
    if target_indices is None:
        target_indices = _default_equity_tail_indices(n_buckets)
    shift = np.zeros(n_buckets, dtype=np.float64)
    for i in target_indices:
        if 0 <= int(i) < n_buckets:
            shift[int(i)] = -float(strength)
    return shift


def is_importance_sampling_enabled() -> bool:
    """Liest den Force-On-Feature-Flag aus den Settings.

    Default: False (Phase 5 war original opt-in). Aktivierbar via
    MC_IMPORTANCE_SAMPLING_ENABLED=true in .env.

    Wenn True: IS ist immer aktiv (ueberschreibt Auto-Decision).
    """
    try:
        from config import settings  # local import um Circular Imports zu vermeiden
        return bool(getattr(settings, "mc_importance_sampling_enabled", False))
    except Exception:
        return False


def is_importance_sampling_auto_enable() -> bool:
    """Liest das Auto-Enable-Flag (Sprint P1, 2026-06-06).

    Default: True. Wenn True und force_on=False: Auto-Decision basierend
    auf Mandate-Context entscheidet ob IS aktiv ist.
    """
    try:
        from config import settings
        return bool(getattr(settings, "mc_importance_sampling_auto_enable", True))
    except Exception:
        return True


def should_auto_enable_is(
    *,
    score_x10: int,
    has_hart_goal: bool,
    is_retired: bool,
    conservative_score_threshold: int = 30,
) -> tuple[bool, str]:
    """Entscheidet ob IS fuer einen Mandate-Context Auto-aktiviert werden soll.

    Triggers (mind. einer reicht):
    1. score_x10 <= 30: Risikoprofil 'Sicherheit' oder 'Konservativ' —
       der Kunde will Tail-Schutz, IS reduziert MC-Fehler in den unteren
       Quantilen (p1, p5).
    2. is_retired=True: Decumulation-Phase — Sequence-of-Returns-Risk
       (Drawdown im fruehen Ruhestand kann irreversibel Kapital frist).
       IS macht die Tail-Szenarien fuer Entnahme-Planung sichtbar.
    3. has_hart_goal: mindestens ein Ziel ist als 'Hart' klassifiziert
       (z.B. 'Mindest-Pension', 'Kapitalerhalt') — Shortfall darf nicht
       passieren, also brauchen wir genaue Tail-Statistik.

    Parameters
    ----------
    score_x10 : int
        Risikoprofil-Score (0-100), aus Risikofragebogen.
    has_hart_goal : bool
        True wenn mind. ein Goal in liabilities hardness_key == 'hart'.
    is_retired : bool
        Decumulation-Flag aus PDFContext / Mandate-Setup.
    conservative_score_threshold : int, default 30
        Score-Threshold unter dem konservativer Tail-Schutz greift. 30 entspricht
        ungefaehr Profil 'Sicherheit' bis 'Konservativ' im Standard-Mapping.

    Returns
    -------
    tuple[bool, str]
        (should_enable, reason). Wenn should_enable=False, reason ist 'standard-mc'.
        Wenn True, reason ist eine menschen-lesbare Begruendung fuer den
        OptimizerResult.reasoning Audit-Trail.
    """
    reasons: list[str] = []
    if score_x10 <= conservative_score_threshold:
        reasons.append(
            f"konservatives Risikoprofil (score={score_x10}<={conservative_score_threshold})"
        )
    if is_retired:
        reasons.append("Decumulation-Phase (Sequence-of-Returns-Risk)")
    if has_hart_goal:
        reasons.append("hart-klassifiziertes Ziel im Mandat")

    if not reasons:
        return False, "standard-mc"
    return True, "Auto-IS: " + ", ".join(reasons)


def decide_is_for_context(
    *,
    score_x10: int,
    has_hart_goal: bool,
    is_retired: bool,
) -> tuple[bool, str]:
    """Master-Decision: ist IS fuer diesen Mandate-Lauf aktiv? (Sprint P1)

    Reihenfolge:
    1. Wenn `mc_importance_sampling_enabled=True` (legacy force-on)
       -> immer IS aktiv mit reason 'force-on via setting'.
    2. Wenn `mc_importance_sampling_auto_enable=True` (default)
       -> auto-decide basierend auf Mandate-Context.
    3. Sonst (beide False) -> nie IS.

    Returns
    -------
    tuple[bool, str]
        (is_active, reason) — analog should_auto_enable_is.
    """
    if is_importance_sampling_enabled():
        return True, "force-on via mc_importance_sampling_enabled"
    if not is_importance_sampling_auto_enable():
        return False, "auto-enable disabled, force-on not set"
    return should_auto_enable_is(
        score_x10=score_x10,
        has_hart_goal=has_hart_goal,
        is_retired=is_retired,
    )
