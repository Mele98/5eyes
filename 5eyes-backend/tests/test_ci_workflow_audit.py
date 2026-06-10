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
    pytest_job = jobs["pytest"]
    setup_step = next(
        s for s in pytest_job["steps"]
        if s.get("uses", "").startswith("actions/setup-python@")
    )
    with_config = setup_step.get("with", {})
    assert with_config.get("cache") == "pip", (
        "pip-Cache fehlt — CI lädt requirements jedes Mal neu."
    )
    assert with_config.get("cache-dependency-path") == "5eyes-backend/requirements.txt"


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
    """
    assert workflow_yaml["jobs"]["pytest"].get("timeout-minutes") == 30


def test_pytest_uses_python_3_12(workflow_yaml):
    matrix = workflow_yaml["jobs"]["pytest"]["strategy"]["matrix"]
    assert "3.12" in matrix["python-version"]


def test_pytest_runs_with_coverage(workflow_text):
    assert "--cov=services" in workflow_text
    assert "--cov=routers" in workflow_text
    assert "--cov=schemas" in workflow_text
    assert "--cov=models" in workflow_text
    assert "--cov-report=xml" in workflow_text


def test_pytest_maxfail_5(workflow_text):
    """maxfail=5 bricht nach 5 Failures ab — Resource-Schutz."""
    assert "--maxfail=5" in workflow_text


def test_pytest_uploads_coverage_artifact(workflow_yaml):
    pytest_job = workflow_yaml["jobs"]["pytest"]
    upload_steps = [
        s for s in pytest_job["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert len(upload_steps) >= 2  # coverage + pytest-log


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
