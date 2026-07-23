"""SEC-2 (Audit 2026-06-24, Ops/Security): _assert_user_visible_to und update_user
gaben JEDEM tenant-losen Firmen-Admin (utid == "") unrestricted Sicht auf ALLE
User quer durch alle Tenants -- der Guard war fuer genau den Fall gedacht, den
er nicht abdeckte. Fix (2026-07-23): im effektiv strikten/Multi-Tenant-Kontext
(_effective_strict_tenant_isolation, z.B. Tier2/Shared-Cloud) wird ein
tenant-loser Admin als restricted behandelt (sieht nur andere tenant-lose
User), NICHT mehr global. Tier1/Single-Tenant-BC (Default) bleibt unveraendert.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config as config_mod  # noqa: E402
from models.users import User  # noqa: E402
from routers.auth import _assert_user_visible_to  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _user(uid, tenant_id, role="admin"):
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid, role=role,
        is_active=1, tenant_id=tenant_id, created_at=_now(), updated_at=_now(),
    )


def test_tenantless_admin_sees_everyone_in_default_single_tenant_bc(monkeypatch):
    """Default (Tier1/single, non-strict): unveraenderte Legacy-Behavior."""
    monkeypatch.setattr(config_mod.settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(config_mod.settings, "deployment_tier", "tier1", raising=False)
    monkeypatch.setattr(config_mod.settings, "strict_tenant_isolation", False, raising=False)
    admin = _user("admin-legacy", tenant_id=None)
    foreign_user = _user("user-foreign", tenant_id="firma-b", role="advisor")
    # Darf nicht raisen (BC: tenant-loser Admin bleibt unrestricted in Tier1).
    _assert_user_visible_to(admin, foreign_user)


def test_tenantless_admin_restricted_in_multi_tenant_mode(monkeypatch):
    """Tenancy-Mode multi (Tier2/Shared-Cloud): tenant-loser Admin ist ein
    Konfigurationsfehler und darf NICHT quer durch alle Tenants sehen."""
    monkeypatch.setattr(config_mod.settings, "tenancy_mode", "multi", raising=False)
    monkeypatch.setattr(config_mod.settings, "deployment_tier", "tier2", raising=False)
    monkeypatch.setattr(config_mod.settings, "strict_tenant_isolation", False, raising=False)
    admin = _user("admin-tenantless", tenant_id=None)
    foreign_user = _user("user-foreign2", tenant_id="firma-b", role="advisor")
    with pytest.raises(HTTPException) as exc:
        _assert_user_visible_to(admin, foreign_user)
    assert exc.value.status_code == 404


def test_tenantless_admin_can_still_see_other_tenantless_users_in_multi_mode(monkeypatch):
    """Auch im Multi-Modus: zwei tenant-lose Rows bleiben zueinander sichtbar
    (kein Vollstop, nur keine Cross-Tenant-Sicht)."""
    monkeypatch.setattr(config_mod.settings, "tenancy_mode", "multi", raising=False)
    admin = _user("admin-tenantless2", tenant_id=None)
    also_tenantless = _user("user-tenantless", tenant_id=None, role="advisor")
    _assert_user_visible_to(admin, also_tenantless)  # darf nicht raisen


def test_super_admin_always_sees_everyone(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "tenancy_mode", "multi", raising=False)
    sa = _user("super", tenant_id=None, role="super_admin")
    foreign_user = _user("user-foreign3", tenant_id="firma-c", role="advisor")
    _assert_user_visible_to(sa, foreign_user)  # darf nicht raisen
