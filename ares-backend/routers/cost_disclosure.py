"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — standalone JSON-Endpoint.

Liefert den vorausschaubaren Kostenausweis eines Mandats als JSON.
Die Datenstruktur ist identisch mit dem dict aus
services.cost_disclosure.build_cost_disclosure (Single-Source-of-Truth);
hier nur typsicheres Wrapping + Auth.

Verwandte Surfaces:
- Aggregator (services.advisory_report) konsumiert dieselbe Funktion
- Depot-Check-PDF rendert dieselbe Datenstruktur (Codex Bug-#4)
- Standalone Kostenausweis-PDF (folgt in PR 2)
- Frontend-Modal + Auto-AdvisoryLog-Flag (folgt in PR 3)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.users import User
from schemas.cost_disclosure import CostDisclosureResponse
from services.auth import get_current_user, get_mandate_for_user_or_404
from services.cost_disclosure import build_cost_disclosure


router = APIRouter(tags=["Kostenausweis"])


@router.get(
    "/mandates/{mandate_id}/cost-disclosure/ex-ante",
    response_model=CostDisclosureResponse,
)
def get_ex_ante_cost_disclosure(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FIDLEG Art. 8/9 Ex-ante Kostenausweis fuer das Mandat.

    Konsumiert die aktuelle RecommendationRun (oder die aktive OptimizerPolicy
    als Fallback). Bei fehlender Empfehlung wird `data_pending=True`
    zurueckgegeben — die Schema-Form bleibt gleich, der Client braucht
    keine 404-Sonderbehandlung.
    """
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    return build_cost_disclosure(db, mandate)
