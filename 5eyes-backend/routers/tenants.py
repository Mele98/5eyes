"""Sprint T4 (2026-06-08): Tenant-Admin-API.

Endpoints fuer Tenant-Verwaltung (Tier 2 / Shared-Cloud only). In Tier 1 +
Tier 3 sind diese Endpoints deaktiviert via settings.tenant_admin_ui_enabled.

# Sicherheit
- Alle Endpoints require_super_admin (role='super_admin')
- Zusaetzlich: 503 wenn settings.tenant_admin_ui_enabled=False
- Tenant-Aenderungen werden auditiert via services.audit.log

# Workflow (Tier 2)
1. Super-Admin (5eyes-Operator) erstellt Tenant via POST /tenants
2. Super-Admin erstellt einen Tenant-Admin-User via existing /auth
3. Super-Admin weist den User dem Tenant zu via PUT /users/{id}/tenant
4. Tenant-Admin loggt sich ein, sieht nur seinen Tenant (via Auth-Layer T2+T3)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db, new_uuid
from models.client_login import ClientLogin
from models.clients import Client
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from schemas.tenants import (
    TenantCreate,
    TenantResponse,
    TenantSelfServiceUpdate,
    TenantUpdate,
    UserAssignTenantRequest,
)
from services.audit import log
from services.auth import require_admin, require_super_admin

router = APIRouter(prefix="/tenants", tags=["Tenants"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def _check_tenant_admin_ui_enabled() -> None:
    """Sprint T4: gemeinsamer Pre-Check fuer alle Tenant-Endpoints.

    Wenn settings.tenant_admin_ui_enabled=False (Tier 1 + 3) → 503.
    In Tier 2 (Shared-Cloud) ist es True, dann erlauben.
    """
    if not getattr(settings, "tenant_admin_ui_enabled", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Tenant-Admin-API ist nur in Tier-2-Deployments aktiv. "
                "In Tier 1 / Tier 3 gibt es genau einen Tenant ('main')."
            ),
        )


@router.get("/me", response_model=TenantResponse)
def get_my_tenant(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """2026-08-01 (Onboarding): liefert die eigene Firma (current_user.
    tenant_id) -- TIER-UNABHAENGIG, im Gegensatz zu GET /tenants/{id}
    (Tier 2 only via _check_tenant_admin_ui_enabled). Muss VOR der
    /{tenant_id}-Route registriert sein, sonst matcht FastAPI 'me' als
    tenant_id-Pfadparameter."""
    tenant_id = getattr(current_user, "tenant_id", None) or DEFAULT_TENANT_ID
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.deleted_at.is_(None),
    ).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Eigene Firma nicht gefunden")
    return tenant


@router.put("/me", response_model=TenantResponse)
def update_my_tenant(
    body: TenantSelfServiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """2026-08-01 (Onboarding): erlaubt einem normalen Firmen-Admin (nicht
    super_admin), Firmenname/Standort der EIGENEN Firma zu pflegen --
    z.B. nachtraeglich, falls bei der Ersteinrichtung (/auth/bootstrap-admin)
    nichts oder etwas Falsches angegeben wurde. Bewusst schmaleres Schema
    (TenantSelfServiceUpdate) als das super_admin-only PUT /tenants/{id}:
    kein Zugriff auf hosting_tier/license_status/max_users etc."""
    tenant_id = getattr(current_user, "tenant_id", None) or DEFAULT_TENANT_ID
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.deleted_at.is_(None),
    ).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Eigene Firma nicht gefunden")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tenant, field, value)
    tenant.updated_at = _now_iso()
    log(
        db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="tenants", record_id=tenant.id, action="UPDATE",
    )
    db.commit()
    db.refresh(tenant)
    return tenant


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Erstellt einen neuen Tenant (Lizenz-Nehmer).

    Pre-Check: settings.tenant_admin_ui_enabled muss True sein (Tier 2).
    """
    _check_tenant_admin_ui_enabled()
    # Slug-Konflikt-Check
    existing = db.query(Tenant).filter(Tenant.slug == body.slug).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{body.slug}' ist bereits vergeben.",
        )
    now = _now_iso()
    tenant = Tenant(
        id=new_uuid(),
        display_name=body.display_name,
        slug=body.slug,
        hosting_tier=body.hosting_tier,
        license_status=body.license_status,
        license_valid_until=body.license_valid_until,
        max_users=body.max_users,
        max_mandates=body.max_mandates,
        storage_quota_mb=body.storage_quota_mb,
        default_retrocession_reimbursement=1 if body.default_retrocession_reimbursement else 0,
        home_jurisdiction=body.home_jurisdiction,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(tenant)
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="tenants",
        record_id=tenant.id,
        action="CREATE",
    )
    try:
        db.commit()
    except IntegrityError:
        # 2026-07-25 (Generalaudit, Wave 13): der Pre-Check oben ist TOCTOU-
        # racy -- analog zum bereits gefixten client_number-Fund in
        # routers/clients.py::create_client. Der UNIQUE-Constraint auf
        # slug (models/tenant.py) verhindert zuverlaessig ein Duplikat,
        # gab dem VERLIERENDEN Request bisher aber einen 500 statt 409.
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' ist bereits vergeben.")
    db.refresh(tenant)
    return tenant


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Listet alle aktiven Tenants. Tier 2 only."""
    _check_tenant_admin_ui_enabled()
    rows = (
        db.query(Tenant)
        .filter(Tenant.deleted_at.is_(None))
        .order_by(Tenant.created_at.desc())
        .all()
    )
    return rows


@router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Liest einen einzelnen Tenant."""
    _check_tenant_admin_ui_enabled()
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .first()
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant nicht gefunden",
        )
    return tenant


