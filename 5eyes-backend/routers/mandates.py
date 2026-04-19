from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.clients import Client
from models.mandates import Mandate
from schemas.mandates import MandateCreate, MandateUpdate, MandateResponse
from services.auth import get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, require_advisor
from services.audit import log

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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = get_client_for_user_or_404(client_id, db, current_user)
    existing = db.query(Mandate).filter(
        Mandate.mandate_number == body.mandate_number,
        Mandate.deleted_at.is_(None)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Mandatsnummer bereits vergeben")
    now = _now()
    mandate = Mandate(
        id=new_uuid(),
        client_id=client_id,
        mandate_number=body.mandate_number,
        mandate_type=body.mandate_type,
        status="Aktiv",
        base_currency=body.base_currency,
        advisory_language=body.advisory_language,
        depot_bank=body.depot_bank,
        depot_account_number=body.depot_account_number,
        opened_at=body.opened_at or date.today().isoformat(),
        created_at=now,
        updated_at=now,
    )
    db.add(mandate)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="mandates", record_id=mandate.id, action="CREATE",
        client_id=client_id)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(mandate, field, value)
    mandate.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="mandates", record_id=mandate_id, action="UPDATE",
        client_id=mandate.client_id)
    db.commit()
    db.refresh(mandate)
    return mandate
