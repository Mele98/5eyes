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
- Bei Tail-Indikatoren reduziert sich die Varianz des Estimators; mit der
  defensiven Mischung (siehe Defaults) gemessen 2.4x fuer ein 5 %-Ereignis
  des Aktienfaktors, analytisch 1.06-2.1x fuer Zielfehlschlaege von 5-20 %
- Bei Symmetric f wie Mean(Z) bleibt Estimator unverzerrt aber liefert
  keine Varianz-Reduktion (Standard-MC ist hier optimal)

## Defaults (IMPORTANCE-SAMPLING-ESS-001, 2026-10-18)

Bis 2026-10-18 wurde der Shift ``mu = -0.5`` auf den Aktienfaktor in JEDEM
Jahr angewandt. Die Log-Likelihood-Ratio ist dann eine Summe von T
unabhaengigen Termen, ``E_q[w^2] = exp(T |mu|^2)`` und die Kish-ESS-Quote
``ESS/N ~ exp(-T/4)`` -- bei T = 31 (Fundament-Mandat) 4e-4, gemessen 7 von
2'000 Pfaden, Einzelpfade mit bis zu 33 % der Gewichtsmasse. Gleichzeitig lag
der Endwert des Aktienfaktors um ``0.5 * sqrt(T)`` Standardabweichungen
verschoben (T = 31: 2.8 sigma) -- weit jenseits jeder Zielgrenze.

Jetzt (Herleitung: docs/planning/2026-10-18-importance-sampling-ess.md):

1. **Horizont-skalierter Shift.** Gesamtbudget ``c`` (in Standardabweichungen
   des KUMULIERTEN Aktienfaktors), pro Jahr ``mu_t = c / sqrt(T)``. Damit ist
   ``sum_t |mu_t|^2 = c^2`` horizontunabhaengig und der kumulierte Faktor
   ``sum_t Z_t / sqrt(T)`` um genau ``c`` verschoben -- der Shift in der
   Richtung, auf die das Endvermoegen reagiert. ``c = 1.0``.
2. **Defensive Mischung (Hesterberg 1995; Owen/Zhou 2000).** Proposal
   ``alpha * p + (1 - alpha) * q`` mit deterministisch verteilten Komponenten
   (Balance-Heuristik, Veach/Guibas), Gewicht
   ``w = p / (alpha p + (1 - alpha) q) = 1 / (alpha + (1 - alpha) q/p)``.
   Damit ``w <= 1/alpha`` PFADWEISE und ``ESS >= alpha * sum(w)``
   deterministisch. ``alpha = 0.5``.
3. **Selbstnormierte Schaetzer** ``sum(f w) / sum(w)`` ueberall (bestehend);
   Kish-ESS geht als ``n`` in die Wilson-Grenze (``certification.py``).
4. **ESS-Fallback.** Liegt die Kish-ESS eines Wuerfels unter
   ``IS_ESS_FALLBACK_FRACTION * N``, rechnet der Lauf mit Standard-MC und
   weist den Grund im Audit aus (mit 2. praktisch unerreichbar, aber die
   Sicherung gehoert zur Methode, nicht zum Parameter).

Analytisch (Aktienfaktor-Ladung rho in {0.6, 0.9}, Zielfehlschlag-
Wahrscheinlichkeit P in {5 %, 20 %}): ESS/N = 0.83, Varianz-Gewinn gegenueber
Standard-MC 1.06x bis 2.1x, Anteil Pfade im Fehlschlag-Bereich 5 % -> 10-14 %,
20 % -> 30-36 %. Alt (T = 31): Varianz-Effizienz 0.002x.

Der Shift trifft den Aktien-Bucket. MC-2 (2026-06-29): der Index wird aus der
KANONISCHEN scenario_engine.BUCKET_ORDER abgeleitet (Index 0), nicht
hartcodiert.

