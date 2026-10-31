"""W1-803-03: Reporting-Mount in der gepackten (PyInstaller-)EXE.

Im Frozen-Build zeigt ``__file__`` von main.py in ``sys._MEIPASS``; der
Repo-relative Pfad ``../ares-desktop/frontend/reporting/dist`` existiert dort
nicht. Vorher lieferte /reporting daher in jeder gepackten App 404 (per
Packaging-Smoke belegt). Der Build bettet die Sub-App als ``reporting_dist``
ein, main.py loest sie bevorzugt von dort auf.
"""
from __future__ import annotations

import sys
from pathlib import Path

import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frozen_build_uses_embedded_reporting_dist(tmp_path, monkeypatch):
    embedded = tmp_path / "reporting_dist"
    embedded.mkdir()
    (embedded / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main._resolve_reporting_dist() == embedded


def test_frozen_build_without_embedded_dist_falls_back_to_source_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    expected = REPO_ROOT / "ares-desktop" / "frontend" / "reporting" / "dist"
    assert main._resolve_reporting_dist() == expected


def test_source_run_uses_source_tree(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = REPO_ROOT / "ares-desktop" / "frontend" / "reporting" / "dist"
    assert main._resolve_reporting_dist() == expected


def test_build_backend_embeds_reporting_dist_fail_closed():
    script = (REPO_ROOT / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "reporting_dist" in script
    assert "reportingDataArg" in script
    assert "npm run build:reporting" in script  # klare Fehlermeldung bei fehlender Sub-App


def test_packaging_smoke_workflow_runs_on_pull_requests():
    workflow = (REPO_ROOT / ".github" / "workflows" / "packaging_smoke.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "windows-latest" in workflow
    assert "npm run pack" in workflow
    assert "scripts/packaging_smoke.py" in workflow
