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
from sqlalchemy.engine import URL
from sqlalchemy.exc import DatabaseError

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
        # URL.create statt f"sqlite:///{variant}": im URL-String waere das "?" der
        # Query-Trenner, die Engine saehe nur den Teil davor (Linux "/": Verzeichnis,
        # SELECT 1 gruen; Windows: OperationalError) und der Waechter nie das Ziel.
        engine = create_engine(URL.create("sqlite", database=variant))
        with pytest.raises(loc.OwnerDatabaseRefused):
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


# --- Nachtrag 4 (N-907-16): unbekannte Geraete-Formen fail-closed ---------------

BS = chr(92)  # ein Backslash (Schreibweisen ohne Escape-Verwechslung)


def _unknown_device_variants(target: Path) -> list[str]:
    plain = str(target)
    q, d = BS * 2 + "?" + BS, BS * 2 + "." + BS  # \\?\ und \\.\
    return [
        q + "GLOBALROOT" + BS + "??" + BS + plain,
        q + "Volume{0a1b2c3d-0000-4000-8000-000000000000}" + BS + plain[3:],
        d + "HarddiskVolume3" + BS + plain[3:],
        d + "GLOBALROOT" + BS + "Device" + BS + "HarddiskVolume3" + BS + plain[3:],
        "//?/GLOBALROOT/??/" + target.as_posix(),
    ]


def test_unknown_device_forms_refused_at_all_three_checkpoints(tmp_path, monkeypatch):
    """Nicht auf Laufwerk/UNC zurueckfuehrbare Geraete-Formen (?- und .-Praefix) werden
    immer verweigert (auch ausserhalb des Owner-Profils); es entsteht keine Datei."""
    import database

    target = tmp_path / "geraet" / "x.db"
    target.parent.mkdir()
    for variant in _unknown_device_variants(target):
        assert loc.is_unresolvable_device_path(variant), variant
        assert loc.owner_db_refusal(variant, {"ARES_OWNER_DB_OPT_IN": "1"})
        with pytest.raises(loc.OwnerDatabaseRefused, match="Geraete-Pfad"):
            config.guarded_sqlite_connect(variant, context="probe")
        with pytest.raises(loc.OwnerDatabaseRefused, match="Geraete-Pfad"):
            database.bootstrap_sqlite_schema(db_path=variant)
        engine = create_engine(URL.create("sqlite", database=variant))  # s. oben
        with pytest.raises(loc.OwnerDatabaseRefused, match="Geraete-Pfad"):
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        engine.dispose()
    assert list(target.parent.iterdir()) == []


def test_embedded_device_form_after_abspath_is_refused():
    """CI (Linux): pysqlite macht aus dem relativen Geraete-Pfad per abspath
    ``/cwd/<\\\\?\\...>`` -- auch eingebettet nie pruefbar, also verweigert."""
    variant = BS * 2 + "?" + BS + "GLOBALROOT" + BS + "??" + BS + "/tmp/x/x.db"
    assert loc.is_unresolvable_device_path("/home/runner/work/" + variant)
    assert loc.is_unresolvable_device_path("C:" + BS + "work" + BS + variant)
    assert not loc.is_unresolvable_device_path("/home/runner/work/ok.db")


def test_known_device_forms_are_not_blanket_refused(tmp_path):
    plain = str(tmp_path / "ok.db")
    for variant in (BS * 2 + "?" + BS + plain, BS * 2 + "." + BS + plain, plain) if WINDOWS else (plain,):
        assert not loc.is_unresolvable_device_path(variant), variant
