"""RC-CH-1-F1 / N-903-01: freie ``str``-Felder, die in CHECK-Spalten schreiben.

``test_enum_check_constraint_parity.py`` prueft ``Literal``-Felder statisch.
Freie Strings haben keine statische Werteliste; sie sind dort in
``STR_FIELD_POLICY`` registriert (Vollstaendigkeitszwang) und hier auf dem
ECHTEN Schema (``init_db`` mit Rohschema-CHECKs) verhaltensgeprueft: ein Wert
ausserhalb der CHECK-Liste endet nie als 500, sondern als 422 --

* ``schema``: Pydantic lehnt ab (``detail`` ist eine Fehlerliste),
* ``router``: der Router lehnt fachlich ab (422 ohne DB-Reason-Code),
* ``derived``: der Router leitet den Wert selbst ab (Eingabe verworfen);
  gespeichert und ausgeliefert wird ein CHECK-Wert,
* ``central_422``: erst die DB lehnt ab; der zentrale Handler
  (``core.middleware.integrity_error_handler``) antwortet 422 mit
  ``DB_CHECK_CONSTRAINT_VIOLATION``. Mit zurueckgenommener ``middleware.py``
  sind genau diese Faelle 500 (Rueckname-Gegenprobe, N-903-04).

Die Klassifizierung wird exakt geprueft: aendert sich ein Pfad (z.B. ein
Schema bekommt eine eigene Pruefung), muss die Registrierung nachgezogen
werden.

Gegenprobe an fb83c8e7 (N-903-04): rot sind alle ``central_422``-Faelle
(500 bzw. -- ClientCreate -- 409 "Kundennummer bereits vergeben", weil der
Router jeden Integritaetsfehler als Duplikat las; jetzt geht eine CHECK-
Verletzung an den zentralen Handler) und die GoalUpdate-Faelle. Die
uebrigen ``schema``/``router``/``derived``-Faelle waren schon vorher 422
bzw. abgeleitet und sind hier als Regressionsschutz festgehalten.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module  # noqa: E402
from database import get_db, init_db  # noqa: E402
from main import app  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from tests.risk_fixture_helpers import noop_lifespan  # noqa: E402
from tests.test_enum_check_constraint_parity import STR_FIELD_POLICY  # noqa: E402

configure_mappers()

BAD = "__ausserhalb_der_werteliste__"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    db_path = tmp_path / "free_text_real_schema.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db_module.attach_sqlite_pragmas(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module.settings, "db_bootstrap_schema_on_startup", True)
    init_db(engine)
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="user-free-text-admin", username="admin-free-text", password_hash="h",
        full_name="Admin", role="admin", is_active=1, tenant_id="main",
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def api(session_factory, admin_user, monkeypatch):
    with session_factory() as db:
        db.merge(admin_user)
        db.commit()

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


class _Ctx:
    def __init__(self, client: TestClient, user: User):
        self.c = client
        self.user = user
        self._client_id = None
        self._mandate_id = None

    def client_id(self) -> str:
        if self._client_id is None:
            r = self.c.post("/clients", json={
                "client_number": "FREE-TEXT-001", "first_name": "Frei", "last_name": "Text",
                "advisor_id": self.user.id, "household_type": "Einzelperson",
            })
            assert r.status_code == 201, r.text
            self._client_id = r.json()["id"]
        return self._client_id

    def mandate_id(self) -> str:
        if self._mandate_id is None:
            r = self.c.post(f"/clients/{self.client_id()}/mandates", json={
                "mandate_number": "FREE-TEXT-M-001", "mandate_type": "Anlageberatung",
            })
            assert r.status_code == 201, r.text
            self._mandate_id = r.json()["id"]
        return self._mandate_id

    def cashflow_id(self) -> str:
        r = self.c.post(f"/clients/{self.client_id()}/cashflows", json={
            "cashflow_type": "Income", "label": "Lohn", "amount_rappen": 100_000_00,
        })
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def product_id(self) -> str:
        r = self.c.post("/products", json=_product(product_type="ETF"))
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def position_id(self) -> str:
        r = self.c.post(f"/clients/{self.client_id()}/wealth-positions", json={
            "position_type": "Liquidität", "label": "Konto", "value_rappen": 10_000_00,
            "currency": "CHF", "assignment": "Anderes Vermögen",
        })
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def conflict_id(self) -> str:
        r = self.c.post(f"/mandates/{self.mandate_id()}/conflicts", json={
            "conflict_type": "Konzernverbindung", "description": "Konzernprodukt",
        })
        assert r.status_code == 201, r.text
        return r.json()["id"]


def _product(**over):
    body = {
        "product_name": "Test-ETF", "product_type": "ETF", "asset_class": "Aktien",
        "currency": "CHF", "suitability_profile_from": 1, "suitability_profile_to": 10,
        "suitability_service_modes": ["investment_advice"],
    }
    body.update(over)
    return body


def _send(ctx: _Ctx, key: str):
    """Ein Request, der genau dieses Feld auf BAD setzt."""
    c = ctx.c
    if key in ("schemas.clients.ClientCreate.civil_status", "schemas.clients.ClientCreate.partner_salutation"):
        return c.post("/clients", json={
            "client_number": "FREE-TEXT-NEU-001", "first_name": "A", "last_name": "B",
            "advisor_id": ctx.user.id, "household_type": "Einzelperson", key.rsplit(".", 1)[1]: BAD,
        })
    if key in ("schemas.clients.ClientUpdate.civil_status", "schemas.clients.ClientUpdate.partner_salutation"):
        return c.put(f"/clients/{ctx.client_id()}", json={key.rsplit(".", 1)[1]: BAD})
    if key in ("schemas.review.ConflictDisclosureCreate.inducement_frequency",
               "schemas.review.ConflictDisclosureCreate.mitigation_action"):
        return c.post(f"/mandates/{ctx.mandate_id()}/conflicts", json={
            "conflict_type": "Konzernverbindung", "description": "x", key.rsplit(".", 1)[1]: BAD,
        })
    if key == "schemas.review.ConflictMitigateRequest.mitigation_action":
        return c.post(f"/mandates/{ctx.mandate_id()}/conflicts/{ctx.conflict_id()}/mitigate",
                      json={"mitigation_action": BAD})
    if key == "schemas.review.ProductCreate.product_type":
        return c.post("/products", json=_product(product_type=BAD))
    if key == "schemas.review.ProductUpdate.product_type":
        return c.put(f"/products/{ctx.product_id()}", json={"product_type": BAD})
    if key == "schemas.review.ReviewTriggerCreate.frequency":
        return c.post(f"/mandates/{ctx.mandate_id()}/triggers", json={
            "trigger_type": "Zeit", "trigger_name": "Jahresreview", "frequency": BAD,
        })
    if key == "schemas.users.AdviserRegistrationCreate.register_status":
        return c.put(f"/users/{ctx.user.id}/adviser-registration", json={"register_status": BAD})
    if key == "schemas.wealth.CashflowCreate.frequency":
        return c.post(f"/clients/{ctx.client_id()}/cashflows", json={
            "cashflow_type": "Income", "label": "Lohn", "amount_rappen": 1_00, "frequency": BAD,
        })
    if key in ("schemas.wealth.CashflowUpdate.frequency", "schemas.wealth.CashflowUpdate.nature"):
        return c.put(f"/clients/{ctx.client_id()}/cashflows/{ctx.cashflow_id()}",
                     json={key.rsplit(".", 1)[1]: BAD})
    if key == "schemas.wealth.WealthPositionUpdate.assignment":
        return c.put(f"/clients/{ctx.client_id()}/wealth-positions/{ctx.position_id()}",
                     json={"assignment": BAD})
    if key.startswith("schemas.wealth.Goal"):
        cls, field = key.split(".")[2:]
        goal = {
            "goal_family": "Cashflow", "goal_type": "Wiederkehrende_Ausgabe", "label": "Reisen",
            "rank": 1, "target_amount_rappen": 10_000_00, "frequency": "jährlich",
            "start_date": "2031-01-01", "is_ongoing": True, "hardness": "Primär",
        }
        if cls == "GoalCreate":
            return c.post(f"/mandates/{ctx.mandate_id()}/goals", json={**goal, field: BAD})
        created = c.post(f"/mandates/{ctx.mandate_id()}/goals", json=goal)
        assert created.status_code == 201, created.text
        return c.put(f"/mandates/{ctx.mandate_id()}/goals/{created.json()['id']}", json={field: BAD})
    raise AssertionError(f"kein Request fuer {key} -- _send ergaenzen")


def _classify(response, key: str) -> str:
    if response.status_code in (200, 201):
        from tests.test_enum_check_constraint_parity import CHECKS, _target_table

        qualname, field = key.rsplit(".", 1)
        stored = response.json().get(field)
        if stored in CHECKS[(_target_table(qualname), field)]:
            return "derived"
    if response.status_code != 422:
        return f"HTTP {response.status_code}"
    detail = response.json().get("detail")
    if isinstance(detail, dict) and detail.get("reason_code") == "DB_CHECK_CONSTRAINT_VIOLATION":
        return "central_422"
    if isinstance(detail, list):
        return "schema"
    return "router"


@pytest.mark.parametrize("key", sorted(STR_FIELD_POLICY))
def test_free_text_field_outside_check_list_is_422_never_500(api, admin_user, key):
    ctx = _Ctx(api, admin_user)
    response = _send(ctx, key)
    assert _classify(response, key) == STR_FIELD_POLICY[key], (key, response.status_code, response.text[:400])
