"""Sprint T3 (2026-06-08): Repository-Layer Tenant-Scoping + Cross-Leak-Tests.

KRITISCH fuer Tier 2 (Shared-Cloud): Berater aus Firma A darf NIE Daten von
Firma B sehen. Diese Tests sind der Sicherheits-Anker.

# Test-Familien
1. Helper _apply_tenant_filter_to_client_query
2. get_client_for_user_or_404 mit Tenant-Filter
3. get_mandate_for_user_or_404 mit Tenant-Filter
4. get_accessible_client_ids / get_accessible_mandate_ids
5. Backwards-Compat: Legacy-User ohne tenant_id

# Sicherheits-Invariante
User mit tenant_id='A' darf NUR sehen:
- Daten mit tenant_id='A'
- Daten mit tenant_id=NULL (Pre-T1-Migration-Pfad)

User mit tenant_id='A' darf NIE sehen:
- Daten mit tenant_id='B' (Cross-Tenant-Leak)
- Daten mit tenant_id='' (sollte nicht existieren, defensive)
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.auth import (
    get_accessible_client_ids,
    get_accessible_mandate_ids,
    get_client_for_user_or_404,
    get_mandate_for_user_or_404,
)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_scoping.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_user(uid: str, tenant_id: str | None, role: str = "advisor") -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid,
        role=role, is_active=1, tenant_id=tenant_id,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )


def _make_client(cid: str, advisor_id: str, tenant_id: str | None) -> Client:
    return Client(
        id=cid, client_number=cid,
        first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id,
        household_type="Einzelperson", client_classification="Privatkunde",
        country_of_residence="CH", language="DE",
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )


def _make_mandate(mid: str, client_id: str, tenant_id: str | None) -> Mandate:
    now = _utc_now_iso()
    return Mandate(
        id=mid, mandate_number=mid, client_id=client_id, tenant_id=tenant_id,
        mandate_type="Anlageberatung", status="Aktiv",
        base_currency="CHF", advisory_language="DE",
        opened_at=now, created_at=now, updated_at=now,
    )


# ===========================================================================
# 1. Cross-Tenant-Leak-Tests fuer Clients
# ===========================================================================


def test_cross_tenant_leak_client_geblockt(session_factory):
    """Berater A (tenant='firm-A') darf Client von Berater B (tenant='firm-B')
    NICHT sehen — auch wenn er die client_id raet."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        user_b = _make_user("u-b", tenant_id="firm-B")
        client_b = _make_client("c-b", advisor_id="u-b", tenant_id="firm-B")
        db.add_all([user_a, user_b, client_b])
        db.commit()
        # User A versucht Client B zu sehen
        with pytest.raises(HTTPException) as exc:
            get_client_for_user_or_404("c-b", db, user_a)
        assert exc.value.status_code == 404


def test_same_tenant_client_sichtbar(session_factory):
    """User A mit tenant='firm-A' sieht Clients seines Tenants."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        # Client seines Tenants, sein Advisor
        client_a = _make_client("c-a", advisor_id="u-a", tenant_id="firm-A")
        db.add_all([user_a, client_a])
        db.commit()
        client = get_client_for_user_or_404("c-a", db, user_a)
        assert client.id == "c-a"


def test_legacy_user_ohne_tenant_id_sieht_alle_seine_clients(session_factory):
    """Backwards-Compat: User ohne tenant_id sieht seine Clients
    unabhaengig von deren tenant_id (Pre-T1-Pfad)."""
    with session_factory() as db:
        legacy_user = _make_user("u-legacy", tenant_id=None)
        # Client mit tenant_id='firm-X' und Pre-T1-Client mit NULL
        c1 = _make_client("c1", advisor_id="u-legacy", tenant_id="firm-X")
        c2 = _make_client("c2", advisor_id="u-legacy", tenant_id=None)
        db.add_all([legacy_user, c1, c2])
        db.commit()
        # Beide sichtbar (kein Tenant-Filter angewendet)
        assert get_client_for_user_or_404("c1", db, legacy_user).id == "c1"
        assert get_client_for_user_or_404("c2", db, legacy_user).id == "c2"


def test_user_mit_tenant_sieht_auch_null_clients_migration_path(session_factory):
    """User mit tenant_id sieht Pre-T1-Daten (Client.tenant_id IS NULL).
    Wichtig fuer Migration: bestehende Daten ohne tenant_id muessen lesbar bleiben."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        # Client ohne tenant_id (Pre-T1)
        c_legacy = _make_client("c-leg", advisor_id="u-a", tenant_id=None)
        db.add_all([user_a, c_legacy])
        db.commit()
        client = get_client_for_user_or_404("c-leg", db, user_a)
        assert client.id == "c-leg"


