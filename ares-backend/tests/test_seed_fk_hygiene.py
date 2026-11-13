"""SEED-FK-HYGIENE (2026-11-05): System-Seeds und die CMA-Datenpipeline
schreiben keine Pseudo-Kennung in Fremdschluessel-Spalten auf users.id.

Befund: services/jurisdiction/de_seed.py schrieb "system:de_jurisdiction_seed"
in jurisdiction_profiles.created_by / jurisdiction_home_bias_defaults.created_by
(FK auf users.id). Unter PRAGMA foreign_keys=ON -- so oeffnet die App jede
Verbindung (database.attach_sqlite_pragmas) -- scheiterte damit jedes INSERT;
database.ensure_default_de_jurisdiction verschluckte den Fehler, der DE-Seed
fiel still aus. Dieselbe Klasse: services/jurisdiction/data_pipeline.py schrieb
"system:cma_data_pipeline" in capital_market_assumptions.created_by (NOT NULL,
FK auf users.id), womit POST /jurisdictions/{code}/cma/compute-candidate unter
FK-Pruefung nie eine Zeile anlegen konnte.

Alle Engines hier laufen mit derselben Pragma-Konfiguration wie die App
(database.create_app_engine), nicht mit einem nackten create_engine ohne FK.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from database import Base, create_app_engine
from main import app  # noqa: F401  (registriert alle Modelle fuer create_all)
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile
from services.jurisdiction import de_seed
import services.jurisdiction.data_pipeline as dp
from tests.test_cma_data_pipeline import _full_curve_provider

_LEGACY_PSEUDO_ID = "system:de_jurisdiction_seed"
_DE_HOME_BIAS_ROW_COUNT = sum(
    len(splits)
    for variants in de_seed.DE_HOME_BIAS_DEFAULTS.values()
    for splits in variants.values()
)


@pytest.fixture()
def fk_engine(tmp_path):
    eng = create_app_engine(db_path=tmp_path / "seed_fk.db", echo=False)
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _fk_on(eng) -> int:
    with eng.connect() as conn:
        return int(conn.execute(text("PRAGMA foreign_keys")).scalar())


def _fk_violations(eng) -> list:
    with eng.connect() as conn:
        return list(conn.execute(text("PRAGMA foreign_key_check")).fetchall())


def _session(eng):
    return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=eng)()


def test_de_seed_runs_with_foreign_keys_enabled(fk_engine):
    assert _fk_on(fk_engine) == 1, "Vorbedingung: Engine prueft Fremdschluessel"
    with _session(fk_engine) as db:
        de_seed.ensure_de_jurisdiction_seed(db)
        db.commit()
    with _session(fk_engine) as db:
        profile = db.query(JurisdictionProfile).filter_by(code="DE").one()
        rows = db.query(JurisdictionHomeBiasDefault).filter_by(jurisdiction_code="DE").all()
    assert profile.created_by is None
    assert len(rows) == _DE_HOME_BIAS_ROW_COUNT == 34
    assert all(r.created_by is None for r in rows)
    assert _fk_violations(fk_engine) == []


def test_boot_wrapper_seeds_de_under_foreign_keys(fk_engine):
    """Gegenprobe zum stillen Ausfall: ueber den Boot-Wrapper (init_db-Pfad)
    muss die DE-Zeile tatsaechlich entstehen."""
    database.ensure_default_de_jurisdiction(fk_engine)
    with _session(fk_engine) as db:
        assert db.query(JurisdictionProfile).filter_by(code="DE").count() == 1
        assert (
            db.query(JurisdictionHomeBiasDefault).filter_by(jurisdiction_code="DE").count()
            == _DE_HOME_BIAS_ROW_COUNT
        )
    assert _fk_violations(fk_engine) == []


def test_pseudo_id_is_rejected_by_the_fk(fk_engine):
    """Gegenprobe: die Engine weist die fruehere Pseudo-Kennung wirklich ab --
    der Test oben ist also nicht gruen, weil FKs gar nicht geprueft wuerden."""
    with fk_engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(text(
            "INSERT INTO jurisdiction_profiles (id, code, display_name, home_currency, "
            "is_active, is_provisional, status, created_by, created_at, updated_at) "
            "VALUES ('x', 'XX', 'X', 'EUR', 1, 1, 'draft', :cb, 'now', 'now')"
        ), {"cb": _LEGACY_PSEUDO_ID})


def test_seed_repairs_legacy_pseudo_created_by(tmp_path):
    """Bestands-DBs: Zeilen, die ueber eine Verbindung OHNE FK-Pruefung mit der
    Pseudo-Kennung entstanden sind (Live-Befund: 35 verwaiste Zeilen), setzt der
    Seed idempotent auf NULL zurueck; danach ist foreign_key_check leer."""
    db_file = tmp_path / "legacy.db"
    raw = create_engine(f"sqlite:///{db_file}")  # bewusst ohne FK-Pragma (Altzustand)
    Base.metadata.create_all(bind=raw)
    with _session(raw) as db:
        de_seed.ensure_de_jurisdiction_seed(db)
        db.commit()
    with raw.begin() as conn:
        conn.execute(text("UPDATE jurisdiction_profiles SET created_by = :cb"), {"cb": _LEGACY_PSEUDO_ID})
        conn.execute(text("UPDATE jurisdiction_home_bias_defaults SET created_by = :cb"), {"cb": _LEGACY_PSEUDO_ID})
    raw.dispose()

    eng = create_app_engine(db_path=db_file, echo=False)
    try:
        assert len(_fk_violations(eng)) == 1 + _DE_HOME_BIAS_ROW_COUNT == 35
        with _session(eng) as db:
            de_seed.ensure_de_jurisdiction_seed(db)
            db.commit()
            de_seed.ensure_de_jurisdiction_seed(db)  # idempotent
            db.commit()
        assert _fk_violations(eng) == []
        with eng.connect() as conn:
            left = conn.execute(text(
                "SELECT (SELECT COUNT(*) FROM jurisdiction_profiles WHERE created_by IS NOT NULL)"
                " + (SELECT COUNT(*) FROM jurisdiction_home_bias_defaults WHERE created_by IS NOT NULL)"
            )).scalar()
            total = conn.execute(text("SELECT COUNT(*) FROM jurisdiction_home_bias_defaults")).scalar()
        assert left == 0
        assert total == _DE_HOME_BIAS_ROW_COUNT, "Reparatur darf keine Zeile doppeln oder loeschen"
    finally:
        eng.dispose()


def _insert_user(eng, user_id: str) -> None:
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, username, password_hash, full_name, role, is_active, "
            "created_at, updated_at, totp_enabled, must_change_password) "
            "VALUES (:id, :id, 'x', 'PM', 'portfolio_management', 1, 'now', 'now', 0, 0)"
        ), {"id": user_id})


def _patch_pipeline(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _full_curve_provider(series_codes, [2.0, 2.3, 2.6, 2.9, 3.1])
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {})


def test_cma_pipeline_persists_under_foreign_keys_with_real_actor(fk_engine, monkeypatch):
    _patch_pipeline(monkeypatch)
    _insert_user(fk_engine, "pm-user-1")
    with _session(fk_engine) as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(
            db, "DE", "2026-07-30", created_by_user_id="pm-user-1",
        )
        db.commit()
        assert cma.created_by == "pm-user-1"
        assert cma.computed_by == dp.COMPUTED_BY  # Herkunft bleibt, ohne FK
    assert _fk_violations(fk_engine) == []


def test_cma_pipeline_pseudo_actor_is_rejected_by_the_fk(fk_engine, monkeypatch):
    """Gegenprobe: mit der frueheren Pseudo-Kennung als created_by scheitert das
    INSERT unter FK-Pruefung -- genau der Fehler, den der Router lieferte."""
    _patch_pipeline(monkeypatch)
    with _session(fk_engine) as db, pytest.raises(IntegrityError):
        dp.compute_cma_candidate_for_jurisdiction(
            db, "DE", "2026-07-30", created_by_user_id=dp.COMPUTED_BY,
        )
        db.commit()


def test_cma_pipeline_requires_explicit_actor():
    with pytest.raises(TypeError):
        dp.compute_cma_candidate_for_jurisdiction(None, "DE", "2026-07-30")  # type: ignore[call-arg]


def _legacy_db_with_pseudo_ids(db_file) -> None:
    raw = create_engine(f"sqlite:///{db_file}")  # ohne FK-Pragma (Altzustand)
    Base.metadata.create_all(bind=raw)
    with _session(raw) as db:
        de_seed.ensure_de_jurisdiction_seed(db)
        db.commit()
    with raw.begin() as conn:
        conn.execute(text("UPDATE jurisdiction_profiles SET created_by = :cb"), {"cb": _LEGACY_PSEUDO_ID})
        conn.execute(text("UPDATE jurisdiction_home_bias_defaults SET created_by = :cb"), {"cb": _LEGACY_PSEUDO_ID})
    raw.dispose()


def _pseudo_id_rows(eng) -> int:
    with eng.connect() as conn:
        return int(conn.execute(text(
            "SELECT (SELECT COUNT(*) FROM jurisdiction_profiles WHERE created_by = :cb)"
            " + (SELECT COUNT(*) FROM jurisdiction_home_bias_defaults WHERE created_by = :cb)"
        ), {"cb": _LEGACY_PSEUDO_ID}).scalar())


def _seed_info_records(caplog) -> list:
    return [
        r for r in caplog.records
        if r.name == de_seed.__name__ and "verwaister Seed-Kennung" in r.getMessage()
    ]


def test_repair_logs_count_once_and_nothing_when_clean(tmp_path, caplog):
    """N-870-1: Reparatur schreibt (ueber den Boot-Pfad, nach dem Commit)
    genau eine INFO-Zeile mit der Anzahl (ohne Inhalte); ein zweiter Lauf
    (0 Zeilen) loggt nichts."""
    import logging

    db_file = tmp_path / "legacy_log.db"
    _legacy_db_with_pseudo_ids(db_file)

    eng = create_app_engine(db_path=db_file, echo=False)
    logger_name = de_seed.__name__
    try:
        with caplog.at_level(logging.INFO, logger=logger_name):
            database.ensure_default_de_jurisdiction(eng)
        first = [r for r in caplog.records if r.name == logger_name]
        assert len(first) == 1 and first[0].levelno == logging.INFO
        msg = first[0].getMessage()
        assert "35 Zeilen" in msg
        assert "jurisdiction_profiles=1" in msg and "jurisdiction_home_bias_defaults=34" in msg
        assert _LEGACY_PSEUDO_ID not in msg and "Deutschland" not in msg, "keine Inhalte im Log"
        assert _pseudo_id_rows(eng) == 0

        caplog.clear()
        with caplog.at_level(logging.INFO, logger=logger_name):
            database.ensure_default_de_jurisdiction(eng)
        assert [r for r in caplog.records if r.name == logger_name] == []
    finally:
        eng.dispose()


def test_seed_function_itself_does_not_log_before_commit(tmp_path, caplog):
    """N-870-5: ensure_de_jurisdiction_seed meldet die Reparatur nicht selbst
    (sie ist bis zum Commit des Aufrufers nicht wirksam), sondern gibt die
    Anzahl je Tabelle zurueck."""
    import logging

    db_file = tmp_path / "legacy_nolog.db"
    _legacy_db_with_pseudo_ids(db_file)
    eng = create_app_engine(db_path=db_file, echo=False)
    try:
        with caplog.at_level(logging.INFO, logger=de_seed.__name__):
            with _session(eng) as db:
                repaired = de_seed.ensure_de_jurisdiction_seed(db)
                assert _seed_info_records(caplog) == [], "vor dem Commit keine Erfolgszeile"
                db.rollback()
        assert repaired == {"jurisdiction_profiles": 1, "jurisdiction_home_bias_defaults": 34}
        assert _seed_info_records(caplog) == []
        assert _pseudo_id_rows(eng) == 35, "Rollback laesst die Altwerte stehen"
    finally:
        eng.dispose()


def test_failed_commit_leaves_no_success_line(tmp_path, caplog, monkeypatch):
    """N-870-5: scheitert der aeussere Commit, bleiben die Altwerte stehen und
    im Log steht keine Erfolgs-INFO, nur der Startfehler (fail-closed)."""
    import logging

    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    db_file = tmp_path / "legacy_fail.db"
    _legacy_db_with_pseudo_ids(db_file)
    eng = create_app_engine(db_path=db_file, echo=False)

    def _failing_commit(self):  # noqa: ANN001
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

    try:
        monkeypatch.setattr(Session, "commit", _failing_commit)
        with caplog.at_level(logging.INFO):
            with pytest.raises(OperationalError):
                database.ensure_default_de_jurisdiction(eng)
        monkeypatch.undo()
        assert _seed_info_records(caplog) == [], "keine Erfolgszeile ohne Commit"
        assert any(
            r.levelno == logging.ERROR and "ensure_default_de_jurisdiction" in r.getMessage()
            for r in caplog.records
        )
        assert _pseudo_id_rows(eng) == 35
    finally:
        eng.dispose()


def test_fresh_seed_logs_nothing(fk_engine, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger=de_seed.__name__):
        database.ensure_default_de_jurisdiction(fk_engine)
    assert [r for r in caplog.records if r.name == de_seed.__name__] == []
