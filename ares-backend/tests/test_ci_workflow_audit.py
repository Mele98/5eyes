"""Sprint U-53 (Roadmap-Punkt 53, 2026-06-04): CI-Workflow Drift-Schutz.

Pre-U-53
--------
Roadmap-Notiz "Backend-Tests CI ohne pip-Cache, 12 min". Audit ergab:
pip-Cache war seit U-P54 (setup-python@v6 Bump, 2026-05-24) bereits
aktiv. U-53 ist also Coverage-Gap (analog U-58/U-62/U-43).

Post-U-53
---------
- pip-Cache + cache-dependency-path verifiziert (war schon da)
- concurrency-group hinzugefuegt (canceled stale Runs bei Push-Storm)
- Frontend vitest-Job hinzugefuegt (npm-Cache + build + vitest run)
- Audit-Tests dass Workflow konsistent bleibt

Diese Tests parsen .github/workflows/test.yml und assert YAML-Struktur.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"


@pytest.fixture(scope="module")
def workflow_yaml() -> dict:
    import yaml
    if not WORKFLOW_PATH.exists():
        pytest.skip(f"Workflow {WORKFLOW_PATH} nicht gefunden.")
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pip-Cache aktiviert (KERN-Audit U-53)
# ---------------------------------------------------------------------------

def test_setup_python_uses_pip_cache(workflow_yaml):
    """setup-python@v6 muss cache:pip + cache-dependency-path haben."""
    jobs = workflow_yaml["jobs"]
    # F0-3: die Suite laeuft in den Shard-/Plan-/Wallclock-Jobs; jeder Job,
    # der requirements installiert, braucht den pip-Cache.
    for job_id in ("backend-test-plan", "backend-test-shard", "backend-test-wallclock"):
        setup_step = next(
            s for s in jobs[job_id]["steps"]
            if s.get("uses", "").startswith("actions/setup-python@")
        )
        with_config = setup_step.get("with", {})
        assert with_config.get("cache") == "pip", (
            f"pip-Cache fehlt in {job_id} — CI lädt requirements jedes Mal neu."
        )
        assert with_config.get("cache-dependency-path") == "ares-backend/requirements.txt"


def test_setup_python_version_at_v6():
    """Drift-Schutz: setup-python sollte mindestens v6 sein (Node-20-Migration)."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/setup-python@v6" in text


