import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.clients import Client
from models.wealth import WealthPosition, Cashflow, Goal, PlanningAssumption
from schemas.wealth import (
    WealthPositionCreate, WealthPositionUpdate, WealthPositionResponse,
    CashflowCreate, CashflowUpdate, CashflowResponse,
    GoalCreate, GoalUpdate, GoalResponse,
    PlanningAssumptionCreate, PlanningAssumptionResponse,
)
from services.auth import get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, require_advisor
from services.audit import log
from services.cashflow_timeline import SUPPORTED_FREQUENCIES, normalize_frequency, normalize_nature

router = APIRouter(tags=["Vermögen & Ziele"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _normalize_cashflow_date(value) -> str | None:
    """C10.3: Normalisiert YYYY-MM nach YYYY-MM-01, erlaubt YYYY-MM-DD,
    leeren String -> None. Alles andere -> 422."""
    raw = str(value or "").strip()
    if not raw:
        return None
    # YYYY-MM (Monat-Praezision) -> ersten Tag des Monats
    if len(raw) == 7 and raw[4:5] == "-" and raw[:4].isdigit() and raw[5:7].isdigit():
        candidate = raw + "-01"
    else:
        candidate = raw[:10]
    try:
        date.fromisoformat(candidate)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"Ungueltiges Datumsformat: {value!r} (erwartet YYYY-MM-DD oder YYYY-MM)",
        )
    return candidate


def _normalize_cashflow_timing_precision(value) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    mapping = {
        "day": "day",
        "date": "day",
        "exact": "day",
        "month": "month",
        "monat": "month",
        "monatjahr": "month",
    }
    return mapping.get(raw)


def _normalize_cashflow_payload(data: dict, existing: Cashflow | None = None) -> dict:
    payload = dict(data)
    frequency = normalize_frequency(payload.get("frequency", getattr(existing, "frequency", None)))
    if frequency not in SUPPORTED_FREQUENCIES:
        raise HTTPException(status_code=422, detail="Ungültige Cashflow-Frequenz")
    nature = normalize_nature(payload.get("nature", getattr(existing, "nature", None)), frequency)
    valid_from = _normalize_cashflow_date(payload.get("valid_from", getattr(existing, "valid_from", None)))
    valid_until = _normalize_cashflow_date(payload.get("valid_until", getattr(existing, "valid_until", None)))
    timing_precision = _normalize_cashflow_timing_precision(payload.get("timing_precision", getattr(existing, "timing_precision", None)))
    amount_rappen = payload.get("amount_rappen", getattr(existing, "amount_rappen", None))
    gross_amount_rappen = payload.get("gross_amount_rappen", getattr(existing, "gross_amount_rappen", None))
    tax_amount_rappen = payload.get("tax_amount_rappen", getattr(existing, "tax_amount_rappen", None))

    amount_rappen = int(amount_rappen or 0)
    gross_amount_rappen = None if gross_amount_rappen in (None, "") else int(gross_amount_rappen)
    tax_amount_rappen = None if tax_amount_rappen in (None, "") else int(tax_amount_rappen)

    if gross_amount_rappen is not None and gross_amount_rappen < 0:
        raise HTTPException(status_code=422, detail="Bruttobetrag darf nicht negativ sein")
    if tax_amount_rappen is not None and tax_amount_rappen < 0:
        raise HTTPException(status_code=422, detail="Kapitalbezugssteuer darf nicht negativ sein")
    if gross_amount_rappen is not None and gross_amount_rappen < amount_rappen:
        raise HTTPException(status_code=422, detail="Bruttobetrag darf nicht kleiner als der Nettozufluss sein")
    if gross_amount_rappen is not None and tax_amount_rappen is not None and tax_amount_rappen > gross_amount_rappen:
        raise HTTPException(status_code=422, detail="Kapitalbezugssteuer darf nicht grösser als der Bruttobetrag sein")

    if frequency == "einmalig" or nature == "einmalig":
        nature = "einmalig"
        timing_precision = timing_precision or "day"
        if timing_precision not in {"day", "month"}:
            raise HTTPException(status_code=422, detail="Ungültige Zeitpräzision für einmaligen Cashflow")
        if not valid_from and valid_until:
            valid_from = valid_until
        if not valid_from:
            raise HTTPException(status_code=422, detail="Einmalige Cashflows benoetigen ein Datum")
        valid_until = valid_from
    elif valid_from and valid_until and valid_until < valid_from:
        raise HTTPException(status_code=422, detail="Enddatum darf nicht vor dem Startdatum liegen")
    else:
        timing_precision = None

    payload["frequency"] = frequency
    payload["nature"] = nature
    payload["valid_from"] = valid_from
    payload["valid_until"] = valid_until
    payload["timing_precision"] = timing_precision
    payload["amount_rappen"] = amount_rappen
    payload["gross_amount_rappen"] = gross_amount_rappen
    payload["tax_amount_rappen"] = tax_amount_rappen
    return payload


def _normalize_goal_date(value) -> str | None:
    raw = str(value or "").strip()[:10]
    return raw or None


def _parse_goal_date(value) -> date | None:
    raw = _normalize_goal_date(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültiges Datumsformat im Ziel")


def _goal_horizon_from_date(target: date | None) -> int | None:
    if not target:
        return None
    delta_days = (target - date.today()).days
    if delta_days <= 0:
        return 1
    return max(1, int((delta_days + 364) // 365))


def _normalize_goal_payload(data: dict, existing: Goal | None = None) -> dict:
    payload = dict(data)
    goal_type = payload.get("goal_type", getattr(existing, "goal_type", None))
    start_date = _normalize_goal_date(payload.get("start_date", getattr(existing, "start_date", None)))
    target_date = _normalize_goal_date(payload.get("target_date", getattr(existing, "target_date", None)))
    parsed_start = _parse_goal_date(start_date)
    parsed_target = _parse_goal_date(target_date)
    if parsed_start and parsed_target and parsed_target < parsed_start:
        raise HTTPException(status_code=422, detail="Zieldatum darf nicht vor dem Startdatum liegen")

    if goal_type == "Einmalige_Ausgabe":
        payload["frequency"] = None
        payload["is_ongoing"] = False
        if not start_date and target_date:
            start_date = target_date
        if not target_date and start_date:
            target_date = start_date
    elif goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        payload["frequency"] = normalize_frequency(payload.get("frequency", getattr(existing, "frequency", None)))
        if not payload["frequency"] or payload["frequency"] == "einmalig":
            payload["frequency"] = "jährlich"
        payload["is_ongoing"] = bool(payload.get("is_ongoing", getattr(existing, "is_ongoing", True)))
    else:
        payload["frequency"] = None
        payload["is_ongoing"] = False

    derived_horizon = None
    if parsed_target:
        derived_horizon = _goal_horizon_from_date(parsed_target)
    elif parsed_start and goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        derived_horizon = _goal_horizon_from_date(parsed_start)

    raw_horizon = payload.get("horizon_years", getattr(existing, "horizon_years", None))
    payload["horizon_years"] = int(raw_horizon) if raw_horizon not in (None, "") else derived_horizon
    if payload["horizon_years"] is None:
        payload["horizon_years"] = 10
    payload["start_date"] = start_date
    payload["target_date"] = target_date
    return payload


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


_AMORTIZATION_LABEL_RE = re.compile(r"\b(tilgung|amortisation|amortization)\b", re.IGNORECASE)


def _is_amortization_label(label) -> bool:
    if not label:
        return False
    return bool(_AMORTIZATION_LABEL_RE.search(str(label)))


def _has_active_mortgage_liability(client_id: str, db: Session) -> bool:
    return db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id,
        WealthPosition.assignment == "Verbindlichkeit",
        WealthPosition.position_type == "Hypothek",
        WealthPosition.is_active == 1,
        WealthPosition.deleted_at.is_(None),
    ).first() is not None


def _validate_no_mortgage_amortization_double_count(
    client_id: str, payload: dict, db: Session, existing: Cashflow | None = None,
) -> None:
    """B3: Hypothek-Tilgung darf nicht als Cashflow erfasst werden, wenn fuer
    denselben Kunden eine aktive Hypothek-Liability existiert.

    Bilanziell ist Tilgung eine Reklassifikation (Vermoegen sinkt, Liability
    sinkt um denselben Betrag) - kein Aufwand. Wenn als Expense-Cashflow
    erfasst, sinkt das Vermoegen scheinbar doppelt -> falsche Reserve, falsche
    Asset-Allokation.

    Quellen: Swiss GAAP FER 16 §28-32, ASIP Standard 2.3, OR 957a.
    """
    cashflow_type = payload.get("cashflow_type")
    if cashflow_type is None and existing is not None:
        cashflow_type = existing.cashflow_type
    if str(cashflow_type or "") != "Expense":
        return
    label = payload.get("label")
    if label is None and existing is not None:
        label = existing.label
    if not _is_amortization_label(label):
        return
    if not _has_active_mortgage_liability(client_id, db):
        return
    raise HTTPException(
        status_code=422,
        detail=(
            "Hypothek-Tilgung darf nicht als Cashflow erfasst werden. "
            "Tilgung ist bilanziell eine Reklassifikation (Vermoegen und Liability "
            "sinken um denselben Betrag), kein Aufwand. Bitte nur Hypothek-Zinsen "
            "als Cashflow erfassen; die Tilgung wird ueber die Liability-Position "
            "verfolgt."
        ),
    )


def _validate_mortgage_link(client_id: str, data: dict, db: Session) -> None:
    linked_property_id = data.get("mortgage_linked_property_id")
    if not linked_property_id:
        return
    linked_property = db.query(WealthPosition).filter(
        WealthPosition.id == linked_property_id,
        WealthPosition.client_id == client_id,
        WealthPosition.position_type == "Immobilien",
        WealthPosition.is_active == 1,
        WealthPosition.deleted_at.is_(None),
    ).first()
    if not linked_property:
        raise HTTPException(
            status_code=422,
            detail="Verknüpfte Immobilie muss eine aktive Immobilien-Position desselben Kunden sein",
        )


# ── Wealth Positions ───────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/wealth-positions", response_model=list[WealthPositionResponse])
def list_wealth_positions(
    client_id: str,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """C10.1: Standardmaessig nur aktive Positionen. include_inactive=true
    fuer Admin-/Audit-Sicht."""
    get_client_for_user_or_404(client_id, db, current_user)
    query = db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None)
    )
    if not include_inactive:
        query = query.filter(WealthPosition.is_active == 1)
    return query.order_by(WealthPosition.assignment, WealthPosition.position_type).all()


@router.post("/clients/{client_id}/wealth-positions",
             response_model=WealthPositionResponse, status_code=201)
def create_wealth_position(
    client_id: str,
    body: WealthPositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = get_client_for_user_or_404(client_id, db, current_user)
    now = _now()
    data = body.model_dump()
    # Convert booleans to integers for SQLite
    for bool_field in ("pension_wef_possible", "is_available_for_goal_funding"):
        if bool_field in data and data[bool_field] is not None:
            data[bool_field] = 1 if data[bool_field] else 0
    _validate_mortgage_link(client_id, data, db)
    wp = WealthPosition(
        id=new_uuid(), client_id=client_id,
        is_active=1, created_at=now, updated_at=now,
        **data
    )
    db.add(wp)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="wealth_positions", record_id=wp.id, action="CREATE",
        client_id=client_id)
    db.commit()
    db.refresh(wp)
    return wp


_ALLOC_FIELDS = (
    "alloc_equities_bps", "alloc_bonds_bps", "alloc_real_estate_bps",
    "alloc_liquidity_bps", "alloc_alternatives_bps",
)


@router.put("/clients/{client_id}/wealth-positions/{wp_id}",
            response_model=WealthPositionResponse)
def update_wealth_position(
    client_id: str, wp_id: str,
    body: WealthPositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    get_client_for_user_or_404(client_id, db, current_user)
    wp = db.query(WealthPosition).filter(
        WealthPosition.id == wp_id,
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None)
    ).first()
    if not wp:
        raise HTTPException(status_code=404, detail="Vermögensposition nicht gefunden")
    # C10.2: exclude_unset erlaubt explizites Null-Setzen ("clear"). exclude_none
    # haette ein None-Update verschluckt und keine Felder gecleared.
    updates = body.model_dump(exclude_unset=True)
    # C10.2: Wenn alloc_*-Felder im Update sind, muss die GEMERGTE Verteilung
    # eine konsistente Summe ergeben (entweder alle 0 = Default-Mix wird genutzt
    # oder Summe = 10000). Partial-Updates duerfen keine 7000-Summe erzeugen.
    if any(f in updates for f in _ALLOC_FIELDS):
        merged = {f: int(updates.get(f, getattr(wp, f, 0)) or 0) for f in _ALLOC_FIELDS}
        total = sum(merged.values())
        if total != 0 and total != 10000:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Allokation muss zusammen 10000 bps oder alle 0 ergeben "
                    f"(aktuelle Summe: {total}). Bitte alle alloc_*-Felder zusammen "
                    f"updaten oder auf 0 zuruecksetzen."
                ),
            )
    _validate_mortgage_link(client_id, updates, db)
    for field, value in updates.items():
        if isinstance(value, bool):
            value = 1 if value else 0
        setattr(wp, field, value)
    # C10.2: updated_at darf nach Update nicht stale bleiben.
    wp.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="wealth_positions", record_id=wp_id, action="UPDATE",
        client_id=client_id)
    db.commit()
    db.refresh(wp)
    return wp


