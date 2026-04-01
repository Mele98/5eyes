from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.review import (
    ReviewTrigger, AdvisoryLog, ContractDocument,
    ConflictOfInterestDisclosure, Product, ProductSuitability,
    RecommendationRun, RecommendationPosition, RecommendationHolding, AuditLog
)
from models.allocation import OptimizerPolicy
from schemas.review import (
    ReviewTriggerCreate, ReviewTriggerResolve, ReviewTriggerResponse,
    AdvisoryLogCreate, AdvisoryLogResponse,
    ContractDocumentCreate, ContractDocumentSign, ContractDocumentResponse,
    ConflictDisclosureCreate, ConflictDisclosureResponse,
    ProductCreate, ProductResponse,
    ProductIdMappingPreviewRequest, ProductIdMappingPreviewResponse,
    ProductIdMappingApplyRequest, ProductIdMappingApplyResponse,
    ProductIdMappingBatchApplyRequest, ProductIdMappingBatchApplyResponse,
    ProductReferencePreviewRequest, ProductReferencePreviewResponse,
    ProductReferenceApplyRequest, ProductReferenceApplyResponse,
    ProductReferenceBatchApplyRequest, ProductReferenceBatchApplyResponse,
    RecommendationRunCreate, RecommendationRunResponse,
    RecommendationPositionCreate, RecommendationPositionResponse,
    RecommendationHoldingUpsert, RecommendationHoldingResponse,
    RecommendationGenerateRequest, RecommendationGenerateResponse,
)
from price_updater import summarize_price_quality
from services.auth import get_accessible_client_ids, get_accessible_mandate_ids, get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, has_global_client_access, require_advisor, require_admin
from services.audit import log
from services.eodhd_client import preview_eodhd_reference
from services.openfigi_client import preview_openfigi_mapping
from services.portfolio_engine import build_recommendation_payload_from_run, generate_recommendation_run
from services.review_engine import refresh_system_review_triggers

router = APIRouter(tags=["Review & Dokumente"])
products_router = APIRouter(prefix="/products", tags=["Produkte"])
recommendations_router = APIRouter(tags=["Empfehlungen"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
ACTIVE_TRIGGER_STATUS_VALUES = ("Ausgelöst", "Ausgeloest", "AusgelÃ¶st", "AusgelÃƒÂ¶st")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


def _get_recommendation_run_or_404(
    mandate_id: str,
    run_id: str,
    db: Session,
    current_user: User,
) -> RecommendationRun:
    _get_mandate_or_404(mandate_id, db, current_user)
    run = db.query(RecommendationRun).filter(
        RecommendationRun.id == run_id,
        RecommendationRun.mandate_id == mandate_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Empfehlung nicht gefunden")
    return run


def _normalize_holding_date(value: str | None) -> str | None:
    raw = str(value or "").strip()[:10]
    return raw or None


def _is_blank(value: str | None) -> bool:
    return not str(value or "").strip()


def _reference_context(product: Product) -> dict[str, str | None]:
    return {
        "product_id": product.id,
        "product_name": product.product_name,
        "isin": product.isin,
        "symbol": product.symbol,
        "exchange_code": product.exchange_code,
        "currency": product.currency,
    }


def _apply_reference_candidate(
    *,
    product: Product,
    candidate: dict,
    now: str,
    overwrite_symbol: bool,
    overwrite_name: bool,
    overwrite_currency: bool,
) -> None:
    if candidate.get("isin") and _is_blank(product.isin):
        product.isin = candidate.get("isin")
    if candidate.get("symbol") and (overwrite_symbol or _is_blank(product.symbol)):
        product.symbol = candidate.get("symbol")
    if candidate.get("exchange_code") and _is_blank(product.exchange_code):
        product.exchange_code = candidate.get("exchange_code")
    if candidate.get("currency") and (overwrite_currency or _is_blank(product.currency)):
        product.currency = candidate.get("currency")
    if candidate.get("name") and (overwrite_name or _is_blank(product.product_name)):
        product.product_name = candidate.get("name")
    if candidate.get("instrument_type") and _is_blank(product.security_type):
        product.security_type = candidate.get("instrument_type")
    product.reference_data_provider = "eodhd"
    product.reference_data_refreshed_at = now
    product.updated_at = now


def _collect_product_market_data_status(db: Session) -> dict:
    products = (
        db.query(Product)
        .filter(Product.deleted_at.is_(None), Product.is_active == 1)
        .order_by(Product.product_name.asc())
        .all()
    )
    openfigi_pending = []
    reference_pending = []
    openfigi_mapped_count = 0
    reference_synced_count = 0
    symbol_count = 0
    isin_only_count = 0
    for product in products:
        has_symbol = not _is_blank(product.symbol)
        has_isin = not _is_blank(product.isin)
        if has_symbol:
            symbol_count += 1
        elif has_isin:
            isin_only_count += 1
        if str(product.mapping_provider or "").strip().lower() == "openfigi":
            openfigi_mapped_count += 1
        if not _is_blank(product.reference_data_provider):
            reference_synced_count += 1
        if has_isin and not has_symbol:
            openfigi_pending.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "currency": product.currency,
                }
            )
        if (has_symbol or has_isin or not _is_blank(product.product_name)) and _is_blank(product.reference_data_provider):
            reference_pending.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "symbol": product.symbol,
                    "currency": product.currency,
                }
            )
    return {
        "active_products": len(products),
        "symbol_count": symbol_count,
        "isin_only_count": isin_only_count,
        "openfigi_mapped_count": openfigi_mapped_count,
        "reference_synced_count": reference_synced_count,
        "openfigi_pending_count": len(openfigi_pending),
        "reference_pending_count": len(reference_pending),
        "samples": {
            "openfigi_pending": openfigi_pending[:8],
            "reference_pending": reference_pending[:8],
        },
        "price_quality": summarize_price_quality(db),
    }


