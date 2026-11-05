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
