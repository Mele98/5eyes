"""Live-Smoketest-Fund (2026-08-06): dieselbe Bugklasse wie in
test_house_matrix_fresh_bootstrap_schema_drift.py und
test_contract_documents_fresh_bootstrap_schema_drift.py -- der rohe
Bootstrap-Schema-CHECK-Constraint (5eyes_schema_v4.0_FINAL.sql, von
init_db() bei JEDER echten Erstinstallation ausgefuehrt) kannte den vom
Frontend tatsaechlich verwendeten Wert nicht.

Konkret: das "Vermoegensposition erfassen"-Modal (Kategorie "Hypothek")
setzt/resettet das Amortisationstyp-Feld per Default auf
'Indirekt (Säule 3a)' (siehe 5eyes_v2.html::setSelectValue('maw-mortgage-
amortization-type', ...), dreifach vorkommend: Options-Liste, Reset-
Default, Edit-Prefill-Fallback). Der CHECK-Constraint erlaubte nur
'Indirekt (3a)' (ohne 'Säule') -- jede Hypothek, bei der der Berater das
Amortisationstyp-Feld nicht manuell auf 'Direkt'/'Keine' umstellte (der
naheliegende, unveraenderte Standardfall), crashte beim Speichern mit
einem rohen 500. Live beim Durchklicken des "Vermoegen"-Tabs mit
Playwright gefunden -- die echte Dev-DB enthaelt fuer diese Spalte nur
'Direkt'/'Keine' (per Read-only-Kopie verifiziert), nie 'Indirekt (...)'
in irgendeiner Schreibweise, was dafuer spricht, dass diese Kombination
bisher immer entweder manuell umgangen oder schlicht nie erfolgreich
gespeichert wurde.
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


def _fresh_session(tmp_path, monkeypatch, name):
    import database as db_module

    db_path = tmp_path / name
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    return sessionmaker(bind=test_engine)


def test_fresh_bootstrap_mortgage_accepts_frontend_default_amortization_type(tmp_path, monkeypatch):
    from models.users import User
    from models.clients import Client
    from models.wealth import WealthPosition

    TestSession = _fresh_session(tmp_path, monkeypatch, "fresh_mortgage.db")
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
        session.add_all([user, client])
        session.flush()
        position = WealthPosition(
            id="mortgage-test", client_id="client-test", label="Hypothek Eigenheim",
            position_type="Hypothek", assignment="Verbindlichkeit", current_value_rappen=80_000_000,
            mortgage_bank="ZKB", mortgage_type="Festhypothek",
            mortgage_amortization_type="Indirekt (Säule 3a)",
            created_at=now, updated_at=now,
        )
        session.add(position)
        # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen.
        session.commit()

        stored = session.query(WealthPosition).filter(WealthPosition.id == "mortgage-test").one()
    assert stored.mortgage_amortization_type == "Indirekt (Säule 3a)"


def test_fresh_bootstrap_mortgage_still_accepts_direkt_and_keine(tmp_path, monkeypatch):
    """Regressionsschutz: die bereits vorher gueltigen (und in der echten
    Dev-DB tatsaechlich verwendeten) Werte duerfen nicht verloren gehen."""
    from models.users import User
    from models.clients import Client
    from models.wealth import WealthPosition

    TestSession = _fresh_session(tmp_path, monkeypatch, "fresh_mortgage2.db")
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
        session.add_all([user, client])
        session.flush()
        for idx, amort_type in enumerate(("Direkt", "Keine", None)):
            session.add(WealthPosition(
                id=f"mortgage-test-{idx}", client_id="client-test", label="Hypothek",
                position_type="Hypothek", assignment="Verbindlichkeit", current_value_rappen=10_000_000,
                mortgage_amortization_type=amort_type,
                created_at=now, updated_at=now,
            ))
        session.commit()
        stored = {row.mortgage_amortization_type for row in session.query(WealthPosition).all()}
    assert stored == {"Direkt", "Keine", None}
