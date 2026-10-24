"""Vektorisierte Szenario-Engine fuer den Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 7,9)

Kontrast zur bestehenden services.portfolio_engine._run_allocation_monte_carlo:
diese ist eine *isolierte* NumPy-Implementierung speziell fuer den Optimizer.
Die existing MC-Engine bleibt unangetastet (Audit-konsistent, alle Z/B/W2.5
Tests gruen). Der Optimizer ruft AUSSCHLIESSLICH diese Engine, nicht die
existing.

Vorteile dieser Engine:
1. NumPy-vektorisiert -> 50-100x schneller als python-loop
2. Cornish-Fisher fat-tail Sampling pro Bucket
3. Antithetic Variates fuer Variance Reduction
4. Deterministischer Seed via numpy Generator
5. Liability-Pfad als zusaetzlicher Outflow-Subtrahierter

Convention:
- bucket order: ('equities', 'bonds', 'real_estate', 'alternatives', 'liquidity')
- weights[i] = Anteil von bucket i (summe = 1.0)
- horizon_years = Anzahl Jahre simuliert
- return_paths shape: (n_paths, horizon_years, 5) - multiplikative Faktoren
  (1.05 = +5% Jahres-Return)
- wealth_paths shape: (n_paths, horizon_years + 1) - in Rappen (kann negativ
  werden = Lebensluecke)

Lebensluecke: konsistent zur existing W2.5-Logik. Wenn wealth nach Cashflow
& Liability negativ wird, wachst es NICHT (kein Zins-auf-Schuld) sondern
bleibt nominal stehen bis Cashflow positiv wird.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from services.cma_validation import (
    CMAValidationError,
    NELSON_SIEGEL_DEFAULT_MATURITY_YEARS,
    correlation_factor,
    parse_correlation_matrix_json,
    validate_equity_kgv_parameters,
    validate_nelson_siegel_parameters,
)
from services.return_moments import (
    arithmetic_moments_to_log_parameters,
    bounded_cornish_fisher,
)

from .distributions import _MAX_EXCESS_KURT, _MAX_SKEW, cornish_fisher_is_monotonic
from services.retirement_phase import is_retired_in_year
from .retained_simulation_context import retain as _retain_context


# Konsistent zu services.portfolio_engine.BUCKET_FIELDS
BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
N_BUCKETS = len(BUCKET_ORDER)


@dataclass(frozen=True)
class ScenarioInputs:
    """Compactes Input-Tupel fuer die Engine.

    Vermeidet Abhaengigkeit von SQLAlchemy Models in der Engine selbst -
    der Caller extrahiert die Werte aus CapitalMarketAssumption.

    Alle bps-Werte sind integer, Cholesky-Matrix ist (5,5) ndarray.
    skew/kurt sind in bps (z.B. -5000 = -0.5 skew). Wenn None, fallback 0.
    """
    mu_bps: np.ndarray  # shape (5,)
    sigma_bps: np.ndarray  # shape (5,)
    skew_bps: np.ndarray  # shape (5,) - 0 wenn nicht gesetzt
    excess_kurt_bps: np.ndarray  # shape (5,) - 0 wenn nicht gesetzt
    cholesky: np.ndarray  # shape (5, 5) lower-triangular
    # CMA-TAIL-MISSINGNESS-SEMANTICS-001: pro Bucket, ob das Tail-Moment am CMA
    # tatsaechlich GESETZT war oder auf 0 defaultete. Beides erzeugt denselben
    # Zahlenwert (und soll das auch), aber im Nachweis muessen die Faelle
    # unterscheidbar sein -- siehe tail_moment_state().
    #
    # Default leeres Tupel, damit die vielen bestehenden
    # ScenarioInputs(...)-Konstruktionen (Tests, Fixtures) unveraendert
    # bleiben; "kein Zustand erfasst" ist dort die ehrliche Angabe.
    skew_state: tuple[str, ...] = ()
    excess_kurt_state: tuple[str, ...] = ()


TAIL_MOMENT_EXPLICIT = "explicit"
TAIL_MOMENT_DEFAULTED = "defaulted"


def tail_moment_state(cma, field_name: str) -> str:
    """War dieses Tail-Moment am CMA gesetzt, oder defaultete es auf 0?

    CMA-TAIL-MISSINGNESS-SEMANTICS-001: beide Engines lesen die
    Skew-/Kurtosis-Felder als ``getattr(cma, name, 0) or 0``. Damit erzeugen
    ``None`` (nie geschaetzt) und eine ausdrueckliche ``0`` denselben
    Laufzeitwert, und nichts weiter unten -- nicht ``ScenarioInputs``, nicht
    die Log-Parameter der Haupt-MC, nicht das CMA-Objekt -- konnte die beiden
    Faelle noch auseinanderhalten.

    Fuer die RECHNUNG ist der Kollaps richtig: beides bedeutet
    normalverteilt, und daran wird hier nichts geaendert. Verloren ging die
    INFORMATION, ob jemand das Moment ueberhaupt angefasst hat.

    Bewusst "explicit" und nicht "approved": es gibt im System kein
    Freigabe-Flag pro Feld (geprueft in models/allocation.py,
    schemas/allocation.py, database.py). Eine 0 in der Datenbank heisst
    "gesetzt", nicht "von einem Modellverantwortlichen geprueft und
    freigegeben". Diese Funktion stellt eine Datentatsache fest und
    behauptet keine Governance, die es nicht gibt -- ein echtes
    Review-/Freigabe-Attribut pro Tail-Moment bleibt ein eigener,
    produktseitig zu entscheidender Schritt.
    """
    raw = getattr(cma, field_name, None)
    return TAIL_MOMENT_DEFAULTED if raw is None else TAIL_MOMENT_EXPLICIT


def tail_moment_provenance(cma) -> dict[str, object]:
    """Nachweis-Block: fuer welche Buckets ist kein Tail-Moment geschaetzt?

    Der Zustand in ``ScenarioInputs`` erreicht nur den Solver-Kanal. Dieser
    Block gehoert in die Modellbasis und damit in den persistierten Nachweis,
    weil die Haupt-MC dieselben Felder mit demselben Ausdruck liest -- die
    Luecke bestand in BEIDEN Kanaelen.

    Ausgewiesen werden die DEFAULTETEN Buckets, nicht alle Zustaende: das ist
    die handlungsrelevante Information ("fuer diese Buckets hat nie jemand ein
    Tail-Moment geschaetzt"), und der Block bleibt kompakt.

    ``approval_flag_exists`` ist bewusst dabei und bewusst ``False``: es gibt
    im System kein Review-/Freigabe-Attribut pro Tail-Moment. Ohne diese
    Angabe koennte "explicit" als "von einem Modellverantwortlichen
    freigegeben" gelesen werden, und das waere eine Governance-Behauptung, die
    die Daten nicht tragen.
    """
    if cma is None:
        # Ohne CMA-Zeile im Scope ist nichts feststellbar. Das wird
        # ausgewiesen und nicht als "alles defaultet" geraten -- sonst
        # behauptet der Nachweis einen Befund, den niemand geprueft hat.
        return {
            "basis": "unknown_no_cma_in_scope",
            "skew_defaulted_buckets": None,
            "excess_kurt_defaulted_buckets": None,
            "all_tail_moments_defaulted": None,
            "approval_flag_exists": False,
        }
    skew_states = {
        bucket: tail_moment_state(cma, f"{bucket}_skewness_bps")
        for bucket in BUCKET_ORDER
    }
    kurt_states = {
        bucket: tail_moment_state(cma, f"{bucket}_excess_kurt_bps")
        for bucket in BUCKET_ORDER
    }
    skew_defaulted = sorted(
        b for b, s in skew_states.items() if s == TAIL_MOMENT_DEFAULTED
    )
    kurt_defaulted = sorted(
        b for b, s in kurt_states.items() if s == TAIL_MOMENT_DEFAULTED
    )
    return {
        "basis": "explicit_vs_defaulted_per_bucket_v1",
        "skew_defaulted_buckets": skew_defaulted,
        "excess_kurt_defaulted_buckets": kurt_defaulted,
        "all_tail_moments_defaulted": (
            len(skew_defaulted) == len(BUCKET_ORDER)
            and len(kurt_defaulted) == len(BUCKET_ORDER)
        ),
        "approval_flag_exists": False,
    }


# ============================================================================
# Cornish-Fisher in NumPy (Vektor-Variante der distributions.py)
# ============================================================================


def cornish_fisher_array(
    z: np.ndarray,
    skew: np.ndarray,
    excess_kurt: np.ndarray,
) -> np.ndarray:
    """NumPy-Variante von distributions.cornish_fisher_quantile.

    z: shape (...) standard-normal Stichproben
    skew, excess_kurt: shape (n_assets,) oder broadcastable

    Clamping konsistent zu distributions._clamp_skew/_clamp_kurt:
    s in [-1, 1], k in [0, 8].
    """
    s = np.clip(skew, -_MAX_SKEW, _MAX_SKEW)
    k = np.clip(excess_kurt, 0.0, _MAX_EXCESS_KURT)
    return np.asarray(bounded_cornish_fisher(z, s, k), dtype=np.float64)


def _log_parameters_for_inputs(
    inputs: ScenarioInputs,
) -> tuple[np.ndarray, np.ndarray]:
    mu = np.asarray(inputs.mu_bps, dtype=np.float64) / 10_000.0
    sigma = np.asarray(inputs.sigma_bps, dtype=np.float64) / 10_000.0
    skew = np.clip(
        np.asarray(inputs.skew_bps, dtype=np.float64) / 10_000.0,
        -_MAX_SKEW,
        _MAX_SKEW,
    )
    kurt = np.clip(
        np.asarray(inputs.excess_kurt_bps, dtype=np.float64) / 10_000.0,
        0.0,
        _MAX_EXCESS_KURT,
    )
    locations = np.empty(N_BUCKETS, dtype=np.float64)
    scales = np.empty(N_BUCKETS, dtype=np.float64)
    for index in range(N_BUCKETS):
        locations[index], scales[index] = (
            arithmetic_moments_to_log_parameters(
                float(mu[index]),
                float(sigma[index]),
                skew=float(skew[index]),
                excess_kurtosis=float(kurt[index]),
                use_cornish_fisher=True,
            )
        )
    return locations, scales


# ============================================================================
# Build Scenario Paths
# ============================================================================


def _safe_cholesky(corr_matrix: np.ndarray) -> np.ndarray:
    """Strict PSD correlation factor (legacy function name retained).

    Invalid matrices are CMA domain errors. Singular but valid PSD matrices
    use an eigen-factor and are not silently replaced with identity.
    """
    return correlation_factor(corr_matrix)


def build_default_correlation_matrix() -> np.ndarray:
    """Default 5x5 Korrelationsmatrix (CH-Markt, konservativ).

    Sprint U-P0 Fix C7: Single-Source-of-Truth aus portfolio_engine importieren.
    Vorher waren hier andere Werte hartcodiert (equity-bonds=-0.10 vs -0.20
    in portfolio_engine), was zwei divergierende Engine-Pfade produzierte.
    Reihenfolge: equities, bonds, real_estate, alternatives, liquidity.
    """
    from services.portfolio_engine import _DEFAULT_CORRELATION_MATRIX
    return np.array(_DEFAULT_CORRELATION_MATRIX)


def build_scenario_paths(
    inputs: ScenarioInputs,
    *,
    horizon_years: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
) -> np.ndarray:
    """Liefert (n_paths, horizon_years, 5) array von log-normal Returns.

    Pro Pfad pro Jahr pro Asset wird ein multiplikativer Faktor
    R = exp(location + scale * Z_correlated_cf) erzeugt. ``location`` und
    ``scale`` werden so kalibriert, dass die einfachen Returns exakt die
    arithmetischen CMA-Momente ``mu`` und ``sigma`` besitzen.

    Antithetic Variates: wenn True, wird die zweite Haelfte der Pfade als
    -Z gespiegelt. Das reduziert Varianz fuer symmetrische Statistiken
    (Mean, Median) und ist Standard in Mulvey/Ziemba-MC.

    Determinismus: gleicher seed + gleiche inputs -> identische Output-Array.
    Wir nutzen np.random.default_rng(seed) (PCG64), nicht legacy RandomState.
    """
    horizon_years = int(max(1, horizon_years))
    n_paths = int(max(1, n_paths))

    if antithetic:
        half = (n_paths + 1) // 2  # round up; antithetic ergaenzt zur Gesamtzahl
    else:
        half = n_paths

    rng = np.random.default_rng(np.uint64(seed))
    # Independent standard normals: shape (half, horizon, n_buckets)
    Z = rng.standard_normal(size=(half, horizon_years, N_BUCKETS))

    # Apply Cholesky correlation per (path, year) - shape stays (half, horizon, n_buckets)
    # Z @ chol.T (broadcasted): np.einsum is most explicit
    Z_corr = np.einsum("phb,kb->phk", Z, inputs.cholesky)

    # Cornish-Fisher per asset (broadcasting)
    skew = inputs.skew_bps / 10_000.0  # bps -> decimal
    kurt = inputs.excess_kurt_bps / 10_000.0
    Z_cf = cornish_fisher_array(Z_corr, skew, kurt)

    if antithetic:
        # Antithetic: -Z (auch durch Cholesky, sollte gleich sein)
        Z_anti_corr = -Z_corr
        Z_anti_cf = cornish_fisher_array(Z_anti_corr, skew, kurt)
        Z_combined = np.concatenate([Z_cf, Z_anti_cf], axis=0)[:n_paths]
    else:
        Z_combined = Z_cf

    log_location, log_scale = _log_parameters_for_inputs(inputs)
    log_returns = log_location + log_scale * Z_combined
    return_factors = np.exp(log_returns)
    return return_factors


SAMPLING_UNIT_ANTITHETIC_PAIR = "antithetic_pair"
SAMPLING_UNIT_PATH = "path"


def sampling_unit_ids(n_paths: int, *, antithetic: bool) -> np.ndarray:
    """Unabhaengige Stichprobeneinheit je Pfad (RESAMPLING-ANTITHETIC-BOOTSTRAP-001).

    Expliziter Layout-Vertrag zu ``build_scenario_paths``: bei
    ``antithetic=True`` liegen die ``half = ceil(n/2)`` Basispfade in den
    Zeilen ``0..half-1`` und ihre gespiegelten Partner in ``half..n-1``;
    Pfad ``i`` und Pfad ``i + half`` sind EINE Einheit (dieselbe Ziehung
    ``Z``). Bei ungerader Pfadzahl hat der letzte Basispfad (``half-1``)
    keinen Partner -- er ist eine eigene Einheit mit einem Mitglied.

    Ohne Antithetics ist jeder Pfad seine eigene Einheit.

    Ein Bootstrap muss EINHEITEN ziehen, nicht Zeilen: nichtlineare
    Portfolio-Verlustdifferenzen zweier Partnerpfade koennen positiv
    korreliert sein; Zeilen-Resampling behandelt dann ``2m`` abhaengige
    Beobachtungen wie ``2m`` unabhaengige und unterschaetzt die Streuung.
    """
    n_paths = int(max(1, n_paths))
    if not antithetic:
        return np.arange(n_paths, dtype=np.int64)
    half = (n_paths + 1) // 2
    ids = np.arange(n_paths, dtype=np.int64)
    ids[half:] -= half
    return ids


def build_scenario_paths_with_weights(
    inputs: ScenarioInputs,
    *,
    horizon_years: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
    use_importance_sampling: bool = False,
    is_shift_strength: float | None = None,
    is_mixture_alpha: float | None = None,
    weight_horizon_years: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Liefert Pfade + Likelihood-Weights (Phase 5b Stochastic-Optimizer-Spec).

    Wenn use_importance_sampling=False, identisch zu build_scenario_paths()
    + weights = ones(n_paths) (trivialer Estimator).

    Wenn use_importance_sampling=True (IMPORTANCE-SAMPLING-ESS-001): defensive
    Mischung aus Nominalverteilung (Anteil ``is_mixture_alpha``) und einer
    Komponente mit horizont-skaliertem Mean-Shift auf den Aktienfaktor
    (Gesamtbudget ``is_shift_strength`` Standardabweichungen des
    KUMULIERTEN Faktors, pro Jahr ``/ sqrt(horizon_years)``). Siehe
    importance_sampling.py.

    Parameters
    ----------
    inputs, horizon_years, n_paths, seed, antithetic
        Wie in build_scenario_paths(). ``horizon_years`` ist der gezogene
        (gemeinsame Szenario-)Horizont; der Shift wird darauf verteilt.
    use_importance_sampling : bool
        Default False.
    is_shift_strength : float | None
        Gesamt-Shift-Budget c. None = ``IS_TOTAL_SHIFT_SIGMA``.
    is_mixture_alpha : float | None
        Nominal-Anteil der Mischung. None = ``IS_DEFENSIVE_MIXTURE_ALPHA``.
    weight_horizon_years : int | None
        Anzahl der fuehrenden Jahre, die der Aufrufer tatsaechlich verwendet
        (Optimierungshorizont; Pfade werden danach gekuerzt). Die Gewichte
        sind die Likelihood-Ratio der MARGINALE dieser Jahre -- korrekt fuer
        die gekuerzten Pfade und ohne die Varianz der verworfenen Jahre.
        None = alle gezogenen Jahre.

    Returns
    -------
    paths : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — log-normal return factors.
    weights : np.ndarray
        Shape (n_paths,) — Likelihood-Ratio. Bei IS off: alle 1.0.

    Notes
    -----
    Antithetic + Importance Sampling werden NICHT kombiniert. Wenn IS aktiv,
    wird antithetic intern auf False gesetzt (die geshiftete Komponente ist
    asymmetrisch, eine Spiegelung wuerde sie aufheben).
    """
    from .importance_sampling import (
        IS_DEFENSIVE_MIXTURE_ALPHA,
        IS_TOTAL_SHIFT_SIGMA,
        build_shift_vector,
        compute_likelihood_weights,
        make_default_weights,
        mixture_shifted_mask,
        per_year_shift_profile,
    )

    n_paths = int(max(1, n_paths))

    if not use_importance_sampling:
        paths = build_scenario_paths(
            inputs,
            horizon_years=horizon_years,
            n_paths=n_paths,
            seed=seed,
            antithetic=antithetic,
        )
        return paths, make_default_weights(n_paths)

    horizon_years = int(max(1, horizon_years))
    strength = IS_TOTAL_SHIFT_SIGMA if is_shift_strength is None else float(is_shift_strength)
    alpha = IS_DEFENSIVE_MIXTURE_ALPHA if is_mixture_alpha is None else float(is_mixture_alpha)
    weight_horizon = (
        horizon_years
        if weight_horizon_years is None
        else int(min(max(1, int(weight_horizon_years)), horizon_years))
    )
    rng = np.random.default_rng(np.uint64(seed))
    z_uncorrelated = rng.standard_normal(size=(n_paths, horizon_years, N_BUCKETS))

    profile = per_year_shift_profile(
        build_shift_vector(N_BUCKETS, strength=strength), horizon_years,
    )
    shifted = mixture_shifted_mask(n_paths, alpha)
    # Proposal-Stichprobe: Nominalkomponente unveraendert, geshiftete
    # Komponente um das Jahresprofil verschoben.
    x = z_uncorrelated + shifted[:, None, None] * profile[None, :, :]
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit) gilt weiter: die Gewichte sind
    # eine Funktion der TATSAECHLICH gezogenen Stichprobe x, nicht des
    # Pre-Shift-Werts. Balance-Heuristik: JEDER Pfad (beider Komponenten)
    # bekommt p(x) / (alpha p(x) + (1-alpha) q(x)).
    weights = compute_likelihood_weights(
        x[:, :weight_horizon, :], profile[:weight_horizon], mixture_alpha=alpha,
    )

    # Cholesky + Cornish-Fisher + Itô-Korrektur — gleiche Pipeline wie
    # build_scenario_paths, aber auf der Proposal-Stichprobe
    z_corr = np.einsum("phb,kb->phk", x, inputs.cholesky)
    skew = inputs.skew_bps / 10_000.0
    kurt = inputs.excess_kurt_bps / 10_000.0
    z_cf = cornish_fisher_array(z_corr, skew, kurt)
    log_location, log_scale = _log_parameters_for_inputs(inputs)
    log_returns = log_location + log_scale * z_cf
    return_factors = np.exp(log_returns)
    return return_factors, weights


