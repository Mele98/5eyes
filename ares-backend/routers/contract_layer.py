"""Vertragsschicht (H-179, L2/L3): Owner-Inhalte mit Vier-Augen-Freigabe,
Gruende der Empfehlung (Art. 15 FIDLEG) und W033-Kundenbestaetigungen.

Muster der KYC-Wiedervorlage (routers/review.py, C-890-01): ein Firmen-Admin
erfasst eine Version, eine ZWEITE Person (Admin oder externe Compliance-
Person) gibt sie mit dem gesehenen Inhalts-Hash und einer Freigabereferenz
frei. Ares belegt keinen Text und keinen Wert vor.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from core.db_integrity import raise_if_check_violation
from core.reason_codes import ReasonCode
from database import get_db, new_uuid
from models.contract_layer import (
    OWNER_CONTENT_GENESIS,
    AdviceRationale,
    OwnerContentApproval,
    OwnerContentVersion,
    W033ClientDeclaration,
)
from models.review import RecommendationRun
from models.users import User
from routers.auth import _extract_client_ip
from schemas.contract_layer import (
    AdviceRationaleCreate,
    OwnerContentApprove,
    OwnerContentCreate,
    W033DeclarationCreate,
)
from services import contract_layer as layer
from services import owner_content as oc
from services.audit import log
from services.auth import (
    _effective_strict_tenant_isolation,
    _resolve_tenant_id_for_user,
    assert_compliance_reviewer_ready,
    get_mandate_for_user_or_404,
    require_admin,
    require_advisor,
    require_compliance_approver,
    require_staff,
    same_person,
)
from services.recommendation_release_gate import row_seal

router = APIRouter(tags=["Vertragsschicht"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _seal(record, column: str) -> str:
    return row_seal({c.name: getattr(record, c.name) for c in record.__table__.columns}, column)


def _owner_tenant(current_user: User) -> str:
    if not getattr(current_user, "tenant_id", None) and _effective_strict_tenant_isolation(settings):
        raise HTTPException(status_code=403, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_TENANT_REQUIRED.value,
            "message": "Im Mehrmandanten-Betrieb braucht der Admin eine eigene Firma.",
        })
    return _resolve_tenant_id_for_user(current_user)


def _row_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _resolution_view(resolution: dict, entry: oc.CatalogEntry | None) -> dict:
    version = resolution.get("version") or {}
    draft = resolution.get("latest_draft") or {}
    return {
        "key": resolution["key"],
        "group": entry.group if entry else None,
        "label": entry.label if entry else resolution["key"],
        "kind": entry.kind if entry else None,
        "placeholder": entry.placeholder if entry else None,
        "owner_input": entry.owner_input if entry else None,
        "visible_in": entry.visible_in if entry else None,
        "required": entry.required if entry else None,
        "status": resolution["status"],
        "effective_version": version.get("version"),
        "effective_row_id": version.get("id"),
        "effective_content_hash": version.get("content_hash"),
        "effective_body_text": version.get("body_text"),
        "effective_value_json": version.get("value_json"),
        "approved_at": (resolution.get("approval") or {}).get("approved_at"),
        "draft_row_id": draft.get("id"),
        "draft_version": draft.get("version"),
        "draft_content_hash": draft.get("content_hash"),
        "draft_body_text": draft.get("body_text"),
        "draft_value_json": draft.get("value_json"),
        "draft_created_by": draft.get("created_by"),
    }


@router.get("/compliance/owner-content")
def list_owner_content(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Katalog der Owner-Inhalte der eigenen Firma mit Status (fehlt, Entwurf,
    freigegeben, Kette ungültig), wirksamer Version und offenem Entwurf.
    Zusätzlich die bereits erfassten Bank-Schlüssel (Zuwendungen der Depotbank)."""
    tenant_id = _resolve_tenant_id_for_user(current_user)
    items = [
        _resolution_view(oc.resolve_owner_content(db, tenant_id, entry.key), entry)
        for entry in oc.static_catalog()
    ]
    bank_keys = sorted({
        str(row[0]) for row in db.query(OwnerContentVersion.content_key).filter(
            OwnerContentVersion.tenant_id == tenant_id,
            OwnerContentVersion.content_key.like(oc.DEPOT_BANK_KEY_PREFIX + "%"),
        ).all()
    })
    for key in bank_keys:
        items.append(_resolution_view(oc.resolve_owner_content(db, tenant_id, key), oc.catalog_entry(key)))
    return {
        "tenant_id": tenant_id,
        "catalog_version": oc.CATALOG_VERSION,
        "contract_mandate_types": list(oc.CONTRACT_MANDATE_TYPES),
        "contract_clauses": [{"clause": c[0], "label": c[1], "placeholder": c[3]} for c in oc.CONTRACT_CLAUSES],
        "items": items,
    }


