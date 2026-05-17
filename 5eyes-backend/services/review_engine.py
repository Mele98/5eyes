import calendar
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import AdvisoryLog, RecommendationPosition, RecommendationRun, ReviewTrigger
from price_updater import summarize_price_quality
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    risk_assessment_ready_for_strategy,
)


SYSTEM_TRIGGER_REVIEW = "Jahres-Review (System)"
SYSTEM_TRIGGER_DRIFT = "Bandbreitenverletzung (System)"
SYSTEM_TRIGGER_GOALS = "Zielerreichung gefaehrdet (System)"
SYSTEM_TRIGGER_MARKET_DATA = "Marktdaten veraltet (System)"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today() -> str:
    return date.today().isoformat()


def _parse_iso_date(value: str | None) -> date:
    raw = str(value or "").strip()[:10]
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def _add_months(value: str | None, months: int) -> str:
    base = _parse_iso_date(value)
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def _format_bps(bps: int) -> str:
    return f"{bps / 100:.1f}%"


def _get_system_trigger(
    db: Session,
    mandate_id: str,
    trigger_type: str,
    trigger_name: str,
) -> ReviewTrigger | None:
    return db.query(ReviewTrigger).filter(
        ReviewTrigger.mandate_id == mandate_id,
        ReviewTrigger.trigger_type == trigger_type,
        ReviewTrigger.trigger_name == trigger_name,
        ReviewTrigger.is_system == 1,
        ReviewTrigger.deleted_at.is_(None),
    ).first()


def _get_or_create_system_trigger(
    db: Session,
    mandate_id: str,
    trigger_type: str,
    trigger_name: str,
    now: str,
) -> ReviewTrigger:
    trigger = _get_system_trigger(db, mandate_id, trigger_type, trigger_name)
    if trigger:
        return trigger
    trigger = ReviewTrigger(
        id=new_uuid(),
        mandate_id=mandate_id,
        trigger_type=trigger_type,
        trigger_name=trigger_name,
        status="Aktiv",
        calendar_exported=0,
        is_system=1,
        created_at=now,
        updated_at=now,
    )
    db.add(trigger)
    db.flush()
    return trigger


def _resolve_system_trigger(
    db: Session,
    mandate_id: str,
    trigger_type: str,
    trigger_name: str,
    now: str,
    note: str,
) -> None:
    trigger = _get_system_trigger(db, mandate_id, trigger_type, trigger_name)
    if not trigger:
        return
    trigger.status = "Erledigt"
    trigger.triggered_value = None
    trigger.triggered_notes = note
    trigger.next_due_at = None if trigger_type != "Zeit" else trigger.next_due_at
    trigger.updated_at = now