# ============================================================================
# Simulate Wealth Paths
# ============================================================================


def _compute_per_path_wealth_tax_drag(
    grown: np.ndarray,
    *,
    tax_regime,
    ctx_template_kwargs: dict,
    tax_mode: str,
    n_bins: int = 20,
) -> np.ndarray:
    """Sprint B2 (2026-06-07): Liefert per-Pfad Wealth-Tax-Drag-Faktor.

    Returns shape (n_paths,) Float-Array mit dem multiplikativen Drag
    pro Pfad (z.B. 0.997 = 0.3% Steuer). Bei Pfaden mit wealth <= 0:
    1.0 (kein Drag).

    Modi:
    - 'median': MEDIAN ueber alle positive wealth → 1 Steuer-Rate fuer alle
      (Backwards-Compat, schnellster Pfad)
    - 'binned': Quantil-Binning in n_bins Schritten, pro Bin eine Rate.
      Empfohlen fuer HNW-Mandate mit progressivem Tarif (CH-Vermoegenssteuer).
      ~n_bins × 1 Tax-Call/Jahr statt 1 (Median) oder n_paths (Per-Path).
    - 'per_path': Eine Tax-Rate pro Pfad (volle Genauigkeit, langsam).
      Nur fuer Audit/Vergleichstests.
    """
    from services.tax.base import TaxContext

    n_paths = grown.shape[0]
    drag = np.ones(n_paths, dtype=np.float64)
    positive_mask = grown > 0
    if not positive_mask.any():
        return drag

    if tax_mode == "median":
        ctx = TaxContext(
            wealth_rappen=float(np.median(grown[positive_mask])),
            **ctx_template_kwargs,
        )
        wt = tax_regime.annual_wealth_tax(ctx)
        if wt.effective_bps > 0:
            drag = np.where(positive_mask, 1.0 - wt.effective_bps / 10000.0, 1.0)
        return drag

    if tax_mode == "per_path":
        # Loop per Pfad — langsam aber maximal genau
        for p in range(n_paths):
            if not positive_mask[p]:
                continue
            ctx = TaxContext(
                wealth_rappen=float(grown[p]),
                **ctx_template_kwargs,
            )
            wt = tax_regime.annual_wealth_tax(ctx)
            if wt.effective_bps > 0:
                drag[p] = 1.0 - wt.effective_bps / 10000.0
        return drag

    # 'binned' (Default-Empfehlung fuer B2)
    pos_wealth = grown[positive_mask]
    n_bins_eff = min(int(n_bins), int(pos_wealth.size))
    if n_bins_eff <= 1:
        # Edge: nur ein positiver Pfad → wie per_path
        ctx = TaxContext(
            wealth_rappen=float(pos_wealth[0]),
            **ctx_template_kwargs,
        )
        wt = tax_regime.annual_wealth_tax(ctx)
        if wt.effective_bps > 0:
            drag = np.where(positive_mask, 1.0 - wt.effective_bps / 10000.0, 1.0)
        return drag
    # Quantil-Bins
    quantiles = np.linspace(0, 1, n_bins_eff + 1)
    bin_edges = np.quantile(pos_wealth, quantiles)
    # Bin-Repraesentant: Median pro Bin
    bin_rates = np.zeros(n_bins_eff, dtype=np.float64)
    for b in range(n_bins_eff):
        in_bin = (pos_wealth >= bin_edges[b]) & (pos_wealth <= bin_edges[b + 1])
        if not in_bin.any():
            continue
        bin_repr = float(np.median(pos_wealth[in_bin]))
        ctx = TaxContext(
            wealth_rappen=bin_repr,
            **ctx_template_kwargs,
        )
        wt = tax_regime.annual_wealth_tax(ctx)
        bin_rates[b] = float(wt.effective_bps)
    # Assign Pfad zu Bin via digitize (auf positiven Pfaden)
    bin_idx = np.clip(
        np.digitize(grown, bin_edges) - 1, 0, n_bins_eff - 1,
    )
    # Drag fuer positive Pfade: 1 - rate/10000; negative bleiben 1.0
    rates_per_path = np.where(positive_mask, bin_rates[bin_idx], 0.0)
    drag = 1.0 - rates_per_path / 10000.0
    return drag


