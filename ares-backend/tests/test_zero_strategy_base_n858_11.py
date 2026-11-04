"""N-858-11 (Pruefrunde #858, Dok. 86): Strategiebasis 0 ist keine fehlende Angabe.

Befund: Beansprucht die Liquiditaetsreserve das ganze Beratungsvermoegen
(synthetisch: Konto CHF 20'000, Ausgaben CHF 40'000 p.a.), rechnet die
Strategie auf eine investierbare Basis von 0. Die Empfehlung ersetzte diese 0
aber per ``x or advisory_wealth_rappen`` durch das volle Beratungsvermoegen:
Fondsuebersicht ("Zielvolumen CHF 20'000"), Kostenausweis (TER und
Transaktionskosten auf CHF 20'000) und Handelsliste (Kauf fuer CHF 20'000)
haetten die Reserve investiert.

Soll:
  * Basis 0 -> Positionen mit Zielbetrag 0, Zielvolumen 0, Kostenausweis ohne
    Produkt-/Transaktionskosten (nur volumenunabhaengige Dienstleistungskosten
    auf das Beratungsvermoegen), Handelsliste ohne Kaeufe, und klar
    ausgewiesen ("keine investierbare Strategiebasis").
  * Basis > 0 -> unveraendert (Summe der Zielbetraege = Strategiebasis).
  * Basis fehlt (None, Altbestand) -> bisheriger Rueckfall aufs
    Beratungsvermoegen.

Nur synthetische Daten.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.cost_disclosure import ZERO_STRATEGY_BASE_COST_NOTE, calculate_cost_disclosure
from services.portfolio_engine_payload import (
    ZERO_STRATEGY_BASE_WARNING,
    resolve_investable_wealth_rappen,
)
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401
    _create_client_and_mandate,
    _seed_products,
    _seed_risk_profile,
    advisor_user,
    api,
    session_factory,
)


def _scenario(api, advisor_user, *, account_rappen: int, expense_rappen: int):
    cid, mid = _create_client_and_mandate(api, advisor_user)
    r = api.post(f"/clients/{cid}/cashflows", json={
        "cashflow_type": "Expense", "label": "Ausgabe Synth", "amount_rappen": expense_rappen,
        "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic",
    })
    assert r.status_code in (200, 201), r.text
    r = api.post(f"/clients/{cid}/wealth-positions", json={
        "label": "Konto Synth", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
        "current_value_rappen": account_rappen, "currency": "CHF",
        "liquidity_instrument": "Kontoguthaben", "data_classification": "synthetic",
    })
    assert r.status_code == 201, r.text
    _seed_risk_profile(api, mid)
    _seed_products(api, advisor_user)
    alloc = api.post(f"/mandates/{mid}/target-allocation/generate", json={})
    assert alloc.status_code in (200, 201), alloc.text
    rec = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    return mid, alloc.json(), rec.json()


def test_zero_strategy_base_invests_nothing_and_says_so(api, advisor_user):
    mid, alloc, rec = _scenario(api, advisor_user, account_rappen=20_000_00, expense_rappen=40_000_00)
    # Vorbedingung: die Strategie rechnet tatsaechlich auf Basis 0.
    assert alloc["advisory_wealth_rappen"] == 20_000_00
    assert alloc["strategy_base_rappen"] == 0
    assert alloc["external_reserve_rappen"] == 20_000_00

    # Empfehlung: Zielbetraege 0, Zielvolumen 0, Basis 0 -- nicht 20'000.
    assert rec["investable_advisory_wealth_rappen"] == 0
    assert rec["positions"], "Gewichte (Strategie) bleiben sichtbar"
    assert all(int(p["target_amount_rappen"]) == 0 for p in rec["positions"])
    assert sum(int(p["target_weight_bps"]) for p in rec["positions"]) > 0
    assert ZERO_STRATEGY_BASE_WARNING in rec["warnings"]

    # Kostenausweis: kein Produkt-/Transaktionsvolumen, Hinweis statt
    # "TER nicht hinterlegt"; Dienstleistungskosten auf das Beratungsvermoegen.
    cd = api.get(f"/mandates/{mid}/cost-disclosure/ex-ante")
    assert cd.status_code == 200, cd.text
    cd = cd.json()
    assert cd["invested_amount_rappen"] == 0
    assert cd["advisory_wealth_rappen"] == 20_000_00
    keys = {item["key"] for item in cd["cost_items"]}
    assert "product_ter" not in keys
    assert "initial_transaction_costs" not in keys
    assert all(int(item["basis_rappen"]) == 20_000_00 for item in cd["cost_items"])
    assert ZERO_STRATEGY_BASE_COST_NOTE in cd["warnings"]
    assert not any("TER) sind" in w for w in cd["warnings"])

    # Handelsliste: nichts zu kaufen.
    run_id = rec["positions"][0]["run_id"]
    pv = api.get(
        f"/mandates/{mid}/recommendations/{run_id}/portfolio-handoff-preview",
        params={"confirm_no_existing_holdings": "true"},
    )
    assert pv.status_code == 409, pv.text
    assert pv.json()["detail"]["reason_code"] == "NO_TRADES"
    assert "Keine investierbare Strategiebasis" in pv.json()["detail"]["message"]


def test_positive_strategy_base_unchanged(api, advisor_user):
    _mid, alloc, rec = _scenario(api, advisor_user, account_rappen=500_000_00, expense_rappen=40_000_00)
    base = int(alloc["strategy_base_rappen"])
    assert 0 < base < 500_000_00
    assert rec["investable_advisory_wealth_rappen"] == base
    total = sum(int(p["target_amount_rappen"]) for p in rec["positions"])
    assert abs(total - base) <= len(rec["positions"])  # Rundung je Position
    assert ZERO_STRATEGY_BASE_WARNING not in rec["warnings"]


def test_resolve_investable_wealth_none_keeps_legacy_fallback():
    assert resolve_investable_wealth_rappen({}, 123_00) == 123_00
    assert resolve_investable_wealth_rappen({"investable_advisory_wealth_rappen": None}, 123_00) == 123_00
    assert resolve_investable_wealth_rappen({"investable_advisory_wealth_rappen": 0}, 123_00) == 0
    assert resolve_investable_wealth_rappen({"investable_advisory_wealth_rappen": 45_00}, 123_00) == 45_00


def test_cost_disclosure_zero_volume_positions_are_not_missing_ter():
    fee_model = {"default_advisory_fee_bps": 100}
    zero = calculate_cost_disclosure(
        advisory_wealth_rappen=20_000_00,
        positions=[{"amount_rappen": 0, "weight_bps": 10_000, "ter_bps": 20}],
        fee_model=fee_model,
    )
    assert zero["invested_amount_rappen"] == 0
    assert ZERO_STRATEGY_BASE_COST_NOTE in zero["warnings"]
    assert {i["key"] for i in zero["cost_items"]} == {"default_advisory_fee_bps"}
    assert zero["totals"]["annual_rappen"] == 200_00
    # Gegenprobe: positives Volumen -> TER wie bisher, kein Basis-0-Hinweis.
    pos = calculate_cost_disclosure(
        advisory_wealth_rappen=20_000_00,
        positions=[{"amount_rappen": 20_000_00, "weight_bps": 10_000, "ter_bps": 20}],
        fee_model=fee_model,
    )
    assert "product_ter" in {i["key"] for i in pos["cost_items"]}
    assert ZERO_STRATEGY_BASE_COST_NOTE not in pos["warnings"]


def test_cost_disclosure_row_amount_zero_is_not_missing(monkeypatch):
    from services import cost_disclosure as cd

    assert cd._position_amount_rappen(SimpleNamespace(target_amount_rappen=0, current_amount_rappen=5_00)) == 0
    assert cd._position_amount_rappen(SimpleNamespace(target_amount_rappen=None, current_amount_rappen=5_00)) == 5_00
    assert cd._position_amount_rappen(SimpleNamespace(target_amount_rappen=7_00, current_amount_rappen=5_00)) == 7_00
    assert cd._position_amount_rappen(SimpleNamespace(target_amount_rappen=None, current_amount_rappen=None)) == 0
