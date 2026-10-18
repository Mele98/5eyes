"""HOUSE-PRIOR-001 (CIO-Entscheid 2026-10-18, Engine ``saa_resampled_v6``):
Hausmatrix als Prior IM Optimierer statt binaerem Signifikanzschalter.

Befund (Design + Experiment: docs/planning/2026-10-18-house-prior-v6.md):
der House-First-Signifikanztest der Engine v5 kannte nur zwei Ergebnisse --
Hausquote ODER Optimierer-Kandidat. Bei +1 % Zielbetrag sprang die
publizierte Allokation um bis zu 20.9 pp Turnover (auch mit festem Seed
17.3 pp, also strukturell und nicht nur Monte-Carlo-Rauschen); ueber Seeds
streute die Aktienquote bis 7.4 pp. Der Bootstrap misst ausserdem nur das
MC-Rauschen bei FESTER CMA, nicht deren Schaetzfehler -- gerade der ist der
Grund, die Hausmeinung zu bevorzugen.

Formel (je Bag ``b``, Default ``goal_shortfall``)::

    w_b = argmin_{w in W}  G_b(w) + P_pref(w) + kappa_H * (w - w_H)' Sigma (w - w_H)
    w   = Pi_W( mean_b w_b ),  danach bps-Rundung + Reparatur

* ``G`` -- Ziel-Fehlbetrag + Chance-Strafe (unveraendert), ``P_pref`` die
  bestehende Soft-Preference.
* ``w_H`` -- die zulaessig projizierte Hausmatrix-Zielquote (derselbe Anker,
  gegen den v5 getestet hat; ``solver._project_house_anchor``).
* ``Sigma`` -- die CMA-Kovarianz des Laufs (``context.scenario_cov_bps2``),
  dieselbe Matrix wie im bisherigen Tiebreak ``kappa * w' Sigma w``, den der
  Prior-Term im Default ERSETZT. Er ist stark konvex (Hesse 2 kappa_H Sigma
  positiv definit) und hat ein eindeutiges Minimum -- er uebernimmt also die
  Aufgabe des Tiebreaks (die Zielfunktion auf Plateaus nicht flach werden
  lassen) vollstaendig.
* Interpretation: eine Abweichung von der Hausmatrix kostet ihren Tracking
  Error. Ein TE von 1 % wird nur genommen, wenn er die Zielebene um
  mindestens ``kappa_H * (1 %)^2 = 0.03`` verbessert. Sind die Ziele mit der
  Hausmatrix sicher erreicht (Gradient von G = 0), ist das Optimum exakt die
  Hausquote -- die CIO-Regel "Hausmatrix, solange die Ziele mit ihr gleich
  sicher erreicht sind" in stetiger Form. Bayes-Lesart: MAP mit
  Gauss-Prior auf die Gewichte (Erwartung w_H, Praezision 2 kappa_H Sigma).

kappa_H = 300 (CIO-Entscheid): bester Wert im Schaetzfehler-Test (Engine
sieht mu_hat = mu + L z / sqrt(20), Bewertung unter der wahren CMA; wahre
Zielwahrscheinlichkeit +1.31 pp gegen v5, se 0.18) und im OOS-Minimum des
kappa-Rasters; 100-1000 sind innerhalb 1 se gleichwertig.

Der gepaarte Bootstrap bleibt NUR zur Offenlegung (Delta Zielebene mit
Konfidenzgrenzen, Zielwahrscheinlichkeiten Haus vs. Final) und als
Sicherheitsnetz: ist das Ergebnis auf der Zielebene einseitig signifikant
SCHLECHTER als die Hausquote (gleiches alpha), wird die Hausquote publiziert
(``DECISION_HOUSE_PRIOR_GUARD``). Er ist bewusst unstetig, weil er nur
Ausreisser abfangen soll; gegen CMA-Fehler schuetzt er nicht (er bewertet
unter derselben CMA).

Risikomass-Varianten (min_volatility, max_drawdown, cvar_return,
max_return) bleiben in Phase 1 bei der v5-Regel (Signifikanz + 50 bps
Materialitaet): dort gibt es keinen w'Sigma w-Tiebreak, und ein additiver
Prior braucht eine eigene Kalibrierung gegen das Risikomass.

Dieses Modul enthaelt nur reine Funktionen (keine Abhaengigkeit auf den
Solver); die Verdrahtung liegt in ``solver._run_resampled_solver``.
"""
from __future__ import annotations

