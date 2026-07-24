"""2026-07-24 (Security-Audit): cleanup_recommendation_runs() ohne Tenant-
Filter konnte ein tenant-gebundener (nicht super_admin) Admin
RecommendationRun/-Position-Zeilen FREMDER Tenants physisch loeschen --
kein Soft-Delete, kein Undo. Diese Tests pinnen den Fix: `current_user`
wird jetzt durchgereicht und beschraenkt Sicht+Loeschung auf den eigenen
Tenant, spiegelt exakt services.auth._apply_tenant_filter_to_client_query.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from models.clients import Client
from models.mandates import Mandate
from models.review import RecommendationPosition, RecommendationRun
from services.recommendation_run_cleanup import cleanup_recommendation_runs
from test_recommendation_run_cleanup import (  # noqa: F401
    _add_product,
    _add_run,
    _seed_admin_and_mandate,
)
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def _set_client_tenant(session_factory, mandate_id: str, tenant_id: str) -> None:
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        client = s.query(Client).filter(Client.id == mandate.client_id).first()
        client.tenant_id = tenant_id
        s.commit()


def _admin(tenant_id: str | None, role: str = "admin"):
    return SimpleNamespace(id=f"admin-{tenant_id or 'none'}", role=role, tenant_id=tenant_id)


def test_tenant_bound_admin_cannot_delete_foreign_tenant_runs(session_factory):
    admin_a_id, mid_a, pid_a = _seed_admin_and_mandate(session_factory, "tia-del-a")
    admin_b_id, mid_b, pid_b = _seed_admin_and_mandate(session_factory, "tia-del-b")
    _add_product(session_factory)
    _set_client_tenant(session_factory, mid_a, "firma-a")
    _set_client_tenant(session_factory, mid_b, "firma-b")

    _add_run(session_factory, mandate_id=mid_a, policy_id=pid_a,
             admin_id=admin_a_id, days_old=200, n_positions=2)
    _add_run(session_factory, mandate_id=mid_b, policy_id=pid_b,
             admin_id=admin_b_id, days_old=200, n_positions=3)

    with session_factory() as s:
        result = cleanup_recommendation_runs(s, current_user=_admin("firma-a"))
        s.commit()

    # Nur firma-a's Run wurde geloescht -- firma-b bleibt unberuehrt.
    assert result.deleted_runs == 1
    assert result.deleted_positions == 2

    with session_factory() as s:
        remaining_mandates = {
            row.mandate_id for row in s.query(RecommendationRun).all()
        }
        assert remaining_mandates == {mid_b}
        assert s.query(RecommendationPosition).count() == 3


def test_dry_run_count_also_scoped_to_tenant(session_factory):
    admin_a_id, mid_a, pid_a = _seed_admin_and_mandate(session_factory, "tia-dry-a")
    admin_b_id, mid_b, pid_b = _seed_admin_and_mandate(session_factory, "tia-dry-b")
    _add_product(session_factory)
    _set_client_tenant(session_factory, mid_a, "firma-a")
    _set_client_tenant(session_factory, mid_b, "firma-b")

    _add_run(session_factory, mandate_id=mid_a, policy_id=pid_a,
             admin_id=admin_a_id, days_old=200, n_positions=1)
    _add_run(session_factory, mandate_id=mid_b, policy_id=pid_b,
             admin_id=admin_b_id, days_old=200, n_positions=5)

    with session_factory() as s:
        result = cleanup_recommendation_runs(s, dry_run=True, current_user=_admin("firma-a"))

    # firma-a sieht/zaehlt NUR die eigene Run (nicht firma-b's 5 Positionen).
    assert result.deleted_runs == 1
    assert result.deleted_positions == 1

    with session_factory() as s:
        assert s.query(RecommendationRun).count() == 2  # nichts geloescht (dry_run)


def test_super_admin_sees_all_tenants(session_factory):
    admin_a_id, mid_a, pid_a = _seed_admin_and_mandate(session_factory, "tia-sa-a")
    admin_b_id, mid_b, pid_b = _seed_admin_and_mandate(session_factory, "tia-sa-b")
    _add_product(session_factory)
    _set_client_tenant(session_factory, mid_a, "firma-a")
    _set_client_tenant(session_factory, mid_b, "firma-b")

    _add_run(session_factory, mandate_id=mid_a, policy_id=pid_a,
             admin_id=admin_a_id, days_old=200, n_positions=1)
    _add_run(session_factory, mandate_id=mid_b, policy_id=pid_b,
             admin_id=admin_b_id, days_old=200, n_positions=1)

    with session_factory() as s:
        result = cleanup_recommendation_runs(
            s, dry_run=True, current_user=_admin(None, role="super_admin"),
        )
    assert result.deleted_runs == 2


def test_tenantless_legacy_admin_unaffected_backwards_compat(session_factory):
    """Tier1/Single-Tenant-Default (kein current_user oder tenant-loser
    Admin) -- unveraendertes Verhalten, kein Filter."""
    admin_id, mid, pid = _seed_admin_and_mandate(session_factory, "tia-legacy")
    _add_product(session_factory)
    _add_run(session_factory, mandate_id=mid, policy_id=pid,
             admin_id=admin_id, days_old=200, n_positions=1)

    with session_factory() as s:
        result_no_user = cleanup_recommendation_runs(s, dry_run=True)
    with session_factory() as s:
        result_tenantless_admin = cleanup_recommendation_runs(
            s, dry_run=True, current_user=_admin(None),
        )
    assert result_no_user.deleted_runs == result_tenantless_admin.deleted_runs == 1
