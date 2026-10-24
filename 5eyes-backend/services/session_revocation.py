"""AF-6 (AUDIT-FIX, 2026-10-23): Widerrufs-Untergrenzen und Massenwiderruf.

Zwei Quellen fuer "alles, was vor Zeitpunkt T ausgestellt wurde, ist
ungueltig":

1. je Benutzer: ``users.token_revoked_before`` (bestehend, AUTH-04 --
   Logout, Passwortwechsel, Mandantenwechsel).
2. global: ``settings.token_revoked_before`` (Env ``TOKEN_REVOKED_BEFORE``),
   wirkt ohne DB-Schreibzugriff fuer alle Benutzer.

Die effektive Untergrenze ist das Maximum beider. Sie gilt fuer Access-
Tokens (``iat``) UND Refresh-Tokens (``refresh_tokens.created_at``).

``revoke_all_sessions`` ist der Massenwiderruf (global oder je Mandant):
setzt ``token_revoked_before`` fuer alle betroffenen Benutzer, revoziert
alle aktiven Refresh-Tokens (Zeilen bleiben fuer die Reuse-Detection
erhalten) und schreibt einen Audit-Eintrag. Commit macht der Aufrufer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from config import settings
from models.refresh_token import RefreshToken
from models.users import User


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso_ts(value) -> Optional[float]:
    """ISO-Zeitstempel (mit/ohne 'Z', mit/ohne Offset) -> Epoch-Sekunden.
    None bei leerem/unlesbarem Wert (der Auth-Pfad darf nicht crashen)."""
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def global_revoked_before_ts() -> Optional[float]:
    return parse_iso_ts(getattr(settings, "token_revoked_before", None))


def effective_revoked_before_ts(user: User | None) -> Optional[float]:
    """Maximum aus globaler und benutzerbezogener Untergrenze (None = keine)."""
    candidates = [global_revoked_before_ts()]
    if user is not None:
        candidates.append(parse_iso_ts(getattr(user, "token_revoked_before", None)))
    present = [c for c in candidates if c is not None]
    return max(present) if present else None


@dataclass(frozen=True)
class MassRevocationResult:
    revoked_before: str
    scope: str
    tenant_id: Optional[str]
    users: int
    refresh_tokens: int


def revoke_all_sessions(
    db: Session,
    *,
    actor_user_id: str,
    actor_name: str,
    tenant_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> MassRevocationResult:
    """Massenwiderruf. ``tenant_id=None`` = global (alle Mandanten; nur fuer
    Betreiberpfade wie die CLI -- auf PostgreSQL unter explizitem
    Operator-Bypass). Mit ``tenant_id`` nur Benutzer dieses Mandanten;
    Benutzer ohne tenant_id zaehlen zum Default-Mandanten (wie beim Login).
    """
    from models.tenant import DEFAULT_TENANT_ID
    from services.audit import log
    from services.tenant_context import operator_bypass

    now = _now_iso()
    tid = str(tenant_id or "").strip() or None

    def _apply() -> MassRevocationResult:
        user_filter = []
        if tid is not None:
            if tid == DEFAULT_TENANT_ID:
                user_filter.append(or_(User.tenant_id == tid, User.tenant_id.is_(None)))
            else:
                user_filter.append(User.tenant_id == tid)
        user_ids = select(User.id).where(*user_filter)
        users_updated = db.execute(
            update(User)
            .where(*user_filter)
            .values(token_revoked_before=now, updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount or 0
        refresh_updated = db.execute(
            update(RefreshToken)
            .where(RefreshToken.revoked_at.is_(None), RefreshToken.user_id.in_(user_ids))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount or 0
        result = MassRevocationResult(
            revoked_before=now,
            scope="tenant" if tid is not None else "global",
            tenant_id=tid,
            users=int(users_updated),
            refresh_tokens=int(refresh_updated),
        )
        # audit_log.action ist ein festes ENUM -> 'UPDATE' auf users, Details
        # als JSON im new_value (keine Schema-Aenderung noetig).
        log(
            db,
            user_id=actor_user_id,
            user_name=actor_name,
            table_name="users",
            record_id=tid or "*",
            action="UPDATE",
            field_name="token_revoked_before",
            new_value=json.dumps({
                "scope": result.scope,
                "tenant_id": tid,
                "revoked_before": now,
                "users": result.users,
                "refresh_tokens": result.refresh_tokens,
            }, sort_keys=True),
            ip_address=ip_address,
            tenant_id=tid,
        )
        return result

    if tid is None:
        with operator_bypass(db):
            outcome = _apply()
    else:
        outcome = _apply()
    # Identity-Map nachziehen (Core-UPDATE aktualisiert geladene Objekte nicht).
    db.expire_all()
    return outcome
