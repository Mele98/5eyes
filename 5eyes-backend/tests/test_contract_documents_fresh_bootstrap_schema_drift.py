"""Live-Smoketest-Fund (2026-08-06): dieselbe Bugklasse wie in
test_house_matrix_fresh_bootstrap_schema_drift.py -- eine per Code
eingefuehrte Aufzaehlungswert wurde nie in den rohen Bootstrap-Schema-
CHECK-Constraint (5eyes_schema_v4.0_FINAL.sql, der von init_db() bei JEDER
echten Erstinstallation ausgefuehrt wird) nachgetragen.

Konkret: das E-Signing-Feature (2026-08-05, Commit 24303b0) setzt
contract_documents.status='Teilweise unterzeichnet', sobald genau EIN
Unterzeichner (Berater ODER Kunde) signiert hat (siehe
routers/review.py::sign_document). Der CHECK-Constraint im Schema-SQL
kannte diesen Wert nicht -- jede Teil-Signatur crashte auf einer echten
Installation mit einem rohen 500 (sqlite3.IntegrityError). Auf der
bestehenden Dev-DB nie aufgefallen, weil deren contract_documents-Tabelle
lange vor diesem Feature erstmalig angelegt wurde (ALTER-freie additive
Migration aendert keine CHECK-Constraints) UND weil test_runtime_
contracts.py::test_sign_document_* ausschliesslich gegen
Base.metadata.create_all() testen (kein Raw-SQL-Bootstrap, daher ohne
CHECK-Constraint ueberhaupt) -- live erst beim Nachstellen des kompletten
E-Signing-Flows in einem echten Browser (Playwright) gegen eine fabrikneue
Installation gefunden.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401,E501
configure_mappers()


def test_fresh_bootstrap_contract_document_accepts_partial_signature_status(tmp_path, monkeypatch):
    import database as db_module
    from models.users import User
    from models.clients import Client
    from models.mandates import Mandate
    from models.review import ContractDocument

    db_path = tmp_path / "fresh_contract_doc.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()

    TestSession = sessionmaker(bind=test_engine)
    now = "2026-08-06T00:00:00.000Z"
    with TestSession() as session:
        user = User(
            id="user-test", username="tester", password_hash="x", full_name="Tester",
            role="advisor", is_active=1, created_at=now, updated_at=now,
        )
        client = Client(
            id="client-test", client_number="K-TEST-1", first_name="Test", last_name="Client",
            country_of_residence="CH", advisor_id="user-test", created_at=now, updated_at=now,
        )
        mandate = Mandate(
            id="mandate-test", client_id="client-test", mandate_number="M-TEST-1",
            mandate_type="Vermögensverwaltung", opened_at="2026-08-06", created_at=now, updated_at=now,
        )
        session.add_all([user, client, mandate])
        session.flush()
        doc = ContractDocument(
            id="doc-test", mandate_id="mandate-test", document_type="Beratungsprotokoll",
            title="Test-Protokoll", status="Teilweise unterzeichnet",
            signed_by_advisor=1, signed_by_client=0, signed_at=now,
            created_by="user-test", created_at=now, updated_at=now,
        )
        session.add(doc)
        # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen.
        session.commit()

        stored = session.query(ContractDocument).filter(ContractDocument.id == "doc-test").one()
    assert stored.status == "Teilweise unterzeichnet"


def test_fresh_bootstrap_contract_document_still_accepts_full_and_draft_status(tmp_path, monkeypatch):
    """Regressionsschutz: die bereits vorher gueltigen Werte duerfen durch
    das Nachtragen von 'Teilweise unterzeichnet' nicht verloren gehen."""
    import database as db_module
    from models.users import User
    from models.clients import Client
    from models.mandates import Mandate
    from models.review import ContractDocument

    db_path = tmp_path / "fresh_contract_doc2.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()

    TestSession = sessionmaker(bind=test_engine)
    now = "2026-08-06T00:00:00.000Z"
    with TestSession() as session:
        user = User(
            id="user-test", username="tester", password_hash="x", full_name="Tester",
            role="advisor", is_active=1, created_at=now, updated_at=now,
        )
        client = Client(
            id="client-test", client_number="K-TEST-1", first_name="Test", last_name="Client",
            country_of_residence="CH", advisor_id="user-test", created_at=now, updated_at=now,
        )
        mandate = Mandate(
            id="mandate-test", client_id="client-test", mandate_number="M-TEST-1",
            mandate_type="Vermögensverwaltung", opened_at="2026-08-06", created_at=now, updated_at=now,
        )
        session.add_all([user, client, mandate])
        session.flush()
        for idx, status in enumerate(("Entwurf", "Bereit", "Unterzeichnet", "Archiviert")):
            session.add(ContractDocument(
                id=f"doc-test-{idx}", mandate_id="mandate-test", document_type="Beratungsprotokoll",
                title="Test-Protokoll", status=status,
                created_by="user-test", created_at=now, updated_at=now,
            ))
        session.commit()
        stored = {row.status for row in session.query(ContractDocument).all()}
    assert stored == {"Entwurf", "Bereit", "Unterzeichnet", "Archiviert"}
