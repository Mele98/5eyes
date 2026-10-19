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
5. Hausmatrix (seit HOUSE-PRIOR-001, Engine ``saa_resampled_v6``):
   im Default-Modus ``goal_shortfall`` ist die (auf Zulaessigkeit
   projizierte) Hausmatrix-Zielquote ein PRIOR in der Zielfunktion jedes
   Bags (``house_prior.py``: ``kappa_H * (w - w_H)' Sigma (w - w_H)`` statt
   des Tiebreaks ``w' Sigma w``); das projizierte Bag-Mittel ist das
   Ergebnis, ohne Schalter. Der gepaarte Bootstrap auf dem UNABHAENGIGEN
   Validierungswuerfel legt nur offen (Delta Zielebene, Konfidenzgrenzen,
   Zielwahrscheinlichkeiten Haus vs. Ergebnis) und ist Sicherheitsnetz: ist
   das Ergebnis auf der Zielebene signifikant SCHLECHTER als die Hausquote,
   gilt die Hausquote.
   In den Risikomass-Varianten und ohne projizierbaren Anker gilt weiter
   die v5-Regel (HOUSE-FIRST-SIGNIFICANCE-001): Signifikanztest gegen die
   Hausmatrix auf der Zielebene, in den Varianten zusaetzlich auf dem
   Risikomass mit Materialitaetsschwelle; ist die Verbesserung nicht
   signifikant (bzw. nicht material), bleibt die Hausmatrix-Zielquote stehen.

Wahl des Tests: Die Zielfunktion ist KEIN Mittelwert pfadweiser Verluste --
die Chance-Constraint-Strafe ist eine quadratische Funktion der
Wilson-Untergrenze einer Erfolgsquote. Ein gepaarter t-Test auf
pfadweisen Verlustdifferenzen ist daher nicht definiert. Verwendet wird ein
gepaarter Bootstrap: dieselben gezogenen Pfadindizes werden fuer beide
Allokationen verwendet, die Zielfunktion auf jeder Replikation vollstaendig
neu ausgewertet.

Engine ``saa_resampled_v7`` (Codex-Review 2026-10-18):

* Stichprobeneinheit (RESAMPLING-ANTITHETIC-BOOTSTRAP-001): die
  Validierungswuerfel sind antithetisch; Pfad ``i`` und ``i + ceil(n/2)``
  stammen aus derselben Ziehung und sind EINE Einheit. Gezogen werden
  Einheiten mit beiden Partnern (``unit_block_bootstrap``), nicht Zeilen --
  sonst zaehlen ``2m`` abhaengige Pfade als ``2m`` unabhaengige und die
  Streuung wird unterschaetzt (Codex-Gegenfall: Zeilen p = 0.037
  "signifikant", Paare 0.087 bzw. nullzentriert 0.072).
* p-Wert (RESAMPLING-PVALUE-SEMANTICS-001): ``p_value`` ist der einseitige
  p-Wert zu H0 ``Delta <= 0`` aus der nullzentrierten Bootstrap-Verteilung
  (Hall & Wilson 1991); der rohe Vorzeichenanteil der unzentrierten
  Verteilung heisst ``bootstrap_tail_fraction`` und entscheidet nichts.
  Signifikant genau dann, wenn ``Delta_hat > 0`` UND ``p_value <= alpha``
  (dual zur einseitigen Basic-Bootstrap-Untergrenze > 0). Groesse unter H0
  simuliert (``tests/test_resampling_statistics_contracts.py``).
* Survivor-Schwelle (RESAMPLING-SUCCESS-SURVIVOR-BIAS-001): mindestens 90 %
  erfolgreiche Bags, sonst fail-closed (Herleitung bei
  ``MIN_SUCCESSFUL_BAG_SHARE``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .importance_sampling import IS_TOTAL_SHIFT_SIGMA, ess_requires_fallback
from .scenario_engine import (
    N_BUCKETS,
    SAMPLING_UNIT_ANTITHETIC_PAIR,
    ScenarioInputs,
    build_scenario_paths,
    build_scenario_paths_with_weights,
    sampling_unit_ids as sampling_unit_ids_for,
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
# definiert. SIGNIFICANCE-SCALAR-ONLY-001 (2026-10-18): die Zwei-Stufen-
# Logik (``lexicographic_improvement``) ist entfernt; Tupel-Verluste werden
# wie im Solver summiert (``scalar_loss``).
# v4 (HOUSE-FIRST-SIGNIFICANCE-001, 2026-10-18, CIO-Entscheid "Hausmatrix,
# solange die Ziele mit ihr gleich sicher erreicht sind"): der Entscheid
# Anker vs. Kandidat faellt auf der ZIELEBENE (Ziel-Fehlbetrag +
# Chance-Strafe + Soft-Preference), nicht mehr auf dem Skalar inklusive
# Volatilitaets-Tiebreak. Der Tiebreak ist deterministisch; auf Mandaten mit
# sicher erreichten Zielen war jede Varianzdifferenz "signifikant"
# (p = 1/(B+1) = 0.0025) und die Hausmatrix verlor gegen Eckloesungen mit
# 2-7 bps weniger Volatilitaet. In den Risikomass-Varianten entscheidet
# zusaetzlich der Skalar (Risikomass + Chance-Strafe), aber nur mit
# Materialitaet (``RISK_MEASURE_MATERIALITY``).
#
# Engine v6 (HOUSE-PRIOR-001, 2026-10-18): dieser Test entscheidet nur noch in
# den Risikomass-Varianten (und ohne projizierbaren Anker); dort ist er
# mathematisch unveraendert und behaelt deshalb seine Version. Im Default
# ersetzt ihn die Offenlegung ``house_prior.HOUSE_PRIOR_DISCLOSURE_TEST_VERSION``
# (``paired_bootstrap_disclosure_goal_level_v5``).
#
# v5 (RESAMPLING-ANTITHETIC-BOOTSTRAP-001 + RESAMPLING-PVALUE-SEMANTICS-001,
# Engine saa_resampled_v7): gezogen werden unabhaengige Stichprobeneinheiten
# (antithetische Pfadpaare) statt Zeilen; ``p_value`` ist der nullzentrierte
# einseitige Shift-Bootstrap-p-Wert mit expliziter Nullhypothese, der rohe
# Vorzeichenanteil heisst ``bootstrap_tail_fraction``.
SIGNIFICANCE_TEST_VERSION = "paired_unit_bootstrap_one_sided_goal_level_v5"
BOOTSTRAP_METHOD_VERSION = "paired_unit_block_bootstrap_v1"
P_VALUE_CALIBRATION = "null_centered_shift_bootstrap_hall_wilson_1991_v1"
NULL_HYPOTHESIS_NOT_BETTER = (
    "H0: E[L(anker) - L(kandidat)] <= 0 (Kandidat nicht besser als der Anker)"
)
NULL_HYPOTHESIS_NOT_WORSE = (
    "H0: E[L(anker) - L(kandidat)] >= 0 (Kandidat nicht schlechter als der Anker)"
)
COMPARISON_SCALAR = "scalar"
COMPARISON_GOAL_LEVEL = "goal_level"
COMPARISON_RISK_MEASURE = "goal_level_plus_risk_measure"

# Materialitaetsschwelle der Risikomass-Varianten (HOUSE-FIRST-SIGNIFICANCE-001):
# 50 bps auf dem Risikomass selbst (alle Varianten sind Renditeanteile:
# Einperioden-Vola, mittlerer verfeinerter Max-Drawdown, Expected Shortfall
# bzw. negative erwartete Rendite p.a.). Begruendung, Herleitung in
# docs/planning/2026-10-18-importance-sampling-ess.md (Abschnitt
# HOUSE-FIRST-SIGNIFICANCE-001):
# * Schaetzfehler der Inputs: die relative Standardabweichung einer
#   Vola-Schaetzung aus 20 Jahren Monatsdaten ist ~1/sqrt(2*240) = 4.6 %, bei
#   8-12 % Portfolio-Vola also 35-55 bps. Kleinere Unterschiede sind von den
#   CMA-Schaetzfehlern nicht unterscheidbar -- sie zu optimieren hiesse,
#   Schaetzfehler zu optimieren (Michaud). Fuer Drawdown (~2-3x Vola) und
#   erwartete Rendite (Standardfehler ~ sigma/sqrt(T), mehrere Prozentpunkte)
#   ist dieselbe Schwelle relativ noch nachsichtiger.
# * Die SAA wird in ganzen Prozent kommuniziert; eine Abweichung von der
#   Hausmeinung (IC) braucht einen Effekt, den man dem Kunden in derselben
#   Granularitaet zeigen kann.
# * Gemessen: die verworfenen Eckloesungen brachten 2-7 bps Vola -- eine bis
#   zwei Groessenordnungen unter der Schwelle.
RISK_MEASURE_MATERIALITY = 0.005

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
# RESAMPLING-SUCCESS-SURVIVOR-BIAS-001 (Engine saa_resampled_v7): Mindestanteil
# erfolgreicher Bags. Mittel und Streuung stammen nur aus den erfolgreichen
# Bags; das ist unverzerrt nur, wenn ein Bag-Ausfall vom Wuerfel unabhaengig
# ist (MCAR) -- unbelegt: adverse Wuerfel koennen systematisch scheitern.
# Herleitung der Schwelle (Sensitivitaetsschranke statt MCAR-Annahme):
#
#   Bias je Bucket = f * (mu_fehlend - mu_erfolgreich),  f = Ausfallanteil.
#
# Stressannahme: die fehlenden Bags liegen um bis zu 2 Bag-Standard-
# abweichungen neben dem Mittel der erfolgreichen (|delta| <= 2 sigma_bag;
# ein fehlender Bag ist "so extrem wie ein 2-sigma-Bag"). Gemessen
# sigma_bag ~ 4-5 pp (Fundament-Mandat, 500 Pfade, siehe oben) -> 2 sigma
# ~ 10 pp. Das Praezisionsziel der publizierten Quote ist 1 pp (Standard-
# fehler-Ziel, dafuer 40 Bags). Bias <= 1 pp verlangt f <= 1 pp / 10 pp = 10 %:
# mindestens 90 % erfolgreiche Bags (36 von 40). Darunter kann der Ausfall
# allein die Quote um mehr als ihr Praezisionsziel verschieben -> fail-closed
# (kontrollierter House-Fallback, kein Mittel publiziert). Die Schranke wird
# je Lauf mit der GEMESSENEN Streuung ausgewiesen
# (``missingness_sensitivity_bps`` = f * 2 * sigma_bag je Bucket).
# Outcomes bei 40 Bags: 40/40, 39/40, 36/40 -> Mittel; 35/40, 30/40, 20/40,
# 19/40 -> House-Fallback. Bis v6 reichten 20/40.
MIN_SUCCESSFUL_BAG_SHARE = 0.9
MISSINGNESS_STRESS_SIGMAS = 2.0
DEFAULT_SIGNIFICANCE_ALPHA = 0.05
# Engine v7 (RESAMPLING-PVALUE-SEMANTICS-001): B = 999 statt 400.
# * alpha (B + 1) = 50 ist ganzzahlig -> der (1 + k)/(B + 1)-Test haelt das
#   Niveau exakt (Davison & Hinkley 1997, Abschn. 4.2.5); bei B = 400 war
#   alpha (B + 1) = 20.05.
# * Monte-Carlo-Fehler des p-Werts an der Grenze alpha = 5 %:
#   sqrt(alpha (1 - alpha) / B) = 0.0069 (B = 400: 0.0109).
# * Laufzeit gemessen +0.08 s je Lauf (Mandat D: Bootstrap 0.06 s -> 0.14 s
#   bei 5.5-6.1 s Gesamtlauf).
DEFAULT_N_BOOTSTRAP = 999

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


def scalar_loss(loss) -> float:
    """Skalar-Zielfunktion eines Verlusts -- dieselbe, die der Solver minimiert.

    Ein Skalar wird unveraendert uebernommen. Ein Tupel
    ``(goal_level, tiebreak[, additiv])`` (Terme aus
    ``objective.two_phase_objective_parts`` plus optional Soft-Preference)
    wird SUMMIERT -- ohne Stufen-Schalter.

    SIGNIFICANCE-SCALAR-ONLY-001 (2026-10-18): hier stand bis dahin die
    Zwei-Stufen-Logik von SAA-SIGNIFICANCE-LEXICOGRAPHIC-001
    (``lexicographic_improvement`` und ``_objective_scalar``: Tiebreak nur,
    wenn die Ziel-Stufe < 1e-12). Seit OBJECTIVE-NORMALIZATION-001 ist der
    Tiebreak im Solver IMMER aktiv; ein Tupel-Verlust wurde hier also nach
    einer ANDEREN Ordnung bewertet als die, nach der optimiert wird. Kein
    Produktionspfad lieferte noch Tupel -- der Code war latent defekt und ist
    entfernt. Ungueltige Formen werden abgelehnt.
    """
    if isinstance(loss, (tuple, list)):
        if len(loss) not in (2, 3):
            raise TypeError(
                "Tupel-Verlust muss (goal_level, tiebreak[, additiv]) sein."
            )
        return float(sum(float(term) for term in loss))
    return float(loss)


def scalar_improvement(anchor, candidate) -> tuple[float, str]:
    """``L(anker) - L(kandidat)`` der Skalar-Zielfunktion (Ebene ``scalar``)."""
    if isinstance(anchor, (tuple, list)) != isinstance(candidate, (tuple, list)):
        raise TypeError("Anker und Kandidat muessen dieselbe Verlustform haben.")
    return scalar_loss(anchor) - scalar_loss(candidate), COMPARISON_SCALAR


def bootstrap_unit_index_matrix(sampling_unit_ids: np.ndarray) -> np.ndarray:
    """Mitglieder je Stichprobeneinheit als (n_units, max_members)-Matrix.

    Einheiten in aufsteigender ID-Reihenfolge, Mitglieder in Pfadreihenfolge,
    aufgefuellt mit -1 (z.B. die Einzel-Einheit einer ungeraden
    antithetischen Pfadzahl).
    """
    ids = np.asarray(sampling_unit_ids, dtype=np.int64).reshape(-1)
    if ids.size == 0:
        raise ValueError("sampling_unit_ids ist leer.")
    units, inverse = np.unique(ids, return_inverse=True)
    counts = np.bincount(inverse, minlength=units.size)
    matrix = np.full((units.size, int(counts.max())), -1, dtype=np.int64)
    fill = np.zeros(units.size, dtype=np.int64)
    for path, unit in enumerate(inverse):
        matrix[unit, fill[unit]] = path
        fill[unit] += 1
    return matrix


def sampling_unit_hash(sampling_unit_ids: np.ndarray) -> str:
    """Bindung der Einheiten-Zuordnung (Replay/Modellbasis)."""
    ids = np.ascontiguousarray(np.asarray(sampling_unit_ids, dtype=np.int64))
    return hashlib.sha256(ids.tobytes()).hexdigest()


def _resolve_sampling_units(
    n_paths: int,
    sampling_unit_ids: np.ndarray | None,
    sampling_unit: str | None,
) -> tuple[np.ndarray, str]:
    """Default: Layout des antithetischen Wuerfels (``build_scenario_paths``).

    Alle Validierungswuerfel der Engine sind antithetisch; fehlt die explizite
    Zuordnung, ist die Paar-Einheit die konservative Annahme (bei
    unabhaengigen Pfaden kostet sie nur Effizienz, nie Ueberdeckung).
    """
    if sampling_unit_ids is None:
        return (
            sampling_unit_ids_for(int(n_paths), antithetic=True),
            SAMPLING_UNIT_ANTITHETIC_PAIR,
        )
    ids = np.asarray(sampling_unit_ids, dtype=np.int64).reshape(-1)
    if ids.size != int(n_paths):
        raise ValueError(
            f"sampling_unit_ids hat {ids.size} Eintraege, erwartet {int(n_paths)}."
        )
    return ids, str(sampling_unit or "custom")


def unit_block_bootstrap(
    statistic: Callable[[np.ndarray | None], float],
    *,
    n_paths: int,
    n_bootstrap: int,
    seed: int,
    sampling_unit_ids: np.ndarray | None = None,
    sampling_unit: str | None = None,
) -> tuple[float, np.ndarray, dict]:
    """Bootstrap ueber unabhaengige Stichprobeneinheiten (Paar-/Blockbootstrap).

    Je Replikation werden ``m = n_units`` Einheiten mit Zuruecklegen gezogen
    und ALLE Mitglieder jeder gezogenen Einheit gemeinsam an ``statistic``
    uebergeben (antithetische Partner also immer zusammen und gleich oft).
    Bei Einzelpfad-Einheiten ist das exakt der bisherige Zeilen-Bootstrap
    (identischer RNG-Strom). Bei ungerader antithetischer Pfadzahl ist der
    partnerlose Basispfad eine eigene Einheit; die Replikationsgroesse
    schwankt dann um hoechstens die Anzahl seiner Ziehungen (Erwartung
    exakt ``n_paths``).

    Returns ``(statistic(None), replikationen, metadaten)``.
    """
    unit_ids, unit_name = _resolve_sampling_units(
        n_paths, sampling_unit_ids, sampling_unit,
    )
    members = bootstrap_unit_index_matrix(unit_ids)
    n_units = int(members.shape[0])
    full = float(statistic(None))
    rng = np.random.default_rng(int(seed))
    replicates = np.empty(int(n_bootstrap), dtype=np.float64)
    single_member = members.shape[1] == 1
    for b in range(int(n_bootstrap)):
        draws = rng.integers(0, n_units, size=n_units)
        if single_member:
            idx = members[draws, 0]
        else:
            idx = members[draws].reshape(-1)
            idx = idx[idx >= 0]
        replicates[b] = float(statistic(idx))
    meta = {
        "bootstrap_method": BOOTSTRAP_METHOD_VERSION,
        "sampling_unit": unit_name,
        "n_independent_units": n_units,
        "sampling_unit_hash": sampling_unit_hash(unit_ids),
    }
    return full, replicates, meta


def null_centered_p_value(
    estimate: float,
    replicates: np.ndarray,
    *,
    alternative: str,
) -> float:
    """Einseitiger p-Wert des Shift-Bootstraps (Hall & Wilson 1991).

    Die Verteilung der Schaetzung am Rand von H0 (Delta = 0) wird durch die
    zentrierte Bootstrap-Verteilung ``Delta* - Delta_hat`` approximiert
    (Hall & Wilson 1991, Guideline 1: resample unter der Nullhypothese):

    * ``alternative="greater"`` (H0: Delta <= 0):
      ``p = (1 + #{Delta*_b - Delta_hat >= Delta_hat}) / (B + 1)``
    * ``alternative="less"`` (H0: Delta >= 0):
      ``p = (1 + #{Delta*_b - Delta_hat <= Delta_hat}) / (B + 1)``

    ``(1 + k)/(B + 1)`` (Davison & Hinkley 1997, Gl. 4.11) -- nie 0. Dual zur
    einseitigen Basic-Bootstrap-Grenze ``2 Delta_hat - q_{1-alpha}``. Die
    Groesse unter H0 (<= alpha) ist in
    ``tests/test_resampling_statistics_contracts.py`` simuliert.
    """
    finite = np.asarray(replicates, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    centered = finite - float(estimate)
    if alternative == "greater":
        hits = int(np.count_nonzero(centered >= float(estimate)))
    elif alternative == "less":
        hits = int(np.count_nonzero(centered <= float(estimate)))
    else:
        raise ValueError(f"Unbekannte Alternative: {alternative!r}")
    return (1.0 + hits) / (1.0 + float(finite.size))


def tail_fraction(replicates: np.ndarray, *, not_better: bool) -> float:
    """Geglaetteter Bootstrap-Vorzeichenanteil -- KEIN p-Wert.

    ``not_better``: ``(1 + #{Delta* <= 0}) / (B + 1)``, sonst
    ``(1 + #{Delta* >= 0}) / (B + 1)``. Aus der UNZENTRIERTEN
    Bootstrap-Verteilung; als Stabilitaetskennzahl offengelegt
    (RESAMPLING-PVALUE-SEMANTICS-001), nicht als Testentscheid.
    """
    finite = np.asarray(replicates, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not_better:
        hits = np.count_nonzero(finite <= 0.0)
    else:
        hits = np.count_nonzero(finite >= 0.0)
    return (1.0 + float(hits)) / (1.0 + float(finite.size))


def paired_bootstrap_improvement(
    loss_pair: Callable[[np.ndarray | None], tuple],
    *,
    n_paths: int,
    n_bootstrap: int,
    alpha: float,
    seed: int,
    sampling_unit_ids: np.ndarray | None = None,
    sampling_unit: str | None = None,
) -> dict:
    """Gepaarter, einseitiger Einheiten-Bootstrap der Verbesserung
    ``Delta = L(anker) - L(kandidat)``.

    ``loss_pair(idx)`` liefert ``(L_anker, L_kandidat)`` auf der Pfadauswahl
    ``idx`` (None = alle Pfade). Beide Verluste werden auf DENSELBEN Indizes
    ausgewertet -- das ist die Paarung Anker/Kandidat. Gezogen werden
    unabhaengige Stichprobeneinheiten (``unit_block_bootstrap``; Default:
    antithetische Pfadpaare), nicht Zeilen.

    Ausgewiesen (RESAMPLING-PVALUE-SEMANTICS-001, nicht vermischt):

    * ``p_value`` -- einseitiger p-Wert zu ``null_hypothesis`` (H0: Delta <= 0)
      aus der nullzentrierten Bootstrap-Verteilung
      (``p_value_calibration``, ``null_centered_p_value``).
    * ``improvement_lower_bound`` -- dazu duale einseitige
      (1-alpha)-Basic-Bootstrap-Untergrenze ``2 Delta_hat - q_{1-alpha}``.
    * ``bootstrap_tail_fraction`` -- roher Vorzeichenanteil
      ``(1 + #{Delta* <= 0})/(B + 1)``; nur Stabilitaetskennzahl.

    Entscheid: signifikant genau dann, wenn ``Delta_hat > 0`` UND
    ``p_value <= alpha``.

    ``loss_pair`` darf Skalare oder ``(goal_level, tiebreak[, additiv])``-
    Tupel liefern; Tupel werden wie im Solver summiert (``scalar_loss``).
    """
    levels: dict[str, int] = {}
    full_pair: dict = {}

    def _improvement(idx):
        anchor, candidate = loss_pair(idx)
        value, level = scalar_improvement(anchor, candidate)
        if idx is None:
            full_pair["anchor"], full_pair["candidate"] = anchor, candidate
            full_pair["comparison"] = level
        else:
            levels[level] = levels.get(level, 0) + 1
        return value

    improvement, replicates, unit_meta = unit_block_bootstrap(
        _improvement,
        n_paths=n_paths,
        n_bootstrap=n_bootstrap,
        seed=seed,
        sampling_unit_ids=sampling_unit_ids,
        sampling_unit=sampling_unit,
    )
    finite = replicates[np.isfinite(replicates)]
    block = {
        "test": SIGNIFICANCE_TEST_VERSION,
        **unit_meta,
        "n_bootstrap": int(n_bootstrap),
        "alpha": float(alpha),
        "anchor_objective": _objective_scalar(full_pair["anchor"]),
        "candidate_objective": _objective_scalar(full_pair["candidate"]),
        "comparison": full_pair["comparison"],
        "replicate_comparisons": dict(sorted(levels.items())),
        "improvement": float(improvement),
        "null_hypothesis": NULL_HYPOTHESIS_NOT_BETTER,
        "p_value_calibration": P_VALUE_CALIBRATION,
    }
    if finite.size == 0 or not np.isfinite(improvement):
        return {
            **block,
            "improvement_lower_bound": None,
            "bootstrap_tail_fraction": None,
            "p_value": None,
            "significant": False,
        }
    p_value = null_centered_p_value(improvement, finite, alternative="greater")
    lower = (
        float(2.0 * improvement - np.quantile(finite, 1.0 - float(alpha)))
        if len(levels) == 1
        else None
    )
    return {
        **block,
        "improvement_lower_bound": lower,
        "bootstrap_tail_fraction": float(tail_fraction(finite, not_better=True)),
        "p_value": float(p_value),
        "significant": bool(improvement > 0.0 and p_value <= float(alpha)),
    }


def _objective_scalar(loss) -> float:
    """Skalar-Zielfunktion fuer den Audit (= ``scalar_loss``)."""
    return scalar_loss(loss)


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
    # RESAMPLING-SUCCESS-SURVIVOR-BIAS-001: der Standardfehler ist bedingt auf
    # die erfolgreichen Bags (Name sagt den Scope); Mindestquote und
    # Ausfall-Sensitivitaet gehoeren zur Entscheidungsbasis.
    "conditional_bag_mean_standard_error_bps",
    "min_successful_bag_share",
    "missingness_sensitivity_bps",
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
    # HOUSE-FIRST-SIGNIFICANCE-001: Entscheidungsebene und (nur Varianten)
    # die Risikomass-Statistik mit Materialitaet.
    "decision_level",
    "risk_measure_test",
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001: nur im Modus max_drawdown gesetzt
    # ("refined_brownian_bridge"); sonst fehlt der Schluessel und die
    # Modellbasis bleibt bit-gleich.
    "drawdown_measure",
    # RESAMPLING-ANTITHETIC-BOOTSTRAP-001 / RESAMPLING-PVALUE-SEMANTICS-001:
    # Stichprobeneinheit, Methode und p-Wert-Vertrag sind replaybar gebunden.
    "bootstrap_method",
    "sampling_unit",
    "n_independent_units",
    "sampling_unit_hash",
    "null_hypothesis",
    "p_value_calibration",
    "p_value",
    "bootstrap_tail_fraction",
    "significant",
    # DRAWDOWN-HOLDOUT-REUSE-001: Rolle des Wuerfels (immer der finale
    # Holdout) und -- nur max_drawdown -- der getrennte Auswahl-Wuerfel.
    "cube_role",
    "selection_seed",
    "selection_cube_hash",
    "validation_seed",
    "validation_cube_hash",
    "validation_n_paths",
    "decision",
    "reason",
)


# HOUSE-PRIOR-001 (Engine v6): Prior-Audit des Default-Modus. Alles
# deterministisch (Inhalts-Seed); kappa und Version gehoeren in die
# Modellbasis, weil sie die Allokation bestimmen.
_HOUSE_PRIOR_BASIS_FIELDS = (
    "version",
    "kappa",
    "house_anchor_bps",
    "house_anchor_projected_bps",
    "candidate_bps",
    "candidate_tracking_error_vs_house_bps",
    "final_bps",
    "tracking_error_vs_house_bps",
    "final_prior_penalty",
    # HOUSE-PRIOR-PSD-NULLSPACE-001: Ridge der Prior-Metrik (Sigma + eps I).
    "prior_metric",
    "disclosure",
    "goal_probabilities",
    "cube_role",
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
    house_prior = resampling.get("house_prior")
    if isinstance(house_prior, dict):
        basis["house_prior"] = {
            key: house_prior[key]
            for key in _HOUSE_PRIOR_BASIS_FIELDS
            if key in house_prior
        }
    return basis