import math
from typing import Callable, Mapping

import numpy as np

from .objective import portfolio_variance_one_year

HOUSE_PRIOR_VERSION = "house_prior_tracking_error_v1"
# CIO-Entscheid 2026-10-18 (HOUSE-PRIOR-001). Versioniert ueber
# ``HOUSE_PRIOR_VERSION`` und die Engine-Version; im Audit und in der
# Modellbasis ausgewiesen. Einheit: Zielebene je Tracking-Error-Varianz
# (Dezimal^2, einjaehrig).
HOUSE_PRIOR_KAPPA = 300.0
HOUSE_PRIOR_DISCLOSURE_TEST_VERSION = "paired_bootstrap_disclosure_goal_level_v5"

DECISION_HOUSE_PRIOR = "house_prior"
DECISION_HOUSE_PRIOR_GUARD = "house_prior_guard"

REASON_IDENTICAL = "identical_to_house_anchor"
REASON_NOT_WORSE = "not_significantly_worse_than_house"
REASON_GUARD = "significantly_worse_than_house"
REASON_TEST_DISABLED = "disclosure_disabled"
REASON_NO_VALIDATION = "no_validation_cube"


def house_prior_penalty(
    weights: np.ndarray,
    house_weights: np.ndarray,
    covariance_bps2: np.ndarray,
    *,
    kappa: float = HOUSE_PRIOR_KAPPA,
) -> float:
    """``kappa_H * (w - w_H)' Sigma (w - w_H)`` (Sigma in bps^2)."""
    delta = (
        np.asarray(weights, dtype=np.float64).reshape(-1)
        - np.asarray(house_weights, dtype=np.float64).reshape(-1)
    )
    return float(kappa) * portfolio_variance_one_year(delta, covariance_bps2)


def tracking_error_bps(
    weights: np.ndarray,
    house_weights: np.ndarray,
    covariance_bps2: np.ndarray,
) -> float:
    """Einjaehriger Tracking Error zur Hausquote in bps (CMA-Kovarianz)."""
    delta = (
        np.asarray(weights, dtype=np.float64).reshape(-1)
        - np.asarray(house_weights, dtype=np.float64).reshape(-1)
    )
    variance = max(0.0, portfolio_variance_one_year(delta, covariance_bps2))
    return float(math.sqrt(variance) * 10000.0)


def paired_bootstrap_disclosure(
    loss_pair: Callable[[np.ndarray | None], tuple[float, float]],
    *,
    n_paths: int,
    n_bootstrap: int,
    alpha: float,
    seed: int,
) -> dict:
    """Gepaarter Bootstrap von ``Delta = L(Haus) - L(Final)`` (Zielebene).

    ``Delta > 0``: das Ergebnis erreicht die Ziele besser als die Hausquote.
    Ein Lauf liefert beide einseitigen p-Werte aus DENSELBEN Replikationen
    (``(1 + k) / (1 + B)``, nie 0):

    * ``p_value_better`` -- Anteil ohne Verbesserung (Offenlegung),
    * ``p_value_worse``  -- Anteil ohne Verschlechterung; ``significantly_worse``
      (Sicherheitsnetz) genau dann, wenn ``Delta < 0`` UND ``p_value_worse <=
      alpha`` (dieselbe Regel wie der v5-Test, mit vertauschten Rollen).

    Konfidenzgrenzen: alpha- und (1-alpha)-Quantil der Replikationen.
    """
    house_full, final_full = loss_pair(None)
    improvement = float(house_full) - float(final_full)
    rng = np.random.default_rng(int(seed))
    replicates = np.empty(int(n_bootstrap), dtype=np.float64)
    for b in range(int(n_bootstrap)):
        idx = rng.integers(0, int(n_paths), size=int(n_paths))
        house_b, final_b = loss_pair(idx)
        replicates[b] = float(house_b) - float(final_b)
    finite = replicates[np.isfinite(replicates)]
    block = {
        "test": HOUSE_PRIOR_DISCLOSURE_TEST_VERSION,
        "n_bootstrap": int(n_bootstrap),
        "alpha": float(alpha),
        "house_goal_level": float(house_full),
        "final_goal_level": float(final_full),
        "improvement": improvement,
    }
    if finite.size == 0 or not math.isfinite(improvement):
        return {
            **block,
            "improvement_lower_bound": None,
            "improvement_upper_bound": None,
            "p_value_better": None,
            "p_value_worse": None,
            "significantly_worse": False,
        }
    denominator = 1.0 + float(finite.size)
    p_better = (1.0 + float(np.count_nonzero(finite <= 0.0))) / denominator
    p_worse = (1.0 + float(np.count_nonzero(finite >= 0.0))) / denominator
    return {
        **block,
        "improvement_lower_bound": float(np.quantile(finite, float(alpha))),
        "improvement_upper_bound": float(np.quantile(finite, 1.0 - float(alpha))),
        "p_value_better": float(p_better),
        "p_value_worse": float(p_worse),
        "significantly_worse": bool(improvement < 0.0 and p_worse <= float(alpha)),
    }


