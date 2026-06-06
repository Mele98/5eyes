"""Sprint U-36 (2026-06-06): Client-Portal Read-Only-Endpoints.

Berater-Demo-Tool: ein Kunde mit eigenem Login (role='client') sieht
seine eigenen Stammdaten + Mandate + Advisory-Report read-only.

Auth: require_client (verweigert advisor/admin). Datenfilter:
get_linked_client_for_user_or_404 — Kunde sieht NUR die mit seinem
User verknuepfte Client-Akte, nie fremde Akten.

Bewusst NICHT exposed: Write-Endpoints, Override-Workflows,
Admin-Tabellen. Pure Read-Only-Sicht.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.advisory_report import compute_advisory_report
from services.auth import get_linked_client_for_user_or_404, require_client


router = APIRouter(prefix="/client-portal", tags=["Kunden-Portal"])


def _client_to_dict(client: Client) -> dict:
    """Read-Only-Projektion auf Berater-unkritische Stammdaten."""
    return {
        "id": client.id,
        "client_number": client.client_number,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "date_of_birth": getattr(client, "date_of_birth", None),
        "tax_residence": getattr(client, "tax_residence", None),
        "primary_currency": getattr(client, "primary_currency", "CHF"),
    }


def _mandate_to_dict(mandate: Mandate) -> dict:
    """Read-Only-Projektion auf Berater-relevante Mandats-Metadaten."""
    return {
        "id": mandate.id,
        "mandate_number": mandate.mandate_number,
        "mandate_type": mandate.mandate_type,
        "status": mandate.status,
        "base_currency": mandate.base_currency,
        "opened_at": mandate.opened_at,
        "closed_at": getattr(mandate, "closed_at", None),
    }


@router.get("/me")
def client_portal_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Stammdaten + alle Mandate des verknuepften Kunden.

    Berater-Reichweite: Kunde sieht nur SEINE Akte, nicht andere.
    """
    client = get_linked_client_for_user_or_404(current_user, db)
    mandates = (
        db.query(Mandate)
        .filter(
            Mandate.client_id == client.id,
            Mandate.deleted_at.is_(None),
        )
        .order_by(Mandate.opened_at.desc())
        .all()
    )
    return {
        "client": _client_to_dict(client),
        "mandates": [_mandate_to_dict(m) for m in mandates],
        "scope": "read_only_client_portal",
    }


@router.get("/mandates/{mandate_id}/report")
def client_portal_mandate_report(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Advisory-Report (volle 24 Sektionen) fuer EIGENES Mandat.

    Sicherheits-Gates:
      - Mandat muss zum verknuepften Kunden gehoeren
      - Sonst 404 (kein Leak ob fremdes Mandat existiert)
    """
    client = get_linked_client_for_user_or_404(current_user, db)
    mandate = (
        db.query(Mandate)
        .filter(
            Mandate.id == mandate_id,
            Mandate.client_id == client.id,
            Mandate.deleted_at.is_(None),
        )
        .first()
    )
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat nicht gefunden.")
    return compute_advisory_report(db, mandate)
