from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation,
    client_login,
    clients,
    mandates,
    portfolio_handoff,
    profiling,
    protocol_bausteine,
    review,
    snapshots,
    users,
    wealth,
)
from models.review import AuditLog
from routers import system as system_router
from services.auth import require_admin
from services.foundation_example import FOUNDATION_CLIENT_NUMBER, FOUNDATION_MANDATE_NUMBER
from services.foundation_purge import PRODUCTION_BLOCK_DETAIL


NOW = "2026-06-17T10:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'foundation_purge.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin = SimpleNamespace(id="admin-purge", full_name="Admin Purge", email="admin@example.test")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _exec(session, sql: str, params: dict | None = None) -> None:
    session.execute(text(sql), params or {})


def _scalar(session, sql: str, params: dict | None = None) -> int:
    return int(session.execute(text(sql), params or {}).scalar() or 0)


def _seed_admin(session) -> None:
    _exec(
        session,
        """
        INSERT INTO users (
            id, username, password_hash, full_name, role, is_active,
            totp_enabled, must_change_password, created_at, updated_at
        )
        VALUES ('admin-purge', 'admin-purge', 'h', 'Admin Purge', 'admin',
                1, 0, 0, :now, :now)
        """,
        {"now": NOW},
    )


def _seed_policy_and_product(session) -> None:
    _exec(
        session,
        """
        INSERT INTO optimizer_policies (
            id, policy_name, version, is_current, valid_from, optimizer_engine,
            max_real_estate_bps, max_alternatives_bps, min_liquidity_bps,
            allow_other_assets_for_goals, created_by, created_at, updated_at
        )
        VALUES ('policy-purge', 'Policy', 1, 1, :now, 'goal_based_v1',
                2000, 1000, 0, 1, 'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO products (
            id, product_name, product_type, asset_class, currency, is_active, created_at, updated_at
        )
        VALUES ('product-purge', 'Demo Fund', 'ETF', 'Aktien', 'CHF', 1, :now, :now)
        """,
        {"now": NOW},
    )