def simulate_wealth_paths(
    *,
    initial_wealth_rappen: int,
    weights: np.ndarray,
    return_paths: np.ndarray,
    cashflow_series_rappen: Iterable[int],
    liability_path_rappen: Iterable[int] | None = None,
    tax_regime=None,
    dividend_yield_bps_per_bucket: np.ndarray | None = None,
    base_calendar_year: int = 2026,
    mandate_age_at_start: int | None = None,
    is_retired: bool = False,
    death_year_index_per_path: np.ndarray | None = None,
    tax_mode: str = "median",
    tax_n_bins: int = 20,
    portfolio_factors: np.ndarray | None = None,
    is_retired_series: Sequence[bool] | None = None,
    retain_scope_context: bool = True,
) -> np.ndarray:
    """Simuliert Wealth-Pfad ueber alle Szenarien — optional steuer-aware.

    weights: shape (5,), summe ~ 1.0 (Toleranz: keine Constraint hier)
    return_paths: shape (n_paths, horizon, 5) aus build_scenario_paths
    cashflow_series_rappen: shape (horizon,) - Netto-Cashflow pro Jahr
        (positiv = Income > Expense)
    liability_path_rappen: shape (horizon,) - Goal-Outflows pro Jahr
        (positiv = Outflow). Wird vom Cashflow subtrahiert (also wealth wird
        kleiner). None = kein Goal-Outflow.
    tax_regime: TaxRegime-Instanz fuer steuer-aware Simulation. None =
        keine Steuern (Backwards-Compat zur Vor-Sprint-3-Version).
        Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md
    dividend_yield_bps_per_bucket: shape (5,), Dividend-Yield pro Bucket
        in bps. Nur relevant wenn tax_regime != None. Bestimmt das
        Dividenden-Einkommen pro Jahr (= wealth * weights @ yields).
    base_calendar_year: Start-Kalender-Jahr fuer Tax-Year-Versioning
        (TaxContext.calendar_year = base_calendar_year + t).
    mandate_age_at_start: optionales Alter des Mandanten zu t=0 fuer
        altersabhaengige Steuern (CH-Pension-Lumpsum, AHV-Alter).
    is_retired: Decumulation-Phase Flag (CH-Pillar-3a-Befreiung) -- statisch
        fuer alle Jahre, wenn ``is_retired_series`` fehlt (Vor-Verhalten).
    is_retired_series: optional Ruhestandsstatus je Jahr t
        (DYNAMIC-RETIREMENT-PHASE-001, services.retirement_phase). Gesetzt
        bestimmt er ``TaxContext.is_retired`` jahresweise; jenseits der Serie
        gilt ihr letzter Wert.
    death_year_index_per_path: optional shape (n_paths,) integer-Array
        mit Sterbe-Jahr-Index pro Pfad. Wenn gesetzt, werden Cashflow
        und Liability nach death_year_index auf 0 gesetzt (pro Pfad).
        Spec: docs/planning/2026-05-17-sprint-4-bfs-mortality.md
        Konvention: death_year_index[p]=5 → Pfad p lebt in t=0..4 (cashflow
        aktiv), ab t=5 cashflow=0. Wachstum laeuft weiter (Erbschaft, aber
        keine weiteren Einnahmen/Ausgaben).

    retain_scope_context: haelt den eingefrorenen Simulationskontext zum
        zurueckgegebenen Array fest (``retained_simulation_context``), damit
        abweichende Prioritaets-Scopes ohne expliziten Replay-Kontext exakt
        -- inklusive pfadweiser Todesmaske -- direkt simuliert werden
        koennen. Aendert keine Zahl des Pfads. Der Solver setzt ``False``
        (er reicht seinen Replay-Kontext immer explizit weiter).

    portfolio_factors: optional shape (n_paths, horizon) -- die bereits
        abgeleiteten Jahres-Wachstumsfaktoren ``return_paths @ weights``
        (``solver._portfolio_return_factors``). Reine Performance-Abkuerzung
        fuer den Solver-Hotpath (SAA-RESAMPLED-RUNTIME-001): der Aufrufer
        braucht dieselbe Groesse ohnehin fuer die annualisierte Rendite, und
        die Ableitung erfolgt hier wie dort mit derselben einsum-Kontraktion
        ueber die Buckets -- das Ergebnis ist bitidentisch zur bisherigen
        Ableitung pro Jahr (Regressionstest
        ``test_simulate_wealth_paths_fast_path_bit_identical``).

    Returns: (n_paths, horizon + 1) wealth array. wealth[:, 0] = initial,
    wealth[:, t+1] = wealth nach Wachstum (- Steuern wenn aktiv) + Cashflow
    - Liability im Jahr t.

    Steuer-Order pro Jahr (wenn tax_regime aktiv):
    1. Wachstum: prev * portfolio_factor
    2. Dividenden-Steuer auf Yield-Komponente des Wachstums
       (nur wenn dividend_yield_bps_per_bucket gesetzt)
    3. Vermoegenssteuer auf Wealth nach Wachstum
       (nur wenn tax_regime.supports_wealth_tax)
    4. Cashflow + Liability

    Lebensluecke (W2.5-konsistent): wealth kann negativ werden. Bei
    negativem wealth wird KEIN Zins-Effekt angewendet (deficit waechst nicht
    durch Schuldzinsen - nur durch weitere negative Cashflows). Steuern
    werden ebenfalls nur auf positives Wealth angewendet.
    """
    return_paths = np.asarray(return_paths, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64).reshape(N_BUCKETS)
    n_paths, horizon, n_buckets = return_paths.shape
    if n_buckets != N_BUCKETS:
        raise ValueError(f"return_paths last dim must be {N_BUCKETS}, got {n_buckets}")

    cashflow = np.asarray(list(cashflow_series_rappen), dtype=np.float64)
    if cashflow.shape != (horizon,):
        # Pad/trim auf horizon
        padded = np.zeros(horizon, dtype=np.float64)
        copy_len = min(horizon, cashflow.size)
        padded[:copy_len] = cashflow[:copy_len]
        cashflow = padded

    if liability_path_rappen is None:
        liability = np.zeros(horizon, dtype=np.float64)
    else:
        liability = np.asarray(list(liability_path_rappen), dtype=np.float64)
        if liability.shape != (horizon,):
            padded = np.zeros(horizon, dtype=np.float64)
            copy_len = min(horizon, liability.size)
            padded[:copy_len] = liability[:copy_len]
            liability = padded

    # Mortalitaets-Maske: pro Pfad cashflow/liability auf 0 nach Tod
    if death_year_index_per_path is not None:
        death_idx = np.asarray(death_year_index_per_path, dtype=np.int32)
        if death_idx.shape != (n_paths,):
            raise ValueError(
                f"death_year_index_per_path must be shape ({n_paths},), got {death_idx.shape}"
            )
        # Maske: shape (n_paths, horizon), True wenn Pfad lebt in Jahr t
        t_range = np.arange(horizon, dtype=np.int32)
        alive_mask = t_range[None, :] < death_idx[:, None]
        cashflow_per_path = cashflow[None, :] * alive_mask
        liability_per_path = liability[None, :] * alive_mask
    else:
        cashflow_per_path = None  # Sentinel: nutze 1D cashflow direkt
        liability_per_path = None

    # Dividend-Yield pro Bucket vorbereiten — fuer Vektor-Dividenden-Berechnung
    dividend_yield_weighted_bps = 0.0
    if dividend_yield_bps_per_bucket is not None and tax_regime is not None:
        dy = np.asarray(dividend_yield_bps_per_bucket, dtype=np.float64)
        if dy.shape != (N_BUCKETS,):
            raise ValueError(
                f"dividend_yield_bps_per_bucket must be shape ({N_BUCKETS},), got {dy.shape}"
            )
        dividend_yield_weighted_bps = float(np.dot(weights, dy))  # gewichteter bps

    # Portfolio-Faktor pro Pfad und Jahr: gewichtete Summe der Asset-Returns.
    # SAA-RESAMPLED-RUNTIME-001 (2026-10-18): einmal fuer alle Jahre statt
    # einer einsum-Kontraktion je Jahr. Jedes Element ist dieselbe Summe ueber
    # die 5 Buckets in derselben Reihenfolge -- bitidentisch, aber ohne
    # ``horizon`` Python-/einsum-Aufrufe pro Zielfunktionsauswertung (der
    # Solver wertet die Zielfunktion je Lauf zehntausendfach aus).
    if portfolio_factors is None:
        portfolio_factors = np.einsum("phb,b->ph", return_paths, weights)
    else:
        portfolio_factors = np.asarray(portfolio_factors, dtype=np.float64)
        if portfolio_factors.shape != (n_paths, horizon):
            raise ValueError(
                "portfolio_factors must be shape "
                f"({n_paths}, {horizon}), got {portfolio_factors.shape}"
            )

    def _retained(wealth_out: np.ndarray) -> np.ndarray:
        if not retain_scope_context or tax_mode != "median" or int(tax_n_bins) != 20:
            return wealth_out
        return _retain_context(wealth_out, {
            "initial_wealth_rappen": initial_wealth_rappen,
            "weights": weights.copy(),
            "return_paths": return_paths,
            "cashflow_series_rappen": tuple(cashflow.tolist()),
            "liability_path_rappen": tuple(liability.tolist()),
            "death_year_index_per_path": (
                None if death_year_index_per_path is None
                else np.array(death_year_index_per_path, dtype=np.int32, copy=True)
            ),
            "tax_regime": tax_regime,
            "dividend_yield_bps_per_bucket": dividend_yield_bps_per_bucket,
            "base_calendar_year": base_calendar_year,
            "mandate_age_at_start": mandate_age_at_start,
            "is_retired": is_retired,
            "is_retired_series": (
                None if is_retired_series is None else tuple(is_retired_series)
            ),
            "portfolio_factors": portfolio_factors,
        })

    if tax_regime is None:
        return _retained(_simulate_wealth_paths_untaxed(
            initial_wealth_rappen=initial_wealth_rappen,
            portfolio_factors=portfolio_factors,
            cashflow=cashflow,
            liability=liability,
            cashflow_per_path=cashflow_per_path,
            liability_per_path=liability_per_path,
        ))

    wealth = np.empty((n_paths, horizon + 1), dtype=np.float64)
    wealth[:, 0] = float(initial_wealth_rappen)

    # Lazy-Import: vermeidet Zirkular-Dependency wenn TaxRegime services.tax nicht importiert ist
    from services.tax.base import TaxContext

    for t in range(horizon):
        portfolio_factor = portfolio_factors[:, t]
        prev = wealth[:, t]
        # Wachstum nur fuer positive Wealth; negative bleibt nominal (W2.5)
        grown = np.where(prev > 0, prev * portfolio_factor, prev)

        if tax_regime is not None:
            # Sprint B2 (2026-06-07): per-Pfad-Tax-Modes statt nur Median.
            # 'median' = Backwards-Compat, 'binned' = besserer Default fuer
            # progressive Tarife (CH-Vermoegenssteuer), 'per_path' = volle
            # Genauigkeit fuer Audit-Tests.
            age_t = (mandate_age_at_start + t) if mandate_age_at_start is not None else None
            ctx_template_kwargs = dict(
                year_index=t,
                calendar_year=base_calendar_year + t,
                age=age_t,
                is_retired=is_retired_in_year(
                    is_retired_series, t, default=is_retired,
                ),
            )
            # Dividenden-Steuer-Drag bleibt repraesentativ (Yield ist ein
            # Asset-Charakteristikum, nicht wealth-skaliert wie Vermoegensteuer).
            # Reprasentations-Context: median wealth (wie pre-B2).
            positive_mask_for_div = grown > 0
            if dividend_yield_weighted_bps > 0 and positive_mask_for_div.any():
                ctx_for_div = TaxContext(
                    wealth_rappen=float(np.median(grown[positive_mask_for_div])),
                    **ctx_template_kwargs,
                )
                div_income_repr = ctx_for_div.wealth_rappen * dividend_yield_weighted_bps / 10000.0
                div_tax_result = tax_regime.dividend_tax(ctx_for_div, div_income_repr)
                div_drag_bps = div_tax_result.effective_bps * dividend_yield_weighted_bps / 10000.0
                grown = np.where(
                    grown > 0,
                    grown * (1.0 - div_drag_bps / 10000.0),
                    grown,
                )

            # 3. Vermoegenssteuer pro Pfad — KERN-VERBESSERUNG B2
            if tax_regime.supports_wealth_tax:
                drag = _compute_per_path_wealth_tax_drag(
                    grown,
                    tax_regime=tax_regime,
                    ctx_template_kwargs=ctx_template_kwargs,
                    tax_mode=tax_mode,
                    n_bins=tax_n_bins,
                )
                # drag ist 1.0 fuer wealth <= 0 (kein Effekt)
                grown = grown * drag

        if cashflow_per_path is not None:
            wealth[:, t + 1] = grown + cashflow_per_path[:, t] - liability_per_path[:, t]
        else:
            wealth[:, t + 1] = grown + cashflow[t] - liability[t]

    return _retained(wealth)


