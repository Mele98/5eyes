"""H11 Nachtrag 2 (Codex C-907-01, REJECTED_AT_SHA 096e9a69): kein roher
SQLite-/SQLCipher-Connect am Owner-Waechter vorbei.

``services/backup.py`` oeffnete SQLite bzw. SQLCipher direkt; der klassenweite
SQLAlchemy-Waechter greift dort nicht. Jetzt laeuft JEDER rohe Connect im
Backend und in den Skripten ueber ``config.guarded_sqlite_connect`` (dieselbe
Owner-Pfad-Pruefung). Ein AST-Waechter verbietet rohe ``*.connect``-Aufrufe der
Module ``sqlite3``/``sqlcipher3``/``pysqlcipher3`` (auch per Alias und
``from sqlite3 import connect``) ausserhalb dieser Funktion; Ausnahmen nur mit
Begruendung je Aufrufstelle.

Verhaltenstests laufen gegen ein Temp-HOME als simuliertes Owner-Profil.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import config
import core.db_location as loc

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
RAW_MODULES = {"sqlite3", "sqlcipher3", "pysqlcipher3"}
SKIP = {"tests", "node_modules", ".venv", "venv", "__pycache__", "versions"}

# "<pfad>::<funktion>" -> Begruendung. Nur Ziele, die nie eine Owner-DB sein koennen.
ALLOWED: dict[str, str] = {
    "ares-backend/config.py::guarded_sqlite_connect":
        "Die zentrale Funktion selbst: Default-Connector sqlite3.connect, Aufruf erst nach der Owner-Pruefung.",
    "ares-backend/services/sqlite_check_constraint_upgrade.py::_ddl_parses":
        "DDL-Probe auf ':memory:' (keine Datei); Modul darf keine weitere Lazy-Import-Kante bekommen.",
    "scripts/security_gate.py::_seed_clean_integrity_db":
        "CI-Werkzeug: legt eine synthetische DB in einem tempfile-Verzeichnis an (Pfad vom Aufrufer).",
    "scripts/packaging_smoke.py::run_start_smoke":
        "CI/Release-Werkzeug: liest die Smoke-DB im isolierten Temp-Root nur lesend (mode=ro).",
}


def _raw_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in RAW_MODULES:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in RAW_MODULES:
            for alias in node.names:
                if alias.name in RAW_CALLABLES:  # H12 N-907-22: auch ``Connection``
                    funcs.add(alias.asname or alias.name)
                elif alias.name == "dbapi2":
                    modules.add(alias.asname or "dbapi2")
    return modules, funcs


RAW_CALLABLES = {"connect", "Connection"}


def raw_connect_sites(source: str, rel: str) -> list[str]:
    """H12 N-907-22: jede REFERENZ (nicht nur der Aufruf) auf ``<roh>.connect``
    bzw. ``<roh>.Connection`` -- also auch ``functools.partial(sqlite3.connect,
    p)``, ``c = sqlite3.connect`` und ``sqlite3.Connection(p)`` --, dazu jedes
    ``creator=``-Argument (``create_engine(creator=...)`` umgeht ``do_connect``
    und damit den Engine-Waechter). Einzige Ausnahme: ``connector=<roh>.connect``
    als Argument an ``guarded_sqlite_connect`` (dort wird geprueft)."""
    tree = ast.parse(source)
    modules, funcs = _raw_aliases(tree)
    allowed_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) \
                == "guarded_sqlite_connect":
            for kw in node.keywords:
                if kw.arg == "connector":
                    allowed_nodes.add(id(kw.value))
        # Typannotationen (``-> sqlite3.Connection``) oeffnen nichts.
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
            args = node.args
            annotations += [a.annotation for a in args.posonlyargs + args.args + args.kwonlyargs]
            annotations += [a.annotation for a in (args.vararg, args.kwarg) if a is not None]
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is not None:
                allowed_nodes.update(id(n) for n in ast.walk(annotation))
    found: list[str] = []

    def is_raw_ref(child: ast.AST) -> bool:
        if isinstance(child, ast.Attribute) and child.attr in RAW_CALLABLES:
            base = ast.unparse(child.value)
            return base in modules or base.split(".")[0] in modules
        return isinstance(child, ast.Name) and child.id in funcs and isinstance(child.ctx, ast.Load)

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if is_raw_ref(child) and id(child) not in allowed_nodes:
                found.append(f"{rel}::{scope}")
                continue  # ``a.b.connect`` nur einmal zaehlen
            if isinstance(child, ast.Call) and any(kw.arg == "creator" for kw in child.keywords):
                found.append(f"{rel}::{scope}")
            visit(child, inner)

    visit(tree, "<modul>")
    return found


def _product_files() -> list[Path]:
    roots = [BACKEND, REPO / "scripts", REPO / "tools"]
    out = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if SKIP & set(path.relative_to(REPO).parts):
                continue
            out.append(path)
    return out


def _all_sites() -> list[str]:
    sites = []
    for path in _product_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "connect" in text and any(m in text for m in RAW_MODULES):
            sites.extend(raw_connect_sites(text, path.relative_to(REPO).as_posix()))
    return sites


def test_no_raw_sqlite_connect_outside_the_central_function():
    sites = _all_sites()
    assert [s for s in sites if s not in ALLOWED] == []
    assert set(ALLOWED) <= set(sites), "veraltete Ausnahme"
    assert all(reason.strip() for reason in ALLOWED.values())


# --- Nachtrag 4: set_authorizer nur im Waechter -------------------------------

# N5 (N-907-19): zusaetzlich die Sperre selbst (AresGuardedConnection.set_authorizer
# ruft die Basisklasse; _guarded_factory_for baut die Klasse). Der Laufzeitschutz
# ist der primaere Schutz; dieses AST-Verbot bleibt als Stolperfalle fuer den
# Basisklassen-Aufruf ``sqlite3.Connection.set_authorizer(conn, ...)``.
AUTHORIZER_ALLOWED = {
    "ares-backend/config.py::install_attach_authorizer",
    "ares-backend/config.py::set_authorizer",
    "ares-backend/config.py::_guarded_subclass",
}


def authorizer_sites(source: str, rel: str) -> list[str]:
    """Jeder Zugriff auf ``set_authorizer`` (Aufruf, Attribut, ``getattr``-Name)."""
    found: list[str] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Attribute) and child.attr == "set_authorizer":
                found.append(f"{rel}::{scope}")
            elif isinstance(child, ast.Constant) and child.value == "set_authorizer":
                found.append(f"{rel}::{scope}")
            visit(child, inner)

    visit(ast.parse(source), "<modul>")
    return found


def test_set_authorizer_only_inside_the_guard():
    """Ein fremder Authorizer wuerde den ATTACH-Waechter (N-907-12) auf Verbindungen
    aus guarded_sqlite_connect bzw. der Engine ersetzen."""
    sites = []
    for path in _product_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "set_authorizer" in text:
            sites.extend(authorizer_sites(text, path.relative_to(REPO).as_posix()))
    assert set(sites) == AUTHORIZER_ALLOWED, sites


@pytest.mark.parametrize("source", [
    "def f(conn):\n    conn.set_authorizer(None)\n",
    "def f(conn):\n    getattr(conn, 'set_authorizer')(None)\n",
    "def f(engine):\n    engine.raw_connection().driver_connection.set_authorizer(lambda *a: 0)\n",
])
def test_authorizer_guard_negative_control(source):
    assert authorizer_sites(source, "x.py") == ["x.py::f"]


@pytest.mark.parametrize("source", [
    "import sqlite3\ndef f(p):\n    return sqlite3.connect(p)\n",
    "import sqlite3 as s3\ndef f(p):\n    return s3.connect(p)\n",
    "from sqlite3 import connect\ndef f(p):\n    return connect(p)\n",
    "from sqlite3 import connect as c\ndef f(p):\n    return c(p)\n",
    "import sqlcipher3\ndef f(p):\n    return sqlcipher3.connect(p)\n",
    "from sqlcipher3 import dbapi2\ndef f(p):\n    return dbapi2.connect(p)\n",
    "import sqlite3.dbapi2\ndef f(p):\n    return sqlite3.dbapi2.connect(p)\n",
])
def test_guard_detects_every_raw_form(source):
    assert raw_connect_sites(source, "x.py") == ["x.py::f"]


@pytest.mark.parametrize("source", [
    # H12 N-907-22 (Pruefer-Proben): Referenzen statt Aufrufe, creator=.
    "import functools, sqlite3\ndef f(p):\n    return functools.partial(sqlite3.connect, p)()\n",
    "import sqlite3\ndef f(p):\n    c = sqlite3.connect\n    return c(p)\n",
    "import sqlite3\ndef f(p):\n    return sqlite3.Connection(p)\n",
    "from sqlite3 import Connection\ndef f(p):\n    return Connection(p)\n",
    "from sqlalchemy import create_engine\ndef f(make):\n    return create_engine('sqlite://', creator=make)\n",
    "import sqlite3\ndef f(p):\n    return {'open': sqlite3.connect}['open'](p)\n",
])
def test_guard_detects_references_and_creator(source):
    assert raw_connect_sites(source, "x.py") == ["x.py::f"]


def test_guard_allows_connector_argument_of_the_central_function_only():
    allowed = ("import sqlcipher3\nfrom config import guarded_sqlite_connect\n"
               "def f(p):\n    return guarded_sqlite_connect(p, context='x', connector=sqlcipher3.connect)\n")
    assert raw_connect_sites(allowed, "x.py") == []
    other = ("import sqlcipher3\ndef f(p):\n    return open_somehow(p, connector=sqlcipher3.connect)\n")
    assert raw_connect_sites(other, "x.py") == ["x.py::f"]


def test_guard_ignores_engine_connect_and_central_function():
    source = ("import sqlite3\nfrom config import guarded_sqlite_connect\n"
              "def f(engine, p):\n    engine.connect()\n    return guarded_sqlite_connect(p, context='x')\n")
    assert raw_connect_sites(source, "x.py") == []


# --- Verhalten (Temp-HOME als Owner-Profil) ------------------------------------

@pytest.fixture()
def owner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ares").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home / "ares" / "ares.db"


@pytest.mark.parametrize("suffix", ["", ".", "::$DATA"])
def test_backup_raw_connection_refuses_owner_path(owner, suffix):
    from services.backup import _open_connection

    with pytest.raises(loc.OwnerDatabaseRefused):
        _open_connection(str(owner) + suffix, uri=False, db_key=None)
    posix = owner.as_posix()
    lead = "" if posix.startswith("/") else "/"
    with pytest.raises(loc.OwnerDatabaseRefused):
        _open_connection(f"file://{lead}{posix}?mode=rwc", uri=True, db_key=None)
    assert list(owner.parent.iterdir()) == []


def test_backup_raw_connection_still_opens_isolated_paths(tmp_path):
    from services.backup import _open_connection

    target = tmp_path / "safe" / "safe.db"
    target.parent.mkdir()
    conn = _open_connection(str(target), uri=False, db_key=None)
    conn.close()
    assert target.exists()


def test_central_function_refuses_before_creating(owner):
    with pytest.raises(loc.OwnerDatabaseRefused, match="probe"):
        config.guarded_sqlite_connect(str(owner), context="probe")
    assert not owner.exists()


def test_restore_drill_and_integrity_audit_use_the_central_function():
    drill = (BACKEND / "scripts" / "restore_drill.py").read_text(encoding="utf-8")
    audit = (REPO / "scripts" / "data_integrity_audit.py").read_text(encoding="utf-8")
    assert "guarded_sqlite_connect(str(db_path), context=\"restore_drill\")" in drill
    assert "guarded_sqlite_connect(str(db_path), context=\"data_integrity_audit\")" in audit


def test_guard_ignores_type_annotations():
    source = ("import sqlite3\ndef f(conn: sqlite3.Connection) -> sqlite3.Connection:\n"
              "    x: sqlite3.Connection = conn\n    return x\n")
    assert raw_connect_sites(source, "x.py") == []


# --- H12 N-907-21: Sperre nicht per Attribut aufhebbar, fremde factory abgeleitet ---

def test_authorizer_lock_cannot_be_lifted_by_attribute(tmp_path):
    import sqlite3

    conn = config.guarded_sqlite_connect(str(tmp_path / "x.db"), context="probe")
    conn._ares_authorizer_locked = False  # Pruefer-Probe N-907-21
    with pytest.raises(config.AuthorizerLocked):
        conn.set_authorizer(None)
    conn.close()
    assert isinstance(conn, sqlite3.Connection)


def test_explicit_factory_is_derived_and_stays_locked(tmp_path):
    import sqlite3

    class Plain(sqlite3.Connection):
        pass

    for factory in (sqlite3.Connection, Plain):
        conn = config.guarded_sqlite_connect(str(tmp_path / "f.db"), context="probe", factory=factory)
        assert isinstance(conn, factory)
        with pytest.raises(config.AuthorizerLocked):
            conn.set_authorizer(None)
        conn.close()
