"""PDF-Report-Endpoints — Anlagestrategie, Risikoprofil als PDF-Download.

Spec: docs/planning/2026-05-17-sprint-5-pdf-engine.md §4 Phase 2
Sprint 11 Phase 5: Logging + Fallback-Sektionen + Portfolio-PDF
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database import get_db
from models.clients import Client

logger = logging.getLogger(__name__)
from models.mandates import Mandate
from models.users import User
from services.auth import get_current_user, get_mandate_for_user_or_404
from services.pdf import ReportLabRenderer
from services.pdf.base import (
    AnlagestrategieData,
    PDFContext,
    RisikoprofilData,
)

router = APIRouter(tags=["PDF Reports"])


def _build_pdf_context(mandate: Mandate, current_user: User, db: Session) -> PDFContext:
    """Sammelt PDFContext-Daten aus Mandant + Client + User.

    Mandate-Anzeige: <Client.name> [<mandate_number>] — falls Client
    nicht ladbar (Test-Setup) Fallback auf mandate_number.
    """
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    client_name = getattr(client, "name", None) if client else None
    mandate_number = str(getattr(mandate, "mandate_number", "") or "")
    if client_name:
        mandate_name = f"{client_name} [{mandate_number}]" if mandate_number else client_name
    else:
        mandate_name = mandate_number or f"Mandat {mandate.id}"

    advisor_name = getattr(current_user, "email", None) or "Berater"
    advisor_org = (
        getattr(current_user, "organization", None)
        or getattr(current_user, "org_name", None)
        or None
    )
    base_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()
    return PDFContext(
        mandate_name=mandate_name,
        advisor_name=advisor_name,
        advisor_org=advisor_org,
        report_date=date.today(),
        audit_hash=_audit_hash_for_mandate(mandate),
        locale="de-CH",
        base_currency=base_currency,
    )


def _audit_hash_for_mandate(mandate: Mandate) -> str:
    """SHA-256 ueber stabile Mandate-Felder fuer Reporting-Audit-Trail.

    Felder muessen real im Mandate-Model existieren (siehe models/mandates.py).
    """
    seed = json.dumps({
        "mandate_id": str(mandate.id or ""),
        "mandate_number": str(getattr(mandate, "mandate_number", "") or ""),
        "mandate_type": str(getattr(mandate, "mandate_type", "") or ""),
        "status": str(getattr(mandate, "status", "") or ""),
        "investment_universe": str(getattr(mandate, "investment_universe", "") or ""),
        "updated_at": str(getattr(mandate, "updated_at", "") or ""),
    }, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _build_anlagestrategie_data(mandate: Mandate, db: Session) -> AnlagestrategieData:
    """Extrahiert AnlagestrategieData aus DB-Models — Sprint 11 erweitert.

    Defensive: fehlt etwas → Defaults, kein Crash. Reichlich getattr-Defaults.
    """
    target_alloc_bps: dict[str, int] = {}
    bucket_bands: dict[str, tuple] = {}
    bucket_amounts: dict[str, int] = {}
    cma_return = 0
    cma_vol = 0
    advisory_wealth = None
    ta_obj = None

    # ---- TargetAllocation ----
    try:
        from models.allocation import TargetAllocation
        ta_obj = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate.id)
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )
        if ta_obj is not None:
            for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
                target_alloc_bps[bucket] = int(getattr(ta_obj, f"{bucket}_bps", 0) or 0)
                # Bands
                min_attr = f"{bucket}_min_bps"
                max_attr = f"{bucket}_max_bps"
                mn = getattr(ta_obj, min_attr, None)
                mx = getattr(ta_obj, max_attr, None)
                if mn is not None and mx is not None:
                    bucket_bands[bucket] = (int(mn), int(mx))
            advisory_wealth = int(getattr(ta_obj, "advisory_wealth_rappen", 0) or 0) or None
            # Bucket-Amounts ableiten aus advisory_wealth * weight
            if advisory_wealth:
                for bucket, bps in target_alloc_bps.items():
                    bucket_amounts[bucket] = int(advisory_wealth * bps / 10000)
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- CMA-Werte (gewichtet) ----
    try:
        from models.allocation import CapitalMarketAssumption
        cma = (
            db.query(CapitalMarketAssumption)
            .order_by(CapitalMarketAssumption.valid_from.desc())
            .first()
        )
        if cma is not None:
            weights_pct = {k: v / 10000.0 for k, v in target_alloc_bps.items()}
            cma_return = int(
                weights_pct.get("equities", 0) * (getattr(cma, "equity_ch_return_bps", 0) or 0)
                + weights_pct.get("bonds", 0) * (getattr(cma, "bonds_chf_ig_return_bps", 0) or 0)
                + weights_pct.get("real_estate", 0) * (getattr(cma, "real_estate_ch_return_bps", 0) or 0)
                + weights_pct.get("liquidity", 0) * (getattr(cma, "liquidity_return_bps", 0) or 0)
            )
            cma_vol = int(
                weights_pct.get("equities", 0) * (getattr(cma, "equity_ch_vol_bps", 0) or 0)
                + weights_pct.get("bonds", 0) * (getattr(cma, "bonds_chf_ig_vol_bps", 0) or 0)
                + weights_pct.get("real_estate", 0) * (getattr(cma, "real_estate_ch_vol_bps", 0) or 0)
                + weights_pct.get("liquidity", 0) * (getattr(cma, "liquidity_vol_bps", 0) or 0)
            )
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Risk-Assessment ----
    risk_score_x10 = None
    risk_label = None
    investment_horizon = None
    knowledge_services: dict = {}
    knowledge_instruments: dict = {}
    try:
        from models.profiling import RiskAssessment
        ra = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == mandate.id, RiskAssessment.is_current == 1)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        if ra is not None:
            score_raw = getattr(ra, "final_score_x10", None) or getattr(ra, "override_score_x10", None)
            risk_score_x10 = int(score_raw) if score_raw is not None else None
            risk_label = getattr(ra, "final_profile", None) or getattr(ra, "risk_capacity_profile", None)
            investment_horizon = int(getattr(ra, "investment_horizon_years", 0) or 0) or None
            # Knowledge-JSONs parsen
            for json_attr, target in [
                ("knowledge_services_json", knowledge_services),
                ("knowledge_instruments_json", knowledge_instruments),
            ]:
                raw = getattr(ra, json_attr, None)
                if raw:
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                target[str(k)] = bool(v)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Produkte (Recommendation) ----
    products: list = []
    try:
        from models.review import Product, RecommendationPosition, RecommendationRun
        last_run = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        if last_run is not None:
            positions = (
                db.query(RecommendationPosition)
                .filter(RecommendationPosition.recommendation_run_id == last_run.id)
                .all()
            )
            for pos in positions:
                product_obj = db.query(Product).filter(Product.id == pos.product_id).first()
                products.append({
                    "name": str(getattr(product_obj, "product_name", None) or "—"),
                    "isin": str(getattr(product_obj, "isin", "") or ""),
                    "asset_class": str(getattr(product_obj, "asset_class", "") or ""),
                    "sub_asset_class": str(getattr(product_obj, "sub_asset_class", "") or ""),
                    "currency": str(getattr(product_obj, "currency", "CHF") or "CHF"),
                    "ter_bps": int(getattr(product_obj, "ter_bps", 0) or 0),
                    "provider": str(getattr(product_obj, "provider", "") or ""),
                    "target_weight_bps": int(getattr(pos, "target_weight_bps", 0) or 0),
                    "target_amount_rappen": int(getattr(pos, "target_amount_rappen", 0) or 0),
                })
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Goal-Analysis (defensive — Felder existieren je nach Optimizer-Run) ----
    goal_analysis: list = []
    try:
        if ta_obj is not None:
            goal_json = getattr(ta_obj, "goal_analysis_json", None)
            if goal_json:
                parsed = json.loads(goal_json)
                if isinstance(parsed, list):
                    for entry in parsed:
                        if not isinstance(entry, dict):
                            continue
                        goal_analysis.append({
                            "rank": int(entry.get("rank", 0) or 0),
                            "label": str(entry.get("label", "") or ""),
                            "achievement_score": float(entry.get("achievement_score", 0) or 0),
                            "target_text": str(entry.get("target_text", "") or ""),
                        })
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Stress/MC-Werte (defensive aus optimization_*_json oder stress_evaluations_json) ----
    max_dd_bps = None
    var_95_bps = None
    median_cagr_bps = None
    try:
        if ta_obj is not None:
            stress_json = getattr(ta_obj, "stress_evaluations_json", None)
            if stress_json:
                parsed = json.loads(stress_json)
                if isinstance(parsed, dict):
                    max_dd_bps = int(parsed.get("max_drawdown_bps", 0) or 0) or None
                    var_95_bps = int(parsed.get("var_95_bps", 0) or 0) or None
                    median_cagr_bps = int(parsed.get("median_cagr_bps", 0) or 0) or None
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    horizon = int(getattr(mandate, "investment_horizon_years", 10) or 10)

    return AnlagestrategieData(
        target_allocation_bps=target_alloc_bps,
        cma_expected_return_bps=cma_return,
        cma_expected_vol_bps=cma_vol,
        horizon_years=horizon,
        monte_carlo_stats=None,
        optimizer_reasoning=None,
        risk_profile_label=risk_label,
        mandate_number=str(getattr(mandate, "mandate_number", "") or ""),
        advisory_wealth_rappen=advisory_wealth,
        risk_score_x10=risk_score_x10,
        investment_horizon_years=investment_horizon,
        mandate_type=str(getattr(mandate, "mandate_type", "") or ""),
        knowledge_services=knowledge_services,
        knowledge_instruments=knowledge_instruments,
        bucket_bands_bps=bucket_bands,
        bucket_amounts_rappen=bucket_amounts,
        products=products,
        goal_analysis=goal_analysis,
        max_drawdown_bps=max_dd_bps,
        var_95_bps=var_95_bps,
        median_cagr_bps=median_cagr_bps,
    )


@router.get(
    "/mandates/{mandate_id}/reports/anlagestrategie.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_anlagestrategie_pdf(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generiert Anlagestrategie-PDF fuer das Mandat."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    ctx = _build_pdf_context(mandate, current_user, db)
    data = _build_anlagestrategie_data(mandate, db)
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"5eyes_anlagestrategie_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get(
    "/mandates/{mandate_id}/reports/risikoprofil.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_risikoprofil_pdf(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generiert Risikoprofil-PDF fuer das Mandat (FINMA W305-konform)."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    ctx = _build_pdf_context(mandate, current_user, db)

    # Risikoprofil-Daten aus dem juengsten RiskAssessment laden (defensiv)
    risk_label = "Nicht definiert"
    risk_capacity = 0
    risk_tolerance = 0
    experience_years = 0
    suitability_note = ""
    try:
        from models.profiling import RiskAssessment
        ra = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == mandate.id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        if ra is not None:
            risk_label = str(getattr(ra, "risk_profile_label", None) or "Nicht definiert")
            risk_capacity = int(getattr(ra, "risk_capacity_score", 0) or 0)
            risk_tolerance = int(getattr(ra, "risk_tolerance_score", 0) or 0)
            experience_years = int(getattr(ra, "experience_years", 0) or 0)
            suitability_note = str(getattr(ra, "suitability_note", "") or "")
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    risk_data = RisikoprofilData(
        risk_profile_label=risk_label,
        risk_capacity_score=risk_capacity,
        risk_tolerance_score=risk_tolerance,
        knowledge_services={},
        knowledge_instruments={},
        experience_years=experience_years,
        suitability_note=suitability_note,
    )

    pdf_bytes = ReportLabRenderer().render_risikoprofil(ctx, risk_data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"5eyes_risikoprofil_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _build_portfolio_data(mandate: Mandate, db: Session) -> PortfolioData:
    """Sprint 11 Phase 6: Portfolio-Daten aus DB.

    Lädt die juengste RecommendationRun + Positions + Product-Lookup.
    Plus aktuelle WealthPositions falls vorhanden (fuer IST-Werte).
    """
    advisory_wealth = None
    positions: list = []

    try:
        from models.allocation import TargetAllocation
        ta = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate.id)
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )
        if ta is not None:
            advisory_wealth = int(getattr(ta, "advisory_wealth_rappen", 0) or 0) or None
    except Exception as exc:
        logger.warning("Portfolio data: TA load failed: %s", exc)

    try:
        from models.review import Product, RecommendationPosition, RecommendationRun
        last_run = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        if last_run is not None:
            pos_list = (
                db.query(RecommendationPosition)
                .filter(RecommendationPosition.recommendation_run_id == last_run.id)
                .all()
            )
            # Batch-Load Products (vermeidet N+1)
            product_ids = [p.product_id for p in pos_list if p.product_id]
            products_map = {}
            if product_ids:
                product_rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
                products_map = {p.id: p for p in product_rows}

            for pos in pos_list:
                prod = products_map.get(pos.product_id)
                target_bps = int(getattr(pos, "target_weight_bps", 0) or 0)
                current_bps = int(getattr(pos, "current_weight_bps", 0) or 0)
                positions.append({
                    "name": str(getattr(prod, "product_name", None) or "—"),
                    "isin": str(getattr(prod, "isin", "") or ""),
                    "sub_asset_class": str(getattr(prod, "sub_asset_class", "") or ""),
                    "target_weight_bps": target_bps,
                    "current_weight_bps": current_bps,
                    "drift_bps": current_bps - target_bps,
                    "target_amount_rappen": int(getattr(pos, "target_amount_rappen", 0) or 0),
                    "current_amount_rappen": int(getattr(pos, "current_amount_rappen", 0) or 0),
                    "currency": str(getattr(prod, "currency", "CHF") or "CHF"),
                    "ter_bps": int(getattr(prod, "ter_bps", 0) or 0),
                    "provider": str(getattr(prod, "provider", "") or ""),
                })
    except Exception as exc:
        logger.warning("Portfolio data: positions load failed: %s", exc)

    return PortfolioData(
        mandate_number=str(getattr(mandate, "mandate_number", "") or ""),
        advisory_wealth_rappen=advisory_wealth,
        positions=positions,
    )


@router.get(
    "/mandates/{mandate_id}/reports/portfolio.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_portfolio_pdf(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint 11 Phase 6: Portfolio-PDF mit Positionen + Soll-vs-IST + Drift."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    ctx = _build_pdf_context(mandate, current_user, db)
    data = _build_portfolio_data(mandate, db)
    pdf_bytes = ReportLabRenderer().render_portfolio(ctx, data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"5eyes_portfolio_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
