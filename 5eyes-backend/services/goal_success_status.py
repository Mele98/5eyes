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
"""

from __future__ import annotations

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


__all__ = [
    "GOAL_SUCCESS_GOOD_PCT",
    "GOAL_SUCCESS_WARN_PCT",
    "GOAL_STATUS_ON_TRACK",
    "GOAL_STATUS_REVIEW",
    "GOAL_STATUS_AT_RISK",
    "goal_status_from_success_pct",
]
