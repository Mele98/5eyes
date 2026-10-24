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
  Prior-Term im Default ERSETZT.
* Prior-Metrik (HOUSE-PRIOR-PSD-NULLSPACE-001, Engine ``saa_resampled_v7``):
  eine Kovarianz ist nur positiv SEMIdefinit. Bei (nahezu) perfekt
  korrelierten Sleeves gleicher Vola gibt es Umschichtungen mit
  ``(w - w_H)' Sigma (w - w_H) = 0`` -- der Term waere dort flach: kein
  Gewichtsanker, kein eindeutiges Minimum. Deshalb gilt im Prior-Term (und
  im ausgewiesenen Abstand) die Ridge-Metrik

      M = Sigma + eps * I,   eps = HOUSE_PRIOR_RIDGE_BPS2 = 2'500 bps^2
                                   (= (0.5 %)^2 p.a.)

  ``M`` ist strikt positiv definit (kleinster Eigenwert >= eps), der Term
  stark konvex (Hesse ``2 kappa_H M``) mit eindeutigem Minimum ueber der
  konvexen zulaessigen Menge; die Bayes-Lesart (MAP mit Gauss-Prior auf die
  Gewichte, Praezision ``2 kappa_H M``) ist damit proper. Wahl von eps: eine
  idiosynkratische Policy-Varianz von 0.5 % je Bucket -- kleiner als die
  Varianz jedes risikobehafteten Buckets (Obligationen-Vola ~3.5 %, Aktien
  ~15 %). Eine Umschichtung von 10 pp zwischen zwei Buckets kostet
  ``eps * 0.02 = 5e-7`` (Dezimal^2); gemessen (Test-CMA) 0.2 % der
  Tracking-Error-Varianz bei Aktien <-> Obligationen (2.7e-4), 0.7 % bei
  Immobilien <-> Obligationen, 3.3 % bei Obligationen <-> Liquiditaet
  (1.5e-5). Ausserhalb des
  Nullraums verschiebt die Ridge das Optimum daher nur marginal; im Nullraum
  macht sie den Anker erst wirksam. Ausgewiesen als
  ``tracking_error_vs_house_bps`` ist der Abstand in dieser Metrik
  (regularisierter Tracking Error ``sqrt(TE^2 + eps * ||w - w_H||^2)``);
  ``prior_metric`` im Audit nennt eps, Eigenwerte und Konditionszahl.
* Interpretation: eine Abweichung von der Hausmatrix kostet ihren Tracking
  Error. Ein TE von 1 % wird nur genommen, wenn er die Zielebene um
  mindestens ``kappa_H * (1 %)^2 = 0.03`` verbessert. Sind die Ziele mit der
  Hausmatrix sicher erreicht (Gradient von G = 0), ist das Optimum exakt die
  Hausquote -- die CIO-Regel "Hausmatrix, solange die Ziele mit ihr gleich
  sicher erreicht sind" in stetiger Form. Bayes-Lesart: MAP mit
  Gauss-Prior auf die Gewichte (Erwartung w_H, Praezision 2 kappa_H M).

kappa_H = 300 (CIO-Entscheid): bester Wert im Schaetzfehler-Test (Engine
sieht mu_hat = mu + L z / sqrt(20), Bewertung unter der wahren CMA; wahre
Zielwahrscheinlichkeit +1.31 pp gegen v5, se 0.18) und im OOS-Minimum des
kappa-Rasters; 100-1000 sind innerhalb 1 se gleichwertig.
HOUSE-PRIOR-CALIBRATION-PROVENANCE-001: Skript, Inputmanifest, Seeds,
Rohresultate des Tunings und ein separater Holdout-Test mit vorab
festgelegter Regel liegen commitgebunden unter
``tools/house_prior_calibration/`` und
``docs/planning/2026-10-18-house-prior-kappa-calibration.md``. Die Auswahl im
Tuning war post hoc (kein vorab registriertes Kriterium); kappa_H ist deshalb
als ``HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS`` gekennzeichnet, bis ein
Modellowner-Entscheid vorliegt.

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
from .resampling import (
    NULL_HYPOTHESIS_NOT_BETTER,
    NULL_HYPOTHESIS_NOT_WORSE,
    P_VALUE_CALIBRATION,
    null_centered_p_value,
    tail_fraction,
    unit_block_bootstrap,
)

