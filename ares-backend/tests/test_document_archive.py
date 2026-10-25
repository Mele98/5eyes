"""Dokumenten-Archiv (Kundenfeedback 2026-08-20): jede generierte PDF-Version
wird server-seitig unveraenderlich abgelegt (services/document_archive.py),
statt wie zuvor nur in-memory an den Client geschickt zu werden.

Deckt den vollen Kreislauf ab: PDF generieren -> ContractDocument-Zeile mit
echten Bytes + Checksum entsteht -> erneutes, unveraendertes Generieren
erzeugt KEINE zweite Version (Dedup ueber Checksum) -> Liste zeigt has_pdf
+ created_by_name -> GET .../documents/{id}/pdf liefert exakt dieselben
Bytes zurueck wie der urspruengliche Report-Endpoint.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.clients import Client
from models.mandates import Mandate
from models.review import ContractDocument
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'document_archive.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-doc-archive",
        username="advisor-doc-archive",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _seed_minimal_mandate(session_factory, advisor_user, mandate_id: str = "mdt-doc-archive") -> str:
    with session_factory() as db:
        if db.query(User).filter(User.id == advisor_user.id).first() is None:
            db.add(advisor_user)
        client_id = "cli-" + mandate_id
        db.add(Client(
            id=client_id, client_number="C-" + mandate_id, first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id=client_id, mandate_number="M-" + mandate_id,
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


def test_generating_pdf_archives_a_version(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"%PDF"

    with session_factory() as db:
        rows = db.query(ContractDocument).filter(
            ContractDocument.mandate_id == mandate_id,
            ContractDocument.document_type == "Risikoprofilierung",
        ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.version == 1
    assert row.supersedes_id is None
    assert row.status == "Archiviert"
    assert row.created_by == advisor_user.id
    assert row.checksum_sha256 == hashlib.sha256(resp.content).hexdigest()
    assert base64.b64decode(row.pdf_base64) == resp.content


def test_regenerating_unchanged_pdf_does_not_create_second_version(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")

    with session_factory() as db:
        rows = db.query(ContractDocument).filter(
            ContractDocument.mandate_id == mandate_id,
            ContractDocument.document_type == "Risikoprofilierung",
        ).all()
    # Dedup ueber Checksum: unveraenderter Inhalt -> keine zweite Version.
    assert len(rows) == 1
    assert rows[0].version == 1


def test_list_documents_exposes_has_pdf_and_creator_name(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")

    resp = auth_client.get(f"/mandates/{mandate_id}/documents")
    assert resp.status_code == 200, resp.text
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["document_type"] == "Risikoprofilierung"
    assert docs[0]["has_pdf"] is True
    assert docs[0]["created_by_name"] == "Test Advisor"
    # pdf_base64 selbst ist bewusst NICHT Teil der Listen-Antwort (Groesse).
    assert "pdf_base64" not in docs[0]


def test_document_pdf_endpoint_returns_archived_bytes(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    original = auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")

    doc_id = auth_client.get(f"/mandates/{mandate_id}/documents").json()[0]["id"]
    archived = auth_client.get(f"/mandates/{mandate_id}/documents/{doc_id}/pdf")
    assert archived.status_code == 200, archived.text
    assert archived.headers["content-type"] == "application/pdf"
    assert archived.content == original.content


def test_document_pdf_endpoint_404_for_unknown_doc(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/documents/does-not-exist/pdf")
    assert resp.status_code == 404


def test_new_mandate_generation_creates_independent_version_history(auth_client, advisor_user, session_factory):
    """Zwei verschiedene Mandate teilen sich keine Versionskette."""
    mid_a = _seed_minimal_mandate(session_factory, advisor_user, mandate_id="mdt-doc-a")
    mid_b = _seed_minimal_mandate(session_factory, advisor_user, mandate_id="mdt-doc-b")
    auth_client.get(f"/mandates/{mid_a}/reports/risikoprofil.pdf")
    auth_client.get(f"/mandates/{mid_b}/reports/risikoprofil.pdf")

    with session_factory() as db:
        rows_a = db.query(ContractDocument).filter(ContractDocument.mandate_id == mid_a).all()
        rows_b = db.query(ContractDocument).filter(ContractDocument.mandate_id == mid_b).all()
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0].version == 1
    assert rows_b[0].version == 1
