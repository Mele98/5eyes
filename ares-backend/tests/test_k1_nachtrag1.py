"""K1-Nachtrag 1 (Pruefung H-165): N-913-02 und N-913-04.

* N-913-02: der einmalige Uebergang v4 -> v5 des Allokations-Pruefwerts meldet
  ehrlich "Berechnungsgrundlage aktualisiert -- bitte neu berechnen", nicht
  "Vermoegen, Cashflows oder Ziele".
* N-913-04: Depot-Check-Fallback (ohne Empfehlungslauf) und Backtest-Startwert
  summieren nie nominal ueber Waehrungen; strikte FX-Basis bzw. typisierte Sperre.

Kurse sind synthetische Testvektoren.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.fx_freshness import (
    STALE_BASIS_UPDATED_MESSAGE,
    STALE_INPUTS_MESSAGE,
    predates_fx_effective_hash,
    stale_allocation_message,
)
from core.reason_codes import DomainError
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
    "label": "Synthetic USD depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
    "current_value_rappen": 100_000_00, "currency": "USD", "data_classification": "synthetic",
    "alloc_equities_bps": 7000, "alloc_bonds_bps": 2000, "alloc_real_estate_bps": 0,
    "alloc_liquidity_bps": 1000, "alloc_alternatives_bps": 0,
}


def _set_usd(api, source):
    row = {"currency": "USD", "rate": 0.88, "source": source, "notes": "Testvektor"}
    if source != "Default":
        row["confirm_current"] = True
    assert api.put("/fx-rates", json={"rates": [row]}).status_code == 200


# ── N-913-02 ────────────────────────────────────────────────────────────────


def test_v4_allocation_is_recognised_by_its_model_basis():
    pre_k1 = json.dumps({"optimization_model_basis": {"basis_id": "stochastic_decision_v2"}})
    k1 = json.dumps({"optimization_model_basis": {"property_advanced_features": "disabled_until_p1_closure_v1"}})
    assert predates_fx_effective_hash(pre_k1) is True
    assert predates_fx_effective_hash(k1) is False
    assert predates_fx_effective_hash(json.dumps({"engine_version": "manual"})) is False  # unbekannt
    assert predates_fx_effective_hash(None) is False
    assert stale_allocation_message([], True) == STALE_BASIS_UPDATED_MESSAGE
    assert "Vermoegen, Cashflows oder Ziele" not in STALE_BASIS_UPDATED_MESSAGE
    assert "Berechnungsgrundlage aktualisiert" in STALE_BASIS_UPDATED_MESSAGE
    assert stale_allocation_message([], False) == STALE_INPUTS_MESSAGE
    assert "Wechselkurs USD" in stale_allocation_message(["USD"], True)


def _generated(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:300]
    return client_id, mandate_id


def test_transition_message_is_honest_for_pre_k1_allocation(api, advisor_user, monkeypatch):
    """Ein Bestand mit v4-Pruefwert wird beim ersten Tabellenwechsel einmalig
    stale -- die Meldung nennt den Update-Grund, nicht Vermoegen/Cashflows/Ziele.
    Der v4-Bestand wird hier ueber die Erkennungsfunktion simuliert (ein echter
    v4-Hash ist ohne Eingriff in die gespeicherte Allokation nicht herstellbar)."""
    import services.portfolio_engine as pe

    client_id, mandate_id = _generated(api, advisor_user)
    # Kurstabellenwechsel mit Einfluss auf den Pruefwert simulieren: hier eine
    # Eingabeaenderung, die Ursache wird nur ueber die Erkennung bestimmt.
    api.post(f"/clients/{client_id}/cashflows", json={
        "cashflow_type": "Expense", "label": "Synthetic extra", "amount_rappen": 1_000_00,
        "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic",
    })
    monkeypatch.setattr(pe, "predates_fx_effective_hash", lambda _json: True)
    stale = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert stale.status_code == 409, stale.text[:300]
    assert "Berechnungsgrundlage aktualisiert" in stale.text
    assert "Vermoegen, Cashflows oder Ziele" not in stale.text
    # Gegenprobe: eine nach K1 erzeugte Allokation meldet weiter die Eingaben.
    monkeypatch.undo()
    again = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert again.status_code == 409 and "Vermoegen, Cashflows oder Ziele" in again.text


# ── N-913-04 ────────────────────────────────────────────────────────────────


def test_depot_check_fallback_converts_with_strict_fx_basis(api, advisor_user, session_factory):
    from models.mandates import Mandate
    from services.depot_check import compute_depot_check

    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_wealth(api, client_id)
    _set_usd(api, "Manual")
    assert api.post(f"/clients/{client_id}/wealth-positions", json=USD_DEPOT).status_code == 201
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = compute_depot_check(db, mandate)
    # Beratungsvermoegen der Thierry-Persona CHF 530'000 + USD 100'000 * 0.88.
    assert result["total_advisory_wealth_rappen"] == 530_000_00 + 88_000_00, result["total_advisory_wealth_rappen"]

    _set_usd(api, "Default")  # Ersatzkurs: keine Summe, typisierte Sperre (Analyse ohne Betraege)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).one()
        blocked = compute_depot_check(db, mandate)
    assert blocked["fx_block_reason_code"] == "CCX_FX_BASIS_MISSING"
    assert blocked["total_advisory_wealth_rappen"] is None


def test_backtest_start_value_fallback_never_sums_nominally():
    from services.backtest_strategy import _resolve_initial_value_rappen

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return self.rows

    def db(rows):
        return SimpleNamespace(query=lambda _model: _Query(rows))

    mandate = SimpleNamespace(client_id="c", base_currency="CHF")
    ta = SimpleNamespace(advisory_wealth_at_generation_rappen=0)
    chf = SimpleNamespace(current_value_rappen=400_000_00, currency="CHF")
    usd = SimpleNamespace(current_value_rappen=100_000_00, currency="USD")
    assert _resolve_initial_value_rappen(db([chf]), mandate, ta) == 400_000_00
    with pytest.raises(DomainError) as exc:
        _resolve_initial_value_rappen(db([chf, usd]), mandate, ta)
    assert exc.value.reason_code == "CCX_FX_BASIS_MISMATCH"
    # Mit Snapshot wird nichts summiert.
    assert _resolve_initial_value_rappen(db([chf, usd]), mandate,
                                         SimpleNamespace(advisory_wealth_at_generation_rappen=7)) == 7
