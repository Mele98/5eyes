"""Tenant quota enforcement.

Quotas are hard limits per tenant. ``NULL`` and ``0`` remain unlimited for
backwards compatibility with existing Tier-1 / legacy installations.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from services.tenant_context import is_postgres_bind

QuotaKind = Literal["users", "mandates"]


def _tenant_rows(db: Session, model, tid: str):
    """Aktive Zeilen eines Mandanten. KN-B (Lizenzzaehlung): Zeilen ohne
    ``tenant_id`` gehoeren zum Default-Mandanten -- dieselbe Regel wie ueberall
    sonst (``tenant_id or DEFAULT_TENANT_ID``, z. B. GET /tenants/me). Die
    Ersteinrichtung (Tier 1) legt den Admin ohne ``tenant_id`` an; ohne diese
    Regel zeigte die Lizenz bei zwei aktiven Konten ``current_users: 0``."""
    owner = model.tenant_id == tid
    if tid == DEFAULT_TENANT_ID:
        owner = or_(owner, model.tenant_id.is_(None))
    return db.query(model).filter(owner, model.deleted_at.is_(None))


def assert_within_quota(db: Session, tenant_id: str | None, kind: QuotaKind) -> None:
    """Raise HTTP 409 when creating ``kind`` would exceed the tenant quota."""
    tid = str(tenant_id or "").strip()
    if not tid:
        return
    # Kontrollrunde 2026-09-24: FOR UPDATE auf der Tenant-Zeile serialisiert
    # konkurrierende Aufrufe fuer denselben Tenant -- ohne diese Sperre
    # koennten zwei gleichzeitige Requests beide den COUNT() VOR dem Insert
    # des jeweils anderen lesen und beide die Pruefung bestehen, wodurch das
    # Quota-Limit um beliebig viele Eintraege ueberschritten werden kann
    # (identisches Race-Muster wie bereits an anderen Stellen in dieser
    # Codebase mit with_for_update() geschlossen, z.B. services/
    # tenant_crypto.py, routers/jurisdiction.py, routers/wealth.py). Auf
    # SQLite (Single-Writer, serialisiert) ist die Sperre wirkungslos aber
    # harmlos; is_postgres_bind() gated sie analog zum etablierten Muster.
    tenant_query = db.query(Tenant).filter(Tenant.id == tid, Tenant.deleted_at.is_(None))
    if is_postgres_bind(db):
        tenant_query = tenant_query.with_for_update()
    tenant = tenant_query.first()
    if tenant is None:
        # Kein Tenant-Datensatz fuer diesen tenant_id (z.B. Tier-1/Legacy-
        # Pfad ohne persistierte Tenant-Zeile) -- bleibt bewusst ein No-Op,
        # identisch zum bisherigen Verhalten. Verifiziert reachable/
        # legitim durch bestehende Tests (test_mandate_tenant_inheritance.py
        # u.a.), die einen Mandate/User mit tenant_id OHNE zugehoerige
        # Tenant-Zeile anlegen -- ein Fail-Closed hier wuerde diese
        # etablierte, unterstuetzte Konfiguration brechen.
        return
    if kind == "users":
        limit = _quota_limit(getattr(tenant, "max_users", None))
        if limit is None:
            return
        current = _tenant_rows(db, User, tid).count()
        _raise_if_at_limit("max_users", current, limit)
        return
    if kind == "mandates":
        limit = _quota_limit(getattr(tenant, "max_mandates", None))
        if limit is None:
            return
        current = _tenant_rows(db, Mandate, tid).count()
        _raise_if_at_limit("max_mandates", current, limit)
        return
    raise ValueError(f"Unknown quota kind: {kind!r}")


def compute_tenant_usage(db: Session, tenant_id: str | None) -> dict[str, int]:
    """Aktuelle Belegung (users/mandates) fuer die Soft-Limit-Warn-UI
    (Roadmap #24-Rest, 2026-08-09). Unabhaengig von assert_within_quota --
    wird auch gebraucht, wenn die Quota unlimitiert ist (NULL/0), um dem
    Firmen-Admin trotzdem die aktuelle Auslastung zu zeigen. Identische
    Zaehl-Logik wie assert_within_quota (bewusst dupliziert statt dort
    mitgezogen, um den Hot-Path der Enforcement-Funktion nicht mit einer
    zweiten, dort ungenutzten Zaehlung zu belasten)."""
    tid = str(tenant_id or "").strip()
    if not tid:
        return {"current_users": 0, "current_mandates": 0}
    current_users = _tenant_rows(db, User, tid).count()
    current_mandates = _tenant_rows(db, Mandate, tid).count()
    return {"current_users": current_users, "current_mandates": current_mandates}


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
