"""W1-803-01: In-Repo-Ratsche fuer die Repo-Struktur.

scripts/check_repo_top_level_layout.py ist ein dependency-freier Gate
(positive Allowlist der Top-Level-Knoten aus ``git ls-files``). Er laeuft in
CI zweimal frueh und unabhaengig von der Python-Testsammlung: als eigener Job
und als erster Schritt von ``backend-test-plan`` (Teil des Aggregat-Checks
"Backend Tests (3.12)"). Diese Tests pinnen zusaetzlich den Vertrag selbst und
belegen mit Positivkontrollen, dass der Gate bei einem zusaetzlichen Knoten
tatsaechlich rot wird.

Das Script wird per importlib geladen (analog test_engine_line_budget_gate.py).
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
GATE_SCRIPT = REPO_ROOT / "scripts" / "check_repo_top_level_layout.py"
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

EXPECTED_TOP_LEVEL = {
    ".gitattributes",
    ".github",
    ".gitignore",
    "README.md",
    "api",
    "ares-backend",
    "ares-desktop",
    "docs",
    "scripts",
    "tools",
}


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_repo_top_level_layout", GATE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


@pytest.fixture(scope="module")
def files(gate):
    if shutil.which("git") is None:
        pytest.fail("git nicht verfuegbar -- die Repo-Struktur-Ratsche braucht git ls-files.")
    tracked = gate.tracked_files(REPO_ROOT)
    assert tracked, "git ls-files lieferte keine Dateien"
    return tracked


def test_gate_script_points_at_this_repo(gate):
    assert GATE_SCRIPT.is_file()
    assert gate.REPO_ROOT == REPO_ROOT
    assert (REPO_ROOT / "ares-backend" / "tests").resolve() == Path(__file__).resolve().parent


def test_allowlist_is_exactly_the_reviewed_set(gate):
    """Jede Erweiterung der Allowlist muss auch hier bewusst nachgezogen werden."""
    assert set(gate.ALLOWED_TOP_LEVEL) == EXPECTED_TOP_LEVEL


def test_repo_top_level_nodes_are_allowlisted(gate, files):
    problems = gate.check_top_level(files)
    assert not problems, "\n".join(problems)


def test_repo_first_level_subdirs_are_allowlisted(gate, files):
    problems = gate.check_subdirs(files)
    assert not problems, "\n".join(problems)


def test_required_paths_are_tracked(gate, files):
    problems = gate.check_required(files)
    assert not problems, "\n".join(problems)


def test_workflow_paths_exist(gate, files):
    problems = gate.check_workflows(files, REPO_ROOT)
    assert not problems, "\n".join(problems)


def test_backend_suite_is_collected_from_this_directory(gate):
    """Der Collect-Schritt muss im Verzeichnis dieser Testdatei laufen."""
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    assert "ares-backend" in gate.workflow_paths(text)
    assert "python -m pytest tests/ --collect-only" in text


def test_ci_runs_gate_early_and_independent_of_python_collection():
    import yaml

    jobs = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    cmd = "python3 scripts/check_repo_top_level_layout.py"

    layout_steps = jobs["repo-layout-gate"]["steps"]
    assert any(s.get("run") == cmd for s in layout_steps)
    assert not any("pip install" in str(s.get("run", "")) for s in layout_steps)

    plan_steps = jobs["backend-test-plan"]["steps"]
    runs = [s.get("run", "") for s in plan_steps]
    assert cmd in runs, "Gate fehlt im backend-test-plan-Job"
    gate_idx = runs.index(cmd)
    assert "working-directory" not in plan_steps[gate_idx]
    install_idx = next(i for i, s in enumerate(plan_steps) if "pip install" in str(s.get("run", "")))
    assert gate_idx < install_idx, "Gate muss vor Dependency-Installation und Collection laufen"


# --- Positivkontrollen: der Gate muss bei Abweichungen wirklich rot werden ---


def test_extra_top_level_node_is_reported_by_name(gate, files):
    mutated = list(files) + ["zz-unexpected-node/tests/test_x.py"]
    problems = gate.check_top_level(mutated)
    assert len(problems) == 1
    assert "'zz-unexpected-node'" in problems[0]


def test_extra_top_level_file_is_reported(gate, files):
    problems = gate.check_top_level(list(files) + ["stray.txt"])
    assert problems and "'stray.txt'" in problems[0]


def test_extra_backend_subdir_is_reported(gate, files):
    problems = gate.check_subdirs(list(files) + ["ares-backend/zz_new_pkg/module.py"])
    assert problems == [
        "Unerwartetes Unterverzeichnis: 'ares-backend/zz_new_pkg' (nicht in ALLOWED_SUBDIRS['ares-backend'])"
    ]


def test_first_level_backend_file_is_not_a_subdir_violation(gate, files):
    assert gate.check_subdirs(list(files) + ["ares-backend/new_entry.py"]) == []


def test_missing_required_path_is_reported(gate, files):
    pruned = [f for f in files if f != "ares-backend/tests/conftest.py"]
    assert gate.check_required(pruned) == ["Pflichtpfad fehlt im Index: 'ares-backend/tests/conftest.py'"]


def test_stale_workflow_working_directory_is_reported(gate, tmp_path):
    wf = tmp_path / ".github" / "workflows" / "x.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(
        "jobs:\n  a:\n    steps:\n      - run: pytest\n        working-directory: zz-stale-dir\n"
        "    strategy:\n      matrix:\n        dir:\n          - zz-other\n          - ok-dir\n",
        encoding="utf-8",
    )
    tracked = [".github/workflows/x.yml", "ok-dir/a.txt"]
    problems = gate.check_workflows(tracked, tmp_path)
    assert problems == [
        "Workflow-Pfad existiert nicht im Index: 'zz-stale-dir' in .github/workflows/x.yml",
        "Workflow-Pfad existiert nicht im Index: 'zz-other' in .github/workflows/x.yml",
    ]


def test_main_is_green_on_current_index(gate, capsys):
    assert gate.main() == 0
    assert "OK:" in capsys.readouterr().out


def test_main_is_red_with_extra_node(gate, monkeypatch, capsys, files):
    monkeypatch.setattr(gate, "tracked_files", lambda *a, **k: list(files) + ["zz-unexpected-node/x.py"])
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "Unerwarteter Top-Level-Knoten: 'zz-unexpected-node'" in out