@router.put("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Partial-Update eines Tenants. Tier 2 only."""
    _check_tenant_admin_ui_enabled()
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .first()
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant nicht gefunden",
        )
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tenant, field, value)
    tenant.updated_at = _now_iso()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="tenants",
        record_id=tenant.id,
        action="UPDATE",
    )
    db.commit()
    db.refresh(tenant)
    return tenant


@router.put("/{tenant_id}/users/{user_id}/assign", response_model=dict)
def assign_user_to_tenant(
    tenant_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Weist einen User einem Tenant zu (Super-Admin only)."""
    _check_tenant_admin_ui_enabled()
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        .first()
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden")
    user = (
        db.query(User)
        .filter(User.id == user_id, User.deleted_at.is_(None))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    # 2026-07-26 (Generalaudit-Nachtrag): Guard gegen stille Verwaisung --
    # Client.tenant_id/ClientLogin bleiben beim ALTEN Tenant stehen (kein
    # Cross-Tenant-Leak), wuerden fuer den User nach der Neuzuweisung aber
    # unsichtbar (Tenant-Filter matcht client.tenant_id gegen den NEUEN
    # user.tenant_id, kein Treffer mehr). Blockiert die Neuzuweisung mit
    # klarer Fehlermeldung statt die Dateninkonsistenz stillschweigend
    # zu erzeugen -- Admin muss die Kunden zuerst umziehen oder den
    # Advisor-Owner wechseln.
    if user.tenant_id and str(user.tenant_id).strip() != str(tenant_id).strip():
        active_clients = db.query(Client).filter(
            Client.advisor_id == user.id,
            Client.deleted_at.is_(None),
        ).count()
        if active_clients > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"User betreut noch {active_clients} aktive Kunden im bisherigen "
                    "Tenant -- Neuzuweisung wuerde diese fuer den User unsichtbar machen. "
                    "Bitte zuerst die Kunden umziehen oder den Advisor-Owner wechseln."
                ),
            )
        active_login = db.query(ClientLogin).filter(
            ClientLogin.user_id == user.id,
            ClientLogin.is_active == 1,
        ).first()
        if active_login is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "User ist als aktiver Kunden-Login mit einem Client im bisherigen "
                    "Tenant verknuepft -- Neuzuweisung wuerde diese Verknuepfung "
                    "inkonsistent machen."
                ),
            )
    user.tenant_id = tenant_id
    user.updated_at = _now_iso()
    # Sprint T4: audit_log.action ist auf festes ENUM begrenzt; wir nutzen
    # 'UPDATE' weil der User-Datensatz aktualisiert wird (tenant_id-Spalte).
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="users",
        record_id=user.id,
        action="UPDATE",
    )
    db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "tenant_id": tenant_id,
        "assigned_at": user.updated_at,
    }
