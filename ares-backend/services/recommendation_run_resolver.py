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

from sqlalchemy.orm import Session

NO_CURRENT_RECOMMENDATION_MARKER = "keine aktuelle Produktempfehlung"
"""Expliziter Marker fuer Dokumente, wenn zur aktuellen Allokation kein
gueltiger Run existiert (Produktliste bleibt dann leer)."""

RESOLVABLE_STATUS_PRIORITY: tuple[str, ...] = ("Final", "Draft")


def resolve_current_recommendation_run(
    db: Session,
    mandate_id: Any,
    target_allocation_id: Any,
) -> Any:
    """Final, sonst Draft, gebunden an ``target_allocation_id``; sonst None."""
    from models.review import RecommendationRun

    if not target_allocation_id:
        return None
    matching_runs = (
        db.query(RecommendationRun)
        .filter(
            RecommendationRun.mandate_id == mandate_id,
            RecommendationRun.target_allocation_id == str(target_allocation_id),
            RecommendationRun.result_status.in_(RESOLVABLE_STATUS_PRIORITY),
        )
        .order_by(RecommendationRun.created_at.desc())
        .all()
    )
    for status in RESOLVABLE_STATUS_PRIORITY:
        run = next((r for r in matching_runs if r.result_status == status), None)
        if run is not None:
            return run
    return None