# ===========================================================================
# 2. Cross-Tenant-Leak-Tests fuer Mandates
# ===========================================================================


def test_cross_tenant_leak_mandate_geblockt(session_factory):
    """User A darf Mandate von Tenant B NICHT sehen."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        user_b = _make_user("u-b", tenant_id="firm-B")
        client_b = _make_client("c-b", advisor_id="u-b", tenant_id="firm-B")
        mandate_b = _make_mandate("m-b", client_id="c-b", tenant_id="firm-B")
        db.add_all([user_a, user_b, client_b, mandate_b])
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_mandate_for_user_or_404("m-b", db, user_a)
        assert exc.value.status_code == 404


def test_same_tenant_mandate_sichtbar(session_factory):
    """User A mit tenant='firm-A' sieht Mandate seines Tenants."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        client_a = _make_client("c-a", advisor_id="u-a", tenant_id="firm-A")
        mandate_a = _make_mandate("m-a", client_id="c-a", tenant_id="firm-A")
        db.add_all([user_a, client_a, mandate_a])
        db.commit()
        m = get_mandate_for_user_or_404("m-a", db, user_a)
        assert m.id == "m-a"


def test_user_tenant_a_sieht_legacy_null_mandate(session_factory):
    """User mit Tenant A sieht Mandate mit tenant_id=NULL (Pre-T1 Migration)."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        client_a = _make_client("c-a", advisor_id="u-a", tenant_id="firm-A")
        legacy_mandate = _make_mandate("m-leg", client_id="c-a", tenant_id=None)
        db.add_all([user_a, client_a, legacy_mandate])
        db.commit()
        m = get_mandate_for_user_or_404("m-leg", db, user_a)
        assert m.id == "m-leg"


# ===========================================================================
# 3. get_accessible_client_ids / get_accessible_mandate_ids
# ===========================================================================


def test_accessible_client_ids_scoped(session_factory):
    """User A bekommt nur Client-IDs seines Tenants."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        c_own = _make_client("c-own", advisor_id="u-a", tenant_id="firm-A")
        c_legacy = _make_client("c-legacy", advisor_id="u-a", tenant_id=None)
        # Andere Tenant-Daten (existieren aber nicht von u-a beraten):
        # nicht relevant, weil advisor_id Filter schon greift.
        db.add_all([user_a, c_own, c_legacy])
        db.commit()
        ids = set(get_accessible_client_ids(db, user_a))
        assert ids == {"c-own", "c-legacy"}


def test_accessible_mandate_ids_scoped(session_factory):
    """User A bekommt nur Mandate-IDs seines Tenants."""
    with session_factory() as db:
        user_a = _make_user("u-a", tenant_id="firm-A")
        c_a = _make_client("c-a", advisor_id="u-a", tenant_id="firm-A")
        m_own = _make_mandate("m-own", client_id="c-a", tenant_id="firm-A")
        m_legacy = _make_mandate("m-legacy", client_id="c-a", tenant_id=None)
        db.add_all([user_a, c_a, m_own, m_legacy])
        db.commit()
        ids = set(get_accessible_mandate_ids(db, user_a))
        assert ids == {"m-own", "m-legacy"}


# ===========================================================================
# 4. Admin sieht alles (has_global_client_access)
# ===========================================================================


def test_admin_sieht_alle_clients_aller_tenants(session_factory):
    """Admin-Role hat global access — Tenant-Filter angewendet aber advisor_id-
    Filter nicht (siehe has_global_client_access).

    HINWEIS: In Tier 2 ist ein Admin pro Tenant; ein 'Super-Admin' fuer
    Cross-Tenant existiert nur in der T4-Admin-API.
    """
    with session_factory() as db:
        admin = _make_user("admin", tenant_id="firm-A", role="admin")
        c_own_a = _make_client("c-own-a", advisor_id="u-other", tenant_id="firm-A")
        c_other_tenant = _make_client(
            "c-other-tenant", advisor_id="u-other", tenant_id="firm-B",
        )
        db.add_all([admin, c_own_a, c_other_tenant])
        db.commit()
        # Admin sieht seinen Tenant-A Client (kein advisor-Filter)
        client = get_client_for_user_or_404("c-own-a", db, admin)
        assert client.id == "c-own-a"
        # Aber NICHT cross-tenant (Tenant-Filter greift)
        with pytest.raises(HTTPException):
            get_client_for_user_or_404("c-other-tenant", db, admin)


