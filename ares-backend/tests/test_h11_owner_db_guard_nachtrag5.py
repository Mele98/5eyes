"""H11 Nachtrag 5 (Pruefung 2bb87211 REJECTED, N-907-17/-18/-19).

Alle Faelle laufen gegen ein Temp-HOME als simuliertes Owner-Profil
(``Path.home`` und HOME/USERPROFILE umgebogen); das echte Profil wird nie
beruehrt. Die simulierte Owner-DB traegt eine Markertabelle; jeder Test prueft,
dass sie unveraendert bleibt.

* N-907-17 (a): Allowlist -- jede Geraete-Form (``\\\\?\\``/``\\\\.\\`` in jeder
  Mischung aus ``\\`` und ``/``, auch ``\\\\.\\UNC\\``), NT-Praefix, UNC-Admin-
  Freigabe und jede URL-kodierte Fassung davon wird immer verweigert -- an allen
  drei Pruefpunkten (guarded_sqlite_connect, Engine-do_connect, Bootstrap).
* N-907-17 (b): Identitaet auf Dateisystemebene (st_dev/st_ino) gegen alle
  Owner-Ziele inkl. ``-wal``/``-shm``; Pruef-Fehler -> verweigert.
* N-907-18: ``restore_database`` prueft das Ziel vor mkdir/os.replace.
* N-907-19: ``set_authorizer`` ist auf geschuetzten Verbindungen gesperrt.
"""
from __future__ import annotations

import hashlib
import itertools
import os
import socket
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

import config
import core.db_location as loc

WINDOWS = os.name == "nt"
BS = chr(92)
FORM_REASON = "Geraete-Pfad|UNC-Admin-Freigabe"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ares").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture()
def owner(home):
    db = home / "ares" / "ares.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE marker(x)")
    conn.execute("INSERT INTO marker VALUES ('OWNER')")
    conn.commit()
    conn.close()
    return db


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owner_state(owner: Path) -> tuple:
    return (_digest(owner), sorted(p.name for p in owner.parent.iterdir()))


def forbidden_variants(owner: Path) -> list[str]:
    """Alle Formen aus dem Pruefbericht + Slash-/Gross-Klein-Kombinatorik."""
    plain = str(owner)
    fw = owner.as_posix()
    if WINDOWS:
        drive, rest = plain[0], plain[3:]
    else:  # unter POSIX bleiben die Formen Text -- die Regel ist plattformunabhaengig
        drive, rest = "C", plain.lstrip("/")
    rest_bs = rest.replace("/", BS)
    rest_fw = rest_bs.replace(BS, "/")
    host = socket.gethostname()
    out: list[str] = []
    # Geraete-Praefix: 2 Trenner x ?/. x Trenner, mit Laufwerk und UNC-Rest
    for a, b, mid, c in itertools.product((BS, "/"), (BS, "/"), ("?", "."), (BS, "/")):
        prefix = a + b + mid + c
        out += [
            prefix + drive + ":" + BS + rest_bs,
            prefix + drive.lower() + ":/" + rest_fw,
            prefix + "UNC" + BS + "localhost" + BS + drive + "$" + BS + rest_bs,
            prefix + "unc/localhost/" + drive.lower() + "$/" + rest_fw,
            prefix + "GLOBALROOT" + BS + "??" + BS + drive + ":" + BS + rest_bs,
            prefix + "globalroot/Device/HarddiskVolume3/" + rest_fw,
            prefix + "Volume{0a1b2c3d-0000-4000-8000-000000000000}" + BS + rest_bs,
        ]
    # Pruefbericht, woertlich
    out += [
        BS * 2 + "?/" + fw, "/" + BS + "?" + BS + plain, BS + "/?" + BS + plain,
        BS * 2 + "./" + fw, BS * 2 + "." + BS + "UNC" + BS + "localhost" + BS + drive + "$" + BS + rest_bs,
        BS * 2 + "." + BS + "unc" + BS + "localhost" + BS + drive.lower() + "$" + BS + rest_bs,
        BS * 2 + "?" + BS + "UNC/localhost/" + drive + "$/" + rest_fw,
        BS + "??" + BS + drive + ":" + BS + rest_bs,
    ]
    # UNC-Admin-Freigaben (beliebiger Host, Gross/Klein, Slash-Mischung)
    for h in ("localhost", "LOCALHOST", "127.0.0.1", "127.0.0.2", "[::1]", host, host.upper()):
        out += [BS * 2 + h + BS + drive + "$" + BS + rest_bs,
                "//" + h + "/" + drive.lower() + "$/" + rest_fw,
                BS + "/" + h + BS + drive + "$/" + rest_fw]
    # file:-URIs, einfach und doppelt kodiert
    dev = BS * 2 + "?" + BS + drive + ":" + BS + rest_bs
    out += [
        "file:" + quote(dev, safe=""), "file:%5C%5C%3F/" + fw,
        "file:///" + quote(dev, safe=""), "file:" + quote(quote(dev, safe=""), safe=""),
        "file:////localhost/" + drive + "$/" + rest_fw, "file:" + dev,
        "file://localhost/" + quote("//?/", safe="") + fw,
        "FILE:%5c%5c%2e%5c" + fw,
    ]
    return out


