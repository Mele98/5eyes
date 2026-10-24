"""DSG-ERASURE-APPEND-ONLY-001: append-only Evidence-Tabellen ohne Klartext-
Personendaten, DSG-Art.-32-Erasure per Crypto-Shredding.

risk_override_decisions (RiskOverrideDecisionV1) und risk_profile_signoffs
(RiskProfileSignoffV1) verbieten UPDATE/DELETE per Trigger. Bisher standen
die Freitexte (Override-Begruendung ``reason``, Signatur-Notiz ``note``) dort
-- und in den replaybaren Audit-Snapshots in audit_log -- im Klartext. Eine
Loeschung nach DSG Art. 32 konnte sie weder entfernen noch redigieren, ohne
die Unveraenderlichkeit aufzuweichen.

Vertrag:

* Freitext landet nur noch als versiegelter Umschlag (Fernet, Schluessel pro
  Kunde in client_pii_keys) in den append-only Zeilen und im Audit-Log;
  der Record-Hash bindet den Umschlag.
* Die Erasure vernichtet den Kundenschluessel (Crypto-Shredding) und redigiert
  die veraenderbare Projektion in risk_assessments. Danach ist der Klartext
  in KEINER Tabelle mehr auffindbar; die Record-Hashes bleiben verifizierbar.
* Die Unveraenderlichkeits-Trigger bleiben unangetastet.
"""
from __future__ import annotations

import json
import shutil

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models.client_login  # noqa: F401
from database import Base, ensure_audit_log_triggers
from models.profiling import RiskAssessment, RiskOverrideDecision, RiskProfileSignoff
from models.review import AuditLog
from routers import profiling as profiling_router
from routers.profiling import RiskProfileSignRequest
from services.client_erasure import REDACTION_MARKER, erase_client_personal_data
from services.risk_override_decision import verify_decision
from services.risk_profile_signoff import verify_signoff
from tests.test_risk_capacity_plausibility import _FakeRequest, _seed
from tests.test_risk_override_current_gate_decision_log import (
    VALID_REASON,
    _assessment,
    _override,
)

SIGN_NOTE = "Max Muster hat am 21.10. telefonisch bestaetigt (Tochter Anna anwesend)"
ERASURE_REASON = "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dsg_append_only.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_audit_log_triggers(engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _sign(session, advisor, note=SIGN_NOTE):
    return profiling_router.sign_risk_profile(
        mandate_id="m-rcp",
        request=_FakeRequest(),
        body=RiskProfileSignRequest(note=note),
        db=session,
        current_user=advisor,
    )


def _seed_override_and_signoff(session):
    advisor = _seed(session)
    session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
    session.commit()
    _override(session, advisor, "ra-current", score=60, profile="Ausgewogen")
    _sign(session, advisor)
    return advisor


def _all_text_values(session) -> list[tuple[str, str, str]]:
    """(Tabelle, Spalte, Wert) fuer JEDEN Text-Wert JEDER Tabelle."""
    hits: list[tuple[str, str, str]] = []
    tables = [
        r[0] for r in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ).all()
    ]
    for table in tables:
        cols = [r[1] for r in session.execute(text(f'PRAGMA table_info("{table}")')).all()]
        for row in session.execute(text(f'SELECT * FROM "{table}"')).all():
            for col, value in zip(cols, row):
                if isinstance(value, str):
                    hits.append((table, col, value))
    return hits


def _plaintext_hits(session, needles=(VALID_REASON, "Max Muster", "Tochter Anna")):
    return [
        (table, col)
        for table, col, value in _all_text_values(session)
        if any(needle in value for needle in needles)
    ]


def _decision(session) -> RiskOverrideDecision:
    return session.query(RiskOverrideDecision).filter_by(assessment_id="ra-current").one()


def _signoff(session) -> RiskProfileSignoff:
    return session.query(RiskProfileSignoff).filter_by(assessment_id="ra-current").one()


# ---------------------------------------------------------------------------
# Kein Klartext in append-only Zeilen und Audit-Snapshots
# ---------------------------------------------------------------------------


