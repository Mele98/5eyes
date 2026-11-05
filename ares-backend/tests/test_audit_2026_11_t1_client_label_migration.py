"""Audit 2026-11 / 05, T1, Delta-Pruefung #863 N-863-6: Migration
b4f8d0e2a6c3 -- client_source_label als Katalogwert."""
from __future__ import annotations

import importlib.util
import io
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import models.product_eligibility as model  # noqa: E402

REVISION = "b4f8d0e2a6c3"
DOWN_REVISION = "a3e7c9d1f5b4"
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "b4f8d0e2a6c3_sustainability_client_source_label_catalog.py"
_INSERT = (
    "INSERT INTO product_sustainability_attributes (id, product_id, category, kind, revenue_threshold_bps, "
    "source_type, source_reference, client_source_label, as_of, valid_until, status, created_by, created_at, "
    "approved_by, approval_mode, updated_at) VALUES (?, 'p1', 'tobacco', 'exclusion_policy', 500, 'kid', 'KID', "
    "?, ?, '2027-06-30', ?, 'u1', 'x', ?, ?, 'x')"
)


def _cfg(url, buf=None):
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_chain_single_head_and_codes_match_model():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg("sqlite://"))
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION
    spec = importlib.util.spec_from_file_location("_b4f8", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.CODES == model.SUSTAINABILITY_CLIENT_SOURCE_LABEL_CODES
    assert set(mod.CODES) == set(model.SUSTAINABILITY_SOURCE_TYPES)


def _triggers(db):
    with sqlite3.connect(str(db)) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def _version(db):
    with sqlite3.connect(str(db)) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").scalar() if False else \
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_n863_9_fail_closed_on_foreign_label_and_triggers_stay_intact(tmp_path):
    """Fehler-Injektion: ein Bestand ausserhalb des Katalogs (Freitext) bzw.
    abweichend vom Quellentyp -> Abbruch mit klarer Meldung; danach
    unveraenderte Daten, Revision a3e7, beide Trigger aktiv."""
    from alembic import command

    db = tmp_path / "lbl.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(_INSERT, ("a", "Acme Ratings", "2026-05-31", "approved", "u2", "four_eyes"))
        conn.execute(_INSERT, ("b", "fund_contract", "2026-04-30", "approved", "u2", "four_eyes"))
    before = _triggers(db)
    assert {"trg_psa_immutable_update", "trg_psa_immutable_delete"} <= before
    with pytest.raises(Exception, match="b4f8d0e2a6c3 abgebrochen") as excinfo:
        command.upgrade(cfg, REVISION)
    assert "a (kid / 'Acme Ratings')" in str(excinfo.value) and "b (kid / 'fund_contract')" in str(excinfo.value)
    assert _version(db) == DOWN_REVISION
    assert _triggers(db) == before
    with sqlite3.connect(str(db)) as conn:
        assert dict(conn.execute("SELECT id, client_source_label FROM product_sustainability_attributes")) == {
            "a": "Acme Ratings", "b": "fund_contract"}
        with pytest.raises(sqlite3.DatabaseError, match="unveraenderlich"):
            conn.execute("UPDATE product_sustainability_attributes SET revenue_threshold_bps = 0 WHERE id = 'a'")


def test_upgrade_downgrade_upgrade_with_clean_data(tmp_path):
    from alembic import command

    db = tmp_path / "ok.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(_INSERT, ("a", "kid", "2026-05-31", "approved", "u2", "four_eyes"))
        conn.execute(_INSERT, ("c", None, "2026-03-31", "draft", None, None))
    triggers = _triggers(db)
    command.upgrade(cfg, REVISION)
    assert _version(db) == REVISION and _triggers(db) == triggers
    command.downgrade(cfg, DOWN_REVISION)
    command.upgrade(cfg, REVISION)
    assert _triggers(db) == triggers
    with sqlite3.connect(str(db)) as conn:
        assert dict(conn.execute("SELECT id, client_source_label FROM product_sustainability_attributes")) == {
            "a": "kid", "c": None}


def test_create_all_check_rejects_free_text(tmp_path):
    from sqlalchemy import create_engine

    from database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'ca.db'}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    with sqlite3.connect(str(tmp_path / "ca.db")) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT, ("x", "Acme Ratings", "2026-05-31", "draft", None, None))
        with pytest.raises(sqlite3.IntegrityError):  # Katalogwert, aber nicht der Quellentyp (kid)
            conn.execute(_INSERT, ("z", "data_vendor", "2026-05-31", "draft", None, None))
        conn.execute(_INSERT, ("y", "kid", "2026-05-31", "draft", None, None))


def test_postgres_ddl_up_and_down():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    ddl = up.getvalue()
    assert "ADD CONSTRAINT ck_psa_client_source_label CHECK" in ddl
    assert "client_source_label = source_type" in ddl
    assert "TRIGGER" not in ddl and "UPDATE product_sustainability_attributes" not in ddl, "keine Aussetzung/Normalisierung"
    down = io.StringIO()
    command.downgrade(_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    assert "DROP CONSTRAINT ck_psa_client_source_label" in down.getvalue()
