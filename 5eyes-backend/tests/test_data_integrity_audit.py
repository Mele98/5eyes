"""FINMA-Hygiene: Daten-Integritäts-Audit erkennt Skript-/Demo-Datensätze, und der
Foundation-Demo-Seed ist in Produktion gesperrt.
"""
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
for p in (str(BACKEND_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import data_integrity_audit as dia  # scripts/data_integrity_audit.py


def _mk_db():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE cashflows (id TEXT, client_id TEXT, label TEXT,
                   created_at TEXT, deleted_at TEXT)""")
    return con


def test_flags_script_timestamp_row():
    con = _mk_db()
    con.execute("INSERT INTO cashflows VALUES ('1','c','Echt','2026-06-07T10:02:10.135Z',NULL)")
    con.execute("INSERT INTO cashflows VALUES ('2','c','Pensionskassen-Rente (BVG)','2026-06-12T18:24:446Z',NULL)")
    con.commit()
    findings = dia.scan_database(con)
    labels = [f["label"] for f in findings]
    assert "Pensionskassen-Rente (BVG)" in labels
    assert "Echt" not in labels  # valides App-Timestamp-Format -> sauber


def test_ignores_soft_deleted_rows():
    con = _mk_db()
    con.execute("INSERT INTO cashflows VALUES ('3','c','Alt-Seed','2026-06-12T18:24:446Z','2026-06-15T00:00:00.000Z')")
    con.commit()
    # soft-deleted -> nicht FINMA-relevant (für den Berater unsichtbar)
    assert dia.scan_database(con) == []


def _mk_orphan_db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE clients (id TEXT, deleted_at TEXT)")
    con.execute("CREATE TABLE recommendation_runs (id TEXT, client_id TEXT, deleted_at TEXT)")
    return con


def test_flags_orphan_of_soft_deleted_client():
    con = _mk_orphan_db()
    con.execute("INSERT INTO clients VALUES ('gone','2026-06-15T00:00:00.000Z')")  # soft-deleted
    con.execute("INSERT INTO recommendation_runs VALUES ('r1','gone',NULL)")        # aktive Waise
    con.commit()
    findings = dia.scan_orphans(con)
    assert any(f["table"] == "recommendation_runs" and f["id"] == "r1" for f in findings)


def test_no_orphan_for_active_client():
    con = _mk_orphan_db()
    con.execute("INSERT INTO clients VALUES ('ok',NULL)")               # aktiver Kunde
    con.execute("INSERT INTO recommendation_runs VALUES ('r2','ok',NULL)")
    con.commit()
    assert dia.scan_orphans(con) == []


def test_orphan_ignores_soft_deleted_child():
    con = _mk_orphan_db()
    con.execute("INSERT INTO clients VALUES ('gone','2026-06-15T00:00:00.000Z')")
    con.execute("INSERT INTO recommendation_runs VALUES ('r3','gone','2026-06-16T00:00:00.000Z')")  # mit-gelöscht
    con.commit()
    assert dia.scan_orphans(con) == []


def test_flags_foundation_demo_label():
    con = _mk_db()
    con.execute("INSERT INTO cashflows VALUES ('4','c','Daniel Lohn','2026-06-07T10:00:00.000Z',NULL)")
    con.commit()
    findings = dia.scan_database(con)
    assert any(f["label"] == "Daniel Lohn" for f in findings)


def test_clean_db_has_no_findings():
    con = _mk_db()
    con.execute("INSERT INTO cashflows VALUES ('5','c','Lohn','2026-06-07T10:00:00.000Z',NULL)")
    con.commit()
    assert dia.scan_database(con) == []


def test_valid_timestamp_regex():
    assert dia.VALID_TS.match("2026-06-12T18:24:30.446Z")
    assert not dia.VALID_TS.match("2026-06-12T18:24:446Z")  # fehlende Sekunden (seed_leart-Bug)


def test_foundation_endpoint_blocked_in_production():
    # Code-Guard vorhanden: Foundation-Seed in Produktion gesperrt.
    src = (BACKEND_ROOT / "routers" / "system.py").read_text(encoding="utf-8")
    assert 'app_env' in src and 'foundation-example' in src
    assert 'in der Produktionsumgebung gesperrt' in src
