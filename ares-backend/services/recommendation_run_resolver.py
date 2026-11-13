"""PDF-RUN-RESOLVER-001: EINE Regel fuer "welcher RecommendationRun gilt".

Kundendokumente (Portfolio-, Anlagestrategie-, Depot-Check-PDF,
Beratungsentscheid, Advisory-Report) loesen den Empfehlungslauf alle ueber
diese Funktion auf:

- nur Runs, deren ``target_allocation_id`` der AKTUELLEN TargetAllocation
  entspricht (ein Run einer ueberholten Allokation passt nie zu deren
  Bucket-Zielen);
- darunter der juengste ``Final``-Run, sonst der juengste ``Draft``-Run;
- ``Superseded`` (oder jeder andere Status) nie.

Gibt es keinen solchen Run, liefert die Funktion ``None`` -- es wird NIE
auf einen beliebigen anderen (juengsten) Run zurueckgefallen.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.sustainability_preference import CURRENT_RUN_SQL

NO_CURRENT_RECOMMENDATION_MARKER = "keine aktuelle Produktempfehlung"
"""Expliziter Marker fuer Dokumente, wenn zur aktuellen Allokation kein
gueltiger Run existiert (Produktliste bleibt dann leer)."""

RESOLVABLE_STATUS_PRIORITY: tuple[str, ...] = ("Final", "Draft")


def resolve_current_recommendation_run(
    db: Session,
    mandate_id: Any,
    target_allocation_id: Any,
) -> Any:
    """Final, sonst Draft, gebunden an ``target_allocation_id``; sonst None.

    N-901-02: dieselbe Abfrage (core/sustainability_preference.py::
    CURRENT_RUN_SQL) nutzen auch die Freigabe-Gates."""
    from models.review import RecommendationRun

    if not target_allocation_id:
        return None
    run_id = db.execute(
        text(CURRENT_RUN_SQL),
        {"mandate_id": mandate_id, "target_allocation_id": str(target_allocation_id)},
    ).scalar()
    return db.get(RecommendationRun, run_id) if run_id else None
