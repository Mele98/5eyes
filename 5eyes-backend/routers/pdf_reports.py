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
    PortfolioData,
    ProtokollData,
    RisikoprofilData,
    VertragData,
)

router = APIRouter(tags=["PDF Reports"])


def _build_pdf_context(mandate: Mandate, current_user: User, db: Session) -> PDFContext:
    """Sammelt PDFContext-Daten aus Mandant + Client + User.

    Mandate-Anzeige: <Client.name> [<mandate_number>] — falls Client
    nicht ladbar (Test-Setup) Fallback auf mandate_number.
    """
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    client_name = _client_display_name(client) if client else None
    mandate_number = str(getattr(mandate, "mandate_number", "") or "")
    if client_name:
        mandate_name = f"{client_name} [{mandate_number}]" if mandate_number else client_name
    else:
        mandate_name = mandate_number or f"Mandat {mandate.id}"

    advisor_name = getattr(current_user, "full_name", None) or getattr(current_user, "email", None) or "Berater"
    advisor_org = (
        getattr(current_user, "organization", None)
        or getattr(current_user, "org_name", None)
        or advisor_name
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


def _client_display_name(client: Client | None) -> str:
    if client is None:
        return ""
    first = str(getattr(client, "first_name", "") or "").strip()
    last = str(getattr(client, "last_name", "") or "").strip()
    return " ".join(part for part in (first, last) if part).strip() or str(
        getattr(client, "client_number", "") or ""
    )


def _bucket_key(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    aliases = {
        "aktien": "equities",
        "equities": "equities",
        "obligationen": "bonds",
        "anleihen": "bonds",
        "bonds": "bonds",
        "immobilien": "real_estate",
        "real estate": "real_estate",
        "real_estate": "real_estate",
        "alternative": "alternatives",
        "alternativen": "alternatives",
        "alternatives": "alternatives",
        "liquiditaet": "liquidity",
        "liquidität": "liquidity",
        "liquides vermoegen": "liquidity",
        "liquides vermögen": "liquidity",
        "cash": "liquidity",
        "liquidity": "liquidity",
    }
    return aliases.get(raw)


def _target_allocation_weights(ta_obj) -> dict[str, int]:
    return {
        "equities": int(getattr(ta_obj, "target_equities_bps", 0) or 0),
        "bonds": int(getattr(ta_obj, "target_bonds_bps", 0) or 0),
        "real_estate": int(getattr(ta_obj, "target_real_estate_bps", 0) or 0),
        "alternatives": int(getattr(ta_obj, "target_alternatives_bps", 0) or 0),
        "liquidity": int(getattr(ta_obj, "target_liquidity_bps", 0) or 0),
    }


def _target_allocation_bands(ta_obj) -> dict[str, tuple[int, int]]:
    return {
        "equities": (
            int(getattr(ta_obj, "band_equities_min_bps", 0) or 0),
            int(getattr(ta_obj, "band_equities_max_bps", 0) or 0),
        ),
        "bonds": (
            int(getattr(ta_obj, "band_bonds_min_bps", 0) or 0),
            int(getattr(ta_obj, "band_bonds_max_bps", 0) or 0),
        ),
        "real_estate": (
            int(getattr(ta_obj, "band_real_estate_min_bps", 0) or 0),
            int(getattr(ta_obj, "band_real_estate_max_bps", 0) or 0),
        ),
        "alternatives": (
            int(getattr(ta_obj, "band_alternatives_min_bps", 0) or 0),
            int(getattr(ta_obj, "band_alternatives_max_bps", 0) or 0),
        ),
        "liquidity": (
            int(getattr(ta_obj, "band_liquidity_min_bps", 0) or 0),
            int(getattr(ta_obj, "band_liquidity_max_bps", 0) or 0),
        ),
    }


def _advisory_wealth_positions(mandate: Mandate, db: Session) -> tuple[list[dict], dict[str, int], int]:
    from models.wealth import WealthPosition

    rows = (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == mandate.client_id,
            WealthPosition.is_active == 1,
            WealthPosition.deleted_at.is_(None),
            WealthPosition.assignment == "Beratungsvermögen",
        )
        .all()
    )
    split_fields = {
        "equities": ("alloc_equities_bps", "Aktien"),
        "bonds": ("alloc_bonds_bps", "Obligationen"),
        "real_estate": ("alloc_real_estate_bps", "Immobilien"),
        "alternatives": ("alloc_alternatives_bps", "Alternative Anlagen"),
        "liquidity": ("alloc_liquidity_bps", "Liquidität"),
    }
    positions: list[dict] = []
    current_amounts = {bucket: 0 for bucket in split_fields}
    total = 0
    for row in rows:
        value = int(getattr(row, "current_value_rappen", 0) or 0)
        if value <= 0:
            continue
        total += value
        any_split = False
        for bucket, (attr, label) in split_fields.items():
            bps = int(getattr(row, attr, 0) or 0)
            if bps <= 0:
                continue
            any_split = True
            amount = int(round(value * bps / 10000))
            current_amounts[bucket] += amount
            positions.append({
                "asset_class": bucket,
                "sub_asset_class": label,
                "current_amount_rappen": amount,
            })
        if not any_split:
            bucket = _bucket_key(getattr(row, "position_type", None)) or "liquidity"
            current_amounts[bucket] += value
            positions.append({
                "asset_class": bucket,
                "sub_asset_class": str(getattr(row, "label", "") or getattr(row, "position_type", "") or bucket),
                "current_amount_rappen": value,
            })
    current_bps = {
        bucket: int(round(amount / total * 10000)) if total > 0 else 0
        for bucket, amount in current_amounts.items()
    }
    return positions, current_bps, total


def _latest_target_allocation(mandate: Mandate, db: Session):
    from models.allocation import TargetAllocation

    current = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .first()
    )
    if current is not None:
        return current
    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .first()
    )


