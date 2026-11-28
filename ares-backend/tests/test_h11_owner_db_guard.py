"""H11 Nachtrag 1 (Vorfall 2026-11-14): ``~/ares/ares.db`` wurde leer neu angelegt.

Ursache (Code-/Git-Analyse, siehe H-160 Nachtrag 1): Ein Prozess startete die
App bzw. ihren Lifespan (``init_db``) ohne ``DB_PATH`` -- ``config`` faellt dann
auf ``core.db_location.default_db_path()`` zurueck. Die Test-Isolation lebt nur
in ``ares-backend/tests/conftest.py``; wer Produkt-Testmodule von ausserhalb
importiert (z. B. Reproducer in einem anderen Verzeichnis), umgeht sie.

Schutz (fail-closed):
1. ``config`` (Regel aus ``core.db_location.owner_db_refusal``) prueft VOR
   jedem SQLite-Connect, im App-Start und im Schema-Bootstrap: Owner-Pfade (``~/ares/ares.db``,
   ``<Alt-Profilordner>/<Alt-Profilordner>.db``, nur per Digest erkannt) unter pytest/CI/Testmodus nie, sonst nur mit
   ``ARES_OWNER_DB_OPT_IN=1`` (Desktop-Shell, Umstieg). ``alembic/env.py``
   prueft die URL zusaetzlich.
2. ``conftest``: Session-Waechter auf ``~/ares`` und den Alt-Profilordner.
3. AST-Waechter: jede Test-Fixture, die einen Backend-Prozess startet, setzt
   HOME/APPDATA/LOCALAPPDATA/DB_PATH auf eigene Werte.
"""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.db_location as loc

# Kunstname fuer den Alt-Profilordner: Tests setzen nur seinen Digest ein; die
# echte Altmarke steht nirgends im Repo (Zero-Trace).
ALT = "altprodukt"


