"""Live-Smoketest-Fund (2026-08-09): dieselbe Bugklasse wie in
test_contract_documents_fresh_bootstrap_schema_drift.py -- gefunden waehrend
eines Live-Playwright-Tests des neuen Portfolio-Handoff-Features (der Test
brauchte einen Foundation-Case mit echten Trades), NICHT durch dieses Feature
selbst verursacht.

services/foundation_example.py::upsert_foundation_example_case() setzte
RiskAssessmentAnswer.question_section auf 'Kenntnisse' und 'Risikofaehigkeit'
(ASCII, ohne " & Erfahrungen"-Suffix) -- der rohe Bootstrap-Schema-CHECK-
Constraint (5eyes_schema_v4.0_FINAL.sql, von init_db() bei JEDER echten
Erstinstallation ausgefuehrt) erlaubt aber nur exakt 'Kenntnisse & Erfahrungen',
'Risikofähigkeit', 'Risikobereitschaft' (database.py:692). Auf jeder frischen
Installation crasht der Foundation-Case-Aufbau daher mit einem rohen
sqlite3.IntegrityError -- unbemerkt, weil test_stage8_foundation_smoketest.py
und alle anderen Aufrufer ausschliesslich gegen Base.metadata.create_all()
testen (kein Raw-SQL-Bootstrap, RiskAssessmentAnswer.question_section ist dort
eine ungeprüfte String-Spalte ohne CHECK-Constraint).

Ruft bewusst die ECHTE init_db() auf (statt einzelne Migrations-Schritte
manuell nachzustellen -- ein erster Versuch mit nur bootstrap_sqlite_schema()
+ create_all() + ensure_runtime_columns() schlug an zwei weiteren, hier
irrelevanten Stellen fehl: fehlende Tabelle wealth_inflows, fehlende Spalte
advisory_log.recommendation_run_id -- beide werden von SEPARATEN init_db()-
Schritten angelegt). init_db() ist damit die einzige Stelle, die garantiert
denselben Endzustand wie eine echte Erstinstallation erzeugt.
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


def test_fresh_bootstrap_foundation_example_accepts_risk_answer_sections(tmp_path, monkeypatch):
    import database as db_module
    from config import settings
    from models.profiling import RiskAssessmentAnswer
    from models.users import User
    from services.foundation_example import upsert_foundation_example_case

    db_path = tmp_path / "fresh_foundation_example.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(settings, "db_path", str(db_path))
    # init_db() repliziert exakt den Boot-Pfad einer echten Erstinstallation
    # (Raw-SQL-Bootstrap mit CHECK-Constraints -> create_all()-Supplement ->
    # alle ensure_*/migrate_*-Schritte in derselben Reihenfolge wie main.py).
    db_module.init_db()

    TestSession = sessionmaker(bind=test_engine)
    now = "2026-08-09T00:00:00.000Z"
    with TestSession() as session:
        advisor = User(
            id="advisor-foundation-drift", username="advisor-foundation-drift",
            password_hash="x", full_name="Foundation Advisor",
            role="advisor", is_active=1, created_at=now, updated_at=now,
        )
        session.add(advisor)
        session.commit()

        # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen.
        upsert_foundation_example_case(session, advisor)
        session.commit()

        sections = {
            row.question_section
            for row in session.query(RiskAssessmentAnswer).all()
        }
    assert sections == {"Kenntnisse & Erfahrungen", "Risikofähigkeit", "Risikobereitschaft"}
