"""Unabhaengige Sicherheits-Tiefenpruefung (2026-07-23): Cross-Tenant-Findings.

Deckt die in docs/planning/2026-07-23-independent-security-audit.md
dokumentierten und gefixten Findings ab:

- F1 (KRITISCH): PUT /users/{user_id}/password erlaubte einem tenant-
  gebundenen Firmen-Admin, das Passwort JEDES Users zu setzen -- auch von
  Usern eines fremden Tenants -- weil (im Unterschied zu resend_invite/
  revoke_invite/update_user) nie ein Tenant-Sichtbarkeits-Check stattfand.
- F2 (MITTEL): GET/PUT /users/{user_id}/adviser-registration hatten dieselbe
  Luecke fuer FINMA-Registrierungsdaten (Registernummer, Ombudsstelle).
- F3 (MITTEL): Die Protocol-Bausteine-Bibliothek (/protocol-bausteine) liess
  admin-Rollen komplett ungefiltert ueber ALLE Tenants lesen/edieren/loeschen;
  ein Mandat konnte zudem einen Baustein eines fremden Tenants in sein
  Beratungsprotokoll ziehen.

Jeder Test verifiziert, dass der Cross-Tenant-Zugriff nach dem Fix explizit
verweigert wird (404/403), waehrend der Same-Tenant-/Self-Pfad weiter
funktioniert (keine Regression).
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

from database import Base  # noqa: E402
from main import app  # noqa: E402,F401  (registriert alle Models fuer FK-Aufloesung)

from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.protocol_bausteine import ProtocolBaustein  # noqa: E402
from models.users import AdviserRegistration, User  # noqa: E402

from schemas.protocol_bausteine import (  # noqa: E402
    BausteinUpdate,
    MandateBausteinSelectionItem,
    MandateBausteinSelectionUpdate,
)
from schemas.users import AdviserRegistrationCreate, UserPasswordReset  # noqa: E402

from routers.auth import (  # noqa: E402
    get_adviser_registration,
    reset_user_password,
    upsert_adviser_registration,
)
from routers.protocol_bausteine import (  # noqa: E402
    delete_baustein,
    list_bausteine,
    replace_mandate_selections,
    update_baustein,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'independent_security_audit.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(uid: str, tenant_id: str | None, role: str = "admin") -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid, role=role,
        is_active=1, tenant_id=tenant_id, created_at=_now(), updated_at=_now(),
    )


def _client(cid: str, advisor_id: str, tenant_id: str | None) -> Client:
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id, household_type="Einzelperson",
        client_classification="Privatkunde", country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _mandate(mid: str, client_id: str, tenant_id: str | None) -> Mandate:
    now = _now()
    return Mandate(
        id=mid, mandate_number=mid, client_id=client_id, tenant_id=tenant_id,
        mandate_type="Anlageberatung", status="Aktiv",
        base_currency="CHF", advisory_language="DE",
        opened_at=now, created_at=now, updated_at=now,
    )


def _baustein(bid: str, tenant_id: str | None, advisor_id: str | None = None) -> ProtocolBaustein:
    now = _now()
    return ProtocolBaustein(
        id=bid, advisor_id=advisor_id, tenant_id=tenant_id,
        title=f"Baustein {bid}", content_md="Inhalt", sort_order=0,
        is_active=1, created_at=now, updated_at=now,
    )


# ===========================================================================
# F1: PUT /users/{user_id}/password -- Cross-Tenant Passwort-Reset
# ===========================================================================


def test_admin_cannot_reset_password_of_foreign_tenant_user(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a", tenant_id="firma-a", role="admin")
        user_b = _user("user-b", tenant_id="firma-b", role="advisor")
        db.add_all([admin_a, user_b])
        db.commit()
        old_hash = user_b.password_hash

        with pytest.raises(HTTPException) as exc:
            reset_user_password(
                user_id="user-b",
                body=UserPasswordReset(new_password="supersecret123"),
                db=db, current_user=admin_a,
            )
        # 404, nicht 403 -- keine Existenz-Leak fremder User.
        assert exc.value.status_code == 404
        db.refresh(user_b)
        assert user_b.password_hash == old_hash, "Passwort darf NICHT geaendert worden sein"


def test_admin_can_reset_password_of_same_tenant_user(session_factory):
    """Regression: der legitime Same-Tenant-Admin-Reset muss weiter funktionieren."""
    with session_factory() as db:
        admin_a = _user("admin-a2", tenant_id="firma-a", role="admin")
        user_a = _user("user-a2", tenant_id="firma-a", role="advisor")
        db.add_all([admin_a, user_a])
        db.commit()
        old_hash = user_a.password_hash

        result = reset_user_password(
            user_id="user-a2",
            body=UserPasswordReset(new_password="supersecret123"),
            db=db, current_user=admin_a,
        )
        assert result.password_hash != old_hash
        assert result.must_change_password == 1


def test_self_password_reset_still_works_without_tenant(session_factory):
    """Self-Service-Pfad (is_self) darf durch den neuen Check nicht blockiert
    werden -- auch wenn der User keinen Tenant hat (Legacy)."""
    with session_factory() as db:
        user = _user("self-user", tenant_id=None, role="advisor")
        db.add(user)
        db.commit()
        old_hash = user.password_hash

        result = reset_user_password(
            user_id="self-user",
            body=UserPasswordReset(new_password="supersecret123"),
            db=db, current_user=user,
        )
        assert result.password_hash != old_hash
        assert result.must_change_password == 0


def test_super_admin_can_reset_password_across_tenants(session_factory):
    """super_admin bleibt bewusst unscoped (Tier-2-Operator-Rolle)."""
    with session_factory() as db:
        super_admin = _user("super-1", tenant_id=None, role="super_admin")
        user_b = _user("user-b2", tenant_id="firma-b", role="advisor")
        db.add_all([super_admin, user_b])
        db.commit()
        old_hash = user_b.password_hash

        result = reset_user_password(
            user_id="user-b2",
            body=UserPasswordReset(new_password="supersecret123"),
            db=db, current_user=super_admin,
        )
        assert result.password_hash != old_hash


# ===========================================================================
# F2: /users/{user_id}/adviser-registration -- Cross-Tenant FINMA-Daten
# ===========================================================================


def test_admin_cannot_view_foreign_tenant_adviser_registration(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a3", tenant_id="firma-a", role="admin")
        adviser_b = _user("adviser-b3", tenant_id="firma-b", role="advisor")
        reg = AdviserRegistration(
            id="reg-b3", user_id="adviser-b3", register_body="FINMA Beraterregister",
            register_number="XY-123", register_status="Aktiv",
            created_at=_now(), updated_at=_now(),
        )
        db.add_all([admin_a, adviser_b, reg])
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_adviser_registration(user_id="adviser-b3", db=db, current_user=admin_a)
        assert exc.value.status_code == 404


def test_admin_cannot_upsert_foreign_tenant_adviser_registration(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a4", tenant_id="firma-a", role="admin")
        adviser_b = _user("adviser-b4", tenant_id="firma-b", role="advisor")
        db.add_all([admin_a, adviser_b])
        db.commit()

        with pytest.raises(HTTPException) as exc:
            upsert_adviser_registration(
                user_id="adviser-b4",
                body=AdviserRegistrationCreate(register_number="HACKED"),
                db=db, current_user=admin_a,
            )
        assert exc.value.status_code == 404
        assert db.query(AdviserRegistration).filter(
            AdviserRegistration.user_id == "adviser-b4"
        ).count() == 0, "Es darf KEIN Registrierungs-Datensatz fuer den fremden User entstehen"


def test_admin_can_manage_same_tenant_adviser_registration(session_factory):
    """Regression: Same-Tenant-Admin-Pflege bleibt erlaubt."""
    with session_factory() as db:
        admin_a = _user("admin-a5", tenant_id="firma-a", role="admin")
        adviser_a = _user("adviser-a5", tenant_id="firma-a", role="advisor")
        db.add_all([admin_a, adviser_a])
        db.commit()

        result = upsert_adviser_registration(
            user_id="adviser-a5",
            body=AdviserRegistrationCreate(register_number="CH-999"),
            db=db, current_user=admin_a,
        )
        assert result.register_number == "CH-999"

        fetched = get_adviser_registration(user_id="adviser-a5", db=db, current_user=admin_a)
        assert fetched.register_number == "CH-999"


# ===========================================================================
# F3: Protocol-Bausteine-Bibliothek -- Cross-Tenant Content-Leak
# ===========================================================================


def test_admin_list_bausteine_excludes_foreign_tenant(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a6", tenant_id="firma-a", role="admin")
        db.add(admin_a)
        db.add(_baustein("b-a6", tenant_id="firma-a"))
        db.add(_baustein("b-b6", tenant_id="firma-b"))
        db.commit()

        rows = list_bausteine(category=None, include_inactive=False, db=db, current_user=admin_a)
        ids = {r.id for r in rows}
        assert "b-a6" in ids
        assert "b-b6" not in ids, "Fremder Tenant-Baustein darf nicht in der Liste erscheinen"


def test_admin_cannot_edit_foreign_tenant_baustein(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a7", tenant_id="firma-a", role="admin")
        db.add(admin_a)
        db.add(_baustein("b-b7", tenant_id="firma-b"))
        db.commit()

        with pytest.raises(HTTPException) as exc:
            update_baustein(
                baustein_id="b-b7",
                body=BausteinUpdate(title="Uebernommen"),
                db=db, current_user=admin_a,
            )
        assert exc.value.status_code == 403
        row = db.query(ProtocolBaustein).filter(ProtocolBaustein.id == "b-b7").one()
        assert row.title != "Uebernommen"


def test_admin_cannot_delete_foreign_tenant_baustein(session_factory):
    with session_factory() as db:
        admin_a = _user("admin-a8", tenant_id="firma-a", role="admin")
        db.add(admin_a)
        db.add(_baustein("b-b8", tenant_id="firma-b"))
        db.commit()

        with pytest.raises(HTTPException) as exc:
            delete_baustein(baustein_id="b-b8", db=db, current_user=admin_a)
        assert exc.value.status_code == 403
        row = db.query(ProtocolBaustein).filter(ProtocolBaustein.id == "b-b8").one()
        assert row.deleted_at is None


def test_admin_can_edit_same_tenant_baustein(session_factory):
    """Regression: Same-Tenant-Admin-Edit bleibt erlaubt."""
    with session_factory() as db:
        admin_a = _user("admin-a9", tenant_id="firma-a", role="admin")
        db.add(admin_a)
        db.add(_baustein("b-a9", tenant_id="firma-a"))
        db.commit()

        result = update_baustein(
            baustein_id="b-a9",
            body=BausteinUpdate(title="Neuer Titel"),
            db=db, current_user=admin_a,
        )
        assert result.title == "Neuer Titel"


def test_replace_mandate_selections_rejects_foreign_tenant_baustein(session_factory):
    with session_factory() as db:
        advisor_a = _user("advisor-a10", tenant_id="firma-a", role="advisor")
        db.add(advisor_a)
        db.add(_client("c-a10", advisor_id="advisor-a10", tenant_id="firma-a"))
        db.add(_mandate("m-a10", client_id="c-a10", tenant_id="firma-a"))
        db.add(_baustein("b-b10", tenant_id="firma-b"))  # fremder Tenant
        db.commit()

        with pytest.raises(HTTPException) as exc:
            replace_mandate_selections(
                mandate_id="m-a10",
                body=MandateBausteinSelectionUpdate(
                    selections=[MandateBausteinSelectionItem(baustein_id="b-b10")]
                ),
                db=db, current_user=advisor_a,
            )
        assert exc.value.status_code == 403


def test_replace_mandate_selections_allows_same_tenant_baustein(session_factory):
    """Regression: Same-Tenant + globaler (tenant_id=None) Baustein bleiben waehlbar."""
    with session_factory() as db:
        advisor_a = _user("advisor-a11", tenant_id="firma-a", role="advisor")
        db.add(advisor_a)
        db.add(_client("c-a11", advisor_id="advisor-a11", tenant_id="firma-a"))
        db.add(_mandate("m-a11", client_id="c-a11", tenant_id="firma-a"))
        db.add(_baustein("b-a11", tenant_id="firma-a"))
        db.add(_baustein("b-global11", tenant_id=None))
        db.commit()

        result = replace_mandate_selections(
            mandate_id="m-a11",
            body=MandateBausteinSelectionUpdate(
                selections=[
                    MandateBausteinSelectionItem(baustein_id="b-a11"),
                    MandateBausteinSelectionItem(baustein_id="b-global11"),
                ]
            ),
            db=db, current_user=advisor_a,
        )
        assert {r.baustein_id for r in result} == {"b-a11", "b-global11"}