@pytest.fixture()
def alt_digest(monkeypatch):
    monkeypatch.setattr(loc, "LEGACY_OWNER_DIR_DIGESTS",
                        frozenset({hashlib.sha256(ALT.encode("utf-8")).hexdigest()}))

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
REQUIRED_ENV = {"HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "DB_PATH"}  # N-907-08: USERPROFILE


# --- 1. Owner-DB-Waechter -------------------------------------------------------

def test_owner_paths_are_ares_and_legacy_live_db(alt_digest):
    home = Path.home()
    assert loc.owner_db_paths()[0] == home / "ares" / "ares.db"
    legacy = home / ALT / f"{ALT}.db"
    assert loc.is_owner_db_path(legacy)  # Textregel: auch ohne vorhandenen Ordner
    assert loc.is_owner_db_path(str(legacy) + "-wal")
    assert not loc.is_owner_db_path(home / ALT / "anders.db")
    assert not loc.is_owner_db_path(home / "sub" / ALT / f"{ALT}.db")
    assert not loc.is_owner_db_path(home / "elsewhere.db")


@pytest.mark.parametrize("env", [{}, {"CI": "true"}, {"ARES_TEST_MODE": "1"}, {"ARES_OWNER_DB_OPT_IN": "1"}])
def test_owner_db_is_always_refused_under_pytest(env):
    """In diesem Prozess laeuft pytest: auch mit Opt-in verweigert."""
    reason = loc.owner_db_refusal(loc.default_db_path(), environ=env)
    assert reason and reason.startswith("pytest:")


def test_owner_db_refused_without_opt_in_and_allowed_with_it(monkeypatch):
    monkeypatch.setattr(loc, "test_or_ci_mode", lambda environ: None)
    assert "ARES_OWNER_DB_OPT_IN=1" in loc.owner_db_refusal(loc.default_db_path(), environ={})
    assert loc.owner_db_refusal(loc.default_db_path(), environ={"ARES_OWNER_DB_OPT_IN": "1"}) is None
    assert loc.owner_db_refusal(Path.home() / "other" / "x.db", environ={}) is None


def test_ci_and_test_mode_are_detected_without_pytest():
    probe = ("import sys; sys.modules.pop('pytest', None); import core.db_location as l; "
             "print([l.test_or_ci_mode({}), l.test_or_ci_mode({'CI': 'true'}), "
             "l.test_or_ci_mode({'GITHUB_ACTIONS': 'true'}), l.test_or_ci_mode({'ARES_TEST_MODE': '1'})])")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}
    out = subprocess.run([sys.executable, "-c", probe], cwd=str(BACKEND), env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[None, 'CI', 'CI', 'Testmodus']"


def test_engine_connect_to_owner_path_is_refused_before_the_file_exists(tmp_path, monkeypatch):
    """Die Datei wird nie angelegt: der Waechter greift vor dem DBAPI-Connect."""
    import config  # noqa: F401  (installiert den Waechter)
    from sqlalchemy import create_engine, text

    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    target = fake_home / "ares" / "ares.db"
    target.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{target}")
    with pytest.raises(loc.OwnerDatabaseRefused, match="Owner-Datenbank"):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    assert not target.exists()
    harmless = create_engine(f"sqlite:///{tmp_path / 'ok.db'}")
    with harmless.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_app_start_without_db_path_is_refused_and_creates_nothing(tmp_path):
    """Nachstellung des Vorfalls: App-Lifespan ohne DB_PATH (ausserhalb der
    Test-conftest, wie ein Reproducer aus einem fremden Verzeichnis)."""
    home = tmp_path / "home"
    home.mkdir()
    probe = ("import sys; sys.path.insert(0, %r)\n"
             "from fastapi.testclient import TestClient\nimport main\n"
             "try:\n    TestClient(main.app).__enter__()\nexcept BaseException as exc:\n"
             "    print('REFUSED', type(exc).__name__, exc)\n" % str(BACKEND))
    env = {k: v for k, v in os.environ.items()
           if k not in {"DB_PATH", "DATABASE_URL", "BACKUP_DIR", "LOG_DIR", "ARES_OWNER_DB_OPT_IN"}
           and not k.startswith("PYTEST")}
    # Nur das Home wird umgebogen (Default-DB = Home/ares/ares.db); APPDATA bleibt fuer site-packages.
    env.update({"HOME": str(home), "USERPROFILE": str(home), "CI": "true", "PYTHONDONTWRITEBYTECODE": "1"})
    out = subprocess.run([sys.executable, "-c", probe], cwd=str(tmp_path), env=env,
                         capture_output=True, text=True, timeout=300)
    assert "REFUSED" in out.stdout and "Owner-Datenbank" in out.stdout, (out.stdout[-2000:], out.stderr[-3000:])
    assert not (home / "ares").exists()  # weder DB noch Logs/Backups im Owner-Profil


def test_guards_sit_before_logging_and_raw_schema_bootstrap():
    import inspect

    import database
    import main

    life = inspect.getsource(main.lifespan)
    assert life.index("refuse_owner_db_settings(settings") < life.index("configure_logging()") < life.index("init_db()")
    boot = inspect.getsource(database.bootstrap_sqlite_schema)
    assert boot.index("refuse_owner_db_file(db_file") < boot.index("guarded_sqlite_connect(")
    assert "sqlite3.connect(" not in boot.replace("connector=sqlcipher3.connect", "")  # N2: nur zentral


def test_desktop_shell_and_alembic_wire_the_guard():
    main_js = (REPO / "ares-desktop" / "main.js").read_text(encoding="utf-8")
    env_fn = main_js[main_js.index("function buildBackendChildEnv("):]
    # N-907-03: nur im gepackten Produktivstart (Verhalten: ares-desktop/tests/main.smoke.test.js).
    assert "if (ownerDbOptInAllowed()) env.ARES_OWNER_DB_OPT_IN = '1';" in env_fn[:env_fn.index("\n}\n")]
    assert "return Boolean(isPackaged) && env.NODE_ENV !== 'test' && env.ARES_TEST !== '1';" in main_js
    alembic_env = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    assert 'refuse_owner_db_file(sqlite_url_file(config.get_main_option("sqlalchemy.url")), context="alembic")' in alembic_env
    assert "\n_install_owner_db_guard()\n" in (BACKEND / "config.py").read_text(encoding="utf-8")


# --- 2. Session-Waechter Owner-Profil ------------------------------------------

def test_profile_guard_reports_new_changed_and_deleted_files(tmp_path, alt_digest):
    import _owner_profile_guard as guard

    roots = guard.owner_profile_roots(tmp_path)
    assert roots == (tmp_path / "ares",)
    (roots[0]).mkdir()
    (roots[0] / "keep.db").write_bytes(b"a")
    (roots[0] / "gone.db").write_bytes(b"b")
    before = guard.snapshot(roots)
    assert guard.changes(before, guard.snapshot(roots)) == []
    (roots[0] / "keep.db").write_bytes(b"aa")
    (roots[0] / "gone.db").unlink()
    (tmp_path / ALT).mkdir()
    (tmp_path / ALT / f"{ALT}.db").write_bytes(b"x")
    roots = (*roots, *guard.owner_profile_roots(tmp_path))
    assert guard.changes(before, guard.snapshot(roots)) == [
        f"neu: {tmp_path / ALT / (ALT + '.db')}", f"veraendert: {roots[0] / 'keep.db'}", f"geloescht: {roots[0] / 'gone.db'}"]


def test_conftest_compares_the_profile_at_session_end():
    src = (BACKEND / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "_OWNER_PROFILE_BEFORE = None if _XDIST_WORKER else _owner_profile_guard.snapshot(" in src
    assert "session.exitstatus = _pytest.ExitCode.TESTS_FAILED" in src.split("OWNER-PROFIL VERAENDERT")[1][:200]


# --- 3. AST-Waechter: Backend-Fixtures isolieren --------------------------------

def _starts_backend(call: ast.Call) -> bool:
    texts = [n.value for n in ast.walk(call) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return any(t in ("uvicorn", "main:app") for t in texts)


def _env_keys(fn: ast.AST, name: str) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            keys |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update" \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == name:
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    keys |= {k.value for k in arg.keys if isinstance(k, ast.Constant)}
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            loop_keys = {e.value for e in node.iter.elts if isinstance(e, ast.Constant)}
            if any(isinstance(s, ast.Subscript) and isinstance(s.value, ast.Name) and s.value.id == name
                   for st in node.body for s in ast.walk(st)):
                keys |= loop_keys
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name \
                        and isinstance(t.slice, ast.Constant):
                    keys.add(t.slice.value)
    return keys


def backend_fixture_violations(source: str, rel: str) -> list[str]:
    tree = ast.parse(source)
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and _starts_backend(call)):
                continue
            env_kw = next((k.value for k in call.keywords if k.arg == "env"), None)
            if not isinstance(env_kw, ast.Name):
                out.append(f"{rel}::{fn.name}: Backend-Start ohne env-Variable")
                continue
            missing = REQUIRED_ENV - _env_keys(fn, env_kw.id)
            if missing:
                out.append(f"{rel}::{fn.name}: fehlt {sorted(missing)}")
    return out


def _backend_fixture_files() -> list[Path]:
    return sorted(p for p in (BACKEND / "tests").rglob("*.py")  # N-907-08: rekursiv
                  if ("uvicorn" in (t := p.read_text(encoding="utf-8")) or "main:app" in t) and p.name != Path(__file__).name)


def test_every_backend_fixture_isolates_home_appdata_and_db_path():
    files = _backend_fixture_files()
    assert len(files) >= 5, files  # Positivkontrolle: e2a, e2b, h10, h11, c890
    violations = [v for p in files for v in backend_fixture_violations(p.read_text(encoding="utf-8"), p.name)]
    assert violations == []


def test_fixture_guard_negative_control():
    bad = ("import subprocess, sys, os\n"
           "def server():\n    env = {**os.environ, 'HOME': 'x', 'USERPROFILE': 'x', 'DB_PATH': 'y'}\n"
           "    subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app'], env=env)\n"
           "def bare():\n    subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app'])\n")
    assert backend_fixture_violations(bad, "x.py") == [
        "x.py::server: fehlt ['APPDATA', 'LOCALAPPDATA']", "x.py::bare: Backend-Start ohne env-Variable"]


# --- 4. Aufrufe wie der Codex-Lauf (Repo-Root) und aus fremdem Verzeichnis --------

def _clean_env(home: Path) -> dict[str, str]:
    """Temp-HOME (nie das echte Profil), ohne DB_PATH/Testvariablen des Elternlaufs."""
    env = {k: v for k, v in os.environ.items()
           if k not in {"DB_PATH", "DATABASE_URL", "BACKUP_DIR", "LOG_DIR", "TENANT_MASTER_KEK",
                        "TENANT_MASTER_KEK_FILE", "ARES_OWNER_DB_OPT_IN"} and not k.startswith("PYTEST")}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _owner_files(home: Path) -> list[str]:
    return sorted(str(p) for root in (home / "ares", *loc.legacy_owner_dirs(home)) if root.exists() for p in root.rglob("*"))


def test_pytest_from_repo_root_with_app_lifespan_leaves_owner_profile_empty(tmp_path):
    """Wie der Codex-Lauf (Start im Repo-Root, Pfade ares-backend/tests/...):
    die conftest-Isolation greift (rootdir ueber ares-backend/pyproject.toml),
    ein TestClient-Lifespan schreibt nichts unter ~/ares oder im Alt-Profilordner."""
    home = tmp_path / "home"
    home.mkdir()
    node = "ares-backend/tests/test_h11_reference_data_get_read_only.py::test_bootstrap_admin_seeds_ch_reference_data"
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
         "--basetemp", str(tmp_path / "bt"), node],
        cwd=str(REPO), env=_clean_env(home), capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-2000:]
    assert _owner_files(home) == []