def test_append_only_rows_and_audit_snapshots_carry_no_plaintext_free_text(session_factory):
    with session_factory() as session:
        _seed_override_and_signoff(session)
        session.expire_all()

        decision = _decision(session)
        signoff = _signoff(session)
        assert VALID_REASON not in decision.reason
        assert "Max Muster" not in (signoff.note or "")

        for entry in session.query(AuditLog).all():
            for value in (entry.old_value, entry.new_value):
                assert VALID_REASON not in (value or ""), entry.field_name
                assert "Max Muster" not in (value or ""), entry.field_name

        # Hash bindet den Umschlag und verifiziert weiterhin.
        assert verify_decision(decision)
        assert verify_signoff(signoff)

        # Fachlich lesbar ueber den Vault (solange der Schluessel existiert).
        from services.pii_vault import is_sealed, reveal

        assert is_sealed(decision.reason)
        assert is_sealed(signoff.note)
        assert reveal(session, decision.reason) == VALID_REASON
        assert reveal(session, signoff.note) == SIGN_NOTE

        # Die veraenderbare Projektion (PDF/Monolith) bleibt lesbar.
        ra = session.get(RiskAssessment, "ra-current")
        assert ra.override_reason == VALID_REASON
        assert ra.client_signed_ref == SIGN_NOTE


