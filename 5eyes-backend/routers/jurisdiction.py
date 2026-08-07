"""WP3 (Backend-Router fuer Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31):
Verwaltungs-Endpunkte fuer JurisdictionProfile/JurisdictionHomeBiasDefault
(models/jurisdiction.py, WP1) + CMA-Kandidaten-Berechnung (services/
jurisdiction/data_pipeline.py) + CMA-Freigabe (CapitalMarketAssumption.status
-> "committee_approved").

# Rollen-Wahl (dokumentiert, wie in der Aufgabenstellung gefordert)
- Lesen (GET, auch home-bias-defaults): require_advisor. Ein Berater muss
  wissen, welche Jurisdiktionen ueberhaupt existieren/freigegeben sind und
  welche Home-Bias-Defaults fuer ein Mandat greifen wuerden -- reine
  Lesezugriffe, kein Risiko.
- Schreiben von Stammdaten (PUT Profile, POST/PUT/DELETE Home-Bias-Defaults):
  require_admin (Stammdaten-Pflege, analog zu ProductUniverseEntry in
  routers/review.py).
- CMA-Kandidaten-Berechnung + CMA-Freigabe: require_portfolio_management
  (dedizierte IC-Rolle, siehe services/auth.py Docstring).

# CH-Lock (harter Constraint der Aufgabenstellung)
code=="CH" darf NIEMALS ueber diese Routen veraendert werden -- weder das
JurisdictionProfile noch (fachlich wirkungslos, da CH nie aus dieser Tabelle
liest -- siehe services/jurisdiction/resolve.py::resolve_home_bias_defaults)
die Home-Bias-Defaults. Jeder Mutationsversuch mit code=="CH" wirft 403 MIT
klarer Fehlermeldung. Es gibt bewusst KEINE DELETE-Route fuer JurisdictionProfile
selbst (Profile werden ausschliesslich per Seed angelegt, siehe
services/jurisdiction/de_seed.py) -- der CH-Lock ist dadurch fuer den
Loeschfall bereits strukturell erfuellt (keine Route existiert, die geloescht
werden koennte).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db, new_uuid
from models.allocation import CapitalMarketAssumption
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile
from models.users import User
from schemas.allocation import CapitalMarketAssumptionResponse
from schemas.jurisdiction import (
    JurisdictionHomeBiasDefaultCreate,
    JurisdictionHomeBiasDefaultResponse,
    JurisdictionHomeBiasDefaultUpdate,
    JurisdictionProfileResponse,
    JurisdictionProfileUpdate,
)
from services.audit import log
from services.auth import require_admin, require_advisor, require_portfolio_management
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer Jurisdiktions-/CMA-Admin-Aktionen.
from routers.auth import _extract_client_ip
from services.jurisdiction.data_pipeline import (
    InsufficientYieldCurveDataError,
    NoYieldCurveSourceConfiguredError,
    compute_cma_candidate_for_jurisdiction,
)

router = APIRouter(prefix="/jurisdictions", tags=["Jurisdiktionen"])

# Separater Router (kein "/jurisdictions"-Prefix): die CMA-Freigabe haengt
# an der bestehenden CapitalMarketAssumption-Resource, nicht an einer
# konkreten Jurisdiktion (eine id ist bereits eindeutig).
cma_approval_router = APIRouter(tags=["Kapitalmarktannahmen"])

_CH_LOCK_DETAIL = "Schweiz-Jurisdiktion ist gesperrt -- Aenderungen ueber diese API sind nicht erlaubt."
_COMMITTEE_APPROVED_STATUS = "committee_approved"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _assert_not_ch(code: str) -> None:
    if code == "CH":
        raise HTTPException(status_code=403, detail=_CH_LOCK_DETAIL)


def _get_profile_or_404(code: str, db: Session) -> JurisdictionProfile:
    profile = db.query(JurisdictionProfile).filter(JurisdictionProfile.code == code).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Jurisdiktion '{code}' nicht gefunden")
    return profile


def _get_home_bias_row_or_404(code: str, row_id: str, db: Session) -> JurisdictionHomeBiasDefault:
    row = db.query(JurisdictionHomeBiasDefault).filter(
        JurisdictionHomeBiasDefault.id == row_id,
        JurisdictionHomeBiasDefault.jurisdiction_code == code,
        JurisdictionHomeBiasDefault.deleted_at.is_(None),
    ).first()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Home-Bias-Default {row_id} fuer Jurisdiktion '{code}' nicht gefunden",
        )
    return row


# ── JurisdictionProfile ─────────────────────────────────────────────────────


@router.get("", response_model=list[JurisdictionProfileResponse])
def list_jurisdictions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    return db.query(JurisdictionProfile).order_by(JurisdictionProfile.code.asc()).all()


@router.get("/{code}", response_model=JurisdictionProfileResponse)
def get_jurisdiction(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    return _get_profile_or_404(code, db)


@router.put("/{code}", response_model=JurisdictionProfileResponse)
def update_jurisdiction(
    code: str,
    body: JurisdictionProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _assert_not_ch(code)
    profile = _get_profile_or_404(code, db)
    payload = body.model_dump(exclude_unset=True)
    for field_name, value in payload.items():
        setattr(profile, field_name, value)
    profile.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="jurisdiction_profiles", record_id=profile.id, action="UPDATE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(profile)
    return profile


# ── JurisdictionHomeBiasDefault ─────────────────────────────────────────────


@router.get("/{code}/home-bias-defaults", response_model=list[JurisdictionHomeBiasDefaultResponse])
def list_home_bias_defaults(
    code: str,
    preference_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    q = db.query(JurisdictionHomeBiasDefault).filter(
        JurisdictionHomeBiasDefault.jurisdiction_code == code,
        JurisdictionHomeBiasDefault.deleted_at.is_(None),
    )
    if preference_key is not None:
        q = q.filter(JurisdictionHomeBiasDefault.preference_key == preference_key)
    return q.order_by(
        JurisdictionHomeBiasDefault.preference_key.asc(),
        JurisdictionHomeBiasDefault.preference_value.asc(),
        JurisdictionHomeBiasDefault.sort_order.asc().nulls_last(),
    ).all()


@router.post(
    "/{code}/home-bias-defaults",
    response_model=JurisdictionHomeBiasDefaultResponse,
    status_code=201,
)
def create_home_bias_default(
    code: str,
    body: JurisdictionHomeBiasDefaultCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # CH-Splits sind hartcodiertes Python (services/portfolio_engine.py::
    # _build_sub_allocations) -- eine DB-Zeile fuer CH waere wirkungslos und
    # wuerde eine Aenderbarkeit suggerieren, die nicht existiert.
    if code == "CH":
        raise HTTPException(
            status_code=403,
            detail=(
                "CH-Home-Bias-Splits sind hartcodiert (services/portfolio_engine.py) "
                "und werden NIE aus dieser Tabelle gelesen -- ein Eintrag hier waere wirkungslos."
            ),
        )
    now = _now()
    row = JurisdictionHomeBiasDefault(
        id=new_uuid(),
        jurisdiction_code=code,
        preference_key=body.preference_key,
        preference_value=body.preference_value,
        sub_asset_class=body.sub_asset_class,
        split_bps=body.split_bps,
        rationale_text=body.rationale_text,
        is_provisional=body.is_provisional,
        sort_order=body.sort_order,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="jurisdiction_home_bias_defaults", record_id=row.id, action="CREATE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{code}/home-bias-defaults/{row_id}",
    response_model=JurisdictionHomeBiasDefaultResponse,
)
def update_home_bias_default(
    code: str,
    row_id: str,
    body: JurisdictionHomeBiasDefaultUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _assert_not_ch(code)
    row = _get_home_bias_row_or_404(code, row_id, db)
    payload = body.model_dump(exclude_unset=True)
    for field_name, value in payload.items():
        setattr(row, field_name, value)
    row.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="jurisdiction_home_bias_defaults", record_id=row.id, action="UPDATE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{code}/home-bias-defaults/{row_id}", status_code=204)
def delete_home_bias_default(
    code: str,
    row_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _assert_not_ch(code)
    row = _get_home_bias_row_or_404(code, row_id, db)
    row.deleted_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="jurisdiction_home_bias_defaults", record_id=row.id, action="DELETE",
        ip_address=_extract_client_ip(request))
    db.commit()
    return None


# ── CMA-Kandidaten-Berechnung (echte Marktdaten) ────────────────────────────


@router.post("/{code}/cma/compute-candidate", response_model=CapitalMarketAssumptionResponse)
def compute_cma_candidate(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    # CH nutzt diese Pipeline nie (CH-CMA wird manuell/IC gepflegt, siehe
    # routers/allocation.py::update_cma) -- ein Aufruf hier waere sinnlos.
    if code == "CH":
        raise HTTPException(
            status_code=403,
            detail="CH nutzt die Kapitalmarktdaten-Pipeline nicht (CMA wird manuell/IC gepflegt).",
        )
    try:
        cma = compute_cma_candidate_for_jurisdiction(db, code, date.today().isoformat())
    except (NoYieldCurveSourceConfiguredError, InsufficientYieldCurveDataError) as exc:
        # Harte Vorgabe: NIEMALS eine erfundene Zahl als Fallback -- der
        # Client bekommt die genaue Fehlerursache, kein generisches 500.
        raise HTTPException(status_code=400, detail=str(exc))
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="capital_market_assumptions", record_id=cma.id, action="CREATE",
        new_value=f"data_pipeline candidate jurisdiction={code} status={cma.status}",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(cma)
    return cma


# ── CMA-Freigabe ─────────────────────────────────────────────────────────────


def _current_cma_scope_query(db: Session, jurisdiction: str | None, tenant_id: str | None):
    q = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    )
    q = q.filter(
        CapitalMarketAssumption.jurisdiction.is_(None)
        if jurisdiction is None
        else CapitalMarketAssumption.jurisdiction == jurisdiction
    )
    q = q.filter(
        CapitalMarketAssumption.tenant_id.is_(None)
        if tenant_id is None
        else CapitalMarketAssumption.tenant_id == tenant_id
    )
    return q


@cma_approval_router.post(
    "/capital-market-assumptions/{id}/approve",
    response_model=CapitalMarketAssumptionResponse,
)
def approve_capital_market_assumption(
    id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    """Setzt CapitalMarketAssumption.status="committee_approved" fuer die
    Zeile mit der gegebenen id.

    Design-Entscheidung (dokumentiert wie in der Aufgabenstellung erlaubt):
    ein frisch freigegebener Kandidat wird SOFORT aktiv (is_current=1) --
    eine IC-Freigabe ohne Aktivierung waere ein toter Zustand, den niemand
    explizit anfordert (das WP-Doc nennt genau diesen Use-Case: "data_derived"
    -> "committee_approved" Freigabe). Die zuvor aktuelle Zeile DERSELBEN
    Jurisdiktion+Tenant-Scope wird dabei mit with_for_update() gelockt und auf
    is_current=0 gesetzt (analog zum Muster in routers/allocation.py::
    update_cma). CH-Zeilen (jurisdiction IS NULL) sind i.d.R. bereits
    committee_approved + is_current=1 -- ein Aufruf darauf ist dann ein
    No-Op-Erfolg (kein Fehler), aendert aber nichts an der bestehenden
    CH-Versionierung durch routers/allocation.py::update_cma.
    """
    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == id,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()
    if not cma:
        raise HTTPException(status_code=404, detail=f"CapitalMarketAssumption {id} nicht gefunden")

    cma.status = _COMMITTEE_APPROVED_STATUS
    if not cma.is_current:
        prev = _current_cma_scope_query(db, cma.jurisdiction, cma.tenant_id).filter(
            CapitalMarketAssumption.id != cma.id,
        ).with_for_update().first()
        if prev is not None:
            prev.is_current = 0
        cma.is_current = 1
    cma.updated_at = _now()

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="capital_market_assumptions", record_id=cma.id, action="APPROVE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(cma)
    return cma