def test_checkout_uses_v5():
    """Drift-Schutz: actions/checkout@v5 (Node-20)."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/checkout@v5" in text


# ---------------------------------------------------------------------------
# Concurrency-Group (U-53 NEU)
# ---------------------------------------------------------------------------

def test_concurrency_group_set(workflow_yaml):
    """U-53: concurrency canceled stale Runs bei Push-Storm."""
    assert "concurrency" in workflow_yaml
    concurrency = workflow_yaml["concurrency"]
    assert "group" in concurrency
    assert concurrency.get("cancel-in-progress") is True


def test_concurrency_group_includes_ref(workflow_yaml):
    """Group muss github.ref enthalten damit unterschiedliche Branches
    parallel laufen."""
    group = workflow_yaml["concurrency"]["group"]
    assert "github.ref" in group


# ---------------------------------------------------------------------------
# Backend pytest-Job
# ---------------------------------------------------------------------------

def test_pytest_job_runs_on_ubuntu(workflow_yaml):
    assert workflow_yaml["jobs"]["pytest"]["runs-on"] == "ubuntu-latest"


def test_pytest_job_has_timeout(workflow_yaml):
    """Timeout-Schutz: stuck-Tests blockieren nicht CI fuer immer.

    2026-06-08 von 15 auf 30 erhoeht: Backend-Suite ueber 3400 Tests
    gewachsen (Stage 9 + PDF-Audit + Bug-Sprint), 15min wurde knapp.

    2026-08-19 von 30 auf 90 erhoeht: PR #374 brachte die Suite auf 5991
    Tests; ausserdem laeuft der Job jetzt zweistufig (schneller blockierender
    Korrektheits-Lauf ohne Coverage + separater, nicht-blockierender
    Coverage-Lauf mit eigenem 60min-Timeout innerhalb desselben Jobs) --
    siehe .github/workflows/test.yml Job-Kommentar fuer die volle
    Root-Cause-Analyse (Coverage-Instrumentierung haengte reproduzierbar
    NUR auf dem Linux-CI-Runner, lokal dreimal bestaetigt unauffaellig).

    2026-10-05 von 90 auf 150 erhoeht: der JOB-Timeout umklammert BEIDE
    Schritte zusammen. Der blockierende Korrektheits-Lauf allein braucht
    inzwischen beobachtet ~28-31min (weiter gewachsene Suite) statt der
    urspruenglich budgetierten ~20-25min; zusammen mit Setup/Install und
    bis zu 60min fuer den nicht-blockierenden Coverage-Schritt ueberschritt
    die Summe wiederholt die 90min-Grenze. GitHub Actions cancelt dann den
    GESAMTEN Job -- auch den laengst erfolgreich abgeschlossenen
    Korrektheits-Lauf (beobachtet an PR #525/#527 mit identischem Muster:
    "0 failed" in den Logs, Job-Conclusion trotzdem "cancelled"). Siehe
    .github/workflows/test.yml Job-Kommentar.

    2026-10-17 von 150 auf 200 erhoeht: Korrektheits-Lauf inzwischen
    ~45-80min (Suite >8100 Tests, SAA-Resampling), plus bis zu 60min
    Coverage; Run 38964294815 wurde nach gruenem Gate im Coverage-Schritt
    vom Job-Limit abgebrochen.

    2026-10-24 (F0-3): die Suite laeuft in 8 parallelen Shards (je
    `-n auto --dist loadfile`); ein Shard braucht ~8-20 min, Limit 60.
    Der Job `pytest` ist nur noch das Aggregat (Vollstaendigkeits-Gate).
    """
    assert workflow_yaml["jobs"]["backend-test-shard"].get("timeout-minutes") == 60
    assert workflow_yaml["jobs"]["backend-test-wallclock"].get("timeout-minutes") == 30
    assert workflow_yaml["jobs"]["pytest"].get("timeout-minutes") == 15


def test_pytest_uses_python_3_12(workflow_yaml):
    matrix = workflow_yaml["jobs"]["pytest"]["strategy"]["matrix"]
    assert "3.12" in matrix["python-version"]


def test_pytest_runs_with_coverage(workflow_text):
    assert "--cov=services" in workflow_text
    assert "--cov=routers" in workflow_text
    assert "--cov=schemas" in workflow_text
    assert "--cov=models" in workflow_text
    # F0-3: Shards schreiben Rohdaten, der Combine-Job erzeugt das XML.
    assert "coverage combine" in workflow_text
    assert "coverage xml -o coverage.xml" in workflow_text


def test_pytest_maxfail_50(workflow_text):
    """maxfail=50: bricht bei Totalschaden (z.B. Importfehler) frueh ab --
    Resource-Schutz --, versteckt aber echte Wechselwirkungen nicht mehr.

    CI-COVERAGE-ON-PUSH (2026-10-18): Mit maxfail=5 brach der kombinierte
    Integrationslauf (Run 39082332916) nach 5 Fehlern ab; lokal zeigten sich
    danach 9 Fehler, und test_performance_budget lief auf PR #619 nie."""
    assert "--maxfail=50" in workflow_text
    assert "--maxfail=5 " not in workflow_text and not workflow_text.rstrip().endswith("--maxfail=5")


