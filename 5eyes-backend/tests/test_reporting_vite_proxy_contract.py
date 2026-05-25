from __future__ import annotations

from pathlib import Path


REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "reporting"
)


def _vite_config() -> str:
    return (REPORTING_ROOT / "vite.config.ts").read_text(encoding="utf-8")


def test_vite_proxies_only_advisory_report_api_under_mandates():
    content = _vite_config()
    assert "^/mandates/.*/advisory-report$" in content
    assert "'/mandates':" not in content
    assert '"/mandates":' not in content


def test_vite_keeps_react_report_route_on_frontend():
    app = (REPORTING_ROOT / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "/mandates/:mandateId/report" in app
