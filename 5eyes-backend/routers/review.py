import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import bindparam, or_, text
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timezone
from config import settings
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.review import (
    ReviewTrigger, AdvisoryLog, ContractDocument,
    ConflictOfInterestDisclosure, Product, ProductSuitability,
    ProductUniverseEntry,
    RecommendationRun, RecommendationPosition, RecommendationHolding, AuditLog
)
from models.allocation import CapitalMarketAssumption, OptimizerPolicy, TargetAllocation
from models.profiling import RiskAssessment
from models.tenant import Tenant
from schemas.review import (
    ReviewTriggerCreate, ReviewTriggerResolve, ReviewTriggerResponse,
    AdvisoryLogCreate, AdvisoryLogUpdate, AdvisoryLogResponse,
    ContractDocumentCreate, ContractDocumentSign, ContractDocumentResponse,
    ConflictDisclosureCreate, ConflictDisclosureResponse,
    ProductCreate, ProductUpdate, ProductResponse,
    ProductMarketOverrideRequest, ProductMarketOverrideResponse,
    ProductIdMappingPreviewRequest, ProductIdMappingPreviewResponse,
    ProductIdMappingApplyRequest, ProductIdMappingApplyResponse,
    ProductIdMappingBatchApplyRequest, ProductIdMappingBatchApplyResponse,
    ProductReferencePreviewRequest, ProductReferencePreviewResponse,
    ProductReferenceApplyRequest, ProductReferenceApplyResponse,
    ProductReferenceBatchApplyRequest, ProductReferenceBatchApplyResponse,
    ProductUniverseEntryCreate, ProductUniverseEntryUpdate, ProductUniverseEntryResponse,
    RecommendationRunCreate, RecommendationRunResponse,
    RecommendationPositionCreate, RecommendationPositionResponse,
    RecommendationHoldingUpsert, RecommendationHoldingResponse,
    RecommendationGenerateRequest, RecommendationGenerateResponse,
)
from price_updater import summarize_price_quality
from services.auth import get_accessible_client_ids, get_accessible_mandate_ids, get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, has_global_client_access, require_advisor, require_admin, _resolve_tenant_id_for_user
from services.audit import log
from services.advisory_report_cache import invalidate_mandate as invalidate_advisory_cache
from services.data_classification import enforce_data_classification
from services.eodhd_client import preview_eodhd_reference
from services.market_data.exceptions import RateLimitError
from services.openfigi_client import preview_openfigi_mapping
from services.portfolio_engine import build_recommendation_payload_from_run, generate_recommendation_run
from services.product_market_data import resolve_market_profile
from services.review_engine import _add_months, refresh_system_review_triggers
from services.suitability_audit import audit_mandate_suitability