def _simulate_wealth_paths_untaxed(
    *,
    initial_wealth_rappen: int,
    portfolio_factors: np.ndarray,
    cashflow: np.ndarray,
    liability: np.ndarray,
    cashflow_per_path: np.ndarray | None,
    liability_per_path: np.ndarray | None,
) -> np.ndarray:
    """Steuerfreier Kern von ``simulate_wealth_paths`` (SAA-RESAMPLED-RUNTIME-001).

    Exakt dieselbe Rekursion wie die Steuer-Schleife ohne Steuerschritte:
    ``grown = prev * f`` nur fuer ``prev > 0`` (sonst ``prev``), danach
    ``(grown + cashflow) - liability`` -- gleiche Operationen in gleicher
    Reihenfolge, daher bitidentisch. Gerechnet wird jahresweise auf
    zusammenhaengenden Zeilen (Jahr x Pfad) statt auf gestrideten Spalten
    und ohne Zwischen-Arrays je Jahr; zurueckgegeben wird wie bisher ein
    C-zusammenhaengendes (n_paths, horizon + 1)-Array.
    """
    n_paths, horizon = portfolio_factors.shape
    factors_by_year = np.ascontiguousarray(portfolio_factors.T)
    wealth_by_year = np.empty((horizon + 1, n_paths), dtype=np.float64)
    wealth_by_year[0] = float(initial_wealth_rappen)
    if cashflow_per_path is not None:
        cashflow_by_year = np.ascontiguousarray(cashflow_per_path.T)
        liability_by_year = np.ascontiguousarray(liability_per_path.T)
    else:
        cashflow_by_year = None
        liability_by_year = None
    grown = np.empty(n_paths, dtype=np.float64)
    positive = np.empty(n_paths, dtype=bool)
    for t in range(horizon):
        prev = wealth_by_year[t]
        # Wachstum nur fuer positive Wealth; negative bleibt nominal (W2.5)
        np.greater(prev, 0, out=positive)
        np.copyto(grown, prev)
        np.multiply(prev, factors_by_year[t], out=grown, where=positive)
        nxt = wealth_by_year[t + 1]
        if cashflow_by_year is not None:
            np.add(grown, cashflow_by_year[t], out=nxt)
            np.subtract(nxt, liability_by_year[t], out=nxt)
        else:
            np.add(grown, cashflow[t], out=nxt)
            # x - 0.0 == x bitgenau (auch fuer -0.0 und NaN): Jahre ohne
            # Goal-Outflow sparen den Aufruf, ohne das Ergebnis zu aendern.
            if liability[t] != 0.0:
                np.subtract(nxt, liability[t], out=nxt)
    return np.ascontiguousarray(wealth_by_year.T)


