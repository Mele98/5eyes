"""PDF-Report-Endpoints fuer Anlagestrategie und Risikoprofil."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database import get_db
from models.allocation import CapitalMarketAssumption, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from services.auth import get_current_user, get_mandate_for_user_or_404
from services.pdf import ReportLabRenderer
from services.pdf.base import AnlagestrategieData, PDFContext, RisikoprofilData
from services.portfolio_engine import require_strategy_ready_assessment

router = APIRouter(tags=["PDF Reports"])


def _client_display_name(client: Client | None) -> str | None:
    if not client:
        return None
    parts = [
        str(getattr(client, "first_name", "") or "").strip(),
        str(getattr(client, "last_name", "") or "").strip(),
    ]
    full_name = " ".join(part for part in parts if part)
    return full_name or str(getattr(client, "client_number", "") or "").strip() or None


def _build_pdf_context(mandate: Mandate, current_user: User, db: Session) -> PDFContext:
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    client_name = _client_display_name(client)
    mandate_number = str(getattr(mandate, "mandate_number", "") or "")
    if client_name:
        mandate_name = f"{client_name} [{mandate_number}]" if mandate_number else client_name
    else:
        mandate_name = mandate_number or f"Mandat {mandate.id}"

    advisor_name = (
        getattr(current_user, "full_name", None)
        or getattr(current_user, "email", None)
        or "Berater"
    )
    advisor_org = (
        getattr(current_user, "organization", None)
        or getattr(current_user, "org_name", None)
        or None
    )
    return PDFContext(
        mandate_name=mandate_name,
        advisor_name=advisor_name,
        advisor_org=advisor_org,
        report_date=date.today(),
        audit_hash=_audit_hash_for_mandate(mandate),
        locale="de-CH",
    )


def _audit_hash_for_mandate(mandate: Mandate) -> str:
    seed = json.dumps({
        "mandate_id": str(mandate.id or ""),
        "mandate_number": str(getattr(mandate, "mandate_number", "") or ""),
        "mandate_type": str(getattr(mandate, "mandate_type", "") or ""),
        "status": str(getattr(mandate, "status", "") or ""),
        "investment_universe": str(getattr(mandate, "investment_universe", "") or ""),
        "updated_at": str(getattr(mandate, "updated_at", "") or ""),
    }, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _current_target_allocation_or_409(db: Session, mandate_id: str) -> TargetAllocation:
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).order_by(TargetAllocation.created_at.desc()).first()
    if not allocation:
        raise HTTPException(status_code=409, detail="Keine aktuelle Soll-Allokation fuer dieses Mandat gefunden.")
    return allocation


def _capital_market_assumption_for_allocation_or_409(
    db: Session,
    allocation: TargetAllocation,
) -> CapitalMarketAssumption:
    cma = None
    if allocation.capital_market_assumptions_id:
        cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == allocation.capital_market_assumptions_id,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).first()
    if not cma:
        cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).order_by(CapitalMarketAssumption.valid_from.desc()).first()
    if not cma:
        raise HTTPException(status_code=409, detail="Keine aktuellen Kapitalmarktannahmen.")
    return cma


def _allocation_bps(allocation: TargetAllocation) -> dict[str, int]:
    values = {
        "equities": int(allocation.target_equities_bps or 0),
        "bonds": int(allocation.target_bonds_bps or 0),
        "real_estate": int(allocation.target_real_estate_bps or 0),
        "alternatives": int(allocation.target_alternatives_bps or 0),
        "liquidity": int(allocation.target_liquidity_bps or 0),
    }
    if sum(values.values()) <= 0:
        raise HTTPException(status_code=409, detail="Aktuelle Soll-Allokation ist leer.")
    return values


def _weighted_cma_metric_bps(
    cma: CapitalMarketAssumption,
    target_alloc_bps: dict[str, int],
    suffix: str,
) -> int:
    fields = {
        "equities": f"equity_ch_{suffix}_bps",
        "bonds": f"bonds_chf_ig_{suffix}_bps",
        "real_estate": f"real_estate_ch_{suffix}_bps",
        "alternatives": f"alternatives_gold_{suffix}_bps",
        "liquidity": f"liquidity_{suffix}_bps",
    }
    total = 0.0
    for bucket, weight_bps in target_alloc_bps.items():
        total += (weight_bps / 10000.0) * int(getattr(cma, fields[bucket], 0) or 0)
    return int(round(total))


def _build_anlagestrategie_data(
    assessment: RiskAssessment,
    allocation: TargetAllocation,
    cma: CapitalMarketAssumption,
) -> AnlagestrategieData:
    target_alloc_bps = _allocation_bps(allocation)
    return AnlagestrategieData(
        target_allocation_bps=target_alloc_bps,
        cma_expected_return_bps=_weighted_cma_metric_bps(cma, target_alloc_bps, "return"),
        cma_expected_vol_bps=_weighted_cma_metric_bps(cma, target_alloc_bps, "vol"),
        horizon_years=int(getattr(assessment, "investment_horizon_years", 10) or 10),
        monte_carlo_stats=None,
        optimizer_reasoning=None,
        risk_profile_label=str(getattr(assessment, "final_profile", "") or ""),
    )


def _json_bool_mapping(raw: str | None) -> dict[str, bool]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in parsed.items():
        if isinstance(value, dict):
            result[str(key)] = bool(value.get("known") or value.get("informed"))
        else:
            result[str(key)] = bool(value)
    return result


def _build_risikoprofil_data(assessment: RiskAssessment) -> RisikoprofilData:
    suitability_note = (
        f"Profil {assessment.final_profile}; Anlagehorizont "
        f"{assessment.investment_horizon_label}; erstellt am {assessment.assessed_at}."
    )
    return RisikoprofilData(
        risk_profile_label=str(assessment.final_profile or ""),
        risk_capacity_score=int(assessment.risk_capacity_score_x10 or 0),
        risk_tolerance_score=int(assessment.risk_willingness_score_x10 or 0),
        knowledge_services=_json_bool_mapping(assessment.knowledge_services_json),
        knowledge_instruments=_json_bool_mapping(assessment.knowledge_instruments_json),
        experience_years=int(assessment.investment_horizon_years or 0),
        suitability_note=suitability_note,
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
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    try:
        assessment = require_strategy_ready_assessment(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    allocation = _current_target_allocation_or_409(db, mandate_id)
    cma = _capital_market_assumption_for_allocation_or_409(db, allocation)
    ctx = _build_pdf_context(mandate, current_user, db)
    data = _build_anlagestrategie_data(assessment, allocation, cma)
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
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    try:
        assessment = require_strategy_ready_assessment(db, mandate.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    ctx = _build_pdf_context(mandate, current_user, db)
    risk_data = _build_risikoprofil_data(assessment)
    pdf_bytes = ReportLabRenderer().render_risikoprofil(ctx, risk_data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"5eyes_risikoprofil_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