@router.post("/compliance/owner-content", status_code=201)
def create_owner_content(
    body: OwnerContentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Neue Version eines Owner-Inhalts (Firmen-Admin). Wirksam erst nach der
    Freigabe durch eine zweite Person (``/approve``)."""
    tenant_id = _owner_tenant(current_user)
    key = body.content_key.strip()
    entry = oc.catalog_entry(key)
    if entry is None:
        raise HTTPException(status_code=422, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_KEY_UNKNOWN.value,
            "message": "Unbekannter Schlüssel; erlaubt sind nur Schlüssel aus dem Katalog.",
        })
    try:
        body_text, value_json = oc.normalize_payload(entry, body.body_text, body.value)
    except oc.OwnerContentInvalid as exc:
        raise HTTPException(status_code=422, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_VALUE_INVALID.value, "message": str(exc),
        }) from exc
    versions, _approvals = oc.owner_content_chain(db, tenant_id, key)
    version = max((int(v["version"]) for v in versions.values()), default=0) + 1
    record = OwnerContentVersion(
        id=new_uuid(), tenant_id=tenant_id, content_key=key, catalog_version=oc.CATALOG_VERSION,
        version=version, body_text=body_text, value_json=value_json,
        source_reference=body.source_reference.strip(), created_by=current_user.id, created_at=_now(),
    )
    record.content_hash = _seal(record, "content_hash")
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise_if_check_violation(exc)
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_VERSION_CONFLICT.value,
            "message": "Gleichzeitig wurde eine andere Version erfasst; bitte neu laden.",
        }) from exc
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="owner_content_versions", record_id=record.id, action="CREATE",
        field_name="owner_content_proposed",
        new_value=f"{key} v{version}; hash {record.content_hash}",
        ip_address=_extract_client_ip(request), tenant_id=tenant_id)
    db.commit()
    return _resolution_view(oc.resolve_owner_content(db, tenant_id, key), entry) | {"created_row_id": record.id}


@router.post("/compliance/owner-content/{row_id}/approve")
def approve_owner_content(
    row_id: str,
    body: OwnerContentApprove,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_compliance_approver),
):
    """Vier-Augen-Freigabe einer Version durch eine zweite Person mit dem
    gesehenen Inhalts-Hash. Die Freigaben bilden je Schlüssel eine lineare
    Kette; zwei gleichzeitige Freigaben auf denselben Stand scheitern (409)."""
    tenant_id = _owner_tenant(current_user)
    record = db.query(OwnerContentVersion).filter(
        OwnerContentVersion.id == row_id, OwnerContentVersion.tenant_id == tenant_id,
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Version nicht gefunden")
    if db.query(OwnerContentApproval).filter(OwnerContentApproval.content_row_id == record.id).first():
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_ALREADY_APPROVED.value,
            "message": "Diese Version ist bereits freigegeben.",
        })
    if same_person(db, record.created_by, current_user.id):
        raise HTTPException(status_code=403, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_SAME_PERSON.value,
            "message": "Die Freigabe muss durch eine zweite Person erfolgen.",
        })
    assert_compliance_reviewer_ready(current_user)
    if _seal(record, "content_hash") != record.content_hash or body.content_hash != record.content_hash:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_HASH_MISMATCH.value,
            "message": "Der bestätigte Prüfwert stimmt nicht mit der Version überein.",
        })
    head = oc.resolve_owner_content(db, tenant_id, record.content_key)
    if head["status"] == oc.STATUS_INVALID:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_CHAIN_INVALID.value,
            "message": "Die bestehende Freigabekette ist ungültig; bitte Compliance informieren.",
        })
    if head["status"] == oc.STATUS_APPROVED:
        if int(record.version) <= int(head["version"]["version"]):
            raise HTTPException(status_code=409, detail={
                "reason_code": ReasonCode.OWNER_CONTENT_VERSION_STALE.value,
                "message": "Es ist bereits eine neuere Version freigegeben; bitte eine neue Version erfassen.",
            })
        predecessor = str(head["approval"]["id"])
    else:
        predecessor = OWNER_CONTENT_GENESIS
    approval = OwnerContentApproval(
        id=new_uuid(), tenant_id=tenant_id, content_key=record.content_key, content_row_id=record.id,
        predecessor_approval_id=predecessor, approved_by=current_user.id, approved_at=_now(),
        approval_reference=body.approval_reference.strip(), content_hash=record.content_hash,
    )
    approval.approval_hash = _seal(approval, "approval_hash")
    db.add(approval)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_VERSION_CONFLICT.value,
            "message": "Gleichzeitig wurde eine andere Freigabe erteilt; bitte neu laden.",
        }) from exc
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="owner_content_approvals", record_id=approval.id, action="CREATE",
        field_name="owner_content_approved",
        new_value=f"{record.content_key} v{record.version}; hash {record.content_hash}",
        ip_address=_extract_client_ip(request), tenant_id=tenant_id)
    db.commit()
    return _resolution_view(oc.resolve_owner_content(db, tenant_id, record.content_key),
                            oc.catalog_entry(record.content_key))


@router.get("/mandates/{mandate_id}/contract-layer")
def get_contract_layer_status(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Status der Vertragsschicht des Mandats (gleiche Quelle wie das Gate)."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    return layer.contract_layer_status(db, mandate)


@router.post("/mandates/{mandate_id}/recommendations/{run_id}/advice-rationale", status_code=201)
def create_advice_rationale(
    mandate_id: str,
    run_id: str,
    body: AdviceRationaleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """P-1 (Art. 15 FIDLEG): Kundenbedürfnisse und Gründe der Empfehlung zu
    einem Empfehlungslauf erfassen. Korrektur = neue Zeile."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    run = db.query(RecommendationRun).filter(
        RecommendationRun.id == run_id, RecommendationRun.mandate_id == mandate.id,
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": ReasonCode.ADVICE_RATIONALE_RUN_UNKNOWN.value,
            "message": "Empfehlung nicht gefunden.",
        })
    record = AdviceRationale(
        id=new_uuid(), tenant_id=mandate.tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
        recommendation_run_id=run.id, client_needs=body.client_needs.strip(),
        recommendation_reasons=body.recommendation_reasons.strip(),
        recorded_by=current_user.id, recorded_at=_now(),
    )
    record.rationale_hash = _seal(record, "rationale_hash")
    db.add(record)
    db.flush()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="advice_rationales", record_id=record.id, action="CREATE",
        field_name="advice_rationale_recorded", new_value=f"run {run.id}; hash {record.rationale_hash}",
        mandate_id=mandate.id, ip_address=_extract_client_ip(request))
    db.commit()
    return {k: v for k, v in _row_dict(record).items()}


