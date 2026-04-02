from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.review import AuditLog
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