# ============================================================================
# Helper: Inputs aus CMA-like Object (loose duck-typing)
# ============================================================================


def scenario_inputs_from_cma(cma, sub_allocations: list[dict] | None = None) -> ScenarioInputs:
    """Extrahiert ScenarioInputs aus einem CMA-Objekt (oder Mock mit gleichen Attributen).

    Sprint B1 (2026-06-07): sub_allocations enables Sub-Allocation-Aware
    Bucket-Returns. Wenn list[dict] uebergeben wird, werden Bucket-Returns
    und -Vols nach den realen Sub-Gewichten berechnet (statt Durchschnitt
    aller verfuegbaren Sub-CMA-Werte).

    sub_allocations: list[dict] mit Keys 'asset_class', 'sub_asset_class',
    'target_weight_bps'. Konsistent zur Konvention in portfolio_engine.
    _weighted_bucket_metrics (Single-Source-of-Truth).

    Backwards-Compat: ohne sub_allocations gelten die historischen
    Bucket-Defaults. Deren Materialisierung erfolgt nun bewusst ueber dieselbe
    Single-Source-of-Truth wie im Reporting.

    Korrelation: nur ein fehlendes/leer gespeichertes Payload nutzt die
    Swiss-market Default-Matrix. Ein vorhandenes Payload wird strikt auf
    Shape, endliche Werte, Range, Symmetrie und PSD validiert.
    """
    # Materialise through the same path as reporting. This is unconditional:
    # a present corrupt Sub-CMA payload is invalid even without sleeves.
    try:
        from services.portfolio_engine import _weighted_bucket_metrics
        sub_returns, sub_vols = _weighted_bucket_metrics(
            cma,
            sub_allocations,
            strict=bool(sub_allocations),
        )
        bucket_returns = {b: float(sub_returns[b]) for b in BUCKET_ORDER}
        bucket_vols = {b: float(sub_vols[b]) for b in BUCKET_ORDER}
    except Exception as exc:
        from .constraints import OptimizerInputError

        if isinstance(exc, OptimizerInputError):
            raise
        raise OptimizerInputError(f"Invalid CMA model input: {exc}") from exc

    mu_bps = np.array([bucket_returns[b] for b in BUCKET_ORDER], dtype=np.float64)
    sigma_bps = np.array([bucket_vols[b] for b in BUCKET_ORDER], dtype=np.float64)
    if not np.all(np.isfinite(mu_bps)) or np.any(mu_bps <= -10_000.0):
        from .constraints import OptimizerInputError

        raise OptimizerInputError(
            "CMA expected returns must be finite and greater than -100%."
        )
    if not np.all(np.isfinite(sigma_bps)) or np.any(sigma_bps < 0.0):
        from .constraints import OptimizerInputError

        raise OptimizerInputError(
            "CMA expected volatilities must be finite and non-negative."
        )

    # Skew + Kurt: Phase 1 Felder pro Bucket aus CMA
    skew_bps = np.array([
        int(getattr(cma, f"{b}_skewness_bps", 0) or 0)
        for b in BUCKET_ORDER
    ], dtype=np.float64)
    excess_kurt_bps = np.array([
        int(getattr(cma, f"{b}_excess_kurt_bps", 0) or 0)
        for b in BUCKET_ORDER
    ], dtype=np.float64)
    # CMA-TAIL-MISSINGNESS-SEMANTICS-001: derselbe Ausdruck laesst NULL und
    # eine explizite 0 auf denselben Wert kollabieren -- das ist fuer die
    # RECHNUNG richtig (beides heisst normalverteilt), aber der Zustand ging
    # dabei verloren. Er wird hier mitgefuehrt, ohne die Zahlen anzutasten.
    skew_state = tuple(
        tail_moment_state(cma, f"{b}_skewness_bps") for b in BUCKET_ORDER
    )
    excess_kurt_state = tuple(
        tail_moment_state(cma, f"{b}_excess_kurt_bps") for b in BUCKET_ORDER
    )

    # CORNISH-FISHER-NON-MONOTONIC-CLAMP-BOUNDS-001 (Kontrollrunde 2026-09-27):
    # der Clamp allein (services.optimizer.distributions._clamp_skew/_clamp_kurt)
    # schliesst nicht-monotone Kombinationen NICHT aus -- z.B. skew=-1.0 (der
    # erlaubte Rand) mit excess_kurt=0.0 (der erlaubte Minimalwert) invertiert
    # die transformierte Quantilfunktion ueber weite Teile der rechten Flanke.
    # Die primaere, immer aktive Absicherung ist services.cma_validation.
    # validate_runtime_cma_completeness() -- die _weighted_bucket_metrics()
    # oben unconditional (auch mit sub_allocations) ueber _asset_class_
    # expected_metrics() aufruft, bevor dieser Punkt ueberhaupt erreicht wird.
    # Dieser zweite Guard ist bewusst redundant (Defense-in-Depth): er
    # schuetzt gegen einen kuenftigen Refactor von _weighted_bucket_metrics,
    # der diesen Aufruf entfernt, sowie gegen DB-Zeilen aus der Zeit vor
    # diesem Fix, falls sie je einen Pfad erreichen, der die Reporting-
    # Validierung umgeht. Ohne IRGENDEINEN dieser Guards wuerde ein
    # kaputtes Bucket-Paar unbemerkt eine invertierte Ertragsverteilung in
    # die Monte-Carlo-Pfaderzeugung einspeisen -- P5/P25/Median-Perzentile
    # und darauf aufbauende VaR/CVaR-Kennzahlen waeren falsch.
    for index, bucket in enumerate(BUCKET_ORDER):
        if not cornish_fisher_is_monotonic(
            float(skew_bps[index]) / 10_000.0,
            float(excess_kurt_bps[index]) / 10_000.0,
        ):
            from .constraints import OptimizerInputError

            raise OptimizerInputError(
                f"CMA-Skew/Kurtosis fuer Bucket '{bucket}' "
                f"(skew={skew_bps[index] / 10_000.0:.3f}, "
                f"excess_kurt={excess_kurt_bps[index] / 10_000.0:.3f}) macht "
                "die Cornish-Fisher-Transformation nicht-monoton (keine "
                "gueltige Quantilfunktion mehr) -- Betrag der Schiefe "
                "reduzieren oder Exzess-Kurtosis erhoehen."
            )

    # Korrelations-Matrix
    try:
        correlation = parse_correlation_matrix_json(
            getattr(cma, "correlation_matrix_json", None),
            default_matrix=build_default_correlation_matrix(),
            dimension=N_BUCKETS,
        )
        assert correlation is not None
        cholesky = _safe_cholesky(np.asarray(correlation, dtype=np.float64))
    except CMAValidationError as exc:
        from .constraints import OptimizerInputError

        raise OptimizerInputError(f"Invalid CMA model input: {exc}") from exc

    return ScenarioInputs(
        mu_bps=mu_bps,
        sigma_bps=sigma_bps,
        skew_bps=skew_bps,
        excess_kurt_bps=excess_kurt_bps,
        cholesky=cholesky,
        skew_state=skew_state,
        excess_kurt_state=excess_kurt_state,
    )