def test_foreign_directory_test_without_product_conftest_is_refused(tmp_path):
    """Die eigentliche Luecke: ein Test in einem fremden Verzeichnis (ohne die
    Produkt-conftest) startet TestClient(app) mit gesetzter KEK (wie ein
    Pruef-Harness). An der Basis legt der Lifespan HOME/ares/ares.db an (leer,
    1 Tenant -- das Vorfallbild); jetzt verweigert, Owner-Profil bleibt leer."""
    from cryptography.fernet import Fernet

    home = tmp_path / "home"
    home.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "test_foreign_probe.py").write_text(
        "import sys\nsys.path.insert(0, %r)\n"
        "def test_app_lifespan():\n"
        "    from fastapi.testclient import TestClient\n    import main\n"
        "    with TestClient(main.app):\n        pass\n" % str(BACKEND), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
         "--rootdir", str(foreign), "--basetemp", str(tmp_path / "bt"), str(foreign / "test_foreign_probe.py")],
        cwd=str(foreign), env={**_clean_env(home), "TENANT_MASTER_KEK": Fernet.generate_key().decode()},
        capture_output=True, text=True, timeout=600)
    assert out.returncode != 0 and "OwnerDatabaseRefused" in out.stdout, out.stdout[-3000:]
    assert _owner_files(home) == []