@router.delete("/clients/{client_id}/wealth-positions/{wp_id}", status_code=204)
def delete_wealth_position(
    client_id: str, wp_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    get_client_for_user_or_404(client_id, db, current_user)
    wp = db.query(WealthPosition).filter(
        WealthPosition.id == wp_id,
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None)
    ).first()
    if not wp:
        raise HTTPException(status_code=404, detail="Vermögensposition nicht gefunden")
    wp.deleted_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="wealth_positions", record_id=wp_id, action="DELETE",
        client_id=client_id)
    db.commit()


# ── Cashflows ──────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/cashflows", response_model=list[CashflowResponse])
def list_cashflows(
    client_id: str,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """C10.1: Standardmaessig nur aktive Cashflows. include_inactive=true
    fuer Admin-/Audit-Sicht."""
    get_client_for_user_or_404(client_id, db, current_user)
    query = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None)
    )
    if not include_inactive:
        query = query.filter(Cashflow.is_active == 1)
    return query.order_by(Cashflow.cashflow_type, Cashflow.label).all()


@router.post("/clients/{client_id}/cashflows",
             response_model=CashflowResponse, status_code=201)
def create_cashflow(
    client_id: str,
    body: CashflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = get_client_for_user_or_404(client_id, db, current_user)
    now = _now()
    data = _normalize_cashflow_payload(body.model_dump())
    _validate_no_mortgage_amortization_double_count(client_id, data, db)
    cf = Cashflow(
        id=new_uuid(), client_id=client_id,
        is_active=1, created_at=now, updated_at=now,
        is_inflation_linked=1 if data.get("is_inflation_linked") else 0,
        **{k: v for k, v in data.items() if k != "is_inflation_linked"}
    )
    db.add(cf)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="cashflows", record_id=cf.id, action="CREATE",
        client_id=client_id)
    db.commit()
    db.refresh(cf)
    return cf


