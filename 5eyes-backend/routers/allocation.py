from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import date, datetime, timezone
from typing import Optional
import json

from config import settings
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.allocation import TargetAllocation, OptimizerPolicy, OptimizerRun, CapitalMarketAssumption, HouseMatrix, BuildingBlock
from models.profiling import RiskAssessment
from models.review import MandateReportNotes
from schemas.allocation import (
    TargetAllocationCreate, TargetAllocationResponse,
    HouseMatrixResponse,
    CapitalMarketAssumptionCreate, CapitalMarketAssumptionResponse,
    TargetAllocationGenerateRequest, TargetAllocationGenerateResponse,
    BuildingBlockResponse,
    AllocationSensitivityRequest, AllocationSensitivityResponse,
    OptimizerRunResponse,
    OptimizerPolicyCreate, OptimizerPolicyUpdate, OptimizerPolicyResponse,
    OptimizerPolicyDetailResponse, HouseMatrixRowsReplace,
)
from schemas.review import ReportNotesResponse, ReportNotesUpdate
from services.auth import get_current_user, get_mandate_for_user_or_404, require_advisor, require_admin
from services.audit import log
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer CMA-/Policy-/Allokations-
# Aenderungen im Audit-Log.
from routers.auth import _extract_client_ip
from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError
from services.jurisdiction.resolve import (
    resolve_cma_for_jurisdiction,
    resolve_mandate_jurisdiction,
)
from services.portfolio_engine import (
    _current_risk_assessment_or_none,
    _current_target_allocation_or_none,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    evaluate_goal_sensitivity,
    generate_target_allocation,
    require_strategy_ready_assessment,
)
from services.advisory_report import compute_advisory_report
from services.advisory_report_cache import (
    cached_compute_advisory_report,
    invalidate_mandate as invalidate_advisory_cache,
)
from services.depot_check import compute_depot_check
from services.backtest_stress import compute_stress_replays
from services.backtest_ab import run_ab_backtest
from services.backtest_strategy import run_strategy_backtest
from services.review_engine import refresh_system_review_triggers
from services.suitability_audit import audit_mandate_suitability

