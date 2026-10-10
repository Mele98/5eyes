"""Schaetzer-bewusste Zertifizierung von Zielerreichungs-Wahrscheinlichkeiten.

OPTIMIZER-POST-SELECTION-CERTIFICATION-001.

Problem
-------
``chance_constraint_penalty()`` zertifizierte ein Ziel als "erreichbar",
sobald der rohe Stichproben-Mittelwert ``>= tau`` lag -- ein Punktschaetzer
ohne jede Beruecksichtigung der Stichprobenunsicherheit. Bei genau
``p_hat == tau`` ist das keine Evidenz dafuer, dass die WAHRE
Erfolgswahrscheinlichkeit ``>= tau`` ist; sie liegt mit rund 50 Prozent
Wahrscheinlichkeit darunter.

Verschaerfend: der Optimizer waehlt den Kandidaten mit dem besten Ergebnis
auf DEMSELBEN Szenario-Cube, auf dem er ihn danach zertifiziert. Das ist
Post-Selection-Bias (Winner's Curse) -- das Maximum ueber viele
rauschbehaftete Schaetzer ist systematisch zu optimistisch. Eine untere
Konfidenzgrenze statt des Punktschaetzers entfernt diese Verzerrung nicht
vollstaendig (dafuer braucht es die unabhaengige Validierungsstichprobe,
siehe ``validation_seed`` unten), macht die Aussage aber von "der Mittelwert
lag zufaellig ueber der Schwelle" zu "die Schwelle ist auch unter
Beruecksichtigung der Stichprobenunsicherheit gehalten".

Wahl der Schaetzer
------------------
- **Wilson-Score** fuer die untere Grenze eines Anteils: deutlich bessere
  Abdeckung bei kleinen Stichproben und bei p nahe 0/1 als die
  Normal-Approximation (Wald), und ohne deren Entartung (Wald liefert bei
  p_hat=1 ein Intervall der Breite 0). Standardverfahren, keine
  Eigenkonstruktion.
- **Kish-ESS** fuer gewichtete Schaetzer (Importance Sampling): bei
  ungleichen Pfadgewichten ist die Pfadzahl ``n`` die falsche Bezugsgroesse.
  ``ESS = (sum w)^2 / sum(w^2)`` ist die etablierte effektive
  Stichprobengroesse; sie wird hier als ``n`` in die Wilson-Formel
  eingesetzt. Das ist die ueblich verwendete Approximation fuer gewichtete
  Anteile -- exakt waere eine Verteilung der Gewichte noetig, die wir nicht
  kennen; die Approximation ist konservativ in der fuer uns relevanten
  Richtung (kollabierendes ESS -> breiteres Intervall -> keine
  Zertifizierung).
"""
from __future__ import annotations

import math

import numpy as np


# Einseitige 95-Prozent-Grenze: Phi^-1(0.95).
WILSON_Z_ONE_SIDED_95 = 1.6448536269514722

# ESS-Schwellen fuer "die Zertifizierung ruht auf genug unabhaengiger
# Evidenz". Zwei Kriterien, beide muessen halten:
#
# - ABSOLUTE_FLOOR: unter ~30 effektiven Pfaden ist jede Anteilsaussage
#   praktisch wertlos, unabhaengig davon wie viele Rohpfade es gab.
# - FRACTION_FLOOR: faellt das ESS unter 10 Prozent der Rohpfadzahl, ist die
#   Importance-Sampling-Gewichtung degeneriert (wenige Pfade tragen fast die
#   gesamte Gewichtsmasse). Dann ist der Schaetzer zwar formal unverzerrt,
#   seine Varianz aber so hoch, dass "erreichbar" keine belastbare Aussage
#   mehr ist.
#
# Fuer den ungewichteten Pfad (weights=None) ist ESS == n, die
# Bruchteil-Bedingung also immer erfuellt -- dort aendert sich nichts.
ESS_ABSOLUTE_FLOOR = 30.0
ESS_FRACTION_FLOOR = 0.10


