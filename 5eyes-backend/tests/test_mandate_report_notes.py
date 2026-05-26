"""Tests für Sprint U-P28 PR A — MandateReportNotes Datenmodell + Endpoints.

Deckt:
- Persistenz: Schema + UNIQUE-Constraint auf mandate_id
- GET /mandates/{id}/report-notes — leere Zeile → leere Response
- PUT /mandates/{id}/report-notes — Insert (erste Pflege) + Update
- Audit-Anchor (last_edited_by / last_edited_at)
- JSON-Listen-Felder (offene_fragen / todos / dokumente)
- Audit-Log-Entry wird bei jedem PUT geschrieben

Wird in PR B um Aggregator-Integration ergänzt; das hier deckt nur das
reine Datenmodell + die HTTP-Schicht ab.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from main import app  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog, MandateReportNotes  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user, require_advisor  # noqa: E402


_NOW = "2026-05-26T10:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'report_notes.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(session) -> tuple[User, Mandate]:
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beispiel",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Hans",
        last_name="Muster",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add_all([advisor, client, mandate])
    session.commit()
    return advisor, mandate


@pytest.fixture()
def http_client(session_factory):
    """TestClient mit get_db + get_current_user + require_advisor overridden.

    Pattern stammt aus existierenden 5eyes-Tests — Auth-Layer wird komplett
    gemockt, damit die Endpoint-Logik (DB-Zugriff + Validierung) isoliert
    getestet werden kann.
    """
    SF = session_factory
    session = SF()
    advisor, mandate = _seed(session)

    def _db_dep():
        try:
            yield session
        finally:
            pass

    def _user_dep():
        return advisor

    app.dependency_overrides[get_db] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep
    app.dependency_overrides[require_advisor] = _user_dep
    try:
        yield TestClient(app), advisor, mandate, session
    finally:
        app.dependency_overrides.clear()
        session.close()


# ---------------------------------------------------------------------------
# 1. Datenmodell-Schema
# ---------------------------------------------------------------------------

def test_table_created_with_unique_mandate_id_constraint(session_factory):
    """Schema-Smoke-Test: Tabelle existiert + UNIQUE-Constraint greift."""
    with session_factory() as s:
        advisor, mandate = _seed(s)
        note_a = MandateReportNotes(
            id=str(uuid.uuid4()),
            mandate_id=mandate.id,
            aa_anmerkungen="Erster Eintrag",
            last_edited_by=advisor.id,
            last_edited_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(note_a)
        s.commit()

        # Zweiter Insert auf gleiches Mandat MUSS scheitern (UNIQUE).
        note_b = MandateReportNotes(
            id=str(uuid.uuid4()),
            mandate_id=mandate.id,
            aa_anmerkungen="Zweiter Eintrag",
            last_edited_by=advisor.id,
            last_edited_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(note_b)
        with pytest.raises(Exception):  # IntegrityError-Wrapping unterscheidet sich pro Backend
            s.commit()


# ---------------------------------------------------------------------------
# 2. GET — leeres Mandat → leere Response
# ---------------------------------------------------------------------------

def test_get_returns_empty_response_for_unedited_mandate(http_client):
    client, advisor, mandate, _session = http_client
    resp = client.get(f"/mandates/{mandate.id}/report-notes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mandate_id"] == mandate.id
    assert body["aa_anmerkungen"] is None
    assert body["waehrungen_erklaerung"] is None
    assert body["vorgehen_offene_fragen"] == []
    assert body["vorgehen_todos"] == []
    assert body["vorgehen_dokumente"] == []
    assert body["last_edited_by"] is None


# ---------------------------------------------------------------------------
# 3. PUT — Insert
# ---------------------------------------------------------------------------

def test_put_creates_row_and_persists_all_fields(http_client):
    client, advisor, mandate, session = http_client
    payload = {
        "aa_anmerkungen": "Berater-Text fuer Asset-Allocation.",
        "waehrungen_erklaerung": "CHF-Anteil aktiv gemanagt.",
        "branchen_analyse": "Schwerpunkt Tech + Healthcare.",
        "vorgehen_block_optimierungen": "Quartalsweise Reviews.",
        "vorgehen_block_zielstrategie": "Vorsorge-Aufbau bis 65.",
        "vorgehen_offene_fragen": ["Pillar 3a-Limit erreicht?", "Risikoabsicherung?"],
        "vorgehen_naechster_termin": "2026-08-15",
        "vorgehen_todos": ["Vorsorgeauftrag pruefen", "BVG-Einkauf evaluieren"],
        "vorgehen_dokumente": ["Identifikationspapier", "Ausweis Wohnsitz"],
    }
    resp = client.put(f"/mandates/{mandate.id}/report-notes", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["aa_anmerkungen"] == "Berater-Text fuer Asset-Allocation."
    assert body["vorgehen_offene_fragen"] == [
        "Pillar 3a-Limit erreicht?",
        "Risikoabsicherung?",
    ]
    assert body["vorgehen_todos"] == [
        "Vorsorgeauftrag pruefen",
        "BVG-Einkauf evaluieren",
    ]
    assert body["last_edited_by"] == advisor.id
    assert body["last_edited_at"].endswith("Z")
    assert body["created_at"] == body["last_edited_at"]

    # DB-Persistenz prüfen
    persisted = session.query(MandateReportNotes).filter_by(mandate_id=mandate.id).one()
    assert persisted.aa_anmerkungen == "Berater-Text fuer Asset-Allocation."
    parsed_fragen = json.loads(persisted.vorgehen_offene_fragen_json)
    assert parsed_fragen == ["Pillar 3a-Limit erreicht?", "Risikoabsicherung?"]


# ---------------------------------------------------------------------------
# 4. PUT — Update (created_at bleibt, last_edited_at aktualisiert)
# ---------------------------------------------------------------------------

def test_put_updates_existing_row_and_keeps_created_at(http_client):
    client, advisor, mandate, session = http_client
    # Insert
    resp_a = client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": "Erste Version"},
    )
    created_at_first = resp_a.json()["created_at"]
    first_edit_at = resp_a.json()["last_edited_at"]

    # Update
    resp_b = client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": "Geupdatete Version"},
    )
    body = resp_b.json()
    assert body["aa_anmerkungen"] == "Geupdatete Version"
    assert body["created_at"] == created_at_first
    # last_edited_at darf NICHT zurueckspringen (nur gleich oder neuer)
    assert body["last_edited_at"] >= first_edit_at


# ---------------------------------------------------------------------------
# 5. PUT — Partial-Update lässt nicht-gesendete Felder unangetastet
# ---------------------------------------------------------------------------

def test_put_partial_update_leaves_other_fields_intact(http_client):
    client, advisor, mandate, session = http_client
    client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={
            "aa_anmerkungen": "A",
            "waehrungen_erklaerung": "B",
            "vorgehen_todos": ["TODO-1"],
        },
    )
    # Nur aa_anmerkungen anpassen
    client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": "A-neu"},
    )
    final = client.get(f"/mandates/{mandate.id}/report-notes").json()
    assert final["aa_anmerkungen"] == "A-neu"
    assert final["waehrungen_erklaerung"] == "B"      # unangetastet
    assert final["vorgehen_todos"] == ["TODO-1"]       # unangetastet


# ---------------------------------------------------------------------------
# 6. Audit-Log: Jeder PUT erzeugt einen Audit-Log-Eintrag
# ---------------------------------------------------------------------------

def test_put_writes_audit_log_entry(http_client):
    client, advisor, mandate, session = http_client
    client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": "Audit-Test"},
    )
    entries = (
        session.query(AuditLog)
        .filter_by(table_name="mandate_report_notes")
        .all()
    )
    assert len(entries) == 1
    e = entries[0]
    assert e.user_id == advisor.id
    assert e.user_name == "Anna Beispiel"
    assert e.action == "update"
    assert e.mandate_id == mandate.id


# ---------------------------------------------------------------------------
# 7. Leerer String "" setzt Feld auf NULL (Aggregator fällt auf Default zurück)
# ---------------------------------------------------------------------------

def test_put_empty_string_clears_field_to_default(http_client):
    client, advisor, mandate, session = http_client
    # Erst pflegen
    client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": "Erstmal etwas"},
    )
    # Dann mit "" loeschen
    client.put(
        f"/mandates/{mandate.id}/report-notes",
        json={"aa_anmerkungen": ""},
    )
    final = client.get(f"/mandates/{mandate.id}/report-notes").json()
    assert final["aa_anmerkungen"] is None


# ---------------------------------------------------------------------------
# 8. JSON-Listen-Robustheit: kaputtes JSON in der DB → leere Liste
# ---------------------------------------------------------------------------

def test_get_returns_empty_list_when_json_is_corrupt(http_client):
    client, advisor, mandate, session = http_client
    # Direkt in DB ein kaputtes JSON setzen (simuliert Datenkorruption)
    notes = MandateReportNotes(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        vorgehen_todos_json="this is not json {",
        last_edited_by=advisor.id,
        last_edited_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(notes)
    session.commit()

    resp = client.get(f"/mandates/{mandate.id}/report-notes")
    assert resp.status_code == 200
    assert resp.json()["vorgehen_todos"] == []  # statt 500


# ---------------------------------------------------------------------------
# 9. Mandat existiert nicht → 404 (Auth-Pattern wie andere Endpoints)
# ---------------------------------------------------------------------------

def test_get_returns_404_for_unknown_mandate(http_client):
    client, _advisor, _mandate, _session = http_client
    resp = client.get("/mandates/does-not-exist/report-notes")
    assert resp.status_code == 404


def test_put_returns_404_for_unknown_mandate(http_client):
    client, _advisor, _mandate, _session = http_client
    resp = client.put(
        "/mandates/does-not-exist/report-notes",
        json={"aa_anmerkungen": "x"},
    )
    assert resp.status_code == 404
