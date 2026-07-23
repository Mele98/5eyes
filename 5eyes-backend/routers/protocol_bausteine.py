"""Bug-#13a (2026-06-07): CRUD-Endpoints fuer Beratungsprotokoll-Bausteine.

Bibliotheks-Sicht
-----------------
- GET    /protocol-bausteine           Liste (mit Filter category)
- POST   /protocol-bausteine           Neuer Baustein in Berater-Bibliothek
- PUT    /protocol-bausteine/{id}      Update (nur Eigentuemer/Admin)
- DELETE /protocol-bausteine/{id}      Soft-Delete (nur Eigentuemer/Admin)

Globale Bausteine (advisor_id is None) sind fuer alle Berater sichtbar,
aber nur durch admin-Role editier-/loeschbar.

Mandate-Selektion
-----------------
- GET /mandates/{mandate_id}/protocol-bausteine  Ausgewaehlte Bausteine fuer
  das Mandat (sortiert).
- PUT /mandates/{mandate_id}/protocol-bausteine  Setzt die Auswahl (replace).
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.mandates import Mandate
from models.protocol_bausteine import (
    MandateBausteinSelection,
    ProtocolBaustein,
)
from models.review import AuditLog
from models.users import User
from schemas.protocol_bausteine import (
    BausteinCreate,
    BausteinResponse,
    BausteinUpdate,
    MandateBausteinSelectionItem,
    MandateBausteinSelectionResponse,
    MandateBausteinSelectionUpdate,
)
from services.auth import (
    get_current_user,
    get_mandate_for_user_or_404,
    require_advisor,
)


router = APIRouter(tags=["Protocol-Bausteine"])


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _log(db: Session, *, user: User, table: str, record_id: str, action: str) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.id,
            user_name=user.full_name or user.username,
            table_name=table,
            record_id=record_id,
            action=action,
            created_at=_now(),
        )
    )


def _baustein_tenant_visible(baustein: ProtocolBaustein, user: User) -> bool:
    """SEC (2026-07-23, unabhaengiges Audit): Mandanten-Trennung fuer die
    Baustein-Bibliothek. Vorher pruefte diese Bibliothek (anders als jeder
    andere Router in dieser Codebase) NIE tenant_id -- ein Admin sah/edierte/
    loeschte automatisch ALLE Bausteine aller Tenants (list_bausteine liess
    admin komplett ungefiltert, _can_edit_baustein gab admin blanko True).
    Mirror von services.auth._apply_tenant_filter_to_client_query:
    - User ohne tenant_id (Legacy/Tier1): immer sichtbar (kein Filter).
    - Baustein ohne tenant_id (Legacy/Pre-T1-Baustein): sichtbar, ausser im
      Strict-Modus (dort NUR exakter Tenant-Match, analog Client/Mandate).
    - Sonst: tenant_id muss exakt matchen.
    """
    user_tid = str(getattr(user, "tenant_id", None) or "").strip()
    if not user_tid:
        return True
    baustein_tid = str(getattr(baustein, "tenant_id", None) or "").strip()
    if not baustein_tid:
        from config import settings as _settings
        from services.auth import _effective_strict_tenant_isolation
        return not _effective_strict_tenant_isolation(_settings)
    return baustein_tid == user_tid


def _apply_tenant_filter_to_baustein_query(query, user: User):
    """SEC (2026-07-23): Query-Variante von _baustein_tenant_visible, fuer
    list_bausteine -- IMMER angewendet, auch fuer admin (spiegelt den
    etablierten Kommentar/Pattern 'Tenant-Filter IMMER anwenden -- auch fuer
    globale Admins' aus routers/clients.py::list_clients)."""
    user_tid = str(getattr(user, "tenant_id", None) or "").strip()
    if not user_tid:
        return query
    from sqlalchemy import or_
    from config import settings as _settings
    from services.auth import _effective_strict_tenant_isolation
    if _effective_strict_tenant_isolation(_settings):
        return query.filter(ProtocolBaustein.tenant_id == user_tid)
    return query.filter(
        or_(ProtocolBaustein.tenant_id == user_tid, ProtocolBaustein.tenant_id.is_(None))
    )


def _can_edit_baustein(baustein: ProtocolBaustein, user: User) -> bool:
    """Globale (advisor_id IS NULL) Bausteine darf nur admin aendern,
    eigene Bausteine darf der Berater selbst. In jedem Fall zusaetzlich
    tenant-sichtbar (siehe _baustein_tenant_visible)."""
    if not _baustein_tenant_visible(baustein, user):
        return False
    if user.role == "admin":
        return True
    if baustein.advisor_id and baustein.advisor_id == user.id:
        return True
    return False


# ---------------------------------------------------------------------------
# Bibliotheks-CRUD
# ---------------------------------------------------------------------------


@router.get("/protocol-bausteine", response_model=list[BausteinResponse])
def list_bausteine(
    category: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Berater sieht: eigene Bausteine + global (advisor_id IS NULL).
    Admin sieht: alles -- aber IMMER nur innerhalb des eigenen Tenants (siehe
    _apply_tenant_filter_to_baustein_query; SEC 2026-07-23)."""
    q = db.query(ProtocolBaustein).filter(ProtocolBaustein.deleted_at.is_(None))
    if current_user.role != "admin":
        q = q.filter(
            (ProtocolBaustein.advisor_id == current_user.id)
            | (ProtocolBaustein.advisor_id.is_(None))
        )
    # SEC (2026-07-23): Tenant-Filter IMMER anwenden -- auch fuer globale
    # Admins. Sonst sieht ein tenant-gebundener Admin (Firma A) die komplette
    # Baustein-Bibliothek einer fremden Firma B (Cross-Tenant-Leak).
    q = _apply_tenant_filter_to_baustein_query(q, current_user)
    if category:
        q = q.filter(ProtocolBaustein.category == category)
    if not include_inactive:
        q = q.filter(ProtocolBaustein.is_active == 1)
    return q.order_by(
        ProtocolBaustein.category.is_(None),
        ProtocolBaustein.category,
        ProtocolBaustein.sort_order,
        ProtocolBaustein.title,
    ).all()


@router.post(
    "/protocol-bausteine",
    response_model=BausteinResponse,
    status_code=201,
)
def create_baustein(
    body: BausteinCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    now = _now()
    b = ProtocolBaustein(
        id=str(uuid.uuid4()),
        advisor_id=current_user.id,
        tenant_id=getattr(current_user, "tenant_id", None),
        title=body.title.strip(),
        content_md=body.content_md or "",
        category=(body.category or None),
        sort_order=int(body.sort_order or 0),
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(b)
    _log(db, user=current_user, table="protocol_bausteine", record_id=b.id, action="CREATE")
    db.commit()
    db.refresh(b)
    return b


@router.put("/protocol-bausteine/{baustein_id}", response_model=BausteinResponse)
def update_baustein(
    baustein_id: str,
    body: BausteinUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    b = (
        db.query(ProtocolBaustein)
        .filter(
            ProtocolBaustein.id == baustein_id,
            ProtocolBaustein.deleted_at.is_(None),
        )
        .first()
    )
    if not b:
        raise HTTPException(status_code=404, detail="Baustein nicht gefunden")
    if not _can_edit_baustein(b, current_user):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf diesen Baustein")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "title" and value is not None:
            value = str(value).strip()
        setattr(b, field, value)
    b.updated_at = _now()
    _log(db, user=current_user, table="protocol_bausteine", record_id=b.id, action="UPDATE")
    db.commit()
    db.refresh(b)
    return b


@router.delete("/protocol-bausteine/{baustein_id}", status_code=204)
def delete_baustein(
    baustein_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    b = (
        db.query(ProtocolBaustein)
        .filter(
            ProtocolBaustein.id == baustein_id,
            ProtocolBaustein.deleted_at.is_(None),
        )
        .first()
    )
    if not b:
        raise HTTPException(status_code=404, detail="Baustein nicht gefunden")
    if not _can_edit_baustein(b, current_user):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf diesen Baustein")
    b.deleted_at = _now()
    b.is_active = 0
    _log(db, user=current_user, table="protocol_bausteine", record_id=b.id, action="DELETE")
    db.commit()


# ---------------------------------------------------------------------------
# Mandate-Selektion
# ---------------------------------------------------------------------------


@router.get(
    "/mandates/{mandate_id}/protocol-bausteine",
    response_model=list[MandateBausteinSelectionResponse],
)
def list_mandate_selections(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # SECURITY (Mandanten-Trennung): kanonischer Helper validiert Ownership
    # (Client.advisor_id fuer non-admins) UND Tenant-Filter, statt nur id+deleted_at.
    get_mandate_for_user_or_404(mandate_id, db, current_user)
    rows = (
        db.query(MandateBausteinSelection, ProtocolBaustein)
        .join(
            ProtocolBaustein,
            ProtocolBaustein.id == MandateBausteinSelection.baustein_id,
        )
        .filter(MandateBausteinSelection.mandate_id == mandate_id)
        .order_by(MandateBausteinSelection.sort_order, ProtocolBaustein.title)
        .all()
    )
    result: list[MandateBausteinSelectionResponse] = []
    for sel, baustein in rows:
        result.append(
            MandateBausteinSelectionResponse(
                id=sel.id,
                mandate_id=sel.mandate_id,
                baustein_id=sel.baustein_id,
                sort_order=sel.sort_order,
                custom_override_md=sel.custom_override_md,
                created_at=sel.created_at,
                updated_at=sel.updated_at,
                title=baustein.title,
                content_md=baustein.content_md,
                category=baustein.category,
            )
        )
    return result


@router.put(
    "/mandates/{mandate_id}/protocol-bausteine",
    response_model=list[MandateBausteinSelectionResponse],
)
def replace_mandate_selections(
    mandate_id: str,
    body: MandateBausteinSelectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Replace-Semantik: die uebergebene Liste IST die neue Selektion.
    Vorhandene Eintraege fuer das Mandat werden entfernt, die neuen gesetzt.
    """
    # SECURITY (Mandanten-Trennung): kanonischer Helper validiert Ownership
    # (Client.advisor_id fuer non-admins) UND Tenant-Filter, statt nur id+deleted_at.
    get_mandate_for_user_or_404(mandate_id, db, current_user)

    # Bausteine validieren — alle muessen existieren und vom User sichtbar sein.
    requested_ids = [item.baustein_id for item in body.selections]
    if requested_ids:
        bausteine = (
            db.query(ProtocolBaustein)
            .filter(
                ProtocolBaustein.id.in_(requested_ids),
                ProtocolBaustein.deleted_at.is_(None),
            )
            .all()
        )
        found_ids = {b.id for b in bausteine}
        missing = set(requested_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannte Baustein-IDs: {sorted(missing)}",
            )
        # SEC (2026-07-23, unabhaengiges Audit): Tenant-Sichtbarkeit gilt fuer
        # ALLE Rollen (auch admin) -- sonst koennte ein Mandat einen Baustein
        # eines FREMDEN Tenants in sein Beratungsprotokoll ziehen (Content-
        # Leak zwischen Firmen). Vorher pruefte dieser Block nur advisor_id
        # und nur fuer Nicht-Admins.
        for b in bausteine:
            if not _baustein_tenant_visible(b, current_user):
                raise HTTPException(
                    status_code=403,
                    detail=f"Baustein {b.id} gehoert einem anderen Mandanten",
                )
        if current_user.role != "admin":
            for b in bausteine:
                if b.advisor_id and b.advisor_id != current_user.id:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Baustein {b.id} gehoert einem anderen Berater",
                    )

    # Replace: alte Selektionen weg, neue rein.
    db.query(MandateBausteinSelection).filter(
        MandateBausteinSelection.mandate_id == mandate_id
    ).delete(synchronize_session=False)

    now = _now()
    for item in body.selections:
        db.add(
            MandateBausteinSelection(
                id=str(uuid.uuid4()),
                mandate_id=mandate_id,
                baustein_id=item.baustein_id,
                sort_order=int(item.sort_order or 0),
                custom_override_md=item.custom_override_md,
                created_at=now,
                updated_at=now,
            )
        )
    _log(
        db,
        user=current_user,
        table="mandate_baustein_selections",
        record_id=mandate_id,
        action="REPLACE",
    )
    db.commit()
    return list_mandate_selections(
        mandate_id=mandate_id, db=db, current_user=current_user
    )