@router.post("/mandates/{mandate_id}/w033-declarations", status_code=201)
def create_w033_declaration(
    mandate_id: str,
    body: W033DeclarationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """E-1: Bestätigung des Kunden zum aktuellen Risikoprofil erfassen, gebunden
    an die gezeigte, freigegebene Textversion der Firma (Prüfwert)."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    state = layer.w033_state(db, mandate)
    if state["assessment_id"] is None:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.W033_DECLARATION_NOT_APPLICABLE.value,
            "message": "Für das Mandat liegt kein aktuelles Risikoprofil vor.",
        })
    binding = state["declaration_binding"] if body.declaration_kind == "angaben_wahr_meldepflicht" \
        else state["advice_binding"]
    if binding is None:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.W033_TEXT_UNAPPROVED.value,
            "message": "Der Text der Firma ist nicht freigegeben.",
        })
    if body.content_hash != binding["content_hash"]:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.OWNER_CONTENT_HASH_MISMATCH.value,
            "message": "Der bestätigte Prüfwert passt nicht zur freigegebenen Textversion.",
        })
    if body.declaration_kind == "horizont_abraten" and not state["advice_required"]:
        raise HTTPException(status_code=409, detail={
            "reason_code": ReasonCode.W033_DECLARATION_NOT_APPLICABLE.value,
            "message": "Der Anlagehorizont liegt nicht unter dem Mindesthorizont der Firma.",
        })
    record = W033ClientDeclaration(
        id=new_uuid(), tenant_id=mandate.tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
        risk_assessment_id=state["assessment_id"], declaration_kind=body.declaration_kind,
        content_key=binding["key"], content_row_id=binding["content_row_id"],
        content_hash=binding["content_hash"], horizon_years=state["horizon_years"],
        min_horizon_years=state["min_horizon_years"], capture_channel=body.capture_channel,
        confirmed_at=body.confirmed_at, recorded_by=current_user.id, recorded_at=_now(),
    )
    record.declaration_hash = _seal(record, "declaration_hash")
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise_if_check_violation(exc)
        raise
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="w033_client_declarations", record_id=record.id, action="CREATE",
        field_name="w033_declaration_recorded",
        new_value=f"{body.declaration_kind}; assessment {state['assessment_id']}; hash {record.declaration_hash}",
        mandate_id=mandate.id, ip_address=_extract_client_ip(request))
    db.commit()
    return _row_dict(record)
