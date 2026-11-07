"""SEED-FK-HYGIENE (2026-11-05): Start-Seeds und -Backfills in database.py
verschlucken keine Fehler mehr.

Vorher stand in ensure_default_tenant, ensure_default_ch_jurisdiction,
ensure_default_de_jurisdiction, ensure_client_login_user_tenant_backfill und
ensure_tenant_backfill ein blankes ``except Exception: pass`` (in
migrate_house_matrix_real_estate_cap_20 ein stilles ``return 0``). So fiel der
DE-Seed unter PRAGMA foreign_keys=ON still aus.

Jetzt gilt (database._handle_startup_step_error):
- Schema noch nicht bereit (Tabelle/Spalte fehlt) -> WARNING, Start laeuft weiter.
- Jeder andere Fehler -> ERROR (Fehlerklasse + Treibermeldung, ohne
  SQL-Parameter) und erneut ausgeloest: der Start bricht ab (fail-closed).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from database import Base, create_app_engine
from main import app  # noqa: F401  (registriert alle Modelle fuer create_all)

_SECRET_PARAM = "geheimer-parameterwert-4711"

_SEEDS = (
    database.ensure_default_tenant,
    database.ensure_default_ch_jurisdiction,
    database.ensure_default_de_jurisdiction,
    database.ensure_client_login_user_tenant_backfill,
    database.migrate_house_matrix_real_estate_cap_20,
)


@pytest.fixture()
def empty_engine(tmp_path):
    eng = create_app_engine(db_path=tmp_path / "empty.db", echo=False)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def full_engine(tmp_path):
    eng = create_app_engine(db_path=tmp_path / "full.db", echo=False)
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _integrity_error() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO x VALUES (?)", (_SECRET_PARAM,), Exception("FOREIGN KEY constraint failed"),
    )


@pytest.mark.parametrize("step", _SEEDS, ids=lambda f: f.__name__)
def test_schema_not_ready_is_skipped_with_warning(step, empty_engine, caplog):
    """Leere/partielle DB: kein Abbruch, aber eine sichtbare WARNING."""
    with caplog.at_level(logging.WARNING, logger="database"):
        step(empty_engine)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "database"]
    assert warnings, "Uebersprungener Startschritt muss geloggt werden"
    assert "no such table" in warnings[0].getMessage()


def test_tenant_backfill_schema_not_ready_is_skipped_with_warning(empty_engine, caplog, monkeypatch):
    import services.auth as auth

    monkeypatch.setattr(auth, "_effective_strict_tenant_isolation", lambda _s: False)
    with caplog.at_level(logging.WARNING, logger="database"):
        database.ensure_tenant_backfill(empty_engine)
    tables = {r.getMessage().split("[", 1)[1].split("]", 1)[0]
              for r in caplog.records if "ensure_tenant_backfill[" in r.getMessage()}
    assert tables == {"users", "clients", "mandates", "protocol_bausteine"}


def test_de_seed_integrity_error_aborts_start_and_is_logged(full_engine, caplog, monkeypatch):
    """Kern des Befunds: ein Integritaetsfehler im DE-Seed darf nicht mehr
    still verschwinden."""
    import services.jurisdiction.de_seed as de_seed

    def _boom(_db):
        raise _integrity_error()

    monkeypatch.setattr(de_seed, "ensure_de_jurisdiction_seed", _boom)
    with caplog.at_level(logging.ERROR, logger="database"), pytest.raises(IntegrityError):
        database.ensure_default_de_jurisdiction(full_engine)
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("ensure_default_de_jurisdiction" in m and "FOREIGN KEY constraint failed" in m for m in errors)
    assert not any(_SECRET_PARAM in m for m in caplog.messages), "SQL-Parameter gehoeren nicht ins Log"


def test_real_pseudo_fk_insert_aborts_start(full_engine):
    """Gegenprobe mit echtem FK-Verstoss statt Mock: ein Seed, der eine
    Pseudo-Kennung in users.id schreibt, bricht den Start ab."""
    import services.jurisdiction.de_seed as de_seed

    def _pseudo(db):
        db.execute(text(
            "INSERT INTO jurisdiction_profiles (id, code, display_name, home_currency, "
            "is_active, is_provisional, status, created_by, created_at, updated_at) "
            "VALUES ('p', 'DE', 'Deutschland', 'EUR', 1, 1, 'draft', 'system:x', 'n', 'n')"
        ))
        db.flush()

    original = de_seed.ensure_de_jurisdiction_seed
    de_seed.ensure_de_jurisdiction_seed = _pseudo
    try:
        with pytest.raises(IntegrityError):
            database.ensure_default_de_jurisdiction(full_engine)
    finally:
        de_seed.ensure_de_jurisdiction_seed = original


@pytest.mark.parametrize(
    "name",
    ["ensure_default_tenant", "ensure_default_ch_jurisdiction",
     "ensure_client_login_user_tenant_backfill", "migrate_house_matrix_real_estate_cap_20"],
)
def test_other_errors_abort_start(name, full_engine, monkeypatch, caplog):
    """Nicht-Schema-Fehler (hier: Integritaetsfehler aus der Session bzw.
    Verbindung) brechen jeden Startschritt ab und werden mit ERROR geloggt."""
    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session

    def _boom(*_a, **_k):
        raise _integrity_error()

    monkeypatch.setattr(Session, "commit", _boom)
    monkeypatch.setattr(Connection, "execute", _boom)
    with caplog.at_level(logging.ERROR, logger="database"), pytest.raises(IntegrityError):
        getattr(database, name)(full_engine)
    assert any(name in m for m in caplog.messages)


def test_operational_error_other_than_missing_schema_aborts(full_engine, monkeypatch):
    """'database is locked' o.ae. ist KEIN fehlendes Schema -> Abbruch."""
    import services.jurisdiction.de_seed as de_seed

    def _locked(_db):
        raise OperationalError("SELECT 1", (), Exception("database is locked"))

    monkeypatch.setattr(de_seed, "ensure_de_jurisdiction_seed", _locked)
    with pytest.raises(OperationalError):
        database.ensure_default_de_jurisdiction(full_engine)


def test_successful_seeds_on_full_schema_log_nothing_and_keep_fk_clean(full_engine, caplog):
    with caplog.at_level(logging.WARNING, logger="database"):
        for step in _SEEDS:
            step(full_engine)
    assert [r for r in caplog.records if r.name == "database"] == []
    with full_engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert conn.execute(text("SELECT COUNT(*) FROM jurisdiction_profiles")).scalar() == 2
