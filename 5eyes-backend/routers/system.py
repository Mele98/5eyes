from datetime import datetime
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
from services.auth import require_admin
from services.foundation_example import upsert_foundation_example_case
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
    build_shadow_comparison_payload,
)

router = APIRouter(prefix="/admin/system", tags=["System"])
AUDIT_LOG_VALID_ACTIONS = frozenset(
    {'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'EXPORT', 'PASSWORD_RESET', 'OPTIMIZER_MODE_CHANGE'}
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
    _ = current_user

    query = db.query(AuditLog)

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


@router.post('/db/backup')
def backup_database(current_user: User = Depends(require_admin)):
    return create_backup()


@router.post('/support-bundle')
def create_support_bundle_endpoint(current_user: User = Depends(require_admin)):
    return create_support_bundle()


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
    _ = current_user
    try:
        return build_shadow_comparison_payload(db, mandate_id)
    except ShadowComparisonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ShadowComparisonMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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
        existing.return_bps = return_bps
        existing.source = source
        existing.updated_at = now
    else:
        db.add(AssetClassAnnualReturn(
            id=str(uuid4()), year=year, asset_class=asset_class,
            return_bps=return_bps, source=source, created_at=now, updated_at=now,
        ))
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


@router.post('/db/optimize')
def optimize_database(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return run_optimize(db)


@router.post('/foundation-example')
def create_foundation_example(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payload = upsert_foundation_example_case(db, current_user)
    db.commit()
    return payload