router = APIRouter(tags=["Review & Dokumente"])
products_router = APIRouter(prefix="/products", tags=["Produkte"])
recommendations_router = APIRouter(tags=["Empfehlungen"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger(__name__)

_HOLDING_MUTABLE_FIELDS = (
    "depot_bank",
    "custody_account_number",
    "as_of_date",
    "units_milli",
    "market_value_rappen",
    "avg_cost_price_rappen",
    "source",
    "notes",
)


def _legacy_text_variants(value: str) -> tuple[str, ...]:
    variants = {value}
    variants.add(
        value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    )
    try:
        latin1_variant = value.encode("utf-8").decode("latin1")
        variants.add(latin1_variant)
        variants.add(latin1_variant.encode("utf-8").decode("latin1"))
    except UnicodeError:
        pass
    return tuple(item for item in variants if item)


ACTIVE_TRIGGER_STATUS_VALUES = _legacy_text_variants("Ausgelöst")


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


def _get_product_or_404(product_id: str, db: Session) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.deleted_at.is_(None),
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    return product


def _validate_recommendation_for_finalization(db: Session, mandate: Mandate, run: RecommendationRun) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if run.result_status != "Draft":
        errors.append("Nur Draft-Empfehlungen koennen finalisiert werden.")
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.id == run.assessment_id,
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.deleted_at.is_(None),
    ).first() if run.assessment_id else None
    if not assessment:
        errors.append("Empfehlung hat kein gueltiges Risikoprofil.")
    elif not assessment.is_current:
        errors.append("Empfehlung basiert nicht auf dem aktuellen Risikoprofil.")
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.id == run.target_allocation_id,
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.deleted_at.is_(None),
    ).first() if run.target_allocation_id else None
    if not allocation:
        errors.append("Empfehlung hat keine gueltige Soll-Allokation.")
    elif not allocation.is_current:
        # Analog zum Risikoprofil-Gate oben: eine finalisierte Empfehlung MUSS auf der
        # aktuellen Soll-Allokation basieren. Sonst wird der Run zwar Final, ist aber
        # ueber get_current_recommendation_payload (filtert auf is_current-Allokation)
        # nicht mehr auffindbar -> verwaister Final-Zustand.
        errors.append("Empfehlung basiert nicht auf der aktuellen Soll-Allokation.")
    elif assessment and allocation.based_on_assessment_id and allocation.based_on_assessment_id != assessment.id:
        errors.append("Soll-Allokation und Risikoprofil der Empfehlung passen nicht zusammen.")
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == run.policy_id,
    ).first() if run.policy_id else None
    if not policy:
        errors.append("Empfehlung hat keine gueltige Policy-Version.")
    elif not policy.is_current:
        # 2026-07-24 (Generalaudit): dasselbe Muster wie der Risikoprofil-/
        # Soll-Allokation-Guard oben (F4, PROAKTIV-AUDIT Runde 4) -- eine
        # finalisierte Empfehlung darf nicht auf einer bereits ersetzten
        # Policy-Version basieren, sonst ist der Final-Zustand fachlich
        # veraltet ohne dass das erkennbar waere.
        errors.append("Empfehlung basiert nicht auf der aktuellen Policy-Version.")
    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == run.capital_market_assumptions_id,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first() if run.capital_market_assumptions_id else None
    if not cma:
        errors.append("Empfehlung hat keine gueltige CMA-Version.")
    elif not cma.is_current:
        errors.append("Empfehlung basiert nicht auf der aktuellen CMA-Version.")
    positions = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run.id).all()
    if not positions:
        errors.append("Empfehlung enthaelt keine Positionen.")
        return errors, warnings
    total_weight = sum(int(position.target_weight_bps or 0) for position in positions)
    if total_weight < 9900 or total_weight > 10100:
        errors.append(f"Positionsgewichte summieren auf {total_weight} bps statt ca. 10000 bps.")
    product_ids = [position.product_id for position in positions if position.product_id]
    products = {product.id: product for product in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    for position in positions:
        product = products.get(position.product_id)
        if not product or product.deleted_at is not None or int(product.is_active or 0) != 1:
            errors.append(f"Produkt {position.product_id} ist nicht aktiv oder nicht verfuegbar.")
            continue
        if product.ter_bps is None:
            warnings.append(f"TER fehlt fuer {product.product_name}.")
        profile = resolve_market_profile(product)
        if not (profile.get("lookup_symbol") or profile.get("isin")):
            warnings.append(f"Marktdaten-Mapping fehlt fuer {product.product_name}.")
    quality = summarize_price_quality(db, product_ids)
    if int(quality.get("missing_prices_count") or 0):
        warnings.append("Mindestens eine Position hat keinen aktuellen Marktpreis.")
    if int(quality.get("stale_positions_count") or 0):
        warnings.append("Mindestens ein Marktpreis ist veraltet.")
    return errors, warnings


def _active_products_query(db: Session, tenant_id: str | None = None):
    """Fondsuniversum (2026-08-05): zeigt den globalen/geteilten Katalog
    (Product.tenant_id IS NULL) plus die privaten Fonds des UEBERGEBENEN
    Tenants -- NIE die privaten Fonds anderer Tenants. tenant_id=None
    (Default) zeigt NUR den globalen Katalog, unveraendert wie vor dieser
    Aenderung (Backwards-Compat fuer Aufrufer ohne User-Kontext)."""
    q = db.query(Product).filter(Product.deleted_at.is_(None), Product.is_active == 1)
    if tenant_id:
        q = q.filter(or_(Product.tenant_id.is_(None), Product.tenant_id == tenant_id))
    else:
        q = q.filter(Product.tenant_id.is_(None))
    return q


def _get_trigger_or_404(mandate_id: str, trigger_id: str, db: Session) -> ReviewTrigger:
    trigger = db.query(ReviewTrigger).filter(
        ReviewTrigger.id == trigger_id,
        ReviewTrigger.mandate_id == mandate_id,
        ReviewTrigger.deleted_at.is_(None),
    ).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger nicht gefunden")
    return trigger


def _get_document_or_404(mandate_id: str, doc_id: str, db: Session) -> ContractDocument:
    document = db.query(ContractDocument).filter(
        ContractDocument.id == doc_id,
        ContractDocument.mandate_id == mandate_id,
        ContractDocument.deleted_at.is_(None),
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return document


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


def _openfigi_context(
    product: Product | None,
    *,
    isin: str | None,
    symbol: str | None,
    currency: str | None,
) -> dict[str, str | None]:
    return {
        "product_id": product.id if product else None,
        "product_name": product.product_name if product else None,
        "isin": isin or (product.isin if product else None),
        "symbol": symbol or (product.symbol if product else None),
        "currency": currency or (product.currency if product else None),
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


def _apply_openfigi_candidate(
    *,
    product: Product,
    candidate: dict,
    now: str,
    overwrite_symbol: bool,
) -> None:
    product.figi = candidate.get("figi")
    product.composite_figi = candidate.get("composite_figi")
    product.share_class_figi = candidate.get("share_class_figi")
    product.exchange_code = candidate.get("exch_code")
    product.market_sector = candidate.get("market_sector")
    product.security_type = candidate.get("security_type")
    product.security_type2 = candidate.get("security_type2")
    product.mapping_provider = "openfigi"
    product.mapping_resolved_at = now
    if (not product.symbol or overwrite_symbol) and candidate.get("ticker"):
        product.symbol = candidate.get("ticker")
    product.updated_at = now


def _commit_product_batch_update(
    db: Session,
    *,
    product: Product,
    current_user: User,
    field_name: str,
    new_value: str,
    apply_change: Callable[[], None],
) -> str | None:
    try:
        with db.begin_nested():
            apply_change()
            log(
                db,
                user_id=current_user.id,
                user_name=current_user.full_name,
                table_name="products",
                record_id=product.id,
                action="UPDATE",
                field_name=field_name,
                new_value=new_value,
            )
            db.flush()
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            db.refresh(product)
        except Exception:
            pass
        return f"DB-Fehler beim Speichern: {exc}"
    return None


def _preview_openfigi_or_raise(
    *,
    product: Product | None,
    isin: str | None,
    symbol: str | None,
    exchange_code: str | None,
    mic_code: str | None,
    currency: str | None,
) -> dict:
    try:
        return preview_openfigi_mapping(
            isin=isin or (product.isin if product else None),
            symbol=symbol or (product.symbol if product else None),
            exchange_code=exchange_code or (product.exchange_code if product else None),
            mic_code=mic_code,
            currency=currency or (product.currency if product else None),
            context=_openfigi_context(
                product,
                isin=isin,
                symbol=symbol,
                currency=currency,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


def _preview_eodhd_or_raise(
    *,
    product: Product | None,
    isin: str | None,
    symbol: str | None,
    product_name: str | None,
    exchange_code: str | None,
    currency: str | None,
) -> dict:
    context = _reference_context(product) if product else {
        "isin": isin,
        "symbol": symbol,
        "product_name": product_name,
        "exchange_code": exchange_code,
        "currency": currency,
    }
    try:
        return preview_eodhd_reference(
            isin=isin or (product.isin if product else None),
            symbol=symbol or (product.symbol if product else None),
            product_name=product_name or (product.product_name if product else None),
            exchange_code=exchange_code or (product.exchange_code if product else None),
            currency=currency or (product.currency if product else None),
            context=context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RateLimitError as exc:
        # Mega-Audit (2026-08-04): eodhd_client wirft jetzt typisiert
        # RateLimitError statt generischem RuntimeError bei HTTP 429 --
        # RateLimitError erbt NICHT von RuntimeError, also eigener Catch
        # (sonst unbehandelter 500 statt aussagekraeftigem 429).
        raise HTTPException(status_code=429, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


def _select_preview_candidate(
    *,
    preview: dict,
    candidate_index: int,
    preferred_figi: str | None = None,
    empty_detail: str,
) -> dict:
    candidates = list(preview.get("candidates") or [])
    if not candidates:
        raise HTTPException(status_code=409, detail=preview.get("warning") or preview.get("error") or empty_detail)
    if preferred_figi:
        selected = next((item for item in candidates if item.get("figi") == preferred_figi), None)
        if selected is None:
            raise HTTPException(status_code=409, detail="Bevorzugter FIGI-Kandidat nicht gefunden")
        return selected
    if candidate_index >= len(candidates):
        raise HTTPException(status_code=409, detail="candidate_index ausserhalb der gefundenen Kandidaten")
    return candidates[candidate_index]


def _collect_product_market_data_status(db: Session, tenant_id: str | None = None) -> dict:
    products = (
        _active_products_query(db, tenant_id=tenant_id)
        .order_by(Product.product_name.asc())
        .all()
    )
    openfigi_pending = []
    reference_pending = []
    openfigi_mapped_count = 0
    reference_synced_count = 0
    lookup_mode_override_count = 0
    symbol_count = 0
    isin_only_count = 0
    for product in products:
        has_symbol = not _is_blank(product.symbol)
        has_isin = not _is_blank(product.isin)
        if not _is_blank(product.lookup_mode_override):
            lookup_mode_override_count += 1
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
        normalized_asset_class = str(product.asset_class or "").strip().lower().replace("ä", "ae")
        normalized_product_type = str(product.product_type or "").strip().lower().replace("ä", "ae")
        is_liquidity_without_market_ids = (
            not has_symbol
            and not has_isin
            and ("liquid" in normalized_asset_class or "cash" in normalized_product_type)
        )
        if is_liquidity_without_market_ids:
            continue
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
        "lookup_mode_override_count": lookup_mode_override_count,
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
        .replace("Ã¤", "ae")
        .replace("Ã¶", "oe")
        .replace("Ã¼", "ue")
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


def _trigger_frequency_months(frequency: str | None) -> int | None:
    normalized = (
        str(frequency or "")
        .strip()
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ã¤", "ae")
        .replace("Ã¶", "oe")
        .replace("Ã¼", "ue")
    )
    if normalized == "monatlich":
        return 1
    if "quart" in normalized:
        return 3
    if "halb" in normalized:
        return 6
    if "jahr" in normalized:
        return 12
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
    current_user: User = Depends(require_advisor)
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
    trigger = _get_trigger_or_404(mandate_id, trigger_id, db)
    now = _now()
    trigger.status = "Erledigt"
    trigger.last_triggered_at = now
    trigger.triggered_notes = body.triggered_notes
    recurrence_months = None
    if trigger.trigger_type == "Zeit":
        recurrence_months = _trigger_frequency_months(trigger.frequency) or 12
    if recurrence_months:
        trigger.next_due_at = _add_months(now[:10], recurrence_months)
        trigger.status = "Aktiv"
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="review_triggers", record_id=trigger_id, action="UPDATE",
        field_name="status", new_value=trigger.status, mandate_id=mandate_id)
    db.commit()
    db.refresh(trigger)
    return trigger


# ── Advisory Log ───────────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/advisory-log", response_model=list[AdvisoryLogResponse])
def list_advisory_log(
    mandate_id: str,
    include_history: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Sprint U-FINMA-2.1: Listet die *aktuellen* (non-superseded) Einträge.

    Mit `?include_history=true` werden alle Versionen geliefert (für
    Compliance-Audit). Default: nur aktuelle Köpfe der Versions-Ketten.
    """
    from services.advisory_log_service import serialize_response

    _get_mandate_or_404(mandate_id, db, current_user)
    q = db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id == mandate_id)
    if not include_history:
        q = q.filter(AdvisoryLog.superseded_by_id.is_(None))
    rows = q.order_by(AdvisoryLog.entry_date.desc()).all()
    return [serialize_response(r) for r in rows]


@router.get(
    "/mandates/{mandate_id}/advisory-log/{log_id}",
    response_model=AdvisoryLogResponse,
)
def get_advisory_log_entry(
    mandate_id: str,
    log_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint U-FINMA-2.1: Einzelner Eintrag mit Read-Audit-Tracking."""
    from services.advisory_log_service import mark_read, serialize_response

    _get_mandate_or_404(mandate_id, db, current_user)
    entry = db.query(AdvisoryLog).filter(
        AdvisoryLog.id == log_id,
        AdvisoryLog.mandate_id == mandate_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Advisory-Log-Eintrag nicht gefunden")
    mark_read(db, entry=entry, reader=current_user)
    db.commit()
    db.refresh(entry)
    return serialize_response(entry)


@router.post("/mandates/{mandate_id}/advisory-log",
             response_model=AdvisoryLogResponse, status_code=201)
def create_advisory_log_entry(
    mandate_id: str,
    body: AdvisoryLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    """Sprint U-FINMA-2.1: FINMA-konforme Eintragserstellung mit Hash,
    Aufbewahrungs-Datum und vollem Audit-Log.
    """
    from services.advisory_log_service import create_advisory_log, serialize_response

    enforce_data_classification(body.data_classification)
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    if body.recommendation_run_id:
        _get_recommendation_run_or_404(mandate_id, body.recommendation_run_id, db, current_user)
    entry = create_advisory_log(
        db, mandate_id=mandate_id, advisor=current_user, payload=body,
    )
    db.flush()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="advisory_log",
        record_id=entry.id,
        action="CREATE",
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        new_value=entry.integrity_hash,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "advisory_log" in str(exc).lower() and "decision" in str(exc).lower():
            raise HTTPException(
                status_code=422,
                detail="Ungültiger Advisory-Entscheid für das aktuelle Schema",
            )
        raise
    db.refresh(entry)
    # U-19: Cache invalidieren — Beratungsprotokoll-Sektion zeigt diesen
    # Eintrag ab dem naechsten GET, statt 60s zu warten.
    invalidate_advisory_cache(mandate_id)
    return serialize_response(entry)


# ── Contract Documents ─────────────────────────────────────────────────────────

_STATUS_TRANSITIONS = {
    "Empfohlen": {"Beschlossen", "Abgelehnt"},
    "Beschlossen": {"Umgesetzt"},
    "Umgesetzt": {"Überarbeitung nötig"},
    "Überarbeitung nötig": {"Beschlossen", "Abgelehnt"},
    "Abgelehnt": set(),
}


@router.post(
    "/mandates/{mandate_id}/advisory-log/from-report-generation",
    response_model=AdvisoryLogResponse, status_code=201,
)
def create_advisory_log_from_report_generation(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Sprint U-FINMA-2.2: Erzeugt ein Beratungsprotokoll mit pre-filled
    Defaults — Topics aus Mandat-Kontext, Risk-Warnings aus aktiven
    Suitability-Mismatches. Berater editiert anschliessend via PUT.

    Endpoint ist explizit — Auto-Log passiert NICHT beim normalen
    Report-Abruf (sonst Audit-Spam).
    """
    from services.advisory_log_service import (
        build_auto_log_payload,
        create_advisory_log,
        serialize_response,
    )

    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    payload_dict = build_auto_log_payload(
        db, mandate=mandate, advisor=current_user,
        entry_datetime=_now(),
    )
    payload = AdvisoryLogCreate(**payload_dict)
    entry = create_advisory_log(
        db, mandate_id=mandate_id, advisor=current_user, payload=payload,
    )
    db.flush()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="advisory_log",
        record_id=entry.id,
        action="CREATE",
        field_name="auto_generated",
        new_value=entry.integrity_hash,
        mandate_id=mandate_id,
        client_id=mandate.client_id,
    )
    db.commit()
    db.refresh(entry)
    invalidate_advisory_cache(mandate_id)
    return serialize_response(entry)


@router.put("/mandates/{mandate_id}/advisory-log/{log_id}", response_model=AdvisoryLogResponse)
def update_advisory_log_entry(
    mandate_id: str,
    log_id: str,
    body: AdvisoryLogUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    """Sprint U-FINMA-2.1: Update erzeugt eine *neue Version*, der alte
    Eintrag wird markiert als superseded (FINMA-Pflicht: keine destructive
    Updates am Beratungsprotokoll).
    """
    from services.advisory_log_service import (
        serialize_response, supersede_advisory_log,
    )

    _get_mandate_or_404(mandate_id, db, current_user)
    entry = db.query(AdvisoryLog).filter(
        AdvisoryLog.id == log_id,
        AdvisoryLog.mandate_id == mandate_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Advisory-Log-Eintrag nicht gefunden")
    if entry.superseded_by_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Dieser Eintrag wurde bereits durch eine neuere Version ersetzt. "
                f"Aktuelle Version: {entry.superseded_by_id}"
            ),
        )

    if body.status is not None:
        current_status = entry.status or "Empfohlen"
        allowed = _STATUS_TRANSITIONS.get(current_status, set())
        if body.status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Übergang '{current_status}'→'{body.status}' nicht erlaubt. "
                    f"Erlaubt: {sorted(allowed) or ['keine weiteren']}"
                ),
            )
        if body.status in {"Abgelehnt", "Überarbeitung nötig"} and not str(body.description or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"Status '{body.status}' erfordert einen Kommentar in description.",
            )
    if body.recommendation_run_id:
        _get_recommendation_run_or_404(
            mandate_id, body.recommendation_run_id, db, current_user,
        )

    new_entry = supersede_advisory_log(
        db, previous=entry, advisor=current_user, update=body,
    )
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="advisory_log",
        record_id=new_entry.id,
        action="UPDATE",
        field_name="version",
        old_value=str(entry.version),
        new_value=str(new_entry.version),
        mandate_id=mandate_id,
    )
    db.commit()
    db.refresh(new_entry)
    invalidate_advisory_cache(mandate_id)
    return serialize_response(new_entry)


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
    fields = body.model_dump()
    # 2026-07-25 (Generalaudit): data_classification hat kein DB-Spalten-
    # Aequivalent auf ContractDocument (nur Enforcement) -- vor dem Spread
    # in den Konstruktor entfernen, sonst TypeError: unexpected keyword arg.
    enforce_data_classification(fields.pop("data_classification", None))
    now = _now()
    doc = ContractDocument(
        id=new_uuid(), mandate_id=mandate_id,
        status="Entwurf", version=1,
        signed_by_advisor=0, signed_by_client=0,
        created_by=current_user.id,
        created_at=now, updated_at=now,
        **fields
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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    # 2026-08-05 (User-Direktive, E-Signing): schreibt jetzt zusaetzlich zu
    # den bestehenden Checkbox-Flags das tatsaechliche Signatur-Artefakt
    # (Bild + Name + Zeitstempel + IP) fuer genau den Unterzeichner, der in
    # diesem Aufruf gesetzt ist -- siehe ContractDocumentSign-Docstring.
    from routers.auth import _extract_client_ip
    _get_mandate_or_404(mandate_id, db, current_user)
    doc = _get_document_or_404(mandate_id, doc_id, db)
    now = _now()
    signer_ip = _extract_client_ip(request)
    signer_name = body.signer_name.strip()
    if body.signed_by_advisor:
        doc.signed_by_advisor = 1
        doc.signature_advisor_image = body.signature_image
        doc.signature_advisor_signer_name = signer_name
        doc.signature_advisor_signed_at = now
        doc.signature_advisor_ip = signer_ip
    if body.signed_by_client:
        doc.signed_by_client = 1
        doc.signature_client_image = body.signature_image
        doc.signature_client_signer_name = signer_name
        doc.signature_client_signed_at = now
        doc.signature_client_ip = signer_ip
    if not doc.signed_at:
        doc.signed_at = now
    doc.status = (
        "Unterzeichnet"
        if doc.signed_by_advisor and doc.signed_by_client
        else "Teilweise unterzeichnet"
    )
    doc.updated_at = now
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="contract_documents", record_id=doc_id, action="UPDATE",
        field_name="status", new_value=doc.status, mandate_id=mandate_id)
    db.commit()
    db.refresh(doc)
    return doc


# ── Conflicts of Interest ──────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/conflict-disclosures",
            response_model=list[ConflictDisclosureResponse])
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
    fields = body.model_dump()
    # 2026-07-25 (Generalaudit): siehe create_document -- kein DB-Spalten-
    # Aequivalent auf ConflictOfInterestDisclosure, nur Enforcement.
    enforce_data_classification(fields.pop("data_classification", None))
    # 2026-07-27 (Retrozessions-Feature): reimbursed_to_client=None bedeutet
    # "nicht angegeben" -- aus der firmenweiten Tenant-Vorbelegung auffuellen
    # (Spalte ist NOT NULL, kann nicht als None persistiert werden).
    if fields.get("reimbursed_to_client") is None:
        tenant_id = getattr(mandate, "tenant_id", None)
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first() if tenant_id else None
        fields["reimbursed_to_client"] = bool(getattr(tenant, "default_retrocession_reimbursement", 0)) if tenant else False
    now = _now()
    conflict = ConflictOfInterestDisclosure(
        id=new_uuid(), mandate_id=mandate_id,
        disclosed_by=current_user.id,
        disclosed_to_client=0, client_acknowledged=0,
        created_at=now, updated_at=now,
        **fields
    )
    db.add(conflict)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="conflict_of_interest_disclosures", record_id=conflict.id,
        action="CREATE", mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(conflict)
    return conflict


# ── Products ───────────────────────────────────────────────────────────────────

_SFDR_VALID_CLASSES = frozenset({"6", "8", "9"})


@products_router.get("", response_model=list[ProductResponse])
def list_products(
    asset_class: str = None,
    sfdr_class: str | None = Query(
        default=None,
        description=(
            "SFDR-Klassifizierung (Sustainable Finance Disclosure Regulation). "
            "Erlaubte Werte: '6' (Standard, keine ESG-Werbung), "
            "'8' (ESG-Werbung mit nachhaltigen Merkmalen), "
            "'9' (Nachhaltigkeits-Ziel als Anlage-Ziel). "
            "Sprint U-95 (2026-06-05)."
        ),
    ),
    esg_rating: str | None = Query(
        default=None,
        description=(
            "ESG-Rating-Filter (case-insensitive exact match). "
            "Sprint U-95 (2026-06-05)."
        ),
    ),
    q: str | None = Query(
        default=None,
        description=(
            "Freitext-Suche ueber Produktname/Anbieter/ISIN/Symbol "
            "(case-insensitive, Substring). Fondsuniversum (2026-08-05)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Sprint U-95 (2026-06-05): ESG/SFDR-Filter ergaenzt.
    Fondsuniversum (2026-08-05): Freitext-Suche (q) + Tenant-Scoping ergaenzt
    -- zeigt den globalen Katalog PLUS die eigenen, privat erfassten Fonds
    des aufrufenden Users' Tenants (nie die eines anderen Tenants).

    Berater kann nach SFDR-Klassifizierung (Art. 6/8/9) und ESG-Rating
    filtern um Anlageprodukte zu finden die zu den ESG-Preferences des
    Kunden passen. Filter sind additiv (AND-Verknuepfung).
    """
    query = _active_products_query(db, tenant_id=_resolve_tenant_id_for_user(current_user))
    if asset_class:
        query = query.filter(Product.asset_class == asset_class)
    if sfdr_class is not None:
        normalized = str(sfdr_class).strip()
        if normalized not in _SFDR_VALID_CLASSES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"sfdr_class muss einer von {sorted(_SFDR_VALID_CLASSES)} sein, "
                    f"erhalten: {sfdr_class!r}"
                ),
            )
        query = query.filter(Product.sfdr_class == normalized)
    if esg_rating is not None:
        normalized_rating = str(esg_rating).strip()
        if not normalized_rating:
            raise HTTPException(
                status_code=422,
                detail="esg_rating darf nicht leer sein.",
            )
        # Case-insensitive Match (ESG-Ratings haben Schreibweise-Varianten wie 'AAA'/'aaa')
        query = query.filter(Product.esg_rating.ilike(normalized_rating))
    if q is not None:
        needle = str(q).strip()
        if needle:
            pattern = f"%{needle}%"
            query = query.filter(or_(
                Product.product_name.ilike(pattern),
                Product.provider.ilike(pattern),
                Product.isin.ilike(pattern),
                Product.symbol.ilike(pattern),
            ))
    return query.order_by(Product.asset_class, Product.product_name).all()


@products_router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    body: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Fondsuniversum (2026-08-05, User-Direktive): manuell erfasste Fonds
    (kotiert MIT isin/symbol, oder nicht-kotiert OHNE -- beide Felder sind
    bereits optional auf Product) werden serverseitig dem Tenant des
    erfassenden Admins zugeordnet -- NIE aus dem Client-Payload uebernommen
    (ProductCreate hat gar kein tenant_id-Feld), sonst waere ein Tenant-
    Spoofing moeglich (Firma A koennte sich als Firma B ausgeben). So kann
    jedes Assetmanagement seine eigenen Fonds erfassen, ohne dass sie fuer
    andere Tenants sichtbar werden (siehe _active_products_query)."""
    now = _now()
    product = Product(
        id=new_uuid(), is_active=1,
        tenant_id=_resolve_tenant_id_for_user(current_user),
        created_at=now, updated_at=now,
        **body.model_dump()
    )
    db.add(product)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="products", record_id=product.id, action="CREATE")
    db.commit()
    db.refresh(product)
    return product


@products_router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    body: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-P10: Admin editiert Produkt-Metadaten + Diversifikations-Tiefe.

    Alle Felder optional; nur gesetzte werden ueberschrieben. JSON-Strings
    (country/sector/currency_exposure_json) werden NICHT validiert hier —
    der Depot-Check-Engine fault-tolerant via product_exposures._parse_or_proxy.
    """
    product = db.query(Product).filter(
        Product.id == product_id, Product.deleted_at.is_(None),
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} nicht gefunden")
    payload = body.model_dump(exclude_none=True)
    if not payload:
        return product
    for field, value in payload.items():
        setattr(product, field, value)
    product.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="products", record_id=product_id, action="UPDATE",
        new_value=", ".join(f"{k}" for k in payload.keys()))
    db.commit()
    db.refresh(product)
    return product


@products_router.put("/{product_id}/market-override", response_model=ProductMarketOverrideResponse)
def set_product_market_override(
    product_id: str,
    body: ProductMarketOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = _get_product_or_404(product_id, db)
    product.lookup_mode_override = body.lookup_mode_override or None
    product.lookup_symbol_override = body.lookup_symbol_override.strip() if body.lookup_symbol_override else None
    product.updated_at = _now()
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="products",
        record_id=product.id,
        action="UPDATE",
        field_name="market_override",
        new_value=(product.lookup_mode_override or "") + "|" + (product.lookup_symbol_override or ""),
    )
    db.commit()
    db.refresh(product)
    return ProductMarketOverrideResponse(
        id=product.id,
        product_name=product.product_name,
        lookup_mode_override=product.lookup_mode_override,
        lookup_symbol_override=product.lookup_symbol_override,
        resolved_market_profile=resolve_market_profile(product),
    )


@products_router.get("/market-data/status")
def get_product_market_data_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return _collect_product_market_data_status(db, tenant_id=_resolve_tenant_id_for_user(current_user))


@products_router.post("/openfigi/resolve", response_model=ProductIdMappingPreviewResponse)
def resolve_product_id_mapping(
    body: ProductIdMappingPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = _get_product_or_404(body.product_id, db) if body.product_id else None
    return _preview_openfigi_or_raise(
        product=product,
        isin=body.isin,
        symbol=body.symbol,
        exchange_code=body.exchange_code,
        mic_code=body.mic_code,
        currency=body.currency,
    )


@products_router.post("/openfigi/apply", response_model=ProductIdMappingApplyResponse)
def apply_product_id_mapping(
    body: ProductIdMappingApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = _get_product_or_404(body.product_id, db)
    preview = _preview_openfigi_or_raise(
        product=product,
        isin=body.isin,
        symbol=body.symbol,
        exchange_code=body.exchange_code,
        mic_code=body.mic_code,
        currency=body.currency,
    )
    selected = _select_preview_candidate(
        preview=preview,
        candidate_index=body.candidate_index,
        preferred_figi=body.preferred_figi,
        empty_detail="Kein Mapping-Kandidat gefunden",
    )
    now = _now()
    _apply_openfigi_candidate(
        product=product,
        candidate=selected,
        now=now,
        overwrite_symbol=body.overwrite_symbol,
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
        _active_products_query(db, tenant_id=_resolve_tenant_id_for_user(current_user))
        .filter(
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
        product_name = product.product_name
        product_isin = product.isin
        try:
            preview = _preview_openfigi_or_raise(
                product=product,
                isin=product.isin,
                symbol=None,
                exchange_code=product.exchange_code,
                mic_code=None,
                currency=product.currency,
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
        item = {
            "product_id": product.id,
            "product_name": product_name,
            "isin": product_isin,
            "status": "applied",
            "detail": "OpenFIGI-Mapping uebernommen",
            "applied_candidate": selected,
        }
        error_detail = _commit_product_batch_update(
            db,
            product=product,
            current_user=current_user,
            field_name="mapping_provider",
            new_value="openfigi",
            apply_change=lambda: _apply_openfigi_candidate(
                product=product,
                candidate=selected,
                now=now,
                overwrite_symbol=body.overwrite_symbol,
            ),
        )
        if error_detail:
            failed_count += 1
            item["status"] = "failed"
            item["detail"] = error_detail
        else:
            applied_count += 1
        items.append(item)
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
    product = _get_product_or_404(body.product_id, db) if body.product_id else None
    return _preview_eodhd_or_raise(
        product=product,
        isin=body.isin,
        symbol=body.symbol,
        product_name=body.product_name,
        exchange_code=body.exchange_code,
        currency=body.currency,
    )


@products_router.post("/eodhd/apply", response_model=ProductReferenceApplyResponse)
def apply_product_reference_data(
    body: ProductReferenceApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = _get_product_or_404(body.product_id, db)
    preview = _preview_eodhd_or_raise(
        product=product,
        isin=body.isin,
        symbol=body.symbol,
        product_name=body.product_name,
        exchange_code=body.exchange_code,
        currency=body.currency,
    )
    selected = _select_preview_candidate(
        preview=preview,
        candidate_index=body.candidate_index,
        empty_detail="Kein Referenzdaten-Kandidat gefunden",
    )
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
        _active_products_query(db, tenant_id=_resolve_tenant_id_for_user(current_user))
        .filter(
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
        product_name = product.product_name
        product_isin = product.isin
        product_symbol = product.symbol
        try:
            preview = _preview_eodhd_or_raise(
                product=product,
                isin=product.isin,
                symbol=product.symbol,
                product_name=product.product_name,
                exchange_code=product.exchange_code,
                currency=product.currency,
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
        item = {
            "product_id": product.id,
            "product_name": product_name,
            "isin": product_isin,
            "symbol": product_symbol,
            "status": "applied",
            "detail": "EODHD-Referenzdaten uebernommen",
            "applied_candidate": selected,
        }
        error_detail = _commit_product_batch_update(
            db,
            product=product,
            current_user=current_user,
            field_name="reference_data_provider",
            new_value="eodhd",
            apply_change=lambda: _apply_reference_candidate(
                product=product,
                candidate=selected,
                now=now,
                overwrite_symbol=body.overwrite_symbol,
                overwrite_name=body.overwrite_name,
                overwrite_currency=body.overwrite_currency,
            ),
        )
        if error_detail:
            failed_count += 1
            item["status"] = "failed"
            item["detail"] = error_detail
        else:
            applied_count += 1
        items.append(item)
    return {
        "processed": len(products),
        "applied": applied_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "dry_run": body.dry_run,
        "items": items,
    }


# ── Fonds-Universum (Laender-Skalierung, Fonds-Kuratierung) ────────────────────
# 2026-07-27: Kuratierte Positivliste je Tenant+Jurisdiktion. Ohne Eintraege
# fuer ein (tenant_id, jurisdiction)-Paar bleibt der volle Produktkatalog
# unveraendert nutzbar (Backwards-Compat) -- siehe models/review.py Docstring.

product_universe_router = APIRouter(prefix="/product-universe", tags=["Fonds-Universum"])


def _effective_tenant_id(user: User) -> str:
    """Sprint T2 (2026-06-08) etabliertes Muster (siehe services/auth.py
    ::_resolve_tenant_id_for_user): user.tenant_id ist in Stage 9 nullable
    (Backwards-Compat, Single-Tenant-Boot-Backfill setzt es i.d.R. auf
    DEFAULT_TENANT_ID='main'). NULL als Fehler zu behandeln wuerde admins
    VOR dem naechsten Boot-Zyklus komplett aussperren -- stattdessen wie
    ueberall sonst im Code auf 'main' fallen lassen."""
    from models.tenant import DEFAULT_TENANT_ID
    raw = getattr(user, "tenant_id", None)
    return raw.strip() if raw and isinstance(raw, str) and raw.strip() else DEFAULT_TENANT_ID


def _get_product_universe_entry_or_404(entry_id: str, tenant_id: str | None, db: Session) -> ProductUniverseEntry:
    entry = db.query(ProductUniverseEntry).filter(
        ProductUniverseEntry.id == entry_id,
        ProductUniverseEntry.deleted_at.is_(None),
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"ProductUniverseEntry {entry_id} nicht gefunden")
    if entry.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"ProductUniverseEntry {entry_id} nicht gefunden")
    return entry


@product_universe_router.get("", response_model=list[ProductUniverseEntryResponse])
def list_product_universe_entries(
    jurisdiction: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tenant_id = _effective_tenant_id(current_user)
    q = db.query(ProductUniverseEntry).filter(
        ProductUniverseEntry.tenant_id == tenant_id,
        ProductUniverseEntry.deleted_at.is_(None),
    )
    if jurisdiction is not None:
        q = q.filter(ProductUniverseEntry.jurisdiction == jurisdiction)
    return q.order_by(ProductUniverseEntry.jurisdiction, ProductUniverseEntry.created_at).all()


@product_universe_router.post("", response_model=ProductUniverseEntryResponse, status_code=201)
def create_product_universe_entry(
    body: ProductUniverseEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tenant_id = _effective_tenant_id(current_user)
    product = db.query(Product).filter(
        Product.id == body.product_id, Product.deleted_at.is_(None),
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {body.product_id} nicht gefunden")
    existing = db.query(ProductUniverseEntry).filter(
        ProductUniverseEntry.tenant_id == tenant_id,
        ProductUniverseEntry.jurisdiction == body.jurisdiction,
        ProductUniverseEntry.product_id == body.product_id,
        ProductUniverseEntry.deleted_at.is_(None),
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Eintrag fuer Produkt {body.product_id} in Jurisdiktion {body.jurisdiction!r} existiert bereits.",
        )
    now = _now()
    entry = ProductUniverseEntry(
        id=new_uuid(),
        tenant_id=tenant_id,
        jurisdiction=body.jurisdiction,
        product_id=body.product_id,
        override_ter_bps=body.override_ter_bps,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(entry)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="product_universe_entries", record_id=entry.id, action="CREATE")
    db.commit()
    db.refresh(entry)
    return entry


@product_universe_router.put("/{entry_id}", response_model=ProductUniverseEntryResponse)
def update_product_universe_entry(
    entry_id: str,
    body: ProductUniverseEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    entry = _get_product_universe_entry_or_404(entry_id, _effective_tenant_id(current_user), db)
    entry.override_ter_bps = body.override_ter_bps
    entry.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="product_universe_entries", record_id=entry.id, action="UPDATE",
        field_name="override_ter_bps", new_value=str(body.override_ter_bps))
    db.commit()
    db.refresh(entry)
    return entry


@product_universe_router.delete("/{entry_id}", status_code=204)
def delete_product_universe_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    entry = _get_product_universe_entry_or_404(entry_id, _effective_tenant_id(current_user), db)
    entry.deleted_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="product_universe_entries", record_id=entry.id, action="DELETE")
    db.commit()
    return None


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
    # C1: Hard-Gate. Auch der direkte Draft-Create muss auf einem aktuellen,
    # strategie-fertigen Risikoprofil + aktueller Policy + aktueller CMA basieren
    # und darf keine fremden / stale TargetAllocation referenzieren.
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise HTTPException(status_code=409, detail="Bitte zuerst ein aktuelles Risikoprofil speichern.")
    if assessment.final_score_x10 is None and assessment.override_score_x10 is None:
        raise HTTPException(status_code=409, detail="Risikoprofil unvollstaendig. Bitte Fragebogen vollstaendig ausfuellen.")
    # Mega-Audit (2026-08-04): die obige Pruefung deckt nur VOLLSTAENDIGKEIT
    # ab, nicht die 365-Tage-Freshness aus audit_mandate_suitability -- ein
    # Mandat mit vollstaendigem, aber veraltetem Risikoprofil erzeugte hier
    # bisher klaglos eine Empfehlung, unabhaengig vom Suitability-Gate-Flag
    # in routers/allocation.py::generate_target_allocation_endpoint.
    # Identisches Opt-in-Gate (Welle 2.1), hier ergaenzt.
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
    if body.assessment_id and body.assessment_id != assessment.id:
        raise HTTPException(status_code=422, detail=(
            "assessment_id muss auf das aktuelle Risikoprofil zeigen "
            f"(erwartet {assessment.id})."
        ))
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == body.policy_id,
        OptimizerPolicy.is_current == 1,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Optimizer Policy nicht gefunden oder nicht aktuell")
    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()
    if not cma:
        raise HTTPException(status_code=409, detail="Keine aktuellen Kapitalmarktannahmen.")
    if body.capital_market_assumptions_id and body.capital_market_assumptions_id != cma.id:
        raise HTTPException(status_code=422, detail=(
            "capital_market_assumptions_id muss auf die aktuellen CMA zeigen "
            f"(erwartet {cma.id})."
        ))
    if body.target_allocation_id:
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.id == body.target_allocation_id,
            TargetAllocation.mandate_id == mandate_id,
            TargetAllocation.deleted_at.is_(None),
        ).first()
        if not ta:
            raise HTTPException(status_code=409, detail=(
                "target_allocation_id gehoert nicht zu diesem Mandat oder ist gelöscht."
            ))
    payload = body.model_dump()
    payload.pop("other_assets_included", None)
    if not payload.get("assessment_id"):
        payload["assessment_id"] = assessment.id
    if not payload.get("capital_market_assumptions_id"):
        payload["capital_market_assumptions_id"] = cma.id
    now = _now()
    run = RecommendationRun(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        result_status="Draft",
        other_assets_included=1 if body.other_assets_included else 0,
        created_by=current_user.id,
        created_at=now, updated_at=now,
        **payload,
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
    # Mega-Audit (2026-08-04): dieser Endpoint hatte bisher UEBERHAUPT
    # keinen Suitability-Bezug -- weder Vollstaendigkeit noch Freshness --
    # und war damit der breiteste der drei gefundenen Umgehungspfade des
    # FIDLEG-Suitability-Gates (Welle 2.1, routers/allocation.py). Identisches
    # Opt-in-Gate hier ergaenzt.
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
        logger.warning("generate_recommendation_run failed for mandate %s: %s", mandate_id, exc)
        raise HTTPException(status_code=409, detail=str(exc))
    refresh_system_review_triggers(
        db,
        mandate,
        current_user.id,
        allocation_payload=result.get("allocation_payload"),
    )
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
    current_allocation = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc()).first()
    if not current_allocation:
        raise HTTPException(status_code=409, detail="Keine aktuelle Soll-Allokation gefunden.")
    runs = db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id
    ).order_by(RecommendationRun.created_at.desc()).all()
    if not runs:
        raise HTTPException(status_code=404, detail="Keine Empfehlung gefunden")
    runs_for_current_allocation = [
        item for item in runs
        if str(item.target_allocation_id or "") == str(current_allocation.id or "")
        and item.result_status != "Superseded"
    ]
    if not runs_for_current_allocation:
        raise HTTPException(
            status_code=409,
            detail=(
                "Die gespeicherte Portfolio-Empfehlung basiert nicht auf der aktuellen "
                "Soll-Allokation. Bitte Empfehlung neu berechnen."
            ),
        )
    run = (
        next((item for item in runs_for_current_allocation if item.result_status == "Final"), None)
        or next((item for item in runs_for_current_allocation if item.result_status == "Draft"), None)
        or runs_for_current_allocation[0]
    )
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


@recommendations_router.get("/mandates/{mandate_id}/recommendations/{run_id}/payload",
                            response_model=RecommendationGenerateResponse)
def get_recommendation_payload_by_id(
    mandate_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    try:
        return build_recommendation_payload_from_run(
            db=db,
            mandate=mandate,
            run=run,
            user_id=current_user.id,
            preferences=None,
        )
    except ValueError as exc:
        logger.warning("build_recommendation_payload_from_run failed for mandate %s: %s", mandate_id, exc)
        raise HTTPException(status_code=409, detail=str(exc))


@recommendations_router.put("/mandates/{mandate_id}/recommendations/{run_id}/finalize",
                             response_model=RecommendationRunResponse)
def finalize_recommendation(
    mandate_id: str, run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # 2026-07-26 (Generalaudit-Nachtrag): sperrt die Mandats-Zeile fuer die
    # Dauer der Transaktion. Der Bulk-UPDATE unten (alle anderen "Final"-Runs
    # -> "Superseded") schuetzt NUR, wenn bereits ein Final-Run existiert --
    # bei der ERSTEN Finalisierung eines Mandats (noch kein Final-Run) matcht
    # das Bulk-UPDATE 0 Zeilen, und zwei nahezu gleichzeitige Finalize-Calls
    # fuer zwei verschiedene Runs koennten dann BEIDE "Final" werden (zwei
    # gleichzeitig gueltige, unterschiedliche Empfehlungen fuer denselben
    # Kunden). Das Sperren der Mandate-Zeile serialisiert JEDEN Finalize-Call
    # fuer dasselbe Mandat, unabhaengig vom Vorzustand.
    db.query(Mandate).filter(Mandate.id == mandate_id).with_for_update().first()
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    errors, warnings = _validate_recommendation_for_finalization(db, mandate, run)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id,
        RecommendationRun.result_status == "Final",
        RecommendationRun.id != run_id
    ).update({"result_status": "Superseded"})
    run.result_status = "Final"
    run.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="recommendation_runs", record_id=run_id, action="UPDATE",
        field_name="result_status",
        new_value=("Final; Warnungen: " + " | ".join(warnings)) if warnings else "Final",
        mandate_id=mandate_id)
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
    product = _get_product_or_404(body.product_id, db)
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
    payload = body.model_dump(exclude_unset=True)
    if "as_of_date" in payload:
        payload["as_of_date"] = _normalize_holding_date(payload.get("as_of_date"))
    holding = db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.recommendation_position_id == position_id,
        RecommendationHolding.deleted_at.is_(None)
    ).order_by(RecommendationHolding.updated_at.desc()).first()
    if holding:
        for field in _HOLDING_MUTABLE_FIELDS:
            if field in payload:
                setattr(holding, field, payload[field])
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
    """Aggregated dashboard: all clients with wealth, active alerts count.

    SECURITY (Mandanten-Trennung): KEIN ungescopter Admin-Zweig mehr. Auch
    globale Admins laufen ueber get_accessible_client_ids/-mandate_ids — diese
    ueberspringen den advisor_id-Filter, wenden aber IMMER den Tenant-Filter an.
    Ein Firma-A-Admin sieht so alle Clients SEINES Tenants, aber nie fremde.
    (Legacy-Admin ohne tenant_id: Tier-1-Single-Tenant, sieht weiter alles.)
    """
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
        c["net_worth_chf"] = (c.get("net_worth_rappen") or 0) / 100
        c["advisory_wealth_chf"] = (c.get("advisory_wealth_rappen") or 0) / 100
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
    # SECURITY (Mandanten-Trennung): kein ungescopter Admin-Zweig — alle laufen
    # ueber get_accessible_mandate_ids (tenant-gefiltert, advisor-Filter fuer
    # Admins uebersprungen).
    mandate_ids = get_accessible_mandate_ids(db, current_user)
    if not mandate_ids:
        return []
    stmt = text(
        "SELECT * FROM v_active_triggers WHERE mandate_id IN :mandate_ids"
    ).bindparams(bindparam("mandate_ids", expanding=True))
    rows = db.execute(stmt, {"mandate_ids": mandate_ids}).fetchall()
    return [dict(r._mapping) for r in rows]
