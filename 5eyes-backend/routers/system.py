from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.review import AuditLog
from models.snapshots import AssetClassAnnualReturn, AssetClassPriceHistory
from models.users import User
from schemas.review import AuditLogEntry, AuditLogPage
from services.audit import log as audit_log
from services.auth import require_admin, require_advisor, require_super_admin, get_mandate_for_user_or_404
from services.foundation_example import upsert_foundation_example_case
from services.foundation_purge import purge_demo_client_data, purge_foundation_example_data
from services.maintenance import (
    build_compliance_status,
    create_backup,
    create_support_bundle,
    database_paths,
    list_backups,
    run_integrity_check,
    run_optimize,
    tail_app_log,
)
from services.shadow_comparison import (
    ShadowComparisonMissing,
    ShadowComparisonNotFound,
    aggregate_shadow_comparisons,
    build_shadow_comparison_payload,
)

router = APIRouter(prefix="/admin/system", tags=["System"])
AUDIT_LOG_VALID_ACTIONS = frozenset(
    {
        'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'EXPORT', 'PASSWORD_RESET',
        'OPTIMIZER_MODE_CHANGE',
        # Sprint U-102 (2026-06-05): zusaetzliche Admin-Aktionen die im
        # Audit-Log geschrieben werden — muessen filtrierbar sein.
        'BACKFILL',
        'BACKUP',
        'SUPPORT_BUNDLE',
        'MARKET_DATA_REFRESH',
        'MARKET_DATA_PURGE',
        'DB_OPTIMIZE',
        'FOUNDATION_EXAMPLE',
        'FOUNDATION_PURGE',
    }
)
OPTIMIZER_MODE_VALUES = frozenset({'house_matrix', 'shadow_stochastic', 'stochastic'})


@router.get('/paths')
def get_paths(current_user: User = Depends(require_admin)):
    return database_paths()


@router.get('/backups')
def get_backups(current_user: User = Depends(require_admin)):
    return list_backups()


@router.get('/logs/recent')
def get_recent_logs(
    lines: int = Query(default=120, ge=1, le=500),
    current_user: User = Depends(require_admin),
):
    return tail_app_log(lines=lines)


