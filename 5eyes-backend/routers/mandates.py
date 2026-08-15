from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from types import SimpleNamespace
from database import get_db, new_uuid
from models.users import User
from models.clients import Client
from models.mandates import Mandate
from models.tenant import Tenant
from schemas.mandates import MandateCreate, MandateUpdate, MandateResponse
from services.auth import get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, require_advisor
from services.audit import log
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer Mandat-Aenderungen.
from routers.auth import _extract_client_ip
from services.data_classification import enforce_data_classification
from services.quota import assert_within_quota
from services.tenant_licensing import enforce_discretionary_management_license
from services.mandate_model_inputs import (
    MandateModelInputError,
    validate_mandate_model_inputs,
)

router = APIRouter(tags=["Mandate"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


@router.get("/clients/{client_id}/mandates", response_model=list[MandateResponse])
def list_mandates(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_client_for_user_or_404(client_id, db, current_user)
    return db.query(Mandate).filter(
        Mandate.client_id == client_id, Mandate.deleted_at.is_(None)
    ).all()


@router.post("/clients/{client_id}/mandates", response_model=MandateResponse, status_code=201)
def create_mandate(
    client_id: str,
    body: MandateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    enforce_data_classification(body.data_classification)
    client = get_client_for_user_or_404(client_id, db, current_user)
    existing = db.query(Mandate).filter(
        Mandate.mandate_number == body.mandate_number,
        Mandate.deleted_at.is_(None)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Mandatsnummer bereits vergeben")
    now = _now()
    # E1 (2026-06-12): tenant_id vom Parent-Client vererben (Fallback: Tenant des
    # anlegenden Users). Damit neue Mandate NIE NULL-tenant_id haben -> Vorbe-
    # dingung fuer spaetere NOT-NULL-Constraint + Entfernen der 'OR IS NULL'-Klausel.
    mandate_tenant_id = getattr(client, "tenant_id", None) or getattr(current_user, "tenant_id", None)
    assert_within_quota(db, mandate_tenant_id, "mandates")
    tenant = db.query(Tenant).filter(Tenant.id == mandate_tenant_id).first() if mandate_tenant_id else None
    # 2026-08-09 (FINIG-Gate): nur Firmen mit FINIG-Bewilligung/AO-Anschluss
    # duerfen mandate_type="Vermögensverwaltung" ueberhaupt waehlen, siehe
    # services/tenant_licensing.py.
    enforce_discretionary_management_license(tenant, body.mandate_type)
    # 2026-08-01 (Onboarding, Entscheid Auftraggeber): explizite Wahl geht
    # vor; sonst Default aus dem Standort der lizenznehmenden Firma
    # (Tenant.home_jurisdiction) -- Firmen mit Kunden in mehreren Laendern
    # koennen jederzeit ein anderes Land pro Mandat waehlen (body.jurisdiction).
    mandate_jurisdiction = body.jurisdiction
    if not mandate_jurisdiction and tenant:
        mandate_jurisdiction = getattr(tenant, "home_jurisdiction", None)
    try:
        validate_mandate_model_inputs(
            body.model_copy(update={"jurisdiction": mandate_jurisdiction})
        )
    except MandateModelInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    mandate = Mandate(
        id=new_uuid(),
        client_id=client_id,
        tenant_id=mandate_tenant_id,
        mandate_number=body.mandate_number,
        mandate_type=body.mandate_type,
        status="Aktiv",
        base_currency=body.base_currency,
        advisory_language=body.advisory_language,
        depot_bank=body.depot_bank,
        depot_account_number=body.depot_account_number,
        investment_universe=body.investment_universe or "Standard",
        jurisdiction=mandate_jurisdiction,
        client_birth_year=body.client_birth_year,
        client_sex=body.client_sex,
        use_mortality_simulation=int(bool(body.use_mortality_simulation)),
        tax_jurisdiction=body.tax_jurisdiction,
        tax_overrides_json=body.tax_overrides_json,
        tax_estimate_in_cashflow_enabled=int(
            bool(body.tax_estimate_in_cashflow_enabled)
        ),
        opened_at=body.opened_at or date.today().isoformat(),
        created_at=now,
        updated_at=now,
    )
    db.add(mandate)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="mandates", record_id=mandate.id, action="CREATE",
        client_id=client_id, ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(mandate)
    return mandate


@router.get("/mandates/{mandate_id}", response_model=MandateResponse)
def get_mandate(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return _get_mandate_or_404(mandate_id, db, current_user)


@router.put("/mandates/{mandate_id}", response_model=MandateResponse)
def update_mandate(
    mandate_id: str,
    body: MandateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # MND-1 Fix: exclude_unset statt exclude_none — sonst lassen sich gesetzte
    # Felder (z.B. tax_jurisdiction, depot_bank) nie wieder leeren, weil null
    # verworfen wird. Mit exclude_unset werden genau die vom Client gesendeten
    # Felder geschrieben (inkl. explizitem null = Loeschen); nicht gesendete bleiben.
    updates = body.model_dump(exclude_unset=True)
    # 2026-07-25 (Generalaudit): data_classification hat kein DB-Spalten-
    # Aequivalent auf Mandate (nur Enforcement, analog Cashflow/Goal) --
    # muss VOR dem generischen setattr-Loop entfernt werden, sonst wuerde
    # setattr(mandate, "data_classification", ...) versucht.
    enforce_data_classification(updates.pop("data_classification", None))
    feature_input_fields = (
        "jurisdiction",
        "client_birth_year",
        "client_sex",
        "use_mortality_simulation",
        "tax_jurisdiction",
        "tax_overrides_json",
        "tax_estimate_in_cashflow_enabled",
        "default_building_blocks_json",
    )
    merged_feature_inputs = SimpleNamespace(**{
        field: updates.get(field, getattr(mandate, field, None))
        for field in feature_input_fields
    })
    try:
        validate_mandate_model_inputs(merged_feature_inputs)
    except MandateModelInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "mandate_type" in updates:
        # 2026-08-09 (FINIG-Gate): auch beim nachtraeglichen Umstellen eines
        # Mandats auf Vermögensverwaltung greift die Firmen-Freischaltung,
        # siehe services/tenant_licensing.py + create_mandate oben.
        mandate_tenant = db.query(Tenant).filter(Tenant.id == mandate.tenant_id).first() if mandate.tenant_id else None
        enforce_discretionary_management_license(mandate_tenant, updates["mandate_type"])
    for field, value in updates.items():
        setattr(mandate, field, value)
    mandate.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="mandates", record_id=mandate_id, action="UPDATE",
        client_id=mandate.client_id, ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(mandate)
    return mandate