def test_pytest_uploads_coverage_artifact(workflow_yaml):
    """CI-COVERAGE-ON-PUSH (2026-10-18): Coverage ist nicht blockierend und
    laeuft nur nach Merge (push); das PR-Gate faehrt die Suite genau EINMAL.

    F0-3 (2026-10-24): Coverage-Shards (6x xdist) + Combine-Job, der genau
    einen Report hochlaedt. Das Gate (Shards) laeuft ohne --cov und laedt
    seine JUnit-Ergebnisse hoch."""
    jobs = workflow_yaml["jobs"]
    for job_id in ("coverage", "coverage-combine"):
        assert jobs[job_id]["if"].startswith("github.event_name == 'push'")
        assert jobs[job_id]["continue-on-error"] is True
    combine_uploads = [
        s for s in jobs["coverage-combine"]["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert len(combine_uploads) == 1
    shard_job = jobs["backend-test-shard"]
    shard_runs = [
        s.get("run", "") for s in shard_job["steps"]
        if "pytest tests/" in s.get("run", "") and "--collect-only" not in s.get("run", "")
    ]
    assert len(shard_runs) == 1 and "--cov" not in shard_runs[0]
    assert any(
        s.get("uses", "").startswith("actions/upload-artifact@")
        for s in shard_job["steps"]
    )  # JUnit + Selektion


# ---------------------------------------------------------------------------
# F0-3: paralleles Gate (Shards x xdist) ohne Testverlust
# ---------------------------------------------------------------------------

_PINNING = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_CORETYPE": "Haswell",
}


@pytest.mark.parametrize(
    "job_id", ["backend-test-plan", "backend-test-shard", "backend-test-wallclock", "coverage"]
)
def test_test_jobs_keep_determinism_pinning(workflow_yaml, job_id):
    """Thread-Pinning + fixer OpenBLAS-Kernel auf Job-Ebene, damit jeder
    xdist-Worker sie erbt (Golden-Snapshot-ULP-Flake 2026-09-09/16)."""
    env = workflow_yaml["jobs"][job_id].get("env", {})
    for key, value in _PINNING.items():
        assert env.get(key) == value, (job_id, key)


def test_shards_run_parallel_per_file(workflow_yaml):
    job = workflow_yaml["jobs"]["backend-test-shard"]
    assert job["strategy"]["matrix"]["group"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert job["strategy"]["fail-fast"] is False
    run = next(s["run"] for s in job["steps"] if "-n auto" in s.get("run", ""))
    assert "--dist loadfile" in run
    assert '-m "not wallclock_budget"' in run
    assert "--splits 8" in job["env"]["SPLIT_ARGS"]


def test_wallclock_budget_tests_run_serially(workflow_yaml):
    job = workflow_yaml["jobs"]["backend-test-wallclock"]
    run = next(s["run"] for s in job["steps"] if "-m wallclock_budget" in s.get("run", "") and "--collect-only" not in s["run"])
    assert "-p no:xdist" in run and "-n " not in run


def test_aggregate_check_keeps_its_name_and_gates_completeness(workflow_yaml):
    """Pflicht-Check-Name "Backend Tests (3.12)" bleibt stabil (Tooling)."""
    job = workflow_yaml["jobs"]["pytest"]
    assert job["name"] == "Backend Tests"
    assert job["strategy"]["matrix"]["python-version"] == ["3.12"]
    assert set(job["needs"]) == {"backend-test-plan", "backend-test-shard", "backend-test-wallclock"}
    assert job["if"] == "always()"
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "scripts/ci_test_shard_gate.py" in runs
    assert 'test "$SHARDS" = success' in runs


# ---------------------------------------------------------------------------
# Vitest-Job (U-53 NEU)
# ---------------------------------------------------------------------------

def test_vitest_job_exists(workflow_yaml):
    """U-53: Frontend Reporting Sub-App muss in CI laufen."""
    assert "vitest" in workflow_yaml["jobs"]


def test_vitest_uses_npm_cache(workflow_yaml):
    vitest_job = workflow_yaml["jobs"]["vitest"]
    setup_step = next(
        s for s in vitest_job["steps"]
        if s.get("uses", "").startswith("actions/setup-node@")
    )
    with_config = setup_step.get("with", {})
    assert with_config.get("cache") == "npm"
    assert "package-lock.json" in with_config.get("cache-dependency-path", "")


def test_vitest_runs_build_then_test(workflow_text):
    """Build laeuft VOR vitest (fuer U-56 Bundle-Size-Tests)."""
    build_idx = workflow_text.find("npm run build")
    vitest_idx = workflow_text.find("npx vitest run")
    assert build_idx != -1
    assert vitest_idx != -1
    assert build_idx < vitest_idx


def test_vitest_uses_npm_ci(workflow_text):
    """npm ci (reproducible installs) statt npm install."""
    assert "npm ci" in workflow_text


def test_vitest_job_timeout(workflow_yaml):
    """Vitest darf nicht ewig laufen."""
    assert workflow_yaml["jobs"]["vitest"].get("timeout-minutes") == 10


# ---------------------------------------------------------------------------
# Triggers (push + pull_request)
# ---------------------------------------------------------------------------

def test_workflow_triggers_on_develop_push(workflow_yaml):
    # PyYAML parsed 'on:' als True (key reserved) — wir nutzen rohen Zugriff
    on_config = workflow_yaml.get("on") or workflow_yaml.get(True)
    push_branches = on_config["push"]["branches"]
    assert "develop" in push_branches
    assert "main" in push_branches


def test_workflow_triggers_on_codex_branches(workflow_yaml):
    """Codex' rapid-fire Branches sollen CI triggern."""
    on_config = workflow_yaml.get("on") or workflow_yaml.get(True)
    push_branches = on_config["push"]["branches"]
    assert any("codex" in str(b) for b in push_branches)


def test_workflow_triggers_on_pull_request_to_main(workflow_yaml):
    on_config = workflow_yaml.get("on") or workflow_yaml.get(True)
    pr_branches = on_config["pull_request"]["branches"]
    assert "develop" in pr_branches
    assert "main" in pr_branches


# ---------------------------------------------------------------------------
# Postgres-RLS-Job -- alle Live-Postgres-Testdateien tatsaechlich verdrahtet
# ---------------------------------------------------------------------------

def _postgres_rls_run_command(workflow_yaml: dict) -> str:
    job = workflow_yaml["jobs"]["postgres-rls"]
    run_step = next(s for s in job["steps"] if "run" in s and "pytest" in s["run"])
    return run_step["run"]


def test_postgres_rls_job_exists(workflow_yaml):
    assert "postgres-rls" in workflow_yaml["jobs"]


def test_postgres_rls_adversarial_test_is_wired_in(workflow_yaml):
    assert "tests/test_postgres_rls_adversarial.py" in _postgres_rls_run_command(workflow_yaml)


def test_authten07_login_guard_test_is_wired_in(workflow_yaml):
    assert "tests/test_authten07_login_guard_postgres_ddl.py" in _postgres_rls_run_command(workflow_yaml)


def test_rls_dynamic_table_coverage_guard_is_wired_in(workflow_yaml):
    """RLS-COVERAGE-GUARD-NOT-WIRED-IN-CI-001 (Kontrollrunde 2026-09-27):
    dieser Guard wurde am 2026-08-17 explizit gebaut, um zu verhindern, dass
    eine neue tenant_id-Tabelle unbemerkt ohne RLS-Policy durchrutscht --
    lief seither aber in KEINEM CI-Job, nur lokal bei manuell gesetztem
    POSTGRES_TEST_DATABASE_URL. Der selbst dokumentierte Zweck war damit nie
    tatsaechlich durchgesetzt. Dieser Test schuetzt dagegen, dass die
    Verdrahtung je wieder stillschweigend verschwindet."""
    assert "tests/test_rls_dynamic_table_coverage_guard.py" in _postgres_rls_run_command(workflow_yaml)


def test_coverage_job_uses_sysmon_and_16_shards(workflow_yaml):
    """Coverage-Shards liefen mit dem klassischen Tracer in den 90-min-Timeout.
    sys.monitoring plus 16 Shards haelt den nicht blockierenden Job im Rahmen."""
    job = workflow_yaml["jobs"]["coverage"]
    assert job["env"].get("COVERAGE_CORE") == "sysmon"
    assert job["strategy"]["matrix"]["group"] == list(range(1, 17))
    run = next(s["run"] for s in job["steps"] if "--cov=" in s.get("run", ""))
    assert "--splits 16" in run
    assert job["continue-on-error"] is True
