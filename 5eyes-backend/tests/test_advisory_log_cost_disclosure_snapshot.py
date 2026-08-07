"""2026-08-07 (CEO/CFO/CIO-Audit): AdvisoryLog.cost_disclosure_given war ein
reines Selbst-Attest-Flag ohne Nachweis, WELCHE Kostenzahlen dem Kunden
tatsaechlich gezeigt wurden (FIDLEG Art. 25/26 Interessenkonflikt-/Kosten-
offenlegung). create_advisory_log() speichert jetzt einen kompakten
JSON-Snapshot der zum Zeitpunkt der Beratung via
services.cost_disclosure.build_cost_disclosure() berechneten Zahlen.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: E402,F401
configure_mappers()

from models.review import AdvisoryLog  # noqa: E402
from models.users import User  # noqa: E402
from schemas.review import AdvisoryLogCreate  # noqa: E402
from services.advisory_log_service import create_advisory_log, serialize_response  # noqa: E402


_NOW = "2026-05-28T14:00:00.000Z"
_FAKE_COST_PAYLOAD = {
    "currency": "CHF",
    "advisory_wealth_rappen": 100_000_000,
    "totals": {
        "one_time_rappen": 500_000,
        "annual_rappen": 800_000,
        "first_year_rappen": 1_300_000,
    },
    "cost_items": [{"label": "Depotgebuehr", "amount_rappen": 800_000}],
}


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'advisory_log_cost_snapshot.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _advisor():
    return User(
        id=str(uuid.uuid4()), username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h", full_name="Anna Beispiel", role="advisor",
        is_active=1, created_at=_NOW, updated_at=_NOW,
    )


def _create_payload(**overrides):
    defaults = dict(
        entry_type="Initialer Beratungsabschluss",
        title="Erstberatung",
        description="A" * 40,
        entry_datetime=_NOW,
        duration_minutes=45,
        communication_channel="persoenlich",
        language="de",
        topics=["Risikoprofil", "Kosten"],
        risk_warnings_given=["Marktrisiko"],
        cost_disclosure_given=True,
    )
    defaults.update(overrides)
    return AdvisoryLogCreate(**defaults)


def test_snapshot_captured_when_cost_disclosure_given(session_factory, monkeypatch):
    import services.advisory_log_service as svc
    monkeypatch.setattr(
        "services.cost_disclosure.build_cost_disclosure",
        lambda db, mandate: _FAKE_COST_PAYLOAD,
    )
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        entry = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(),
            mandate=SimpleNamespace(id="m1"),
        )
        db.commit()

    assert entry.cost_disclosure_snapshot_json is not None
    snapshot = json.loads(entry.cost_disclosure_snapshot_json)
    assert snapshot["currency"] == "CHF"
    assert snapshot["one_time_rappen"] == 500_000
    assert snapshot["annual_rappen"] == 800_000
    assert snapshot["first_year_rappen"] == 1_300_000
    assert "generated_at" in snapshot


def test_no_snapshot_when_cost_disclosure_not_given(session_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "services.cost_disclosure.build_cost_disclosure",
        lambda db, mandate: calls.append(1) or _FAKE_COST_PAYLOAD,
    )
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        entry = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(cost_disclosure_given=False),
            mandate=SimpleNamespace(id="m1"),
        )
        db.commit()

    assert entry.cost_disclosure_snapshot_json is None
    assert not calls, "build_cost_disclosure darf nicht aufgerufen werden, wenn das Flag False ist"


def test_no_snapshot_when_mandate_not_provided(session_factory):
    """Backwards-Compat: Aufrufer, die (noch) kein mandate=... uebergeben,
    duerfen nicht crashen -- das Flag bleibt gueltig, nur ohne Snapshot."""
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        entry = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(),
        )
        db.commit()

    assert entry.cost_disclosure_given == 1
    assert entry.cost_disclosure_snapshot_json is None


def test_snapshot_fail_soft_when_cost_disclosure_raises(session_factory, monkeypatch):
    """Wenn build_cost_disclosure fehlschlaegt (z.B. keine Empfehlung
    vorhanden), darf das den Beratungsprotokoll-Eintrag NICHT verhindern --
    Berater hat das Gespraech dokumentiert, auch ohne Engine-Zahlen."""
    def _raise(db, mandate):
        raise ValueError("keine aktuelle Empfehlung")
    monkeypatch.setattr("services.cost_disclosure.build_cost_disclosure", _raise)
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        entry = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(),
            mandate=SimpleNamespace(id="m1"),
        )
        db.commit()

    assert entry.cost_disclosure_given == 1
    assert entry.cost_disclosure_snapshot_json is None


def test_serialize_response_exposes_snapshot_as_dict(session_factory, monkeypatch):
    monkeypatch.setattr(
        "services.cost_disclosure.build_cost_disclosure",
        lambda db, mandate: _FAKE_COST_PAYLOAD,
    )
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        entry = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(),
            mandate=SimpleNamespace(id="m1"),
        )
        db.commit()
        response = serialize_response(entry)

    assert isinstance(response["cost_disclosure_snapshot"], dict)
    assert response["cost_disclosure_snapshot"]["annual_rappen"] == 800_000


def test_supersede_carries_snapshot_forward(session_factory, monkeypatch):
    from services.advisory_log_service import supersede_advisory_log
    from schemas.review import AdvisoryLogUpdate

    monkeypatch.setattr(
        "services.cost_disclosure.build_cost_disclosure",
        lambda db, mandate: _FAKE_COST_PAYLOAD,
    )
    with session_factory() as db:
        advisor = _advisor()
        db.add(advisor)
        db.commit()
        original = create_advisory_log(
            db, mandate_id="m1", advisor=advisor,
            payload=_create_payload(),
            mandate=SimpleNamespace(id="m1"),
        )
        db.commit()

        new_entry = supersede_advisory_log(
            db, previous=original, advisor=advisor,
            update=AdvisoryLogUpdate(description="B" * 40),
        )
        db.commit()

    assert new_entry.cost_disclosure_snapshot_json == original.cost_disclosure_snapshot_json


def test_hash_payload_does_not_include_snapshot_field():
    """Der Integritaets-Hash-Feld-Order ist ein fester Vertrag (siehe
    services.advisory_log_integrity Docstring) -- der Snapshot darf dort
    NICHT auftauchen, sonst wuerden alle historischen Eintraege beim
    naechsten Read-Verify faelschlich als manipuliert markiert."""
    from services.advisory_log_service import build_hash_payload
    entry = AdvisoryLog(
        id="x", mandate_id="m1", advisor_id="a1", entry_type="Sonstiges",
        title="t", cost_disclosure_given=1,
        cost_disclosure_snapshot_json='{"annual_rappen": 999}',
        version=1, created_at=_NOW, updated_at=_NOW, entry_date="2026-05-28",
    )
    payload = build_hash_payload(entry)
    assert "cost_disclosure_snapshot_json" not in payload
    assert "cost_disclosure_snapshot" not in payload
