from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.users import User
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
