"""SAA-RESAMPLED-STABILITY-001 (2026-10-14): Resampled Efficiency fuer den
stochastischen SAA-Optimierer.

Befund (Fundament-Beispielmandat, identische Inputs, nur der Monte-Carlo-Seed
variiert, alle Laeufe ``converged``):

* 2'000 Pfade (Produktion): Aktien 63.2-75.0 % (Sigma 5.4 pp), Immobilien
  5.0-20.0 % (Sigma 6.6 pp); 10 Seeds -> 7 verschiedene SAAs.
* 8'000 Pfade: Sigma 3.7 / 4.2 pp; 6 von 8 Seeds auf einer Eckloesung.

Die Zielfunktion ist auf diesem Mandat flach und -- wegen der
Chance-Constraint-Indikatoren -- stueckweise konstant. Das Argmin eines
einzelnen Monte-Carlo-Wuerfels ist deshalb zum grossen Teil Stichproben-
rauschen: mehr Pfade helfen nur langsam (Sigma ~ n^-0.27), weil der Solver
zwischen nahezu gleichwertigen Ecken springt.

Methode (Michaud-artiges Bagging mit Common Random Numbers):

1. Aus dem INHALTS-Seed des Laufs (nie aus Datenbank-IDs, siehe
   ``solver.optimizer_content_seed``) werden ``n_bags`` Teil-Seeds abgeleitet.
2. Je Teil-Seed wird ein unabhaengiger Szenario-Wuerfel mit
   ``bag_n_paths`` Pfaden gezogen (identische Verteilung, identische
   Importance-Sampling-Entscheidung wie der Hauptwuerfel) und der
   UNVERAENDERTE bestehende Solver (Multi-Start-SLSQP + DE-Fallback +
   Stage-9-Robustifizierung) darauf gefahren.
3. Die optimalen Gewichte werden gemittelt. Der zulaessige Bereich (Bandbreiten,
   Risikobudget, Reserve-Untergrenze, Illiquiditaets-Caps, Summe = 1) ist
   konvex -- der Mittelwert zulaessiger Punkte ist selbst zulaessig. Die
   Projektion darauf ist deshalb im Normalfall die Identitaet und nur eine
   Absicherung gegen numerische Randfaelle.
4. Die Streuung je Bucket ueber die Bags (Standardabweichung in bps) wird als
   Stabilitaetskennzahl ausgewiesen.
5. Signifikanztest gegen die Hausmatrix: auf dem UNABHAENGIGEN
   Validierungswuerfel wird die Zielfunktion der resampelten Allokation mit
   der (auf Zulaessigkeit projizierten) Hausmatrix-Zielquote GEPAART
   verglichen. Ist die Verbesserung nicht signifikant, bleibt die
   Hausmatrix-Zielquote stehen.

Wahl des Tests: Die Zielfunktion ist KEIN Mittelwert pfadweiser Verluste --
die Chance-Constraint-Strafe ist eine quadratische Funktion der
Wilson-Untergrenze einer Erfolgsquote. Ein gepaarter t-Test auf
pfadweisen Verlustdifferenzen ist daher nicht definiert. Verwendet wird ein
gepaarter Bootstrap: dieselben gezogenen Pfadindizes werden fuer beide
Allokationen verwendet, die Zielfunktion auf jeder Replikation vollstaendig
neu ausgewertet. Einseitig, alpha = 5 %: signifikant genau dann, wenn die
Punktschaetzung der Verbesserung positiv ist UND das untere 5-%-Perzentil
der Bootstrap-Verteilung der Verbesserung > 0 liegt.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .importance_sampling import IS_TOTAL_SHIFT_SIGMA, ess_requires_fallback
from .scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    build_scenario_paths_with_weights,
)

RESAMPLING_SCHEME_VERSION = "michaud_bagging_crn_v1"
# v2 (SAA-SIGNIFICANCE-LEXICOGRAPHIC-001, 2026-10-17): lexikographischer
# Vergleich der zwei Zielfunktions-Stufen statt Differenz der Skalar-
# Zielfunktion; Entscheid ueber den Vorzeichen-Anteil (p-Wert), siehe
# ``lexicographic_improvement`` und ``paired_bootstrap_improvement``.
# v3 (OBJECTIVE-NORMALIZATION-001, 2026-10-18): der Solver minimiert jetzt
# eine STETIGE, Pareto-monotone Skalar-Zielfunktion (Tiebreak immer aktiv,
# kein Stufen-Schalter). Der Produktionstest vergleicht deshalb wieder die
# Skalar-Zielfunktion -- dieselbe Ordnung, nach der optimiert wurde; die
# Differenz hat eine Einheit, die untere Konfidenzgrenze ist wieder
# definiert. ``lexicographic_improvement`` bleibt fuer Aufrufer, die
# ausdruecklich die Zwei-Stufen-Logik vergleichen wollen.
SIGNIFICANCE_TEST_VERSION = "paired_bootstrap_one_sided_scalar_v3"
# Nulltoleranz der Zwei-Stufen-Logik in ``lexicographic_improvement`` (war
# bis v2 identisch mit dem inzwischen entfernten Stufe-2-Schalter des
# Solvers).
GOAL_LEVEL_EPSILON = 1e-12
COMPARISON_GOAL_LEVEL = "goal_level"
COMPARISON_TIEBREAK = "volatility_tiebreak"
COMPARISON_SCALAR = "scalar"

# Parameterwahl siehe docs/planning/2026-10-14-saa-stability-resampling.md.
# Gemessen auf dem Fundament-Beispielmandat (10 Seed-Salze): die Streuung
# EINES Bags (500 Pfade) liegt bei ~4-5 pp je Bucket (Aktien/Immobilien), die
# des Bag-Mittels faellt mit 1/sqrt(n_bags): 40 Bags -> gemessen 0.76 pp
# (Aktien) / 0.77 pp (Immobilien), also unter dem 1-pp-Ziel. Zu kleine Bags
# verschieben das Optimum systematisch (die Wilson-Untergrenze der
# Chance-Constraints haengt von n ab); 500 Pfade je Bag halten die gesamte
# Generierung bei ~2.4x der bisherigen Laufzeit (Budget: <= 3x).
DEFAULT_N_BAGS = 40
DEFAULT_BAG_N_PATHS = 500
# Weniger als die Haelfte erfolgreicher Bags ist kein belastbarer Mittelwert:
# dann gilt der Lauf als nicht konvergiert (kontrollierter House-Fallback).
MIN_SUCCESSFUL_BAG_SHARE = 0.5
DEFAULT_SIGNIFICANCE_ALPHA = 0.05
DEFAULT_N_BOOTSTRAP = 400

BAG_SEED_DOMAIN = "saa-resampling-bag-v1"
BOOTSTRAP_SEED_DOMAIN = "saa-significance-bootstrap-v1"


@dataclass(frozen=True)
class ResamplingConfig:
    """Parameter des Resamplings. ``n_bags <= 1`` schaltet es ab (Altpfad:
    ein einzelner Wuerfel, nur noch fuer gezielte Vergleichsmessungen)."""

    n_bags: int = DEFAULT_N_BAGS
    bag_n_paths: int = DEFAULT_BAG_N_PATHS
    significance_alpha: float = DEFAULT_SIGNIFICANCE_ALPHA
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP
    significance_test: bool = True

    @property
    def enabled(self) -> bool:
        return int(self.n_bags) > 1


DEFAULT_RESAMPLING = ResamplingConfig()
SINGLE_CUBE = ResamplingConfig(n_bags=1, significance_test=False)


def _domain_seed(domain: str, *parts) -> int:
    hasher = hashlib.sha256()
    hasher.update(domain.encode("utf-8"))
    for part in parts:
        hasher.update(b"\x00")
        hasher.update(str(part).encode("utf-8"))
    return int.from_bytes(hasher.digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


def bag_seeds(content_seed: int, n_bags: int) -> list[int]:
    """Teil-Seeds der Bags, ausschliesslich aus dem Inhalts-Seed abgeleitet.

    Common Random Numbers: zwei Laeufe mit gleichem Inhalts-Seed (z.B.
    Baseline und Variante der Goal-Sensitivity, die denselben gepinnten Seed
    teilen) sehen exakt dieselben Bag-Wuerfel.
    """
    return [
        _domain_seed(BAG_SEED_DOMAIN, int(content_seed), index)
        for index in range(int(n_bags))
    ]


def bootstrap_seed(validation_seed: int) -> int:
    return _domain_seed(BOOTSTRAP_SEED_DOMAIN, int(validation_seed))


def build_bag_paths(
    inputs: ScenarioInputs,
    *,
    scenario_horizon_years: int,
    horizon_years: int,
    n_paths: int,
    seed: int,
    importance_sampling: bool,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Zieht einen Bag-Wuerfel mit derselben Verteilung wie der Hauptwuerfel.

    Bewusst ungecacht: 40 Bags je Lauf wuerden den 16er-LRU-Cache des
    Hauptwuerfels nur verdraengen, ohne je wieder getroffen zu werden.
    Gezogen wird -- wie im Hauptwuerfel -- auf dem gemeinsamen
    Szenario-Horizont und danach auf den Optimierungshorizont gekuerzt.
    """
    if importance_sampling:
        # IMPORTANCE-SAMPLING-ESS-001: dieselbe Proposal wie der Hauptwuerfel
        # (defensive Mischung, horizont-skalierter Shift), Gewichte auf dem
        # tatsaechlich verwendeten Jahres-Praefix.
        paths, weights = build_scenario_paths_with_weights(
            inputs,
            horizon_years=int(scenario_horizon_years),
            n_paths=int(n_paths),
            seed=int(seed),
            antithetic=True,
            use_importance_sampling=True,
            is_shift_strength=IS_TOTAL_SHIFT_SIGMA,
            weight_horizon_years=int(horizon_years),
        )
        if ess_requires_fallback(weights):
            # Dieselbe Regel wie im Hauptwuerfel: unter der ESS-Schwelle
            # rechnet dieser Bag mit Standard-MC.
            importance_sampling = False
    if not importance_sampling:
        paths = build_scenario_paths(
            inputs,
            horizon_years=int(scenario_horizon_years),
            n_paths=int(n_paths),
            seed=int(seed),
            antithetic=True,
        )
        weights = None
    return paths[:, : int(horizon_years), :], weights


