from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.clients import Client, ClientNationality, ClientOptHistory
from models.wealth import Cashflow, WealthPosition, WealthInflow
from schemas.clients import (
    ClientCreate, ClientUpdate, ClientResponse,
    ClientErasureRequest, ClientErasureResponse,
    NationalityCreate, NationalityResponse,
    OptHistoryCreate, OptHistoryResponse,
    WealthSummaryResponse, CashflowSummaryResponse,
    CashflowYearRow, CashflowProjectionResponse,
)
from services.auth import (
    _apply_tenant_filter_to_client_query,
    get_client_for_user_or_404,
    get_current_user,
    has_global_client_access,
    hash_password,
    require_admin,
    require_advisor,
)
from services.audit import log
from services.cashflow_timeline import totals_for_year
from services.client_erasure import erase_client_personal_data
from services.data_classification import enforce_data_classification
from services.planning_horizon import life_expectancy_year_for
from services.quota import assert_within_quota
from services.wealth_cashflows import derive_wealth_cashflows, mortgage_interest_adjustment_series

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
    # SECURITY (Mandanten-Trennung): Tenant-Filter IMMER anwenden — auch fuer
    # globale Admins. Sonst sieht ein tenant-gebundener Admin (role=admin)
    # Clients fremder Tenants. Spiegelt get_accessible_client_ids.
    q = _apply_tenant_filter_to_client_query(q, current_user)
    if search:
        safe = search.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')
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
    payload = body.model_dump()
    enforce_data_classification(payload.pop("data_classification", None))
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
        # E1 (2026-06-14): Client erbt den Tenant des anlegenden Users -> nie
        # NULL-tenant_id, harte Firmen-Trennung (Voraussetzung fuer strict mode).
        **{**payload, "advisor_id": advisor_id,
           "tenant_id": getattr(current_user, "tenant_id", None)}
    )
    db.add(client)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client.id, action="CREATE",
        client_id=client.id)
    try:
        db.commit()
    except IntegrityError:
        # 2026-07-24 (Generalaudit): der Pre-Check oben ist TOCTOU-racy --
        # zwei parallele Requests (z.B. Doppelklick) koennen beide den
        # Check passieren, bevor einer committet. Der UNIQUE-Constraint auf
        # client_number (models/clients.py) verhindert zuverlaessig ein
        # Duplikat, gab dem VERLIERENDEN Request bisher aber einen 500
        # statt eines klaren 409. Kein Datenintegritaets-Bug (kein Duplikat
        # persistiert), nur eine falsche HTTP-Statuscode-Antwort.
        db.rollback()
        raise HTTPException(status_code=409, detail="Kundennummer bereits vergeben")
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
    updates = body.model_dump(exclude_unset=True)
    enforce_data_classification(updates.pop("data_classification", None))
    client = _get_client_or_404(client_id, db, current_user)
    if "advisor_id" in updates and not has_global_client_access(current_user):
        if updates["advisor_id"] != current_user.id:
            raise HTTPException(status_code=403, detail="Berater duerfen Kunden nicht einem anderen Berater zuweisen")
        updates["advisor_id"] = current_user.id
    for field, value in updates.items():
        setattr(client, field, value)
    client.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client_id, action="UPDATE",
        client_id=client_id)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(
    client_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    from routers.auth import _extract_client_ip
    client = _get_client_or_404(client_id, db, current_user)
    client.deleted_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client_id, action="DELETE",
        client_id=client_id, ip_address=_extract_client_ip(request))
    db.commit()


def _get_client_for_erasure_or_404(client_id: str, db: Session, current_user: User) -> Client:
    """Lookup fuer DSG-Art.-32-Erasure: bewusst OHNE deleted_at-Filter
    (im Unterschied zu get_client_for_user_or_404) -- eine Loeschungs-
    anfrage trifft haeufig gerade einen bereits (soft-)geloeschten
    Kunden, dessen Personendaten trotzdem noch vollstaendig in der DB
    liegen. Tenant-Scoping bleibt bestehen (kein globaler Admin darf
    Kunden eines fremden Tenants anonymisieren)."""
    query = db.query(Client).filter(Client.id == client_id)
    query = _apply_tenant_filter_to_client_query(query, current_user)
    client = query.first()
    if not client:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return client