def test_signoff_invalidation_audit_does_not_copy_plaintext_note(session_factory):
    """Ein Override nach einer Berater-Signatur schreibt den Invalidierungs-
    Snapshot ins Audit-Log -- bisher inkl. ``client_signed_ref`` = Klartext-
    Notiz, die dann unloeschbar im audit_log stand."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        _sign(session, advisor)
        _override(session, advisor, "ra-current", score=40, profile="Defensiv")

        rows = (
            session.query(AuditLog)
            .filter(AuditLog.field_name == "client_signed_invalidated")
            .all()
        )
        assert len(rows) == 1
        payload = json.loads(rows[0].new_value)
        assert "Max Muster" not in rows[0].new_value
        from services.pii_vault import reveal

        assert reveal(session, payload["invalidated_client_signed_ref"]) == SIGN_NOTE


# ---------------------------------------------------------------------------
# Erasure: Crypto-Shredding, Hashes bleiben verifizierbar, Trigger intakt
# ---------------------------------------------------------------------------


def test_erasure_leaves_no_plaintext_anywhere_and_hashes_stay_verifiable(session_factory):
    with session_factory() as session:
        _seed_override_and_signoff(session)
        before_decision_hash = _decision(session).decision_hash
        before_signoff_hash = _signoff(session).signoff_hash
        assert _plaintext_hits(session)  # Projektion traegt den Klartext noch

        summary = erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()
        session.expire_all()

        assert summary["pii_keys_shredded"] == 1
        assert summary["unsealed_append_only_rows"] == {}

        # Kern-Nachweis: in KEINER Tabelle mehr Klartext.
        assert _plaintext_hits(session) == []

        decision = _decision(session)
        signoff = _signoff(session)
        # Zeilen unveraendert (append-only), Hash weiter verifizierbar ...
        assert decision.decision_hash == before_decision_hash
        assert signoff.signoff_hash == before_signoff_hash
        assert verify_decision(decision)
        assert verify_signoff(signoff)
        # ... aber der Freitext ist nicht mehr entschluesselbar.
        from services.pii_vault import reveal

        assert reveal(session, decision.reason) is None
        assert reveal(session, signoff.note) is None

        key = session.execute(
            text("SELECT key_material, shredded_at FROM client_pii_keys WHERE client_id='cl-rcp'")
        ).one()
        assert key.key_material is None
        assert key.shredded_at

        ra = session.get(RiskAssessment, "ra-current")
        assert ra.override_reason == REDACTION_MARKER
        assert ra.client_signed_ref == REDACTION_MARKER
        # Strukturierte Evidence bleibt (Score/Profil/Pointer).
        assert ra.override_score_x10 == 60
        assert ra.override_decision_id == decision.id

        # Unveraenderlichkeit NICHT aufgeweicht.
        for table in ("risk_override_decisions", "risk_profile_signoffs", "audit_log"):
            with pytest.raises(Exception, match="immutable"):
                session.execute(text(f"UPDATE {table} SET created_at = 'x'"))
            session.rollback()
            with pytest.raises(Exception, match="immutable"):
                session.execute(text(f"DELETE FROM {table}"))
            session.rollback()


def test_shredded_key_cannot_be_resurrected_and_new_seal_is_refused(session_factory):
    with session_factory() as session:
        _seed_override_and_signoff(session)
        erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()

        with pytest.raises(Exception, match="shred-only"):
            session.execute(text(
                "UPDATE client_pii_keys SET key_material = 'restored', shredded_at = NULL "
                "WHERE client_id = 'cl-rcp'"
            ))
        session.rollback()

        from services.pii_vault import PiiVaultError, seal_for_client

        with pytest.raises(PiiVaultError):
            seal_for_client(session, "cl-rcp", "neue Notiz nach Loeschung")


def test_erasure_reports_legacy_plaintext_rows_without_mutating_them(session_factory):
    """Altbestand vor diesem Fix (Klartext in append-only Zeilen) kann ohne
    Aufweichung der Trigger nicht redigiert werden -- er wird gezaehlt und
    gemeldet (Owner-/Legal-Entscheid), nie still uebergangen."""
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        session.execute(text(
            "INSERT INTO risk_override_decisions (id, schema_version, assessment_id, mandate_id, "
            "client_id, assessment_version, sequence_no, basis_final_score_x10, "
            "requested_score_x10, requested_profile, reason, actor_id, decided_at, "
            "rules_version, decision_hash, created_at, client_confirmed, warning_delivered, "
            "required_client_confirmation, required_warning) VALUES ('legacy-d1', "
            "'RiskOverrideDecisionV1', 'ra-current', 'm-rcp', 'cl-rcp', 1, 1, 50, 60, "
            "'Ausgewogen', 'Klartext Max Muster', :actor, '2026-10-19', 'r', 'h', '2026-10-19', "
            "0, 0, 0, 0)"
        ), {"actor": advisor.id})
        session.commit()

        summary = erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()

        assert summary["unsealed_append_only_rows"] == {"risk_override_decisions": 1}
        assert session.execute(
            text("SELECT reason FROM risk_override_decisions WHERE id='legacy-d1'")
        ).scalar() == "Klartext Max Muster"


def test_restore_of_pre_erasure_backup_reshreds_the_key(session_factory, tmp_path):
    """PRIV-005-Pfad: ein Restore einer Sicherung von VOR der Erasure bringt
    den Schluessel zurueck -- die Ledger-Wiederanwendung vernichtet ihn erneut."""
    from services.client_erasure import reapply_erasures_after_restore

    with session_factory() as session:
        _seed_override_and_signoff(session)
        db_file = session.get_bind().url.database
        session.close()
    backup = tmp_path / "pre_erasure_backup.db"
    shutil.copyfile(db_file, backup)

    with session_factory() as session:
        erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()
        session.get_bind().dispose()

    shutil.copyfile(backup, db_file)  # "Restore"
    summary = reapply_erasures_after_restore(db_file)
    assert summary["reapplied"] == ["cl-rcp"]

    with session_factory() as session:
        assert _plaintext_hits(session) == []
        from services.pii_vault import reveal

        assert reveal(session, _decision(session).reason) is None


# ---------------------------------------------------------------------------
# Schema-Drift: client_pii_keys in ORM, Bootstrap-SQL, Runtime-Patch, Alembic
# ---------------------------------------------------------------------------

KEY_TABLE_COLUMNS = {"client_id", "key_id", "key_material", "created_at", "shredded_at"}
KEY_TABLE_TRIGGERS = {"trg_client_pii_keys_shred_only", "trg_client_pii_keys_no_delete"}
KEY_REVISION = "e8a4c2f7d913"


def _sqlite_columns_and_triggers(db_path):
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(client_pii_keys)")}
        triggers = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='client_pii_keys'"
            )
        }
    return cols, triggers


def _alembic_cfg(db_url):
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    root = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_key_table_model_matches_bootstrap_and_runtime_patch(tmp_path, monkeypatch):
    from pathlib import Path

    import database as db_module
    from models.clients import ClientPiiKey

    assert {c.name for c in ClientPiiKey.__table__.columns} == KEY_TABLE_COLUMNS
    # Kein harter FK (Purge-fest wie audit_log).
    assert not ClientPiiKey.__table__.foreign_keys

    schema = Path(__file__).resolve().parents[1] / "ares_schema.sql"
    fresh = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=schema)
    assert _sqlite_columns_and_triggers(fresh) == (KEY_TABLE_COLUMNS, KEY_TABLE_TRIGGERS)

    import sqlite3

    legacy = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=legacy, schema_path=schema)
    with sqlite3.connect(str(legacy)) as conn:
        conn.execute("DROP TABLE client_pii_keys")
        conn.commit()
    engine = create_engine(f"sqlite:///{legacy}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()
    assert _sqlite_columns_and_triggers(legacy) == (KEY_TABLE_COLUMNS, KEY_TABLE_TRIGGERS)


def test_alembic_single_head_chain_contains_key_table_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert KEY_REVISION in chain
    assert script.get_revision(KEY_REVISION).down_revision == "d7b3f1a9c2e4"
