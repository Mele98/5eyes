"""VALID-01 (Audit-Finding, 2026-10-07): schemas/clients.py hatte keine
Datenqualitaets-Validierung fuer date_of_birth/canton. Ein Client liess
sich mit einem Geburtsdatum in der Zukunft, einem absurden Geburtsjahr
(impliziert Alter > 120), oder einem Kanton-Freitext anlegen/aktualisieren,
der keiner der 26 echten Schweizer Kantonscodes ist.

Diese Guards sind bewusst DATENQUALITAETS-Pruefungen, keine strengen
Geschaeftsregeln -- household_type='Paar' + civil_status='Ledig' bleibt
absichtlich ungeprueft (FINMA verlangt keine harte Ablehnung dieser
Kombination, siehe Audit-Notiz; bestehender, rein kosmetischer Frontend-
Hinweis bleibt die einzige Warnung dafuer).

Deckt ab:
- schemas.clients.ClientCreate/ClientUpdate: direkte Pydantic-Validierung
  (kein DB/HTTP-Overhead noetig fuer die reine Werte-Pruefung).
- End-to-end ueber POST /clients und PUT /clients/{id} (422 bei Verstoss,
  201/200 beim gueltigen Normalfall) -- selbe Fixtures wie
  test_data_classification_gate.py.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.clients import ClientCreate, ClientUpdate
from test_data_classification_gate import (  # noqa: F401
    _client_payload,
    advisor_user,
    auth_client,
    session_factory,
)


def _base_create_kwargs(**overrides) -> dict:
    kwargs = {
        "client_number": "VALID01-1",
        "first_name": "Valid",
        "last_name": "Guard",
        "advisor_id": "advisor-data-gate",
    }
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Schema-level: date_of_birth
# ---------------------------------------------------------------------------

def test_date_of_birth_future_rejected_on_create():
    with pytest.raises(ValidationError, match="Zukunft"):
        ClientCreate(**_base_create_kwargs(date_of_birth=str(date.today() + timedelta(days=1))))


def test_date_of_birth_implausibly_old_rejected_on_create():
    with pytest.raises(ValidationError, match="unplausibles Alter"):
        ClientCreate(**_base_create_kwargs(date_of_birth="1800-01-01"))


def test_date_of_birth_malformed_rejected_on_create():
    with pytest.raises(ValidationError, match="gueltiges ISO-Datum"):
        ClientCreate(**_base_create_kwargs(date_of_birth="not-a-date"))


def test_date_of_birth_plausible_value_accepted_on_create():
    model = ClientCreate(**_base_create_kwargs(date_of_birth="1970-05-15"))
    assert model.date_of_birth == "1970-05-15"


def test_date_of_birth_none_accepted_on_create():
    model = ClientCreate(**_base_create_kwargs(date_of_birth=None))
    assert model.date_of_birth is None


def test_date_of_birth_future_rejected_on_update():
    with pytest.raises(ValidationError, match="Zukunft"):
        ClientUpdate(date_of_birth=str(date.today() + timedelta(days=1)))


def test_date_of_birth_plausible_value_accepted_on_update():
    model = ClientUpdate(date_of_birth="1990-01-01")
    assert model.date_of_birth == "1990-01-01"


# ---------------------------------------------------------------------------
# Schema-level: canton
# ---------------------------------------------------------------------------

def test_canton_garbage_string_rejected_on_create():
    with pytest.raises(ValidationError, match="Schweizer Kantonscodes"):
        ClientCreate(**_base_create_kwargs(canton="XX"))


def test_canton_case_insensitive_normalized_to_uppercase_on_create():
    model = ClientCreate(**_base_create_kwargs(canton="zh"))
    assert model.canton == "ZH"


def test_canton_all_26_real_codes_accepted_on_create():
    from schemas.clients import SWISS_CANTON_CODES
    assert len(SWISS_CANTON_CODES) == 26
    for code in SWISS_CANTON_CODES:
        model = ClientCreate(**_base_create_kwargs(canton=code.lower()))
        assert model.canton == code


def test_canton_none_accepted_on_create():
    model = ClientCreate(**_base_create_kwargs(canton=None))
    assert model.canton is None


def test_canton_garbage_string_rejected_on_update():
    with pytest.raises(ValidationError, match="Schweizer Kantonscodes"):
        ClientUpdate(canton="Zurich")


def test_canton_valid_code_accepted_on_update():
    model = ClientUpdate(canton="ge")
    assert model.canton == "GE"


# ---------------------------------------------------------------------------
# household_type/civil_status: explicitly NOT hard-rejected (soft case)
# ---------------------------------------------------------------------------

def test_household_paar_with_civil_status_ledig_not_rejected():
    """Bewusst ungeprueft -- FINMA verlangt keine harte Ablehnung dieser
    Kombination (siehe Audit-Notiz). Nur ein kosmetischer, nicht-
    blockierender Frontend-Hinweis existiert dafuer, dieser Schema-Layer
    lehnt sie nicht ab."""
    model = ClientCreate(
        **_base_create_kwargs(household_type="Paar", civil_status="Ledig")
    )
    assert model.household_type == "Paar"
    assert model.civil_status == "Ledig"


# ---------------------------------------------------------------------------
# End-to-end: POST /clients, PUT /clients/{id}
# ---------------------------------------------------------------------------

def test_post_clients_rejects_future_date_of_birth(auth_client):
    payload = _client_payload("VALID01-E2E-1", "synthetic")
    payload["date_of_birth"] = str(date.today() + timedelta(days=5))
    response = auth_client.post("/clients", json=payload)
    assert response.status_code == 422, response.text


def test_post_clients_rejects_bad_canton(auth_client):
    payload = _client_payload("VALID01-E2E-2", "synthetic")
    payload["canton"] = "NOPE"
    response = auth_client.post("/clients", json=payload)
    assert response.status_code == 422, response.text


def test_post_clients_accepts_valid_canton_and_dob(auth_client):
    payload = _client_payload("VALID01-E2E-3", "synthetic")
    payload["canton"] = "vd"
    payload["date_of_birth"] = "1985-03-20"
    response = auth_client.post("/clients", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["canton"] == "VD"


def test_put_clients_rejects_bad_canton(auth_client):
    payload = _client_payload("VALID01-E2E-4", "synthetic")
    created = auth_client.post("/clients", json=payload)
    assert created.status_code == 201, created.text
    client_id = created.json()["id"]

    response = auth_client.put(f"/clients/{client_id}", json={"canton": "ZZ"})
    assert response.status_code == 422, response.text