# ===========================================================================
# 5. Edge-Cases
# ===========================================================================


def test_user_mit_leerem_tenant_string_wie_legacy(session_factory):
    """User mit tenant_id='   ' (whitespace) wird als Legacy behandelt."""
    with session_factory() as db:
        user = _make_user("u-empty", tenant_id="   ")
        c_a = _make_client("c-a", advisor_id="u-empty", tenant_id="firm-A")
        c_b = _make_client("c-b", advisor_id="u-empty", tenant_id="firm-B")
        db.add_all([user, c_a, c_b])
        db.commit()
        # Beide sichtbar (Legacy-Pfad)
        ids = set(get_accessible_client_ids(db, user))
        assert ids == {"c-a", "c-b"}


# ===========================================================================
# 6. TEN-COMP-001 (Codex-Audit 2026-08-27): tenant-loser GLOBALER Zugriff
# muss im Strict-Modus fail-closed sein, nicht fail-open. Die urspruengliche
# Audit-Reproduktion nutzte genau einen Admin (has_global_client_access=True)
# ohne tenant_id -- vorher wurde in diesem Fall VOR dem Strict-Check "kein
# Filter" (= Vollzugriff auf jeden Tenant) zurueckgegeben.
# ===========================================================================


def test_admin_ohne_tenant_id_wird_im_strict_modus_bei_client_geblockt(session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        admin = _make_user("admin-notenant", tenant_id=None, role="admin")
        foreign_client = _make_client("c-foreign", advisor_id="u-other", tenant_id="firm-B")
        db.add_all([admin, foreign_client])
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_client_for_user_or_404("c-foreign", db, admin)
        assert exc.value.status_code == 404


def test_admin_ohne_tenant_id_wird_im_strict_modus_bei_mandate_geblockt(session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        admin = _make_user("admin-notenant2", tenant_id=None, role="admin")
        foreign_client = _make_client("c-foreign2", advisor_id="u-other", tenant_id="firm-B")
        foreign_mandate = _make_mandate("m-foreign", client_id="c-foreign2", tenant_id="firm-B")
        db.add_all([admin, foreign_client, foreign_mandate])
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_mandate_for_user_or_404("m-foreign", db, admin)
        assert exc.value.status_code == 404


def test_admin_ohne_tenant_id_bekommt_leere_accessible_ids_im_strict_modus(session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        admin = _make_user("admin-notenant3", tenant_id=None, role="admin")
        other_client = _make_client("c-other", advisor_id="u-other", tenant_id="firm-B")
        db.add_all([admin, other_client])
        db.commit()
        assert get_accessible_client_ids(db, admin) == []


def test_legacy_advisor_ohne_tenant_id_bleibt_auch_im_strict_modus_unveraendert(session_factory, monkeypatch):
    """Regressionsschutz: ein REGULAERER Berater (kein globaler Zugriff) ohne
    tenant_id ist bereits durch den advisor_id-Filter sicher begrenzt -- die
    is_global_access-Unterscheidung darf sein Verhalten NICHT aendern, auch
    nicht im Strict-Modus (sonst waere Holgers reales Tier-1-Deployment
    betroffen, falls dort je strict_tenant_isolation gesetzt wuerde)."""
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        advisor = _make_user("adv-notenant", tenant_id=None, role="advisor")
        own_client = _make_client("c-own", advisor_id="adv-notenant", tenant_id=None)
        db.add_all([advisor, own_client])
        db.commit()
        client = get_client_for_user_or_404("c-own", db, advisor)
        assert client.id == "c-own"


def test_super_admin_role_treated_as_global_access_helper_unchanged():
    """Dokumentiert die bestehende has_global_client_access()-Semantik
    (role=='admin' -> global) bleibt durch diesen Fix unangetastet -- siehe
    PR-Beschreibung: die Verengung auf super_admin ist bewusst NICHT Teil
    dieses Fixes (separates, groesseres Vorhaben)."""
    from services.auth import has_global_client_access
    admin = _make_user("plain-admin", tenant_id=None, role="admin")
    assert has_global_client_access(admin) is True
