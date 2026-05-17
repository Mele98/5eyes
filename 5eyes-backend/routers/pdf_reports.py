"""PDF-Report-Endpoints — Anlagestrategie, Risikoprofil als PDF-Download.

Spec: docs/planning/2026-05-17-sprint-5-pdf-engine.md §4 Phase 2
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database import get_db
from models.clients import Client
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
    return PDFContext(
        mandate_name=mandate_name,
        advisor_name=advisor_name,
        advisor_org=advisor_org,
        report_date=date.today(),
        audit_hash=_audit_hash_for_mandate(mandate),
        locale="de-CH",
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
    """Extrahiert AnlagestrategieData aus DB-Models.

    Defensive: fehlt etwas → Defaults, kein Crash.
    """
    target_alloc_bps: dict[str, int] = {}
    cma_return = 0
    cma_vol = 0

    # TargetAllocation lesen (falls vorhanden)
    try:
        from models.allocation import TargetAllocation
        ta = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate.id)
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )
        if ta is not None:
            target_alloc_bps = {
                "equities": int(getattr(ta, "equities_bps", 0) or 0),
                "bonds": int(getattr(ta, "bonds_bps", 0) or 0),
                "real_estate": int(getattr(ta, "real_estate_bps", 0) or 0),
                "alternatives": int(getattr(ta, "alternatives_bps", 0) or 0),
                "liquidity": int(getattr(ta, "liquidity_bps", 0) or 0),
            }
    except Exception:
        # Wenn Model anders heisst oder DB-Felder fehlen: leeres SAA
        pass

    # CMA-Werte (defensive)
    try:
        from models.allocation import CapitalMarketAssumption
        cma = (
            db.query(CapitalMarketAssumption)
            .order_by(CapitalMarketAssumption.valid_from.desc())
            .first()
        )
        if cma is not None:
            # Weighted Average ueber Allokation (vereinfacht)
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
    except Exception:
        pass

    horizon = int(getattr(mandate, "investment_horizon_years", 10) or 10)
    risk_label = getattr(mandate, "risk_profile_label", None)

    return AnlagestrategieData(
        target_allocation_bps=target_alloc_bps,
        cma_expected_return_bps=cma_return,
        cma_expected_vol_bps=cma_vol,
        horizon_years=horizon,
        monte_carlo_stats=None,  # MC-Stats laden ist Phase 2.1, hier defaults
        optimizer_reasoning=None,
        risk_profile_label=risk_label,
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
    except Exception:
        pass

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
