"""KN-B / Nebenbefund Lizenzzaehlung (Dok. 117): ``current_users: 0`` bei zwei Konten.

Ursache: Die Ersteinrichtung (Tier 1, Desktop) legt den Admin ohne
``tenant_id`` an, eingeladene Konten erben diese (NULL). GET /tenants/me nimmt
den Default-Mandanten (``tenant_id or DEFAULT_TENANT_ID``), die Zaehlung filterte
aber nur ``tenant_id == 'main'`` und fand deshalb niemanden.

Jetzt zaehlen Zeilen ohne ``tenant_id`` zum Default-Mandanten (gleiche Regel wie
ueberall). Fremde Mandanten zaehlen weiter nicht mit.

Gegenprobe: ``_tenant_rows`` ohne NULL-Zweig -> rot.
"""
from __future__ import annotations

from models.mandates import Mandate
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from services.quota import compute_tenant_usage
from tests.test_tenant_me_usage_soft_limit import (  # noqa: F401
    _login_as,
    _logout,
    _now,
    client,
    session_factory,
)


def _seed(db):
    now = _now()
    if db.get(Tenant, DEFAULT_TENANT_ID) is None:
        db.add(Tenant(id=DEFAULT_TENANT_ID, display_name="Testfirma Fiktiv", slug="main", hosting_tier="tier1",
                      license_status="active", max_users=1, is_active=1, created_at=now, updated_at=now))
    # Ersteinrichtung + eingeladene externe Pruefperson: beide ohne tenant_id.
    for uid, role in (("admin-boot", "admin"), ("ext-review", "compliance_reviewer")):
        db.add(User(id=uid, username=uid, password_hash="h", full_name=uid, role=role, is_active=1,
                    tenant_id=None, created_at=now, updated_at=now))
    db.add(User(id="gone", username="gone", password_hash="h", full_name="gone", role="advisor", is_active=0,
                tenant_id=None, created_at=now, updated_at=now, deleted_at=now))
    db.add(Tenant(id="other-firm", display_name="Andere", slug="other-firm", hosting_tier="tier2",
                  license_status="active", is_active=1, created_at=now, updated_at=now))
    db.add(User(id="other-user", username="other-user", password_hash="h", full_name="o", role="advisor",
                is_active=1, tenant_id="other-firm", created_at=now, updated_at=now))
    db.commit()


def test_default_tenant_counts_accounts_without_tenant_id(session_factory):
    with session_factory() as db:
        _seed(db)
        assert compute_tenant_usage(db, DEFAULT_TENANT_ID)["current_users"] == 2
        assert compute_tenant_usage(db, "other-firm")["current_users"] == 1


def test_tenants_me_reports_both_accounts(client, session_factory):
    with session_factory() as db:
        _seed(db)
    _login_as("admin-boot", "admin", tenant_id=None)
    try:
        body = client.get("/tenants/me").json()
        assert body["current_users"] == 2, body
        assert body["max_users"] == 1
    finally:
        _logout()


def test_mandates_without_tenant_count_for_default_tenant(session_factory):
    with session_factory() as db:
        _seed(db)
        db.add(Mandate(id="m-null", client_id="c-null", mandate_number="M-NULL", tenant_id=None,
                       mandate_type="Anlageberatung", opened_at="2026-11-19", created_at=_now(), updated_at=_now()))
        db.commit()
        assert compute_tenant_usage(db, DEFAULT_TENANT_ID)["current_mandates"] == 1
        assert compute_tenant_usage(db, "other-firm")["current_mandates"] == 0