def test_legacy_owner_digest_matches_brand_digest_list():
    from brand_digest_support import LEGACY_BRAND_STEM_DIGESTS

    assert loc.LEGACY_OWNER_DIR_DIGESTS == {
        digest for brand, length, digest in LEGACY_BRAND_STEM_DIGESTS if brand == "LB-B" and length == 5}


def test_existing_legacy_dir_is_discovered_and_guarded(alt_digest, tmp_path, monkeypatch):
    (tmp_path / ALT).mkdir()
    (tmp_path / "andere").mkdir()
    assert loc.legacy_owner_dirs(tmp_path) == (tmp_path / ALT,)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert loc.owner_db_paths() == (tmp_path / "ares" / "ares.db", tmp_path / ALT / f"{ALT}.db")
    db = tmp_path / ALT / f"{ALT}.db"
    db.write_bytes(b"x")
    alias = tmp_path / "andere" / "harmlos.db"
    try:
        os.link(db, alias)
    except OSError as exc:
        pytest.skip(f"keine Hardlinks: {exc}")
    assert loc.is_owner_db_path(alias)  # Identitaet (Hardlink) der vorhandenen Alt-DB


def test_unlistable_home_makes_hardlink_identity_fail_closed(tmp_path, monkeypatch):
    """Home nicht auflistbar (Traverse ja, Auflisten nein): eine Alt-Live-DB waere
    unsichtbar -> ein Kandidat mit mehreren Namen gilt als nicht verifizierbar."""
    real = tmp_path / "x.db"
    real.write_bytes(b"x")
    alias = tmp_path / "alias.db"
    try:
        os.link(real, alias)
    except OSError as exc:
        pytest.skip(f"keine Hardlinks: {exc}")
    monkeypatch.setattr(loc, "_legacy_owner_scan", lambda home=None: ((), True))
    state, _ = loc.fs_identity_check(alias)
    assert state == "error"
    single = tmp_path / "einzeln.db"
    single.write_bytes(b"y")
    assert loc.fs_identity_check(single)[0] is None  # ein Name: kein Hardlink moeglich