def lexicographic_improvement(
    anchor,
    candidate,
    *,
    epsilon: float = GOAL_LEVEL_EPSILON,
) -> tuple[float, str]:
    """Verbesserung ``anker - kandidat`` in der Logik der Zwei-Stufen-Zielfunktion.

    Argumente sind entweder Skalare (Altvertrag: Differenz der Skalar-
    Zielfunktion, Ebene ``scalar``) oder ``(goal_level, tiebreak[, additiv])``
    aus ``objective.two_phase_objective_parts`` (plus optional der
    Soft-Preference-Strafe, die wie im Solver auf jeder Ebene mitzaehlt).

    SAA-SIGNIFICANCE-LEXICOGRAPHIC-001 (2026-10-17): Die Skalar-Zielfunktion
    schaltet den Volatilitaetsterm PRO ALLOKATION zu, sobald deren Stufe 1
    (Ziel-Fehlbetrag + Chance-Penalty) unter ``epsilon`` faellt. Als
    Differenz zweier Allokationen ist sie damit nicht monoton: gemessen auf
    dem CH-Golden-Mandat (Score 7) hatte die Hausmatrix-Zielquote auf EINEM
    von 2'000 Validierungspfaden einen winzigen Fehlbetrag (Stufe 1 = 8.1e-9,
    kein Volatilitaetsterm), der Kandidat erfuellte alle Ziele (Stufe 2,
    Volatilitaetsterm 1.42e4) -- "Verbesserung" -14'204, Hausmatrix gewaehlt,
    obwohl der Kandidat auf BEIDEN Stufen besser war. Ob dieser eine Pfad im
    Wuerfel lag, entschied je nach Inhalts-Seed zwischen 60 % und 68 % Aktien.

    Regel (dieselbe Prioritaet wie der Solver):
    * Erfuellen BEIDE Stufe 1 (``goal_level < epsilon``), entscheidet der
      Volatilitaetsterm (Ebene ``volatility_tiebreak``).
    * Sonst entscheidet allein Stufe 1 (Ebene ``goal_level``); der
      Volatilitaetsterm zaehlt fuer keine der beiden Allokationen.
    """
    if isinstance(anchor, (tuple, list)) != isinstance(candidate, (tuple, list)):
        raise TypeError("Anker und Kandidat muessen dieselbe Verlustform haben.")
    if not isinstance(anchor, (tuple, list)):
        return float(anchor) - float(candidate), COMPARISON_SCALAR
    anchor_goal, anchor_tiebreak, anchor_extra = _loss_parts(anchor)
    candidate_goal, candidate_tiebreak, candidate_extra = _loss_parts(candidate)
    if anchor_goal < float(epsilon) and candidate_goal < float(epsilon):
        return (
            (anchor_goal + anchor_tiebreak + anchor_extra)
            - (candidate_goal + candidate_tiebreak + candidate_extra),
            COMPARISON_TIEBREAK,
        )
    return (
        (anchor_goal + anchor_extra) - (candidate_goal + candidate_extra),
        COMPARISON_GOAL_LEVEL,
    )


