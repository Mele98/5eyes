"""Live-Smoketest-Fund (2026-08-09): dieselbe Bugklasse wie in
test_contract_documents_fresh_bootstrap_schema_drift.py und
test_foundation_example_fresh_bootstrap_schema_drift.py -- gefunden waehrend
eines Live-Playwright-Tests des FINIG-Gate-Features.

Der rohe Bootstrap-Schema-CHECK-Constraint fuer users.role
(5eyes_schema_v4.0_FINAL.sql, von init_db() bei JEDER echten Erstinstallation
ausgefuehrt) erlaubte bisher nur ('admin', 'advisor', 'readonly') -- die
Rollen 'super_admin' (Tenant-Provisioning/Operator-Panel, services/auth.py),
'portfolio_management' (CMA-Freigabe, routers/jurisdiction.py) und 'client'
(Client-Portal-Login, routers/clients.py::create_client_login) sind aber
laengst aktiver Anwendungscode und werden an vielen Stellen geprueft. Auf
JEDER frischen Installation war es dadurch strukturell unmoeglich, einen
super_admin-User anzulegen -- das GESAMTE Tenant-Provisioning-/Multi-Firmen-
Lizenzierungsfeature (Kernanliegen dieser Session) war ab Werk unbenutzbar.
Unbemerkt, weil kein Test gegen den Raw-SQL-Bootstrap-Pfad lief (users.role
ist im SQLAlchemy-Modell eine ungeprüfte String-Spalte ohne CHECK-Constraint,
siehe models/users.py:19).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401,E501
configure_mappers()


@pytest.fixture()
def fresh_bootstrap_session(tmp_path, monkeypatch):
    import database as db_module
    from config import settings

    db_path = tmp_path / "fresh_user_role.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(settings, "db_path", str(db_path))
    # init_db() repliziert exakt den Boot-Pfad einer echten Erstinstallation
    # (Raw-SQL-Bootstrap mit CHECK-Constraints -> create_all()-Supplement ->
    # alle ensure_*/migrate_*-Schritte in derselben Reihenfolge wie main.py).
    db_module.init_db()

    TestSession = sessionmaker(bind=test_engine)
    with TestSession() as session:
        yield session


@pytest.mark.parametrize("role", ["admin", "advisor", "readonly", "super_admin", "portfolio_management", "client"])
def test_fresh_bootstrap_accepts_every_role_used_by_application_code(fresh_bootstrap_session, role):
    from models.users import User

    now = "2026-08-09T00:00:00.000Z"
    user = User(
        id=f"user-role-{role}", username=f"user-role-{role}", password_hash="x",
        full_name="Role Drift Test", role=role, is_active=1,
        created_at=now, updated_at=now,
    )
    fresh_bootstrap_session.add(user)
    # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen --
    # sonst ist diese Rolle auf einer echten Erstinstallation strukturell
    # unerreichbar, egal was der Anwendungscode vorsieht.
    fresh_bootstrap_session.commit()

    stored = fresh_bootstrap_session.query(User).filter(User.id == f"user-role-{role}").one()
    assert stored.role == role


def test_fresh_bootstrap_still_rejects_unknown_role(fresh_bootstrap_session):
    """Regressionsschutz: die CHECK-Erweiterung darf keine Freigabe fuer
    beliebige Strings werden -- nur die tatsaechlich verwendeten Rollen."""
    from models.users import User

    now = "2026-08-09T00:00:00.000Z"
    user = User(
        id="user-role-bogus", username="user-role-bogus", password_hash="x",
        full_name="Role Drift Test", role="totally-not-a-real-role", is_active=1,
        created_at=now, updated_at=now,
    )
    fresh_bootstrap_session.add(user)
    with pytest.raises(IntegrityError):
        fresh_bootstrap_session.commit()
