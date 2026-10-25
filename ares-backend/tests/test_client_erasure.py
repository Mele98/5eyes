"""Sprint 2026-08-15 (DSG Art. 32 -- Recht auf Loeschung / Erasure).

Testet POST /clients/{client_id}/erase (routers/clients.py::erase_client,
services/client_erasure.py::erase_client_personal_data):

- Happy path: direkt identifizierende Felder werden auf allen Tier-A-
  Tabellen redigiert (Client-Kernidentitaet, Mandat-Bankverbindung,
  Vermoegen/Cashflow-Notizen/Adressen, Vertragsdokument-Signaturen,
  Kundenportal-Login).
- Cascade-Vollstaendigkeit: NACH der Erasure ist keine direkt
  identifizierende Personenangabe fuer diesen Kunden mehr in der DB
  vorhanden (ausser dem Redaction-Marker selbst).
- Tier-B-Tabellen (FIDLEG-Pflichtdokumentation: advisory_log,
  risk_assessments, suitability_checks) bleiben unveraendert -- Design-
  Entscheidung, siehe services/client_erasure.py Modul-Docstring.
- audit_log-Zeilen ÜBERLEBEN unveraendert (nicht geloescht, nicht
  mutiert) -- weil harte SQLite-Trigger (trg_audit_log_no_update/
  _no_delete) das technisch erzwingen. Die Erasure-Aktion selbst wird
  als neuer, normaler Audit-Log-Eintrag schreiben (auditierbar: wer hat
  wann wen aus welchem Grund geloescht).
- Nur Admin/Super-Admin darf loeschen; Pflichtbegruendung (Qualitaets-
  Check); idempotent-sicher (409 bei Doppelaufruf); 404 fuer unbekannte
  Kunden; funktioniert auch fuer bereits (soft-)geloeschte Kunden.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_audit_log_triggers, get_db
from main import app
from models import (  # noqa: F401
    allocation,
    client_login,
    clients,
    mandates,
    profiling,
    protocol_bausteine,
    refresh_token,
    review,
    snapshots,
    users,
    wealth,
)
from models.review import AuditLog
from services.auth import get_current_user, require_admin
from services.client_erasure import REDACTION_MARKER


NOW = "2026-08-15T10:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client_erasure.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    # Base.metadata.create_all() kennt keine DB-Trigger (nur Spalten/Tabellen)
    # -- die audit_log-Unveraenderlichkeit wird separat via Startup-Migration
    # gesetzt (database.py::ensure_audit_log_triggers). Ohne diesen Aufruf
    # wuerde der Immutability-Test unten falsch-positiv durchlaufen.
    ensure_audit_log_triggers(engine)
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

    admin = SimpleNamespace(
        id="admin-erasure", full_name="Admin Erasure", email="admin@example.test",
        role="admin", tenant_id=None,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def advisor_client(session_factory):
    """Non-admin caller -- used to prove the endpoint rejects it (require_admin
    is NOT overridden here, so the real role check in services.auth runs)."""
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    advisor = SimpleNamespace(
        id="advisor-erasure", full_name="Advisor Erasure", email="advisor@example.test",
        role="advisor", tenant_id=None,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _exec(session, sql: str, params: dict | None = None) -> None:
    session.execute(text(sql), params or {})


def _scalar(session, sql: str, params: dict | None = None):
    return session.execute(text(sql), params or {}).scalar()


def _seed_admin(session) -> None:
    _exec(
        session,
        """
        INSERT INTO users (
            id, username, password_hash, full_name, role, is_active,
            totp_enabled, must_change_password, created_at, updated_at
        )
        VALUES ('admin-erasure', 'admin-erasure', 'h', 'Admin Erasure', 'admin',
                1, 0, 0, :now, :now)
        """,
        {"now": NOW},
    )


def _seed_full_client_chain(session, *, client_id: str = "client-e1") -> dict:
    """Legt einen Kunden mit vollem Fussabdruck an: Mandat, Risikoprofil,
    Beratungsprotokoll, Vertragsdokument (mit Signatur), Vermoegen/
    Cashflow/Ziele, Kundenportal-Login + Refresh-Token. Deckt alle
    Tier-A- (zu redigieren) und Tier-B- (unveraendert) Tabellen ab, die
    services/client_erasure.py anfasst bzw. bewusst nicht anfasst.
    """
    _seed_admin(session)
    _exec(
        session,
        """
        INSERT INTO clients (
            id, client_number, salutation, first_name, last_name, date_of_birth,
            country_of_residence, canton, civil_status, profession, employer,
            partner_salutation, partner_first_name, partner_last_name,
            partner_date_of_birth, partner_profession,
            language, household_type, client_classification,
            is_professional_opt_out, is_qualified_investor,
            advisor_id, notes, created_at, updated_at
        )
        VALUES (
            :id, 'E-001', 'Herr', 'Hans', 'Muster', '1970-01-01',
            'CH', 'ZH', 'verheiratet', 'Ingenieur', 'ACME AG',
            'Frau', 'Erika', 'Muster', '1972-02-02', 'Lehrerin',
            'DE', 'Paar', 'Privatkunde',
            0, 0,
            'admin-erasure', 'Kunde bevorzugt Telefonkontakt, wohnt an der Bahnhofstrasse',
            :now, :now
        )
        """,
        {"id": client_id, "now": NOW},
    )
    _exec(
        session,
        "INSERT INTO client_nationalities (id, client_id, country_code, is_primary, created_at) "
        "VALUES ('nat-e1', :cid, 'CH', 1, :now)",
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO client_opt_history (
            id, client_id, event_type, from_classification, to_classification,
            client_requested, documented_by, documented_at, notes, created_at
        )
        VALUES ('opt-e1', :cid, 'create', 'Privatkunde', 'Privatkunde',
                1, 'admin-erasure', :now, 'Erstgespraech mit Hans Muster am Hauptsitz', :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO mandates (
            id, client_id, mandate_number, mandate_type, status, base_currency,
            advisory_language, investment_universe, depot_bank, depot_account_number,
            client_birth_year, client_sex, opened_at, created_at, updated_at
        )
        VALUES ('mandate-e1', :cid, 'M-E-001', 'Anlageberatung', 'Aktiv', 'CHF',
                'DE', 'Standard', 'UBS', 'CH93-0000-0000-0000-0000-1', 1970, 'M',
                :now, :now, :now)
        """,
        {"cid": client_id, "now": NOW},
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
            'assessment-e1', 'mandate-e1', 1, 1, :now,
            1, 1, 1, 1, 4, 'Mittel', 10, 'Langfristig', 500,
            1, 1, 1, 3, 'Mittel', 500, 500, 'Ausgewogen', 0, 0, 0,
            :now, 'admin-erasure', :now, :now
        )
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO suitability_checks (
            id, mandate_id, client_id, duty_type, result, result_notes,
            client_proceeding_despite, warning_delivered, client_acknowledged,
            checked_by, checked_at, created_at, updated_at
        )
        VALUES ('suitability-e1', 'mandate-e1', :cid, 'suitability', 'ok',
                'Eignung fuer Hans Muster bestaetigt', 0, 0, 0,
                'admin-erasure', :now, :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO advisory_log (
            id, mandate_id, entry_type, title, description, status, advisor_id,
            client_signed, entry_date, cost_disclosure_given,
            version, created_at, updated_at
        )
        VALUES ('advisory-e1', 'mandate-e1', 'beratung', 'Erstberatung',
                'Gespraech mit Hans Muster ueber Anlagestrategie', 'Empfohlen', 'admin-erasure',
                0, :now, 0, 1, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO contract_documents (
            id, mandate_id, document_type, title, content_json, pdf_path,
            checksum_sha256, status, signed_by_advisor, signed_by_client,
            signature_advisor_image, signature_advisor_signer_name, signature_advisor_ip,
            signature_client_image, signature_client_signer_name, signature_client_ip,
            version, created_by, created_at, updated_at
        )
        VALUES (
            'doc-e1', 'mandate-e1', 'Anlageberatungsvertrag', 'Vertrag Hans Muster',
            '{"client_name": "Hans Muster"}', '/tmp/hans-muster.pdf',
            'deadbeef', 'Unterzeichnet', 1, 1,
            'data:image/png;base64,ADVISORSIG', 'Admin Erasure', '10.0.0.1',
            'data:image/png;base64,CLIENTSIG', 'Hans Muster', '10.0.0.2',
            1, 'admin-erasure', :now, :now
        )
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO cashflows (
            id, client_id, cashflow_type, label, amount_rappen, currency, frequency,
            nature, is_inflation_linked, notes, is_active, created_at, updated_at
        )
        VALUES ('cashflow-e1', :cid, 'Income', 'Lohn', 12000000, 'CHF', 'jaehrlich',
                'wiederkehrend', 0, 'Hans erhaelt Bonus jeweils im Maerz', 1, :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO wealth_positions (
            id, client_id, label, position_type, assignment, current_value_rappen,
            currency, property_address, property_zip_city, depot_bank,
            depot_account_number, mortgage_bank, notes,
            alloc_equities_bps, alloc_bonds_bps, alloc_real_estate_bps,
            alloc_liquidity_bps, alloc_alternatives_bps, property_rental_income_rappen,
            mortgage_amortization_rappen, pension_wef_possible, is_available_for_goal_funding,
            is_active, created_at, updated_at
        )
        VALUES (
            'wealth-e1', :cid, 'Eigenheim', 'Immobilie', 'Sockel', 150000000, 'CHF',
            'Bahnhofstrasse 1', '8001 Zuerich', 'UBS', 'CH93-...-1', 'UBS',
            'Erbstueck der Familie Muster',
            0, 0, 10000, 0, 0, 0, 0, 0, 0, 1, :now, :now
        )
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO wealth_inflows (
            id, client_id, label, source_type, amount_rappen, expected_year,
            is_recurring, value_mode, notes, is_active, created_at, updated_at
        )
        VALUES ('inflow-e1', :cid, 'Erbschaft', 'Erbschaft', 50000000, 2028,
                0, 'nominal', 'Erbschaft von Vater Muster erwartet', 1, :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO goals (
            id, mandate_id, client_id, goal_family, goal_type, label, rank,
            goal_scope, value_mode, is_ongoing, hardness, probability_pct,
            notes, is_active, created_at, updated_at
        )
        VALUES ('goal-e1', 'mandate-e1', :cid, 'Vermoegen', 'Vermoegensziel',
                'Ruhestand Hans Muster', 1, 'Beratungsvermoegen', 'nominal', 0,
                'Primaer', 100, 'Ziel: Ruhestand mit 63 wie mit Hans besprochen',
                1, :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO planning_assumptions (
            id, mandate_id, client_id, version, is_current, valid_from, notes,
            created_at, updated_at
        )
        VALUES ('planning-e1', 'mandate-e1', :cid, 1, 1, :now,
                'Pensionierung mit 63 gemaess Absprache mit Hans', :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO client_knowledge (
            id, client_id, version, is_current, valid_from, knowledge_level,
            exp_equities, exp_bonds, exp_funds, exp_derivatives, exp_alternatives,
            exp_structured, confirmed_at, confirmed_by, created_at, updated_at
        )
        VALUES ('knowledge-e1', :cid, 1, 1, :now, 'Mittel',
                'Keine', 'Keine', 'Keine', 'Keine', 'Keine', 'Keine',
                :now, 'admin-erasure', :now, :now)
        """,
        {"cid": client_id, "now": NOW},
    )
    # Kundenportal-Login: eigenes User-Konto des Kunden.
    _exec(
        session,
        """
        INSERT INTO users (
            id, username, password_hash, full_name, email, role, is_active,
            totp_enabled, totp_secret, must_change_password, created_at, updated_at
        )
        VALUES ('client-user-e1', 'hans.muster', 'h', 'Hans Muster', 'hans@example.test',
                'client', 1, 1, 'SECRETBASE32', 0, :now, :now)
        """,
        {"now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO client_logins (id, user_id, client_id, created_by, created_at, is_active)
        VALUES ('login-e1', 'client-user-e1', :cid, 'admin-erasure', :now, 1)
        """,
        {"cid": client_id, "now": NOW},
    )
    _exec(
        session,
        """
        INSERT INTO refresh_tokens (
            id, user_id, token_hash, family_id, created_at, expires_at, revoked_at
        )
        VALUES ('rt-e1', 'client-user-e1', 'hashvalue', 'family-e1', :now, :now, NULL)
        """,
        {"now": NOW},
    )
    session.commit()
    return {"client_id": client_id, "mandate_id": "mandate-e1", "user_id": "client-user-e1"}


# ---------------------------------------------------------------------------
# Happy path + cascade completeness
# ---------------------------------------------------------------------------

def test_erase_client_redacts_all_tier_a_pii_and_returns_summary(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde hat schriftlich sein Recht auf Loeschung nach DSG Art. 32 geltend gemacht."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "erased"
    assert payload["client_id"] == ids["client_id"]
    assert payload["redacted"]["clients"] == 1
    assert payload["redacted"]["mandates"] == 1
    assert payload["redacted"]["wealth_positions"] == 1
    assert payload["redacted"]["contract_documents"] == 1
    assert payload["redacted"]["users"] == 1

    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT salutation, first_name, last_name, date_of_birth, canton, "
                "civil_status, profession, employer, partner_salutation, "
                "partner_first_name, partner_last_name, partner_date_of_birth, "
                "partner_profession, notes, erased_at, erasure_reason, deleted_at "
                "FROM clients WHERE id = :id"
            ),
            {"id": ids["client_id"]},
        ).one()
        for value in row[:14]:
            assert value == REDACTION_MARKER, row
        assert row.erased_at is not None
        assert "DSG Art. 32" in row.erasure_reason
        assert row.deleted_at is not None

        assert _scalar(session, "SELECT notes FROM client_opt_history WHERE id='opt-e1'") == REDACTION_MARKER

        mandate = session.execute(
            text(
                "SELECT depot_bank, depot_account_number, client_sex, client_birth_year "
                "FROM mandates WHERE id='mandate-e1'"
            )
        ).one()
        assert mandate.depot_bank == REDACTION_MARKER
        assert mandate.depot_account_number == REDACTION_MARKER
        assert mandate.client_sex == REDACTION_MARKER
        assert mandate.client_birth_year is None

        wealth = session.execute(
            text(
                "SELECT property_address, property_zip_city, depot_bank, "
                "depot_account_number, mortgage_bank, notes "
                "FROM wealth_positions WHERE id='wealth-e1'"
            )
        ).one()
        for value in wealth:
            assert value == REDACTION_MARKER

        assert _scalar(session, "SELECT notes FROM cashflows WHERE id='cashflow-e1'") == REDACTION_MARKER
        assert _scalar(session, "SELECT notes FROM wealth_inflows WHERE id='inflow-e1'") == REDACTION_MARKER
        assert _scalar(session, "SELECT notes FROM goals WHERE id='goal-e1'") == REDACTION_MARKER
        assert _scalar(session, "SELECT notes FROM planning_assumptions WHERE id='planning-e1'") == REDACTION_MARKER

        doc = session.execute(
            text(
                "SELECT title, content_json, pdf_path, checksum_sha256, "
                "signature_advisor_image, signature_advisor_signer_name, signature_advisor_ip, "
                "signature_client_image, signature_client_signer_name, signature_client_ip "
                "FROM contract_documents WHERE id='doc-e1'"
            )
        ).one()
        for value in doc:
            assert value == REDACTION_MARKER

        # Kundenportal-Login deaktiviert + eigenes User-Konto redigiert.
        user = session.execute(
            text("SELECT full_name, email, is_active, totp_secret FROM users WHERE id='client-user-e1'")
        ).one()
        assert user.full_name == REDACTION_MARKER
        assert user.email == REDACTION_MARKER
        assert user.is_active == 0
        assert user.totp_secret is None
        assert _scalar(session, "SELECT is_active FROM client_logins WHERE id='login-e1'") == 0
        assert _scalar(session, "SELECT revoked_at FROM refresh_tokens WHERE id='rt-e1'") is not None

        # Freitextsuche: kein "Hans" / "Muster" / "Bahnhofstrasse" mehr in
        # irgendeiner Tier-A-Tabelle -- Cascade-Vollstaendigkeit.
        for table, columns in [
            ("clients", ["first_name", "last_name", "notes"]),
            ("wealth_positions", ["property_address", "notes"]),
            ("cashflows", ["notes"]),
            ("goals", ["notes"]),
            ("contract_documents", ["title", "content_json"]),
            ("users", ["full_name", "email"]),
        ]:
            for col in columns:
                val = session.execute(text(f"SELECT {col} FROM {table}")).scalar()
                assert val is None or "Hans" not in str(val)
                assert val is None or "Muster" not in str(val)
                assert val is None or "Bahnhofstrasse" not in str(val)


def test_erase_client_leaves_tier_b_fideleg_records_untouched(admin_client, session_factory):
    """Beratungsprotokoll, Risikoprofil, Eignungspruefung sind FIDLEG-
    Pflichtdokumentation (10 Jahre Aufbewahrung) -- bewusst NICHT Teil
    der Erasure, siehe services/client_erasure.py Modul-Docstring."""
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text

    with session_factory() as session:
        advisory = session.execute(
            text("SELECT title, description FROM advisory_log WHERE id='advisory-e1'")
        ).one()
        assert advisory.title == "Erstberatung"
        assert advisory.description == "Gespraech mit Hans Muster ueber Anlagestrategie"

        assessment = session.execute(
            text("SELECT final_profile FROM risk_assessments WHERE id='assessment-e1'")
        ).one()
        assert assessment.final_profile == "Ausgewogen"

        suitability = session.execute(
            text("SELECT result_notes FROM suitability_checks WHERE id='suitability-e1'")
        ).one()
        assert suitability.result_notes == "Eignung fuer Hans Muster bestaetigt"


# ---------------------------------------------------------------------------
# Audit log: survives unmodified, immutability trigger not weakened
# ---------------------------------------------------------------------------

def test_erase_client_writes_auditable_clientase_event(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text

    with session_factory() as session:
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "CLIENT_ERASE", AuditLog.client_id == ids["client_id"])
            .one()
        )
        assert entry.user_id == "admin-erasure"
        assert entry.table_name == "clients"
        assert entry.record_id == ids["client_id"]
        assert "DSG Art. 32" in (entry.new_value or "")
        assert entry.integrity_hash


def test_erase_client_does_not_delete_or_mutate_pre_existing_audit_rows(admin_client, session_factory):
    """Kernaussage der Design-Entscheidung: audit_log-Zeilen ueber den
    Kunden von VOR der Erasure bleiben byte-identisch erhalten -- sie
    werden weder geloescht noch redigiert (das waere technisch ein
    UPDATE/DELETE, das der DB-Trigger ohnehin verwirft)."""
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        # Ein "historischer" Audit-Eintrag, der den Klarnamen referenziert
        # (alte CREATE-Aktion, wie sie routers/clients.py::create_client
        # normalerweise schreiben wuerde).
        from services.audit import log as audit_log_fn
        audit_log_fn(
            session, user_id="admin-erasure", user_name="Admin Erasure",
            table_name="clients", record_id=ids["client_id"], action="CREATE",
            new_value="Hans Muster", client_id=ids["client_id"],
        )
        session.commit()
        before = session.query(AuditLog).filter(AuditLog.action == "CREATE").one()
        before_hash = before.integrity_hash
        before_new_value = before.new_value

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text

    with session_factory() as session:
        after = session.query(AuditLog).filter(AuditLog.action == "CREATE").one()
        assert after.integrity_hash == before_hash
        assert after.new_value == before_new_value == "Hans Muster"

        # Trigger-Beweis: ein direkter UPDATE-Versuch auf audit_log wird
        # weiterhin hart verworfen -- die Erasure hat die Unveraenderlich-
        # keits-Garantie NICHT aufgeweicht.
        with pytest.raises(Exception):
            session.execute(
                text("UPDATE audit_log SET new_value = 'tampered' WHERE id = :id"),
                {"id": after.id},
            )
            session.commit()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

def test_erase_client_rejects_non_admin(advisor_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = advisor_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 403

    with session_factory() as session:
        assert _scalar(session, "SELECT first_name FROM clients WHERE id=:id", {"id": ids["client_id"]}) == "Hans"


def test_erase_client_requires_meaningful_reason(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = admin_client.post(f"/clients/{ids['client_id']}/erase", json={"reason": "ok"})
    assert response.status_code == 422

    with session_factory() as session:
        assert _scalar(session, "SELECT first_name FROM clients WHERE id=:id", {"id": ids["client_id"]}) == "Hans"


# ---------------------------------------------------------------------------
# Idempotency + not-found + already-soft-deleted
# ---------------------------------------------------------------------------

def test_erase_client_is_idempotent_guarded_with_409(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    first = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert first.status_code == 200, first.text

    second = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Zweiter Versuch, sollte als bereits erledigt erkannt werden."},
    )
    assert second.status_code == 409


def test_erase_client_404_for_unknown_client(admin_client):
    response = admin_client.post(
        "/clients/does-not-exist/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 404


def test_erase_client_works_on_already_soft_deleted_client(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        _exec(session, "UPDATE clients SET deleted_at = :now WHERE id = :id", {"now": NOW, "id": ids["client_id"]})
        session.commit()

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text