def _loss_parts(loss) -> tuple[float, float, float]:
    """``(goal_level, tiebreak[, additiv])`` -> drei Floats.

    Der optionale dritte Term (Soft-Preference-Strafe) liegt im Solver
    ausserhalb des Stufen-Schalters und wird deshalb auf JEDER Ebene addiert,
    entscheidet aber nicht ueber den Wechsel in Stufe 2.
    """
    goal_level, tiebreak = float(loss[0]), float(loss[1])
    extra = float(loss[2]) if len(loss) > 2 else 0.0
    return goal_level, tiebreak, extra


def paired_bootstrap_improvement(
    loss_pair: Callable[[np.ndarray | None], tuple],
    *,
    n_paths: int,
    n_bootstrap: int,
    alpha: float,
    seed: int,
) -> dict:
    """Gepaarter, einseitiger Bootstrap der Verbesserung ``L(anker) - L(kandidat)``.

    ``loss_pair(idx)`` liefert ``(L_anker, L_kandidat)`` auf der Pfadauswahl
    ``idx`` (None = alle Pfade). Beide Verluste werden auf DENSELBEN Indizes
    ausgewertet -- das ist die Paarung; sie entfernt die gemeinsame
    Szenariostreuung aus der Differenz.

    p-Wert: Anteil der Replikationen ohne Verbesserung, mit der ueblichen
    (1 + k) / (1 + B)-Korrektur, damit nie p = 0 ausgewiesen wird.

    ``loss_pair`` darf Skalare oder ``(goal_level, tiebreak)``-Paare liefern;
    die Verbesserung je Replikation bildet ``lexicographic_improvement``.

    Entscheid (SAA-SIGNIFICANCE-LEXICOGRAPHIC-001): signifikant genau dann,
    wenn die Punktschaetzung positiv ist UND ``p <= alpha``. Der Entscheid
    haengt damit nur an Vorzeichen, nie an Betraegen -- noetig, weil
    Replikationen auf verschiedenen Ebenen verglichen werden koennen (Stufe 1
    in der einen, Volatilitaets-Tiebreak in der anderen) und ein Quantil
    ueber Werte verschiedener Einheit interpolieren wuerde. Die untere
    Konfidenzgrenze wird nur noch ausgewiesen, und nur wenn alle
    Replikationen auf derselben Ebene verglichen wurden.
    """
    anchor_full, candidate_full = loss_pair(None)
    improvement, comparison = lexicographic_improvement(anchor_full, candidate_full)
    rng = np.random.default_rng(int(seed))
    replicates = np.empty(int(n_bootstrap), dtype=np.float64)
    levels: dict[str, int] = {}
    for b in range(int(n_bootstrap)):
        idx = rng.integers(0, int(n_paths), size=int(n_paths))
        anchor_b, candidate_b = loss_pair(idx)
        replicates[b], level = lexicographic_improvement(anchor_b, candidate_b)
        levels[level] = levels.get(level, 0) + 1
    finite = replicates[np.isfinite(replicates)]
    block = {
        "test": SIGNIFICANCE_TEST_VERSION,
        "n_bootstrap": int(n_bootstrap),
        "alpha": float(alpha),
        "anchor_objective": _objective_scalar(anchor_full),
        "candidate_objective": _objective_scalar(candidate_full),
        "comparison": comparison,
        "replicate_comparisons": dict(sorted(levels.items())),
        "improvement": float(improvement),
    }
    if finite.size == 0 or not np.isfinite(improvement):
        return {
            **block,
            "improvement_lower_bound": None,
            "p_value": None,
            "significant": False,
        }
    no_improvement = int(np.count_nonzero(finite <= 0.0))
    p_value = (1.0 + no_improvement) / (1.0 + float(finite.size))
    lower = float(np.quantile(finite, float(alpha))) if len(levels) == 1 else None
    return {
        **block,
        "improvement_lower_bound": lower,
        "p_value": float(p_value),
        "significant": bool(improvement > 0.0 and p_value <= float(alpha)),
    }


