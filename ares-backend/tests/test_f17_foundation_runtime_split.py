"""F17 (Codex-Entscheid Runde 3, 2026-11-07): Guard fuer die Trennung
Fachtest / Laufzeit-Sentinel des Foundation-Smoketests.

- Die Fachtests in test_stage8_foundation_smoketest.py laufen mit injizierter
  Laufzeit im normalen Shard (kein wallclock_budget-Marker), der Sentinel
  traegt den Marker und laeuft damit nur im seriellen Job.
- Kein Rerun verdeckt einen roten Erstlauf: weder ein flaky-Marker an diesen
  Tests noch --reruns/--last-failed in den CI-Workflows oder in addopts.
- Der serielle Job dokumentiert seine Runnerklasse (runs-on + Erfassung der
  tatsaechlichen Hardware).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SMOKETEST = BACKEND_ROOT / "tests" / "test_stage8_foundation_smoketest.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SENTINEL = "test_foundation_wallclock_budget_sentinel"


def _decorator_names(node: ast.FunctionDef) -> list[str]:
    return [ast.unparse(d) for d in node.decorator_list]


@pytest.fixture(scope="module")
def smoketest_tests() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(SMOKETEST.read_text(encoding="utf-8"))
    assert not any(
        isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "pytestmark" for t in n.targets)
        for n in tree.body
    ), "kein modulweiter Marker: Fachtests und Sentinel sind getrennt markiert"
    return {
        n.name: n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    }


def test_sentinel_is_serial_wallclock_and_fachtests_are_not(smoketest_tests):
    assert SENTINEL in smoketest_tests
    for name, node in smoketest_tests.items():
        marked = any("wallclock_budget" in d for d in _decorator_names(node))
        assert marked == (name == SENTINEL), name


def test_fachtest_uses_injected_runtime(smoketest_tests):
    source = ast.unparse(smoketest_tests["test_foundation_case_yields_green_or_yellow_verdict"])
    assert "INJECTED_ELAPSED_MS" in source
    sentinel = ast.unparse(smoketest_tests[SENTINEL])
    assert "elapsed_ms=None" in sentinel and "record_property" in sentinel


def test_no_flaky_marker_on_foundation_tests(smoketest_tests):
    for name, node in smoketest_tests.items():
        assert not any("flaky" in d for d in _decorator_names(node)), name


_RERUN = re.compile(r"--reruns\b|--last-failed\b|--lf\b|--failed-first\b|--ff\b|--sw\b|--stepwise\b")


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_ci_workflows_do_not_rerun_pytest(workflow):
    text = workflow.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "pytest" in line or line.strip().startswith("--"):
            assert not _RERUN.search(line), f"{workflow.name}: {line.strip()}"


def test_pytest_addopts_do_not_rerun():
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    addopts = re.search(r'^addopts\s*=\s*"([^"]*)"', pyproject, re.M)
    assert addopts is not None
    assert not _RERUN.search(addopts.group(1))


def test_wallclock_job_documents_runner_class():
    import yaml

    workflow = yaml.safe_load((WORKFLOWS / "test.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["backend-test-wallclock"]
    assert job["runs-on"] == "ubuntu-latest"
    step = next(s for s in job["steps"] if s.get("name") == "Record runner class")
    assert "nproc" in step["run"] and "GITHUB_STEP_SUMMARY" in step["run"]
