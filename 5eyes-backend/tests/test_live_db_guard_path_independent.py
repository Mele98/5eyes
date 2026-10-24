"""Live-DB-Waechter sind pfadunabhaengig (Folge des Vorfalls 2026-10-15).

Vorher hielt jeder Waechter (tests/conftest.py, Analyse-Tools, Deploy-Skript)
ein eigenes Pfad-Literal des Produktivpfads und verglich per ``resolve() ==``.
Zwei Luecken:

1. Wird der Default-Datenpfad in ``config`` umbenannt, vergleichen die
   Waechter weiter gegen den alten Pfad und schuetzen still nicht mehr.
2. Ein Alias derselben Datei (Hardlink, Symlink/Junction, andere Schreibweise)
   faellt durch den reinen Namensvergleich.

Jetzt gibt es genau eine Quelle (``core.db_location.default_db_path``), aus
der auch ``config.Settings.db_path`` seinen Default bezieht, plus einen
``samefile``-Vergleich. Alle Proben laufen gegen eine *simulierte* Live-DB in
``tmp_path`` (umgebogenes Home bzw. umgebogene Quelle); die echte
Produktiv-DB wird weder geoeffnet noch per ``stat`` beruehrt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
TESTS_DIR = BACKEND_ROOT / "tests"
DB_LOCATION = BACKEND_ROOT / "core" / "db_location.py"


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

def _fake_home_env(home: Path, **extra: str) -> dict[str, str]:
    """Subprozess-Umgebung mit umgebogenem Home (=> umgebogener Default-Pfad)."""
    # Ohne xdist-Worker-Kennung: der Subprozess ist eine eigene, serielle
    # Test-Session (sonst greift dort der Worker-Zweig der conftest).
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"DB_PATH", "DATABASE_URL", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"}
    }
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def _fake_live_db(home: Path) -> Path:
    """Simulierte Live-DB unter dem umgebogenen Home -- ueber die echte Quelle
    abgeleitet (kein Literal), damit der Test eine Umbenennung mitmacht."""
    probe = subprocess.run(
        [sys.executable, str(DB_LOCATION), "live-path"],
        env=_fake_home_env(home), capture_output=True, text=True, timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    live = Path(probe.stdout.strip())
    assert home in live.parents, (live, home)
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(b"")
    return live


_CONFTEST_PROBE = textwrap.dedent(
    """
    import json, os, sys
    sys.path[:0] = [{tests!r}, {backend!r}]
    import conftest
    from config import settings
    result = {{"db_path": settings.db_path, "exit": None}}
    try:
        conftest.pytest_sessionstart(None)
    except BaseException as exc:  # pytest.exit -> Exit(returncode=3)
        result["exit"] = getattr(exc, "returncode", repr(exc))
    print("PROBE=" + json.dumps(result))
    """
)


def _run_conftest_probe(home: Path, tmp_path: Path, **env_extra: str) -> dict:
    """Importiert tests/conftest.py frisch in einem Subprozess (wie eine neue
    pytest-Session) und meldet den resultierenden DB-Pfad bzw. Abbruch."""
    code = _CONFTEST_PROBE.format(tests=str(TESTS_DIR), backend=str(BACKEND_ROOT))
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(tmp_path),
        env=_fake_home_env(home, **env_extra), capture_output=True, text=True, timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE=")]
    assert proc.returncode == 0 and lines, (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(lines[-1][len("PROBE="):])


def _same_file(a: str | Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


# --------------------------------------------------------------------------
# 1. Eine Quelle: Umbenennung des Default-Pfads zieht den Waechter mit
# --------------------------------------------------------------------------

def test_guard_blocks_exactly_the_renamed_default_path(tmp_path, monkeypatch):
    """Simulierte Umbenennung: die Default-Quelle zeigt auf einen Temp-Pfad.
    ``config`` uebernimmt ihn als Default, und der Session-Waechter blockiert
    genau diesen Pfad. Mit dem alten Literal-Waechter (eigene Pfadkopie) waere
    der neue Pfad nicht blockiert."""
    import conftest
    import core.db_location as db_location
    from config import Settings

    renamed = tmp_path / "renamed-data-dir" / "renamed.db"
    monkeypatch.setattr(db_location, "default_db_path", lambda: renamed)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)
    assert Path(settings.db_path) == renamed, "config bezieht den Default nicht aus der Quelle"
    assert db_location.is_live_db_path(renamed)
    assert conftest.live_db_violation(settings.db_path) == "DB_PATH"
    assert conftest.live_db_violation(None, f"sqlite:///{renamed}") == "DATABASE_URL"
    with pytest.raises(SystemExit, match="produktive Datenbank"):
        db_location.refuse_live_db(str(renamed), context="probe")
    # Der Pfad VOR der Umbenennung ist nicht mehr der Produktivpfad.
    assert not db_location.is_live_db_path(tmp_path / "harmless.db")


def test_fresh_session_on_the_live_default_is_redirected_and_url_aborts(tmp_path):
    home = tmp_path / "home"
    live = _fake_live_db(home)

    redirected = _run_conftest_probe(home, tmp_path, DB_PATH=str(live))
    assert not _same_file(redirected["db_path"], live)
    assert redirected["exit"] is None

    aborted = _run_conftest_probe(
        home, tmp_path, DB_PATH=str(tmp_path / "harmless.db"), DATABASE_URL=f"sqlite:///{live}",
    )
    assert aborted["exit"] == 3


# --------------------------------------------------------------------------
# 2. Aliase derselben Datei werden ebenfalls blockiert
# --------------------------------------------------------------------------

def _alias_variants(live: Path, tmp_path: Path) -> list[tuple[str, Path]]:
    variants: list[tuple[str, Path]] = [
        ("dotdot", live.parent / ".." / live.parent.name / live.name),
    ]
    hard = tmp_path / "hardlink.db"
    try:
        os.link(live, hard)
        variants.append(("hardlink", hard))
    except OSError:
        pass
    sym = tmp_path / "symlink.db"
    try:
        sym.symlink_to(live)
        variants.append(("symlink", sym))
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        variants.append(("case", Path(str(live).upper())))
    return variants


def test_aliases_of_the_live_db_are_detected(tmp_path, monkeypatch):
    import core.db_location as db_location

    live = tmp_path / "data" / "live.db"
    live.parent.mkdir()
    live.write_bytes(b"")
    monkeypatch.setattr(db_location, "default_db_path", lambda: live)

    variants = _alias_variants(live, tmp_path)
    assert any(name == "hardlink" for name, _ in variants), "Hardlink nicht anlegbar"
    for name, alias in variants:
        assert db_location.is_live_db_path(alias), name
    assert not db_location.is_live_db_path(tmp_path / "other.db")
    assert not db_location.is_live_db_path("")
    assert not db_location.is_live_db_path(None)


def test_fresh_session_on_an_alias_of_the_live_db_is_redirected(tmp_path):
    """Der alte Waechter verglich nur ``resolve()``-Namen: ein Hardlink auf
    die Live-DB lief als DB_PATH ungehindert durch."""
    home = tmp_path / "home"
    live = _fake_live_db(home)
    hard = tmp_path / "alias.db"
    try:
        os.link(live, hard)
    except OSError:
        pytest.skip("Dateisystem ohne Hardlinks")

    result = _run_conftest_probe(home, tmp_path, DB_PATH=str(hard))
    assert not _same_file(result["db_path"], live), result
    assert result["exit"] is None


# --------------------------------------------------------------------------
# 3. Harmlose Temp-DB: Session laeuft normal auf genau dieser Datei
# --------------------------------------------------------------------------

def test_fresh_session_on_a_harmless_temp_db_runs_normally(tmp_path):
    home = tmp_path / "home"
    _fake_live_db(home)
    harmless = tmp_path / "harmless.db"

    result = _run_conftest_probe(home, tmp_path, DB_PATH=str(harmless))
    assert Path(result["db_path"]) == harmless
    assert result["exit"] is None


# --------------------------------------------------------------------------
# 4. Kommandozeile (fuer die PowerShell-Skripte) und Tools
# --------------------------------------------------------------------------

def test_cli_check_exit_codes(tmp_path):
    home = tmp_path / "home"
    live = _fake_live_db(home)
    hard = tmp_path / "alias.db"
    os.link(live, hard)

    def check(path: Path) -> int:
        return subprocess.run(
            [sys.executable, str(DB_LOCATION), "check", str(path)],
            env=_fake_home_env(home), capture_output=True, text=True, timeout=60,
        ).returncode

    assert check(live) == 3
    assert check(hard) == 3
    assert check(tmp_path / "harmless.db") == 0
    bad = subprocess.run(
        [sys.executable, str(DB_LOCATION)], env=_fake_home_env(home),
        capture_output=True, text=True, timeout=60,
    )
    assert bad.returncode not in (0, 3)


@pytest.mark.parametrize(
    "tool",
    [
        REPO_ROOT / "tools" / "analytic_gradients" / "analytic_gradient_experiment.py",
        REPO_ROOT / "tools" / "house_prior_calibration" / "calibration_common.py",
    ],
    ids=lambda p: p.stem,
)
def test_tools_refuse_an_alias_of_the_live_db(tool, tmp_path):
    home = tmp_path / "home"
    live = _fake_live_db(home)
    hard = tmp_path / "alias.db"
    os.link(live, hard)

    proc = subprocess.run(
        [sys.executable, str(tool)], cwd=str(tmp_path),
        env=_fake_home_env(home, DB_PATH=str(hard)), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0
    assert "produktive Datenbank" in proc.stderr, proc.stderr[-2000:]


# --------------------------------------------------------------------------
# 5. Strukturell: kein Waechter haelt mehr eine eigene Pfadkopie
# --------------------------------------------------------------------------

GUARD_FILES = [
    BACKEND_ROOT / "tests" / "conftest.py",
    BACKEND_ROOT / "tests" / "test_risk_answer_migration_idempotent.py",
    BACKEND_ROOT / "seed_external_demo.py",
    BACKEND_ROOT / "make_demo_accounts_easy.py",
    REPO_ROOT / "tools" / "analytic_gradients" / "analytic_gradient_experiment.py",
    REPO_ROOT / "tools" / "house_prior_calibration" / "calibration_common.py",
    REPO_ROOT / "docs" / "deploy" / "promote_operator.py",
    REPO_ROOT / "scripts" / "data_integrity_audit.py",
    REPO_ROOT / "docs" / "deploy" / "start-external.ps1",
    REPO_ROOT / "docs" / "deploy" / "start-external-staging.ps1",
]


@pytest.mark.parametrize("path", GUARD_FILES, ids=lambda p: p.name)
def test_guard_files_derive_the_live_path_from_the_single_source(path):
    text = path.read_text(encoding="utf-8")
    assert "db_location" in text, f"{path.name} nutzt core/db_location nicht"
    assert "_LIVE_DB" not in text, f"{path.name} haelt noch eine eigene Live-Pfad-Kopie"


def test_config_default_comes_from_the_single_source():
    text = (BACKEND_ROOT / "config.py").read_text(encoding="utf-8")
    assert "default_factory=lambda: str(_db_location.default_db_path())" in text


def test_tunnel_scripts_use_the_python_check_and_fail_closed():
    ext = (REPO_ROOT / "docs" / "deploy" / "start-external.ps1").read_text(encoding="utf-8")
    assert "$realDbPath = Join-Path" not in ext
    assert "live-path" in ext
    assert "check $env:DB_PATH" in ext
    assert "$dbCheck -eq 3" in ext
    assert "$dbCheck -ne 0 -and $dbCheck -ne 3" in ext  # unbekannter Exit -> Abbruch

    stg = (REPO_ROOT / "docs" / "deploy" / "start-external-staging.ps1").read_text(encoding="utf-8")
    assert "check $stagingDb" in stg
    assert stg.index("check $stagingDb") < stg.index("$env:DB_PATH               = $stagingDb")