def _seed_foundation_chain(session) -> str:
    _seed_admin(session)
    _seed_policy_and_product(session)
    _exec(
        session,
        """
        INSERT INTO clients (
            id, client_number, first_name, last_name, country_of_residence,
            language, household_type, client_classification,
            is_professional_opt_out, is_qualified_investor,
            advisor_id, created_at, updated_at, deleted_at
        )
        VALUES ('client-foundation', :client_number, 'Daniel', 'Beispiel', 'CH',
                'DE', 'Einzelperson', 'Privatkunde', 0, 0,
                'admin-purge', :now, :now, :now)
        """,
        {"client_number": FOUNDATION_CLIENT_NUMBER, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO mandates (
            id, client_id, mandate_number, mandate_type, status, base_currency,
            advisory_language, investment_universe, opened_at, created_at, updated_at, deleted_at
        )
        VALUES ('mandate-foundation', 'client-foundation', :mandate_number,
                'Anlageberatung', 'Aktiv', 'CHF', 'DE', 'Standard', :now, :now, :now, :now)
        """,
        {"mandate_number": FOUNDATION_MANDATE_NUMBER, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO recommendation_runs (
            id, mandate_id, client_id, policy_id, run_type, result_status,
            other_assets_included, created_by, created_at, updated_at
        )
        VALUES ('run-foundation', 'mandate-foundation', 'client-foundation',
                'policy-purge', 'Initial', 'Draft', 0, 'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO recommendation_positions (
            id, run_id, product_id, target_weight_bps, created_at, updated_at
        )
        VALUES ('position-foundation', 'run-foundation', 'product-purge', 10000, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO recommendation_holdings (
            id, run_id, recommendation_position_id, product_id, source, created_at, updated_at
        )
        VALUES ('holding-foundation', 'run-foundation', 'position-foundation',
                'product-purge', 'manual', :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO risk_assessments (
            id, mandate_id, version, is_current, valid_from,
            q_income_points, q_obligations_points, q_savings_points, q_wealth_points,
            risk_capacity_total, risk_capacity_profile, investment_horizon_years,
            investment_horizon_label, risk_capacity_score_x10,
            q_investment_goal_points, q_risk_preference_points, q_risk_behavior_points,
            risk_willingness_total, risk_willingness_profile, risk_willingness_score_x10,
            final_score_x10, final_profile, is_overridden,
            override_client_confirmed, override_warning_delivered,
            assessed_at, assessed_by, created_at, updated_at
        )
        VALUES (
            'assessment-foundation', 'mandate-foundation', 1, 1, :now,
            1, 1, 1, 1, 4, 'Mittel', 10, 'Langfristig', 500,
            1, 1, 1, 3, 'Mittel', 500, 500, 'Ausgewogen', 0, 0, 0,
            :now, 'admin-purge', :now, :now
        )
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO risk_assessment_answers (
            id, assessment_id, question_number, question_section, answer_label, answer_points, created_at
        )
        VALUES ('answer-foundation', 'assessment-foundation', 1, 'capacity', 'A', 1, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO suitability_checks (
            id, mandate_id, client_id, recommendation_run_id, duty_type, result,
            client_proceeding_despite, warning_delivered, client_acknowledged,
            checked_by, checked_at, created_at, updated_at
        )
        VALUES ('suitability-foundation', 'mandate-foundation', 'client-foundation',
                'run-foundation', 'suitability', 'ok', 0, 0, 0,
                'admin-purge', :now, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO advisory_log (
            id, mandate_id, entry_type, title, recommendation_run_id, status,
            advisor_id, client_signed, entry_date, cost_disclosure_given,
            suitability_check_id, version, created_at, updated_at
        )
        VALUES ('advisory-foundation', 'mandate-foundation', 'recommendation',
                'Demo Beratung', 'run-foundation', 'Empfohlen', 'admin-purge',
                0, :now, 0, 'suitability-foundation', 1, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO strategy_snapshots (
            id, mandate_id, snapshot_date, advisory_assets_rappen,
            risk_profile_score, risk_profile_label,
            soll_equities_bps, soll_bonds_bps, soll_real_estate_bps,
            soll_liquidity_bps, soll_alternatives_bps,
            created_by, created_at, updated_at
        )
        VALUES ('snapshot-foundation', 'mandate-foundation', '2026-06-17',
                10000000, 50, 'Ausgewogen', 4000, 3000, 1000, 1000, 1000,
                'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO cashflows (
            id, client_id, cashflow_type, label, amount_rappen, currency, frequency,
            nature, is_inflation_linked, is_active, created_at, updated_at
        )
        VALUES ('cashflow-foundation', 'client-foundation', 'Income', 'Daniel Lohn',
                12000000, 'CHF', 'jaehrlich', 'wiederkehrend', 0, 1, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO wealth_positions (
            id, client_id, label, position_type, assignment, current_value_rappen,
            currency, alloc_equities_bps, alloc_bonds_bps, alloc_real_estate_bps,
            alloc_liquidity_bps, alloc_alternatives_bps, property_rental_income_rappen,
            mortgage_amortization_rappen, pension_wef_possible, is_available_for_goal_funding,
            is_active, created_at, updated_at
        )
        VALUES ('wealth-foundation', 'client-foundation', 'UBS Advisory Depot',
                'Depot', 'Beratungsvermoegen', 10000000, 'CHF', 5000, 3000,
                0, 2000, 0, 0, 0, 0, 1, 1, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO goals (
            id, mandate_id, client_id, goal_family, goal_type, label, rank,
            goal_scope, value_mode, is_ongoing, hardness, probability_pct,
            is_active, created_at, updated_at
        )
        VALUES ('goal-foundation', 'mandate-foundation', 'client-foundation',
                'Vermoegen', 'Vermoegensziel', 'Demo Ziel', 1,
                'Beratungsvermoegen', 'nominal', 0, 'Primaer', 100, 1, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO planning_assumptions (
            id, mandate_id, client_id, version, is_current, valid_from, created_at, updated_at
        )
        VALUES ('planning-foundation', 'mandate-foundation', 'client-foundation',
                1, 1, :now, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO client_knowledge (
            id, client_id, version, is_current, valid_from, knowledge_level,
            exp_equities, exp_bonds, exp_funds, exp_derivatives, exp_alternatives,
            exp_structured, confirmed_at, confirmed_by, created_at, updated_at
        )
        VALUES ('knowledge-foundation', 'client-foundation', 1, 1, :now, 'Mittel',
                'Keine', 'Keine', 'Keine', 'Keine', 'Keine', 'Keine',
                :now, 'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        "INSERT INTO client_nationalities (id, client_id, country_code, is_primary, created_at) "
        "VALUES ('nat-foundation', 'client-foundation', 'CH', 1, :now)",
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO client_opt_history (
            id, client_id, event_type, from_classification, to_classification,
            client_requested, documented_by, documented_at, created_at
        )
        VALUES ('opt-foundation', 'client-foundation', 'create', 'Privatkunde',
                'Privatkunde', 1, 'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    session.commit()
    return "client-foundation"


def _seed_real_client(session) -> str:
    _seed_admin(session)
    _exec(
        session,
        """
        INSERT INTO clients (
            id, client_number, first_name, last_name, country_of_residence,
            language, household_type, client_classification,
            is_professional_opt_out, is_qualified_investor,
            advisor_id, created_at, updated_at
        )
        VALUES ('client-real', 'REAL-001', 'Real', 'Client', 'CH',
                'DE', 'Einzelperson', 'Privatkunde', 0, 0,
                'admin-purge', :now, :now)
        """,
        {"now": NOW},
    )
    session.commit()
    return "client-real"


def test_foundation_purge_removes_fk_chain_and_writes_audit(admin_client, session_factory):
    with session_factory() as session:
        _seed_foundation_chain(session)

    response = admin_client.post("/admin/system/foundation-example/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "purged"
    assert payload["deleted"]["recommendation_holdings"] == 1
    assert payload["deleted"]["recommendation_positions"] == 1
    assert payload["deleted"]["recommendation_runs"] == 1
    with session_factory() as session:
        for table in [
            "recommendation_holdings",
            "recommendation_positions",
            "recommendation_runs",
            "advisory_log",
            "suitability_checks",
            "strategy_snapshots",
            "risk_assessment_answers",
            "risk_assessments",
            "cashflows",
            "wealth_positions",
            "goals",
            "planning_assumptions",
            "client_knowledge",
            "client_nationalities",
            "client_opt_history",
            "mandates",
            "clients",
        ]:
            assert _scalar(session, f"SELECT COUNT(*) FROM {table}") == 0, table
        assert _scalar(session, "SELECT COUNT(*) FROM products") == 1
        audit = session.query(AuditLog).filter(AuditLog.action == "FOUNDATION_PURGE").one()
        assert audit.table_name == "foundation_example"
        assert audit.record_id == "client-foundation"


def test_foundation_purge_is_idempotent(admin_client, session_factory):
    with session_factory() as session:
        _seed_admin(session)

    response = admin_client.post("/admin/system/foundation-example/purge")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_found"


def test_demo_client_purge_refuses_non_demo_client(admin_client, session_factory):
    with session_factory() as session:
        client_id = _seed_real_client(session)

    response = admin_client.post(f"/admin/system/clients/{client_id}/purge-demo")

    assert response.status_code == 403
    assert response.json()["detail"].startswith("Hard-Purge ist nur fuer")
    with session_factory() as session:
        assert _scalar(session, "SELECT COUNT(*) FROM clients WHERE id='client-real'") == 1


def test_foundation_purge_is_blocked_in_production(admin_client, session_factory, monkeypatch):
    monkeypatch.setattr(system_router.settings, "app_env", "production")
    with session_factory() as session:
        _seed_foundation_chain(session)

    response = admin_client.post("/admin/system/foundation-example/purge")

    assert response.status_code == 403
    assert response.json()["detail"] == PRODUCTION_BLOCK_DETAIL
    with session_factory() as session:
        assert _scalar(session, "SELECT COUNT(*) FROM clients WHERE id='client-foundation'") == 1


# ---------------------------------------------------------------------------
# Kontrollrunde 2026-09-21 (Foundation-Purge-Audit): 4 Befunde.
# ---------------------------------------------------------------------------

def test_foundation_purge_is_blocked_in_staging(admin_client, session_factory, monkeypatch):
    """BUG (vor Fix): der Guard blockte nur woertlich app_env=='production'
    -- 'staging' (von config.py's eigenen security-relevanten Validatoren
    laengst als ebenso schutzwuerdig behandelt, siehe secret_key/TLS/
    strict_tenant_isolation-Checks dort) lief bisher unconditional durch."""
    monkeypatch.setattr(system_router.settings, "app_env", "staging")
    with session_factory() as session:
        _seed_foundation_chain(session)

    response = admin_client.post("/admin/system/foundation-example/purge")

    assert response.status_code == 403
    assert response.json()["detail"] == PRODUCTION_BLOCK_DETAIL
    with session_factory() as session:
        assert _scalar(session, "SELECT COUNT(*) FROM clients WHERE id='client-foundation'") == 1


def test_foundation_purge_must_not_delete_unrelated_real_client_sharing_mandate_number(
    admin_client, session_factory,
):
    """BUG (vor Fix): _foundation_client_ids() mergte JEDEN Mandate.client_id,
    dessen mandate_number zufaellig/versehentlich dem reservierten
    FOUNDATION_MANDATE_NUMBER entsprach -- ein echter Kunde mit einem
    (Tippfehler-/Copy-Paste-)Mandat dieser Nummer wurde damit komplett
    (inkl. aller ANDEREN, unbeteiligten Mandate/Vermoegen/Cashflows)
    mitgeloescht. Fix: Client-Identifikation ausschliesslich ueber
    client_number; das kollidierende Mandat selbst darf weiterhin bereinigt
    werden (eigener, unabhaengiger mandate_number-Match in _load_scope),
    der BESITZENDE Client bleibt aber unangetastet."""
    with session_factory() as session:
        _seed_admin(session)
        _exec(
            session,
            """
            INSERT INTO clients (
                id, client_number, first_name, last_name, country_of_residence,
                language, household_type, client_classification,
                is_professional_opt_out, is_qualified_investor,
                advisor_id, created_at, updated_at
            )
            VALUES ('client-real-2', 'REAL-777', 'Real', 'Client2', 'CH',
                    'DE', 'Einzelperson', 'Privatkunde', 0, 0,
                    'admin-purge', :now, :now)
            """,
            {"now": NOW},
        )
        # Kollidierendes Mandat: traegt versehentlich die reservierte
        # Foundation-Mandatsnummer, gehoert aber einem echten Kunden.
        _exec(
            session,
            """
            INSERT INTO mandates (
                id, client_id, mandate_number, mandate_type, status, base_currency,
                advisory_language, investment_universe, opened_at, created_at, updated_at
            )
            VALUES ('mandate-real-2', 'client-real-2', :mandate_number,
                    'Anlageberatung', 'Aktiv', 'CHF', 'DE', 'Standard', :now, :now, :now)
            """,
            {"mandate_number": FOUNDATION_MANDATE_NUMBER, "now": NOW},
        )
        # Zweites, UNBETEILIGTES Mandat desselben Kunden -- der eigentliche
        # Schadensnachweis: ueberlebt es den Purge?
        _exec(
            session,
            """
            INSERT INTO mandates (
                id, client_id, mandate_number, mandate_type, status, base_currency,
                advisory_language, investment_universe, opened_at, created_at, updated_at
            )
            VALUES ('mandate-real-2-untouched', 'client-real-2', 'REAL-M-777',
                    'Anlageberatung', 'Aktiv', 'CHF', 'DE', 'Standard', :now, :now, :now)
            """,
            {"now": NOW},
        )
        session.commit()

    response = admin_client.post("/admin/system/foundation-example/purge")
    assert response.status_code == 200, response.text
    # Kein Foundation-Client vorhanden -> "not_found", NICHT "purged" mit
    # dem echten Client in client_ids.
    assert response.json()["status"] == "not_found"

    with session_factory() as session:
        assert _scalar(session, "SELECT COUNT(*) FROM clients WHERE id='client-real-2'") == 1
        assert _scalar(session, "SELECT COUNT(*) FROM mandates WHERE id='mandate-real-2-untouched'") == 1


def test_foundation_purge_deletes_portfolio_handoff_without_integrity_error(
    admin_client, session_factory,
):
    """BUG (vor Fix): PortfolioHandoff.mandate_id ist FK NOT NULL --
    portfolio_handoffs fehlte in der Delete-Liste, sodass ein vorhandener
    Handoff das DELETE FROM mandates mit IntegrityError scheitern liess
    (SQLite-FK-Enforcement ist in database.py immer aktiv)."""
    with session_factory() as session:
        client_id = _seed_foundation_chain(session)
        _exec(
            session,
            """
            INSERT INTO portfolio_handoffs (
                id, mandate_id, recommendation_run_id, trade_list_snapshot_json,
                live_total_value_rappen, position_count, recipient_name, status,
                created_by, created_at, updated_at
            )
            VALUES ('handoff-foundation', 'mandate-foundation', 'run-foundation', '[]',
                    1000000, 1, 'UBS AG Zuerich', 'Gesendet',
                    'admin-purge', :now, :now)
            """,
            {"now": NOW},
        )
        session.commit()

    response = admin_client.post("/admin/system/foundation-example/purge")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "purged"
    assert response.json()["deleted"]["portfolio_handoffs"] == 1
    with session_factory() as session:
        assert _scalar(session, "SELECT COUNT(*) FROM portfolio_handoffs") == 0
        assert _scalar(session, "SELECT COUNT(*) FROM mandates") == 0


def test_table_exists_and_columns_use_dialect_agnostic_inspection(session_factory):
    """BUG (vor Fix): _table_exists/_columns fragten sqlite_master/PRAGMA
    table_info direkt ab -- crashte mit ProgrammingError auf Postgres. Der
    Fix nutzt sqlalchemy.inspect(), dialekt-agnostisch. Dieser Test laeuft
    gegen SQLite (kein Postgres-Testserver in dieser Umgebung verfuegbar,
    siehe andere Postgres-Tests/POSTGRES_TEST_DATABASE_URL), verifiziert
    aber, dass die NEUE Implementierung ueberhaupt noch korrekt gegen
    SQLite funktioniert (Regressionsschutz) -- die Dialekt-Unabhaengigkeit
    selbst folgt daraus, dass sqlalchemy.inspect() eine offizielle,
    dialekt-uebergreifende SQLAlchemy-API ist, keine SQLite-spezifische."""
    from services.foundation_purge import _columns, _table_exists

    with session_factory() as session:
        assert _table_exists(session, "clients") is True
        assert _table_exists(session, "this_table_does_not_exist") is False
        cols = _columns(session, "clients")
        assert "client_number" in cols
        assert "id" in cols
        assert _columns(session, "this_table_does_not_exist") == set()