@router.post("/{client_id}/erase", response_model=ClientErasureResponse)
def erase_client(
    client_id: str,
    body: ClientErasureRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """DSG Art. 32 -- Loeschungsanspruch. Anonymisiert irreversibel alle
    direkt identifizierenden Personendaten dieses Kunden (siehe
    services/client_erasure.py fuer die vollstaendige rechtliche und
    technische Begruendung des Umfangs). Admin-only, Pflichtbegruendung
    (schemas.clients.ClientErasureRequest), idempotent-sicher (409 bei
    Doppelaufruf). Die Aktion selbst wird -- wie jede sensible Aktion --
    unveraenderlich im Audit-Log protokolliert (wer hat wann wen aus
    welchem Grund geloescht)."""
    from routers.auth import _extract_client_ip
    _get_client_for_erasure_or_404(client_id, db, current_user)
    result = erase_client_personal_data(db, client_id, reason=body.reason)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="clients", record_id=client_id, action="CLIENT_ERASE",
        client_id=client_id,
        new_value=str({"reason": body.reason, "redacted": result["redacted"]}),
        ip_address=_extract_client_ip(request))
    db.commit()
    return result


# ── Nationalities ──────────────────────────────────────────────────────────────

@router.get("/{client_id}/nationalities", response_model=list[NationalityResponse])
def list_nationalities(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_client_or_404(client_id, db, current_user)
    return db.query(ClientNationality).filter(
        ClientNationality.client_id == client_id,
        ClientNationality.deleted_at.is_(None)
    ).all()


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
    # 2026-06-14: vermögensgetriebene Cashflows (Hypothekarzins, Amortisation,
    # Miet-/Zinserträge) zählen MIT in die Summe — sie sind echte Cashflows, nur
    # automatisch aus dem Vermögen abgeleitet statt manuell erfasst.
    cashflows = list(cashflows) + _derived_cashflows_for_client(client_id, db)
    # CF-2 (2026-07-23): FX-Konvertierung wie im Schwester-Endpoint
    # cashflow_projection — sonst zeigt das Summary Fremdwaehrungs-Cashflows im
    # Rohbetrag statt zu CHF konvertiert (Divergenz zwischen den beiden Ansichten).
    # 2026-07-24 (Generalaudit): FXRateSource.from_db() faengt intern bereits
    # JEDEN Fehler ab und faellt selbst auf Default-Kurse zurueck (siehe
    # services/currency/fx_rates.py::from_db) -- dieser aeussere except greift
    # praktisch nie. Faellt er doch (z.B. Import-Fehler), war der Fallback
    # bisher fx_source=None -> totals_for_year() KONVERTIERT GAR NICHT MEHR
    # (Fremdwaehrungs-Betraege im Rohwert), schlechter als der DEFAULT_FX_RATES-
    # Fallback, den from_db() selbst nutzt. FXRateSource() (= Default-Kurse)
    # ist die konsistente Wahl.
    from services.currency.fx_rates import FXRateSource
    fx_source = None
    try:
        fx_source = FXRateSource.from_db(db)
    except Exception:
        fx_source = FXRateSource()
    totals = totals_for_year(cashflows, fx_source=fx_source, target_currency="CHF")
    client_name = f"{client.first_name or ''} {client.last_name or ''}".strip() or client.client_number or client.id
    return CashflowSummaryResponse(
        client_id=client_id,
        client_name=client_name,
        summary_year=totals["year"],
        recurring_income_rappen=totals["recurring_income_rappen"],
        capital_inflow_rappen=totals["capital_inflow_rappen"],
        total_income_rappen=totals["income_rappen"],
        recurring_expense_rappen=totals["recurring_expense_rappen"],
        capital_outflow_rappen=totals["capital_outflow_rappen"],
        total_expense_rappen=totals["expense_rappen"],
        recurring_net_rappen=totals["recurring_income_rappen"] - totals["recurring_expense_rappen"],
        capital_net_rappen=totals["capital_inflow_rappen"] - totals["capital_outflow_rappen"],
        surplus_rappen=totals["net_rappen"],
        total_income_chf=totals["income_rappen"] / 100,
        total_expense_chf=totals["expense_rappen"] / 100,
        surplus_chf=totals["net_rappen"] / 100,
    )


def _derived_cashflows_for_client(client_id: str, db: Session) -> list:
    """Lädt aktive Vermögenspositionen und leitet die periodischen Cashflows ab
    (Hypothekarzins, Amortisation, Miet-/Zinserträge). Read-only, kein DB-Eintrag."""
    positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    return derive_wealth_cashflows(positions)


@router.get("/{client_id}/cashflows-derived")
def cashflows_derived(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Vermögensgetriebene, schreibgeschützte Cashflows (Hypothekarzins,
    Amortisation, Miet-/Zinserträge) — damit die UI sie sichtbar UND klar als
    'automatisch aus Vermögen' gekennzeichnet anzeigen kann."""
    _get_client_or_404(client_id, db, current_user)
    return [d.to_dict() for d in _derived_cashflows_for_client(client_id, db)]


def _derive_cashflow_projection_horizon(
    client: Client, db: Session, *, cashflows: list | None = None,
    default_years: int = 40, cap: int = 60,
) -> int:
    """Cashflow-/Vermoegensverzehr-Projektions-Horizont aus den Stammdaten.

    Anders als der ANLAGEhorizont (endet typischerweise an der Pensionierung)
    soll die IST-Cashflow-Projektion bis zum LEBENSENDE laufen, damit die
    Nach-Pensionierungs-Phase (AHV-Einkommen < Ausgaben -> Vermoegensverzehr)
    ueberhaupt sichtbar wird. Vorher: hartes Default 40, unabhaengig von der Person.

    Genommen wird das spaeteste plausible Jahr aus:
      - dem letzten erfassten Cashflow-Ende (valid_until/valid_from) — die
        Projektion MUSS alle vom Berater erfassten Cashflows abdecken (z.B.
        AHV/Verzehr bis 2060), sonst wird der Verzehr abgeschnitten;
      - ``client.investment_horizon_end`` (explizites Stammdatum);
      - manuell gesetztem ``Mandate.life_expectancy_year``;
      - sonst Geburtsjahr +83 (Herr) bzw. +85 (sonstige/unbekannt);
      - bei Paaren dem spaeteren der beiden Lebenserwartungsjahre.
    Fallback ``default_years``.
    """
    from datetime import date as _date
    from models.mandates import Mandate

    today_year = _date.today().year

    def _year(value) -> int | None:
        s = str(value or "").strip()
        if len(s) < 4:
            return None
        try:
            return int(s[:4])
        except ValueError:
            return None

    end_years: list[int] = []

    # Letztes erfasstes Cashflow-Jahr (valid_until bevorzugt, sonst valid_from) —
    # die Projektion muss alle Cashflows vollstaendig abbilden.
    for cf in (cashflows or []):
        cf_year = _year(getattr(cf, "valid_until", None)) or _year(getattr(cf, "valid_from", None))
        if cf_year:
            end_years.append(cf_year)

    horizon_end = _year(getattr(client, "investment_horizon_end", None))
    if horizon_end:
        end_years.append(horizon_end)

    mandate = (
        db.query(Mandate)
        .filter(Mandate.client_id == client.id, Mandate.deleted_at.is_(None))
        .order_by(Mandate.created_at.desc())
        .first()
    )
    if mandate is not None:
        life_year = life_expectancy_year_for(client=client, mandate=mandate)
    else:
        life_year = life_expectancy_year_for(client=client)
    if life_year:
        end_years.append(life_year)

    plausible = [y for y in end_years if y > today_year]
    if plausible:
        # +1: das Lebensende-Jahr selbst soll in der Projektion enthalten sein
        # (range startet beim laufenden Jahr), damit der Verzehr bis dahin zu sehen ist.
        return max(1, min(cap, max(plausible) - today_year + 1))
    return default_years


@router.get("/{client_id}/cashflow-projection", response_model=CashflowProjectionResponse)
def cashflow_projection(
    client_id: str,
    horizon_years: int | None = Query(default=None, ge=1, le=60),
    indexation: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import date as _date

    client = _get_client_or_404(client_id, db, current_user)
    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    # #Zeitraum-Fix (2026-06-12): ohne expliziten Override wird der Horizont aus
    # den Stammdaten + erfassten Cashflows bis zum Lebensende abgeleitet (statt
    # hartes Default 40), damit der Vermoegensverzehr nach der Pensionierung
    # vollstaendig sichtbar ist (alle Cashflows abgedeckt).
    effective_horizon = (
        int(horizon_years)
        if horizon_years is not None
        else _derive_cashflow_projection_horizon(client, db, cashflows=cashflows)
    )
    # 2026-06-14: abgeleitete Vermögens-Cashflows in die Projektion einbeziehen
    # (nach Horizont-Ableitung, damit der Horizont weiterhin aus den erfassten
    # Cashflows + Stammdaten bestimmt wird — die abgeleiteten sind wiederkehrend).
    cashflows = list(cashflows) + _derived_cashflows_for_client(client_id, db)
    start_year = _date.today().year
    horizon = int(effective_horizon or 40)
    # 2026-06-14 (#31 B-2): Hypothek-Amortisation/Refinanzierung jahresabhängig
    # einrechnen — konsistent mit der Strategie-Engine. Positiv = weniger Zinslast
    # (direkte Amortisation), negativ = mehr (3% nach Ablauf/5J-SARON).
    _mort_positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    _mort_adj = mortgage_interest_adjustment_series(_mort_positions, horizon, start_year)

    # CF-1/CF-2 (2026-07-16): Cashflow-Ansicht mit der Strategie-Engine angleichen.
    # Vorher rief dieser Endpoint totals_for_year(cashflows, yr) OHNE Inflation/FX/
    # Inflows -> die dem Berater/Kunden gezeigte Tabelle divergierte von den
    # Strategie-Zahlen (_load_allocation_inputs in portfolio_engine.py) -> FIDLEG-
    # Vertrauensrisiko. Hier werden dieselben drei Angleichungen angewandt:
    #   1. Inflation: is_inflation_linked-Cashflows werden per CMA-Inflationspfad
    #      aufgezinst (AHV/Lohn/Miete wachsen; Bonus/Erbschaft bleiben nominal).
    #   2. FX: Fremdwaehrungs-Cashflows werden zu CHF konvertiert.
    #   3. Wealth-Inflows: erwartete Zufluesse (Erbschaft/Bonus/Saeule3b) werden als
    #      zusaetzliche Zufluss-Beitraege addiert (KEINE Cashflow-Rows).
    #
    # ARCHITEKTUR: Dieser Endpoint ist CLIENT-scoped, die Engine ist MANDAT-scoped.
    # Fuer die client-weite Ansicht daher:
    #   - Inflation: aktuell gueltige CMA (is_current=1) — Inflation ist CMA-Ebene,
    #     kein mandat-spezifischer Wert noetig. Ohne CMA -> None -> nominale Darstellung.
    #   - Waehrung: Ziel = 'CHF' (Schweizer Berater-Default), da am Client-Level kein
    #     eindeutiges Mandat/base_currency existiert.
    #   - Wealth-Inflows: ALLE aktiven WealthInflow-Records des Clients (mandate-
    #     spezifische UND client-weite), da client-scoped ueber alle Mandate aggregiert.
    from models.allocation import CapitalMarketAssumption
    from services.portfolio_engine import (
        _inflation_path_series,
        _wealth_inflow_series_rappen,
    )

    # FX-Source spiegelt die Engine (_load_allocation_inputs): bei Lade-Fehler
    # 2026-07-24 (Generalaudit): Fallback auf FXRateSource() (Default-Kurse)
    # statt None -- FXRateSource.from_db() faengt intern schon jeden Fehler ab
    # und faellt selbst auf Default-Kurse zurueck, dieser aeussere except
    # greift praktisch nie. Faellt er doch, ist fx_source=None schlechter
    # (deaktiviert Konvertierung komplett statt Naeherung zu zeigen).
    from services.currency.fx_rates import FXRateSource
    fx_source = None
    try:
        fx_source = FXRateSource.from_db(db)
    except Exception:
        fx_source = FXRateSource()
    target_currency = "CHF"

    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()
    # Indexierungs-Schalter (2026-07-19, 3eyes-like): Globaler Master-Toggle fuer
    # die Cashflow-Projektions-Ansicht. indexation=True (Default) = heutiges
    # CF-Verhalten (is_inflation_linked-Cashflows werden per CMA-Inflationspfad
    # aufgezinst, gilt fuer Einnahmen UND Ausgaben sowie Wealth-Inflows).
    # indexation=False = alles nominal (keine Aufzinsung). FX bleibt unabhaengig
    # aktiv, da Waehrungsumrechnung keine Indexierung ist.
    inflation_series_bps = (
        _inflation_path_series(cma, horizon, start_year)
        if (cma is not None and indexation)
        else None
    )

    wealth_inflows = db.query(WealthInflow).filter(
        WealthInflow.client_id == client_id,
        WealthInflow.deleted_at.is_(None),
        WealthInflow.is_active == 1,
    ).all()
    inflow_series = _wealth_inflow_series_rappen(
        wealth_inflows, horizon, start_year, inflation_series_bps,
    )

    rows = []
    for offset in range(horizon):
        yr = start_year + offset
        t = totals_for_year(
            cashflows,
            yr,
            inflation_series_bps=inflation_series_bps,
            start_year=start_year,
            fx_source=fx_source,
            target_currency=target_currency,
        )
        adj = int(_mort_adj[offset]) if offset < len(_mort_adj) else 0
        # Wealth-Inflows als Zufluss-Beitrag (Erbschaft/Bonus sind Kapital-Zufluesse).
        inflow = int(inflow_series[offset]) if offset < len(inflow_series) else 0
        rows.append(CashflowYearRow(
            year=yr,
            recurring_income_rappen=t["recurring_income_rappen"],
            capital_inflow_rappen=t["capital_inflow_rappen"] + inflow,
            income_rappen=t["income_rappen"] + inflow,
            recurring_expense_rappen=max(0, t["recurring_expense_rappen"] - adj),
            capital_outflow_rappen=t["capital_outflow_rappen"],
            expense_rappen=max(0, t["expense_rappen"] - adj),
            net_rappen=t["net_rappen"] + adj + inflow,
        ))
    return CashflowProjectionResponse(
        client_id=client_id,
        start_year=start_year,
        years=rows,
    )


# ---------------------------------------------------------------------------
# Sprint U-36 (2026-06-06): Client-Login-Verwaltung (Berater erstellt Kunden-
# Login fuer einen seiner Klienten).
# ---------------------------------------------------------------------------

@router.post("/{client_id}/client-login", status_code=201)
def create_client_login(
    client_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Sprint U-36: Erstellt User mit role='client' + ClientLogin-Linkage.

    Body (Pflicht):
      - username: str
      - password: str (min 8 Zeichen)
    Optional:
      - full_name: str (Default: Kunde.first_name + last_name)
      - email: str

    Bedingungen:
      - Berater muss den Client besitzen (oder Admin sein)
      - Username darf nicht vergeben sein
      - Pro Client darf nur EINE aktive Linkage existieren
    """
    from models.client_login import ClientLogin

    client = _get_client_or_404(client_id, db, current_user)

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username:
        raise HTTPException(status_code=422, detail="username erforderlich")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password muss mindestens 8 Zeichen lang sein")

    existing_user = db.query(User).filter(
        User.username == username,
        User.deleted_at.is_(None),
    ).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Benutzername bereits vergeben")

    existing_link = db.query(ClientLogin).filter(
        ClientLogin.client_id == client.id,
        ClientLogin.is_active == 1,
    ).first()
    if existing_link:
        raise HTTPException(status_code=409, detail="Fuer diesen Kunden existiert bereits ein aktiver Login")

    now = _now()
    full_name = str(body.get("full_name") or "").strip() or f"{client.first_name} {client.last_name}".strip()
    email = body.get("email")
    # SEC-1 (2026-07-04): Client-Login-User erbt tenant_id vom Parent-Client
    # (Fallback: Tenant des anlegenden Beraters), analog create_mandate. Damit
    # entstehen keine "herrenlosen" NULL-Tenant-Client-User mehr (harte Mandanten-
    # trennung / FINMA/FIDLEG/DSG; Vorbedingung fuer spaetere NOT-NULL-Constraint).
    client_user_tenant_id = getattr(client, "tenant_id", None) or getattr(current_user, "tenant_id", None)
    # Guard: Ist kein Tenant ableitbar, darf im Strict-/Multi-Kontext KEIN NULL-
    # Tenant-User entstehen (waere fuer JEDEN Tenant sichtbar). Legacy-Single/
    # non-strict bleibt zulaessig (BC).
    if not (client_user_tenant_id and str(client_user_tenant_id).strip()):
        from config import settings as _settings
        _strict = getattr(_settings, "strict_tenant_isolation", False)
        _multi = getattr(_settings, "tenancy_mode", "single") == "multi"
        if _strict or _multi:
            raise HTTPException(
                status_code=409,
                detail="Tenant nicht bestimmbar — Client-Login kann im Multi-/Strict-Modus nicht ohne Mandant angelegt werden",
            )
    # 2026-07-25 (Generalaudit): assert_within_quota fehlte hier -- anders als
    # create_user/invite_user (routers/auth.py) liess sich max_users durch
    # beliebig viele Client-Portal-Logins umgehen (Lizenzmodell-Bypass), da
    # services.quota zaehlt ALLE User-Zeilen des Tenants unabhaengig von role.
    assert_within_quota(db, client_user_tenant_id, "users")
    client_user = User(
        id=new_uuid(),
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        email=email,
        role="client",
        tenant_id=client_user_tenant_id,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(client_user)
    db.flush()

    link = ClientLogin(
        id=new_uuid(),
        user_id=client_user.id,
        client_id=client.id,
        created_by=current_user.id,
        created_at=now,
        is_active=1,
    )
    db.add(link)

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="client_logins", record_id=link.id, action="CREATE",
        new_value=f"client_id={client.id} user_id={client_user.id}")
    db.commit()

    return {
        "client_login_id": link.id,
        "user_id": client_user.id,
        "username": client_user.username,
        "client_id": client.id,
        "status": "created",
    }

# ── DSG-Datenexport (Roadmap-Punkt 10) ────────────────────────────────────────

@router.get("/{client_id}/data-export")
def export_data(
    client_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """DSG Art. 25 — Auskunftsrecht. Liefert alle personenbezogenen Daten
    des Kunden in maschinenlesbarem JSON-Format.

    Authentifizierung
        Advisor-only. Mandantentrennung wird ueber `_get_client_or_404`
        erzwungen (Berater darf nur seine eigenen Kunden exportieren,
        ausser bei globalem Zugriff).

    Audit
        Jeder Export landet als `EXPORT`-Eintrag im audit_log mit
        integrity_hash, sodass spaeter nachvollziehbar bleibt, welcher
        Berater wann welche Daten herausgegeben hat (FINMA-konform).
    """
    from routers.auth import _extract_client_ip
    from services.data_export import export_client_data

    client = _get_client_or_404(client_id, db, current_user)
    payload = export_client_data(db, client.id)
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="clients",
        record_id=client.id,
        action="EXPORT",
        client_id=client.id,
        new_value=f"DSG-Export schema_v{payload['schema_version']}, "
                  f"{sum(payload['manifest'].values())} Datensaetze",
        ip_address=_extract_client_ip(request),
    )
    db.commit()
    return payload