# v2 (Engine saa_resampled_v7): Ridge-Metrik Sigma + eps I
# (HOUSE-PRIOR-PSD-NULLSPACE-001), Einheiten-Bootstrap mit kalibrierten
# p-Werten in der Offenlegung, fail-closed ohne Validierungswuerfel.
HOUSE_PRIOR_VERSION = "house_prior_ridge_tracking_error_v2"
# CIO-Entscheid 2026-10-18 (HOUSE-PRIOR-001). Versioniert ueber
# ``HOUSE_PRIOR_VERSION`` und die Engine-Version; im Audit und in der
# Modellbasis ausgewiesen. Einheit: Zielebene je Tracking-Error-Varianz
# (Dezimal^2, einjaehrig).
HOUSE_PRIOR_KAPPA = 300.0
HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS = "experimental_tuned_holdout_checked"
# Ridge der Prior-Metrik in bps^2 (Herleitung im Modul-Docstring).
HOUSE_PRIOR_RIDGE_BPS2 = 2500.0
HOUSE_PRIOR_DISCLOSURE_TEST_VERSION = "paired_unit_bootstrap_disclosure_goal_level_v6"

DECISION_HOUSE_PRIOR = "house_prior"
DECISION_HOUSE_PRIOR_GUARD = "house_prior_guard"
# OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (v7): ohne Validierungswuerfel
# keine Zertifizierung -> projizierte Hausquote (fail-closed).
DECISION_HOUSE_PRIOR_FAIL_CLOSED = "house_prior_fail_closed"

REASON_IDENTICAL = "identical_to_house_anchor"
# Numerische Gleichheit mit dem Anker (Engine v7): ist der Gradient der
# Zielebene an der Hausquote 0 (Ziele sicher erreicht, keine Ziele), ist das
# exakte Optimum die Hausquote. SLSQP stoppt mit der Produktions-Toleranz
# (ftol 1e-6) aber bei Zielfunktionswerten ~1e-11 schon vorher: gemessen
# 0.6 bp Restabweichung (Mandat E ohne Ziele; mit ftol 1e-9: 0.0003 bp). Nach
# der bps-Rundung kann das genau 1 bp je Bucket ausmachen. Abweichungen
# <= HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS in JEDEM Bucket sind deshalb
# Solver-Toleranz, keine Optimierer-Aussage: publiziert wird der Anker.
REASON_WITHIN_TOLERANCE = "within_solver_tolerance_of_house_anchor"
HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS = 1
REASON_NOT_WORSE = "not_significantly_worse_than_house"
REASON_GUARD = "significantly_worse_than_house"
REASON_TEST_DISABLED = "disclosure_disabled"
REASON_NO_VALIDATION = "no_validation_cube"


def prior_metric_bps2(covariance_bps2: np.ndarray) -> np.ndarray:
    """Ridge-Metrik ``M = Sigma + eps I`` (bps^2), strikt positiv definit."""
    cov = np.asarray(covariance_bps2, dtype=np.float64)
    return cov + HOUSE_PRIOR_RIDGE_BPS2 * np.eye(cov.shape[0], dtype=np.float64)


def prior_metric_audit(covariance_bps2: np.ndarray) -> dict:
    """Offenlegung der Prior-Metrik: eps, Eigenwerte (bps^2), Konditionszahl."""
    metric = prior_metric_bps2(covariance_bps2)
    eigen = np.linalg.eigvalsh(0.5 * (metric + metric.T))
    smallest, largest = float(eigen[0]), float(eigen[-1])
    return {
        "metric": "covariance_plus_ridge",
        "ridge_bps2": float(HOUSE_PRIOR_RIDGE_BPS2),
        "min_eigenvalue_bps2": round(smallest, 4),
        "max_eigenvalue_bps2": round(largest, 4),
        "condition_number": (
            round(largest / smallest, 4) if smallest > 0.0 else None
        ),
        "kappa_calibration_status": HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS,
    }


def _metric_quadratic(delta: np.ndarray, covariance_bps2: np.ndarray) -> float:
    return portfolio_variance_one_year(delta, prior_metric_bps2(covariance_bps2))


def house_prior_penalty(
    weights: np.ndarray,
    house_weights: np.ndarray,
    covariance_bps2: np.ndarray,
    *,
    kappa: float = HOUSE_PRIOR_KAPPA,
) -> float:
    """``kappa_H * (w - w_H)' (Sigma + eps I) (w - w_H)`` (Sigma in bps^2).

    Strikt positiv fuer jedes ``w != w_H`` (HOUSE-PRIOR-PSD-NULLSPACE-001).
    """
    delta = (
        np.asarray(weights, dtype=np.float64).reshape(-1)
        - np.asarray(house_weights, dtype=np.float64).reshape(-1)
    )
    return float(kappa) * _metric_quadratic(delta, covariance_bps2)


def tracking_error_bps(
    weights: np.ndarray,
    house_weights: np.ndarray,
    covariance_bps2: np.ndarray,
) -> float:
    """Einjaehriger (Ridge-regularisierter) Tracking Error zur Hausquote in bps.

    ``sqrt((w - w_H)' (Sigma + eps I) (w - w_H))`` -- derselbe Abstand, den
    der Prior bestraft; > 0 fuer jedes ``w != w_H``.
    """
    delta = (
        np.asarray(weights, dtype=np.float64).reshape(-1)
        - np.asarray(house_weights, dtype=np.float64).reshape(-1)
    )
    variance = max(0.0, _metric_quadratic(delta, covariance_bps2))
    return float(math.sqrt(variance) * 10000.0)