def refresh_system_review_triggers(
    db: Session,
    mandate: Mandate,
    user_id: str,
    allocation_payload: dict | None = None,
) -> list[ReviewTrigger]:
    now = _now()
    today = _today()

    latest_log = db.query(AdvisoryLog).filter(
        AdvisoryLog.mandate_id == mandate.id,
        AdvisoryLog.entry_type.in_(("Beratungsprotokoll", "Anlageberatung")),
    ).order_by(AdvisoryLog.entry_date.desc(), AdvisoryLog.created_at.desc()).first()
    review_anchor = latest_log.entry_date if latest_log and latest_log.entry_date else mandate.opened_at
    review_trigger = _get_or_create_system_trigger(
        db=db,
        mandate_id=mandate.id,
        trigger_type="Zeit",
        trigger_name=SYSTEM_TRIGGER_REVIEW,
        now=now,
    )
    review_trigger.frequency = "jährlich"
    review_trigger.threshold_bps = None
    review_trigger.next_due_at = _add_months(review_anchor, 12)
    review_trigger.status = "Aktiv"
    review_trigger.triggered_value = None
    review_trigger.triggered_notes = (
        f"Letzter dokumentierter Review-Anker: {_parse_iso_date(review_anchor).isoformat()}"
        if review_anchor else "System-Review-Intervall aktiv"
    )
    review_trigger.updated_at = now

    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).first()

    if assessment and allocation and risk_assessment_ready_for_strategy(assessment):
        payload = allocation_payload
        if payload is None:
            policy, cma = ensure_runtime_reference_data(db, user_id)
            payload = build_target_payload_from_allocation(
                db=db,
                mandate=mandate,
                allocation=allocation,
                policy=policy,
                cma=cma,
                assessment=assessment,
                preferences=None,
            )

        live_rebalancing = payload.get("live_rebalancing") or {}
        drift_source = live_rebalancing.get("bucket_drifts") or payload.get("buckets", [])
        drifts = []
        for bucket in drift_source:
            current_weight = int(bucket.get("current_weight_bps") or 0)
            min_weight = int(bucket.get("band_min_bps") or 0)
            max_weight = int(bucket.get("band_max_bps") or 0)
            if min_weight == 0 and max_weight == 0:
                continue
            if current_weight < min_weight:
                drifts.append(
                    {
                        "label": bucket.get("asset_class") or "Allokation",
                        "breach_bps": min_weight - current_weight,
                        "detail": f"{bucket.get('asset_class')}: {_format_bps(current_weight)} unter Minimum {_format_bps(min_weight)}",
                    }
                )
            elif current_weight > max_weight:
                drifts.append(
                    {
                        "label": bucket.get("asset_class") or "Allokation",
                        "breach_bps": current_weight - max_weight,
                        "detail": f"{bucket.get('asset_class')}: {_format_bps(current_weight)} ueber Maximum {_format_bps(max_weight)}",
                    }
                )

        if drifts:
            drift_trigger = _get_or_create_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Markt",
                trigger_name=SYSTEM_TRIGGER_DRIFT,
                now=now,
            )
            drift_trigger.status = "Ausgelöst"
            drift_trigger.threshold_bps = max(item["breach_bps"] for item in drifts)
            drift_trigger.next_due_at = today
            drift_trigger.triggered_at = now
            drift_trigger.triggered_value = "; ".join(item["detail"] for item in drifts[:3])
            drift_trigger.triggered_notes = (
                "Systempruefung erkennt Bandbreitenverletzungen auf Basis der letzten Live-Bewertung des empfohlenen Beratungsportfolios."
                if live_rebalancing else
                "Systempruefung erkennt Bandbreitenverletzungen im Beratungsvermoegen."
            )
            drift_trigger.updated_at = now
        else:
            _resolve_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Markt",
                trigger_name=SYSTEM_TRIGGER_DRIFT,
                now=now,
                note=(
                    "Systempruefung: letzte Live-Bewertung des Beratungsportfolios innerhalb der Bandbreiten."
                    if live_rebalancing else
                    "Systempruefung: aktuelle Advisory-Allokation innerhalb der Bandbreiten."
                ),
            )

        endangered_goals = [
            goal for goal in payload.get("goal_analysis", [])
            if int(goal.get("achievement_score") or 0) < 45
        ]
        if endangered_goals:
            goal_trigger = _get_or_create_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Ereignis",
                trigger_name=SYSTEM_TRIGGER_GOALS,
                now=now,
            )
            goal_trigger.status = "Ausgelöst"
            goal_trigger.threshold_bps = None
            goal_trigger.next_due_at = today
            goal_trigger.triggered_at = now
            goal_trigger.triggered_value = "; ".join(
                f"{goal.get('label')}: {int(goal.get('achievement_score') or 0)}%"
                for goal in endangered_goals[:3]
            )
            goal_trigger.triggered_notes = "Mindestens ein Ziel liegt gemaess Goal Engine unter 45% Zielerreichung."
            goal_trigger.updated_at = now
        else:
            _resolve_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Ereignis",
                trigger_name=SYSTEM_TRIGGER_GOALS,
                now=now,
                note="Systempruefung: aktuell keine gefaehrdeten Ziele unterhalb 45% Zielerreichung.",
            )

    recommendation_runs = db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate.id
    ).order_by(RecommendationRun.created_at.desc()).all()
    current_run = next((item for item in recommendation_runs if item.result_status == "Final"), None) or (recommendation_runs[0] if recommendation_runs else None)
    recommendation_product_ids = []
    if current_run:
        recommendation_product_ids = [
            row[0]
            for row in db.query(RecommendationPosition.product_id).filter(
                RecommendationPosition.run_id == current_run.id
            ).all()
            if row[0]
        ]
    if recommendation_product_ids:
        quality = summarize_price_quality(db, recommendation_product_ids)
        stale_count = int(quality.get("stale_products_count") or 0)
        missing_count = int(quality.get("missing_price_count") or 0)
        mapping_gap_count = int(quality.get("mapping_gap_count") or 0)
        if stale_count or missing_count or mapping_gap_count:
            market_trigger = _get_or_create_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Markt",
                trigger_name=SYSTEM_TRIGGER_MARKET_DATA,
                now=now,
            )
            market_trigger.status = "Ausgelöst"
            market_trigger.threshold_bps = None
            market_trigger.next_due_at = today
            market_trigger.triggered_at = now
            market_trigger.triggered_value = (
                f"Fresh {quality.get('fresh_products_count', 0)}/{quality.get('active_products_count', 0)}"
                f"; stale {stale_count}; ohne Preis {missing_count}; ohne Mapping {mapping_gap_count}"
            )
            market_trigger.triggered_notes = (
                f"Empfehlungsuniversum mit Preisqualitaet unter Zielniveau. "
                f"Frisch innerhalb {quality.get('stale_after_days', 5)} Tagen: {quality.get('fresh_coverage_pct', 0)}%."
            )
            market_trigger.updated_at = now
        else:
            _resolve_system_trigger(
                db=db,
                mandate_id=mandate.id,
                trigger_type="Markt",
                trigger_name=SYSTEM_TRIGGER_MARKET_DATA,
                now=now,
                note="Systempruefung: aktuelle Empfehlungsprodukte verfuegen ueber frische Marktdaten.",
            )
    else:
        _resolve_system_trigger(
            db=db,
            mandate_id=mandate.id,
            trigger_type="Markt",
            trigger_name=SYSTEM_TRIGGER_MARKET_DATA,
            now=now,
            note="Systempruefung: aktuell kein aktives Empfehlungsuniversum fuer Marktdaten-Checks vorhanden.",
        )

    db.flush()
    return db.query(ReviewTrigger).filter(
        ReviewTrigger.mandate_id == mandate.id,
        ReviewTrigger.deleted_at.is_(None),
    ).order_by(ReviewTrigger.next_due_at).all()
