"""GOAL-STATUS-BY-SUCCESS-001: Zielstatus aus der Erfolgswahrscheinlichkeit.

Seit #654 ist die Erfolgswahrscheinlichkeit (Anteil der simulierten
Verlaeufe, in denen ein Ziel vollstaendig erreicht wird) die EINE
Primaerkennzahl mit der Ampel 70/45 (>= 70 % gut, 45-69 % knapp,
< 45 % kritisch). Der Ziel-Status in ``goal_analysis`` /
``current_goal_analysis`` beruhte bis dahin auf dem Mischwert
``achievement_score`` (alpha * Erfolgsquote + (1 - alpha) * Deckungsgrad,
B5). Folge: ein Ziel mit 30 % Erfolgswahrscheinlichkeit, aber hohem
Median-Deckungsgrad, konnte "On Track" heissen, waehrend dieselbe Zeile in
der Ampel "kritisch" zeigte.

Die Statuswoerter ``On Track`` / ``Pruefen`` / ``Gefaehrdet`` bleiben
unveraendert: sie sind Teil des Backend-Vertrags (``GoalAnalysisResponse.
status``; der Monolith uebersetzt sie in ``goalTimingLabel`` und in der
Ziel-Liste). Geaendert ist nur die Berechnungsgrundlage. Zuordnung zur
Ampel: On Track = gut, Pruefen = knapp, Gefaehrdet = kritisch.

``achievement_score`` (Mischwert) bleibt als eigenes Feld erhalten, traegt
aber keinen Status mehr.

EINE Quelle (CIO-Entscheid zu #667): kanonisch ist die priorisierte, vom
Optimizer publizierte Erfolgswahrscheinlichkeit (``goal_achievability``,
``evaluation_scope=priority_funded``) -- seit #659 im Scope des Objectives
und dieselbe Quelle wie im Bericht (``_compute_goal_achievement_score_bps``).
Nur wenn sie fuer ein Ziel fehlt (Altbestand/IST, keine Optimizer-Evidenz),
gilt ``success_rate_pct`` der Simulation als Schaetzung
(``success_probability_source = "simulation"``).
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

GOAL_SUCCESS_GOOD_PCT = 70
GOAL_SUCCESS_WARN_PCT = 45

GOAL_STATUS_ON_TRACK = "On Track"
GOAL_STATUS_REVIEW = "Pruefen"
GOAL_STATUS_AT_RISK = "Gefaehrdet"


def goal_status_from_success_pct(success_rate_pct: int | float | None) -> str:
    """Status nach der 70/45-Ampel der Erfolgswahrscheinlichkeit (0..100)."""
    try:
        pct = float(success_rate_pct or 0)
    except (TypeError, ValueError):
        pct = 0.0
    if pct >= GOAL_SUCCESS_GOOD_PCT:
        return GOAL_STATUS_ON_TRACK
    if pct >= GOAL_SUCCESS_WARN_PCT:
        return GOAL_STATUS_REVIEW
    return GOAL_STATUS_AT_RISK


SUCCESS_SOURCE_OPTIMIZER = "optimizer"
SUCCESS_SOURCE_SIMULATION = "simulation"


def canonical_success_by_goal(achievability: Iterable[Mapping] | None) -> dict[str, float]:
    """goal_id -> priorisierte Erfolgswahrscheinlichkeit (0..1) aus der
    Optimizer-Evidenz. Plan-Solvenz und Altbewertungen ohne Scope zaehlen
    nicht (keine zielindividuelle Evidenz)."""
    from services.optimizer.goal_attribution import (
        is_individual_goal_row,
        split_goal_achievability,
    )

    rows, _plan = split_goal_achievability(achievability or [])
    out: dict[str, float] = {}
    for row in rows:
        if not is_individual_goal_row(row):
            continue
        goal_id = str(row.get("goal_id") or "")
        try:
            probability = float(row.get("probability"))
        except (TypeError, ValueError):
            continue
        if goal_id and math.isfinite(probability):
            out[goal_id] = max(0.0, min(1.0, probability))
    return out


def report_goal_weight(weight_bps) -> float:
    """Zielgewicht wie im Bericht (AR-2): ``Goal.weight_bps`` roh, <= 0 -> 1."""
    try:
        weight = float(weight_bps or 0)
    except (TypeError, ValueError):
        weight = 0.0
    return weight if weight > 0 else 1.0


def weighted_success_probability_bps(
    pairs: Iterable[tuple[float, float]],
) -> int | None:
    """Gewichtete Erfolgswahrscheinlichkeit in bps aus (probability 0..1,
    Gewicht). Einzige Formel fuer Bericht, Cockpit-Kachel (JS-Spiegel
    ``goalSuccessSummary``) und Foundation-Beispiel."""
    weighted_sum = 0.0
    weight_total = 0.0
    for probability, weight in pairs:
        weighted_sum += float(probability) * float(weight)
        weight_total += float(weight)
    if weight_total <= 0:
        return None
    return int(round(weighted_sum / weight_total * 10000))


def goal_items_weighted_success_bps(goal_analysis: Iterable[Mapping]) -> int | None:
    """Dieselbe Kennzahl aus ``goal_analysis``-Zeilen (nach Merge)."""
    pairs = [
        (float(item["success_probability"]), report_goal_weight(item.get("success_weight_bps")))
        for item in goal_analysis or []
        if item.get("success_probability") is not None
    ]
    return weighted_success_probability_bps(pairs)


__all__ = [
    "SUCCESS_SOURCE_OPTIMIZER",
    "SUCCESS_SOURCE_SIMULATION",
    "canonical_success_by_goal",
    "goal_items_weighted_success_bps",
    "report_goal_weight",
    "weighted_success_probability_bps",
    "GOAL_SUCCESS_GOOD_PCT",
    "GOAL_SUCCESS_WARN_PCT",
    "GOAL_STATUS_ON_TRACK",
    "GOAL_STATUS_REVIEW",
    "GOAL_STATUS_AT_RISK",
    "goal_status_from_success_pct",
]
