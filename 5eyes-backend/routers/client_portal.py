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

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.advisory_report import compute_advisory_report
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer die Kunden-Unterschrift
# (rechtlich relevant -- Eignungspruefungs-Nachweis).
from routers.auth import _extract_client_ip
from services.auth import get_linked_client_for_user_or_404, require_client


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client-portal", tags=["Kunden-Portal"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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
    # REP-002 (Codex-Audit 2026-08-25): Kundenportal darf ausschliesslich
    # eine finalisierte, an die aktuelle Zielallokation gebundene Empfehlung
    # zeigen -- niemals einen Entwurf oder eine ueberholte Version.
    _assert_portal_report_releasable(db, mandate, client, current_user)
    return compute_advisory_report(db, mandate, client_facing=True)


def _assert_portal_report_releasable(db: Session, mandate: Mandate, client: Client, user: User) -> None:
    """CIO-Entscheid 2026-10-24: kein Kundenbericht, solange die
    Risikoprofil-Signatur nicht mehr zum gespeicherten Profil passt --
    dasselbe zentrale Gate wie Kunden-PDFs, E-Signing und Handoff. Der Kunde
    sieht nur eine neutrale Meldung; Reason-Code nur in Log und Audit."""
    from services.audit import log as audit_log
    from services.recommendation_release_gate import (
        CHANNEL_CLIENT_PORTAL,
        CLIENT_PORTAL_UNAVAILABLE_MESSAGE,
        assert_current_allocation_without_adr12a_hold,
        assert_risk_signoff_release_eligible,
    )

    try:
        assert_risk_signoff_release_eligible(db, mandate, channel=CHANNEL_CLIENT_PORTAL)
        # CMA-001 / ADR-12a-Release-Hold: Strategie auf KGV-aktiver CMA wird
        # dem Kunden nicht angezeigt (neutrale Meldung, Code nur in Log/Audit).
        assert_current_allocation_without_adr12a_hold(
            db, mandate, channel=CHANNEL_CLIENT_PORTAL,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        reason_code = str(detail.get("reason_code") or "RELEASE_BLOCKED")
        logger.warning(
            "Client-portal report blocked for mandate %s: %s (%s)",
            mandate.id, reason_code, ", ".join(detail.get("integrity_mismatches") or []),
        )
        audit_log(
            db, user_id=user.id, user_name=user.full_name or user.username,
            table_name="mandates", record_id=mandate.id, action="EXPORT",
            field_name="client_portal_report_blocked", new_value=reason_code,
            mandate_id=mandate.id, client_id=client.id,
        )
        db.commit()
        raise HTTPException(status_code=409, detail=CLIENT_PORTAL_UNAVAILABLE_MESSAGE) from None


@router.post("/mandates/{mandate_id}/risk-profile/sign")
def client_portal_sign_risk_profile(
    mandate_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Modell B (Kundenportal): der eingeloggte Kunde signiert das aktuelle
    Risikoprofil (FIDLEG-Eignungspruefung) SEINES verknuepften Mandats.

    Sicherheits-Gates (identisch zum Report-Endpoint):
      - Kunde ist 1:1 mit genau seiner Client-Akte verknuepft
      - Mandat muss zu dieser Akte gehoeren, sonst 404 (kein Leak, ob ein
        fremdes Mandat existiert) -> ein Kunde kann NUR sein eigenes Profil
        signieren, nie ein fremdes.
    Reine DOKUMENTATION der Bestaetigung — aendert die Eignungs-Konformitaet
    (Audit is_compliant) NICHT.
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

    # RISK-PROFILE-SIGNOFF-001: derselbe fail-closed Signoff-Pfad wie beim
    # Berater (append-only RiskProfileSignoffV1, verifizierte Decision, CAS).
    from services import risk_profile_signoff as signoff_service
    from services.advisory_report_cache import invalidate_mandate as invalidate_advisory_cache

    result = signoff_service.record_signoff(
        db,
        mandate=mandate,
        actor=current_user,
        method=signoff_service.METHOD_PORTAL,
        note=None,
        ip_address=_extract_client_ip(request),
    )
    invalidate_advisory_cache(mandate_id)
    return result
