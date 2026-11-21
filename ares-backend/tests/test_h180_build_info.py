"""H-180 EXE-01/EXE-03: Build-Kennung und Import-Selbsttest (Quellseite).

Die Artefaktseite prueft der Packaging-Smoke (scripts/packaging_release_checks.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core import build_info as bi  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    bi.build_info.cache_clear()
    yield
    bi.build_info.cache_clear()


def test_source_run_has_no_build_info_and_keeps_settings_version(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert bi.build_info() is None
    assert bi.effective_version("1.3.0") == "1.3.0"
    assert bi.build_sha() is None


def test_frozen_bundle_reports_package_version_and_sha(monkeypatch, tmp_path):
    (tmp_path / bi.BUILD_INFO_FILE).write_text(json.dumps(
        {"product": "Ares", "version": "0.4.0", "git_sha": "a" * 40}), encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bi.effective_version("1.3.0") == "0.4.0"
    assert bi.build_sha() == "a" * 40


def test_corrupt_build_info_is_ignored(monkeypatch, tmp_path):
    (tmp_path / bi.BUILD_INFO_FILE).write_text("{kaputt", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bi.build_info() is None


def test_health_payload_carries_build_sha_field():
    from routers.health import _base_payload

    payload = _base_payload()
    assert "build_sha" in payload and payload["version"]


def test_build_backend_embeds_build_info_version_file_and_lazy_modules():
    js = (REPO / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "ares_build_info.json" in js and "--version-file" in js
    for needle in ("'scipy._external'", "'core'", "'schemas'", "'packaging_selftest'"):
        assert needle in js, needle


def test_self_test_imports_passes_in_source_tree():
    import packaging_selftest

    result = packaging_selftest.run_self_test()
    assert result["ok"], result["failures"]
    assert result["own_modules"] >= 300
    assert "services.optimizer.solver" in packaging_selftest.RUNTIME_MODULES


def test_self_test_reports_missing_module(monkeypatch):
    import packaging_selftest

    monkeypatch.setattr(packaging_selftest, "RUNTIME_MODULES", ("ares_h180_gibt_es_nicht",))
    monkeypatch.setattr(packaging_selftest, "OWN_PACKAGES", ("core",))
    result = packaging_selftest.run_self_test()
    assert not result["ok"] and "ares_h180_gibt_es_nicht" in result["failures"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")
def test_frontend_label_shows_version_and_short_sha():
    script = (REPO / "ares-desktop" / "frontend" / "build-info.js").read_text(encoding="utf-8")
    probe = (
        "global.window={};global.document={readyState:'complete',getElementById:()=>null};"
        + script
        + ";const L=window.AresBuildInfo.label;"
        "console.log(JSON.stringify([L({version:'0.4.0',build_sha:'" + "b" * 40 + "'}),"
        "L({version:'1.3.0',build_sha:null})]));"
    )
    out = subprocess.run(["node", "-e", probe], capture_output=True, check=True).stdout.decode("utf-8")
    assert json.loads(out) == ["Ares 0.4.0 · Build bbbbbbb", "Ares 1.3.0 · Entwicklungsstand"]