router = APIRouter(tags=["Allokation"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# Sprint U-103 (2026-06-05): Felder die NICHT in den Archiv-Snapshot
# uebernommen werden (Identitaet/Lifecycle gehoeren zur neuen Zeile).
_POLICY_NONCLONE_FIELDS = frozenset({"id", "version", "is_current", "valid_from", "valid_to"})


def _archive_policy_snapshot(db: Session, policy: OptimizerPolicy, now: str) -> OptimizerPolicy:
    """Sprint U-103 (2026-06-05): Snapshot der aktuellen Policy in eine
    archivierte Zeile schreiben (is_current=0, valid_to=now). Damit kann
    nach einem Update die historische Konfiguration rekonstruiert werden,
    wie sie zum Zeitpunkt eines bestimmten TargetAllocation-Runs galt.

    Praezise: alle Felder ausser id/version/is_current/valid_from/valid_to
    werden 1:1 kopiert. Die archivierte Zeile bekommt:
      - neue id (eigener PK)
      - dieselbe version wie die aktuelle Zeile (= Stand der Archivierung)
      - is_current=0
      - valid_from = bisheriges valid_from der aktuellen Zeile
      - valid_to   = now (Ende-der-Gueltigkeit)
    """
    snapshot_kwargs = {
        column.name: getattr(policy, column.name)
        for column in policy.__table__.columns
        if column.name not in _POLICY_NONCLONE_FIELDS
    }
    snapshot = OptimizerPolicy(
        id=new_uuid(),
        version=policy.version,
        is_current=0,
        valid_from=policy.valid_from,
        valid_to=now,
        **snapshot_kwargs,
    )
    db.add(snapshot)
    return snapshot


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


@router.get("/mandates/{mandate_id}/target-allocation/current",
            response_model=TargetAllocationResponse)
def get_current_allocation(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    try:
        ta = _current_target_allocation_or_none(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ta:
        raise HTTPException(status_code=404, detail="Keine Soll-Allokation gefunden")
    return ta


@router.get("/mandates/{mandate_id}/optimizer-runs",
            response_model=list[OptimizerRunResponse])
def list_optimizer_runs(
    mandate_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """V3 Sprint 2: Liste der persistierten Solver-Laufe fuer ein Mandat.

    Sortiert absteigend nach run_at (neueste zuerst). Default-Pagination
    50/Anfrage. Wenn der Solver in keinem Modus lief, ist die Liste leer.
    """
    _get_mandate_or_404(mandate_id, db, current_user)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit muss in [1, 500] sein")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset darf nicht negativ sein")
    runs = db.query(OptimizerRun).filter(
        OptimizerRun.mandate_id == mandate_id,
    ).order_by(OptimizerRun.run_at.desc()).offset(offset).limit(limit).all()
    return runs


@router.get("/mandates/{mandate_id}/target-allocation/current/payload",
            response_model=TargetAllocationGenerateResponse)
def get_current_allocation_payload(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        ta = _current_target_allocation_or_none(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ta:
        raise HTTPException(status_code=404, detail="Keine Soll-Allokation gefunden")
    # rp-ueberarbeitung: pruefe ob die referenzierte Policy noch aktuell ist,
    # BEVOR ensure_runtime_reference_data eine neue Policy/CMA erstellt. Eine
    # Allocation auf einer archivierten Policy soll 404 zurueckgeben.
    ta_policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == ta.policy_id,
    ).first()
    if not ta_policy or ta_policy.is_current != 1:
        raise HTTPException(
            status_code=404,
            detail="Soll-Allokation referenziert eine nicht-aktuelle Optimizer Policy."
        )
    try:
        assessment = _current_risk_assessment_or_none(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not assessment:
        raise HTTPException(status_code=409, detail="Bitte zuerst ein aktuelles Risikoprofil speichern.")
    try:
        policy, current_cma = ensure_runtime_reference_data(
            db,
            current_user.id,
            jurisdiction=resolve_mandate_jurisdiction(mandate),
            tenant_id=getattr(mandate, "tenant_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Sprint U-P6 Fix H6: CMA-Reload-Asymmetrie behoben — Metrics/MC werden
    # mit der zum Generate-Zeitpunkt persistierten CMA berechnet, nicht mit
    # der aktuellen. Vorher: Bands aus Snapshot, Returns/Vola aus aktueller CMA
    # → silent Drift wenn CMA-Update zwischen Generate und Reload. Drift-Warning
    # in _strategy_drift_warnings macht die Differenz weiterhin sichtbar.
    try:
        return build_target_payload_from_allocation(
            db=db,
            mandate=mandate,
            allocation=ta,
            policy=ta_policy,
            cma=current_cma,
            assessment=assessment,
            preferences=None,
        )
    except ValueError as exc:
        # Invalid legacy/raw position semantics and persisted-context integrity
        # failures are repairable domain conflicts, not opaque server errors.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/mandates/{mandate_id}/target-allocation",
             response_model=TargetAllocationResponse, status_code=201)
def create_target_allocation(
    mandate_id: str,
    body: TargetAllocationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # rp-ueberarbeitung: zuerst Policy pruefen (404 fuer archivierte/fehlende),
    # dann FIDLEG-Risikoprofil-Gate (409 fuer fehlende Risikoprofilierung).
    # Damit ist die Fehlermeldung bei archivierter Policy eindeutig 404.
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == body.policy_id,
        OptimizerPolicy.is_current == 1,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Optimizer Policy nicht gefunden oder nicht aktuell")
    # FIDLEG: jede gespeicherte Soll-Allokation muss auf einer strategie-fertigen
    # Risikoprofilierung beruhen. Direktes POST darf das nicht umgehen.
    try:
        assessment = require_strategy_ready_assessment(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # Mega-Audit (2026-08-04): require_strategy_ready_assessment prueft nur
    # VOLLSTAENDIGKEIT (alle 11 Fragen beantwortet), NICHT die 365-Tage-
    # Freshness, die audit_mandate_suitability zusaetzlich verlangt -- ein
    # Mandat mit vollstaendigem, aber Jahre altem Risikoprofil passierte
    # dieses Gate bisher klaglos. Identisches Opt-in-Gate wie in
    # generate_target_allocation_endpoint (Welle 2.1), hier ergaenzt, damit
    # der direkte POST-Pfad es nicht mehr umgehen kann.
    if settings.require_suitability_before_recommendation:
        suitability = audit_mandate_suitability(db, mandate)
        if not suitability.get("is_compliant", True):
            raise HTTPException(
                status_code=409,
                detail=(
                    "FIDLEG: Eignungsprüfung fehlt oder ist nicht aktuell — "
                    "Speichern blockiert "
                    "(require_suitability_before_recommendation=True)."
                ),
            )
    if body.based_on_assessment_id and body.based_on_assessment_id != assessment.id:
        raise HTTPException(status_code=422, detail=(
            "based_on_assessment_id muss auf das aktuelle Risikoprofil zeigen "
            f"(erwartet {assessment.id})."
        ))
    if settings.optimizer_mode != "house_matrix":
        raise HTTPException(
            status_code=409,
            detail=(
                "Manuell erzeugte Soll-Allokationen sind im stochastischen Modus "
                "nicht zulaessig. Bitte den Engine-Generate-Pfad verwenden; "
                "manuelle Leitplanken werden dort als harte Bands uebergeben."
            ),
        )
    now = _now()
    # Sprint U-P0 Fix C8: with_for_update verhindert Race-Condition (zwei
    # gleichzeitige POSTs → zwei is_current=1 Rows). Konsistent zur
    # generate_target_allocation-Pfad-Logik in portfolio_engine.py:5134.
    try:
        prev = _current_target_allocation_or_none(
            db,
            mandate_id,
            for_update=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev_version = prev.version
        # Release the existing partial-unique anchor before inserting the new
        # version; database uniqueness is immediate, not deferred.
        db.flush()
    payload = body.model_dump()
    if not payload.get("based_on_assessment_id"):
        payload["based_on_assessment_id"] = assessment.id
    ta = TargetAllocation(
        id=new_uuid(),
        mandate_id=mandate_id,
        version=prev_version + 1,
        is_current=1,
        set_by=current_user.id,
        set_at=now,
        created_at=now,
        updated_at=now,
        **payload
    )
    db.add(ta)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="target_allocations", record_id=ta.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id,
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(ta)
    return ta


@router.get("/house-matrix/{score}", response_model=HouseMatrixResponse)
def get_house_matrix_for_score(
    score: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get house matrix band for a given risk score (1–10)."""
    if not 1 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score muss zwischen 1 und 10 liegen")
    # Get current policy
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    hm = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score,
        HouseMatrix.score_to >= score,
        HouseMatrix.is_active == 1
    ).first()
    if not hm:
        raise HTTPException(status_code=404, detail=f"Kein House Matrix Eintrag für Score {score}")
    return hm


@router.get("/optimizer-policies/current")
def get_current_policy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    return policy


@router.get("/building-blocks/current", response_model=list[BuildingBlockResponse])
def get_current_building_blocks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    return db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy.id,
        BuildingBlock.is_active == 1,
    ).order_by(BuildingBlock.asset_class.asc(), BuildingBlock.sub_asset_class.asc()).all()


@router.get("/capital-market-assumptions/current",
            response_model=CapitalMarketAssumptionResponse)
def get_current_cma(
    # 2026-07-31 (WP3): bewusst PLAIN defaults statt fastapi.Query(...) --
    # tests/test_runtime_contracts.py ruft diesen Endpoint direkt als Python-
    # Funktion auf (body=..., db=..., current_user=...) unter Umgehung der
    # FastAPI-Dependency-Injection; mit Query(...) als Default wuerde der
    # ungeloeste Query-Sentinel statt "CH"/None durchgereicht. Scalar-Typ-
    # Parameter ohne Body-Model werden von FastAPI ohnehin automatisch als
    # Query-Parameter behandelt (siehe FastAPI-Doku), Query(...) ist hier
    # nicht notwendig.
    jurisdiction: str = "CH",
    tenant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """2026-07-31 (WP3, Jurisdiktions-Verwaltung): optionaler jurisdiction/
    tenant_id Query-Parameter, Default "CH" -- unveraendertes Verhalten fuer
    alle bestehenden Aufrufer (kein Query-Parameter gesetzt = exakt die
    bisherige Query, siehe services/jurisdiction/resolve.py::
    resolve_cma_for_jurisdiction, das fuer jurisdiction in (None,'CH') die
    identische Query ohne jurisdiction-Filter faehrt und tenant_id ignoriert)."""
    jur = jurisdiction if jurisdiction not in (None, "") else "CH"
    resolved_jurisdiction = None if jur == "CH" else jur
    try:
        cma = resolve_cma_for_jurisdiction(db, resolved_jurisdiction, tenant_id=tenant_id)
    except JurisdictionReferenceDataMissingError:
        # Byte-identische 404-Message zum bisherigen CH-Verhalten.
        raise HTTPException(status_code=404, detail="Keine Kapitalmarktannahmen gefunden")
    return cma


@router.put("/capital-market-assumptions",
            response_model=CapitalMarketAssumptionResponse)
def update_cma(
    body: CapitalMarketAssumptionCreate,
    request: Request,
    # 2026-07-31 (WP3): siehe Kommentar in get_current_cma() -- bewusst PLAIN
    # defaults statt fastapi.Query(...) fuer Direktaufruf-Kompatibilitaet.
    jurisdiction: str = "CH",
    tenant_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Admin only — update capital market assumptions (creates new version).

    rp-ueberarbeitung: nicht im Body gesetzte Felder werden von der vorigen
    Version uebernommen, damit ein partial-Update keine zuvor gepflegten
    sub_asset_class/correlation/etc. Werte unbeabsichtigt loescht.

    2026-07-31 (WP3, Jurisdiktions-Verwaltung): optionaler jurisdiction/
    tenant_id Query-Parameter, Default "CH". Fuer jurisdiction="CH" (Default)
    bleibt die Vorgaenger-Suche UNVERAENDERT (kein jurisdiction-Filter noetig,
    weil bestehende CH-Zeilen jurisdiction IS NULL haben und das vor WP3 die
    einzigen is_current=1-Zeilen ueberhaupt waren) -- die Versionierungslogik
    selbst (Snapshot/Supersede/version+1) ist NICHT angefasst. Fuer eine
    andere jurisdiction wird die Vorgaenger-Suche zusaetzlich auf
    (jurisdiction, tenant_id) eingeschraenkt, damit ein DE-Update nicht
    versehentlich die CH-Zeile (oder eine andere Jurisdiktion/Tenant)
    superseded.
    """
    now = _now()
    payload = body.model_dump(exclude_unset=True)
    jur = jurisdiction if jurisdiction not in (None, "") else "CH"
    # Archive previous
    # 2026-07-25 (Generalaudit, Wave 11): with_for_update() ergaenzt --
    # fehlte hier als einzige is_current-Supersede-Stelle im gesamten
    # Codebase (anders als OptimizerPolicy/TargetAllocation/RiskAssessment/
    # ClientKnowledge). Zwei nahezu gleichzeitige Admin-Edits (Doppelklick/
    # Retry) haetten sonst zwei CMA-Versionen mit is_current=1 erzeugen koennen.
    prev_query = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None)
    )
    if jur == "CH":
        prev_query = prev_query.filter(
            or_(
                CapitalMarketAssumption.jurisdiction.is_(None),
                CapitalMarketAssumption.jurisdiction == "CH",
            ),
            CapitalMarketAssumption.tenant_id.is_(None),
        )
    else:
        prev_query = prev_query.filter(CapitalMarketAssumption.jurisdiction == jur)
        prev_query = prev_query.filter(
            CapitalMarketAssumption.tenant_id.is_(None)
            if not tenant_id
            else CapitalMarketAssumption.tenant_id == tenant_id
        )
    previous_rows = prev_query.with_for_update().all()
    if len(previous_rows) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Mehrere aktuelle CMA-Versionen fuer {jur} und den gewaehlten "
                "Tenant-Scope gefunden; Update blockiert, bis der "
                "Referenzdatenkonflikt bereinigt ist."
            ),
        )
    prev = previous_rows[0] if previous_rows else None
    prev_dict: dict = {}
    prev_version = 0
    if prev:
        immutable_or_scope_fields = {
            "id", "version", "is_current", "created_by", "created_at",
            "updated_at", "deleted_at", "jurisdiction", "tenant_id",
        }
        # Preserve every persisted model input, including optimizer-effective
        # tail moments and future additive CMA columns.  Copying only Pydantic
        # request fields silently erased model inputs on a partial version bump.
        for column in CapitalMarketAssumption.__table__.columns:
            if column.name not in immutable_or_scope_fields:
                prev_dict[column.name] = getattr(prev, column.name, None)
        prev.is_current = 0
        prev_version = prev.version
    merged = {**prev_dict, **payload}
    cma = CapitalMarketAssumption(
        id=new_uuid(),
        version=prev_version + 1,
        is_current=1,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
        **merged
    )
    if jur == "CH":
        cma.jurisdiction = "CH"
        cma.tenant_id = None
    else:
        cma.jurisdiction = jur
        cma.tenant_id = tenant_id or None
    db.add(cma)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="capital_market_assumptions", record_id=cma.id, action="CREATE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(cma)
    return cma


@router.post("/mandates/{mandate_id}/target-allocation/generate",
             response_model=TargetAllocationGenerateResponse)
def generate_target_allocation_endpoint(
    mandate_id: str,
    body: TargetAllocationGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # Welle 2.1 (2026-07): Opt-in FIDLEG-Hard-Gate. Default AUS
    # (require_suitability_before_recommendation=False) → heutiges Verhalten,
    # der Suitability-Check bleibt reiner Sichtbarkeits-Layer und blockiert
    # NICHT. Nur wenn das Flag aktiv ist, wird VOR der Generierung geprueft,
    # ob eine aktuelle/konforme Eignungspruefung vorliegt (FIDLEG Art. 11-13).
    # Konservativ: blockiert ausschliesslich wenn audit_mandate_suitability
    # is_compliant=False meldet (fehlende/nicht-konforme Pruefung).
    if settings.require_suitability_before_recommendation:
        suitability = audit_mandate_suitability(db, mandate)
        if not suitability.get("is_compliant", True):
            raise HTTPException(
                status_code=409,
                detail=(
                    "FIDLEG: Eignungsprüfung fehlt oder ist nicht aktuell — "
                    "Empfehlung blockiert "
                    "(require_suitability_before_recommendation=True)."
                ),
            )
    try:
        result = generate_target_allocation(
            db=db,
            mandate=mandate,
            user_id=current_user.id,
            preferences=body.preferences.model_dump() if body.preferences else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    refresh_system_review_triggers(db, mandate, current_user.id)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="target_allocations", record_id=result["target_allocation"].id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id,
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(result["target_allocation"])
    return result


@router.post("/mandates/{mandate_id}/target-allocation/sensitivity",
             response_model=AllocationSensitivityResponse)
def goal_target_sensitivity(
    mandate_id: str,
    body: AllocationSensitivityRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Phase 6 FE-Optimizer-Panel: ein einzelnes Goal um delta_pct verschieben
    und neuen Solver-Lauf zurueckliefern (mit gepinntem Seed = identische
    Scenarios = sauberes Apples-to-Apples-Delta).

    Gibt 409 wenn OPTIMIZER_MODE != 'stochastic' oder kein Risikoprofil.
    Gibt 404 wenn Goal nicht zum Mandanten gehoert.

    FINMA-Trace: jeder Aufruf wird als SENSITIVITY-Eintrag im AuditLog
    persistiert (mandate, goal, delta).
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        result = evaluate_goal_sensitivity(
            db=db,
            mandate=mandate,
            user_id=current_user.id,
            goal_id=body.goal_id,
            target_delta_pct=body.target_delta_pct,
            # Sprint U-P5 Fix H9: Horizon-Perturbation optional
            horizon_delta_years=getattr(body, "horizon_delta_years", 0),
        )
    except ValueError as exc:
        msg = str(exc)
        if "nicht gefunden" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    # Phase 6.3: AuditLog-Eintrag fuer FINMA-Trace. record_id = goal_id, weil
    # die Sensitivity sich auf ein konkretes Goal bezieht; new_value = delta_pct
    # damit forensisch nachvollziehbar ist welche Schieber bewegt wurden.
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="goals", record_id=body.goal_id, action="SENSITIVITY",
        new_value=str(body.target_delta_pct),
        mandate_id=mandate_id, client_id=mandate.client_id,
        ip_address=_extract_client_ip(request))
    db.commit()
    return result


# ============================================================================
# Sprint U-P12 (2026-05-20): Depot-Check pro Mandant
#
# Endpoint liefert eine vollstaendige Diversifikations-Analyse:
# - IST-vs-SOLL pro Asset-Klasse (Bands)
# - Country/Sector/Currency-Exposure aggregiert aus Produkt-Tiefe
# - Konzentrations-HHI pro Dimension
# - Top-10-Positionen + Fund-Charakteristika (TER/Duration/ESG)
# - Liquiditaets-Profil + automatische Warnings
# ============================================================================


@router.get("/mandates/{mandate_id}/depot-check")
def get_depot_check(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Vollstaendiger Depot-Check fuer das Mandat.

    Defensive: kein Crash bei fehlenden Daten. Returnt was berechnen geht +
    Liste der Warnings/Empfehlungen.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    return compute_depot_check(db, mandate)


@router.get("/mandates/{mandate_id}/advisory-report")
def get_advisory_report(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-P21: Voller 15-Seiten Advisory-Report als JSON.

    Konsumiert von der React-Sub-App (5eyes-electron/frontend/reporting/,
    folgt in U-P22) und vom Server-PDF (U-P26). Berater-Auth via
    get_current_user, gleiche Pattern wie Depot-Check-Endpoint.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    return cached_compute_advisory_report(db, mandate, advisor=current_user)


# ---------------------------------------------------------------------------
# Sprint U-P28 — Berater-Overrides für den Advisory-Report.
# Eine Zeile pro Mandat (UNIQUE auf mandate_id); GET liefert die Override-
# Texte falls vorhanden, sonst leere Defaults. PUT macht Upsert. Der
# Aggregator (services.advisory_report) konsumiert diese Tabelle und fällt
# pro Feld auf den Auto-Default-Text zurück, wenn keine Override gepflegt ist.

def _parse_json_list(raw: Optional[str]) -> list[str]:
    """Defensiv: kein JSON in der DB → leere Liste, nicht Crash."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item is not None]


def _serialize_notes(notes: "MandateReportNotes") -> dict:
    # Sprint U-37b (2026-06-04): History aus previous_versions_json
    # exponieren — schliesst U-37 Review-Lücke aus PR #140.
    from services.notes_versioning import load_history as _u37_load_history
    return {
        "id": notes.id,
        "mandate_id": notes.mandate_id,
        "aa_anmerkungen": notes.aa_anmerkungen,
        "waehrungen_erklaerung": notes.waehrungen_erklaerung,
        "branchen_analyse": notes.branchen_analyse,
        "vorgehen_block_optimierungen": notes.vorgehen_block_optimierungen,
        "vorgehen_block_zielstrategie": notes.vorgehen_block_zielstrategie,
        "vorgehen_offene_fragen": _parse_json_list(notes.vorgehen_offene_fragen_json),
        "vorgehen_naechster_termin": notes.vorgehen_naechster_termin,
        "vorgehen_todos": _parse_json_list(notes.vorgehen_todos_json),
        "vorgehen_dokumente": _parse_json_list(notes.vorgehen_dokumente_json),
        "last_edited_by": notes.last_edited_by,
        "last_edited_at": notes.last_edited_at,
        "created_at": notes.created_at,
        "updated_at": notes.updated_at,
        "previous_versions": _u37_load_history(notes),
    }


@router.get("/mandates/{mandate_id}/report-notes", response_model=ReportNotesResponse)
def get_report_notes(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """U-P28: Berater-Overrides fuer den Advisory-Report.

    Leere Zeile (noch nichts gepflegt) → leere Response mit nur `mandate_id`
    gesetzt. Die Sub-App und das PDF konsumieren denselben Aggregator und
    fallen pro Feld auf den Auto-Default-Text zurueck.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    notes = (
        db.query(MandateReportNotes)
        .filter(MandateReportNotes.mandate_id == mandate.id)
        .first()
    )
    if notes is None:
        return ReportNotesResponse(mandate_id=mandate.id)
    return ReportNotesResponse(**_serialize_notes(notes))


@router.put("/mandates/{mandate_id}/report-notes", response_model=ReportNotesResponse)
def put_report_notes(
    mandate_id: str,
    body: ReportNotesUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """U-P28: Upsert der Berater-Overrides.

    Auth: nur Berater (require_advisor) — Kunden sehen den Report
    read-only. Audit-Anchor (`last_edited_by` + `last_edited_at`) wird bei
    jedem PUT aktualisiert; das `created_at` bleibt beim ersten Insert.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    notes = (
        db.query(MandateReportNotes)
        .filter(MandateReportNotes.mandate_id == mandate.id)
        .first()
    )

    now = _now()
    if notes is None:
        notes = MandateReportNotes(
            id=new_uuid(),
            mandate_id=mandate.id,
            created_at=now,
            updated_at=now,
            last_edited_by=current_user.id,
            last_edited_at=now,
        )
        db.add(notes)

    # Sprint U-37: ALT-Werte snapshotten VOR Update fuer
    # previous_versions_json History.
    from services.notes_versioning import (
        NOTES_VERSIONED_FIELDS as _u37_fields,
        compute_changes as _u37_compute_changes,
        _parse_history as _u37_parse_history,
        _now_iso as _u37_now_iso,
    )
    _u37_old_values = {f: getattr(notes, f, None) for f in _u37_fields}
    _u37_new_values: dict[str, Any] = {}

    # Felder updaten — None laesst das bestehende Feld unangetastet
    # (Schritt-fuer-Schritt-Bearbeitung in der Sub-App), `""` setzt explizit
    # auf leer und triggert damit den Auto-Default-Fallback im Aggregator.
    if body.aa_anmerkungen is not None:
        _u37_new_values["aa_anmerkungen"] = body.aa_anmerkungen or None
        notes.aa_anmerkungen = body.aa_anmerkungen or None
    if body.waehrungen_erklaerung is not None:
        _u37_new_values["waehrungen_erklaerung"] = body.waehrungen_erklaerung or None
        notes.waehrungen_erklaerung = body.waehrungen_erklaerung or None
    if body.branchen_analyse is not None:
        _u37_new_values["branchen_analyse"] = body.branchen_analyse or None
        notes.branchen_analyse = body.branchen_analyse or None
    if body.vorgehen_block_optimierungen is not None:
        _u37_new_values["vorgehen_block_optimierungen"] = body.vorgehen_block_optimierungen or None
        notes.vorgehen_block_optimierungen = body.vorgehen_block_optimierungen or None
    if body.vorgehen_block_zielstrategie is not None:
        _u37_new_values["vorgehen_block_zielstrategie"] = body.vorgehen_block_zielstrategie or None
        notes.vorgehen_block_zielstrategie = body.vorgehen_block_zielstrategie or None
    if body.vorgehen_offene_fragen is not None:
        _val = json.dumps([str(item) for item in body.vorgehen_offene_fragen])
        _u37_new_values["vorgehen_offene_fragen_json"] = _val
        notes.vorgehen_offene_fragen_json = _val
    if body.vorgehen_naechster_termin is not None:
        _u37_new_values["vorgehen_naechster_termin"] = body.vorgehen_naechster_termin or None
        notes.vorgehen_naechster_termin = body.vorgehen_naechster_termin or None
    if body.vorgehen_todos is not None:
        _val = json.dumps([str(item) for item in body.vorgehen_todos])
        _u37_new_values["vorgehen_todos_json"] = _val
        notes.vorgehen_todos_json = _val
    if body.vorgehen_dokumente is not None:
        _val = json.dumps([str(item) for item in body.vorgehen_dokumente])
        _u37_new_values["vorgehen_dokumente_json"] = _val
        notes.vorgehen_dokumente_json = _val

    # U-37: bei tatsaechlichen Aenderungen Snapshot in History prependen.
    _u37_changes = _u37_compute_changes(_u37_old_values, _u37_new_values)
    if _u37_changes:
        _u37_history = _u37_parse_history(
            getattr(notes, "previous_versions_json", None)
        )
        _u37_history.insert(0, {
            "edited_at": _u37_now_iso(),
            "edited_by": current_user.id,
            "changes": _u37_changes,
        })
        notes.previous_versions_json = json.dumps(_u37_history)

    notes.last_edited_by = current_user.id
    notes.last_edited_at = now
    notes.updated_at = now

    # Audit-Eintrag in dieselbe Transaktion einbinden, damit Notes und
    # Audit-Log zusammen committed werden (FINMA-Anforderung).
    db.flush()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="mandate_report_notes",
        record_id=notes.id,
        action="UPDATE",
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        ip_address=_extract_client_ip(request),
    )
    db.commit()
    db.refresh(notes)
    # U-19: Cache invalidieren, damit die naechste GET /advisory-report den
    # frisch gespeicherten Override sofort sieht (statt bis zu TTL-Sekunden
    # auf Auto-Default-Cache zu zeigen).
    invalidate_advisory_cache(mandate.id)
    return ReportNotesResponse(**_serialize_notes(notes))


@router.get("/mandates/{mandate_id}/backtest/stress-replays")
def get_backtest_stress_replays(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-P13: Historische Stress-Szenarien (Dotcom 2000-2002, GFC
    2008, Covid 2020, Bonds-Crash 2022, Stagflation 1973-74) angewandt
    auf die aktuelle Target-Allocation des Mandates.

    Foundation-Variante mit hartcodierten Returns. Voll-Pipeline mit
    historischer Time-Series kommt in Sprint U-P11.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    return compute_stress_replays(db, mandate)


@router.get("/optimizer-policies", response_model=list[OptimizerPolicyResponse])
def list_optimizer_policies_read(
    include_historic: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-P15: Read-only Policy-Liste für Advisor-UI (A/B-Backtest-
    Selektoren). Im Gegensatz zu /admin/optimizer-policies erfordert dieser
    Endpoint kein Admin-Recht — er liefert nur die schlanke Liste ohne
    HouseMatrix-Detail-Rows.
    """
    q = db.query(OptimizerPolicy)
    if not include_historic:
        q = q.filter(OptimizerPolicy.is_current == 1)
    return q.order_by(
        OptimizerPolicy.policy_name.asc(),
        OptimizerPolicy.version.desc(),
    ).all()


@router.get("/mandates/{mandate_id}/backtest/ab")
def get_backtest_ab(
    mandate_id: str,
    policy_a: str,
    policy_b: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-P15: A/B-HouseMatrix-Backtest.

    Vergleicht zwei OptimizerPolicy-Versionen auf dem Risikoprofil des
    Mandates und liefert Bucket-Gewichtung, Risk-Metriken (Return/Vol/
    Sharpe/TER) und Stress-Replays pro Policy + Diff-Strukturen.

    Read-only: kein DB-Mutation, kein Audit-Log nötig.

    Fehler:
        400: policy_a == policy_b
        404: eine der Policies nicht gefunden
        409: Assessment fehlt oder keine aktive CMA
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        return run_ab_backtest(db, mandate, policy_a, policy_b)
    except ValueError as exc:
        msg = str(exc)
        if "müssen unterschiedlich" in msg:
            raise HTTPException(status_code=400, detail=msg)
        if "nicht gefunden" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)


def _parse_sub_asset_benchmark_query(value: str | None) -> dict[str, int] | None:
    """Phase 3 (2026-06-09): Parsed Query-Param 'benchmark_sub_assets'.

    Format: 'Aktien_CH_Large:5000,Aktien_US_Large:5000,Obligationen_CH_IG:0'
    Whitespace toleriert. Leerer/None -> None (kein Sub-Asset-Benchmark).
    Ungueltige Eintraege werden geskippt (kein Crash); Endsumme wird im
    Service _normalize_sub_asset_weights normalisiert.
    """
    if not value or not value.strip():
        return None
    out: dict[str, int] = {}
    for part in value.split(","):
        if ":" not in part:
            continue
        key, bps_str = part.split(":", 1)
        key = key.strip()
        bps_str = bps_str.strip()
        if not key:
            continue
        try:
            out[key] = int(bps_str)
        except (TypeError, ValueError):
            continue
    return out or None


@router.get("/mandates/{mandate_id}/backtest/strategy")
def get_strategy_backtest(
    mandate_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    benchmark_equities_bps: int | None = None,
    benchmark_bonds_bps: int | None = None,
    benchmark_real_estate_bps: int | None = None,
    benchmark_alternatives_bps: int | None = None,
    benchmark_liquidity_bps: int | None = None,
    resolution: str = "annual",
    # Bug-#8a (2026-06-07): Fee-Inputs in bps p.a.
    # strategy_fee_bps = TER + Beratungs-/Depotgebuehren der SOLL-Strategie.
    # benchmark_fee_bps = Fee, die der Benchmark (z.B. ein passives ETF-
    # Mandat) realistisch traegt. Bei 0 = Brutto-Index (theoretisch nicht
    # investierbar, aber als oberer Vergleichsanker nuetzlich).
    strategy_fee_bps: int | None = None,
    benchmark_fee_bps: int | None = None,
    # Phase 3 Sub-Asset (2026-06-09): Optional Benchmark auf Sub-Asset-
    # Granularitaet (z.B. SMI/SPI/SPX statt nur 'Aktien'). Format:
    # 'Key1:bps,Key2:bps' (Komma-getrennt, Doppelpunkt zwischen
    # Sub-Asset-Schluessel und Gewicht). Sub-Asset-Catalog in
    # services/market_data/symbol_catalog.py.
    benchmark_sub_assets: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-P17: SOLL-Strategie-Backtest auf historischen Jahresrenditen.

    Wendet die aktuelle TargetAllocation (Bucket-Gewichte) auf die Jahres-
    renditen aus admin/system/annual-returns an. Beratungsvermögen als
    Initial-Kapital (Snapshot aus advisory_wealth_at_generation_rappen,
    fallback aktuelle WealthPositions-Summe).

    Liefert für SOLL beide Pfade (mit / ohne jährlichem Rebalancing).
    Optional gleiche Methode auf einen frei konfigurierbaren Benchmark-Mix.

    Query-Params:
        start_year, end_year — optional, default = max verfügbarer Bereich
        benchmark_*_bps — optional, alle 5 zusammen ergeben den Benchmark.
            Wenn alle None, kein Benchmark. Summe wird auf 10000 normalisiert.
        benchmark_sub_assets — optional Sub-Asset-Benchmark, Format
            'Key1:bps,Key2:bps' (Phase 3 Sub-Asset-Sprint 2026-06-09).

    Read-only, kein Audit-Log.
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    bm_inputs = {
        "equities": benchmark_equities_bps,
        "bonds": benchmark_bonds_bps,
        "real_estate": benchmark_real_estate_bps,
        "alternatives": benchmark_alternatives_bps,
        "liquidity": benchmark_liquidity_bps,
    }
    benchmark = (
        {k: int(v) for k, v in bm_inputs.items() if v is not None}
        if any(v is not None for v in bm_inputs.values())
        else None
    )
    sub_benchmark = _parse_sub_asset_benchmark_query(benchmark_sub_assets)
    return run_strategy_backtest(
        db,
        mandate,
        start_year=start_year,
        end_year=end_year,
        benchmark_weights_bps=benchmark,
        resolution=resolution,
        strategy_fee_bps=strategy_fee_bps,
        benchmark_fee_bps=benchmark_fee_bps,
        benchmark_sub_weights_bps=sub_benchmark,
    )


@router.post("/mandates/{mandate_id}/portfolio/refresh-prices")
def refresh_portfolio_live_prices(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Sprint U-P11b (2026-05-22): Live-Preise für die Produkte dieses
    Mandates via Marktdaten-Aggregator (yfinance/stooq-Fallback) holen
    und in price_history persistieren.

    Engerer Scope als /admin/prices/refresh — nur Produkte aus dem
    aktuellsten RecommendationRun des Mandates werden aktualisiert.

    Returns Summary mit processed/inserted/updated/unchanged/failed +
    Failure-Liste pro Produkt.
    """
    from price_updater import refresh_prices_for_mandate
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    return refresh_prices_for_mandate(db, mandate.id)


# ============================================================================
# Sprint U-P7 (2026-05-20): OptimizerPolicy + HouseMatrix Admin-CRUD
#
# Versionierung: jeder strukturelle Edit erzeugt eine neue Policy-Row
# (vorige is_current=0). House-Matrix-Rows einer Policy werden bulk-ersetzt
# (atomar). Bestehende TargetAllocation-Records bleiben auf ihrer
# urspruenglichen policy_id verankert → Snapshot-faehig fuer Backtest.
#
# RBAC: alle Admin-Endpoints require_admin (HTTP 403 fuer advisor-only).
# ============================================================================


@router.get("/admin/optimizer-policies", response_model=list[OptimizerPolicyResponse])
def list_optimizer_policies(
    include_historic: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = db.query(OptimizerPolicy)
    if not include_historic:
        q = q.filter(OptimizerPolicy.is_current == 1)
    return q.order_by(OptimizerPolicy.policy_name.asc(), OptimizerPolicy.version.desc()).all()


@router.get("/admin/optimizer-policies/{policy_id}", response_model=OptimizerPolicyDetailResponse)
def get_optimizer_policy_detail(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"OptimizerPolicy {policy_id} nicht gefunden")
    rows = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy_id,
        HouseMatrix.is_active == 1,
    ).order_by(HouseMatrix.score_from.asc()).all()
    payload = {c.name: getattr(policy, c.name) for c in policy.__table__.columns}
    payload["house_matrix_rows"] = [
        HouseMatrixResponse.model_validate(r, from_attributes=True) for r in rows
    ]
    return OptimizerPolicyDetailResponse(**payload)


@router.post("/admin/optimizer-policies", response_model=OptimizerPolicyDetailResponse, status_code=201)
def create_optimizer_policy(
    body: OptimizerPolicyCreate,
    request: Request,
    activate: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    now = _now()
    if activate:
        prev = db.query(OptimizerPolicy).filter(
            OptimizerPolicy.is_current == 1,
        ).with_for_update().first()
        if prev:
            prev.is_current = 0
            prev.valid_to = now
            prev.updated_at = now
            # The new active row is inserted below.  Persist deactivation
            # first so the immediate partial unique index never sees two
            # current policies in a single flush.
            db.flush()

    policy = OptimizerPolicy(
        id=new_uuid(),
        policy_name=body.policy_name,
        version=1,
        is_current=1 if activate else 0,
        valid_from=now,
        optimizer_engine=body.optimizer_engine,
        max_real_estate_bps=int(body.max_real_estate_bps),
        max_alternatives_bps=int(body.max_alternatives_bps),
        min_liquidity_bps=int(body.min_liquidity_bps),
        fee_model_json=body.fee_model_json,
        notes=body.notes,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    db.flush()

    for row in body.house_matrix_rows:
        hm = HouseMatrix(
            id=new_uuid(),
            policy_id=policy.id,
            **row.model_dump(),
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(hm)

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="optimizer_policies", record_id=policy.id, action="CREATE",
        new_value=body.policy_name, ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(policy)
    return get_optimizer_policy_detail(policy.id, db, current_user)


@router.put("/admin/optimizer-policies/{policy_id}", response_model=OptimizerPolicyResponse)
def update_optimizer_policy(
    policy_id: str,
    body: OptimizerPolicyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} nicht gefunden")
    payload = body.model_dump(exclude_none=True)
    now = _now()
    # Sprint U-103 (2026-06-05): vor In-Place-Update einen Archive-Snapshot
    # der bisherigen Policy schreiben. Dadurch bleibt rekonstruierbar welche
    # Werte zur Generierung einer historischen TargetAllocation in Kraft
    # waren. Die aktuelle Zeile bleibt unter derselben policy_id erreichbar
    # (FK-Integritaet bestehender TAs unveraendert).
    if payload:
        previous_version = policy.version
        _archive_policy_snapshot(db, policy, now=now)
        policy.version = previous_version + 1
        policy.valid_from = now
        policy.valid_to = None
    for field, value in payload.items():
        setattr(policy, field, value)
    policy.updated_at = now
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="optimizer_policies", record_id=policy_id, action="UPDATE",
        new_value=", ".join(f"{k}={v}" for k, v in payload.items()),
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(policy)
    return policy


@router.put("/admin/optimizer-policies/{policy_id}/house-matrix",
            response_model=OptimizerPolicyDetailResponse)
def replace_house_matrix_rows(
    policy_id: str,
    body: HouseMatrixRowsReplace,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} nicht gefunden")

    # Redesign 2026-06-10: Versionstreue serverseitig durchsetzen. Die House-Matrix-
    # Rows werden hier in-place ersetzt (kein Archiv-Snapshot wie beim Policy-PUT).
    # Auf der AKTIVEN Policy wuerde das alle laufenden Mandate still veraendern und
    # das UI-Versprechen "jeder Edit erzeugt eine neue Version" brechen. Editieren
    # daher nur auf Draft/Klon erlauben; danach via /activate scharf schalten.
    if policy.is_current == 1:
        raise HTTPException(
            status_code=409,
            detail="Aktive Policy kann nicht direkt überschrieben werden — bitte zuerst klonen und die neue Version aktivieren.",
        )

    now = _now()
    db.query(HouseMatrix).filter(HouseMatrix.policy_id == policy_id).delete()
    for row in body.rows:
        hm = HouseMatrix(
            id=new_uuid(),
            policy_id=policy_id,
            **row.model_dump(),
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(hm)
    policy.updated_at = now
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="house_matrix", record_id=policy_id, action="REPLACE_ALL",
        new_value=f"{len(body.rows)} rows", ip_address=_extract_client_ip(request))
    db.commit()
    return get_optimizer_policy_detail(policy_id, db, current_user)


@router.post("/admin/optimizer-policies/{policy_id}/activate",
             response_model=OptimizerPolicyResponse)
def activate_optimizer_policy(
    policy_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} nicht gefunden")
    if policy.is_current == 1:
        return policy

    now = _now()
    prev = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.is_current == 1,
    ).with_for_update().first()
    if prev and prev.id != policy_id:
        prev.is_current = 0
        prev.valid_to = now
        prev.updated_at = now
        # SQLAlchemy orders same-table UPDATEs by primary key.  Without this
        # boundary it can activate ``policy`` before clearing ``prev`` and
        # trip the immediate global-current unique index.
        db.flush()

    policy.is_current = 1
    policy.valid_from = now
    policy.valid_to = None
    policy.updated_at = now
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="optimizer_policies", record_id=policy_id, action="ACTIVATE",
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(policy)
    return policy


@router.post("/admin/optimizer-policies/{policy_id}/clone",
             response_model=OptimizerPolicyDetailResponse, status_code=201)
def clone_optimizer_policy(
    policy_id: str,
    request: Request,
    new_name: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    source = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Source-Policy {policy_id} nicht gefunden")

    now = _now()
    max_version = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.policy_name == source.policy_name,
    ).order_by(OptimizerPolicy.version.desc()).first()
    next_version = (int(max_version.version) if max_version else 0) + 1

    clone = OptimizerPolicy(
        id=new_uuid(),
        policy_name=(new_name or source.policy_name),
        version=next_version,
        is_current=0,
        valid_from=now,
        optimizer_engine=source.optimizer_engine,
        max_real_estate_bps=source.max_real_estate_bps,
        max_alternatives_bps=source.max_alternatives_bps,
        min_liquidity_bps=source.min_liquidity_bps,
        allow_other_assets_for_goals=source.allow_other_assets_for_goals,
        fee_model_json=source.fee_model_json,
        notes=f"Geklont aus {source.id} ({source.policy_name} v{source.version})",
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(clone)
    db.flush()

    source_rows = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == source.id,
        HouseMatrix.is_active == 1,
    ).order_by(HouseMatrix.score_from.asc()).all()
    for src_row in source_rows:
        new_row = HouseMatrix(
            id=new_uuid(),
            policy_id=clone.id,
            score_from=src_row.score_from,
            score_to=src_row.score_to,
            profile_name=src_row.profile_name,
            liq_min_bps=src_row.liq_min_bps,
            liq_target_bps=src_row.liq_target_bps,
            liq_max_bps=src_row.liq_max_bps,
            bonds_min_bps=src_row.bonds_min_bps,
            bonds_target_bps=src_row.bonds_target_bps,
            bonds_max_bps=src_row.bonds_max_bps,
            equity_min_bps=src_row.equity_min_bps,
            equity_target_bps=src_row.equity_target_bps,
            equity_max_bps=src_row.equity_max_bps,
            real_estate_min_bps=src_row.real_estate_min_bps,
            real_estate_target_bps=src_row.real_estate_target_bps,
            real_estate_max_bps=src_row.real_estate_max_bps,
            alt_min_bps=src_row.alt_min_bps,
            alt_target_bps=src_row.alt_target_bps,
            alt_max_bps=src_row.alt_max_bps,
            equity_minimum_bps=src_row.equity_minimum_bps,
            max_risky_fraction_bps=src_row.max_risky_fraction_bps,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(new_row)

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="optimizer_policies", record_id=clone.id, action="CLONE",
        old_value=source.id, new_value=clone.policy_name,
        ip_address=_extract_client_ip(request))
    db.commit()
    return get_optimizer_policy_detail(clone.id, db, current_user)