def goal_probability_rows(
    house_rows: list[Mapping],
    final_rows: list[Mapping],
) -> list[dict]:
    """Zielwahrscheinlichkeit je Ziel (und Plan-Zeile) Haus vs. Final.

    Beide Listen stammen aus ``publish_goal_achievability`` auf DEMSELBEN
    Validierungswuerfel (gleiche Reihenfolge der Ziele)."""
    rows: list[dict] = []
    for house, final in zip(house_rows, final_rows):
        rows.append({
            "goal_id": house.get("goal_id"),
            "label": house.get("label"),
            "evaluation_scope": house.get("evaluation_scope"),
            "probability_house": _probability(house.get("probability")),
            "probability_final": _probability(final.get("probability")),
        })
    return rows


def _probability(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 6) if math.isfinite(number) else None


def house_prior_sentence(block: Mapping) -> str:
    """Reasoning-Satz fuer Kunde und Pruefer (alle Zahlen im Audit)."""
    kappa = float(block.get("kappa") or HOUSE_PRIOR_KAPPA)
    te_bps = float(block.get("tracking_error_vs_house_bps") or 0.0)
    decision = block.get("decision")
    if decision == DECISION_HOUSE_PRIOR_GUARD:
        head = (
            "Hausmatrix-Zielquote publiziert (Sicherheitsnetz): das Ergebnis des "
            "Optimierers mit Hausmatrix-Prior erreicht die Ziele auf dem "
            "unabhaengigen Validierungswuerfel signifikant schlechter als die "
            "Hausmatrix."
        )
    elif te_bps <= 0.0:
        head = (
            "Hausmatrix als Anker des Optimierers (Prior, kappa = "
            f"{kappa:g}): keine Abweichung, weil sie die Zielerreichung nicht "
            "verbessert; Hausmatrix-Zielquote beibehalten."
        )
    else:
        head = (
            "Hausmatrix als Anker des Optimierers (Prior, kappa = "
            f"{kappa:g}): Abweichung nur so weit, wie sie die Zielerreichung "
            f"verbessert (Tracking Error zur Hausmatrix {te_bps / 100.0:.2f} %)."
        )
    parts = [head]
    disclosure = block.get("disclosure")
    if isinstance(disclosure, Mapping) and disclosure.get("improvement") is not None:
        alpha = float(disclosure.get("alpha") or 0.05)
        text = (
            f"Zielebene (Ziel-Fehlbetrag + Chance-Strafe) Hausmatrix "
            f"{float(disclosure['house_goal_level']):.6e} vs. Ergebnis "
            f"{float(disclosure['final_goal_level']):.6e}, Verbesserung "
            f"{float(disclosure['improvement']):.6e}"
        )
        lower = disclosure.get("improvement_lower_bound")
        upper = disclosure.get("improvement_upper_bound")
        if lower is not None and upper is not None:
            text += (
                f" ({1 - 2 * alpha:.0%}-Intervall {float(lower):.6e} bis "
                f"{float(upper):.6e}, gepaarter Bootstrap B = "
                f"{disclosure.get('n_bootstrap')}, "
                f"{block.get('validation_n_paths')} Validierungspfade)"
            )
        parts.append(text + ".")
    probabilities = [
        row for row in (block.get("goal_probabilities") or [])
        if row.get("probability_house") is not None
        and row.get("probability_final") is not None
        and row.get("goal_id") is not None
    ]
    if probabilities:
        parts.append(
            "Zielwahrscheinlichkeit (Validierungswuerfel): "
            + "; ".join(
                f"{row.get('label')}: {100.0 * float(row['probability_final']):.1f} % "
                f"statt {100.0 * float(row['probability_house']):.1f} % mit der Hausmatrix"
                for row in probabilities
            )
            + "."
        )
    return " ".join(parts)