Aktivierung: ``decide_is_for_context`` (Auto bei konservativem Profil,
Decumulation oder hartem Ziel; Force-On via ``mc_importance_sampling_enabled``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# IMPORTANCE-SAMPLING-ESS-001: Gesamt-Shift-Budget ``c`` in Standard-
# abweichungen des KUMULIERTEN Aktienfaktors (pro Jahr ``c / sqrt(T)``).
# Kalibrierung (Doku Abschnitt 2): ESS/N der Mischung 0.83 bei c = 1.0 und
# alpha = 0.5; der Varianz-Gewinn fuer Zielfehlschlag-Wahrscheinlichkeiten
# von 5-20 % ist im ganzen Raster >= 1 (bei c >= 1.25 faellt er fuer
# schwach aktienlastige Portfolios unter 1, bei c <= 0.5 bleibt der
# Tail-Gewinn klein).
IS_TOTAL_SHIFT_SIGMA = 1.0
# Defensiver Mischungsanteil der Nominalverteilung: Gewichte <= 1/alpha = 2.
IS_DEFENSIVE_MIXTURE_ALPHA = 0.5
# Unter dieser Kish-ESS-Quote rechnet ein Wuerfel mit Standard-MC.
IS_ESS_FALLBACK_FRACTION = 0.30
IS_SCHEME_VERSION = "is_defensive_mixture_horizon_scaled_v1"

# Rueckwaertskompatible Namen: der Default-Shift-VEKTOR ist das Gesamtbudget
# (Norm ``c``) in Richtung des Aktien-Buckets; die Verteilung auf die Jahre
# uebernimmt ``per_year_shift_profile``.
DEFAULT_TAIL_SHIFT_STRENGTH = IS_TOTAL_SHIFT_SIGMA
DEFAULT_TAIL_SHIFT_VECTOR = np.array([-IS_TOTAL_SHIFT_SIGMA, 0.0, 0.0, 0.0, 0.0])


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


def _shift_profile(shift: np.ndarray, horizon_years: int) -> np.ndarray:
    """(B,) -> konstant ueber die Jahre (Altvertrag); (T, B) unveraendert."""
    shift = np.asarray(shift, dtype=np.float64)
    if shift.ndim == 1:
        return np.broadcast_to(shift, (int(horizon_years), shift.shape[0]))
    if shift.shape[0] != int(horizon_years):
        raise ValueError(
            f"shift profile has {shift.shape[0]} years, samples have {horizon_years}"
        )
    return shift


def compute_likelihood_weights(
    x: np.ndarray,
    shift: np.ndarray,
    *,
    mixture_alpha: float = 0.0,
) -> np.ndarray:
    """Likelihood-Ratio ``p(x) / m(x)`` je Pfad.

    Parameters
    ----------
    x : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) -- die TATSAECHLICH
        gezogenen unkorrelierten Standard-Normals (Proposal-Stichprobe, vor
        Cholesky). Nominal ``p = N(0, I)``.
    shift : np.ndarray
        Mittelwert der geshifteten Komponente ``q = N(mu, I)``: Shape
        ``(n_buckets,)`` (in jedem Jahr derselbe Shift, Altvertrag) oder
        ``(horizon_years, n_buckets)`` (Profil je Jahr, siehe
        ``per_year_shift_profile``).
    mixture_alpha : float
        Anteil der Nominalkomponente in der Proposal ``m = alpha p +
        (1 - alpha) q``. ``0`` = reiner Mean-Shift (Altvertrag):
        ``w = exp(-sum_t mu_t x_t + 0.5 sum_t |mu_t|^2)``.

    Returns
    -------
    np.ndarray
        Shape (n_paths,). Mit ``l = log q/p = sum_t mu_t x_t - 0.5 sum_t |mu_t|^2``
        ist ``w = 1 / (alpha + (1 - alpha) exp(l))``, im Log-Raum stabil
        berechnet. Fuer alpha > 0 gilt ``0 < w <= 1/alpha`` je Pfad.
    """
    x = np.asarray(x, dtype=np.float64)
    profile = _shift_profile(shift, int(x.shape[1]))
    log_q_over_p = (
        np.einsum("phb,hb->p", x, profile)
        - 0.5 * float(np.sum(profile * profile))
    )
    alpha = float(mixture_alpha)
    if not 0.0 <= alpha < 1.0:
        raise ValueError("mixture_alpha must lie in [0, 1).")
    if alpha == 0.0:
        return np.exp(-log_q_over_p)
    log_mix = np.logaddexp(np.log(alpha), np.log1p(-alpha) + log_q_over_p)
    return np.exp(-log_mix)


def per_year_shift_profile(
    shift_vector: np.ndarray,
    horizon_years: int,
) -> np.ndarray:
    """Gesamt-Shift ``shift_vector`` (Norm = Budget c) gleichmaessig auf T Jahre.

    ``mu_t = shift_vector / sqrt(T)``: der kumulierte, standardisierte Faktor
    ``sum_t Z_t / sqrt(T)`` ist um genau ``shift_vector`` verschoben und
    ``sum_t |mu_t|^2 = |shift_vector|^2`` haengt nicht von T ab -- die
    Gewichtsvarianz ist horizontunabhaengig (IMPORTANCE-SAMPLING-ESS-001).
    """
    horizon_years = int(max(1, horizon_years))
    vector = np.asarray(shift_vector, dtype=np.float64).reshape(-1)
    per_year = vector / np.sqrt(float(horizon_years))
    return np.tile(per_year, (horizon_years, 1))


def mixture_shifted_mask(n_paths: int, mixture_alpha: float) -> np.ndarray:
    """Deterministische Komponentenzuordnung der defensiven Mischung.

    Pfad ``i`` stammt aus der geshifteten Komponente, wenn
    ``floor((i+1)(1-alpha)) > floor(i (1-alpha))`` -- gleichmaessig verteilt
    (bei alpha = 0.5 abwechselnd), damit jedes Praefix der Pfade dieselbe
    Mischung enthaelt. Mit festen Komponentenanteilen ist das
    Balance-Heuristik-Gewicht ``p / (alpha p + (1-alpha) q)`` unverzerrt
    (Veach/Guibas 1995; Owen/Zhou 2000) und hat kleinere Varianz als eine
    zufaellige Komponentenwahl.
    """
    n_paths = int(max(0, n_paths))
    share = 1.0 - float(mixture_alpha)
    index = np.arange(n_paths, dtype=np.float64)
    return np.floor((index + 1.0) * share + 1e-12) > np.floor(index * share + 1e-12)


def importance_sampling_diagnostics(weights: np.ndarray | None) -> dict:
    """Kish-ESS und Gewichtskonzentration eines Wuerfels (fuer das Audit)."""
    if weights is None:
        return {"ess": None, "ess_fraction": None, "max_weight_share": None}
    from .certification import effective_sample_size

    arr = np.asarray(weights, dtype=np.float64).reshape(-1)
    total = float(np.sum(arr))
    ess = float(effective_sample_size(arr))
    return {
        "ess": ess,
        "ess_fraction": ess / float(arr.size) if arr.size else 0.0,
        "max_weight_share": float(np.max(arr)) / total if total > 0 else None,
        "max_weight_normalized": (
            float(np.max(arr)) * float(arr.size) / total if total > 0 else None
        ),
    }


def ess_requires_fallback(weights: np.ndarray | None) -> bool:
    """True, wenn die Kish-ESS unter ``IS_ESS_FALLBACK_FRACTION * N`` liegt."""
    if weights is None:
        return False
    diag = importance_sampling_diagnostics(weights)
    return float(diag["ess_fraction"] or 0.0) < IS_ESS_FALLBACK_FRACTION


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