def _objective_scalar(loss) -> float:
    """Skalar-Zielfunktion fuer den Audit (wie ``combined_objective_two_phase``)."""
    if not isinstance(loss, (tuple, list)):
        return float(loss)
    goal_level, tiebreak, extra = _loss_parts(loss)
    if goal_level < GOAL_LEVEL_EPSILON:
        return goal_level + tiebreak + extra
    return goal_level + extra


# Felder des Resampling-Audits, die in die Modellbasis (und damit in
# effective_constraints_json / allocation_context_hash) eingehen. Bewusst
# NICHT: Laufzeiten (nicht deterministisch) und die Einzel-Bags (Umfang;
# die Streuung je Bucket ist die verdichtete Kennzahl daraus).
_MODEL_BASIS_FIELDS = (
    "scheme",
    "seed_scheme",
    "engine_version",
    "content_seed",
    "n_bags",
    "n_bags_succeeded",
    "n_bags_robustified",
    "n_bags_de_fallback",
    "bag_n_paths",
    "mean_weights_bps",
    "dispersion_bps",
    "standard_error_bps",
    "projection_distance_bps",
    "resampled_weights_bps",
    "final_weights_bps",
    "decision",
)
_SIGNIFICANCE_BASIS_FIELDS = (
    "test",
    "alpha",
    "n_bootstrap",
    "house_anchor_bps",
    "house_anchor_projected_bps",
    "candidate_bps",
    "anchor_objective",
    "candidate_objective",
    "improvement",
    "improvement_lower_bound",
    "comparison",
    "replicate_comparisons",
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001: nur im Modus max_drawdown gesetzt
    # ("refined_brownian_bridge"); sonst fehlt der Schluessel und die
    # Modellbasis bleibt bit-gleich.
    "drawdown_measure",
    "p_value",
    "significant",
    "validation_seed",
    "validation_cube_hash",
    "validation_n_paths",
    "decision",
    "reason",
)


def resampling_model_basis(resampling: dict | None) -> dict | None:
    """Deterministische Verdichtung des Resampling-Audits fuer die Modellbasis."""
    if not isinstance(resampling, dict) or not resampling.get("enabled"):
        return None
    basis = {
        key: resampling[key] for key in _MODEL_BASIS_FIELDS if key in resampling
    }
    significance = resampling.get("significance")
    if isinstance(significance, dict):
        basis["significance"] = {
            key: significance[key]
            for key in _SIGNIFICANCE_BASIS_FIELDS
            if key in significance
        }
    return basis
