"""Test helper: write LEGACY wealth-inflow links that the database now refuses.

PG-002 (tenant database boundary): new writes of a dangling or foreign-client
``wealth_inflows.linked_position_id`` are rejected by triggers. Older desktop
databases can still contain such rows (the runtime patch reports, but never
rewrites them), so read paths must stay fail-closed for them. Tests that
model that legacy state drop the link-guard triggers for the duration of the
block (SQLite only) and restore them afterwards.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text

from services.wealth_tenant_boundary import WEALTH_INFLOW_SQLITE_TRIGGERS

_LINK_GUARDS = tuple(ddl for ddl in WEALTH_INFLOW_SQLITE_TRIGGERS if "link_guard" in ddl)


def _name(ddl: str) -> str:
    return ddl.split("IF NOT EXISTS", 1)[1].split()[0]


@contextmanager
def legacy_link_guards_disabled(session):
    for ddl in _LINK_GUARDS:
        session.execute(text(f"DROP TRIGGER IF EXISTS {_name(ddl)}"))
    try:
        yield
    finally:
        session.rollback()
        for ddl in _LINK_GUARDS:
            session.execute(text(ddl))
        session.commit()