def effective_sample_size(weights: np.ndarray) -> float:
    """Kish'sche effektive Stichprobengroesse ``(sum w)^2 / sum(w^2)``.

    Bei uniformen Gewichten ist das genau ``n``; bei auf einen Pfad
    konzentrierter Gewichtsmasse geht sie gegen 1.
    """
    weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
    if weights_arr.size == 0:
        return 0.0
    total = float(np.sum(weights_arr))
    sum_squares = float(np.sum(weights_arr * weights_arr))
    if sum_squares <= 0.0 or total <= 0.0:
        return 0.0
    return (total * total) / sum_squares


def wilson_lower_bound(
    p_hat: float,
    n_effective: float,
    *,
    z: float = WILSON_Z_ONE_SIDED_95,
) -> float:
    """Einseitige untere Wilson-Score-Konfidenzgrenze fuer einen Anteil.

    ``n_effective`` ist die Pfadzahl (ungewichtet) bzw. das ESS
    (gewichtet). Rueckgabe ist auf [0, 1] begrenzt; bei ``n_effective <= 0``
    gibt es keine Evidenz und die Grenze ist 0.
    """
    n = float(n_effective)
    if n <= 0.0:
        return 0.0
    phat = min(1.0, max(0.0, float(p_hat)))
    z_sq = z * z
    denominator = 1.0 + z_sq / n
    center = phat + z_sq / (2.0 * n)
    adjustment = z * math.sqrt(phat * (1.0 - phat) / n + z_sq / (4.0 * n * n))
    lower = (center - adjustment) / denominator
    return min(1.0, max(0.0, lower))


def ess_is_sufficient(n_effective: float, n_paths: int) -> bool:
    """Ob das ESS fuer eine belastbare Zertifizierung ausreicht.

    Siehe ESS_ABSOLUTE_FLOOR / ESS_FRACTION_FLOOR.
    """
    n_eff = float(n_effective)
    if n_eff < ESS_ABSOLUTE_FLOOR:
        return False
    if int(n_paths) > 0 and n_eff < ESS_FRACTION_FLOOR * float(n_paths):
        return False
    return True


# Reliability-Taxonomie. Bewusst getrennt vom Berater-sichtbaren `status`:
# `status` beantwortet "ist das Ziel erreichbar?", `reliability_verdict`
# beantwortet "wie belastbar ist diese Aussage?".
RELIABILITY_UNRELIABLE_LOW_ESS = "unreliable_low_ess"
RELIABILITY_UNCERTAIN_FINITE_SAMPLE = "uncertain_finite_sample"
RELIABILITY_UNVALIDATED_SINGLE_CUBE = "unvalidated_single_cube"
RELIABILITY_ROBUST = "robust"
RELIABILITY_BELOW_TAU = "below_tau"


def reliability_verdict(
    *,
    probability: float,
    lower_bound: float,
    tau: float,
    ess_sufficient: bool,
    validation_seed: int | None,
) -> str:
    """Belastbarkeits-Verdikt zu einer Zielerreichungs-Aussage.

    ``RELIABILITY_UNVALIDATED_SINGLE_CUBE`` ist der ehrliche Normalfall,
    solange die Zertifizierung auf demselben Szenario-Cube laeuft, auf dem
    selektiert wurde: die Schwelle haelt dann zwar auch unter
    Stichprobenunsicherheit, aber der Post-Selection-Bias ist damit NICHT
    ausgeschlossen. ``RELIABILITY_ROBUST`` ist deshalb erst erreichbar, wenn
    ein ``validation_seed`` einer unabhaengigen Validierungsstichprobe
    vorliegt -- so bleibt das Fehlen dieser Evidenz sichtbar statt
    stillschweigend als "gruen" durchzugehen.
    """
    if not ess_sufficient:
        return RELIABILITY_UNRELIABLE_LOW_ESS
    if lower_bound >= tau:
        if validation_seed is None:
            return RELIABILITY_UNVALIDATED_SINGLE_CUBE
        return RELIABILITY_ROBUST
    if probability >= tau:
        return RELIABILITY_UNCERTAIN_FINITE_SAMPLE
    return RELIABILITY_BELOW_TAU