def _knowledge_map_from_json(raw) -> dict[str, bool]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in parsed.items():
        if isinstance(value, dict):
            result[str(key)] = bool(
                value.get("known")
                or value.get("informed")
                or value.get("has_experience")
            )
        else:
            result[str(key)] = bool(value)
    return result


def _build_anlagestrategie_data(mandate: Mandate, db: Session) -> AnlagestrategieData:
    """Extrahiert AnlagestrategieData aus DB-Models — Sprint 11 erweitert.

    Defensive: fehlt etwas → Defaults, kein Crash. Reichlich getattr-Defaults.

    Sprint U-P1 Fix C2+C5: Risk-Metrics (expected_return, expected_vol, MC,
    Goal-Analysis) kommen jetzt aus build_target_payload_from_allocation
    (echtes √(w'Σw) + echte Monte-Carlo) statt aus stress_evaluations_json +
    linearer Vol-Summe.
    """
    target_alloc_bps: dict[str, int] = {}
    bucket_bands: dict[str, tuple] = {}
    bucket_amounts: dict[str, int] = {}
    cma_return = 0
    cma_vol = 0
    advisory_wealth = None
    ta_obj = None
    engine_payload: dict | None = None
    advisory_positions, current_allocation_bps, current_advisory_wealth = _advisory_wealth_positions(mandate, db)

    # ---- TargetAllocation + Engine-Payload (Single-Source-of-Truth) ----
    try:
        ta_obj = _latest_target_allocation(mandate, db)
        if ta_obj is not None:
            target_alloc_bps = _target_allocation_weights(ta_obj)
            bucket_bands = _target_allocation_bands(ta_obj)
            advisory_wealth = (
                int(getattr(ta_obj, "advisory_wealth_at_generation_rappen", 0) or 0)
                or current_advisory_wealth
                or None
            )
            # Bucket-Amounts ableiten aus advisory_wealth * weight
            if advisory_wealth:
                for bucket, bps in target_alloc_bps.items():
                    bucket_amounts[bucket] = int(advisory_wealth * bps / 10000)

            # Sprint U-P1 Fix C2+C5: korrekte Risk-Metrics aus Engine-Payload
            try:
                from services.portfolio_engine import build_target_payload_from_allocation
                from models.profiling import RiskAssessment
                from models.allocation import OptimizerPolicy, CapitalMarketAssumption
                from services.portfolio_engine import ensure_runtime_reference_data
                assessment_obj = db.query(RiskAssessment).filter(
                    RiskAssessment.mandate_id == mandate.id,
                    RiskAssessment.is_current == 1,
                    RiskAssessment.deleted_at.is_(None),
                ).first()
                policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == ta_obj.policy_id).first()
                if policy and policy.is_current == 1 and assessment_obj:
                    _runtime_policy, runtime_cma = ensure_runtime_reference_data(db, getattr(mandate, "advisor_id", None) or getattr(assessment_obj, "assessed_by", None) or "")
                    engine_payload = build_target_payload_from_allocation(
                        db=db,
                        mandate=mandate,
                        allocation=ta_obj,
                        policy=policy,
                        cma=runtime_cma,
                        assessment=assessment_obj,
                        preferences=None,
                    )
            except Exception as exc:
                logger.warning(
                    "PDF engine-payload load failed for mandate %s: %s",
                    getattr(mandate, "id", "?"), exc,
                )
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- CMA-Werte aus Engine-Payload (echtes √(w'Σw) via _portfolio_volatility_bps) ----
    if engine_payload is not None:
        cma_return = int(engine_payload.get("expected_return_bps", 0) or 0)
        cma_vol = int(engine_payload.get("expected_volatility_bps", 0) or 0)
    else:
        # Fallback (Legacy): lineare gewichtete Summe wenn Engine-Payload nicht ladbar.
        # NOT MATHEMATICALLY CORRECT für Vola (ignoriert Korrelation) — nur als
        # letzte Notlösung wenn z.B. RA fehlt. Berater bekommt Drift-Warning im UI.
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
                "PDF data-load CMA-fallback failed for mandate %s: %s",
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
                target.update(_knowledge_map_from_json(getattr(ra, json_attr, None)))
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
                .filter(RecommendationPosition.run_id == last_run.id)
                .all()
            )
            product_ids = [p.product_id for p in positions if p.product_id]
            products_map = {}
            if product_ids:
                product_rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
                products_map = {p.id: p for p in product_rows}

            for pos in positions:
                product_obj = products_map.get(pos.product_id)
                asset_class = _bucket_key(getattr(product_obj, "asset_class", None)) or "alternatives"
                sub_class = str(getattr(product_obj, "sub_asset_class", "") or "")
                target_amt = int(getattr(pos, "target_amount_rappen", 0) or 0)

                products.append({
                    "name": str(getattr(product_obj, "product_name", None) or "—"),
                    "isin": str(getattr(product_obj, "isin", "") or ""),
                    "asset_class": asset_class,
                    "sub_asset_class": sub_class,
                    "currency": str(getattr(product_obj, "currency", "CHF") or "CHF"),
                    "ter_bps": int(getattr(product_obj, "ter_bps", 0) or 0),
                    "provider": str(getattr(product_obj, "provider", "") or ""),
                    "target_weight_bps": int(getattr(pos, "target_weight_bps", 0) or 0),
                    "target_amount_rappen": target_amt,
                })

    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Other Wealth (NICHT-Beratungsvermoegen) ----
    other_wealth_positions: list = []
    try:
        from models.wealth import WealthPosition
        client_id = getattr(mandate, "client_id", None)
        if client_id:
            other_q = (
                db.query(WealthPosition)
                .filter(
                    WealthPosition.client_id == client_id,
                    WealthPosition.is_active == 1,
                    WealthPosition.deleted_at.is_(None),
                    WealthPosition.assignment != "Beratungsvermögen",
                )
                .all()
            )
            for wp in other_q:
                amt = int(getattr(wp, "current_value_rappen", 0) or 0)
                if amt == 0:
                    continue
                other_wealth_positions.append({
                    "label": str(getattr(wp, "label", "—") or "—"),
                    "amount_rappen": amt,
                    "kind": str(getattr(wp, "position_type", "") or ""),
                })
    except Exception as exc:
        logger.warning(
            "PDF data-load other_wealth failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Risk-Answers (Frage-Antwort fuer Eignungspruefung) ----
    risk_answers: list = []
    try:
        from models.profiling import RiskAssessment as _RA, RiskAssessmentAnswer
        _ra = (
            db.query(_RA)
            .filter(_RA.mandate_id == mandate.id, _RA.is_current == 1)
            .order_by(_RA.created_at.desc())
            .first()
        )
        if _ra is not None:
            ans_rows = (
                db.query(RiskAssessmentAnswer)
                .filter(RiskAssessmentAnswer.assessment_id == _ra.id)
                .order_by(RiskAssessmentAnswer.question_number.asc())
                .all()
            )
            for a in ans_rows:
                risk_answers.append({
                    "question_number": int(getattr(a, "question_number", 0) or 0),
                    "question_section": str(getattr(a, "question_section", "") or ""),
                    "answer_label": str(getattr(a, "answer_label", "") or ""),
                    "answer_points": int(getattr(a, "answer_points", 0) or 0),
                })
    except Exception as exc:
        logger.warning(
            "PDF data-load risk_answers failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Cashflow-Events + Goals-List (Seite 12 der Vorlage) ----
    cashflow_events: list = []
    goals_list: list = []
    try:
        from models.wealth import Cashflow, WealthInflow, Goal
        client_id = getattr(mandate, "client_id", None)
        if client_id:
            # Einkommensseite Cashflows + WealthInflows
            cfs = (
                db.query(Cashflow)
                .filter(
                    Cashflow.client_id == client_id,
                    Cashflow.is_active == 1,
                    Cashflow.deleted_at.is_(None),
                )
                .all()
            )
            for cf in cfs:
                kind = str(getattr(cf, "cashflow_type", "") or "")
                # nur Einkommens-Cashflows (positiv)
                if kind.lower() not in ("einkommen", "income", "zufluss"):
                    continue
                cashflow_events.append({
                    "name": str(getattr(cf, "label", "—") or "—"),
                    "household_member": "",
                    "recurrence": str(getattr(cf, "frequency", "") or "—"),
                    "start_label": str(getattr(cf, "valid_from", "") or "—"),
                    "amount_rappen": int(getattr(cf, "amount_rappen", 0) or 0),
                })
            inflows = (
                db.query(WealthInflow)
                .filter(
                    WealthInflow.client_id == client_id,
                    WealthInflow.is_active == 1,
                    WealthInflow.deleted_at.is_(None),
                )
                .all()
            )
            for inf in inflows:
                cashflow_events.append({
                    "name": str(getattr(inf, "label", "—") or "—"),
                    "household_member": "",
                    "recurrence": "Einmalig" if not getattr(inf, "is_recurring", 0) else
                                  str(getattr(inf, "frequency", "") or "Wiederkehrend"),
                    "start_label": str(getattr(inf, "expected_year", "") or "—"),
                    "amount_rappen": int(getattr(inf, "amount_rappen", 0) or 0),
                })

        # Goals fuer Mandate
        goals_q = (
            db.query(Goal)
            .filter(
                Goal.mandate_id == mandate.id,
                Goal.is_active == 1,
                Goal.deleted_at.is_(None),
            )
            .order_by(Goal.rank.asc())
            .all()
        )
        for g in goals_q:
            target_amt = int(getattr(g, "target_amount_rappen", 0) or 0) or 0
            target_wealth = int(getattr(g, "target_wealth_rappen", 0) or 0) or 0
            target_pct = getattr(g, "target_return_bps", None)
            if target_pct is not None:
                target_pct = float(target_pct) / 100.0  # bps→%
            start = str(getattr(g, "start_date", "") or "—")
            target_date = str(getattr(g, "target_date", "") or "—")
            period = f"{start} – {target_date}" if start != "—" or target_date != "—" else "—"
            goals_list.append({
                "name": str(getattr(g, "label", "—") or "—"),
                "category": str(getattr(g, "goal_family", "") or "—"),
                "recurrence": str(getattr(g, "frequency", "") or "Einmalig"),
                "period_label": period,
                "amount_rappen": target_amt or target_wealth,
                "target_pct": target_pct,
            })
    except Exception as exc:
        logger.warning(
            "PDF data-load cashflow/goals failed for mandate %s: %s",
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
                            "shortfall_rappen": int(entry.get("shortfall_rappen", 0) or 0),
                        })
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    # ---- Stress/MC-Werte (echte MC-Werte aus Engine-Payload) ----
    # Sprint U-P1 Fix C2: PDF las vorher `median_cagr_bps`/`var_95_bps`/
    # `max_drawdown_bps` aus stress_evaluations_json — diese Keys existierten
    # dort NICHT (Stress-JSON hat scenario-spezifische Felder wie
    # `end_wealth_rappen`, `min_year_wealth_rappen`). Resultat: PDF zeigte
    # immer 0/None fuer CAGR + VaR + Drawdown. Jetzt aus engine_payload.
    max_dd_bps = None
    var_95_bps = None
    median_cagr_bps = None
    if engine_payload is not None:
        mc = engine_payload.get("monte_carlo") or {}
        try:
            max_dd_bps = int(mc.get("target_max_drawdown_p50_bps", 0) or 0) or None
            var_95_bps = int(mc.get("target_var_95_1y_bps", 0) or 0) or None
            median_cagr_bps = int(mc.get("target_annualized_return_p50_bps", 0) or 0) or None
        except (TypeError, ValueError) as exc:
            logger.warning(
                "PDF MC-metrics parse failed for mandate %s: %s",
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
        risk_answers=risk_answers,
        advisory_positions=advisory_positions,
        other_wealth_positions=other_wealth_positions,
        cashflow_events=cashflow_events,
        goals_list=goals_list,
        current_allocation_bps=current_allocation_bps,
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
    knowledge_services: dict[str, bool] = {}
    knowledge_instruments: dict[str, bool] = {}
    try:
        from models.profiling import RiskAssessment
        ra = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == mandate.id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        if ra is not None:
            is_overridden = bool(getattr(ra, "is_overridden", 0))
            risk_label = str(
                (getattr(ra, "override_profile", None) if is_overridden else None)
                or getattr(ra, "final_profile", None)
                or "Nicht definiert"
            )
            risk_capacity = int(getattr(ra, "risk_capacity_score_x10", 0) or 0)
            risk_tolerance = int(getattr(ra, "risk_willingness_score_x10", 0) or 0)
            experience_years = int(getattr(ra, "investment_horizon_years", 0) or 0)
            knowledge_services = _knowledge_map_from_json(getattr(ra, "knowledge_services_json", None))
            knowledge_instruments = _knowledge_map_from_json(getattr(ra, "knowledge_instruments_json", None))
            if is_overridden:
                reason = str(getattr(ra, "override_reason", "") or "").strip()
                suitability_note = "Berater-Override wurde dokumentiert."
                if reason:
                    suitability_note += f" Begruendung: {reason}"
            else:
                suitability_note = (
                    "Risikofaehigkeit, Risikobereitschaft, Anlagehorizont "
                    "sowie Kenntnisse und Erfahrungen wurden dokumentiert."
                )
    except Exception as exc:
        logger.warning(
            "PDF data-load section failed for mandate %s: %s",
            getattr(mandate, "id", "?"), exc,
        )

    risk_data = RisikoprofilData(
        risk_profile_label=risk_label,
        risk_capacity_score=risk_capacity,
        risk_tolerance_score=risk_tolerance,
        knowledge_services=knowledge_services,
        knowledge_instruments=knowledge_instruments,
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
        ta = _latest_target_allocation(mandate, db)
        if ta is not None:
            advisory_wealth = int(
                getattr(ta, "advisory_wealth_at_generation_rappen", 0) or 0
            ) or None
    except Exception as exc:
        logger.warning("Portfolio data: TA load failed: %s", exc)

    try:
        from models.review import (
            Product,
            RecommendationHolding,
            RecommendationPosition,
            RecommendationRun,
        )
        last_run = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        if last_run is not None:
            pos_list = (
                db.query(RecommendationPosition)
                .filter(RecommendationPosition.run_id == last_run.id)
                .all()
            )
            # Batch-Load Products (vermeidet N+1)
            product_ids = [p.product_id for p in pos_list if p.product_id]
            products_map = {}
            if product_ids:
                product_rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
                products_map = {p.id: p for p in product_rows}

            holding_rows = (
                db.query(RecommendationHolding)
                .filter(
                    RecommendationHolding.run_id == last_run.id,
                    RecommendationHolding.deleted_at.is_(None),
                )
                .all()
            )
            current_amount_by_position: dict[str, int] = {}
            for holding in holding_rows:
                pos_id = str(getattr(holding, "recommendation_position_id", "") or "")
                if not pos_id:
                    continue
                current_amount_by_position[pos_id] = (
                    current_amount_by_position.get(pos_id, 0)
                    + int(getattr(holding, "market_value_rappen", 0) or 0)
                )
            current_total = sum(current_amount_by_position.values())
            target_total = sum(int(getattr(pos, "target_amount_rappen", 0) or 0) for pos in pos_list)
            if advisory_wealth is None:
                advisory_wealth = current_total or target_total or None

            for pos in pos_list:
                prod = products_map.get(pos.product_id)
                target_bps = int(getattr(pos, "target_weight_bps", 0) or 0)
                current_amount = current_amount_by_position.get(str(getattr(pos, "id", "") or ""), 0)
                current_bps = (
                    int(round(current_amount / current_total * 10000))
                    if current_total > 0 and current_amount > 0
                    else 0
                )
                drift_bps = current_bps - target_bps if current_total > 0 else 0
                positions.append({
                    "name": str(getattr(prod, "product_name", None) or "—"),
                    "isin": str(getattr(prod, "isin", "") or ""),
                    "sub_asset_class": str(getattr(prod, "sub_asset_class", "") or ""),
                    "target_weight_bps": target_bps,
                    "current_weight_bps": current_bps,
                    "drift_bps": drift_bps,
                    "target_amount_rappen": int(getattr(pos, "target_amount_rappen", 0) or 0),
                    "current_amount_rappen": current_amount,
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


def _build_vertrag_data(mandate: Mandate, doc_id: str | None, db: Session) -> VertragData:
    """Sprint 12: Vertrags-Daten aus ContractDocument + Mandate.

    Wenn doc_id None: nimmt den juengsten Vertrag fuer das Mandat.
    Wenn keine Vertraege da: liefert Standard-Defaults aus dem
    Frontend-Modal m-contract-edit.
    """
    document_title = "Persönliche Anlagestrategie – Individuelle Vermögensberatung"
    document_type = "Anlagestrategie"
    praeambel = (
        "Auf Grundlage der gemeinsamen Analyse der persönlichen und finanziellen "
        "Situation sowie der Anlageziele wurde folgende individuelle "
        "Anlagestrategie vereinbart."
    )
    haftungsklausel = (
        "Diese Empfehlung basiert auf den zum Zeitpunkt der Beratung bekannten "
        "Informationen und stellt keine Garantie künftiger Wertentwicklungen dar. "
        "Die Umsetzung erfolgt eigenverantwortlich durch den Kunden."
    )
    sondervereinbarungen = None
    ort = "Zürich"
    datum = date.today().isoformat()

    try:
        from models.review import ContractDocument
        q = db.query(ContractDocument).filter(
            ContractDocument.mandate_id == mandate.id,
            ContractDocument.deleted_at.is_(None),
        )
        if doc_id:
            doc = q.filter(ContractDocument.id == doc_id).first()
        else:
            doc = q.order_by(ContractDocument.created_at.desc()).first()
        if doc is not None:
            document_title = str(getattr(doc, "title", None) or document_title)
            document_type = str(getattr(doc, "document_type", None) or document_type)
            content_raw = getattr(doc, "content_json", None)
            if content_raw:
                try:
                    parsed = json.loads(content_raw)
                    if isinstance(parsed, dict):
                        praeambel = str(parsed.get("praeambel", praeambel) or praeambel)
                        haftungsklausel = str(parsed.get("haftungsklausel", haftungsklausel) or haftungsklausel)
                        sondervereinbarungen = parsed.get("sondervereinbarungen", None)
                        if sondervereinbarungen is not None:
                            sondervereinbarungen = str(sondervereinbarungen)
                        ort = str(parsed.get("ort_unterzeichnung", parsed.get("ort", ort)) or ort)
                        datum = str(parsed.get("vereinbarungs_datum", parsed.get("datum", datum)) or datum)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Vertrag content_json parse failed: %s", exc)
    except Exception as exc:
        logger.warning("Vertrag data: ContractDocument load failed: %s", exc)

    advisory_wealth = None
    try:
        ta = _latest_target_allocation(mandate, db)
        if ta is not None:
            advisory_wealth = int(
                getattr(ta, "advisory_wealth_at_generation_rappen", 0) or 0
            ) or None
    except Exception as exc:
        logger.warning("Vertrag data: TA load failed: %s", exc)

    return VertragData(
        document_title=document_title,
        document_type=document_type,
        praeambel=praeambel,
        haftungsklausel=haftungsklausel,
        sondervereinbarungen=sondervereinbarungen,
        ort_unterzeichnung=ort,
        vereinbarungs_datum=datum,
        mandate_number=str(getattr(mandate, "mandate_number", "") or ""),
        advisory_wealth_rappen=advisory_wealth,
    )


@router.get(
    "/mandates/{mandate_id}/reports/vertrag.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_vertrag_pdf(
    mandate_id: str,
    document_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sprint 12: Vertrags-PDF (ContractDocument). Optional ?document_id=..."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    ctx = _build_pdf_context(mandate, current_user, db)
    data = _build_vertrag_data(mandate, document_id, db)
    pdf_bytes = ReportLabRenderer().render_vertrag(ctx, data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"5eyes_vertrag_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _build_protokoll_data(mandate: Mandate, db: Session) -> ProtokollData:
    """Beratungsprotokoll-Daten aus AdvisoryLog + letzter Empfehlung."""
    advisory_wealth = None
    try:
        ta = _latest_target_allocation(mandate, db)
        if ta is not None:
            advisory_wealth = int(
                getattr(ta, "advisory_wealth_at_generation_rappen", 0) or 0
            ) or None
    except Exception as exc:
        logger.warning("Protokoll data: TA load failed: %s", exc)

    entries: list[dict] = []
    latest_recommendation_summary = None
    try:
        from models.review import AdvisoryLog, RecommendationRun

        log_rows = (
            db.query(AdvisoryLog)
            .filter(AdvisoryLog.mandate_id == mandate.id)
            .order_by(AdvisoryLog.entry_date.desc(), AdvisoryLog.created_at.desc())
            .limit(40)
            .all()
        )
        for row in log_rows:
            entries.append({
                "entry_date": str(getattr(row, "entry_date", "") or ""),
                "entry_type": str(getattr(row, "entry_type", "") or ""),
                "title": str(getattr(row, "title", "") or ""),
                "description": str(getattr(row, "description", "") or ""),
                "decision": str(getattr(row, "decision", "") or ""),
                "status": str(getattr(row, "status", "") or ""),
            })

        latest_run = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        if latest_run is not None:
            latest_recommendation_summary = str(
                getattr(latest_run, "objective_summary", None)
                or getattr(latest_run, "result_status", "")
                or ""
            ).strip() or None
    except Exception as exc:
        logger.warning("Protokoll data: AdvisoryLog load failed: %s", exc)

    return ProtokollData(
        mandate_number=str(getattr(mandate, "mandate_number", "") or ""),
        advisory_wealth_rappen=advisory_wealth,
        entries=entries,
        latest_recommendation_summary=latest_recommendation_summary,
    )


@router.get(
    "/mandates/{mandate_id}/reports/protokoll.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_protokoll_pdf(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Beratungsprotokoll-PDF mit AdvisoryLog und Unterschrift."""
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    ctx = _build_pdf_context(mandate, current_user, db)
    data = _build_protokoll_data(mandate, db)
    pdf_bytes = ReportLabRenderer().render_protokoll(ctx, data)
    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    filename = f"protokoll_{safe_name}_{ctx.report_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
