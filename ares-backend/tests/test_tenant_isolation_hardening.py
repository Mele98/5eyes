"""#299-Security-Follow-ups (2026-07-09):

#4: ensure_postgres_rls_policies bricht in staging/production ab, wenn die App-DB-
    Rolle Superuser/BYPASSRLS ist (RLS waere sonst wirkungslos).
#5: Config verlangt strict_tenant_isolation=True in staging/production auf PostgreSQL
    (Multi-Tenant-App-Layer-Backstop).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

import services.postgres_rls as rls
from config import Settings

_STRONG_KEY = "a-strong-override-secret-key-1234567890"
_PG_URL = "postgresql://user:pw@localhost/db"


# --- #4: RLS-Rollen-Check ---------------------------------------------------

class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row
        self.queried = False

    def execute(self, *args, **kwargs):
        self.queried = True
        return _FakeResult(self._row)


def test_rls_role_check_raises_on_superuser_in_prod(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="RLS wirkungslos"):
        rls._assert_rls_effective_role(_FakeConn((True, False)))  # rolsuper=True


def test_rls_role_check_raises_on_bypassrls_in_staging(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_env", "staging")
    with pytest.raises(RuntimeError, match="RLS wirkungslos"):
        rls._assert_rls_effective_role(_FakeConn((False, True)))  # rolbypassrls=True


def test_rls_role_check_ok_for_unprivileged_role(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_env", "production")
    rls._assert_rls_effective_role(_FakeConn((False, False)))  # kein Raise


def test_rls_role_check_skipped_in_dev(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_env", "development")
    conn = _FakeConn((True, True))  # sogar Superuser+Bypass
    rls._assert_rls_effective_role(conn)  # kein Raise
    assert conn.queried is False, "in dev darf gar nicht erst abgefragt werden"


# --- #5: Config-Validator ---------------------------------------------------

def test_config_requires_strict_isolation_in_staging_postgres():
    with pytest.raises(ValueError, match="strict_tenant_isolation"):
        Settings(app_env="staging", database_url=_PG_URL,
                 secret_key=_STRONG_KEY, strict_tenant_isolation=False)


def test_config_ok_with_strict_isolation_on():
    s = Settings(app_env="staging", database_url=_PG_URL,
                 secret_key=_STRONG_KEY, strict_tenant_isolation=True)
    assert s.strict_tenant_isolation is True


def test_config_sqlite_dev_unaffected():
    # Tier-1 SQLite-Desktop (kein Postgres, dev) darf ohne strict laufen.
    s = Settings(app_env="development", strict_tenant_isolation=False)
    assert s.strict_tenant_isolation is False