def _avg_or_zero(values: list) -> float:
    """Mittelwert der nicht-None-Werte; 0 wenn alle None."""
    valid = [int(v) for v in values if v is not None]
    if not valid:
        return 0.0
    return float(sum(valid) / len(valid))


# Sprint 6 Phase 2: Default-Maturity fuer Bonds-Bucket-Return-Aggregation.
# 5 Jahre = mittlere Duration eines IG-Bond-Universums (typisch 4-7).
# Berater kann via separates Mandate-Feld spaeter ueberschreiben.
_BONDS_DEFAULT_MATURITY_YEARS = NELSON_SIEGEL_DEFAULT_MATURITY_YEARS


def _compute_return_from_risk_premium(cma, premium_field_name: str) -> float | None:
    """Sprint 8: Risk-Asset-Return = NS.short_rate + premium.

    Returns None wenn:
    - premium-Feld nicht gesetzt im CMA
    - NS-Curve nicht aktiv (kein risk_free-Anker)
    Caller faellt dann auf fixe Werte zurueck (Backwards-Compat).

    Bei Aktivierung: nutzt NelsonSiegelCurve.short_rate_bps() (= y(0+) =
    beta0 + beta1) als risk_free Anker und addiert das Premium.
    """
    premium = getattr(cma, premium_field_name, None)
    if premium is None:
        return None
    # The risk-free anchor exists only when the *complete* NS group is active.
    # Beta0+Beta1 alone is a partial/inactive group and must not activate a
    # model that Bonds themselves are not using.
    ns_parameters = validate_nelson_siegel_parameters(cma)
    if ns_parameters is None:
        return None
    beta0, beta1, _, _ = ns_parameters
    if isinstance(premium, bool):
        raise CMAValidationError(f"{premium_field_name} muss eine Zahl sein.")
    try:
        premium_bps = float(premium)
        if not np.isfinite(premium_bps):
            raise CMAValidationError(
                f"{premium_field_name} muss endlich (finite) sein."
            )
        from services.risk_premium.model import RiskPremiumModel
        # Short-Rate = beta0 + beta1 (kein Curvature-Effekt am Short-End)
        risk_free_bps = beta0 + beta1
        model = RiskPremiumModel(
            asset_class=premium_field_name,
            premium_bps=premium_bps,
        )
        result = float(model.expected_return_bps(risk_free_bps))
    except CMAValidationError:
        raise
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CMAValidationError(
            f"Ungueltige {premium_field_name}-CMA-Parameter: {exc}"
        ) from exc
    if not np.isfinite(result) or result <= -10_000.0:
        raise CMAValidationError(
            f"{premium_field_name} erzeugt keinen endlichen, fachlich "
            "gueltigen Return (> -100 %)."
        )
    return result


