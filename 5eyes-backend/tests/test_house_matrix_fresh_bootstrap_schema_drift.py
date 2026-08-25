"""Live-Smoketest-Fund (2026-08-06): auf einer fabrikneuen, per Raw-SQL
(5eyes_schema_v4.0_FINAL.sql) gebooteten Installation (= der echte init_db()-
Pfad, der JEDE echte Erstinstallation betrifft) crashte die allererste
Zielallokation-Generierung eines Mandanten mit einem rohen 500
(sqlite3.IntegrityError: CHECK constraint failed: profile_name) --
_ensure_runtime_reference_data_ch() seedet beim allerersten Aufruf eine
Default-HouseMatrix mit profile_name='Wachstumsorientiert' (siehe
ALLOWED_HOUSE_MATRIX_PROFILES in services/portfolio_engine.py), aber der
CHECK-Constraint im rohen Schema-SQL erlaubte noch den veralteten Namen
'Wachstum'.

Das reale, seit langem existierende Dev/Produktions-DB betrifft das nicht
(die bereits vorhandenen house_matrix-Zeilen wurden vor diesem Rename
angelegt und werden nie neu geseedet -- profile_name wird ausserdem NIE
als Lookup-Key verwendet, siehe _house_matrix_or_default(), nur
score_from/score_to), aber JEDE neue Tier-1-Erstinstallation trifft
exakt diesen Pfad beim ersten `/target-allocation/generate`-Aufruf.
Gleiche Bugklasse wie test_a2_target_allocations_schema_drift.py (dort:
fehlende Spalten; hier: veralteter CHECK-Constraint-Wert) -- beide nur
auf einer wirklich frischen, per Raw-SQL gebooteten DB sichtbar, nicht
auf der langjaehrigen Dev-DB.

Die dritte Testfunktion unten pinnt zusaetzlich risk_assessments.
final_profile/.override_profile (dieselbe 'Wachstumsorientiert'-
Aufzaehlung) -- diese beiden Constraints waren in der Commit-History
nie fehlerhaft, die Zeile deckt aber dieselbe Bugklasse defensiv ab,
falls sie kuenftig aus dem Sync mit ALLOWED_HOUSE_MATRIX_PROFILES laufen.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Alle Model-Module importieren, damit SQLAlchemys Mapper-Registry beim
# ersten session.query() vollstaendig konfiguriert ist (Mandate.client
# referenziert 'Client' per String -- ohne diesen Import schlaegt jede
# Query mit einem InvalidRequestError fehl, siehe test_optimizer_shadow_
# mode.py fuer das etablierte Muster).
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401,E501
configure_mappers()


def test_fresh_bootstrap_house_matrix_check_constraint_allows_all_used_profile_names(tmp_path, monkeypatch):
    """Der house_matrix.profile_name-CHECK-Constraint im rohen Schema-SQL muss
    JEDEN Wert aus ALLOWED_HOUSE_MATRIX_PROFILES zulassen -- sonst crasht das
    Default-Seeding auf jeder echten Erstinstallation."""
    import database as db_module
    from services.portfolio_engine import ALLOWED_HOUSE_MATRIX_PROFILES
    from models.allocation import HouseMatrix, OptimizerPolicy

    db_path = tmp_path / "fresh_house_matrix.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")

    TestSession = sessionmaker(bind=test_engine)
    now = "2026-08-06T00:00:00.000Z"
    with TestSession() as session:
        policy = OptimizerPolicy(
            id="policy-test", policy_name="Test", version=1, is_current=1,
            valid_from="2026-08-06", optimizer_engine="goal_based_v1",
            created_by="tester", created_at=now, updated_at=now,
        )
        session.add(policy)
        session.flush()
        for idx, profile_name in enumerate(ALLOWED_HOUSE_MATRIX_PROFILES):
            session.add(HouseMatrix(
                id=f"hm-test-{idx}", policy_id=policy.id,
                score_from=idx + 1, score_to=idx + 1, profile_name=profile_name,
                liq_min_bps=0, liq_target_bps=100, liq_max_bps=1000,
                bonds_min_bps=0, bonds_target_bps=1000, bonds_max_bps=5000,
                equity_min_bps=0, equity_target_bps=8900, equity_max_bps=10000,
                real_estate_min_bps=0, real_estate_target_bps=0, real_estate_max_bps=2000,
                alt_min_bps=0, alt_target_bps=0, alt_max_bps=1000,
                max_risky_fraction_bps=5000,
                is_active=1, created_at=now, updated_at=now,
            ))
        # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen.
        session.commit()

        stored = {row.profile_name for row in session.query(HouseMatrix).all()}
    assert stored == set(ALLOWED_HOUSE_MATRIX_PROFILES)


def test_fresh_bootstrap_first_target_allocation_generation_does_not_crash(tmp_path, monkeypatch):
    """End-to-End-Pin: der reale Auto-Seeding-Pfad (_ensure_runtime_reference_
    data_ch, ausgeloest von der allerersten Zielallokation-Generierung in
    einer Erstinstallation) muss auf einer fabrikneuen DB durchlaufen."""
    import database as db_module

    db_path = tmp_path / "fresh_first_alloc.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()

    from services.portfolio_engine import _ensure_runtime_reference_data_ch
    from models.allocation import HouseMatrix

    TestSession = sessionmaker(bind=test_engine)
    with TestSession() as session:
        policy, cma = _ensure_runtime_reference_data_ch(session, "tester")
        session.commit()
        rows = session.query(HouseMatrix).filter(HouseMatrix.policy_id == policy.id).all()
    assert len(rows) == 6
    assert any(r.profile_name == "Wachstumsorientiert" for r in rows)


def test_fresh_bootstrap_risk_assessment_accepts_wachstumsorientiert_final_and_override_profile(tmp_path, monkeypatch):
    """Defensiver Guard (siehe Moduldocstring): risk_assessments.final_profile
    und .override_profile nutzen dieselbe Profil-Aufzaehlung wie
    house_matrix.profile_name -- pinnt, dass beide Constraints weiterhin
    'Wachstumsorientiert' akzeptieren, falls sie kuenftig unabhaengig
    voneinander bearbeitet werden."""
    import database as db_module
    from models.users import User
    from models.clients import Client
    from models.mandates import Mandate
    from models.profiling import RiskAssessment

    db_path = tmp_path / "fresh_risk_assessment.db"
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
            country_of_residence="CH", advisor_id="user-test",
            created_at=now, updated_at=now,
        )
        mandate = Mandate(
            id="mandate-test", client_id="client-test", mandate_number="M-TEST-1",
            mandate_type="Vermögensverwaltung", opened_at="2026-08-06",
            created_at=now, updated_at=now,
        )
        session.add_all([user, client, mandate])
        session.flush()
        assessment = RiskAssessment(
            id="ra-test", mandate_id="mandate-test", version=1, is_current=1, valid_from="2026-08-06",
            q_income_points=3, q_obligations_points=1, q_savings_points=6, q_wealth_points=9,
            risk_capacity_total=19, risk_capacity_profile="Wachstumsorientiert",
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            risk_capacity_score_x10=70,
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70,
            final_score_x10=70, final_profile="Wachstumsorientiert",
            is_overridden=1, override_score_x10=70, override_profile="Wachstumsorientiert",
            override_by="user-test", override_at=now, override_reason="Test",
            knowledge_services_json="{}", knowledge_instruments_json="{}", income_sources_json="[]",
            assessed_at=now, assessed_by="user-test", created_at=now, updated_at=now,
        )
        session.add(assessment)
        # Darf NICHT mit sqlite3.IntegrityError (CHECK constraint failed) crashen.
        session.commit()

        stored = session.query(RiskAssessment).filter(RiskAssessment.id == "ra-test").one()
    assert stored.final_profile == "Wachstumsorientiert"
    assert stored.override_profile == "Wachstumsorientiert"
