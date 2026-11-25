"""L2d / N-938-02 live auf PostgreSQL: konstante Abfragezahl unter FORCE RLS.

Echte Migrationskette in ein Wegwerf-Schema, Boot-RLS-Plan, Proben als
NICHT-Owner, NOSUPERUSER, NOBYPASSRLS mit versiegelten Zeilen:

* Beratungslog: 20 Eintraege kosten hoechstens fuenf SELECTs mehr als einer;
* Kundenbericht: 20 Notizversionen hoechstens fuenf mehr als eine;
* ein fremder Mandant sieht weder Eintraege noch Versionen;
* Gegenprobe: ohne Schluesselkontext waechst die Zahl linear.

Uebersprungen ohne ``POSTGRES_TEST_DATABASE_URL`` (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(BACKEND_ROOT), str(BACKEND_ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from h8_support import NOW, TENANT, mandate, user  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import MandateReportNotes  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from routers import review as review_api  # noqa: E402
from services import pii_vault  # noqa: E402
from services.advisory_report import _load_report_notes  # noqa: E402
from services.notes_versioning import save_report_notes_version  # noqa: E402
from services.postgres_rls import ensure_postgres_rls_policies  # noqa: E402
from services.tenant_context import attach_tenant_context_reset, set_tenant_context  # noqa: E402
from tests.test_l2c_dsg_protocol_texts import _log  # noqa: E402
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: E402
    _alembic_cfg,
    _qi,
    _scoped_url,
)

FOREIGN = "t-l2d-fremd"


@pytest.fixture()
def pg_app():
    pytest.importorskip("psycopg")
    from alembic import command

    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema, role, password = f"l2d_{token}", f"l2d_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), "head")
        with sessionmaker(bind=owner, autoflush=False)() as seed:
            for tid in (TENANT, FOREIGN):
                seed.add(Tenant(id=tid, display_name=tid, slug=f"{tid}-{token}", created_at=NOW, updated_at=NOW))
            seed.flush()
            seed.add(User(id="adv-1", username=f"adv-{token}", password_hash="x", full_name="ADV-1",
                          role="advisor", is_active=1, tenant_id=TENANT, created_at=NOW, updated_at=NOW))
            seed.flush()
            seed.add(Client(id="c-1", tenant_id=TENANT, client_number="K-1", first_name="Eva",
                            last_name="Muster", advisor_id="adv-1", created_at=NOW, updated_at=NOW))
            seed.flush()
            seed.add(Mandate(id="m-1", tenant_id=TENANT, client_id="c-1", mandate_number="M-1",
                             mandate_type="Anlageberatung", opened_at=NOW, created_at=NOW, updated_at=NOW))
            seed.flush()
            seed.add(MandateReportNotes(id="notes-1", mandate_id="m-1", last_edited_by="adv-1", last_edited_at=NOW,
                                        created_at=NOW, updated_at=NOW))
            seed.commit()
        with owner.begin() as conn:
            ensure_postgres_rls_policies(conn)
            conn.execute(text(
                f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"))
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True)
        attach_tenant_context_reset(app)
        yield sessionmaker(bind=app, autoflush=False, expire_on_commit=False)
    finally:
        if app is not None:
            app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _selects(db, call):
    count = 0

    def hook(_conn, _cursor, statement, *_rest):
        nonlocal count
        count += statement.lstrip().upper().startswith("SELECT")

    event.listen(db.get_bind(), "before_cursor_execute", hook)
    try:
        result = call()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", hook)
    return result, count


def _list(db):
    return _selects(db, lambda: review_api.list_advisory_log("m-1", db=db, current_user=user(db, "adv-1")))


def _commit(db):
    db.commit()
    set_tenant_context(db, TENANT)


def _add_logs(db, count):
    for index in range(count):
        _log(db, title=f"Eintrag {index}")
    _commit(db)


def _add_note(db, value):
    head = db.query(MandateReportNotes).filter(MandateReportNotes.mandate_id == "m-1").one()
    save_report_notes_version(
        db, notes_head=head, client_id="c-1", values={"aa_anmerkungen": value}, edited_by="adv-1", edited_at=NOW)
    _commit(db)


def test_advisory_log_selects_are_constant_under_rls(pg_app):
    with pg_app() as db:
        set_tenant_context(db, TENANT)
        _add_logs(db, 1)
        sealed = db.execute(text("SELECT title FROM advisory_log")).scalar_one()
        assert pii_vault.is_sealed(sealed)
        one, baseline = _list(db)
        assert len(one) == 1 and one[0]["title"] == "Eintrag 0" and one[0]["integrity_verified"] is True
        _add_logs(db, 19)
        twenty, count = _list(db)
        assert len(twenty) == 20 and all(row["integrity_verified"] is True for row in twenty)
        assert {row["title"] for row in twenty} == {f"Eintrag {index}" for index in range(19)}
        assert count <= baseline + 5, (baseline, count)
    with pg_app() as db:
        set_tenant_context(db, FOREIGN)
        assert db.execute(text("SELECT COUNT(*) FROM advisory_log")).scalar_one() == 0


def test_report_selects_are_constant_under_rls(pg_app):
    with pg_app() as db:
        set_tenant_context(db, TENANT)
        _add_note(db, "Fassung 1")
        first, baseline = _selects(db, lambda: _load_report_notes(db, mandate(db)))
        assert first.aa_anmerkungen == "Fassung 1"
        for index in range(2, 21):
            _add_note(db, f"Fassung {index}")
        latest, count = _selects(db, lambda: _load_report_notes(db, mandate(db)))
        assert latest.aa_anmerkungen == "Fassung 20" and latest.current_version == 20
        assert count <= baseline + 5, (baseline, count)
    with pg_app() as db:
        set_tenant_context(db, FOREIGN)
        assert db.execute(text("SELECT COUNT(*) FROM mandate_report_note_versions")).scalar_one() == 0


def test_negative_control_without_key_context_grows_linearly(pg_app, monkeypatch):
    original = pii_vault.KeyReader.key

    def uncached(self, key_id):
        self._keys.clear()
        return original(self, key_id)

    monkeypatch.setattr(pii_vault.KeyReader, "key", uncached)
    with pg_app() as db:
        set_tenant_context(db, TENANT)
        _add_logs(db, 1)
        _, baseline = _list(db)
        _add_logs(db, 19)
        _, count = _list(db)
        assert count > baseline + 19, (baseline, count)
