from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.review import AuditLog
from models.snapshots import AssetClassAnnualReturn
from models.users import User
from schemas.review import AuditLogEntry, AuditLogPage
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

router = APIRouter(prefix="/admin/system", tags=["System"])
AUDIT_LOG_VALID_ACTIONS = frozenset(
    {'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'EXPORT', 'PASSWORD_RESET'}
)


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
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    if offset < 0:
        offset = 0

    query = db.query(AuditLog)

    normalized_action = str(action or '').strip().upper()
    if normalized_action in AUDIT_LOG_VALID_ACTIONS:
        query = query.filter(AuditLog.action == normalized_action)

    query_text = str(q or '').strip()
    if query_text:
        pattern = f"%{query_text}%"
        query = query.filter(
            or_(
                AuditLog.user_name.ilike(pattern),
                AuditLog.table_name.ilike(pattern),
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
