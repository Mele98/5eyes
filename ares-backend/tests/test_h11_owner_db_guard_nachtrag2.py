"""H11 Nachtrag 2 (Pruefrunde 096e9a69, N-907-01..04): Owner-DB-Waechter ohne Alias-Luecken.

Alle Faelle laufen gegen ein Temp-HOME, das als "Owner-Profil" simuliert wird
(``Path.home`` umgebogen) -- das echte Profil wird nie beruehrt.

* N-907-01: EINE Normalisierung (``core.db_location.normalize_db_target``) fuer
  alle Pruefpunkte: ``file:``-URIs (``file:///C:/``, ``file://localhost/``,
  Prozent-Kodierung, ``?mode``), NTFS-Datenstroeme, Punkt/Leerzeichen am Ende,
  ``abspath`` + ``realpath``. Lifespan-Pruefung und roher Schema-Bootstrap
  verweigern VOR dem Anlegen.
* N-907-02 (trivialer Teil): ``ATTACH`` auf die Owner-DB wird verweigert.
* N-907-03: ``ARES_TEST=1`` und ``NODE_ENV=test`` gelten als Testmodus.
* N-907-04: der Bootstrap-Hook faengt jede Ausnahme.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine, text

import config
import core.db_location as loc


@pytest.fixture()
def owner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ares").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home / "ares" / "ares.db"


def _variants(target: Path) -> list[str]:
    posix = target.as_posix()
    drive_style = posix if posix[1:2] == ":" else posix  # Windows: C:/..., POSIX: /...
    lead = "" if drive_style.startswith("/") else "/"
    encoded = quote(drive_style).replace("ares.db", "ar%65s.db")
    return [
        str(target),
        str(target).upper() if len(str(target)) and str(target)[1:2] == ":" else str(target),
        f"file:{drive_style}?mode=rwc",
        f"file://{lead}{drive_style}?mode=rwc",
        f"file://localhost{lead}{drive_style}",
        f"file://{lead}{encoded}",
        str(target) + "::$DATA",
        str(target) + ":stream",
        str(target) + ".",
        str(target) + " ",
        str(target) + ". .",
        str(target.parent / ".." / "ares" / "ares.db"),
    ]


def test_every_spelling_is_recognised_as_owner_path(owner):
    missed = [v for v in _variants(owner) if not loc.is_owner_db_path(v)]
    assert missed == []
    assert not loc.is_owner_db_path(owner.parent / "ares-other.db")


def test_sqlite_url_with_file_uri_resolves_to_the_owner_file(owner):
    posix = owner.as_posix()
    lead = "" if posix.startswith("/") else "/"
    url_file = loc.sqlite_url_file(f"sqlite:///file://{lead}{posix}?mode=rwc&uri=true")
    assert url_file is not None and loc.is_owner_db_path(url_file)


@pytest.mark.parametrize("suffix", ["", "::$DATA", ".", " "])
def test_engine_connect_variants_refused_before_the_file_exists(owner, suffix):
    engine = create_engine(f"sqlite:///{owner}{suffix}")
    with pytest.raises(loc.OwnerDatabaseRefused):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    assert list(owner.parent.iterdir()) == []


def test_engine_connect_with_file_uri_refused(owner):
    posix = owner.as_posix()
    lead = "" if posix.startswith("/") else "/"
    for url in (f"sqlite:///file://{lead}{posix}?mode=rwc&uri=true",
                f"sqlite:///file://localhost{lead}{posix}?mode=rwc&uri=true"):
        engine = create_engine(url)
        with pytest.raises(loc.OwnerDatabaseRefused):
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    assert list(owner.parent.iterdir()) == []


@pytest.mark.parametrize("suffix", [".", " ", "::$DATA"])
def test_lifespan_check_and_raw_schema_bootstrap_refuse_before_creating(owner, suffix):
    import database

    with pytest.raises(loc.OwnerDatabaseRefused):
        config.refuse_owner_db_settings(SimpleNamespace(db_path=str(owner) + suffix, database_url=""), context="Start")
    with pytest.raises(loc.OwnerDatabaseRefused):
        database.bootstrap_sqlite_schema(db_path=str(owner) + suffix)
    assert list(owner.parent.iterdir()) == []


def test_attach_of_the_owner_db_is_refused(owner, tmp_path):
    """N-907-12: SQLite-Authorizer (SQLITE_ATTACH) statt Textparsing."""
    from sqlalchemy.exc import DatabaseError

    engine = create_engine(f"sqlite:///{tmp_path / 'harmless.db'}")
    with engine.connect() as conn:
        with pytest.raises(DatabaseError, match="not authorized"):
            conn.execute(text(f"ATTACH DATABASE '{owner}.' AS o"))
        with pytest.raises(DatabaseError, match="not authorized"):
            conn.exec_driver_sql("ATTACH DATABASE ? AS o", (str(owner),))
        conn.execute(text(f"ATTACH DATABASE '{tmp_path / 'other.db'}' AS ok"))  # Positivkontrolle
    assert list(owner.parent.iterdir()) == []


@pytest.mark.parametrize("env", [{"ARES_TEST": "1"}, {"NODE_ENV": "test"}, {"ARES_TEST_MODE": "1"}])
def test_desktop_test_flags_count_as_test_mode(env, monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "pytest", raising=False)
    assert loc.test_or_ci_mode(env) == "Testmodus"
    reason = loc.owner_db_refusal(loc.default_db_path(), {**env, "ARES_OWNER_DB_OPT_IN": "1"})
    assert reason and reason.startswith("Testmodus")  # Opt-in wirkungslos


def test_bootstrap_hook_never_fails_and_logs_without_personal_data(monkeypatch, caplog):
    import routers.allocation as allocation

    class _Db:
        rolled_back = False

        def commit(self):
            raise AssertionError("kein Commit nach Fehler")

        def rollback(self):
            self.rolled_back = True

    def _boom(*_a, **_k):
        raise RuntimeError("OperationalError: database is locked (Kunde Max Muster)")

    monkeypatch.setattr(allocation, "ensure_runtime_reference_data", _boom)
    db = _Db()
    with caplog.at_level("WARNING"):
        assert allocation.seed_reference_data_at_bootstrap(db, "user-123") is False
    assert db.rolled_back
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and "Muster" not in logged and "user-123" not in logged
