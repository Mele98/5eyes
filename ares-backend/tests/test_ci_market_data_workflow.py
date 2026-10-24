"""P20: Validierungstest fuer den GitHub-Workflow.

Statisch (kein Netzwerk, kein gh-CLI):
- YAML laedt sauber.
- Pflicht-Trigger vorhanden (schedule + pull_request + workflow_dispatch).
- Pfad-Filter beruehrt market_data/ und smoketest-Skript.
- Workflow ruft scripts/smoketest_market_data.py mit --no-network.
- Live-Mode nur ueber workflow_dispatch + secret-Gates.

Zweck: verhindert, dass Workflow-File ungewollt zerbricht (z.B. falscher
Pfadfilter, kaputte YAML-Struktur, Cron-Schedule weg).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "market_data_smoketest.yml"


@pytest.fixture(scope="module")
def workflow_dict():
    yaml = pytest.importorskip("yaml")
    raw = WORKFLOW.read_text(encoding="utf-8")
    return yaml.safe_load(raw), raw


# ============================================================================
# Existenz und YAML-Syntax
# ============================================================================


def test_workflow_file_exists():
    assert WORKFLOW.exists(), f"Workflow-File fehlt: {WORKFLOW}"


def test_workflow_yaml_loads(workflow_dict):
    data, raw = workflow_dict
    assert isinstance(data, dict)
    assert data.get("name")


# ============================================================================
# Trigger
# ============================================================================


def test_workflow_has_schedule(workflow_dict):
    data, _ = workflow_dict
    # YAML 'on' wird in Python zu Boolean True parsed (on=true), daher beide checken
    triggers = data.get("on") or data.get(True)
    assert triggers, "Keine Trigger im Workflow"
    assert "schedule" in triggers
    schedule = triggers["schedule"]
    assert isinstance(schedule, list) and len(schedule) > 0
    assert "cron" in schedule[0]
    cron = schedule[0]["cron"]
    # Format: M H D M W -- 5 Felder
    assert len(cron.split()) == 5


def test_workflow_has_pull_request_with_paths(workflow_dict):
    data, _ = workflow_dict
    triggers = data.get("on") or data.get(True)
    assert "pull_request" in triggers
    pr = triggers["pull_request"]
    assert "paths" in pr
    paths = pr["paths"]
    assert any("market_data" in p for p in paths), \
        "Path-Filter trifft market_data/ nicht"
    assert any("smoketest_market_data.py" in p for p in paths), \
        "Path-Filter trifft Smoketest-Skript nicht"


def test_workflow_has_workflow_dispatch(workflow_dict):
    data, _ = workflow_dict
    triggers = data.get("on") or data.get(True)
    assert "workflow_dispatch" in triggers
    wd = triggers["workflow_dispatch"]
    assert "inputs" in wd
    assert "live" in wd["inputs"]


# ============================================================================
# Job-Struktur
# ============================================================================


def test_workflow_has_smoketest_job(workflow_dict):
    data, _ = workflow_dict
    jobs = data.get("jobs") or {}
    assert "smoketest" in jobs
    job = jobs["smoketest"]
    assert job.get("runs-on") == "ubuntu-latest"
    assert "steps" in job and len(job["steps"]) >= 3


def test_workflow_installs_requirements(workflow_dict):
    _, raw = workflow_dict
    assert "pip install -r requirements.txt" in raw


def test_workflow_runs_smoketest_no_network(workflow_dict):
    _, raw = workflow_dict
    assert "scripts/smoketest_market_data.py" in raw
    assert "--no-network" in raw


def test_workflow_uploads_report_artifact(workflow_dict):
    _, raw = workflow_dict
    assert "actions/upload-artifact" in raw
    assert "smoketest_report.md" in raw


# ============================================================================
# Live-Mode-Gates
# ============================================================================


def test_workflow_live_mode_uses_secrets(workflow_dict):
    _, raw = workflow_dict
    # Live-Mode darf API-Keys nur ueber secrets bekommen, nie hardcoded
    assert "${{ secrets.ALPHAVANTAGE_API_KEY }}" in raw
    assert "github.event.inputs.live == 'true'" in raw


def test_workflow_live_mode_is_opt_in(workflow_dict):
    """Live-Mode darf nur bei workflow_dispatch laufen, nicht bei jedem Cron/PR."""
    _, raw = workflow_dict
    # Suche Live-Step und pruefe seine if-Bedingung
    assert "github.event_name == 'workflow_dispatch'" in raw
