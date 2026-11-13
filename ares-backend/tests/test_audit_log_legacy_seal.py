"""Bestandssiegel fuer Altzeilen ohne Hash (Delta-Pruefung #869).

Im Live-Bestand liegen Altzeilen ohne integrity_hash (Maerz bis 9. August,
Folge des frueheren Neuaufbau-Fehlers). Ihr heutiger Stand wird beim Start
genau einmal in einem verketteten Eintrag (field_name='LEGACY_SEAL')
festgehalten; der Verifier prueft ab dann, ob der Altbestand noch dazu
passt.

Geprueft: Siegel wird einmal geschrieben (verkettet, Kette ok), ein zweiter
Start schreibt kein weiteres; Aenderung, Loeschung und Einfuegung im
Altbestand danach werden erkannt (CRITICAL); ohne ungehashte Altzeilen kein
Siegel; der Digest haengt nicht von der Einfuegereihenfolge ab; das App-Log
enthaelt keine Inhalte.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models.review import AuditLog  # noqa: E402
from services.audit import (  # noqa: E402
    LEGACY_SEAL_MARKER,
    _legacy_seal_digest,
    audit_log_integrity_report,
    log,
    run_startup_audit_chain_check,
    verify_audit_chain,
)

SECRET = "Geheimer-Altinhalt-4411"


@pytest.fixture()
def session_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seal.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    yield factory
    engine.dispose()


def _legacy_rows(session_local, ids=("L1", "L2", "L3")) -> None:
    """Altzeilen wie im Live-Bestand: ohne sequence, ohne Hash (Zeit vor dem
    Hash / Folge des frueheren Neuaufbau-Fehlers)."""
    with session_local() as s:
        for n, row_id in enumerate(ids):
            s.add(AuditLog(
                id=row_id, user_id="u0", user_name=f"Alt {SECRET}", table_name="clients",
                record_id=f"c{n}", action="UPDATE", old_value=SECRET, new_value=f"{SECRET}-{n}",
                created_at=f"2026-0{3 + n}-01T10:00:00.000Z",
            ))
        s.commit()


def _seals(session_local) -> list[AuditLog]:
    with session_local() as s:
        return s.query(AuditLog).filter(AuditLog.field_name == LEGACY_SEAL_MARKER).all()


def test_seal_is_written_once_and_chained(session_local, caplog):
    _legacy_rows(session_local)
    with session_local() as s:
        log(s, user_id="u1", user_name="A", table_name="clients", record_id="c9", action="CREATE")
        s.commit()

    with caplog.at_level(logging.INFO, logger="services.audit"):
        first = run_startup_audit_chain_check(session_local)
    seals = _seals(session_local)
    assert len(seals) == 1
    seal = seals[0]
    assert seal.sequence == 2 and seal.integrity_hash and seal.action == "CREATE"
    content = json.loads(seal.new_value)
    assert content["count"] == 3 and content["unhashed"] == 3
    assert content["id_min"] == "L1" and content["id_max"] == "L3"
    assert content["created_at_min"].startswith("2026-03") and content["created_at_max"].startswith("2026-05")
    assert first["ok"] and first["legacy"]["seal_ok"] is True and first["legacy"]["seal_sequence"] == 2
    with session_local() as s:
        assert verify_audit_chain(s) == {"ok": True, "checked": 2, "errors": []}
    # Keine Inhalte im App-Log.
    assert all(SECRET not in r.getMessage() for r in caplog.records)
    assert any("Bestandssiegel fuer 3 Altzeilen" in r.getMessage() for r in caplog.records)

    second = run_startup_audit_chain_check(session_local)
    assert len(_seals(session_local)) == 1, "zweiter Start darf kein weiteres Siegel schreiben"
    assert second["ok"] and second["legacy"]["seal_ok"] is True


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE audit_log SET new_value = 'manipuliert' WHERE id = 'L2'",
        "DELETE FROM audit_log WHERE id = 'L3'",
        "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at)"
        " VALUES ('L0', 'X', 'asset_class_annual_returns', 'r', 'BACKFILL', '2026-02-01T00:00:00.000000')",
    ],
    ids=["geaendert", "geloescht", "eingefuegt"],
)
def test_changes_to_sealed_legacy_rows_are_detected(session_local, caplog, tamper):
    _legacy_rows(session_local)
    assert run_startup_audit_chain_check(session_local)["ok"]
    with session_local() as s:
        s.execute(text(tamper))
        s.commit()
        report = audit_log_integrity_report(s)
    assert report["legacy"]["seal_ok"] is False
    assert report["ok"] is False
    with caplog.at_level(logging.WARNING, logger="services.audit"):
        run_startup_audit_chain_check(session_local)
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    assert len(_seals(session_local)) == 1


def test_no_seal_without_unhashed_legacy_rows(session_local):
    with session_local() as s:
        log(s, user_id="u1", user_name="A", table_name="clients", record_id="c1", action="CREATE")
        s.commit()
    report = run_startup_audit_chain_check(session_local)
    assert _seals(session_local) == []
    assert report["legacy"]["seal_present"] is False and report["legacy"]["seal_ok"] is None


def test_digest_is_independent_of_insertion_order(tmp_path):
    digests = []
    for name, order in (("a", ("L1", "L2", "L3")), ("b", ("L3", "L1", "L2"))):
        engine = create_engine(f"sqlite:///{tmp_path / (name + '.db')}")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as s:
            for row_id in order:
                n = int(row_id[1])
                s.add(AuditLog(
                    id=row_id, user_id="u0", user_name="Alt", table_name="clients",
                    record_id=f"c{n}", action="UPDATE", created_at=f"2026-0{3 + n}-01T10:00:00.000Z",
                ))
            s.commit()
            digests.append(_legacy_seal_digest(s))
        engine.dispose()
    assert digests[0] == digests[1]


# ---------------------------------------------------------------------------
# N-869-10 (Delta 2 #869): Siegelformat eingefroren
# ---------------------------------------------------------------------------

_FROZEN_ROWS = (
    dict(id="L-a", user_id="u0", user_name="Alt Müller", table_name="clients", record_id="c1",
         action="UPDATE", field_name="note", old_value="A|B", new_value="C", mandate_id=None,
         client_id="c1", integrity_hash=None, ip_address=None,
         created_at="2026-03-01T10:00:00.000Z", tenant_id=None, sequence=None, previous_hash=None),
    dict(id="L-b", user_id="u0", user_name="Alt", table_name="asset_class_annual_returns",
         record_id="2005-2024", action="BACKFILL", field_name=None, old_value=None,
         new_value="rows_written=7 errors=0", mandate_id=None, client_id=None,
         integrity_hash="ab" * 32, ip_address="203.0.113.1",
         created_at="2026-08-01T09:00:00.000000", tenant_id="tenant-a", sequence=None, previous_hash=None),
    dict(id="L-c", user_id=None, user_name="Portal", table_name="users", record_id="u9",
         action="LOGIN", field_name=None, old_value=None, new_value=None, mandate_id="m1",
         client_id=None, integrity_hash=None, ip_address="198.51.100.2",
         created_at="2026-05-17T23:59:59.999Z", tenant_id=None, sequence=None, previous_hash=None),
)
# Eingefrorener Soll-Wert (legacy-seal-v1). Live ist bereits ein Siegel nach
# genau diesem Format geschrieben: jede Aenderung an json.dumps-Parametern,
# Spaltenliste/-reihenfolge, Sortierung oder Zeilentrenner macht dieses
# Siegel ungueltig und muss hier rot werden. NICHT anpassen, sondern ein
# neues Schema (legacy-seal-v2) einfuehren.
_FROZEN_SHA256 = "e70ae65af20fe32b5ea8d74624f154c75898e92831eac08fae70b57c9e68cbe9"


def test_seal_format_is_frozen(session_local):
    with session_local() as s:
        # Einfuegereihenfolge bewusst nicht nach id.
        for row in (_FROZEN_ROWS[2], _FROZEN_ROWS[0], _FROZEN_ROWS[1]):
            s.add(AuditLog(**row))
        s.commit()
        digest = _legacy_seal_digest(s)
    assert digest == {
        "scheme": "legacy-seal-v1",
        "count": 3,
        "unhashed": 2,
        "id_min": "L-a",
        "id_max": "L-c",
        "created_at_min": "2026-03-01T10:00:00.000Z",
        "created_at_max": "2026-08-01T09:00:00.000000",
        "sha256": _FROZEN_SHA256,
    }


def test_verifier_requires_matching_seal_scheme(session_local):
    """Ein Siegel mit anderer (z.B. kuenftiger oder gefaelschter) Format-
    Version wird nicht als passend akzeptiert, auch wenn der Hash stimmt."""
    _legacy_rows(session_local)
    run_startup_audit_chain_check(session_local)
    with session_local() as s:
        seal = s.query(AuditLog).filter(AuditLog.field_name == LEGACY_SEAL_MARKER).one()
        content = json.loads(seal.new_value)
    assert content["scheme"] == "legacy-seal-v1"
    content["scheme"] = "legacy-seal-v2"
    with session_local() as s:
        # Simuliert eine Zeile mit anderer Version (Dateizugriff, ohne Trigger).
        s.execute(text("UPDATE audit_log SET new_value = :v WHERE id = :id"),
                  {"v": json.dumps(content, sort_keys=True, separators=(",", ":")), "id": seal.id})
        s.commit()
        report = audit_log_integrity_report(s)
    assert report["legacy"]["seal_ok"] is False


# ---------------------------------------------------------------------------
# N-869-9 (Delta 2 #869): Parallelstart schreibt nur EIN Siegel
# ---------------------------------------------------------------------------

def _file_db(tmp_path, name: str):
    url = f"sqlite:///{tmp_path / name}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    return url, engine


def test_parallel_starts_write_exactly_one_seal(tmp_path, monkeypatch):
    """Deterministischer Wettlauf: alle Starts passieren gemeinsam die
    Vorpruefung "kein Siegel" (Barriere), erst dann wird geschrieben. Ohne
    erneute Pruefung unter der Zaehler-Sperre schrieb jeder Start ein Siegel.
    Ohne Unique-Index, damit allein die Sperre belegt ist."""
    import threading

    import services.audit as audit_service

    url, engine = _file_db(tmp_path, "parallel.db")
    _legacy_rows(sessionmaker(bind=engine, expire_on_commit=False))
    workers = 4
    barrier = threading.Barrier(workers)
    seen = threading.local()
    original = audit_service._legacy_seals

    def _racing_legacy_seals(db):
        result = original(db)
        if not getattr(seen, "passed", False):
            seen.passed = True
            barrier.wait(timeout=20)
        return result

    monkeypatch.setattr(audit_service, "_legacy_seals", _racing_legacy_seals)
    errors: list[BaseException] = []

    def _start():
        own = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        try:
            factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=own)
            with factory() as db:
                if audit_service.ensure_legacy_seal(db) is not None:
                    db.commit()
        except BaseException as exc:  # noqa: BLE001 -- im Haupt-Thread pruefen
            errors.append(exc)
        finally:
            own.dispose()

    threads = [threading.Thread(target=_start) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    monkeypatch.setattr(audit_service, "_legacy_seals", original)
    assert not errors, errors
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        seals = s.query(AuditLog).filter(AuditLog.field_name == LEGACY_SEAL_MARKER).all()
        assert len(seals) == 1
        assert verify_audit_chain(s)["ok"]
        assert audit_log_integrity_report(s)["legacy"]["seal_ok"] is True
    engine.dispose()


def test_unique_index_rejects_a_second_seal(tmp_path):
    from database import ensure_audit_log_indexes
    from sqlalchemy.exc import IntegrityError

    _url, engine = _file_db(tmp_path, "unique.db")
    ensure_audit_log_indexes(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    _legacy_rows(factory)
    assert run_startup_audit_chain_check(factory)["legacy"]["seal_ok"] is True
    with factory() as s:
        log(s, user_id="system", user_name="X", table_name="audit_log", record_id="legacy-seal",
            action="CREATE", field_name=LEGACY_SEAL_MARKER, new_value="{}", tenant_id=None)
        with pytest.raises(IntegrityError):
            s.commit()
    engine.dispose()


def test_unique_index_with_existing_duplicates_is_critical_not_fatal(tmp_path, caplog):
    from database import ensure_audit_log_indexes

    _url, engine = _file_db(tmp_path, "dupes.db")
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as s:
        for n in range(2):
            log(s, user_id="system", user_name="X", table_name="audit_log", record_id="legacy-seal",
                action="CREATE", field_name=LEGACY_SEAL_MARKER, new_value=str(n), tenant_id=None)
        s.commit()
    with caplog.at_level(logging.WARNING, logger="database.audit_log"):
        ensure_audit_log_indexes(engine)  # darf nicht werfen
    assert any(r.levelno == logging.CRITICAL and "ux_audit_log_legacy_seal" in r.getMessage()
               for r in caplog.records)
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert "idx_audit_sequence" in names and "ux_audit_log_legacy_seal" not in names
    engine.dispose()


# ---------------------------------------------------------------------------
# N-869-8 (Delta 2 #869): Siegel auch ohne ungehashte Altzeilen, seal_missing
# ---------------------------------------------------------------------------

def _hashed_legacy_rows(session_local) -> None:
    with session_local() as s:
        for n in range(2):
            s.add(AuditLog(
                id=f"H{n}", user_id="u0", user_name="Alt", table_name="clients", record_id=f"c{n}",
                action="UPDATE", integrity_hash=f"{n}" * 64,
                created_at=f"2026-08-2{n}T10:00:00.000Z",
            ))
        s.commit()


def test_seal_is_written_when_all_legacy_rows_are_hashed(session_local):
    _hashed_legacy_rows(session_local)
    report = run_startup_audit_chain_check(session_local)
    seals = _seals(session_local)
    assert len(seals) == 1
    content = json.loads(seals[0].new_value)
    assert content["count"] == 2 and content["unhashed"] == 0
    assert report["legacy"]["seal_ok"] is True and report["legacy"]["seal_missing"] is False


def test_seal_missing_is_reported_as_hint(session_local, caplog):
    """Altzeilen ohne Siegel (z.B. Startpruefung uebersprungen oder Siegel
    noch nicht geschrieben): Hinweis seal_missing, kein Befund."""
    _legacy_rows(session_local)
    with session_local() as s:
        report = audit_log_integrity_report(s)
    assert report["legacy"]["seal_missing"] is True
    assert report["legacy"]["seal_present"] is False and report["ok"] is True
    import services.audit as audit_service

    original = audit_service.ensure_legacy_seal
    audit_service.ensure_legacy_seal = lambda db: None  # Siegel-Schreiben unterdrueckt
    try:
        with caplog.at_level(logging.INFO, logger="services.audit"):
            run_startup_audit_chain_check(session_local)
    finally:
        audit_service.ensure_legacy_seal = original
    warning = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning and "ohne Bestandssiegel: True" in warning[0].getMessage()
    assert not [r for r in caplog.records if r.levelno == logging.CRITICAL]
