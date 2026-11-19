"""K1 / E2E-03 (Dok. 115, BLOCKER): eine irrelevante Kursaenderung entwertet keine
gespeicherte oder publizierte Allokation.

Vorher band ``canonical_model_signature`` die ``basis_id`` -- den Fingerabdruck
der GANZEN Kurstabelle -- in den Allokations-Pruefwert (``input_snapshot_hash``).
Jede Kursaenderung (auch GBP/JPY bei einem reinen CHF-Mandat) machte alle
Allokationen veraltet; die Meldung behauptete "Vermoegen, Cashflows oder Ziele".
Jetzt (Snapshot-Version v5) zaehlen nur die effektiven Kurse der verwendeten
Waehrungen plus Zielwaehrung und ``uses_versioned_defaults``. Die Meldung nennt
eine echte Kursaenderung als Ursache.

Kurse sind synthetische Testvektoren.
"""
from __future__ import annotations

from services.portfolio_engine import fx_freshness_projection_context
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
    "current_value_rappen": 100_000_00, "currency": "USD", "data_classification": "synthetic",
    "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_real_estate_bps": 0,
    "alloc_liquidity_bps": 1000, "alloc_alternatives_bps": 0,
}


def _rate(api, currency, rate):
    resp = api.put("/fx-rates", json={"rates": [{
        "currency": currency, "rate": rate, "source": "Manual", "notes": "Testvektor",
        "confirm_current": True,
    }]})
    assert resp.status_code == 200, resp.text[:300]


def _setup(api, advisor_user, *, usd: bool):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    if usd:
        _rate(api, "USD", 0.88)
        assert api.post(f"/clients/{client_id}/wealth-positions", json=USD_DEPOT).status_code == 201
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:400]
    assert api.get(f"/mandates/{mandate_id}/target-allocation/current/payload").status_code == 200
    return mandate_id


def test_unrelated_rate_change_keeps_chf_mandate_fresh(api, advisor_user):
    mandate_id = _setup(api, advisor_user, usd=False)
    _rate(api, "GBP", 1.13)
    _rate(api, "JPY", 0.0058)
    payload = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert payload.status_code == 200, payload.text[:400]


def test_relevant_rate_change_makes_allocation_stale_with_true_cause(api, advisor_user):
    mandate_id = _setup(api, advisor_user, usd=True)
    # Irrelevant fuer dieses Mandat: GBP.
    _rate(api, "GBP", 1.13)
    assert api.get(f"/mandates/{mandate_id}/target-allocation/current/payload").status_code == 200
    # Bestaetigung desselben USD-Kurses aendert keinen effektiven Kurs.
    _rate(api, "USD", 0.88)
    assert api.get(f"/mandates/{mandate_id}/target-allocation/current/payload").status_code == 200
    # Relevante Aenderung: USD-Kurs selbst.
    _rate(api, "USD", 0.91)
    stale = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert stale.status_code == 409, stale.text[:400]
    text = stale.text
    assert "Wechselkurs USD" in text, text[:400]
    assert "Vermoegen, Cashflows oder Ziele" not in text


def test_freshness_view_drops_only_table_wide_provenance():
    context = {
        "fx_basis": {"basis_id": "db_current:abc", "uses_versioned_defaults": False,
                     "target_currency": "CHF", "effective_rates_x1e8": [["CHF", 100000000]]},
        "external_foundation_projection": {
            "pension_transfer_ledger_snapshot": {
                "snapshot_hash": "h", "snapshot_id": "ptls-h", "rows": [],
                "fx_evidence": {"status": "applied", "basis_id": "x", "effective_rates_x1e8": []},
            },
            "property_series_rappen": [1],
        },
    }
    view = fx_freshness_projection_context(context)
    assert "basis_id" not in view["fx_basis"]
    assert view["fx_basis"]["effective_rates_x1e8"] == [["CHF", 100000000]]
    snapshot = view["external_foundation_projection"]["pension_transfer_ledger_snapshot"]
    assert "basis_id" not in snapshot["fx_evidence"] and "snapshot_hash" not in snapshot
    assert context["fx_basis"]["basis_id"] == "db_current:abc"  # Original (Audit) unveraendert