def _normalize_trigger_frequency(trigger_type: str, frequency: str | None, trigger_name: str | None = None) -> str | None:
    if trigger_type == "Ereignis":
        return "bei Ereignis"
    raw = str(frequency or "").strip().lower()
    name = str(trigger_name or "").strip().lower()
    if not raw:
        raw = name
    normalized = (
        raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("?", "ae")
    )
    if "quart" in normalized or normalized.startswith("3 "):
        return "quartalsweise"
    if "halb" in normalized or normalized.startswith("6 "):
        return "halbjährlich"
    if "jahr" in normalized or normalized.startswith("12 "):
        return "jährlich"
    if "monat" in normalized or normalized.startswith("1 "):
        return "monatlich"
    if "einmal" in normalized:
        return "einmalig"
    if trigger_type == "Zeit":
        return "jährlich"
    return None


# ── Review Triggers ────────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/triggers", response_model=list[ReviewTriggerResponse])
def list_triggers(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(ReviewTrigger).filter(
        ReviewTrigger.mandate_id == mandate_id,
        ReviewTrigger.deleted_at.is_(None)
    ).order_by(ReviewTrigger.next_due_at).all()


@router.post("/mandates/{mandate_id}/triggers",
             response_model=ReviewTriggerResponse, status_code=201)
def create_trigger(
    mandate_id: str,
    body: ReviewTriggerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    payload = body.model_dump()
    payload["frequency"] = _normalize_trigger_frequency(
        trigger_type=payload["trigger_type"],
        frequency=payload.get("frequency"),
        trigger_name=payload.get("trigger_name"),
    )
    trigger = ReviewTrigger(
        id=new_uuid(), mandate_id=mandate_id,
        status="Aktiv", is_system=0,
        calendar_exported=0,
        created_at=now, updated_at=now,
        **payload
    )
    db.add(trigger)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="review_triggers", record_id=trigger.id, action="CREATE",
        mandate_id=mandate_id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "review_triggers" in str(exc).lower() and "frequency" in str(exc).lower():
            raise HTTPException(status_code=422, detail="Ungültige Review-Trigger-Frequenz für das aktuelle Schema")
        raise
    db.refresh(trigger)
    return trigger


@router.post("/mandates/{mandate_id}/triggers/system-refresh",
             response_model=list[ReviewTriggerResponse])
def refresh_system_triggers(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    triggers = refresh_system_review_triggers(db, mandate, current_user.id)
    db.commit()
    return triggers


@router.put("/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
            response_model=ReviewTriggerResponse)
def resolve_trigger(
    mandate_id: str, trigger_id: str,
    body: ReviewTriggerResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    trigger = db.query(ReviewTrigger).filter(
        ReviewTrigger.id == trigger_id,
        ReviewTrigger.mandate_id == mandate_id,
        ReviewTrigger.deleted_at.is_(None)
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger nicht gefunden")
    now = _now()
    trigger.status = "Erledigt"
    trigger.last_triggered_at = now
    trigger.triggered_notes = body.triggered_notes
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="review_triggers", record_id=trigger_id, action="UPDATE",
        field_name="status", new_value="Erledigt", mandate_id=mandate_id)
    db.commit()
    db.refresh(trigger)
    return trigger


# ── Advisory Log ───────────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/advisory-log", response_model=list[AdvisoryLogResponse])
def list_advisory_log(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(AdvisoryLog).filter(
        AdvisoryLog.mandate_id == mandate_id
    ).order_by(AdvisoryLog.entry_date.desc()).all()


@router.post("/mandates/{mandate_id}/advisory-log",
             response_model=AdvisoryLogResponse, status_code=201)
def create_advisory_log_entry(
    mandate_id: str,
    body: AdvisoryLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    entry = AdvisoryLog(
        id=new_uuid(), mandate_id=mandate_id,
        advisor_id=current_user.id,
        entry_date=body.entry_date or date.today().isoformat(),
        client_signed=1 if body.client_signed else 0,
        created_at=now, updated_at=now,
        **{k: v for k, v in body.model_dump().items()
           if k not in ("client_signed", "entry_date")}
    )
    db.add(entry)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="advisory_log", record_id=entry.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "advisory_log" in str(exc).lower() and "decision" in str(exc).lower():
            raise HTTPException(status_code=422, detail="Ungültiger Advisory-Entscheid für das aktuelle Schema")
        raise
    db.refresh(entry)
    return entry


# ── Contract Documents ─────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/documents", response_model=list[ContractDocumentResponse])
def list_documents(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(ContractDocument).filter(
        ContractDocument.mandate_id == mandate_id,
        ContractDocument.deleted_at.is_(None)
    ).order_by(ContractDocument.created_at.desc()).all()


@router.post("/mandates/{mandate_id}/documents",
             response_model=ContractDocumentResponse, status_code=201)
def create_document(
    mandate_id: str,
    body: ContractDocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    doc = ContractDocument(
        id=new_uuid(), mandate_id=mandate_id,
        status="Entwurf", version=1,
        signed_by_advisor=0, signed_by_client=0,
        created_by=current_user.id,
        created_at=now, updated_at=now,
        **body.model_dump()
    )
    db.add(doc)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="contract_documents", record_id=doc.id, action="CREATE",
        mandate_id=mandate_id)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/mandates/{mandate_id}/documents/{doc_id}/sign",
             response_model=ContractDocumentResponse)
def sign_document(
    mandate_id: str, doc_id: str,
    body: ContractDocumentSign,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    doc = db.query(ContractDocument).filter(
        ContractDocument.id == doc_id,
        ContractDocument.mandate_id == mandate_id,
        ContractDocument.deleted_at.is_(None)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    now = _now()
    if body.signed_by_advisor:
        doc.signed_by_advisor = 1
    if body.signed_by_client:
        doc.signed_by_client = 1
    doc.signed_at = now
    doc.status = "Unterzeichnet"
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="contract_documents", record_id=doc_id, action="UPDATE",
        field_name="status", new_value="Unterzeichnet", mandate_id=mandate_id)
    db.commit()
    db.refresh(doc)
    return doc


# ── Conflicts of Interest ──────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/conflicts",
            response_model=list[ConflictDisclosureResponse])
def list_conflicts(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(ConflictOfInterestDisclosure).filter(
        ConflictOfInterestDisclosure.mandate_id == mandate_id,
        ConflictOfInterestDisclosure.deleted_at.is_(None)
    ).all()


@router.post("/mandates/{mandate_id}/conflicts",
             response_model=ConflictDisclosureResponse, status_code=201)
def create_conflict(
    mandate_id: str,
    body: ConflictDisclosureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    conflict = ConflictOfInterestDisclosure(
        id=new_uuid(), mandate_id=mandate_id,
        disclosed_by=current_user.id,
        disclosed_to_client=0, client_acknowledged=0,
        created_at=now, updated_at=now,
        **body.model_dump()
    )
    db.add(conflict)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="conflict_of_interest_disclosures", record_id=conflict.id,
        action="CREATE", mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(conflict)
    return conflict


# ── Products ───────────────────────────────────────────────────────────────────

@products_router.get("", response_model=list[ProductResponse])
def list_products(
    asset_class: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Product).filter(Product.deleted_at.is_(None), Product.is_active == 1)
    if asset_class:
        q = q.filter(Product.asset_class == asset_class)
    return q.order_by(Product.asset_class, Product.product_name).all()


@products_router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    body: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    now = _now()
    product = Product(
        id=new_uuid(), is_active=1,
        created_at=now, updated_at=now,
        **body.model_dump()
    )
    db.add(product)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="products", record_id=product.id, action="CREATE")
    db.commit()
    db.refresh(product)
    return product


@products_router.get("/market-data/status")
def get_product_market_data_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return _collect_product_market_data_status(db)


@products_router.post("/openfigi/resolve", response_model=ProductIdMappingPreviewResponse)
def resolve_product_id_mapping(
    body: ProductIdMappingPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = None
    if body.product_id:
        product = db.query(Product).filter(Product.id == body.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    try:
        return preview_openfigi_mapping(
            isin=body.isin or (product.isin if product else None),
            symbol=body.symbol or (product.symbol if product else None),
            exchange_code=body.exchange_code,
            mic_code=body.mic_code,
            currency=body.currency or (product.currency if product else None),
            context={
                "product_id": product.id if product else None,
                "product_name": product.product_name if product else None,
                "isin": body.isin or (product.isin if product else None),
                "symbol": body.symbol or (product.symbol if product else None),
                "currency": body.currency or (product.currency if product else None),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@products_router.post("/openfigi/apply", response_model=ProductIdMappingApplyResponse)
def apply_product_id_mapping(
    body: ProductIdMappingApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    try:
        preview = preview_openfigi_mapping(
            isin=body.isin or product.isin,
            symbol=body.symbol or product.symbol,
            exchange_code=body.exchange_code or product.exchange_code,
            mic_code=body.mic_code,
            currency=body.currency or product.currency,
            context={
                "product_id": product.id,
                "product_name": product.product_name,
                "isin": body.isin or product.isin,
                "symbol": body.symbol or product.symbol,
                "currency": body.currency or product.currency,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    candidates = list(preview.get("candidates") or [])
    if not candidates:
        raise HTTPException(status_code=409, detail=preview.get("warning") or preview.get("error") or "Kein Mapping-Kandidat gefunden")

    selected = None
    if body.preferred_figi:
        selected = next((item for item in candidates if item.get("figi") == body.preferred_figi), None)
        if selected is None:
            raise HTTPException(status_code=409, detail="Bevorzugter FIGI-Kandidat nicht gefunden")
    elif body.candidate_index >= len(candidates):
        raise HTTPException(status_code=409, detail="candidate_index ausserhalb der gefundenen Kandidaten")
    else:
        selected = candidates[body.candidate_index]

    now = _now()
    product.figi = selected.get("figi")
    product.composite_figi = selected.get("composite_figi")
    product.share_class_figi = selected.get("share_class_figi")
    product.exchange_code = selected.get("exch_code")
    product.market_sector = selected.get("market_sector")
    product.security_type = selected.get("security_type")
    product.security_type2 = selected.get("security_type2")
    product.mapping_provider = "openfigi"
    product.mapping_resolved_at = now
    product.updated_at = now
    if (not product.symbol or body.overwrite_symbol) and selected.get("ticker"):
        product.symbol = selected.get("ticker")
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="products",
        record_id=product.id,
        action="UPDATE",
        field_name="mapping_provider",
        new_value="openfigi",
    )
    db.commit()
    db.refresh(product)
    return {
        "product": product,
        "applied": selected,
        "preview_warning": preview.get("warning"),
    }


@products_router.post("/openfigi/auto-apply", response_model=ProductIdMappingBatchApplyResponse)
def auto_apply_product_id_mappings(
    body: ProductIdMappingBatchApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    products = (
        db.query(Product)
        .filter(
            Product.deleted_at.is_(None),
            Product.is_active == 1,
            Product.isin.is_not(None),
            (Product.symbol.is_(None) | (Product.symbol == "")),
        )
        .order_by(Product.updated_at.asc(), Product.product_name.asc())
        .limit(body.limit)
        .all()
    )
    items = []
    applied_count = 0
    skipped_count = 0
    failed_count = 0
    for product in products:
        try:
            preview = preview_openfigi_mapping(
                isin=product.isin,
                symbol=None,
                exchange_code=product.exchange_code,
                currency=product.currency,
                context={
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "currency": product.currency,
                },
            )
        except Exception as exc:
            failed_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            continue

        candidates = list(preview.get("candidates") or [])
        if not candidates:
            skipped_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "status": "skipped",
                    "detail": preview.get("warning") or preview.get("error") or "Kein Kandidat",
                }
            )
            continue

        selected = candidates[0]
        if body.dry_run:
            skipped_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "status": "preview",
                    "detail": "Erster Kandidat ermittelt, dry_run aktiv",
                    "applied_candidate": selected,
                }
            )
            continue

        now = _now()
        product.figi = selected.get("figi")
        product.composite_figi = selected.get("composite_figi")
        product.share_class_figi = selected.get("share_class_figi")
        product.exchange_code = selected.get("exch_code")
        product.market_sector = selected.get("market_sector")
        product.security_type = selected.get("security_type")
        product.security_type2 = selected.get("security_type2")
        product.mapping_provider = "openfigi"
        product.mapping_resolved_at = now
        if (not product.symbol or body.overwrite_symbol) and selected.get("ticker"):
            product.symbol = selected.get("ticker")
        product.updated_at = now
        applied_count += 1
        items.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "isin": product.isin,
                "status": "applied",
                "detail": "OpenFIGI-Mapping uebernommen",
                "applied_candidate": selected,
            }
        )
        log(
            db,
            user_id=current_user.id,
            user_name=current_user.full_name,
            table_name="products",
            record_id=product.id,
            action="UPDATE",
            field_name="mapping_provider",
            new_value="openfigi",
        )
    db.commit()
    return {
        "processed": len(products),
        "applied": applied_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "dry_run": body.dry_run,
        "items": items,
    }


@products_router.post("/eodhd/resolve", response_model=ProductReferencePreviewResponse)
def resolve_product_reference_data(
    body: ProductReferencePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = None
    if body.product_id:
        product = db.query(Product).filter(Product.id == body.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    try:
        return preview_eodhd_reference(
            isin=body.isin or (product.isin if product else None),
            symbol=body.symbol or (product.symbol if product else None),
            product_name=body.product_name or (product.product_name if product else None),
            exchange_code=body.exchange_code or (product.exchange_code if product else None),
            currency=body.currency or (product.currency if product else None),
            context=_reference_context(product) if product else {
                "isin": body.isin,
                "symbol": body.symbol,
                "product_name": body.product_name,
                "exchange_code": body.exchange_code,
                "currency": body.currency,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@products_router.post("/eodhd/apply", response_model=ProductReferenceApplyResponse)
def apply_product_reference_data(
    body: ProductReferenceApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    try:
        preview = preview_eodhd_reference(
            isin=body.isin or product.isin,
            symbol=body.symbol or product.symbol,
            product_name=body.product_name or product.product_name,
            exchange_code=body.exchange_code or product.exchange_code,
            currency=body.currency or product.currency,
            context=_reference_context(product),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    candidates = list(preview.get("candidates") or [])
    if not candidates:
        raise HTTPException(status_code=409, detail=preview.get("warning") or "Kein Referenzdaten-Kandidat gefunden")
    if body.candidate_index >= len(candidates):
        raise HTTPException(status_code=409, detail="candidate_index ausserhalb der gefundenen Kandidaten")
    selected = candidates[body.candidate_index]
    now = _now()
    _apply_reference_candidate(
        product=product,
        candidate=selected,
        now=now,
        overwrite_symbol=body.overwrite_symbol,
        overwrite_name=body.overwrite_name,
        overwrite_currency=body.overwrite_currency,
    )
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="products",
        record_id=product.id,
        action="UPDATE",
        field_name="reference_data_provider",
        new_value="eodhd",
    )
    db.commit()
    db.refresh(product)
    return {
        "product": product,
        "applied": selected,
        "preview_warning": preview.get("warning"),
    }


@products_router.post("/eodhd/auto-apply", response_model=ProductReferenceBatchApplyResponse)
def auto_apply_product_reference_data(
    body: ProductReferenceBatchApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    products = (
        db.query(Product)
        .filter(
            Product.deleted_at.is_(None),
            Product.is_active == 1,
            (Product.reference_data_provider.is_(None) | (Product.reference_data_provider == "")),
        )
        .order_by(Product.updated_at.asc(), Product.product_name.asc())
        .limit(body.limit)
        .all()
    )
    items = []
    applied_count = 0
    skipped_count = 0
    failed_count = 0
    for product in products:
        try:
            preview = preview_eodhd_reference(
                isin=product.isin,
                symbol=product.symbol,
                product_name=product.product_name,
                exchange_code=product.exchange_code,
                currency=product.currency,
                context=_reference_context(product),
            )
        except Exception as exc:
            failed_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "symbol": product.symbol,
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            continue

        candidates = list(preview.get("candidates") or [])
        if not candidates:
            skipped_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "symbol": product.symbol,
                    "status": "skipped",
                    "detail": preview.get("warning") or "Kein Referenzdaten-Kandidat gefunden",
                }
            )
            continue
        selected = candidates[0]
        if body.dry_run:
            skipped_count += 1
            items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "isin": product.isin,
                    "symbol": product.symbol,
                    "status": "preview",
                    "detail": "EODHD-Kandidat gefunden",
                    "applied_candidate": selected,
                }
            )
            continue
        now = _now()
        _apply_reference_candidate(
            product=product,
            candidate=selected,
            now=now,
            overwrite_symbol=body.overwrite_symbol,
            overwrite_name=body.overwrite_name,
            overwrite_currency=body.overwrite_currency,
        )
        applied_count += 1
        items.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "isin": product.isin,
                "symbol": product.symbol,
                "status": "applied",
                "detail": "EODHD-Referenzdaten uebernommen",
                "applied_candidate": selected,
            }
        )
        log(
            db,
            user_id=current_user.id,
            user_name=current_user.full_name,
            table_name="products",
            record_id=product.id,
            action="UPDATE",
            field_name="reference_data_provider",
            new_value="eodhd",
        )
    db.commit()
    return {
        "processed": len(products),
        "applied": applied_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "dry_run": body.dry_run,
        "items": items,
    }


# ── Recommendations ────────────────────────────────────────────────────────────

@recommendations_router.get("/mandates/{mandate_id}/recommendations",
                             response_model=list[RecommendationRunResponse])
def list_recommendations(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id
    ).order_by(RecommendationRun.created_at.desc()).all()


@recommendations_router.post("/mandates/{mandate_id}/recommendations",
                              response_model=RecommendationRunResponse, status_code=201)
def create_recommendation_run(
    mandate_id: str,
    body: RecommendationRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == body.policy_id
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Optimizer Policy nicht gefunden")
    now = _now()
    run = RecommendationRun(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        result_status="Draft",
        other_assets_included=1 if body.other_assets_included else 0,
        created_by=current_user.id,
        created_at=now, updated_at=now,
        **{k: v for k, v in body.model_dump().items() if k != "other_assets_included"}
    )
    db.add(run)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_runs", record_id=run.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(run)
    return run


@recommendations_router.post("/mandates/{mandate_id}/recommendations/generate",
                             response_model=RecommendationGenerateResponse)
def generate_recommendation_run_endpoint(
    mandate_id: str,
    body: RecommendationGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        result = generate_recommendation_run(
            db=db,
            mandate=mandate,
            user_id=current_user.id,
            preferences=body.preferences.model_dump() if body.preferences else None,
            target_allocation_id=body.target_allocation_id,
            run_type=body.run_type,
            depot_bank=body.depot_bank,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    refresh_system_review_triggers(db, mandate, current_user.id)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_runs", record_id=result["run"].id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(result["run"])
    return result


@recommendations_router.get("/mandates/{mandate_id}/recommendations/current/payload",
                            response_model=RecommendationGenerateResponse)
def get_current_recommendation_payload(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    runs = db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id
    ).order_by(RecommendationRun.created_at.desc()).all()
    if not runs:
        raise HTTPException(status_code=404, detail="Keine Empfehlung gefunden")
    run = next((item for item in runs if item.result_status == "Final"), None) or runs[0]
    try:
        return build_recommendation_payload_from_run(
            db=db,
            mandate=mandate,
            run=run,
            user_id=current_user.id,
            preferences=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@recommendations_router.put("/mandates/{mandate_id}/recommendations/{run_id}/finalize",
                             response_model=RecommendationRunResponse)
def finalize_recommendation(
    mandate_id: str, run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    # Supersede previous final runs
    db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id,
        RecommendationRun.result_status == "Final",
        RecommendationRun.id != run_id
    ).update({"result_status": "Superseded"})
    run.result_status = "Final"
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_runs", record_id=run_id, action="UPDATE",
        field_name="result_status", new_value="Final", mandate_id=mandate_id)
    db.commit()
    db.refresh(run)
    return run


@recommendations_router.get("/mandates/{mandate_id}/recommendations/{run_id}/positions",
                             response_model=list[RecommendationPositionResponse])
def list_positions(
    mandate_id: str, run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    return db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run_id
    ).order_by(RecommendationPosition.target_weight_bps.desc()).all()


@recommendations_router.post("/mandates/{mandate_id}/recommendations/{run_id}/positions",
                              response_model=RecommendationPositionResponse, status_code=201)
def add_position(
    mandate_id: str, run_id: str,
    body: RecommendationPositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    if run.result_status == "Final":
        raise HTTPException(status_code=400, detail="Finalisierte Runs können nicht mehr geändert werden")
    product = db.query(Product).filter(Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    now = _now()
    pos = RecommendationPosition(
        id=new_uuid(), run_id=run_id,
        created_at=now, updated_at=now,
        **body.model_dump()
    )
    db.add(pos)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_positions", record_id=pos.id, action="CREATE",
        mandate_id=mandate_id)
    db.commit()
    db.refresh(pos)
    return pos


# ── Dashboard ──────────────────────────────────────────────────────────────────

@recommendations_router.get("/mandates/{mandate_id}/recommendations/{run_id}/holdings",
                             response_model=list[RecommendationHoldingResponse])
def list_holdings(
    mandate_id: str, run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    return db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.deleted_at.is_(None)
    ).order_by(RecommendationHolding.updated_at.desc()).all()


@recommendations_router.put("/mandates/{mandate_id}/recommendations/{run_id}/positions/{position_id}/holding",
                             response_model=RecommendationHoldingResponse)
def upsert_position_holding(
    mandate_id: str, run_id: str, position_id: str,
    body: RecommendationHoldingUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    position = db.query(RecommendationPosition).filter(
        RecommendationPosition.id == position_id,
        RecommendationPosition.run_id == run_id
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail="Empfehlungsposition nicht gefunden")
    now = _now()
    payload = body.model_dump()
    payload["as_of_date"] = _normalize_holding_date(payload.get("as_of_date"))
    holding = db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.recommendation_position_id == position_id,
        RecommendationHolding.deleted_at.is_(None)
    ).order_by(RecommendationHolding.updated_at.desc()).first()
    if holding:
        for field, value in payload.items():
            setattr(holding, field, value)
        holding.updated_at = now
        action = "UPDATE"
    else:
        holding = RecommendationHolding(
            id=new_uuid(),
            run_id=run_id,
            recommendation_position_id=position_id,
            product_id=position.product_id,
            created_at=now,
            updated_at=now,
            **payload
        )
        db.add(holding)
        action = "CREATE"
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_holdings", record_id=holding.id, action=action,
        mandate_id=mandate_id, client_id=run.client_id)
    db.commit()
    db.refresh(holding)
    return holding


@recommendations_router.delete("/mandates/{mandate_id}/recommendations/{run_id}/positions/{position_id}/holding",
                                status_code=204)
def delete_position_holding(
    mandate_id: str, run_id: str, position_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    holding = db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.recommendation_position_id == position_id,
        RecommendationHolding.deleted_at.is_(None)
    ).order_by(RecommendationHolding.updated_at.desc()).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding nicht gefunden")
    holding.deleted_at = _now()
    holding.updated_at = holding.deleted_at
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_holdings", record_id=holding.id, action="DELETE",
        mandate_id=mandate_id, client_id=run.client_id)
    db.commit()


@dashboard_router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aggregated dashboard: all clients with wealth, active alerts count."""
    if has_global_client_access(current_user):
        rows = db.execute(text("SELECT * FROM v_client_wealth_summary ORDER BY client_name")).fetchall()
        trigger_stmt = text(
            "SELECT COUNT(*) FROM v_active_triggers WHERE status IN :active_statuses"
        ).bindparams(bindparam("active_statuses", expanding=True))
        trigger_count = db.execute(trigger_stmt, {"active_statuses": ACTIVE_TRIGGER_STATUS_VALUES}).scalar()
        clients = [dict(r._mapping) for r in rows]
        for c in clients:
            c["net_worth_chf"] = c["net_worth_rappen"] / 100
            c["advisory_wealth_chf"] = c["advisory_wealth_rappen"] / 100
        return {
            "clients": clients,
            "active_alerts": trigger_count,
            "total_clients": len(clients),
        }

    client_ids = get_accessible_client_ids(db, current_user)
    mandate_ids = get_accessible_mandate_ids(db, current_user)
    if not client_ids:
        return {
            "clients": [],
            "active_alerts": 0,
            "total_clients": 0,
        }
    summary_stmt = text(
        "SELECT * FROM v_client_wealth_summary WHERE client_id IN :client_ids ORDER BY client_name"
    ).bindparams(bindparam("client_ids", expanding=True))
    rows = db.execute(summary_stmt, {"client_ids": client_ids}).fetchall()
    if mandate_ids:
        trigger_stmt = text(
            "SELECT COUNT(*) FROM v_active_triggers WHERE status IN :active_statuses AND mandate_id IN :mandate_ids"
        ).bindparams(
            bindparam("active_statuses", expanding=True),
            bindparam("mandate_ids", expanding=True),
        )
        trigger_count = db.execute(
            trigger_stmt,
            {"active_statuses": ACTIVE_TRIGGER_STATUS_VALUES, "mandate_ids": mandate_ids},
        ).scalar()
    else:
        trigger_count = 0
    clients = [dict(r._mapping) for r in rows]
    for c in clients:
        c["net_worth_chf"] = c["net_worth_rappen"] / 100
        c["advisory_wealth_chf"] = c["advisory_wealth_rappen"] / 100
    return {
        "clients": clients,
        "active_alerts": trigger_count,
        "total_clients": len(clients),
    }


@dashboard_router.get("/active-triggers")
def active_triggers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if has_global_client_access(current_user):
        rows = db.execute(text("SELECT * FROM v_active_triggers")).fetchall()
        return [dict(r._mapping) for r in rows]
    mandate_ids = get_accessible_mandate_ids(db, current_user)
    if not mandate_ids:
        return []
    stmt = text(
        "SELECT * FROM v_active_triggers WHERE mandate_id IN :mandate_ids"
    ).bindparams(bindparam("mandate_ids", expanding=True))
    rows = db.execute(stmt, {"mandate_ids": mandate_ids}).fetchall()
    return [dict(r._mapping) for r in rows]
