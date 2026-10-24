"""rls-1 (2026-07-19): effektive strikte Mandanten-Trennung wird aus Tier/Modus
abgeleitet, damit ein Tier-2-/Multi-Tenant-Deployment nie versehentlich ohne
Strict-Isolation laeuft. Tier1/single bleibt unveraendert.

Verifiziert audit-finding rls-1: die 3 Lesestellen in services/auth.py lesen
nicht mehr den rohen Flag, sondern _effective_strict_tenant_isolation(settings).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.auth import _effective_strict_tenant_isolation  # noqa: E402


def _settings(**kw):
    base = {"strict_tenant_isolation": False, "deployment_tier": "tier1", "tenancy_mode": "single"}
    base.update(kw)
    return SimpleNamespace(**base)


def test_tier1_single_default_not_strict():
    assert _effective_strict_tenant_isolation(_settings()) is False


def test_raw_flag_true_is_strict():
    assert _effective_strict_tenant_isolation(_settings(strict_tenant_isolation=True)) is True


def test_tier2_derives_strict_even_if_flag_false():
    assert _effective_strict_tenant_isolation(_settings(deployment_tier="tier2")) is True


def test_tenancy_multi_derives_strict_even_if_flag_false():
    assert _effective_strict_tenant_isolation(_settings(tenancy_mode="multi")) is True


def test_tier3_single_not_strict():
    # Tier 3 = dedicated single-tenant -> keine erzwungene Strict-Isolation.
    assert _effective_strict_tenant_isolation(_settings(deployment_tier="tier3")) is False


def test_case_and_whitespace_robust():
    assert _effective_strict_tenant_isolation(_settings(deployment_tier=" TIER2 ")) is True
    assert _effective_strict_tenant_isolation(_settings(tenancy_mode="MULTI")) is True


def test_missing_attrs_defaults_false():
    assert _effective_strict_tenant_isolation(SimpleNamespace()) is False