@router.delete("/clients/{client_id}/cashflows/{cf_id}", status_code=204)
def delete_cashflow(
    client_id: str, cf_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    get_client_for_user_or_404(client_id, db, current_user)
    cf = db.query(Cashflow).filter(
        Cashflow.id == cf_id,
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None)
    ).first()
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow nicht gefunden")
    cf.deleted_at = _now()
    cf.is_active = 0
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="cashflows", record_id=cf_id, action="DELETE",
        client_id=client_id)
    db.commit()


@router.put("/clients/{client_id}/cashflows/{cf_id}", response_model=CashflowResponse)
def update_cashflow(
    client_id: str, cf_id: str,
    body: CashflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    get_client_for_user_or_404(client_id, db, current_user)
    cf = db.query(Cashflow).filter(
        Cashflow.id == cf_id,
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None)
    ).first()
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow nicht gefunden")
    updates = _normalize_cashflow_payload(body.model_dump(exclude_unset=True), cf)
    _validate_no_mortgage_amortization_double_count(client_id, updates, db, existing=cf)
    for field, value in updates.items():
        if isinstance(value, bool):
            value = 1 if value else 0
        setattr(cf, field, value)
    cf.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="cashflows", record_id=cf_id, action="UPDATE",
        client_id=client_id)
    db.commit()
    db.refresh(cf)
    return cf


