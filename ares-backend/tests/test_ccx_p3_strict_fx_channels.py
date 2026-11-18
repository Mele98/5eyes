"""CCX-P3 Nachtrag 1 (N-909-01) -- Pruefer-Fall ueber die echte API.

CHF-Mandat mit CHF-Depot und USD-Depot. Mit belegtem, frischem USD-Kurs
(synthetischer Testvektor 0.8800, Quelle Manual) liefern Strategie, App-Payload,
Asset-Allocation- und Anlagestrategie-PDF. Wird der USD-Kurs auf die Quelle
``Default`` (Ersatzkurs, Weg "Defaults laden") gesetzt, sperren App-Payload, beide
PDFs und die Neuberechnung typisiert mit ``CCX_FX_BASIS_MISSING``; der
Beratungsbericht zeigt keine Summen und keine Prognose. Kein Ersatzkurs wird
kundenwirksam, nichts wird gerendert oder archiviert.
"""
from __future__ import annotations

import pytest

from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    _seed_cashflows,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

USD_DEPOT = {
    "label": "Depot USD", "position_type": "Depot", "assignment": "Beratungsvermögen",
    "current_value_rappen": 100_000_05, "currency": "USD", "data_classification": "synthetic",
    "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_real_estate_bps": 0,
    "alloc_liquidity_bps": 1000, "alloc_alternatives_bps": 0,
}


def _set_usd(api, source):
    resp = api.put("/fx-rates", json={"rates": [
        {"currency": "USD", "rate": 0.88, "source": source, "notes": "Testvektor"}]})
    assert resp.status_code == 200, resp.text[:300]


def _code(resp):
    body = resp.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail.get("reason_code") if isinstance(detail, dict) else None


def test_substitute_usd_rate_blocks_payload_pdfs_and_regeneration(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    resp = api.post(f"/clients/{client_id}/wealth-positions", json=USD_DEPOT)
    assert resp.status_code == 201, resp.text[:300]
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)

    # Ersatzkurs vor der Strategie: Neuberechnung sperrt.
    _set_usd(api, "Default")
    blocked = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert blocked.status_code == 409 and _code(blocked) == "CCX_FX_BASIS_MISSING", blocked.text[:300]

    # Belegter Kurs: alles liefert (Kontrolle).
    _set_usd(api, "Manual")
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:300]
    alloc_id = generated.json().get("target_allocation_id") or generated.json().get("id")
    ok_payload = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert ok_payload.status_code == 200, ok_payload.text[:400]
    ok_pdf = api.get(f"/mandates/{mandate_id}/reports/assetallocation.pdf")
    assert ok_pdf.status_code == 200, ok_pdf.text[:300]

    # Ersatzkurs nach der Strategie: App und PDFs sperren typisiert.
    _set_usd(api, "Default")
    payload = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert payload.status_code == 409 and _code(payload) == "CCX_FX_BASIS_MISSING", payload.text[:300]
    for report, params in (("assetallocation.pdf", {}),
                           ("anlagestrategie.pdf", {"expected_allocation_id": alloc_id})):
        pdf = api.get(f"/mandates/{mandate_id}/reports/{report}", params=params)
        assert pdf.status_code == 409, (report, pdf.status_code, pdf.text[:300])
        assert _code(pdf) == "CCX_FX_BASIS_MISSING", (report, pdf.text[:300])
    report = api.get(f"/mandates/{mandate_id}/advisory-report")
    if report.status_code == 409:  # Bericht insgesamt gesperrt (Engine-Spiegel strikt)
        assert _code(report) == "CCX_FX_BASIS_MISSING", report.text[:300]
    else:
        assert report.status_code == 200, report.text[:300]
        sections = report.json().get("sections") or report.json()
        assert sections["ausgangslage"]["wealth_summary"]["beratungsvermoegen_rappen"] is None
        mc = sections["goal_based_investing"]["monte_carlo_paths"]
        assert mc["projection_status"] == "blocked" and mc.get("p50") == []
    pdf = api.get(f"/mandates/{mandate_id}/reports/advisory-report.pdf")
    assert pdf.status_code == 409 and _code(pdf) == "CCX_FX_BASIS_MISSING", (pdf.status_code, pdf.text[:300])