def test_every_forbidden_form_is_refused_even_with_opt_in(owner):
    missed = [v for v in forbidden_variants(owner)
              if not loc.owner_db_refusal(v, {"ARES_OWNER_DB_OPT_IN": "1"})]
    assert missed == []
    for v in forbidden_variants(owner):
        assert loc.forbidden_path_form(v), v


def test_forbidden_forms_refused_at_all_three_checkpoints(owner):
    import database

    before = _owner_state(owner)
    for variant in forbidden_variants(owner):
        with pytest.raises(loc.OwnerDatabaseRefused, match=FORM_REASON):
            config.guarded_sqlite_connect(variant, context="probe")
        with pytest.raises(loc.OwnerDatabaseRefused, match=FORM_REASON):
            database.bootstrap_sqlite_schema(db_path=variant)
        is_uri = variant[:5].lower() == "file:"
        # file:-Formen mit uri=true (so liest SQLite sie als URI); ohne uri=true
        # siehe test_file_forms_without_uri_never_open_anything.
        engine = create_engine(URL.create("sqlite", database=variant,
                                          query={"uri": "true"} if is_uri else {}))
        # POSIX: pysqlite oeffnet os.path.abspath(variant); normpath streicht dabei
        # das "."-Segment ("//./C:/x" -> "//C:/x"). Der Engine-Waechter sieht dann
        # einen normalen, nicht existierenden Nicht-Owner-Pfad -- SQLite scheitert
        # ("unable to open"), es entsteht nichts. Nur dort ist OperationalError
        # zulaessig, und nur wenn das tatsaechliche Ziel nachweislich kein Owner ist.
        opened = os.path.abspath(variant)
        collapsed = (not WINDOWS and not is_uri and loc.forbidden_path_form(opened) is None)
        if collapsed:
            assert not loc.is_owner_db_path(opened) and loc.fs_identity_owner(opened) is None, opened
        with pytest.raises((loc.OwnerDatabaseRefused, OperationalError) if collapsed
                           else loc.OwnerDatabaseRefused) as info:
            with engine.connect() as conn:
                conn.execute(text("SELECT x FROM marker"))
        engine.dispose()
        if collapsed and not isinstance(info.value, loc.OwnerDatabaseRefused):
            # nichts geoeffnet/angelegt -- "no such table" hiesse: fremde Datei erzeugt
            assert "unable to open" in str(info.value), (variant, info.value)
            assert not os.path.exists(opened), opened
    assert _owner_state(owner) == before