# ── Goals ──────────────────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/goals", response_model=list[GoalResponse])
def list_goals(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(Goal).filter(
        Goal.mandate_id == mandate_id,
        Goal.deleted_at.is_(None),
        Goal.is_active == 1
    ).order_by(Goal.rank).all()


@router.post("/mandates/{mandate_id}/goals", response_model=GoalResponse, status_code=201)
def create_goal(
    mandate_id: str,
    body: GoalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    data = _normalize_goal_payload(body.model_dump())
    # Check rank uniqueness
    existing_rank = db.query(Goal).filter(
        Goal.mandate_id == mandate_id,
        Goal.rank == data["rank"],
        Goal.is_active == 1,
        Goal.deleted_at.is_(None)
    ).first()
    if existing_rank:
        raise HTTPException(status_code=409,
            detail=f"Rang {data['rank']} ist bereits vergeben. Bitte anderen Rang wählen.")
    now = _now()
    goal = Goal(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        is_active=1,
        is_ongoing=1 if data.get("is_ongoing") else 0,
        created_at=now,
        updated_at=now,
        **{k: v for k, v in data.items() if k not in ("is_ongoing",)}
    )
    db.add(goal)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="goals", record_id=goal.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(goal)
    return goal


@router.put("/mandates/{mandate_id}/goals/{goal_id}", response_model=GoalResponse)
def update_goal(
    mandate_id: str, goal_id: str,
    body: GoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.mandate_id == mandate_id,
        Goal.deleted_at.is_(None)
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    updates = _normalize_goal_payload(body.model_dump(exclude_unset=True), goal)
    new_rank = updates.get("rank")
    if new_rank is not None and int(new_rank) != int(goal.rank or 0):
        existing_rank = db.query(Goal).filter(
            Goal.mandate_id == mandate_id,
            Goal.rank == new_rank,
            Goal.id != goal_id,
            Goal.is_active == 1,
            Goal.deleted_at.is_(None)
        ).first()
        if existing_rank:
            raise HTTPException(status_code=409,
                detail=f"Rang {new_rank} ist bereits vergeben. Bitte anderen Rang wählen.")
    for field, value in updates.items():
        if isinstance(value, bool):
            value = 1 if value else 0
        setattr(goal, field, value)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="goals", record_id=goal_id, action="UPDATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/mandates/{mandate_id}/goals/{goal_id}", status_code=204)
def delete_goal(
    mandate_id: str, goal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.mandate_id == mandate_id,
        Goal.deleted_at.is_(None)
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Ziel nicht gefunden")
    goal.deleted_at = _now()
    goal.is_active = 0
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="goals", record_id=goal_id, action="DELETE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()


# ── Planning Assumptions ───────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/planning-assumptions/current",
            response_model=PlanningAssumptionResponse)
def get_planning_assumptions(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    pa = db.query(PlanningAssumption).filter(
        PlanningAssumption.mandate_id == mandate_id,
        PlanningAssumption.is_current == 1,
        PlanningAssumption.deleted_at.is_(None)
    ).first()
    if not pa:
        raise HTTPException(status_code=404, detail="Keine Planungsannahmen gefunden")
    return pa


@router.get("/mandates/{mandate_id}/planning-assumptions")
def get_planning_assumptions_ui(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    pa = db.query(PlanningAssumption).filter(
        PlanningAssumption.mandate_id == mandate_id,
        PlanningAssumption.is_current == 1,
        PlanningAssumption.deleted_at.is_(None)
    ).order_by(PlanningAssumption.version.desc()).first()
    if not pa:
        return {"inflation_assumption_bps": None}
    return {
        "id": pa.id,
        "inflation_assumption_bps": pa.inflation_assumption_bps,
        "retirement_age_primary": pa.retirement_age_primary,
        "retirement_age_partner": pa.retirement_age_partner,
        "life_expectancy_primary": pa.life_expectancy_primary,
        "life_expectancy_partner": pa.life_expectancy_partner,
        "notes": pa.notes,
    }


@router.put("/mandates/{mandate_id}/planning-assumptions")
def upsert_planning_assumptions(
    mandate_id: str,
    body: PlanningAssumptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    today = date.today().isoformat()
    payload = body.model_dump(exclude_unset=True)
    existing = db.query(PlanningAssumption).filter(
        PlanningAssumption.mandate_id == mandate_id,
        PlanningAssumption.is_current == 1,
        PlanningAssumption.deleted_at.is_(None)
    ).order_by(PlanningAssumption.version.desc()).first()
    if existing:
        # rp-ueberarbeitung: Upsert legt eine NEUE Version an (versioning), nicht
        # eine UPDATE in-place. Felder die im neuen Body nicht gesetzt sind,
        # werden aus der vorigen Version uebernommen.
        full: dict = {}
        for field_name in PlanningAssumptionCreate.model_fields:
            full[field_name] = getattr(existing, field_name, None)
        full.update(payload)
        prev_id = existing.id
        prev_version = int(existing.version or 0)
        existing.is_current = 0
        existing.valid_to = today
        pa = PlanningAssumption(
            id=new_uuid(),
            mandate_id=mandate_id,
            client_id=mandate.client_id,
            version=prev_version + 1,
            is_current=1,
            valid_from=today,
            supersedes_id=prev_id,
            created_at=now,
            updated_at=now,
            **full,
        )
        db.add(pa)
        log(db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="planning_assumptions", record_id=pa.id, action="CREATE",
            mandate_id=mandate_id, client_id=mandate.client_id)
        db.commit()
        return {"ok": True, "inflation_assumption_bps": pa.inflation_assumption_bps}

    pa = PlanningAssumption(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        version=1,
        is_current=1,
        valid_from=today,
        created_at=now,
        updated_at=now,
        **payload,
    )
    db.add(pa)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="planning_assumptions", record_id=pa.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    return {"ok": True, "inflation_assumption_bps": pa.inflation_assumption_bps}


@router.post("/mandates/{mandate_id}/planning-assumptions",
             response_model=PlanningAssumptionResponse, status_code=201)
def create_planning_assumptions(
    mandate_id: str,
    body: PlanningAssumptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    today = date.today().isoformat()
    # Supersede previous (Race-Hardening, siehe profiling.py).
    prev = db.query(PlanningAssumption).filter(
        PlanningAssumption.mandate_id == mandate_id,
        PlanningAssumption.is_current == 1,
        PlanningAssumption.deleted_at.is_(None)
    ).with_for_update().first()
    prev_version = 0
    prev_id = None
    if prev:
        prev.is_current = 0
        prev.valid_to = today
        prev_id = prev.id
        prev_version = prev.version
    pa = PlanningAssumption(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        version=prev_version + 1,
        is_current=1,
        valid_from=today,
        supersedes_id=prev_id,
        created_at=now,
        updated_at=now,
        **body.model_dump()
    )
    db.add(pa)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="planning_assumptions", record_id=pa.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(pa)
    return pa
