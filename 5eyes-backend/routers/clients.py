from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.clients import Client, ClientNationality, ClientOptHistory
from models.wealth import Cashflow
from schemas.clients import (
    ClientCreate, ClientUpdate, ClientResponse,
    NationalityCreate, NationalityResponse,
    OptHistoryCreate, OptHistoryResponse,
    WealthSummaryResponse, CashflowSummaryResponse,
    CashflowYearRow, CashflowProjectionResponse,
)
from services.auth import get_client_for_user_or_404, get_current_user, has_global_client_access, require_advisor
from services.audit import log
from services.cashflow_timeline import totals_for_year

router = APIRouter(prefix="/clients", tags=["Kunden"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_client_or_404(client_id: str, db: Session, current_user: User) -> Client:
    return get_client_for_user_or_404(client_id, db, current_user)


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ClientResponse])
def list_clients(
    search: str = Query(None),
    advisor_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Client).filter(Client.deleted_at.is_(None))
    if not has_global_client_access(current_user):
        q = q.filter(Client.advisor_id == current_user.id)
    if search:
        safe = search.replace('%', r'\%').replace('_', r'\_')
        like = f"%{safe}%"
        q = q.filter(
            (Client.first_name.ilike(like, escape='\\')) |
            (Client.last_name.ilike(like, escape='\\')) |
            (Client.client_number.ilike(like, escape='\\'))
        )
    if advisor_id:
        q = q.filter(Client.advisor_id == advisor_id)
    return q.order_by(Client.last_name, Client.first_name).all()


@router.post("", response_model=ClientResponse, status_code=201)
def create_client(
    body: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    existing = db.query(Client).filter(
        Client.client_number == body.client_number,
        Client.deleted_at.is_(None)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Kundennummer bereits vergeben")
    now = _now()
    advisor_id = body.advisor_id
    if not has_global_client_access(current_user):
        advisor_id = current_user.id
    client = Client(
        id=new_uuid(), created_at=now, updated_at=now,
        **{**body.model_dump(), "advisor_id": advisor_id}
    )
    db.add(client)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client.id, action="CREATE",
        client_id=client.id)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return _get_client_or_404(client_id, db, current_user)


@router.put("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: str,
    body: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = _get_client_or_404(client_id, db, current_user)
    updates = body.model_dump(exclude_unset=True)
    if "advisor_id" in updates and not has_global_client_access(current_user):
        if updates["advisor_id"] != current_user.id:
            raise HTTPException(status_code=403, detail="Berater duerfen Kunden nicht einem anderen Berater zuweisen")
        updates["advisor_id"] = current_user.id
    for field, value in updates.items():
        setattr(client, field, value)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client_id, action="UPDATE",
        client_id=client_id)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = _get_client_or_404(client_id, db, current_user)
    client.deleted_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client_id, action="DELETE",
        client_id=client_id)
    db.commit()


# ── Nationalities ──────────────────────────────────────────────────────────────

@router.get("/{client_id}/nationalities", response_model=list[NationalityResponse])
def list_nationalities(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_client_or_404(client_id, db, current_user)
    return db.query(ClientNationality).filter(ClientNationality.client_id == client_id).all()


@router.post("/{client_id}/nationalities", response_model=NationalityResponse, status_code=201)
def add_nationality(
    client_id: str,
    body: NationalityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    _get_client_or_404(client_id, db, current_user)
    if body.is_primary:
        # Clear existing primary
        db.query(ClientNationality).filter(
            ClientNationality.client_id == client_id,
            ClientNationality.is_primary == 1
        ).update({"is_primary": 0})
    nat = ClientNationality(
        id=new_uuid(), client_id=client_id,
        country_code=body.country_code,
        is_primary=1 if body.is_primary else 0,
        created_at=_now()
    )
    db.add(nat)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="client_nationalities", record_id=nat.id, action="CREATE",
        client_id=client_id)
    db.commit()
    db.refresh(nat)
    return nat


# ── Opt History ────────────────────────────────────────────────────────────────

@router.get("/{client_id}/opt-history", response_model=list[OptHistoryResponse])
def get_opt_history(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_client_or_404(client_id, db, current_user)
    return db.query(ClientOptHistory).filter(
        ClientOptHistory.client_id == client_id
    ).order_by(ClientOptHistory.documented_at.desc()).all()


@router.post("/{client_id}/opt-history", response_model=OptHistoryResponse, status_code=201)
def add_opt_history(
    client_id: str,
    body: OptHistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = _get_client_or_404(client_id, db, current_user)
    now = _now()
    entry = ClientOptHistory(
        id=new_uuid(), client_id=client_id,
        event_type=body.event_type,
        from_classification=body.from_classification,
        to_classification=body.to_classification,
        client_requested=1 if body.client_requested else 0,
        documented_by=current_user.id,
        documented_at=now,
        document_id=body.document_id,
        notes=body.notes,
        created_at=now
    )
    # Update classification on client
    client.client_classification = body.to_classification
    db.add(entry)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="client_opt_history", record_id=entry.id, action="CREATE",
        client_id=client_id)
    db.commit()
    db.refresh(entry)
    return entry


# ── Wealth & Cashflow Summary Views ───────────────────────────────────────────

@router.get("/{client_id}/wealth-summary", response_model=WealthSummaryResponse)
def wealth_summary(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_client_or_404(client_id, db, current_user)
    row = db.execute(
        text("SELECT * FROM v_client_wealth_summary WHERE client_id = :id"),
        {"id": client_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keine Vermögensdaten")
    d = dict(row._mapping)
    return WealthSummaryResponse(
        **d,
        gross_wealth_chf=d["gross_wealth_rappen"] / 100,
        liabilities_chf=d["liabilities_rappen"] / 100,
        net_worth_chf=d["net_worth_rappen"] / 100,
        advisory_wealth_chf=d["advisory_wealth_rappen"] / 100,
    )


@router.get("/{client_id}/cashflow-summary", response_model=CashflowSummaryResponse)
def cashflow_summary(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    client = _get_client_or_404(client_id, db, current_user)
    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    totals = totals_for_year(cashflows)
    client_name = f"{client.first_name or ''} {client.last_name or ''}".strip() or client.client_number or client.id
    return CashflowSummaryResponse(
        client_id=client_id,
        client_name=client_name,
        summary_year=totals["year"],
        total_income_rappen=totals["income_rappen"],
        total_expense_rappen=totals["expense_rappen"],
        surplus_rappen=totals["net_rappen"],
        total_income_chf=totals["income_rappen"] / 100,
        total_expense_chf=totals["expense_rappen"] / 100,
        surplus_chf=totals["net_rappen"] / 100,
    )


@router.get("/{client_id}/cashflow-projection", response_model=CashflowProjectionResponse)
def cashflow_projection(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import date as _date

    _get_client_or_404(client_id, db, current_user)
    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    start_year = _date.today().year
    rows = []
    for offset in range(5):
        yr = start_year + offset
        t = totals_for_year(cashflows, yr)
        rows.append(CashflowYearRow(
            year=yr,
            income_rappen=t["income_rappen"],
            expense_rappen=t["expense_rappen"],
            net_rappen=t["net_rappen"],
        ))
    return CashflowProjectionResponse(
        client_id=client_id,
        start_year=start_year,
        years=rows,
    )
