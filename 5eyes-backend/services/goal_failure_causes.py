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


_PRIMARY_SHARE_TOL = 1e-4  # 1 Basispunkt
_PROBABILITY_ONE_TOL = 1e-12


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _mode_order(event_id: str) -> tuple[int, str]:
    # Gleiche Reihenfolge wie die Engine (goal_attribution._failure_event_
    # distribution): Anteil absteigend, dann frueheres Jahr, dann eigenes Ziel.
    match = _LIQUIDITY_RE.match(event_id)
    return (int(match.group(1)), event_id) if match else (10**9, event_id)


def is_bound_to_goal_row(row: Mapping[str, Any] | None, entries: list[dict] | None) -> bool:
    """Semantische Bindung einer normalisierten Verteilung an IHRE Zielzeile.

    Closure-Review PR #671 (GOAL-ACHIEVABILITY-ATTRIBUTION-001). Die Syntax
    prueft ``normalize_failure_event_distribution``; hier gilt zusaetzlich:

    * zielspezifische Ereignisse (``zielschwelle-*``/``renditeziel-*``)
      tragen exakt die ``goal_id`` der Zeile (und die zur ``target_kind``
      passende Art, falls angegeben);
    * keine doppelten Event-IDs;
    * ``failure_event_id`` ist der deterministische Modus der Verteilung und
      ``failure_event_share`` dessen Anteil (Toleranz 1 bp); leere
      Verteilung -> kein primaeres Ereignis;
    * Wahrscheinlichkeit 100 % verlangt eine leere Verteilung; unter 100 %
      verlangt sie Failure-Evidence (ausser ausserhalb des Simulations-
      horizonts bzw. bei Maximierungszielen, die keine Verteilung tragen).

    ``False`` -> die Verteilung wird nicht publiziert (fail-closed).
    """
    if not isinstance(row, Mapping) or entries is None:
        return False
    goal_id = str(row.get("goal_id") or "").strip()
    if not goal_id:
        return False
    raw = row.get("failure_event_distribution")
    if not isinstance(raw, (list, tuple)) or len(raw) != len(entries):
        return False
    target_kind = str(row.get("target_kind") or "").strip()
    own_kinds = (
        {KIND_RETURN} if target_kind == "return_rate"
        else {KIND_THRESHOLD} if target_kind
        else {KIND_THRESHOLD, KIND_RETURN}
    )
    seen: set[str] = set()
    for entry in entries:
        event_id = entry["event_id"]
        if event_id in seen:
            return False
        seen.add(event_id)
        kind = entry["kind"]
        if kind in (KIND_THRESHOLD, KIND_RETURN):
            if kind not in own_kinds or event_id != f"{kind}-{goal_id}":
                return False

    primary_id = row.get("failure_event_id")
    primary_share = row.get("failure_event_share")
    probability = _float_or_none(row.get("probability"))
    if not entries:
        if primary_id is not None or primary_share is not None:
            return False
        exempt = bool(row.get("outside_simulation_horizon")) or target_kind == "maximize"
        if probability is not None and probability < 1.0 - _PROBABILITY_ONE_TOL and not exempt:
            return False
        return True

    if probability is not None and probability >= 1.0 - _PROBABILITY_ONE_TOL:
        return False
    shares = {item["event_id"]: float(item["share"]) for item in raw}
    mode_id = min(shares, key=lambda eid: (-shares[eid], _mode_order(eid)))
    if primary_id != mode_id:
        return False
    primary = _float_or_none(primary_share)
    if primary is None or abs(primary - shares[mode_id]) > _PRIMARY_SHARE_TOL:
        return False
    return True


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