def test_file_forms_without_uri_never_open_anything(owner, tmp_path, monkeypatch):
    """Ohne ``uri=true`` macht pysqlite aus ``file:...`` einen relativen Namen
    unter dem Arbeitsordner (Windows: NTFS-Datenstrom an ``file``). Das darf weder
    die Owner-DB noch irgendeine Datei oeffnen bzw. anlegen."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    before = _owner_state(owner)
    for variant in (v for v in forbidden_variants(owner) if v[:5].lower() == "file:"):
        engine = create_engine(URL.create("sqlite", database=variant))
        with pytest.raises(Exception) as info:
            with engine.connect() as conn:
                conn.execute(text("SELECT x FROM marker"))
        engine.dispose()
        assert "no such table" not in str(info.value), variant
    assert list(cwd.iterdir()) == []
    assert _owner_state(owner) == before


def test_harmless_paths_stay_allowed(tmp_path, home):
    ok = tmp_path / "data" / "x.db"
    for candidate in (str(ok), ok.as_posix(), "relative.db", "/data///./x.db" if not WINDOWS else str(ok),
                      f"file:{ok.as_posix()}?mode=ro", ":memory:"):
        assert loc.forbidden_path_form(candidate) is None, candidate
        assert loc.owner_db_refusal(candidate, {}) is None, candidate
    ok.parent.mkdir()
    config.guarded_sqlite_connect(str(ok), context="probe").close()
    assert ok.exists()


# --- (b) Identitaet auf Dateisystemebene ------------------------------------------

def test_hardlink_to_owner_is_refused(owner, tmp_path):
    alias = tmp_path / "anderswo" / "harmlos.db"
    alias.parent.mkdir()
    try:
        os.link(owner, alias)
    except OSError as exc:
        pytest.skip(f"keine Hardlinks: {exc}")
    assert loc.fs_identity_owner(alias) == "owner"
    with pytest.raises(loc.OwnerDatabaseRefused):
        config.guarded_sqlite_connect(str(alias), context="probe")


def test_symlink_to_owner_is_refused(owner, tmp_path):
    alias = tmp_path / "link.db"
    try:
        alias.symlink_to(owner)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"keine Symlinks: {exc}")
    assert loc.fs_identity_owner(alias) == "owner"
    with pytest.raises(loc.OwnerDatabaseRefused):
        config.guarded_sqlite_connect(str(alias), context="probe")


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_owner_companion_files_are_owner_targets(owner, suffix, tmp_path):
    companion = Path(str(owner) + suffix)
    companion.write_bytes(b"")
    assert loc.owner_db_refusal(str(companion), {})
    alias = tmp_path / ("x" + suffix)
    try:
        os.link(companion, alias)
    except OSError:
        return
    assert loc.fs_identity_owner(alias) == "owner"


@pytest.mark.skipif(not WINDOWS, reason="8.3-Kurznamen gibt es nur unter Windows")
def test_short_name_alias_is_refused(owner):
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(owner), buf, 1024)
    if not buf.value or buf.value == str(owner):
        pytest.skip("kein 8.3-Name vergeben")
    assert loc.fs_identity_owner(buf.value) == "owner"
    assert loc.owner_db_refusal(buf.value, {"ARES_OWNER_DB_OPT_IN": "1"})


def test_identity_check_error_is_fail_closed(owner, tmp_path, monkeypatch):
    probe = tmp_path / "p.db"
    real_stat = os.stat

    def broken(path, *a, **kw):
        if str(path).endswith("p.db"):
            raise PermissionError("simuliert")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(loc.os, "stat", broken)
    assert loc.fs_identity_owner(probe) == "error"
    reason = loc.owner_db_refusal(str(probe), {"ARES_OWNER_DB_OPT_IN": "1"})
    assert reason and "Identitaetspruefung" in reason


def _owner_unreadable(monkeypatch, owner):
    real_stat = os.stat

    def broken(path, *a, **kw):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(str(owner)):
            raise PermissionError("simuliert")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(loc.os, "stat", broken)


def test_unreadable_owner_target_blocks_only_possibly_affected_candidates(owner, tmp_path, monkeypatch):
    """H12 N-907-23: ein unlesbares Owner-Ziel sperrt nicht mehr jede DB. Eine
    isolierte Datei mit genau einem Namen und eine noch fehlende Datei bleiben
    offen; ein Hardlink-Kandidat (Identitaet unbekannt) bleibt gesperrt, mit
    dem betroffenen Owner-Ziel in der Meldung (Home als ``~``)."""
    single = tmp_path / "isoliert.db"
    sqlite3.connect(single).close()
    missing = tmp_path / "neu" / "neu.db"
    linked_src = tmp_path / "quelle.db"
    sqlite3.connect(linked_src).close()
    linked = tmp_path / "hardlink.db"
    os.link(linked_src, linked)
    _owner_unreadable(monkeypatch, owner)
    assert loc.fs_identity_owner(single) is None
    assert loc.fs_identity_owner(missing) is None
    assert loc.owner_db_refusal(str(single), {}) is None
    assert loc.fs_identity_owner(linked) == "error"
    reason = loc.owner_db_refusal(str(linked), {})
    assert reason and "Owner-Ziel nicht lesbar" in reason and "verweigert (fail-closed)" in reason
    assert "~" in reason and str(owner.parent.parent) not in reason
    # Der Owner-Pfad selbst bleibt per Textabgleich gesperrt.
    assert loc.owner_db_refusal(str(owner), {})


# --- N-907-18: Restore-Ziel ------------------------------------------------------

def _backup_source(tmp_path: Path) -> Path:
    src = tmp_path / "bk" / "b.db"
    src.parent.mkdir()
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE marker(x)")
    conn.execute("INSERT INTO marker VALUES ('AUS_BACKUP')")
    conn.commit()
    conn.close()
    return src


@pytest.mark.parametrize("spelling", ["path", "str", "tilde"])
def test_restore_refuses_owner_target_and_leaves_it_untouched(owner, tmp_path, spelling):
    from services import backup

    src = _backup_source(tmp_path)
    target = {"path": owner, "str": str(owner), "tilde": "~/ares/ares.db"}[spelling]
    before = _owner_state(owner)
    with pytest.raises(loc.OwnerDatabaseRefused):
        backup.restore_database(src, target_db_path=target, verify_hash=False, verify_hmac=False)
    assert _owner_state(owner) == before


def test_restore_refuses_missing_owner_target_without_creating_folder(home, tmp_path):
    from services import backup

    src = _backup_source(tmp_path)
    legacy = home / "5eyes" / "5eyes.db"
    with pytest.raises(loc.OwnerDatabaseRefused):
        backup.restore_database(src, target_db_path=legacy, verify_hash=False, verify_hmac=False)
    assert not legacy.parent.exists()


def test_restore_refuses_hardlinked_alias_of_owner(owner, tmp_path):
    from services import backup

    alias = tmp_path / "alias" / "harmlos.db"
    alias.parent.mkdir()
    try:
        os.link(owner, alias)
    except OSError as exc:
        pytest.skip(f"keine Hardlinks: {exc}")
    before = _owner_state(owner)
    with pytest.raises(loc.OwnerDatabaseRefused):
        backup.restore_database(_backup_source(tmp_path), target_db_path=alias,
                                verify_hash=False, verify_hmac=False)
    assert _owner_state(owner) == before


def test_atomic_copy_refuses_owner_target(owner, tmp_path):
    from services import backup

    before = _owner_state(owner)
    with pytest.raises(loc.OwnerDatabaseRefused):
        backup._perform_atomic_copy(_backup_source(tmp_path), owner)
    assert _owner_state(owner) == before


def test_maintenance_restore_refuses_owner_target(owner, tmp_path):
    from services import maintenance

    before = _owner_state(owner)
    with pytest.raises(loc.OwnerDatabaseRefused):
        maintenance.restore_backup(backup_path=_backup_source(tmp_path), target_db_path=owner,
                                   verify_hash=False, verify_hmac=False)
    assert _owner_state(owner) == before


def test_restore_to_isolated_target_still_works(home, tmp_path):
    from services import backup

    target = tmp_path / "ziel" / "neu.db"
    backup.restore_database(_backup_source(tmp_path), target_db_path=target,
                            verify_hash=False, verify_hmac=False)
    conn = sqlite3.connect(target)
    assert conn.execute("SELECT x FROM marker").fetchone()[0] == "AUS_BACKUP"
    conn.close()


# --- N-907-19: set_authorizer zur Laufzeit gesperrt -----------------------------

def test_raw_connection_authorizer_cannot_be_replaced(owner, tmp_path):
    conn = config.guarded_sqlite_connect(str(tmp_path / "a.db"), context="probe")
    try:
        with pytest.raises(config.AuthorizerLocked):
            conn.set_authorizer(None)
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"ATTACH DATABASE '{owner}' AS o")
    finally:
        conn.close()


def test_engine_connection_authorizer_cannot_be_replaced(owner, tmp_path):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "e.db")))
    try:
        with engine.connect() as conn:
            dbapi = conn.connection.dbapi_connection
            with pytest.raises(config.AuthorizerLocked):
                dbapi.set_authorizer(None)
            with pytest.raises(Exception, match="not authorized"):
                conn.exec_driver_sql(f"ATTACH DATABASE '{owner}' AS o")
    finally:
        engine.dispose()


def test_explicit_factory_is_kept(tmp_path):
    class Own(sqlite3.Connection):
        pass

    conn = config.guarded_sqlite_connect(str(tmp_path / "f.db"), context="probe", factory=Own)
    try:
        # H12 N-907-21 (bewusste Vertragsaenderung): die eigene Klasse bleibt
        # wirksam (Unterklasse), wird aber abgeleitet, damit die Authorizer-
        # Sperre auch hier greift -- vorher blieb sie unveraendert ungeschuetzt.
        assert isinstance(conn, Own) and type(conn) is not Own
        with pytest.raises(config.AuthorizerLocked):
            conn.set_authorizer(None)
    finally:
        conn.close()