@router.get('/audit-log', response_model=AuditLogPage)
def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    action: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    query = db.query(AuditLog)

    # E1 (2026-06-14): Mandanten-Trennung — super_admin (Operator) sieht das ganze
    # Audit-Log; ein Firmen-Admin NUR Eintraege zu EIGENEN Clients/Mandaten plus
    # eigene Aktionen. (audit_log hat keine tenant_id -> Scope ueber accessible IDs;
    # fremde System-/Operator-Aktionen ohne client/mandate-Bezug bleiben unsichtbar.)
    _user_tid = getattr(current_user, "tenant_id", None)
    if getattr(current_user, "role", None) != "super_admin" and _user_tid and str(_user_tid).strip():
        from services.auth import get_accessible_client_ids, get_accessible_mandate_ids
        cids = list(get_accessible_client_ids(db, current_user))
        mids = list(get_accessible_mandate_ids(db, current_user))
        conds = [AuditLog.user_id == current_user.id]
        if cids:
            conds.append(AuditLog.client_id.in_(cids))
        if mids:
            conds.append(AuditLog.mandate_id.in_(mids))
        query = query.filter(or_(*conds))

    normalized_action = str(action or '').strip().upper()
    if normalized_action in AUDIT_LOG_VALID_ACTIONS:
        query = query.filter(AuditLog.action == normalized_action)

    query_text = str(q or '').strip()
    if query_text:
        # LIKE-Wildcards (% und _) im User-Input escapen, damit eine Suche nach '%'
        # nicht alle Datensaetze matched, sondern nur Eintraege mit literalem %.
        escaped = query_text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f"%{escaped}%"
        query = query.filter(
            or_(
                AuditLog.user_name.ilike(pattern, escape='\\'),
                AuditLog.table_name.ilike(pattern, escape='\\'),
            )
        )

    total = query.count()
    entries = (
        query
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return AuditLogPage(
        total=total,
        limit=limit,
        offset=offset,
        entries=entries,
    )


@router.get('/db/integrity')
def database_integrity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return run_integrity_check(db)


@router.post('/recommendation-runs/cleanup')
def cleanup_recommendation_runs_endpoint(
    body: dict | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-104 (2026-06-05): RecommendationRuns aelter als
    retention_days (default 90) loeschen. Berater-Trigger, kein Cron
    (Anlagephilosophie ADR-003).

    Body (alles optional):
      - retention_days: int (default 90, min 30)
      - dry_run: bool (default False)
    """
    from services.recommendation_run_cleanup import cleanup_recommendation_runs

    payload = body or {}
    retention_days = payload.get("retention_days")
    dry_run = bool(payload.get("dry_run", False))
    try:
        result = cleanup_recommendation_runs(
            db,
            retention_days=int(retention_days) if retention_days is not None else None,
            dry_run=dry_run,
            # 2026-07-24 (Security-Audit): current_user durchreichen, sonst
            # loescht/zaehlt cleanup_recommendation_runs quer durch ALLE
            # Tenants -- ein tenant-gebundener Admin (nicht super_admin)
            # koennte fremder Tenants RecommendationRun-Historie physisch
            # unwiderruflich loeschen.
            current_user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="recommendation_runs",
        record_id=f"cleanup-cutoff-{result.cutoff_iso}",
        action="DELETE",
        field_name="bulk_cleanup",
        new_value=(
            f"dry_run={dry_run} "
            f"days={result.retention_days} "
            f"runs={result.deleted_runs} "
            f"positions={result.deleted_positions}"
        ),
    )
    db.commit()
    return result.to_dict()


@router.post('/db/backup')
def backup_database(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = create_backup()
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="system_backups",
        record_id=str(result.get("backup_path") or result.get("filename") or "backup"),
        action="BACKUP",
        new_value=str(result.get("size_bytes") or result.get("bytes") or ""),
    )
    db.commit()
    return result


@router.post('/support-bundle')
def create_support_bundle_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = create_support_bundle()
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="support_bundles",
        record_id=str(result.get("bundle_path") or result.get("filename") or "support_bundle"),
        action="SUPPORT_BUNDLE",
        new_value=str(result.get("size_bytes") or result.get("bytes") or ""),
    )
    db.commit()
    return result


@router.get('/compliance')
def get_compliance_status(current_user: User = Depends(require_admin)):
    return build_compliance_status()


@router.get('/optimizer-mode')
def get_optimizer_mode(current_user: User = Depends(require_admin)):
    return {
        'optimizer_mode': settings.optimizer_mode,
        'allowed_values': sorted(OPTIMIZER_MODE_VALUES),
    }


@router.put('/optimizer-mode')
def set_optimizer_mode(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    requested = str(body.get('optimizer_mode') or '').strip().lower()
    if requested not in OPTIMIZER_MODE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"optimizer_mode muss einer von {', '.join(sorted(OPTIMIZER_MODE_VALUES))} sein.",
        )
    old_value = str(settings.optimizer_mode or '').strip().lower()
    changed = requested != old_value
    if changed:
        settings.optimizer_mode = requested
        audit_log(
            db,
            user_id=current_user.id,
            user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
            table_name="system_settings",
            record_id="optimizer_mode",
            action="OPTIMIZER_MODE_CHANGE",
            field_name="optimizer_mode",
            old_value=old_value,
            new_value=requested,
        )
        db.commit()
    return {
        'optimizer_mode': settings.optimizer_mode,
        'old_value': old_value,
        'new_value': requested,
        'changed': changed,
    }


@router.get('/shadow-comparison/{mandate_id}')
def get_shadow_comparison(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # SECURITY (Mandanten-Trennung): Ownership-/Tenant-Guard — sonst liest ein
    # tenant-gebundener Admin (Firma A) Shadow-Daten eines fremden Mandats (Firma B).
    # 404 bei fremdem/nicht vorhandenem Mandat.
    get_mandate_for_user_or_404(mandate_id, db, current_user)
    try:
        return build_shadow_comparison_payload(db, mandate_id)
    except ShadowComparisonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ShadowComparisonMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get('/shadow-comparison-aggregate')
def get_shadow_comparison_aggregate(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Stage 8 Foundation: aggregierter Shadow-Vergleich über alle Mandate.

    Quelle für die Owner-Verifikation und das Compliance-Template
    (docs/compliance/shadow-vergleich-template.md). Liefert
    GREEN/YELLOW/RED-Counts, repräsentative Beispiele und das
    Methodology-§4-Gesamt-Verdikt fuer den Default-Wechsel.
    """
    _ = current_user
    return aggregate_shadow_comparisons(db)


_VALID_ASSET_CLASSES = {'Aktien', 'Obligationen', 'Immobilien', 'Liquiditaet', 'Alternative'}


@router.get('/annual-returns')
def get_annual_returns(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rows = (
        db.query(AssetClassAnnualReturn)
        .order_by(AssetClassAnnualReturn.year, AssetClassAnnualReturn.asset_class)
        .all()
    )
    result: dict = {}
    for row in rows:
        result.setdefault(str(row.year), {})[row.asset_class] = {
            'return_bps': row.return_bps,
            'source': row.source or '',
        }
    return result


@router.post('/annual-returns/backfill')
def backfill_annual_returns_endpoint(
    from_year: int | None = None,
    to_year: int | None = None,
    overwrite: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-P11a (2026-05-22): Annual-Returns automatisch aus
    Marktdaten-Aggregator (yfinance + stooq) befüllen.

    Defaults:
        from_year = aktuelles Jahr - 20
        to_year   = aktuelles Jahr - 1
    Body-Params (Query):
        overwrite: True (default) - bestehende Rows überschreiben.
                   False = vorhandene Rows beibehalten, nur Lücken füllen.

    Audit-Log-Eintrag wird geschrieben (Action=BACKFILL).
    """
    from services.market_data.annual_returns_backfill import backfill_annual_returns
    from services.market_data.factory import build_default_aggregator

    current_year = datetime.utcnow().year
    fy = from_year if from_year is not None else current_year - 20
    ty = to_year if to_year is not None else current_year - 1
    try:
        aggregator = build_default_aggregator()
        result = backfill_annual_returns(
            db, aggregator,
            from_year=int(fy), to_year=int(ty),
            overwrite=bool(overwrite),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.add(AuditLog(
        id=str(uuid4()),
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="asset_class_annual_returns",
        record_id=f"{fy}-{ty}",
        action="BACKFILL",
        new_value=f"rows_written={result['summary']['rows_written']} errors={result['summary']['error_count']}",
        created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    return result


@router.put('/annual-returns/{year}/{asset_class}')
def upsert_annual_return(
    year: int,
    asset_class: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if asset_class not in _VALID_ASSET_CLASSES:
        raise HTTPException(status_code=400, detail=f"Ungültige Anlageklasse: {asset_class}")
    if 'return_bps' not in body:
        raise HTTPException(status_code=400, detail="return_bps erforderlich")
    return_bps = int(body['return_bps'])
    source = str(body.get('source') or 'admin')
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(AssetClassAnnualReturn)
        .filter_by(year=year, asset_class=asset_class)
        .first()
    )
    if existing:
        old_bps = existing.return_bps
        existing.return_bps = return_bps
        existing.source = source
        existing.updated_at = now
        action = "UPDATE"
        old_value = str(old_bps)
    else:
        db.add(AssetClassAnnualReturn(
            id=str(uuid4()), year=year, asset_class=asset_class,
            return_bps=return_bps, source=source, created_at=now, updated_at=now,
        ))
        action = "CREATE"
        old_value = None
    # Sprint U-102 (2026-06-05): direkter CMA-Write muss auditiert sein.
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="asset_class_annual_returns",
        record_id=f"{year}-{asset_class}",
        action=action,
        field_name="return_bps",
        old_value=old_value,
        new_value=str(return_bps),
    )
    db.commit()
    return {'year': year, 'asset_class': asset_class, 'return_bps': return_bps}


@router.get('/asset-class-prices/status')
def get_asset_class_prices_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-P19: Abdeckung der täglichen EOD-Serie je Asset-Klasse
    (erste/letzte Bar + Punktzahl) — Datenquelle für resolution=daily."""
    from sqlalchemy import func
    rows = (
        db.query(
            AssetClassPriceHistory.asset_class,
            func.min(AssetClassPriceHistory.price_date),
            func.max(AssetClassPriceHistory.price_date),
            func.count(AssetClassPriceHistory.id),
        )
        .group_by(AssetClassPriceHistory.asset_class)
        .all()
    )
    coverage = {
        ac: {"first": first, "last": last, "points": int(cnt)}
        for ac, first, last, cnt in rows
    }
    complete = all(ac in coverage and coverage[ac]["points"] > 0 for ac in _VALID_ASSET_CLASSES)
    return {"coverage": coverage, "complete": complete}


@router.post('/asset-class-prices/backfill')
def backfill_asset_class_prices_endpoint(
    from_year: int | None = None,
    to_year: int | None = None,
    overwrite: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-P19: Tägliche EOD-Serie je Asset-Klasse aus dem Marktdaten-
    Aggregator (yfinance + stooq) befüllen — Foundation für den Daily-Backtest.

    Defaults:
        from_year = aktuelles Jahr - 20
        to_year   = aktuelles Jahr
    overwrite: True (default) bestehende Rows überschreiben, False = nur Lücken.

    Audit-Log-Eintrag (Action=BACKFILL).
    """
    from services.market_data.asset_class_price_backfill import backfill_asset_class_prices
    from services.market_data.factory import build_default_aggregator

    current_year = datetime.utcnow().year
    fy = from_year if from_year is not None else current_year - 20
    ty = to_year if to_year is not None else current_year
    try:
        aggregator = build_default_aggregator()
        result = backfill_asset_class_prices(
            db, aggregator,
            from_year=int(fy), to_year=int(ty),
            overwrite=bool(overwrite),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.add(AuditLog(
        id=str(uuid4()),
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="asset_class_price_history",
        record_id=f"{fy}-{ty}",
        action="BACKFILL",
        new_value=f"rows_written={result['summary']['rows_written']} errors={result['summary']['error_count']}",
        created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    return result


@router.post('/market-data/refresh-now')
def refresh_market_data_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """U-31: manueller Recovery-Trigger fuer den taeglichen Marktdaten-Refresh."""
    try:
        from services.market_data_daily_refresh import run_daily_market_data_refresh
        result = run_daily_market_data_refresh(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    # Sprint U-102 (2026-06-05): manueller Refresh muss auditiert sein.
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="market_data_runs",
        record_id=str(result.get("run_id") or result.get("started_at") or "refresh"),
        action="MARKET_DATA_REFRESH",
        new_value=str(result.get("status") or "ok"),
    )
    db.commit()
    return result


@router.post('/fx-rates/refresh-now')
def refresh_fx_rates_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sprint U-99 (2026-06-05): FX-only Recovery-Trigger.

    Aktualisiert ausschliesslich asset_class_fx_history (kein Product-
    oder Asset-Class-Proxy-Sweep). Sinnvoll wenn Berater Wochenend-Pflege
    der Reference-Data macht ohne den vollen Marktdaten-Refresh
    anzustossen.
    """
    try:
        from services.fx_rate_daily_refresh import run_daily_fx_refresh
        result = run_daily_fx_refresh(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="asset_class_fx_history",
        record_id=str(result.get("started_at") or "fx_refresh"),
        action="MARKET_DATA_REFRESH",
        field_name="fx_only_refresh",
        new_value=f"fx_added={result.get('fx_added', 0)} status={result.get('status', 'ok')}",
    )
    db.commit()
    return result


@router.get('/market-data/provider-health')
def get_provider_health_registry(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    from services.market_data.provider_health_registry import list_provider_health
    return {
        "items": list_provider_health(db, limit=limit),
        "limit": limit,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.post('/market-data/provider-health/reset')
def reset_provider_health_registry(
    body: dict | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    from services.market_data.provider_health_registry import reset_provider_health

    provider_name = str((body or {}).get("provider_name") or "").strip() or None
    deleted = reset_provider_health(db, provider_name=provider_name)
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="provider_health_events",
        record_id=provider_name or "all",
        action="DELETE",
        field_name="provider_health_events",
        old_value=f"deleted={deleted}",
        new_value="reset",
    )
    db.commit()
    return {"deleted": deleted, "provider_name": provider_name, "status": "reset"}


@router.get('/market-data/purge-history')
def get_market_data_purge_history(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    from services.market_data.cache_purge import list_purge_history

    return {
        "items": list_purge_history(db, limit=limit),
        "limit": limit,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.post('/market-data/purge-now')
def purge_market_data_cache_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Manual recovery trigger for the health-aware market-data cache purge."""
    from services.market_data.cache_purge import run_daily_cache_purge

    result = run_daily_cache_purge(db)
    # Sprint U-102 (2026-06-05): Cache-Purge ist destruktiv, muss auditiert sein.
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "advisor"),
        table_name="market_data_cache",
        record_id=str(result.get("run_id") or result.get("started_at") or "purge"),
        action="MARKET_DATA_PURGE",
        new_value=str(result.get("rows_deleted") or result.get("status") or "ok"),
    )
    db.commit()
    return result


@router.post('/db/optimize')
def optimize_database(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = run_optimize(db)
    # Sprint U-102 (2026-06-05): VACUUM/ANALYZE wird auditiert (Compliance-Spur).
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="system_db",
        record_id="optimize",
        action="DB_OPTIMIZE",
        new_value=str(result.get("status") or "ok"),
    )
    db.commit()
    return result


@router.post('/foundation-example')
def create_foundation_example(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # FINMA-Hygiene (2026-06-15): Demo-/Foundation-Beispieldaten dürfen NIEMALS in einer
    # Produktionsumgebung erzeugt werden — sonst landen synthetische Datensätze zwischen
    # echten Kundendaten. In Produktion hart sperren.
    if str(getattr(settings, "app_env", "") or "").strip().lower() == "production":
        raise HTTPException(
            status_code=403,
            detail="Foundation-/Demo-Daten sind in der Produktionsumgebung gesperrt "
                   "(FINMA: keine synthetischen Datensätze zwischen echten Kundendaten).",
        )
    payload = upsert_foundation_example_case(db, current_user)
    # Sprint U-102 (2026-06-05): Foundation-Example erzeugt DB-Daten, muss auditiert sein.
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="foundation_example",
        record_id=str(payload.get("mandate_id") or payload.get("client_id") or "foundation_example"),
        action="FOUNDATION_EXAMPLE",
        new_value=str(payload.get("status") or "created"),
    )
    db.commit()
    return payload


@router.post('/foundation-example/purge')
def purge_foundation_example(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = purge_foundation_example_data(db)
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="foundation_example",
        record_id=",".join(result.get("client_ids") or []) or "foundation_example",
        action="FOUNDATION_PURGE",
        new_value=str({
            "status": result.get("status"),
            "deleted": result.get("deleted", {}),
        }),
    )
    db.commit()
    return result


@router.post('/clients/{client_id}/purge-demo')
def purge_demo_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = purge_demo_client_data(db, client_id)
    audit_log(
        db,
        user_id=current_user.id,
        user_name=getattr(current_user, "full_name", None) or getattr(current_user, "email", "admin"),
        table_name="foundation_example",
        record_id=client_id,
        action="FOUNDATION_PURGE",
        new_value=str({
            "status": result.get("status"),
            "deleted": result.get("deleted", {}),
        }),
    )
    db.commit()
    return result
