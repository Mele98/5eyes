"""K1 / CK-01: Kundensummen des Vermoegens nie als nominale Mischsumme.

Vorher addierte ``GET /clients/{id}/wealth-summary`` (View
``v_client_wealth_summary``) CHF 400'000 und USD 100'000 zu "500'000" -- unter
Feldern namens ``*_chf``. Jetzt konvertiert der Python-Pfad jede Position mit
EINER strikten P3-FX-Basis in die Mandats-/Kunden-Basiswaehrung; ein Ersatzkurs
oder ein fehlender Kurs sperrt typisiert. Dieselbe Regel gilt fuer die
Dashboard-Liste (``GET /dashboard/summary``), dort je Kunde.

Die Kurse sind synthetische Testvektoren, keine Fachwerte.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.reason_codes import DomainError
from services.client_wealth_summary import resolve_summary_currency
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

CHF_DEPOT = {
    "label": "Synthetic CHF depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
    "current_value_rappen": 400_000_00, "currency": "CHF", "valuation_date": "2026-11-18",
    "alloc_equities_bps": 6500, "alloc_bonds_bps": 2000, "alloc_real_estate_bps": 500,
    "alloc_liquidity_bps": 500, "alloc_alternatives_bps": 500, "data_classification": "synthetic",
}
USD_DEPOT = {
    "label": "Synthetic USD depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
    "current_value_rappen": 100_000_00, "currency": "USD", "valuation_date": "2026-11-18",
    "alloc_equities_bps": 7000, "alloc_bonds_bps": 2000, "alloc_real_estate_bps": 0,
    "alloc_liquidity_bps": 1000, "alloc_alternatives_bps": 0, "data_classification": "synthetic",
}
USD_LOAN = {
    "label": "Synthetic USD loan", "position_type": "Custom", "assignment": "Verbindlichkeit",
    "current_value_rappen": 10_000_00, "currency": "USD", "data_classification": "synthetic",
}


def _set_usd(api, source: str, rate: float = 0.88) -> None:
    row = {"currency": "USD", "rate": rate, "source": source, "notes": "Synthetischer Testvektor"}
    if source != "Default":
        row["confirm_current"] = True
    resp = api.put("/fx-rates", json={"rates": [row]})
    assert resp.status_code == 200, resp.text[:300]


def _code(resp):
    body = resp.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail.get("reason_code") if isinstance(detail, dict) else None


def _post(api, client_id, row):
    resp = api.post(f"/clients/{client_id}/wealth-positions", json=row)
    assert resp.status_code == 201, resp.text[:300]


def test_mixed_currency_summary_converts_with_confirmed_rate(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _set_usd(api, "Manual")
    _post(api, client_id, CHF_DEPOT)
    _post(api, client_id, USD_DEPOT)

    summary = api.get(f"/clients/{client_id}/wealth-summary")
    assert summary.status_code == 200, summary.text[:400]
    data = summary.json()
    # CHF 400'000 + USD 100'000 * 0.88 = CHF 488'000 (nie 500'000).
    assert data["advisory_wealth_rappen"] == 488_000_00, data
    assert data["gross_wealth_rappen"] == 488_000_00, data
    assert data["net_worth_rappen"] == 488_000_00, data
    assert data["advisory_wealth_chf"] == 488_000.0
    assert data["amount_currency"] == "CHF"
    assert data["fx_basis_hash"] and data["valuation_as_of"]

    # Mit ausdruecklichem Mandatskontext identisch (gleiche Basis).
    scoped = api.get(f"/clients/{client_id}/wealth-summary", params={"mandate_id": mandate_id}).json()
    assert scoped["advisory_wealth_rappen"] == 488_000_00
    assert scoped["fx_basis_hash"] == data["fx_basis_hash"]
    assert scoped["mandate_id"] == mandate_id

    # Verbindlichkeit in Fremdwaehrung: ebenfalls konvertiert, Netto ohne Rohsumme.
    _post(api, client_id, USD_LOAN)
    with_loan = api.get(f"/clients/{client_id}/wealth-summary").json()
    assert with_loan["liabilities_rappen"] == 8_800_00, with_loan
    assert with_loan["net_worth_rappen"] == 488_000_00 - 8_800_00, with_loan


def test_substitute_or_missing_rate_blocks_typed(api, advisor_user):
    client_id, _mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _post(api, client_id, CHF_DEPOT)
    _post(api, client_id, USD_DEPOT)

    missing = api.get(f"/clients/{client_id}/wealth-summary")
    assert missing.status_code == 409, missing.text[:300]
    assert _code(missing) == "CCX_FX_BASIS_MISSING"

    _set_usd(api, "Default")  # Ersatzkurs wird nie kundenwirksam
    substitute = api.get(f"/clients/{client_id}/wealth-summary")
    assert substitute.status_code == 409, substitute.text[:300]
    assert _code(substitute) == "CCX_FX_BASIS_MISSING"
    assert b"500000" not in substitute.content

    dashboard = api.get("/dashboard/summary")
    assert dashboard.status_code == 200, dashboard.text[:300]
    row = next(c for c in dashboard.json()["clients"] if c["client_id"] == client_id)
    assert row["amount_block_reason_code"] == "CCX_FX_BASIS_MISSING"
    assert row["net_worth_chf"] is None and row["advisory_wealth_rappen"] is None


def test_single_currency_case_unchanged(api, advisor_user):
    """CHF-only (und Fremdwaehrungs-Mandat mit CHF-Positionen): wie bisher die
    Positionswaehrung ohne Umrechnung, keine FX-Abfrage noetig."""
    client_id, _ = _create_client_and_mandate(api, advisor_user, "EUR")
    _post(api, client_id, CHF_DEPOT)
    data = api.get(f"/clients/{client_id}/wealth-summary").json()
    assert data["advisory_wealth_rappen"] == 400_000_00
    assert data["amount_currency"] == "CHF"

    dashboard = api.get("/dashboard/summary").json()
    row = next(c for c in dashboard["clients"] if c["client_id"] == client_id)
    assert row["advisory_wealth_rappen"] == 400_000_00
    assert row["advisory_wealth_chf"] == 400_000.0
    assert row["amount_currency"] == "CHF" and row["amount_block_reason_code"] is None


def test_dashboard_converts_mixed_currency_per_client(api, advisor_user):
    client_id, _ = _create_client_and_mandate(api, advisor_user, "CHF")
    _set_usd(api, "Manual")
    _post(api, client_id, CHF_DEPOT)
    _post(api, client_id, USD_DEPOT)
    row = next(c for c in api.get("/dashboard/summary").json()["clients"] if c["client_id"] == client_id)
    assert row["advisory_wealth_rappen"] == 488_000_00
    assert row["net_worth_chf"] == 488_000.0
    assert row["amount_currency"] == "CHF"


def test_mixed_currency_without_unique_client_currency_requires_context():
    positions = [SimpleNamespace(currency="CHF"), SimpleNamespace(currency="USD")]
    mandates = [SimpleNamespace(base_currency="CHF", status="Aktiv", deleted_at=None),
                SimpleNamespace(base_currency="EUR", status="Aktiv", deleted_at=None)]
    with pytest.raises(DomainError) as exc:
        resolve_summary_currency(positions, mandates)
    assert exc.value.reason_code == "CCX_FX_BASIS_MISMATCH"
    with pytest.raises(DomainError):
        resolve_summary_currency(positions, [])
    # Mandatskontext oder Zielwaehrung loesen den Fall eindeutig auf.
    assert resolve_summary_currency(positions, mandates, mandate_currency="EUR") == "EUR"
    assert resolve_summary_currency(positions, mandates, target_currency="USD") == "USD"
    # Aktive Mandate gehen vor beendeten.
    mixed = mandates[:1] + [SimpleNamespace(base_currency="EUR", status="Beendet", deleted_at=None)]
    assert resolve_summary_currency(positions, mixed) == "CHF"
