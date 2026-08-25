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


def test_vite_proxies_mandate_editor_api_to_backend():
    # DL-4 (2026-06-07): der Dev-Proxy deckt bewusst die GANZE Mandate-API ab (nicht
    # nur advisory-report), sonst scheitern die Goals/Allocation/Cashflow/Mandate/CRM/
    # WealthInflow-Editor-Calls in `npm run dev`. Der frueher hier erzwungene enge
    # advisory-report-only-Kontrakt ist damit ueberholt. SPA-Routen liegen dank
    # base:'/reporting/' unter /reporting/... und werden vom Proxy nicht getroffen.
    content = _vite_config()
    # anker-praezises Muster (nicht ein unanker'tes '/mandates'), Ziel = Backend.
    assert "^/mandates/" in content
    assert "localhost:8000" in content


def test_vite_keeps_react_report_route_on_frontend():
    app = (REPORTING_ROOT / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "/mandates/:mandateId/report" in app