def paired_bootstrap_disclosure(
    loss_pair: Callable[[np.ndarray | None], tuple[float, float]],
    *,
    n_paths: int,
    n_bootstrap: int,
    alpha: float,
    seed: int,
    sampling_unit_ids: np.ndarray | None = None,
    sampling_unit: str | None = None,
) -> dict:
    """Gepaarter Einheiten-Bootstrap von ``Delta = L(Haus) - L(Final)`` (Zielebene).

    ``Delta > 0``: das Ergebnis erreicht die Ziele besser als die Hausquote.
    Gezogen werden unabhaengige Stichprobeneinheiten (Default: antithetische
    Pfadpaare; ``resampling.unit_block_bootstrap``). Aus DENSELBEN
    Replikationen (RESAMPLING-PVALUE-SEMANTICS-001, nicht vermischt):

    * ``p_value_better`` -- einseitiger p-Wert zu H0 ``Delta <= 0``,
      ``p_value_worse`` -- zu H0 ``Delta >= 0``; beide nullzentriert
      (``resampling.null_centered_p_value``; Vertrag in
      ``null_hypothesis``/``p_value_calibration``).
    * ``significantly_worse`` (Sicherheitsnetz) genau dann, wenn
      ``Delta < 0`` UND ``p_value_worse <= alpha``.
    * Intervall: zweiseitiges (1 - 2 alpha)-Basic-Bootstrap-Intervall
      ``[2 Delta - q_{1-alpha}, 2 Delta - q_alpha]`` (dual zu den p-Werten).
    * ``bootstrap_tail_fraction_*`` -- rohe Vorzeichenanteile der
      unzentrierten Verteilung, nur Stabilitaetskennzahl.
    """
    def _delta(idx):
        house, final = loss_pair(idx)
        return float(house) - float(final)

    improvement, replicates, unit_meta = unit_block_bootstrap(
        _delta,
        n_paths=n_paths,
        n_bootstrap=n_bootstrap,
        seed=seed,
        sampling_unit_ids=sampling_unit_ids,
        sampling_unit=sampling_unit,
    )
    house_full, final_full = loss_pair(None)
    finite = replicates[np.isfinite(replicates)]
    block = {
        "test": HOUSE_PRIOR_DISCLOSURE_TEST_VERSION,
        **unit_meta,
        "n_bootstrap": int(n_bootstrap),
        "alpha": float(alpha),
        "house_goal_level": float(house_full),
        "final_goal_level": float(final_full),
        "improvement": improvement,
        "null_hypothesis": {
            "p_value_better": NULL_HYPOTHESIS_NOT_BETTER,
            "p_value_worse": NULL_HYPOTHESIS_NOT_WORSE,
        },
        "p_value_calibration": P_VALUE_CALIBRATION,
    }
    if finite.size == 0 or not math.isfinite(improvement):
        return {
            **block,
            "improvement_lower_bound": None,
            "improvement_upper_bound": None,
            "p_value_better": None,
            "p_value_worse": None,
            "bootstrap_tail_fraction_not_better": None,
            "bootstrap_tail_fraction_not_worse": None,
            "significantly_worse": False,
        }
    p_better = null_centered_p_value(improvement, finite, alternative="greater")
    p_worse = null_centered_p_value(improvement, finite, alternative="less")
    return {
        **block,
        "improvement_lower_bound": float(
            2.0 * improvement - np.quantile(finite, 1.0 - float(alpha))
        ),
        "improvement_upper_bound": float(
            2.0 * improvement - np.quantile(finite, float(alpha))
        ),
        "p_value_better": float(p_better),
        "p_value_worse": float(p_worse),
        "bootstrap_tail_fraction_not_better": float(
            tail_fraction(finite, not_better=True)
        ),
        "bootstrap_tail_fraction_not_worse": float(
            tail_fraction(finite, not_better=False)
        ),
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
    if decision == DECISION_HOUSE_PRIOR_FAIL_CLOSED:
        head = (
            "Hausmatrix-Zielquote publiziert (fail-closed): der finale "
            "Validierungswuerfel liess sich nicht bauen, das Ergebnis des "
            "Optimierers ist deshalb nicht zertifiziert."
        )
    elif decision == DECISION_HOUSE_PRIOR_GUARD:
        head = (
            "Hausmatrix-Zielquote publiziert (Sicherheitsnetz): das Ergebnis des "
            "Optimierers mit Hausmatrix-Prior erreicht die Ziele auf dem "
            "finalen, unabhaengigen Validierungswuerfel signifikant schlechter "
            "als die Hausmatrix."
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
                f"{float(upper):.6e}, gepaarter Bootstrap ueber "
                f"{disclosure.get('n_independent_units')} unabhaengige "
                f"Einheiten ({disclosure.get('sampling_unit')}), B = "
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
