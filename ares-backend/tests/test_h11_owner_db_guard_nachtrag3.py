"""H11 Nachtrag 3 (Delta-Pruefung 50627939, N-907-11/-12).

Alle Faelle laufen gegen ein Temp-HOME als simuliertes Owner-Profil
(``Path.home`` umgebogen); das echte Profil wird nie beruehrt.

* N-907-11: Win32-Geraete-Namensraum (``\\\\?\\``, ``\\\\.\\``, ``\\\\?\\UNC\\``)
  und UNC-Admin-Freigaben des eigenen Rechners (``\\\\localhost\\C$``,
  ``\\\\127.0.0.1\\C$``, ``\\\\<rechner>\\C$``) umgingen den Waechter. Jetzt:
  Praefixe/Freigaben werden zurueckgefuehrt, und der Vergleich laeuft ueber die
  Identitaet (``samefile`` bzw. derselbe existierende Elternordner per
  st_dev/st_ino + Dateiname casefold) -- fuer alle drei Pruefpunkte
  (``guarded_sqlite_connect``, Engine, Schema-Bootstrap).
* N-907-12: ATTACH ueber den SQLite-Authorizer (``SQLITE_ATTACH``) auf jeder
  Verbindung (Engine und roh), nicht per Textparsing: Kommentare, ``||`` und
  Parameter loest SQLite selbst auf; ein nicht aufloesbares Ziel wird verweigert.
"""
from __future__ import annotations

import os
import socket
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError, OperationalError

import config
import core.db_location as loc

WINDOWS = os.name == "nt"


@pytest.fixture()
def owner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ares").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home / "ares" / "ares.db"


def _win_variants(owner: Path) -> list[str]:
    plain = str(owner)
    drive, rest = plain[0], plain[3:]
    host = socket.gethostname()
    return [
        "\\\\?\\" + plain,
        "\\\\.\\" + plain,
        "\\\\?\\UNC\\localhost\\" + drive + "$\\" + rest,
        "\\\\localhost\\" + drive + "$\\" + rest,
        "\\\\127.0.0.1\\" + drive.lower() + "$\\" + rest,
        "\\\\" + host + "\\" + drive + "$\\" + rest,
        "//?/" + owner.as_posix(),
        "\\\\?\\" + plain + ".",
    ]


@pytest.mark.skipif(not WINDOWS, reason="Win32-Geraete-/UNC-Schreibweisen gibt es nur unter Windows")
def test_device_and_admin_share_spellings_are_owner_paths(owner):
    missed = [v for v in _win_variants(owner) if not loc.is_owner_db_path(v)]
    assert missed == []


@pytest.mark.skipif(not WINDOWS, reason="Win32-Geraete-/UNC-Schreibweisen gibt es nur unter Windows")
def test_all_three_checkpoints_refuse_device_and_unc_spellings_before_creating(owner):
    import database

    for variant in _win_variants(owner):
        with pytest.raises(loc.OwnerDatabaseRefused):
            config.guarded_sqlite_connect(variant, context="probe")
        with pytest.raises(loc.OwnerDatabaseRefused):
            database.bootstrap_sqlite_schema(db_path=variant)
        engine = create_engine(f"sqlite:///{variant}")
        with pytest.raises((loc.OwnerDatabaseRefused, OperationalError)):
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        engine.dispose()
    assert list(owner.parent.iterdir()) == []


def test_identity_via_existing_parent_folder_and_casefold_name(owner, tmp_path):
    """Kein Textvergleich noetig: gleicher existierender Elternordner + Name."""
    alias = Path(str(owner.parent) + os.sep + "." + os.sep + "ARES.DB")
    assert loc._same_identity(alias, owner)
    other = tmp_path / "anders"
    other.mkdir()
    assert not loc._same_identity(other / "ares.db", owner)
    assert not loc._same_identity(owner.parent / "ares-2.db", owner)


@pytest.mark.parametrize("statement", [
    "ATTACH /*kommentar*/ DATABASE '{owner}' AS o",
    "ATTACH DATABASE '{home}' || '/ares/ares.db' AS o",
    "ATTACH\n'{owner}'\nAS o",
    "attach database '{owner}.' as o",
])
def test_attach_variants_refused_on_engine_and_raw_connection(owner, tmp_path, statement):
    sql = statement.format(owner=owner, home=owner.parent.parent.as_posix())
    engine = create_engine(f"sqlite:///{tmp_path / 'harmless.db'}")
    with engine.connect() as conn:
        with pytest.raises(DatabaseError, match="not authorized"):
            conn.exec_driver_sql(sql)
    raw = config.guarded_sqlite_connect(str(tmp_path / "raw.db"), context="probe")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            raw.execute(sql)
    finally:
        raw.close()
    assert list(owner.parent.iterdir()) == []


def test_attach_of_harmless_literal_and_memory_still_works(owner, tmp_path):
    raw = config.guarded_sqlite_connect(str(tmp_path / "raw.db"), context="probe")
    try:
        raw.execute(f"ATTACH DATABASE '{tmp_path / 'side.db'}' AS side")
        raw.execute("ATTACH DATABASE ':memory:' AS mem")
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            raw.execute("ATTACH DATABASE ? AS p", (str(tmp_path / "param.db"),))  # nicht aufloesbar
    finally:
        raw.close()
    assert (tmp_path / "side.db").exists() and not (tmp_path / "param.db").exists()


def test_attach_decision_rule():
    assert loc.attach_decision(None, {}) == loc.SQLITE_DENY
    assert loc.attach_decision(":memory:", {}) == loc.SQLITE_OK
