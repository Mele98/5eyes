"""Report-Darstellung der Ursachenverteilung verfehlter Zielverlaeufe.

GOAL-FAILURE-DISTRIBUTION-REPORT-001: Seit Engine v10 (PR #659) persistiert
``services.optimizer.goal_attribution.publish_goal_achievability`` je Ziel die
volle ``failure_event_distribution`` (Event-ID, gewichtete Masse, Anteil).
Dieses Modul uebersetzt sie fuer den Advisory-Report (Payload, PDF, React):

* ``normalize_failure_event_distribution`` -- typisierte, validierte Eintraege
  (``event_id``, ``kind``, ``plan_year``, ``share_bps``); die interne
  ``weighted_mass`` wird nicht publiziert.
* ``summarize_failure_causes`` -- kompakte, kundenverstaendliche Gruppen je
  Ereignisart (Liquiditaetsengpass / Zielbetrag / Zielrendite) mit Anteil und
  Planjahr-Spanne.

Vertrag:
* Fehlt die Verteilung (Altbestand vor Engine v10), ist sie fehlerhaft oder
  nicht vollstaendig deutbar, ist das Ergebnis ``None`` -- der Bericht zeigt
  dann NICHTS (fail-closed, keine geratene Teilverteilung).
* Leere Verteilung (Ziel in keinem Verlauf verfehlt) -> ``[]``; ebenfalls
  keine Anzeige.
* Die Texte beschreiben, welches Ereignis in den verfehlten Verlaeufen
  ZUERST eintritt -- keine Kausalaussage ("weil", "verursacht").
* Planjahr ``t`` ist die Spalte ``t`` des simulierten Vermoegenspfads
  (Spalte 0 = Ausgangslage), also das t-te Simulationsjahr. Eine Umrechnung
  in Kalenderjahre erfolgt bewusst nicht: der Bericht kennt den Startzeitpunkt
  der gespeicherten Simulation nicht verlaesslich.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

KIND_LIQUIDITY = "liquiditaetsengpass"
KIND_THRESHOLD = "zielschwelle"
KIND_RETURN = "renditeziel"

_LIQUIDITY_RE = re.compile(r"^liquiditaetsengpass-jahr-(\d+)$")
_KIND_ORDER = (KIND_LIQUIDITY, KIND_THRESHOLD, KIND_RETURN)
_SHARE_TOL = 1e-6

FAILURE_CAUSE_INTRO = (
    "In den simulierten Verläufen, in denen das Ziel verfehlt wird, "
    "tritt zuerst ein"
)
FAILURE_CAUSE_NOTE = (
    "Anteile der verfehlten Verläufe nach dem ersten eingetretenen Ereignis; "
    "beschreibt den Verlauf, keine Ursache im engeren Sinn."
)


def _classify(event_id: str) -> tuple[str, int | None] | None:
    match = _LIQUIDITY_RE.match(event_id)
    if match:
        year = int(match.group(1))
        return (KIND_LIQUIDITY, year) if year >= 1 else None
    if event_id == KIND_THRESHOLD or event_id.startswith(KIND_THRESHOLD + "-"):
        return KIND_THRESHOLD, None
    if event_id.startswith(KIND_RETURN + "-"):
        return KIND_RETURN, None
    return None


def normalize_failure_event_distribution(row: Mapping[str, Any] | None) -> list[dict] | None:
    """Validierte Verteilung einer Zielzeile oder ``None`` (nicht anzeigen)."""
    if not isinstance(row, Mapping):
        return None
    raw = row.get("failure_event_distribution")
    if not isinstance(raw, (list, tuple)):
        return None
    entries: list[dict] = []
    total = 0.0
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        event_id = item.get("event_id")
        share = item.get("share")
        if not isinstance(event_id, str) or isinstance(share, bool):
            return None
        try:
            share_f = float(share)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(share_f) or share_f < 0.0 or share_f > 1.0 + _SHARE_TOL:
            return None
        classified = _classify(event_id)
        if classified is None:
            return None
        kind, plan_year = classified
        total += share_f
        entries.append({
            "event_id": event_id,
            "kind": kind,
            "plan_year": plan_year,
            "share_bps": int(round(share_f * 10000)),
        })
    if entries and abs(total - 1.0) > 1e-3:
        # Teilverteilung -> nicht als Ganzes darstellbar.
        return None
    return entries


def _plan_year_span(years: list[int]) -> str:
    lo, hi = min(years), max(years)
    if lo == hi:
        return f"im {lo}. Planjahr"
    return f"zwischen dem {lo}. und {hi}. Planjahr"


def summarize_failure_causes(distribution: list[dict] | None) -> list[dict] | None:
    """Kompakte Gruppen je Ereignisart, Anteil absteigend.

    ``None`` -> ``None``; leere Verteilung -> ``[]``.
    """
    if distribution is None:
        return None
    groups: dict[str, dict] = {}
    for entry in distribution:
        kind = entry["kind"]
        group = groups.setdefault(kind, {"kind": kind, "share_bps": 0, "years": []})
        group["share_bps"] += int(entry["share_bps"])
        if entry.get("plan_year") is not None:
            group["years"].append(int(entry["plan_year"]))
    out: list[dict] = []
    for kind, group in groups.items():
        years = group.pop("years")
        if kind == KIND_LIQUIDITY:
            label = (
                "Liquiditätsengpass – verfügbares Vermögen "
                f"{_plan_year_span(years)} aufgebraucht"
            )
        elif kind == KIND_THRESHOLD:
            label = "Zielbetrag zum Fälligkeitszeitpunkt nicht vollständig erreicht"
        else:
            label = "Zielrendite nicht erreicht"
        out.append({
            "kind": kind,
            "label": label,
            "share_bps": min(10000, group["share_bps"]),
            "first_plan_year": min(years) if years else None,
            "last_plan_year": max(years) if years else None,
        })
    out.sort(key=lambda g: (-g["share_bps"], _KIND_ORDER.index(g["kind"])))
    return out