# Sprint 7: Default-Horizont fuer KGV-Mean-Reversion-Adjustment.
# 10 Jahre ist sinnvoller Planungshorizont. Berater kann via separate
# scenario_inputs_from_cma-Wrapper-Funktion overriden (TODO Phase 3).
_KGV_DEFAULT_HORIZON_YEARS = 10


def _compute_equity_kgv_adjustment(cma) -> float:
    """Sprint 7: Equity-Return-Adjustment aus KGV-Mean-Reversion in bps.

    Returns 0.0 wenn CMA NICHT alle 3 KGV-Params hat (Backwards-Compat).
    Bei vollstaendigen Params: berechnet KGVMeanReversionModel-Adjustment
    fuer Default-Horizont 10J.
    """
    parameters = validate_equity_kgv_parameters(cma)
    if parameters is None:
        return 0.0
    kgv_current, kgv_fair, alpha = parameters
    try:
        from services.equity_valuation.mean_reversion import KGVMeanReversionModel
        model = KGVMeanReversionModel(
            kgv_current=kgv_current,
            kgv_fair=kgv_fair,
            alpha=alpha,
        )
        adjustment = model.expected_annual_return_adjustment_bps(
            _KGV_DEFAULT_HORIZON_YEARS
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CMAValidationError(
            f"Ungueltige vollstaendige KGV-CMA-Parameter: {exc}"
        ) from exc
    if not np.isfinite(adjustment):
        raise CMAValidationError(
            "KGV-CMA-Parameter erzeugen kein endliches Return-Adjustment."
        )
    return float(adjustment)


def _compute_bonds_return_from_nelson_siegel(
    cma, *, maturity_years: float | None = None
) -> float | None:
    """Kurvenwert (Niveau) an einer Laufzeit. KEIN Bond-Return.

    Returns None wenn CMA NICHT alle 4 NS-Params hat.

    NS-BOND-SLEEVE-COLLAPSE-001: diese Funktion hiess einmal "Bond-Return aus
    Nelson-Siegel" und ihr Ergebnis wurde dem Obligationen-Bucket direkt
    zugewiesen. Das war falsch. Die Kurve ist eine Swap-/Staatskurve OHNE
    Kreditaufschlag (die hinterlegte CHF-Kalibrierung: 50 bps bei 5 Jahren),
    die CMA-Bond-Returns sind Basis-plus-Spread (CHF IG 180, Global Hedged
    220, High Yield 420 bps). Die Zuweisung vernichtete also den gesamten
    Kreditaufschlag und kollabierte zusaetzlich alle Sleeves auf einen Wert.

    Das Niveau der Kurve gehoert deshalb NICHT in den Bond-Return. Was dort
    hingehoert, ist die Differenz zweier Kurvenpunkte -- siehe
    ``_compute_bonds_duration_tilt_bps()``. Diese Funktion bleibt als reine
    Kurvenabfrage erhalten (Kalibrierungs-Diagnostik, Methodik-Audit,
    strikter Runtime-Contract) und wird vom Return-Pfad nicht mehr benutzt.
    """
    parameters = validate_nelson_siegel_parameters(cma)
    if parameters is None:
        return None
    beta0, beta1, beta2, lambda_ = parameters
    maturity = (
        _BONDS_DEFAULT_MATURITY_YEARS if maturity_years is None else float(maturity_years)
    )
    if not np.isfinite(maturity) or maturity <= 0.0:
        raise CMAValidationError(
            f"Nelson-Siegel-Laufzeit muss positiv und endlich sein, erhalten: {maturity_years!r}."
        )
    try:
        from services.rates.nelson_siegel import NelsonSiegelCurve
        curve = NelsonSiegelCurve(
            beta0_bps=beta0,
            beta1_bps=beta1,
            beta2_bps=beta2,
            lambda_=lambda_,
        )
        result = float(curve.yield_at(maturity))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CMAValidationError(
            f"Ungueltige vollstaendige Nelson-Siegel-CMA-Parameter: {exc}"
        ) from exc
    if not np.isfinite(result) or result <= -10_000.0:
        raise CMAValidationError(
            "Nelson-Siegel-CMA-Parameter erzeugen keinen endlichen, "
            f"fachlich gueltigen {maturity:g}J-Yield (> -100 %)."
        )
    return result


def _compute_bonds_duration_tilt_bps(
    cma, *, maturity_years: float | None = None
) -> float | None:
    """Termstruktur-Tilt in bps: ``y(laufzeit) - y(referenz)``.

    Das ist der einzige Beitrag, den die NS-Kurve zum Obligationen-Return
    leisten darf (Begruendung in services/rates/bond_duration.py). Additiv auf
    den sleeve-gewichteten CMA-Return angewendet bleiben Kreditaufschlag UND
    Sleeve-Differenzierung vollstaendig erhalten -- der Tilt ist fuer alle
    Sleeves derselbe Betrag.

    Returns None wenn die NS-Gruppe nicht vollstaendig ist (Caller laesst den
    CMA-Return dann unangetastet). Liefert **exakt 0.0**, wenn die Laufzeit
    der Referenzlaufzeit entspricht -- also fuer jedes Mandat ohne
    Laufzeitpraeferenz.
    """
    from services.rates.bond_duration import CMA_REFERENCE_MATURITY_YEARS

    target = _compute_bonds_return_from_nelson_siegel(
        cma, maturity_years=maturity_years
    )
    if target is None:
        return None
    reference = _compute_bonds_return_from_nelson_siegel(
        cma, maturity_years=CMA_REFERENCE_MATURITY_YEARS
    )
    if reference is None:  # pragma: no cover - dieselbe NS-Gruppe wie oben
        return None
    tilt = float(target) - float(reference)
    if not np.isfinite(tilt):
        raise CMAValidationError(
            "Nelson-Siegel-Termstruktur-Tilt ist nicht endlich."
        )
    return tilt
