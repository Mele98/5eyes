"""Connection-scoped tenant context for PostgreSQL RLS.

SQLite remains the default/self-hosted path and treats these helpers as no-ops
apart from recording the intended tenant in ``Session.info`` for tests and
diagnostics. PostgreSQL stores the tenant in GUCs read by RLS policies.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


TENANT_GUC = "app.tenant_id"
BYPASS_GUC = "app.rls_bypass"


def is_postgres_bind(bind) -> bool:
    """Return True when a SQLAlchemy bind/session is backed by PostgreSQL."""

    dialect = getattr(bind, "dialect", None)
    if dialect is None and hasattr(bind, "get_bind"):
        dialect = getattr(bind.get_bind(), "dialect", None)
    return str(getattr(dialect, "name", "")).startswith("postgresql")


def _reset_dbapi_context(dbapi_connection) -> None:
    """Run the GUC resets and close the implicit transaction they open.

    TENANT-CONTEXT-IDLE-IN-TRANSACTION-001 (Kontrollrunde 2026-09-25): diese
    Funktion laeuft direkt auf dem rohen DBAPI-Connection-Objekt (Pool-
    Events, nicht die SQLAlchemy-Session) -- der Treiber steht dort per
    Default NICHT im Autocommit-Modus. Jedes `cursor.execute(...)` startet
    also implizit eine neue Transaktion. Ohne explizites commit()/rollback()
    blieb diese Transaktion offen: beim `checkout`-Event lief die naechste
    Session einfach in die bereits offene Transaktion hinein (meist
    unbemerkt, da die Session i.d.R. selbst bald committet), aber beim
    `checkin`-Event -- wenn die Verbindung NICHT weiterverwendet, sondern
    einfach in den Pool zurueckgelegt wird -- blieb die Verbindung auf
    Postgres-Seite dauerhaft "idle in transaction" (sichtbar in
    pg_stat_activity), obwohl SQLAlchemy sie bereits als frei/verfuegbar
    fuehrte. Bei Verbindungspools mit vielen selten genutzten Connections
    haelt das unnoetig lange den Autovacuum-xmin-Horizont fest und kann bei
    einem konfigurierten idle_in_transaction_session_timeout zum
    unerwarteten Verbindungsabbruch fuehren. Fix: die Reset-Transaktion wird
    hier sofort geschlossen, damit die Verbindung im Pool tatsaechlich idle
    (nicht idle-in-transaction) ist.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"RESET {TENANT_GUC}")
        cursor.execute(f"RESET {BYPASS_GUC}")
    finally:
        cursor.close()
    dbapi_connection.commit()


def attach_tenant_context_reset(target_engine: Engine) -> None:
    """Reset tenant/bypass GUCs whenever a PostgreSQL connection is reused."""

    if not is_postgres_bind(target_engine):
        return

    marker = "_5eyes_tenant_context_reset_attached"
    if getattr(target_engine, marker, False):
        return
    setattr(target_engine, marker, True)

    @event.listens_for(target_engine, "checkout")
    def _reset_on_checkout(dbapi_connection, connection_record, connection_proxy):
        _ = connection_record, connection_proxy
        _reset_dbapi_context(dbapi_connection)

    @event.listens_for(target_engine, "checkin")
    def _reset_on_checkin(dbapi_connection, connection_record):
        _ = connection_record
        if dbapi_connection is not None:
            _reset_dbapi_context(dbapi_connection)


def set_tenant_context(session: Session, tenant_id: str | None) -> None:
    """Set the effective tenant for all subsequent SQL on this session."""

    cleaned = str(tenant_id or "").strip()
    session.info["tenant_id"] = cleaned or None
    if not is_postgres_bind(session):
        return
    session.execute(
        text("SELECT set_config(:name, :value, false)"),
        {"name": TENANT_GUC, "value": cleaned},
    )
    session.execute(
        text("SELECT set_config(:name, 'off', false)"),
        {"name": BYPASS_GUC},
    )


def reset_tenant_context(session: Session) -> None:
    """Clear tenant and operator-bypass context on a SQLAlchemy session."""

    session.info.pop("tenant_id", None)
    session.info.pop("rls_bypass", None)
    if not is_postgres_bind(session):
        return
    session.execute(text(f"RESET {TENANT_GUC}"))
    session.execute(text(f"RESET {BYPASS_GUC}"))


def set_operator_bypass(session: Session, enabled: bool) -> None:
    """Enable/disable explicit operator bypass for RLS-protected maintenance.

    Normal ``super_admin`` request handling does not call this. It exists for
    intentionally marked operator jobs/tests only and is reset on pool reuse.
    """

    session.info["rls_bypass"] = bool(enabled)
    if not is_postgres_bind(session):
        return
    session.execute(
        text("SELECT set_config(:name, :value, false)"),
        {"name": BYPASS_GUC, "value": "on" if enabled else "off"},
    )


@contextmanager
def operator_bypass(session: Session) -> Iterator[None]:
    """Temporarily mark a PostgreSQL session as an explicit operator query."""

    previous = bool(session.info.get("rls_bypass"))
    set_operator_bypass(session, True)
    try:
        yield
    finally:
        set_operator_bypass(session, previous)
