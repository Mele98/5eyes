"""MC-CONTEXT-001 / GOAL-PUBLICATION-001: letzte Publikationsgrenze fuer
Projektionswerte im Advisory-Report-Payload.

Die Section-Builder pruefen den Projection-Gate bereits VOR teuren
Berechnungen. Genau diese Verteilung ueber viele Builder liess zwei Werte
ungeschuetzt (aggregierter Zielerreichungs-Score als ``0`` statt
"nicht verfuegbar"; Risikoquote einer alten Allokation in der
Risikoprofil-Sektion). Dieser Redactor ist deshalb die zentrale, typisierte
Grenze NACH dem Aggregator: Ein Manifest skalarer Projektionsfelder wird bei
ausgeblendetem Gate auf ``None`` gesetzt -- unabhaengig davon, ob ein Builder
ihn vergessen hat.

Pfadsyntax je Manifest-Eintrag (Tupel von Segmenten):

* ``"name"`` -- Dict-Schluessel;
* ``"[]"``   -- jedes Element einer Liste;
* ``"*"``    -- jeder Wert eines Dicts.

Nur das letzte Segment wird ersetzt. Fehlt ein Zwischenknoten (Sektion per
``hidden_report_sections`` ausgeblendet, Leerform), passiert nichts.

Keine Finanzmathematik: hier wird nichts berechnet, nur unterdrueckt.
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator

# Skalare Projektionsfelder, die bei ``ProjectionGate.is_hidden`` zwingend
# ``None`` sein muessen. Dotted-Name (Payload-Inventar) -> Segmentpfad.
SCALAR_PROJECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "ausgangslage.key_metrics": ("ausgangslage", "key_metrics", "*"),
    "goal_based_investing.goal_achievement_score_bps": (
        "goal_based_investing", "goal_achievement_score_bps",
    ),
    "goal_based_investing.goals.probability_bps": (
        "goal_based_investing", "goals", "[]", "probability_bps",
    ),
    "goal_based_investing.plan_solvency": (
        "goal_based_investing", "plan_solvency",
    ),
    "risikoprofilierung.risky_fraction_bps": (
        "risikoprofilierung", "risky_fraction_bps",
    ),
}


def _parents(node: Any, segments: tuple[str, ...]) -> Iterator[tuple[Any, Any]]:
    """Liefert (Container, Schluessel/Index) fuer jedes Blatt des Pfads."""
    head, rest = segments[0], segments[1:]
    if head == "[]":
        if not isinstance(node, list):
            return
        keys: Iterable[Any] = range(len(node))
    elif head == "*":
        if not isinstance(node, dict):
            return
        keys = list(node.keys())
    else:
        if not isinstance(node, dict) or head not in node:
            return
        keys = (head,)
    for key in keys:
        if not rest:
            yield node, key
        else:
            yield from _parents(node[key], rest)


def redact_projection_channels(payload: dict[str, Any], gate: Any) -> dict[str, Any]:
    """Setzt bei ausgeblendetem Gate jedes Manifest-Feld auf ``None``.

    Mutiert und liefert ``payload``. Bei publizierbarem Gate (``current``,
    ``no_allocation``) bleibt der Payload unveraendert."""
    if not bool(getattr(gate, "is_hidden", True)):
        return payload
    for segments in SCALAR_PROJECTION_FIELDS.values():
        for container, key in list(_parents(payload, segments)):
            container[key] = None
    return payload


def numeric_projection_leaks(payload: dict[str, Any]) -> list[str]:
    """Diagnose fuer Invariant-Tests: Manifest-Pfade mit numerischem Wert."""
    leaks: list[str] = []
    for name, segments in SCALAR_PROJECTION_FIELDS.items():
        for container, key in _parents(payload, segments):
            value = container[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) or (
                isinstance(value, dict)
                and any(
                    isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in value.values()
                )
            ):
                leaks.append(f"{name}[{key}]")
    return leaks
