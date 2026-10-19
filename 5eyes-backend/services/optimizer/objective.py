"""Objective Functions + Goal-Drivers (V3 Sprint 1d).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 6)

All Rappen shortfalls entering the optimizer objective are divided by the
single context scale ``max(1, initial_wealth_rappen)`` before squaring. This
makes the primary term dimensionless while retaining absolute goal priority.

Primary Objective (Advisory-Methodik Slide 18, Priorität 1):
    L(w) = Σ_g h_g · w_g · (1/N) · Σ_n max(0, target_g - wealth_g(w, n))^2

Sekundaer (Priorität 2, als stetiger Tiebreak, OBJECTIVE-NORMALIZATION-001):
    kappa · w' Sigma w   (einjaehrige Portfolio-Varianz aus der CMA-Kovarianz, immer aktiv)

Chance-Constraint (Ziel-Untergrenze, jeder Modus):
    Σ_g max(0, tau_g - LB_g) · (Zielvolumen_g / W0)^2

Hardness-Weights (OWNER-DECISION OD-1, vom User bestaetigt):
    hart: 10.0    primaer: 1.0    opportunistisch: 0.2
Seit GOAL-HARDNESS-DEFAULT-001 (Engine ``saa_resampled_v7``) standardmaessig
aktiv (auf den Fehlbetrag; die weiche Chance-Strafe bleibt ungewichtet) und
zusaetzlich als Zielhierarchie: harte und primaere Ziele sind Stufe 1
(GOAL-HIERARCHY-001, ``protected_goal_level``).
``OPTIMIZER_GOAL_WEIGHTING=equal`` ist der Opt-out der Gewichte.

Pro Goal-Typ wird Shortfall anders berechnet:
- "wealth_at_t":      max(0, target - wealth[t])^2
- "cashflow_in_year": max(0, -wealth[t])^2 (Outflow ist bereits abgezogen)
- "outflow_stream":   max(0, -min_t wealth[t])^2 (jeder Outflow muss finanzierbar sein)
- "return_rate":      max(0, target_bps - annualized_return_bps)^2
- "maximize":         kein Fehlbetrag; Wachstumsterm
                      -lambda_M * T * E[log(1 + r_TWR)] (MAXIMIZE-GOAL-001)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

import numpy as np

from config import validate_goal_weighting_mode

from .certification import (
    effective_sample_size,
    ess_is_sufficient,
    reliability_verdict,
    wilson_lower_bound,
)
from .goal_liabilities import GoalLiability


# OBJECTIVE-NORMALIZATION-001 (2026-10-18): Gewicht der Chance-Constraint-
# Strafe. Vorher ``1e6`` auf das QUADRAT des Wahrscheinlichkeitsdefizits --
# einheitenfremd zu allen anderen Termen (Primaerterm, Risikomass-Varianten
# und Tiebreak liegen in [1e-9, 10]); gemessen auf dem Fundament-Mandat
# 1.1e6 gegen einen Drawdown-Term von 0.26: die Variante "Max-Drawdown"
# lieferte dort MEHR Aktien als der Default, weil allein die Strafe zaehlte.
#
# Jetzt (siehe ``chance_constraint_penalty``): Defizit LINEAR (exakte
# Strafe, kein Quadrat, das kleine Defizite verschwinden laesst) mal
# ``(Zielvolumen / Kontext-Skala)^2`` -- derselbe dimensionslose Massstab wie
# der Primaerterm. Gewicht 1.0 ist keine Kalibrierung, sondern die natuerliche
# Einheit: ein Defizit von Delta kostet genau so viel wie ein VOLLSTAENDIGER
# Ausfall des Ziels auf dem Pfad-Anteil Delta (die Obergrenze dessen, was
# dieses Defizit im Primaerterm anrichten kann).
CHANCE_PENALTY_WEIGHT = 1.0
# Rueckwaertskompatibler Name (Tests/Aufrufer); Semantik siehe oben.
LAMBDA_CHANCE_DEFAULT = CHANCE_PENALTY_WEIGHT
# Gewicht des IMMER aktiven Volatilitaets-Tiebreaks (OBJECTIVE-NORMALIZATION-001:
# stetig, kein Stufen-Schalter).
#
# TIEBREAK-PORTFOLIO-VARIANCE-001 (CIO-Entscheid 2026-10-18): das Mass ist
# die EINJAEHRIGE Portfolio-Varianz ``w' Sigma w`` aus der CMA-Kovarianz des
# Laufs (Dezimal^2), nicht mehr ``Var(W_T) / W0^2``. Das alte Mass war
# mittelwertabhaengig (eine hoehere erwartete Rendite vergroessert ueber 31
# Jahre auch die Endvermoegens-Streuung; Score 7/9: analytische Vola +3..6
# bps durch den "Varianz"-Tiebreak) und wurde auf dem IS-Wuerfel mit ~10
# effektiven Pfaden geschaetzt. ``w' Sigma w`` ist exakt, glatt, pfadfrei und
# dieselbe Groesse wie die ausgewiesene erwartete Volatilitaet.
#
# Kalibrierung (40 Bags je Mandat, 7 Mandate; Doku
# docs/planning/2026-10-18-importance-sampling-ess.md, Abschnitt 4):
# siehe dort -- kleinster Wert, bei dem der Solver auf allen Mandaten den
# Startpunkt verlaesst, mit mindestens einer Dekade Abstand zur ersten
# messbaren Ziel-Erosion auf dem Konfliktmandat.
TIEBREAK_VARIANCE_WEIGHT = 1.0
TAU_UNREACHABLE = 0.50

# OWNER-DECISION OD-1 (bestaetigt 2026-05-05): 50x zwischen hart/opportunistisch.
# Im Optimizer brauchen wir staerkere Hardness-Trennung als in der reinen Score-
# Aggregation (_GOAL_HARDNESS_MULTIPLIER_BPS in portfolio_engine, Faktor 5x).
HARDNESS_WEIGHT = {
    "hart": 10.0,
    "primaer": 1.0,
    "opportunistisch": 0.2,
}

_PRIMARY_HARDNESS_KEYS = {"hart", "primaer", "primär"}

# GOAL-HARDNESS-DEFAULT-001 (CIO-Entscheid 2026-10-18, Engine
# ``saa_resampled_v7``): der Haertegrad wirkt standardmaessig (Default
# ``OPTIMIZER_GOAL_WEIGHTING=hardness``, config.DEFAULT_GOAL_WEIGHTING_MODE):
# (1) HARDNESS_WEIGHT (OD-1) skaliert den Ziel-Fehlbetrag, (2) harte und
# primaere Ziele bilden die geschuetzte Stufe 1 der Zielhierarchie
# (GOAL-HIERARCHY-001), deren Erosionstoleranz durch h_g geteilt wird.
# Im Default "equal" bis v6 war "hart" rechnerisch identisch mit "primaer".
# Herleitung und Kalibrierungsbezug (primaer = 1 = Referenz der
# kappa_H-Kalibrierung):
# docs/planning/2026-10-18-maximize-goal-and-hardness.md.
GOAL_HARDNESS_POLICY_VERSION = "hardness_scales_shortfall_and_protection_v1"

# MAXIMIZE-GOAL-001 (CIO-Entscheid 2026-10-18, Engine ``saa_resampled_v7``):
# Ziel "Maximierung" als Wachstumsterm in G statt Fehlbetrag 0:
#
#     M_g(w) = -lambda_M * h_g * g_g * T * E_n[ log(1 + r_n(w)) ]
#
# r_n = cashflow-neutrale annualisierte Portfolio-Rendite (TWR) auf Pfad n,
# T = Bewertungshorizont des Ziels -- also -lambda_M * E[log(R_T/1)], der
# erwartete Log-Endvermoegensfaktor (Kelly/Breiman: maximiert Median- und
# Langfrist-Wachstum, risikoavers durch die Jensen-Luecke ~ -sigma^2/2,
# skalenfrei in W0 und Waehrung). lambda_M = 1.0 ist die natuerliche
# Einheit der uebrigen Zielterme (relatives Endvermoegen bei W_T = W0, d log W
# = dW / W0); keine Kalibrierungsgroesse. Der Haertegrad wird fuer
# Maximierung auf "primaer" gedeckelt (h <= 1): ein Ziel ohne Zielwert kann
# nicht "sicher erreicht" werden. Herleitung und Alternativen:
# docs/planning/2026-10-18-maximize-goal-and-hardness.md.
MAXIMIZE_GOAL_POLICY_VERSION = "maximize_log_growth_v1"
MAXIMIZE_GROWTH_WEIGHT = 1.0
# Untergrenze des Wachstumsfaktors je Pfad (Totalverlust), wie in
# ``solver._annualized_twr_bps_per_path`` (Faktoren >= 1e-12).
_MAXIMIZE_MIN_GROWTH_FACTOR = 1e-12

# GOAL-HIERARCHY-001 (CIO-Entscheid 2026-10-18, Engine ``saa_resampled_v7``,
# nach Codex-Review OBJECTIVE-TIEBREAK-NOT-LEXICOGRAPHIC-001 /
# GOAL-SCREEN-OBJECTIVE-ERASURE-001): harte und primaere Ziele bilden eine
# echte Stufe 1. Je Szenario-Wuerfel wird zuerst
#
#     G1* = min_w G1(w),  G1(w) = sum_{g hart/primaer} (h_g * g_g * L_g(w) + C_g(w))
#
# bestimmt (dieselben Terme wie in der Zielfunktion), danach die volle
# Zielfunktion (Stufe 2: opportunistische Ziele, Maximierung,
# Soft-Preference, Haus-Prior) NUR unter der Nebenbedingung
#
#     G1(w) <= G1* + eps,   eps = z * SE(G1(w_H) - G1(w1*)) / h_max + GOAL_EROSION_NUMERIC_TOL
#
# minimiert. ``SE`` ist der Monte-Carlo-Standardfehler des gepaarten
# Unterschieds der Zielebene zwischen Hausquote ``w_H`` und Stufe-1-Optimum
# ``w1*`` auf demselben Wuerfel (ohne Haus-Anker: Standardfehler von G1 in
# ``w1*``): eine Erosion innerhalb dieses Rauschens ist nicht als
# Verschlechterung belegbar und wird dem Haus-Prior ueberlassen; alles
# darueber kann er nicht "auskaufen". z = einseitiges 95-%-Quantil, dasselbe
# alpha = 5 % wie die Hausmatrix-Offenlegung. Ist ein HARTES Ziel unter den
# geschuetzten, wird die Toleranz durch sein Haertegrad-Gewicht geteilt
# (h_hart / h_primaer = 10, OD-1): primaer darf innerhalb des Rauschens
# erodieren, hart nur um ein Zehntel davon. Opportunistische Ziele sind
# nicht geschuetzt (Stufe 2). Herleitung:
# docs/planning/2026-10-18-maximize-goal-and-hardness.md.
GOAL_HIERARCHY_POLICY_VERSION = "protected_goals_lexicographic_v2_reachable_only"
GOAL_EROSION_Z = 1.6448536269514722
GOAL_EROSION_NUMERIC_TOL = 1e-9


def resolve_goal_weighting_mode() -> str:
    """Goal-Weighting-Modus des Laufs (``equal`` | ``hardness``).

    GOAL-HARDNESS-DEFAULT-001 (CIO-Entscheid 2026-10-18, Engine v7): Default
    ist ``hardness`` (config.DEFAULT_GOAL_WEIGHTING_MODE) -- hart 10x /
    primaer 1x / opportunistisch 0.2x auf den ganzen Zielbeitrag. Bis v6 war
    ``equal`` der Default (3eyes-Methodik "Alle Ziele sind gleich wichtig
    (Mittelung)", ADR-011 Entscheid 2); er bleibt als Opt-out
    OPTIMIZER_GOAL_WEIGHTING=equal erhalten. Die Gewichtung NACH WICHTIGKEIT
    bleibt beim Rang (weight_bps); der Haertegrad steuert, wie stark ein
    Ziel gegen die Hausmatrix-Abweichung durchgesetzt wird.

    CERT-OPTIMIZER-OBJECTIVE-001 / OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001: this
    used to normalize ANY unrecognized value (a typo, an empty string, ...)
    silently to "equal" -- indistinguishable from an unset variable, with no
    error and no evidence of the misconfiguration. It now delegates to the
    single centrally validated definition in config.validate_goal_weighting_mode,
    which raises ValueError fail-closed for anything other than "equal" or
    "hardness" (unset -> documented default "equal"). This is the one call
    site this module uses to resolve the mode; every objective/driver
    function below calls this function (directly or via
    _effective_hardness_weight), never os.environ, so there is a single
    source of truth for "which mathematics produced this run".

    This is intentionally still a live env read rather than a value frozen
    once at process start: a config change must take effect on the very
    next optimizer run without requiring a process restart. The remaining
    architectural gap -- binding the resolved mode into one immutable
    per-run ObjectiveContract so solver/reevaluation/driver/sensitivity/
    replay are provably congruent even if the environment changes mid-run
    -- is tracked as further work (see certification spec Sec. 6.2-6.3);
    this fix closes the "silent fallback" and "not hashed" gaps, not that
    larger contract-freeze gap.
    """
    return validate_goal_weighting_mode(os.environ.get("OPTIMIZER_GOAL_WEIGHTING"))


def _goal_weighting_mode() -> str:
    """Backwards-compatible internal alias for resolve_goal_weighting_mode()."""
    return resolve_goal_weighting_mode()


def _effective_hardness_weight(
    hardness_key: str | None, goal_weighting_mode: str | None = None,
) -> float:
    """Haertegrad-Multiplikator im Modus ``hardness`` (Default ab v7), sonst 1.0.

    Im Opt-out ``equal`` mittelt der Optimizer alle Ziele gleich.

    OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: ``goal_weighting_mode`` ist der
    aus dem unveraenderlichen Lauf-Vertrag durchgereichte Modus. Ohne ihn las
    diese Funktion die Umgebung PRO ZIEL PRO AUSWERTUNG -- bei einem
    Umgebungswechsel mitten im Lauf wurden einzelne Ziele innerhalb derselben
    Summe verschieden gewichtet.

    ``None`` bleibt erlaubt und loest wie bisher live auf: ausserhalb des
    Solvers rufen Konsumenten die Objective-Funktionen ohne Lauf-Kontext auf
    (Reports, Analysen), und fuer die ist der aktuelle Modus die richtige
    Antwort. Der Solver reicht den Vertrag IMMER durch; nur dort ist
    "derselbe Wert fuer den ganzen Lauf" eine Korrektheitsbedingung.
    """
    mode = (
        goal_weighting_mode
        if goal_weighting_mode is not None
        else _goal_weighting_mode()
    )
    if mode == "hardness":
        return HARDNESS_WEIGHT.get(_hardness_key(hardness_key), 1.0)
    return 1.0


def _goal_hardness_weight(
    liability: GoalLiability, goal_weighting_mode: str | None = None,
) -> float:
    """Haertegrad-Gewicht EINES Ziels (Fehlbetrag, Stufe 1 und 2).

    MAXIMIZE-GOAL-001: fuer ``maximize`` hoechstens 1.0 -- "hart" verlangt
    Zielsicherheit, und ein Ziel ohne Zielwert hat keine.
    """
    weight = _effective_hardness_weight(
        getattr(liability, "hardness_key", None), goal_weighting_mode,
    )
    if getattr(liability, "target_kind", None) == "maximize":
        return min(1.0, weight)
    return weight


def maximize_growth_per_path(
    liability: GoalLiability,
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> np.ndarray:
    """Log-Wachstumsfaktor ``T * log(1 + r_n)`` je Pfad fuer ein Maximierungsziel.

    MAXIMIZE-GOAL-001. ``r_n`` ist die cashflow-neutrale annualisierte
    Portfolio-Rendite des Solvers (TWR); ohne sie (Konsumenten ausserhalb
    eines Laufs) die annualisierte Rendite aus dem Vermoegenspfad bis T.
    """
    n_cols = wealth_paths.shape[1]
    horizon = max(1, min(
        int(liability.target_year_index or (n_cols - 1)), max(1, n_cols - 1),
    ))
    if annualized_return_bps_per_path is None:
        annualized = _annualized_return_bps_per_path(
            initial_wealth_rappen, wealth_paths[:, horizon], horizon,
        )
    else:
        annualized = np.asarray(
            annualized_return_bps_per_path, dtype=np.float64
        ).reshape(-1)
        if annualized.shape != (wealth_paths.shape[0],):
            raise ValueError(
                "annualized_return_bps_per_path must match n_paths "
                f"({annualized.shape} != {(wealth_paths.shape[0],)})"
            )
    factor = np.maximum(1.0 + annualized / 10000.0, _MAXIMIZE_MIN_GROWTH_FACTOR)
    return float(horizon) * np.log(factor)


def _hardness_key(value: str | None) -> str:
    raw = str(value or "primaer").strip().lower()
    if raw in ("hart", "hard"):
        return "hart"
    if raw in ("primaer", "primär", "primary"):
        return "primaer"
    if raw in ("opportunistisch", "opportunistic", "opp"):
        return "opportunistisch"
    return raw or "primaer"


def _display_hardness(value: str | None) -> str:
    key = _hardness_key(value)
    if key == "primaer":
        return "primär"
    return key


def _default_tau_x100(liability: GoalLiability) -> int:
    raw = getattr(liability, "success_probability_min_x100", None)
    if raw is not None:
        try:
            return max(0, min(10000, int(raw)))
        except (TypeError, ValueError):
            pass
    if liability.target_kind == "return_rate":
        return 5000
    if liability.target_kind == "maximize":
        return 10000
    return 8000


def _annualized_return_bps_per_path(
    initial_wealth_rappen: float,
    end_wealth_per_path: np.ndarray,
    horizon_years: int,
) -> np.ndarray:
    """Annualisierte Rendite pro Pfad in bps.

    Wenn end_wealth <= 0 (Lebensluecke): Rendite konstanter Wert von -10000bps
    (= -100% effektiv). Verhindert log-of-non-positive Errors und ist
    konsistent zu portfolio_engine._annualized_return_bps clamp.
    """
    horizon = max(1, int(horizon_years))
    initial = max(1.0, float(initial_wealth_rappen))
    ratio = end_wealth_per_path / initial
    safe_ratio = np.where(ratio > 0, ratio, 1e-12)
    annualized = np.power(safe_ratio, 1.0 / horizon) - 1.0
    annualized_bps = annualized * 10000.0
    # Clamp wenn Pfad negativ wurde
    annualized_bps = np.where(end_wealth_per_path > 0, annualized_bps, -10000.0)
    return annualized_bps


def _context_scale_rappen(value: float) -> float:
    """Return the finite, positive common normalization scale."""
    raw = float(value)
    if not np.isfinite(raw):
        raise ValueError("initial_wealth_rappen must be finite")
    return max(1.0, raw)


def _squared_rappen_shortfall(
    shortfall_rappen: np.ndarray,
    *,
    normalization_scale_rappen: float | None,
) -> np.ndarray:
    """Square a Rappen shortfall after optional context normalization.

    ``None`` intentionally preserves the historic raw-rappen helper contract
    for direct callers. The optimizer objective and explainability path always
    pass the common context scale ``max(1, initial_wealth_rappen)``.
    """
    scale = (
        1.0
        if normalization_scale_rappen is None
        else _context_scale_rappen(normalization_scale_rappen)
    )
    relative_shortfall = np.asarray(shortfall_rappen, dtype=np.float64) / scale
    return relative_shortfall * relative_shortfall


def _positive_due_wealth_indices(
    liability: GoalLiability,
    *,
    n_wealth_columns: int,
) -> np.ndarray:
    """Map this goal's positive liability entries to wealth-path columns.

    ``liability_path_rappen[0]`` is paid in year one and is observed in
    ``wealth_paths[:, 1]``. Unrelated negative wealth before or after this
    goal's payment window must not make this goal fail.

    The supplied wealth path is aggregate across all goals. Exact causal
    attribution between simultaneous liabilities would require per-goal
    counterfactual wealth paths; this helper intentionally does not invent an
    ordering or allocation rule from the aggregate series.
    """
    return _positive_due_wealth_indices_cached(
        tuple(liability.liability_path_rappen or ()),
        int(n_wealth_columns),
    )


@lru_cache(maxsize=256)
def _positive_due_wealth_indices_cached(
    liability_path_rappen: tuple,
    n_wealth_columns: int,
) -> np.ndarray:
    """Reine Funktion des Zahlungsplans (SAA-RESAMPLED-RUNTIME-001).

    Die Zielfunktion fragt dieselben Indizes je Auswertung mehrfach ab (der
    Solver wertet zehntausendfach aus); der Plan aendert sich dabei nie.
    Das gecachte Array ist schreibgeschuetzt, damit kein Aufrufer den
    geteilten Cache-Eintrag veraendern kann.
    """
    indices = [
        path_index + 1
        for path_index, amount in enumerate(liability_path_rappen)
        if float(amount or 0) > 0.0 and path_index + 1 < int(n_wealth_columns)
    ]
    result = np.asarray(indices, dtype=np.intp)
    result.setflags(write=False)
    return result


def scheduled_outside_wealth_horizon(
    liability: GoalLiability,
    *,
    n_wealth_columns: int,
) -> bool:
    """Liegt der Zahlungsplan dieses Ziels KOMPLETT jenseits des Horizonts?

    GOAL-OUTSIDE-HORIZON-001. `_positive_due_wealth_indices()` liefert eine
    leere Liste fuer ZWEI voellig verschiedene Zustaende:

        (a) das Ziel hat gar keine positive Verbindlichkeit
            -- dann ist "erreicht" korrekt: es ist nichts zu finanzieren;
        (b) das Ziel hat Faelligkeiten, aber ALLE liegen hinter dem
            Horizont -- dann wurde es NICHT geprueft, sondern nur nicht
            angesehen.

    Die Aufrufer unterschieden das nicht und behandelten (b) wie (a):
    `_goal_probability_core()` gibt bei leeren Indizes `np.ones(...)` zurueck,
    also "auf jedem Pfad erreicht". Gemessen an einem Mock-Mandanten mit
    CHF 530'000 Beratungsvermoegen und einer Pensionsausgabe von
    CHF 5'000'000 PRO JAHR ab 2046 (Risikoprofil-Horizont 20 Jahre, also
    Buckets 2026-2045):

        liability_path_rappen = 20 Einträge, davon 0 positiv
        due_indices           = 0
        probability            = 1.0  ->  10000 bps, Status "erreichbar"

    Ein einmaliges Ziel von CHF 50 Mio im Horizont bekam im selben Lauf
    korrekt 0 bps. Nur der Strom jenseits des Horizonts -- das haerteste
    Ziel, Rang 1, in einer Ruhestandsplanung -- meldete erfundene Gewissheit.

    Die Unterscheidung wird NICHT aus dem Geldpfad zurueckgerechnet, sondern
    aus dem strukturellen Fahrplan gelesen: `target_year_index` traegt den
    Bucket der ersten echten Faelligkeit, und `_build_recurring_outflow()`
    klemmt ihn bei leerem Horizont bewusst NICHT (siehe dort:
    "``target_year_index > horizon_years`` ist das etablierte Signal 'liegt
    ausserhalb des Horizonts', auf das Konsumenten pruefen"). Dieser
    Aufrufer war der Konsument, der nicht geprueft hat.

    Aus dem Geldpfad zu schliessen waere ausserdem falsch: eine Reihe kann
    auch dann komplett null sein, wenn der Fahrplan IM Horizont liegt (ein
    bedingtes Ziel mit `probability_pct=0`, oder Betraege, die pro Bucket auf
    null runden) -- derselbe Zahlenwert, ein anderer Zustand.

    `n_wealth_columns` ist `horizon_years + 1`: Bucket t wird in Spalte t+1
    beobachtet, Spalte 0 ist das Startvermoegen.
    """
    horizon_years = int(n_wealth_columns) - 1
    if horizon_years < 1:
        return False
    return int(getattr(liability, "target_year_index", 0) or 0) > horizon_years


def shortfall_squared_per_path(
    liability: GoalLiability,
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
    normalization_scale_rappen: float | None = None,
) -> np.ndarray:
    """Liefert shortfall^2 pro Szenario-Pfad fuer ein Goal, shape (n_paths,).

    Wealth-Pfade kommen aus simulate_wealth_paths mit Liability bereits
    subtrahiert.

    Mit ``normalization_scale_rappen`` wird der Rappen-Fehlbetrag vor dem
    Quadrieren durch diese gemeinsame Context-Skala geteilt. ``None`` behaelt
    fuer direkte Diagnose-Caller den historischen Roh-Rappen-Wert bei.
    """
    n_paths = wealth_paths.shape[0]

    if liability.target_kind == "maximize":
        return np.zeros(n_paths, dtype=np.float64)

    if liability.target_kind == "return_rate":
        # #2 (2026-06-12): einheitenkonsistenter Shortfall in Rappen statt bps².
        # Vorher: max(0, target_bps - annualized_bps)² in bps² (~1e4-1e8) — ging
        # in gemischten Goal-Sets gegen Wealth-Ziele (Rappen²~1e16) unter, das
        # Renditeziel war im primaeren SLSQP-Objective faktisch unsichtbar.
        # Fix: impliziertes Wealth-Target = initial·(1+r)^h (Spec §4.1: annualized
        # >= target  <=>  end_wealth >= initial·(1+target)^h). IDENTISCH zu
        # goal_probability_per_path -> primaeres Objective & Chance-Constraint
        # (P-Ampel) nutzen jetzt dieselbe Renditeziel-Definition.
        horizon = max(1, min(
            int(liability.target_year_index or (wealth_paths.shape[1] - 1)),
            wealth_paths.shape[1] - 1,
        ))
        target_return = float(liability.target_amount_rappen) / 10000.0
        target_wealth = max(1.0, float(initial_wealth_rappen)) * ((1.0 + target_return) ** horizon)
        if annualized_return_bps_per_path is None:
            comparison_wealth = wealth_paths[:, horizon]
        else:
            twr = np.asarray(
                annualized_return_bps_per_path, dtype=np.float64
            ).reshape(-1)
            if twr.shape != (n_paths,):
                raise ValueError(
                    "annualized_return_bps_per_path must match n_paths "
                    f"({twr.shape} != {(n_paths,)})"
                )
            comparison_wealth = max(1.0, float(initial_wealth_rappen)) * np.power(
                np.maximum(0.0, 1.0 + twr / 10000.0), horizon
            )
        shortfall = np.maximum(0.0, target_wealth - comparison_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "wealth_at_t":
        target = float(liability.target_amount_rappen)
        idx = max(1, min(int(liability.target_year_index), wealth_paths.shape[1] - 1))
        wealth_at_t = wealth_paths[:, idx]
        shortfall = np.maximum(0.0, target - wealth_at_t)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "cashflow_in_year":
        # The one-off expense is already part of liability_path and therefore
        # already subtracted in the simulated wealth at T. Requiring the same
        # amount again here would double-count the goal.
        due_indices = _positive_due_wealth_indices(
            liability,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.zeros(n_paths, dtype=np.float64)
        minimum_due_wealth = np.min(wealth_paths[:, due_indices], axis=1)
        shortfall = np.maximum(0.0, -minimum_due_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "outflow_stream":
        # Every scheduled payment must be fundable when due. Looking only at
        # terminal wealth can hide an interim funding gap that a later inflow
        # happens to repair.
        due_indices = _positive_due_wealth_indices(
            liability,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.zeros(n_paths, dtype=np.float64)
        minimum_due_wealth = np.min(wealth_paths[:, due_indices], axis=1)
        shortfall = np.maximum(0.0, -minimum_due_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    return np.zeros(n_paths, dtype=np.float64)


def _priority_protected_wealth_paths(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
) -> tuple[np.ndarray, bool]:
    """Reconstruct `goal`'s priority-protected wealth trajectory.

    GOAL-FUNDING-PRIORITY-001 (CERT-GOAL-FUNDING-001), Spec Sec. 4.2: a goal
    with rank ``r`` must be evaluated on the cumulative scope
    ``S_r = {h | rank(h) <= r}``, not on the unprotected joint aggregate of
    every requested goal. ``goals_to_liabilities()`` precomputes, for every
    goal in a batch, ``priority_scope_liability_path_rappen`` (the scope-r
    cumulative outflow) and ``joint_liability_path_rappen`` (the full
    unprotected aggregate -- what actually produced the given
    ``wealth_paths``).

    When both are present and differ, this derives the per-path, per-year
    growth factor directly from the already-realized joint trajectory
    (``simulate_wealth_paths`` applies growth before subtracting the
    liability for that year) and re-applies that SAME realized growth to the
    scope-protected liability path instead. This is mathematically identical
    to re-running ``simulate_wealth_paths`` on the same scenario cube with a
    different liability path (common random numbers, Hard Invariant #3) as
    long as liability subtraction does not itself feed back into growth
    (true when ``tax_regime`` is inactive; a known approximation otherwise,
    see PR description). It is NOT path-wise lookahead: every return used
    here already happened in the given ``wealth_paths``; no later year's
    return is consulted to decide an earlier year's funding order.

    Returns (wealth_paths_or_reconstruction, was_reconstructed).
    """
    scope_path = goal.priority_scope_liability_path_rappen
    joint_path = goal.joint_liability_path_rappen
    if not scope_path or not joint_path or list(scope_path) == list(joint_path):
        return wealth_paths, False

    n_cols = wealth_paths.shape[1]
    horizon = n_cols - 1
    protected = np.array(wealth_paths, dtype=np.float64, copy=True)
    prev_joint = wealth_paths[:, 0]
    prev_protected = protected[:, 0]
    for t in range(horizon):
        joint_next = wealth_paths[:, t + 1]
        joint_liab_t = float(joint_path[t]) if t < len(joint_path) else 0.0
        scope_liab_t = float(scope_path[t]) if t < len(scope_path) else 0.0
        pre_liability_joint = joint_next + joint_liab_t
        with np.errstate(divide="ignore", invalid="ignore"):
            growth_factor = np.where(
                prev_joint != 0.0, pre_liability_joint / prev_joint, 1.0
            )
        protected_next = prev_protected * growth_factor - scope_liab_t
        protected[:, t + 1] = protected_next
        prev_joint = joint_next
        prev_protected = protected_next
    return protected, True


def _goal_probability_core(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
    initial_value_rappen: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> np.ndarray:
    """Returns an int array with 1 where the goal is achieved, else 0.

    Pure function of the GIVEN wealth_paths (no priority-scope
    reconstruction) -- used internally wherever the deliberately unprotected
    joint-requested-plan view is required (``chance_constraint_penalty``).
    """
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return np.zeros(0, dtype=np.int8)
    if goal.target_kind == "maximize":
        return np.ones(n_paths, dtype=np.int8)
    if goal.target_kind == "wealth_at_t":
        idx = max(1, min(int(goal.target_year_index), wealth_paths.shape[1] - 1))
        target = float(goal.target_amount_rappen or 0)
        return (wealth_paths[:, idx] >= target).astype(np.int8)
    if goal.target_kind == "cashflow_in_year":
        due_indices = _positive_due_wealth_indices(
            goal,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.ones(n_paths, dtype=np.int8)
        return np.all(wealth_paths[:, due_indices] >= 0, axis=1).astype(np.int8)
    if goal.target_kind == "outflow_stream":
        due_indices = _positive_due_wealth_indices(
            goal,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.ones(n_paths, dtype=np.int8)
        return np.all(wealth_paths[:, due_indices] >= 0, axis=1).astype(np.int8)
    if goal.target_kind == "return_rate":
        if annualized_return_bps_per_path is not None:
            twr = np.asarray(
                annualized_return_bps_per_path, dtype=np.float64
            ).reshape(-1)
            if twr.shape != (n_paths,):
                raise ValueError(
                    "annualized_return_bps_per_path must match n_paths "
                    f"({twr.shape} != {(n_paths,)})"
                )
            return (
                twr >= float(goal.target_amount_rappen or 0)
            ).astype(np.int8)
        horizon = max(1, min(int(goal.target_year_index or (wealth_paths.shape[1] - 1)), wealth_paths.shape[1] - 1))
        target_return = float(goal.target_amount_rappen or 0) / 10000.0
        target_wealth = float(max(1, int(initial_value_rappen or 0))) * ((1.0 + target_return) ** horizon)
        return (wealth_paths[:, horizon] >= target_wealth).astype(np.int8)
    return np.ones(n_paths, dtype=np.int8)


def goal_probability_per_path(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
    initial_value_rappen: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> np.ndarray:
    """Returns an int array with 1 where the goal is achieved, else 0.

    GOAL-FUNDING-PRIORITY-001: when `goal` carries priority-scope evidence
    (built via ``goals_to_liabilities()``), the goal is evaluated on its own
    priority-protected wealth trajectory (Spec Sec. 4.2 ``P_protected(g)``),
    not on the raw ``wealth_paths`` the caller supplies -- a lower-priority
    (higher-rank) goal's outflow must not be able to drag a higher-priority
    goal's achievability below what it would have been without it. Callers
    that deliberately want the unprotected joint-requested-plan view (e.g.
    ``chance_constraint_penalty`` below) use ``_goal_probability_core``
    directly instead of this public wrapper.
    """
    protected_wealth_paths, reconstructed = _priority_protected_wealth_paths(
        wealth_paths, goal
    )
    effective_twr = None if reconstructed else annualized_return_bps_per_path
    return _goal_probability_core(
        protected_wealth_paths,
        goal,
        initial_value_rappen,
        annualized_return_bps_per_path=effective_twr,
    )


def certify_success_indicator(
    per_path: np.ndarray,
    *,
    tau: float,
    weights_arr: np.ndarray | None,
    weight_sum: float | None,
    validation_seed: int | None,
    outside_horizon: bool = False,
) -> dict:
    """Schaetzer + Zertifizierung fuer EINEN 0/1-Erfolgsindikator je Pfad.

    Einzige Implementierung der Statuskette erreichbar / knapp /
    nicht_erreichbar / unreliable / ausserhalb_horizont. Herausgeloest aus
    ``chance_constraint_penalty`` (GOAL-ACHIEVABILITY-ATTRIBUTION-001), damit
    die publizierte priorisierte Zielerreichung und die Plan-Solvenz
    (``services/optimizer/goal_attribution.py``) exakt dieselbe
    Zertifizierungsregel verwenden wie die Chance-Penalty -- zwei Kopien
    dieser Kette waeren genau die Divergenzklasse, die die
    MC-Paritaetsbefunde ausgeloest hat. Rein strukturell: fuer die Penalty
    entstehen bit-identische Werte.
    """
    if per_path.size == 0:
        probability = 0.0
    elif weights_arr is None:
        probability = float(np.mean(per_path))
    else:
        probability = float(
            np.sum(per_path.astype(np.float64) * weights_arr) / weight_sum
        )

    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001: schaetzer-bewusste
    # Zertifizierung statt roher Punktschaetzer -- siehe
    # services/optimizer/certification.py.
    n_paths = int(per_path.size)
    if weights_arr is None:
        n_effective = float(n_paths)
    else:
        n_effective = effective_sample_size(weights_arr)
    lower_bound = wilson_lower_bound(probability, n_effective)
    ess_sufficient = ess_is_sufficient(n_effective, n_paths)

    if outside_horizon:
        # GOAL-OUTSIDE-HORIZON-001: `_goal_probability_core()` liefert fuer
        # ein Ziel ohne Faelligkeit im Horizont `np.ones(...)`, also
        # probability = 1.0. Die Zahl folgt dem MC-Kanal, der denselben
        # Zustand schon so meldet (`portfolio_engine_mc_simulation.py`:
        # `success_rate_pct = 0` plus `outside_simulation_horizon = True`
        # plus Notiz). Genau der WIDERSPRUCH zwischen den beiden Kanaelen
        # war der Befund: derselbe Zustand, hier 100 %, dort 0 %. Parity ist
        # der Gewinn, nicht die Zahl -- 0 ist eine durch die Offenlegung
        # getragene Konvention, keine Messung. Der eigene Status verhindert,
        # dass ein Konsument daraus "nicht erreichbar" liest.
        probability = 0.0
        lower_bound = 0.0
        status = "ausserhalb_horizont"
    elif ess_sufficient and lower_bound >= tau:
        status = "erreichbar"
    elif not ess_sufficient and probability >= TAU_UNREACHABLE:
        # Zu wenig unabhaengige Evidenz (z.B. degenerierte IS-Gewichtung),
        # UND der Punktschaetzer deutet in Richtung erreichbar: dann laesst
        # sich die Frage nicht beantworten -> nicht beurteilbar.
        #
        # Das Gate blockiert bewusst nur die ZERTIFIZIERUNG, nicht jede
        # Aussage: liegt der Punktschaetzer klar unter der Schwelle, ist
        # "nicht erreichbar" auch bei kleiner Stichprobe die korrekte und
        # nuetzliche Antwort -- ein sicherer Negativbefund ist nicht
        # unzuverlaessig, nur negativ.
        status = "unreliable"
    elif probability >= TAU_UNREACHABLE:
        status = "knapp"
    else:
        status = "nicht_erreichbar"

    verdict = reliability_verdict(
        probability=probability,
        lower_bound=lower_bound,
        tau=tau,
        ess_sufficient=ess_sufficient,
        validation_seed=validation_seed,
        outside_horizon=outside_horizon,
    )
    return {
        "probability": probability,
        "lower_confidence_bound": lower_bound,
        "effective_sample_size": n_effective,
        "status": status,
        "reliability_verdict": verdict,
    }


def goal_volume_rappen(
    goal: GoalLiability,
    *,
    initial_value_rappen: float,
    n_wealth_columns: int,
) -> float:
    """Geldvolumen, das bei einem VOLLSTAENDIGEN Ausfall des Ziels fehlt.

    OBJECTIVE-NORMALIZATION-001: Massstab der Chance-Constraint-Strafe.

    * ``wealth_at_t``: der Zielbetrag.
    * ``cashflow_in_year`` / ``outflow_stream``: Summe der positiven
      Faelligkeiten INNERHALB des Horizonts (dieselben Indizes, die
      Fehlbetrag und Erfolgsquote pruefen; Faelligkeiten jenseits des
      Horizonts werden nirgends bewertet).
    * ``return_rate``: das implizite Zielvermoegen ``W0 * (1 + r)^h`` --
      dieselbe Definition wie in ``shortfall_squared_per_path``.
    * ``maximize`` und Unbekanntes: 0 (keine Strafe; ein Maximierungsziel
      hat keinen Zielwert und damit keine Ziel-Untergrenze -- es wirkt nur
      ueber den Wachstumsterm in L(w), MAXIMIZE-GOAL-001).
    """
    kind = goal.target_kind
    if kind == "wealth_at_t":
        return max(0.0, float(goal.target_amount_rappen or 0))
    if kind in ("cashflow_in_year", "outflow_stream"):
        return float(sum(
            float(amount or 0)
            for index, amount in enumerate(goal.liability_path_rappen or ())
            if float(amount or 0) > 0.0 and index + 1 < int(n_wealth_columns)
        ))
    if kind == "return_rate":
        horizon = max(1, min(
            int(goal.target_year_index or (int(n_wealth_columns) - 1)),
            max(1, int(n_wealth_columns) - 1),
        ))
        target_return = float(goal.target_amount_rappen or 0) / 10000.0
        return max(1.0, float(initial_value_rappen)) * ((1.0 + target_return) ** horizon)
    return 0.0


def chance_constraint_penalty(
    wealth_paths: np.ndarray,
    goal_liabilities: list[GoalLiability],
    initial_value_rappen: int,
    lambda_chance: float | None = None,
    *,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    validation_seed: int | None = None,
) -> tuple[float, list[dict]]:
    """Return chance-constraint penalty and per-goal achievability rows.

    WEICHE Strafe (Soft-Regret), keine garantierte Untergrenze (Codex-
    Review CHANCE-PENALTY-NOT-CONSTRAINT-001; echte Wahrscheinlichkeits-
    Untergrenzen sind Phase 2). Der Haertegrad wirkt NICHT hier, sondern
    ueber den Fehlbetrag und die Zielhierarchie (GOAL-HARDNESS-DEFAULT-001,
    GOAL-HIERARCHY-001).

    GOAL-SCREEN-OBJECTIVE-ERASURE-001 (Engine v7): es gibt KEINE
    Ausnahme mehr fuer "praktisch unerreichbare" Ziele. Bis v6 nahm
    ``penalty_exempt_goal_ids`` (Reachability-Screen) harte/primaere Ziele
    ganz aus Strafe und Fehlbetrag -- CHF 0 und CHF 900 gegen ein hartes
    Ziel von CHF 1'000 waren dann gleich gut. Der Screen ist jetzt reine
    Offenlegung (``goal_reachability.py``).

    Parameters
    ----------
    weights : np.ndarray | None
        Sprint P1 (2026-06-06): Optional Likelihood-Ratio-Weights aus
        Importance Sampling. Wenn None: uniform sample-mean P(success).
        Wenn gesetzt: weighted estimator
        P_weighted = Sum(per_path * w) / Sum(w).

        WICHTIG: ohne diesen Parameter wuerde IS einen verzerrten
        Probability-Estimator liefern (alle Pfade aus shifted distribution
        gleich gewichtet) — die PDF-Achievability-Rows waeren falsch.
    validation_seed : int | None
        OPTIMIZER-POST-SELECTION-CERTIFICATION-001: Seed der UNABHAENGIGEN
        Validierungsstichprobe, auf der dieses Ergebnis nachgeprueft wurde.
        None bedeutet "auf demselben Cube zertifiziert, auf dem selektiert
        wurde" -- dann kann das Verdikt hoechstens
        `unvalidated_single_cube` werden, niemals `robust`. Das Fehlen der
        Evidenz bleibt so sichtbar statt stillschweigend als gruen
        durchzugehen.

    Zertifizierungsregel (OPTIMIZER-POST-SELECTION-CERTIFICATION-001)
    -----------------------------------------------------------------
    "erreichbar" verlangt jetzt, dass die einseitige untere
    Konfidenzgrenze (Wilson-Score, bei Importance Sampling auf Basis des
    Kish-ESS) die Schwelle tau haelt -- nicht mehr der rohe
    Punktschaetzer. Bei genau p_hat == tau liegt die wahre
    Wahrscheinlichkeit mit rund 50 Prozent darunter; das ist keine
    Zertifizierungsgrundlage.

    Ebenso wichtig: die STRAFE haengt ebenfalls an der unteren Grenze. Sonst
    wuerde der Solver weiterhin gegen den rauschbehafteten Punktschaetzer
    optimieren und genau den Winner's-Curse-Effekt einsammeln, den diese
    Aenderung adressiert -- er darf erst zufrieden sein, wenn die
    ZERTIFIZIERTE Wahrscheinlichkeit die Schwelle haelt.

    Strafe (OBJECTIVE-NORMALIZATION-001, 2026-10-18)
    ------------------------------------------------
    Je Ziel mit Primaer-Haertegrad::

        lambda * max(0, tau - LB) * (Zielvolumen / max(1, W0))^2

    Vorher ``1e6 * max(0, tau - LB)^2``. Zwei Defekte:

    * Skala: 1e6 ist dimensionslos gegen nichts -- der Primaerterm liegt
      (gleiche Kontext-Skala W0) bei 1e-9..10, die Risikomass-Varianten bei
      0.01..0.3. Gemessen (Fundament-Mandat): Strafe 1.1e6 gegen Drawdown
      0.26 -- in jeder Variante entschied allein die Strafe.
    * Form: das Quadrat macht kleine Defizite verschwindend (1 pp ->
      1e-4 * lambda) und grosse explosiv; es ist eine INEXAKTE Strafe.
      Linear im Defizit ist die exakte (L1-)Strafe: ab hinreichendem Gewicht
      wird die Nebenbedingung exakt eingehalten, wo sie einhaltbar ist.

    Das Zielvolumen-Quadrat ueber W0^2 ist exakt die Einheit des
    Primaerterms (mittlerer quadrierter relativer Fehlbetrag): ein Defizit
    Delta kostet so viel wie ein vollstaendiger Ausfall des Ziels auf einem
    Pfad-Anteil Delta. ``lambda`` (Default ``CHANCE_PENALTY_WEIGHT`` = 1.0)
    bleibt als Parameter, ist aber keine Kalibrierungsgroesse mehr.
    """
    weight = CHANCE_PENALTY_WEIGHT if lambda_chance is None else float(lambda_chance)
    context_scale_rappen = _context_scale_rappen(initial_value_rappen)
    penalty = 0.0
    achievability: list[dict] = []
    if weights is not None:
        weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
        if weights_arr.shape[0] != wealth_paths.shape[0]:
            raise ValueError(
                f"weights.shape[0]={weights_arr.shape[0]} != n_paths={wealth_paths.shape[0]}"
            )
        weight_sum = float(np.sum(weights_arr))
        if weight_sum <= 0:
            raise ValueError("Sum-of-weights must be > 0")
    else:
        weights_arr = None
        weight_sum = None
    for goal in goal_liabilities:
        # Deliberately the UNPROTECTED joint-requested-plan view (Spec Sec.
        # 4.2 `W_joint_requested`/`P_joint_requested`): the chance-constraint
        # term feeding the SLSQP objective is unchanged by
        # GOAL-FUNDING-PRIORITY-001 and GOAL-ACHIEVABILITY-ATTRIBUTION-001.
        #
        # GOAL-ACHIEVABILITY-ATTRIBUTION-001 (2026-10-14): the rows returned
        # here are the PENALTY's internal per-goal view of the joint path and
        # are NOT published any more. Every publication point (solver
        # result, validation cube, House fallback) uses
        # `services.optimizer.goal_attribution.publish_goal_achievability`,
        # which emits priority-funded goal rows plus exactly ONE joint-plan
        # row. The rows are tagged with their own scope so that an
        # accidental publication is recognisable as non-individual evidence.
        per_path = _goal_probability_core(
            wealth_paths,
            goal,
            initial_value_rappen,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
        )
        tau = _default_tau_x100(goal) / 10000.0
        # GOAL-OUTSIDE-HORIZON-001: VOR der Statuskette und vor dem Verdikt
        # (Begruendung in `certify_success_indicator`).
        outside_horizon = goal.target_kind in (
            "cashflow_in_year", "outflow_stream",
        ) and scheduled_outside_wealth_horizon(
            goal, n_wealth_columns=wealth_paths.shape[1]
        )
        estimate = certify_success_indicator(
            per_path,
            tau=tau,
            weights_arr=weights_arr,
            weight_sum=weight_sum,
            validation_seed=validation_seed,
            outside_horizon=outside_horizon,
        )
        probability = estimate["probability"]
        lower_bound = estimate["lower_confidence_bound"]
        n_effective = estimate["effective_sample_size"]
        status = estimate["status"]
        verdict = estimate["reliability_verdict"]

        hardness = _hardness_key(getattr(goal, "hardness_key", None))
        applies_penalty = hardness in _PRIMARY_HARDNESS_KEYS and goal.target_kind != "maximize"
        if outside_horizon:
            # KEINE Strafe: der Solver darf nicht gegen etwas optimieren, das
            # die Simulation nicht beobachtet. Eine Strafe wuerde die
            # Allokation fuer alle UEBRIGEN Ziele verzerren, um einen
            # Fehlbetrag zu bekaempfen, der innerhalb des Horizonts gar nicht
            # auftritt. Der Befund war die falsche AUSSAGE, nicht eine
            # fehlende Strafe -- deshalb wird hier offengelegt, nicht
            # bestraft.
            applies_penalty = False
        if applies_penalty:
            # Strafe an der unteren Grenze, nicht am Punktschaetzer (siehe
            # Docstring). Bei kollabierendem ESS geht die Grenze gegen 0 und
            # die Strafe entsprechend hoch -- eine unbelastbare
            # Zertifizierung ist damit automatisch kein Freifahrtschein.
            deficit = max(0.0, tau - lower_bound)
            relative_volume = goal_volume_rappen(
                goal,
                initial_value_rappen=initial_value_rappen,
                n_wealth_columns=wealth_paths.shape[1],
            ) / context_scale_rappen
            penalty += weight * deficit * relative_volume * relative_volume
        achievability.append({
            "goal_id": str(goal.goal_id),
            "label": str(goal.label),
            "target_kind": str(goal.target_kind),
            "probability": probability,
            "tau": tau,
            "status": status,
            "hardness": _display_hardness(hardness),
            "lower_confidence_bound": lower_bound,
            "effective_sample_size": n_effective,
            "validation_seed": validation_seed,
            "reliability_verdict": verdict,
            # Gleicher Feldname wie im MC-Kanal, damit ein Konsument beide
            # Strecken gleich lesen kann.
            "outside_simulation_horizon": outside_horizon,
            "evaluation_scope": "joint_path_chance_penalty",
        })
    return float(penalty), achievability


def shortfall_objective(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    goal_weighting_mode: str | None = None,
) -> float:
    """Primaere Objective L(w): gewichteter dimensionsloser MSE-Shortfall.

    Jedes Ziel geht ein (GOAL-SCREEN-OBJECTIVE-ERASURE-001, Engine v7: keine
    Ausnahme "unerreichbarer" Ziele mehr -- auch ein Ziel, das seine
    Schwelle nie erreicht, unterscheidet zwischen viel und wenig
    Fehlbetrag).

    Jeder Rappen-Fehlbetrag wird vor dem Quadrieren durch die gemeinsame
    Context-Skala ``max(1, initial_wealth_rappen)`` geteilt. Damit bleibt die
    absolute Rangfolge der Fehlbetraege sowie die Hardness-/Goal-Gewichtung
    erhalten, waehrend Primary- und Chance-Terme einheitenfrei sind.

    L(w) = Σ_g h_g · g_g · mean_n(shortfall(g, n)^2)

    h_g = _goal_hardness_weight(liability)
          → Default HARDNESS_WEIGHT (Modus ``hardness``, ab v7);
            1.0 im Opt-out OPTIMIZER_GOAL_WEIGHTING=equal; fuer
            ``maximize`` hoechstens 1.0.
    g_g = liability.weight_bps / 10000

    Maximierungsziele (MAXIMIZE-GOAL-001) tragen statt eines Fehlbetrags
    ``-MAXIMIZE_GROWTH_WEIGHT * h_g * g_g * mean_n(T * log(1 + r_n))``
    (siehe ``maximize_growth_per_path``); L(w) kann damit negativ werden.

    Skalar-Output, von scipy.optimize.minimize konsumierbar.

    Parameters
    ----------
    weights : np.ndarray | None
        Optional. Shape (n_paths,). Likelihood-Ratio-Weights aus
        Importance Sampling (services/optimizer/importance_sampling.py).
        Wenn None: trivialer sample-mean (alle Pfade gleich gewichtet).
        Wenn gesetzt: weighted mean = Σ (per_path · w) / Σ w.

        Phase 5c — Mathematik-Backbone fuer IS-faehigen Solver-Pfad.
        Backwards-Compat: bei weights=None identisch zu vorher.
    """
    total = 0.0
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return 0.0
    context_scale_rappen = _context_scale_rappen(initial_wealth_rappen)
    # Normalisierung: bei weights=None → uniform; sonst weighted (NOT mean von w,
    # sondern Sum(per_path · w) / Sum(w) als unverzerrter Estimator).
    if weights is None:
        inv_n = 1.0 / n_paths
        weight_sum = None
    else:
        weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
        if weights_arr.shape[0] != n_paths:
            raise ValueError(
                f"weights.shape[0]={weights_arr.shape[0]} != n_paths={n_paths}"
            )
        weight_sum = float(np.sum(weights_arr))
        if weight_sum <= 0:
            raise ValueError("Sum-of-weights must be > 0")
    for liab in liabilities:
        h_weight = _goal_hardness_weight(liab, goal_weighting_mode)
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        if liab.target_kind == "maximize":
            # MAXIMIZE-GOAL-001: Wachstumsterm statt Fehlbetrag (negativ =
            # Nutzen; die Zielfunktion wird minimiert).
            growth = maximize_growth_per_path(
                liab, wealth_paths,
                initial_wealth_rappen=initial_wealth_rappen,
                annualized_return_bps_per_path=annualized_return_bps_per_path,
            )
            if weights is None:
                mean_growth = float(np.sum(growth) * inv_n)
            else:
                mean_growth = float(np.sum(growth * weights_arr) / weight_sum)
            total -= MAXIMIZE_GROWTH_WEIGHT * h_weight * g_weight * mean_growth
            continue
        per_path = shortfall_squared_per_path(
            liab, wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            normalization_scale_rappen=context_scale_rappen,
        )
        if weights is None:
            mean_sq = float(np.sum(per_path) * inv_n)
        else:
            mean_sq = float(np.sum(per_path * weights_arr) / weight_sum)
        total += h_weight * g_weight * mean_sq
    return total


def volatility_objective(
    wealth_paths: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> float:
    """Sekundaere Objective: Varianz des End-Wealth ueber Pfade.

    Wird genutzt wenn die primary objective bereits ~0 ist und wir auf
    minimale Volatilitaet optimieren wollen (Slide 18 Priorität 2).

    Parameters
    ----------
    weights : np.ndarray | None
        Optional Likelihood-Ratios (Phase 5c). Bei None: trivial np.var.
        Bei gesetzt: weighted variance = Σ w·(x-E_w[x])² / Σ w
        (Estimator fuer Var unter Ziel-Verteilung wenn weights die
        Likelihood-Ratios sind).
    """
    end_wealth = wealth_paths[:, -1]
    if weights is None:
        return float(np.var(end_wealth))
    weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
    if weights_arr.shape[0] != end_wealth.shape[0]:
        raise ValueError(
            f"weights.shape[0]={weights_arr.shape[0]} != n_paths={end_wealth.shape[0]}"
        )
    weight_sum = float(np.sum(weights_arr))
    if weight_sum <= 0:
        raise ValueError("Sum-of-weights must be > 0")
    weighted_mean = float(np.sum(end_wealth * weights_arr) / weight_sum)
    deviations = end_wealth - weighted_mean
    return float(np.sum(weights_arr * deviations * deviations) / weight_sum)


# ============================================================================
# V3 Sprint 1d (Plan §5.4): Goal-Driver Erklaerbarkeit
# ============================================================================


@dataclass(frozen=True)
class GoalShortfallContribution:
    """Beitrag eines einzelnen Goals zum Gesamt-Shortfall-Objective.

    Objective-Beitraege sind dimensionslos: jeder Rappen-Fehlbetrag wird vor
    dem Quadrieren mit derselben Initialvermoegens-Skala normalisiert.

    'Contribution under aggregate wealth path' (Plan §5.4):
        contribution = h_g · g_g · mean_n(shortfall(g, n)^2)
    Das ist NICHT eine teure marginale Counterfactual-Berechnung
    ('Objective ohne dieses Goal') — sondern der direkte Beitrag, den dieses
    Goal in der gemeinsam evaluierten Summe ausmacht. Sortierung absteigend
    macht 'welches Ziel dominiert den Shortfall' fuer den Berater sichtbar.

    weighted_objective_contribution: float
        Direkt vergleichbar mit dem Output von shortfall_objective() — die
        Summe aller GoalShortfallContribution.weighted_objective_contribution
        ergibt L(w).
    """
    goal_id: str
    label: str
    target_kind: str
    hardness_key: str
    weight_bps: int
    mean_shortfall_squared: float
    weighted_objective_contribution: float


def shortfall_contributions(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
    goal_weighting_mode: str | None = None,
) -> list[GoalShortfallContribution]:
    """Pro Goal: Mean-Shortfall² und gewichteter Beitrag zum Objective.

    Sortiert absteigend nach weighted_objective_contribution: das groesste
    Risiko zuerst. Wenn n_paths == 0, leere Liste.

    OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: ``goal_weighting_mode`` kommt vom
    Aufrufer aus dem eingefrorenen Lauf-Vertrag. Diese Funktion erzeugt die
    Goal-Driver-Zeilen ("welches Ziel treibt den Shortfall") -- laest sie den
    Modus selbst aus der Umgebung, koennen die Treiber nach einer ANDEREN
    Gewichtung ausgewiesen sein als die, mit der der Solver optimiert hat.
    Die Erklaerung widerspraeche dann der Entscheidung, die sie erklaert.
    """
    rows: list[GoalShortfallContribution] = []
    if wealth_paths.size == 0:
        return rows
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return rows
    context_scale_rappen = _context_scale_rappen(initial_wealth_rappen)
    inv_n = 1.0 / n_paths
    for liab in liabilities:
        per_path = shortfall_squared_per_path(
            liab,
            wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            normalization_scale_rappen=context_scale_rappen,
        )
        mean_sq = float(np.sum(per_path) * inv_n)
        h_weight = _goal_hardness_weight(liab, goal_weighting_mode)
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        contribution = h_weight * g_weight * mean_sq
        if liab.target_kind == "maximize":
            # MAXIMIZE-GOAL-001: derselbe Term wie in ``shortfall_objective``
            # (Summe der Beitraege = L(w)); kein Fehlbetrag.
            growth = maximize_growth_per_path(
                liab, wealth_paths,
                initial_wealth_rappen=initial_wealth_rappen,
                annualized_return_bps_per_path=annualized_return_bps_per_path,
            )
            contribution = -MAXIMIZE_GROWTH_WEIGHT * h_weight * g_weight * float(
                np.sum(growth) * inv_n
            )
        rows.append(GoalShortfallContribution(
            goal_id=str(liab.goal_id),
            label=str(liab.label),
            target_kind=str(liab.target_kind),
            hardness_key=str(liab.hardness_key),
            weight_bps=int(liab.weight_bps),
            mean_shortfall_squared=mean_sq,
            weighted_objective_contribution=float(contribution),
        ))
    return sorted(rows, key=lambda row: row.weighted_objective_contribution, reverse=True)


def normalized_terminal_variance(
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    weights: np.ndarray | None = None,
) -> float:
    """``Var(W_T) / max(1, W0)^2`` -- der Tiebreak in der Einheit des Primaerterms.

    OBJECTIVE-NORMALIZATION-001: vorher ``1e-12 * Var(W_T)`` in Rappen^2.
    Das war an die Waehrungseinheit gekoppelt (Faktor W0^2): bei CHF 500'000
    lag der Term bei ~2e3, bei CHF 5'000 bei ~0.2 -- die Rangfolge zwischen
    Ziel-Fehlbetrag und Volatilitaet hing an der Vermoegensgroesse. Mit
    derselben Kontext-Skala wie ``shortfall_objective`` ist sie
    skaleninvariant.
    """
    scale = _context_scale_rappen(initial_wealth_rappen)
    return volatility_objective(wealth_paths, weights=weights) / (scale * scale)


def portfolio_variance_one_year(
    weights: np.ndarray,
    covariance_bps2: np.ndarray,
) -> float:
    """``w' Sigma w`` in Dezimal^2 (Sigma in bps^2): Tiebreak-Mass.

    TIEBREAK-PORTFOLIO-VARIANCE-001: einjaehrige Portfolio-Varianz aus der
    CMA-Kovarianz des Laufs -- dieselbe Groesse wie die ausgewiesene
    erwartete Volatilitaet (Quadrat), unabhaengig vom Mittelwert und von
    den Szenariopfaden.
    """
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    cov = np.asarray(covariance_bps2, dtype=np.float64) / 1e8
    return float(w @ cov @ w)


def combined_objective_two_phase(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    primary_weight: float = 1.0,
    volatility_weight: float | None = None,
    lambda_chance: float | None = None,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    objective_mode: str | None = None,
    goal_weighting_mode: str | None = None,
    portfolio_return_factors: np.ndarray | None = None,
    portfolio_variance: float | None = None,
) -> float:
    """Skalare Zielfunktion des Solvers: Ziel-Stufe + IMMER aktiver Tiebreak.

    ``f(w) = primary_weight * P(w) + C(w) + kappa * w' Sigma w``

    * ``P(w)``: Primaerterm des Modus (Default ``goal_shortfall`` = L(w)).
    * ``C(w)``: Chance-Constraint-Strafe (``chance_constraint_penalty``),
      in JEDEM Modus aktiv -- die Ziel-Untergrenze.
    * Tiebreak nur im Modus ``goal_shortfall`` (in den Varianten uebernimmt
      der Primaerterm diese Rolle; bei ``min_volatility`` wuerde er die
      Kennzahl doppelt zaehlen). ``kappa`` = ``volatility_weight``, Default
      ``TIEBREAK_VARIANCE_WEIGHT``.

    OBJECTIVE-NORMALIZATION-001 (2026-10-18): Vorher wurde der Tiebreak PRO
    ALLOKATION nur zugeschaltet, wenn deren Ziel-Stufe < 1e-12 war
    (Stufen-Schalter), mit einem Gewicht von 1e-12 auf Rappen^2. Die
    Funktion war damit nicht monoton: eine Allokation mit einem Fehlbetrag
    von 8e-9 auf einem einzigen Pfad hatte den Wert 8e-9, eine Allokation,
    die alle Ziele erfuellt, den Wert ~1.4e4. Gemessen in den Bags der
    CH-Golden-Mandate (Score 5): in 44 von 49 Bags, in denen der Solver
    ueberhaupt einen Punkt mit Ziel-Stufe 0 auswertete, gewann trotzdem eine
    Allokation mit Restfehlbetrag. Jetzt: stetig und Pareto-monoton -- ist
    eine Allokation auf Ziel-Stufe UND Tiebreak mindestens so gut und auf
    einem davon besser, ist ihr Wert kleiner. Herleitung von ``kappa``:
    docs/planning/2026-10-18-objective-normalization.md.

    Die Funktion behaelt ihren Namen (Aufrufer, Audit-Trails); "two phase"
    bezeichnet die Prioritaet der zwei Stufen, nicht mehr einen Schalter.

    OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: ``objective_mode`` UND
    ``goal_weighting_mode`` kommen beim Solver-Aufruf aus dem
    unveraenderlichen Lauf-Vertrag (``OptimizerContext.objective_contract``).
    Beide bleiben optional, weil Nicht-Solver-Konsumenten ohne Lauf-Kontext
    aufrufen; nur innerhalb eines Laufs ist Konstanz eine
    Korrektheitsbedingung.
    """
    goal_level, tiebreak = two_phase_objective_parts(
        liabilities,
        wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
        primary_weight=primary_weight,
        volatility_weight=volatility_weight,
        lambda_chance=lambda_chance,
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
        objective_mode=objective_mode,
        goal_weighting_mode=goal_weighting_mode,
        portfolio_return_factors=portfolio_return_factors,
        portfolio_variance=portfolio_variance,
    )
    return goal_level + tiebreak


def two_phase_objective_parts(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    primary_weight: float = 1.0,
    volatility_weight: float | None = None,
    lambda_chance: float | None = None,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    objective_mode: str | None = None,
    goal_weighting_mode: str | None = None,
    portfolio_return_factors: np.ndarray | None = None,
    portfolio_variance: float | None = None,
    primary_value_override: float | None = None,
) -> tuple[float, float]:
    """Die beiden Terme von ``combined_objective_two_phase`` GETRENNT.

    Rueckgabe ``(goal_level, tiebreak)``: ``goal_level`` = Primaerterm +
    Chance-Strafe, ``tiebreak`` = gewichteter normierter Volatilitaetsterm
    (nur im Modus ``goal_shortfall``, sonst 0). Ihre Summe ist exakt der
    Skalarwert des Solvers -- fuer Audit und Diagnose, nicht fuer einen
    abweichenden Vergleich.

    ``primary_value_override`` (OPTIMIZER-DRAWDOWN-CERTIFICATION-001,
    2026-10-18): ersetzt den Primaerterm durch einen extern gemessenen Wert --
    im Modus ``max_drawdown`` der verfeinerte mittlere Max-Drawdown
    (Brownsche Bruecke) statt des Jahresgitter-Proxy. Chance-Strafe und
    Tiebreak bleiben dieselben; so gibt es fuer die Chance-Strafe genau EINE
    Implementierung, egal mit welchem Drawdown-Mass verglichen wird.
    """
    from .objective_variants import (
        OBJECTIVE_GOAL_SHORTFALL,
        primary_objective,
        resolve_objective_mode,
    )

    mode = resolve_objective_mode() if objective_mode is None else objective_mode
    liability_list = list(liabilities)
    is_goal_shortfall = mode == OBJECTIVE_GOAL_SHORTFALL
    # L(w) nur berechnen, wenn es auch der Primaerterm ist -- in den Varianten
    # waere es verworfene Arbeit in jeder einzelnen Solver-Iteration.
    goal_shortfall_value = (
        shortfall_objective(
            liability_list, wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            weights=weights,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            goal_weighting_mode=goal_weighting_mode,
        )
        if is_goal_shortfall
        else 0.0
    )
    primary = (
        float(primary_value_override)
        if primary_value_override is not None
        else primary_objective(
            mode,
            goal_shortfall_value=goal_shortfall_value,
            portfolio_return_factors=portfolio_return_factors,
            weights=weights,
        )
    )
    chance, _achievability = chance_constraint_penalty(
        wealth_paths,
        liability_list,
        int(initial_wealth_rappen),
        lambda_chance=lambda_chance,
        # OPT-1: weights MUSS auch in die Chance-Penalty fliessen. shortfall_ und
        # volatility_objective bekommen sie bereits; ohne sie schätzt die Penalty
        # P(success) als uniformes Sample-Mean über IS-geshiftete Pfade -> verzerrt
        # -> falsche Strafterme -> falsch gewichtete Optimierung. Konsistent mit
        # _objective_from_array/evaluate_weights (solver.py), die weights setzen.
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
    )
    kappa = (
        TIEBREAK_VARIANCE_WEIGHT if volatility_weight is None else float(volatility_weight)
    )
    # TIEBREAK-PORTFOLIO-VARIANCE-001: kappa * w' Sigma w (vom Aufrufer, der
    # die Allokation kennt). Ohne Allokation (Konsumenten ausserhalb eines
    # Laufs) gibt es keinen Tiebreak -- er ordnet nur Allokationen.
    tiebreak = (
        kappa * float(portfolio_variance)
        if is_goal_shortfall and kappa != 0.0 and portfolio_variance is not None
        else 0.0
    )
    goal_level = primary_weight * primary + chance
    return float(goal_level), float(tiebreak)


# ============================================================================
# GOAL-HIERARCHY-001: Stufe 1 (harte und primaere Ziele)
# ============================================================================


def is_protected_goal(liability: GoalLiability, *, n_wealth_columns: int) -> bool:
    """Ziel der Stufe 1: Haertegrad hart/primaer, mit Zielwert, im Horizont.

    Nicht geschuetzt: opportunistische Ziele, Maximierung (kein Zielwert),
    staatlich gedeckte Ziele und Zahlungsstroeme komplett jenseits des
    Horizonts (die Simulation beobachtet sie nicht, GOAL-OUTSIDE-HORIZON-001).
    """
    if _hardness_key(getattr(liability, "hardness_key", None)) not in _PRIMARY_HARDNESS_KEYS:
        return False
    if liability.target_kind in ("maximize", "state_funded"):
        return False
    if liability.target_kind in ("cashflow_in_year", "outflow_stream") and (
        scheduled_outside_wealth_horizon(liability, n_wealth_columns=n_wealth_columns)
    ):
        return False
    return True


def protected_goal_level(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    goal_weighting_mode: str | None = None,
    with_per_path: bool = False,
) -> tuple[float, np.ndarray | None]:
    """Stufe-1-Zielniveau ``G1(w)`` der harten/primaeren Ziele.

    ``G1 = sum_{g geschuetzt} (h_g * g_g * L_g + C_g)`` -- exakt die Terme,
    mit denen diese Ziele in ``combined_objective_two_phase`` stehen
    (Fehlbetrag mit Haertegrad- und Rang-Gewicht, weiche Chance-Strafe). Die Zielebene, die zuerst geschuetzt
    wird, ist damit dieselbe, die die Zielfunktion und die
    Hausmatrix-Offenlegung ausweisen -- kein zweites Mass.

    ``with_per_path``: zusaetzlich ein Vektor ``y_n`` je Pfad, dessen
    Streuung die Monte-Carlo-Unschaerfe von G1 traegt (fuer die
    Erosionstoleranz): ``y_n = sum_g (h_g * g_g * s_g,n^2 + V_g^2 * (1 -
    erfolg_g,n))`` -- der Fehlbetragsteil exakt, der Strafteil linearisiert
    (dC/dp = -V^2, ohne die Wilson-Kruemmung). Gepaarte Differenzen zweier
    Allokationen auf DEMSELBEN Wuerfel ergeben den Standardfehler ihres
    Zielebenen-Unterschieds.
    """
    liability_list = [
        liab for liab in liabilities
        if is_protected_goal(liab, n_wealth_columns=wealth_paths.shape[1])
    ]
    n_paths = wealth_paths.shape[0]
    if not liability_list or n_paths <= 0:
        return 0.0, (np.zeros(max(0, n_paths)) if with_per_path else None)
    scale = _context_scale_rappen(initial_wealth_rappen)
    level = shortfall_objective(
        liability_list, wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
        goal_weighting_mode=goal_weighting_mode,
    )
    per_path = np.zeros(n_paths, dtype=np.float64) if with_per_path else None
    for liab in liability_list:
        h_weight = _goal_hardness_weight(liab, goal_weighting_mode)
        chance, _rows = chance_constraint_penalty(
            wealth_paths, [liab], int(initial_wealth_rappen),
            weights=weights,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
        )
        level += float(chance)
        if per_path is None:
            continue
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        shortfall = shortfall_squared_per_path(
            liab, wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            normalization_scale_rappen=scale,
        )
        success = _goal_probability_core(
            wealth_paths, liab, int(initial_wealth_rappen),
            annualized_return_bps_per_path=annualized_return_bps_per_path,
        ).astype(np.float64)
        volume = goal_volume_rappen(
            liab, initial_value_rappen=initial_wealth_rappen,
            n_wealth_columns=wealth_paths.shape[1],
        ) / scale
        per_path += h_weight * g_weight * shortfall + volume * volume * (1.0 - success)
    return float(level), per_path


def monte_carlo_standard_error(
    per_path: np.ndarray, weights: np.ndarray | None = None,
) -> float:
    """Standardfehler des (gewichteten) Mittels eines Pfadvektors.

    Bei Importance Sampling: gewichtete Varianz / Kish-ESS.
    """
    values = np.asarray(per_path, dtype=np.float64).reshape(-1)
    if values.size == 0:
        return 0.0
    if weights is None:
        mean = float(np.mean(values))
        variance = float(np.mean((values - mean) ** 2))
        n_eff = float(values.size)
    else:
        w = np.asarray(weights, dtype=np.float64).reshape(-1)
        w_sum = float(np.sum(w))
        mean = float(np.sum(values * w) / w_sum)
        variance = float(np.sum(w * (values - mean) ** 2) / w_sum)
        n_eff = float(effective_sample_size(w))
    return float(np.sqrt(max(0.0, variance) / max(1.0, n_eff)))


# Breite der logistischen Glaettung des Erfolgsindikators in der Stufe-1-
# SUCHE (Anteil des Zielvolumens). Reine Numerik: der stueckweise konstante
# Indikator hat fuer Gradientenverfahren keinen Gradienten; entschieden wird
# immer mit dem EXAKTEN G1 (Codex-Empfehlung "glatte Surrogate mit finaler
# exakter Pruefung").
STAGE1_SURROGATE_WIDTH = 0.02


def _success_margin_per_path(
    goal: GoalLiability,
    wealth_paths: np.ndarray,
    initial_value_rappen: float,
    annualized_return_bps_per_path: np.ndarray | None,
) -> np.ndarray | None:
    """Relativer Erfolgsabstand je Pfad (> 0 = erreicht), wie
    ``_goal_probability_core``; None, wenn das Ziel immer als erreicht gilt."""
    n_cols = wealth_paths.shape[1]
    if goal.target_kind == "wealth_at_t":
        idx = max(1, min(int(goal.target_year_index), n_cols - 1))
        target = max(1.0, float(goal.target_amount_rappen or 0))
        return (wealth_paths[:, idx] - target) / target
    if goal.target_kind in ("cashflow_in_year", "outflow_stream"):
        due = _positive_due_wealth_indices(goal, n_wealth_columns=n_cols)
        if due.size == 0:
            return None
        volume = max(1.0, goal_volume_rappen(
            goal, initial_value_rappen=initial_value_rappen, n_wealth_columns=n_cols,
        ))
        return np.min(wealth_paths[:, due], axis=1) / volume
    if goal.target_kind == "return_rate":
        horizon = max(1, min(int(goal.target_year_index or (n_cols - 1)), n_cols - 1))
        target_growth = (1.0 + float(goal.target_amount_rappen or 0) / 10000.0) ** horizon
        if annualized_return_bps_per_path is not None:
            growth = np.power(
                np.maximum(0.0, 1.0 + np.asarray(annualized_return_bps_per_path) / 10000.0),
                horizon,
            )
        else:
            growth = wealth_paths[:, horizon] / max(1.0, float(initial_value_rappen))
        return growth / max(target_growth, 1e-12) - 1.0
    return None


def protected_goal_level_surrogate(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    goal_weighting_mode: str | None = None,
) -> float:
    """Glatte Naeherung von ``protected_goal_level`` fuer die Stufe-1-SUCHE.

    Fehlbetragsteil exakt; im Strafteil ersetzt ``sigmoid(Abstand / Breite)``
    den Erfolgsindikator. Nie fuer Entscheidungen: die Schranke und jede
    Auswahl verwenden das exakte G1.
    """
    liability_list = [
        liab for liab in liabilities
        if is_protected_goal(liab, n_wealth_columns=wealth_paths.shape[1])
    ]
    n_paths = wealth_paths.shape[0]
    if not liability_list or n_paths <= 0:
        return 0.0
    level = shortfall_objective(
        liability_list, wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
        goal_weighting_mode=goal_weighting_mode,
    )
    scale = _context_scale_rappen(initial_wealth_rappen)
    if weights is None:
        w = None
        n_eff = float(n_paths)
    else:
        w = np.asarray(weights, dtype=np.float64).reshape(-1)
        n_eff = float(effective_sample_size(w))
    for liab in liability_list:
        margin = _success_margin_per_path(
            liab, wealth_paths, initial_wealth_rappen, annualized_return_bps_per_path,
        )
        if margin is None:
            continue
        smooth = 0.5 * (1.0 + np.tanh(0.5 * margin / STAGE1_SURROGATE_WIDTH))
        p_smooth = float(np.mean(smooth)) if w is None else float(np.sum(smooth * w) / np.sum(w))
        tau = _default_tau_x100(liab) / 10000.0
        deficit = max(0.0, tau - wilson_lower_bound(p_smooth, n_eff))
        volume = goal_volume_rappen(
            liab, initial_value_rappen=initial_wealth_rappen,
            n_wealth_columns=wealth_paths.shape[1],
        ) / scale
        level += CHANCE_PENALTY_WEIGHT * deficit * volume * volume
    return float(level)
