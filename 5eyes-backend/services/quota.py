"""Tenant quota enforcement.

Quotas are hard limits per tenant. ``NULL`` and ``0`` remain unlimited for
backwards compatibility with existing Tier-1 / legacy installations.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.tenant import Tenant
from models.users import User

QuotaKind = Literal["users", "mandates"]


def assert_within_quota(db: Session, tenant_id: str | None, kind: QuotaKind) -> None:
    """Raise HTTP 409 when creating ``kind`` would exceed the tenant quota."""
    tid = str(tenant_id or "").strip()
    if not tid:
        return
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tid, Tenant.deleted_at.is_(None))
        .first()
    )
    if tenant is None:
        return
    if kind == "users":
        limit = _quota_limit(getattr(tenant, "max_users", None))
        if limit is None:
            return
        current = (
            db.query(User)
            .filter(User.tenant_id == tid, User.deleted_at.is_(None))
            .count()
        )
        _raise_if_at_limit("max_users", current, limit)
        return
    if kind == "mandates":
        limit = _quota_limit(getattr(tenant, "max_mandates", None))
        if limit is None:
            return
        current = (
            db.query(Mandate)
            .filter(Mandate.tenant_id == tid, Mandate.deleted_at.is_(None))
            .count()
        )
        _raise_if_at_limit("max_mandates", current, limit)
        return
    raise ValueError(f"Unknown quota kind: {kind!r}")


def _quota_limit(value: object) -> int | None:
    try:
        limit = int(value or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def _raise_if_at_limit(name: str, current: int, limit: int) -> None:
    if current < limit:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Tenant-Quota {name} erreicht ({current}/{limit}).",
    )
