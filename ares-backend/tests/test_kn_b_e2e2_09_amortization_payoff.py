"""KN-B / E2E2-09: abgeleitete Amortisation endet bei getilgter heutiger Schuld.

Befund (Dok. 117): Die aus der Hypothek abgeleitete Amortisation floss im
K1-Modus (Property-Gate) unbefristet als Ausgabe ab -- auch weit ueber die
Restschuld hinaus --, ohne dass die Hypothek sank. Die Prognose lag zu tief.

CTO-Entscheid 2026-11-19: Die Amortisation endet, sobald die kumulierte
Amortisation die heutige Schuld erreicht; das letzte Jahr anteilig. Die Schuld
bleibt in der Bilanz konstant (konservativ, bis Property-P1).

Gegenprobe: ``k1_payoff_cap`` auf False (bzw. alte Frueh-Rueckgabe im K1-Modus)
-> die Tests werden rot.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.wealth_cashflows import mortgage_amortization_adjustment_series
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


def _hyp(**kw):
    base = dict(position_type="Hypothek", is_active=1, deleted_at=None, current_value_rappen=25_000_00,
                mortgage_interest_rate_bps=150, mortgage_amortization_rappen=10_000_00,
                mortgage_amortization_type="Direkt", currency="CHF")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("amort_type", ["Direkt", "Indirekt (Säule 3a)", None])
def test_payoff_cap_in_k1_mode_last_year_pro_rata(amort_type):
    # 25'000 Schuld, 10'000 p.a.: 10'000, 10'000, 5'000 (anteilig), dann 0.
    # Die Serie korrigiert die konstante Ausgabe von 10'000 um den Ueberhang.
    assert mortgage_amortization_adjustment_series([_hyp(mortgage_amortization_type=amort_type)], 6) == [
        0, 0, 5_000_00, 10_000_00, 10_000_00, 10_000_00,
    ]


def test_no_change_while_debt_is_not_repaid_within_horizon():
    """Persona A (600'000 Schuld, 10'000 p.a., 28 Jahre): kein Unterschied."""
    pos = _hyp(current_value_rappen=600_000_00)
    assert mortgage_amortization_adjustment_series([pos], 28) == [0] * 28


def test_without_debt_no_amortization_flows():
    pos = _hyp(current_value_rappen=0)
    assert mortgage_amortization_adjustment_series([pos], 4) == [10_000_00] * 4


def _mortgage_mandate(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    created = api.post(f"/clients/{client_id}/wealth-positions", json={
        "label": "Hypothek Test (fiktiv)", "position_type": "Hypothek", "assignment": "Verbindlichkeit",
        "current_value_rappen": 25_000_00, "currency": "CHF", "mortgage_type": "Festhypothek",
        "mortgage_interest_rate_bps": 160, "mortgage_maturity_date": "2032-03-31",
        "mortgage_amortization_type": "Direkt", "mortgage_amortization_rappen": 10_000_00,
        "data_classification": "synthetic",
    })
    assert created.status_code == 201, created.text[:300]
    return client_id, mandate_id


def test_cashflow_projection_ends_amortization_and_keeps_debt(api, advisor_user):
    client_id, _mandate_id = _mortgage_mandate(api, advisor_user)
    years = api.get(f"/clients/{client_id}/cashflow-projection?horizon_years=5").json()["years"]
    expenses = [int(y["recurring_expense_rappen"]) for y in years]
    # Zins (400) bleibt konstant (Schuld konstant), Amortisation 10'000/10'000/5'000/0/0.
    deltas = [expenses[0] - value for value in expenses]
    print("E2E2-09 Ausgaben je Jahr (Rappen):", expenses)
    assert deltas == [0, 0, 5_000_00, 10_000_00, 10_000_00], expenses


def test_engine_projection_before_and_after(api, advisor_user, session_factory, monkeypatch):
    """Vorher/Nachher am Testmandat (Engine-Projektionsreihe)."""
    import services.portfolio_engine as pe
    from models.mandates import Mandate

    _client_id, mandate_id = _mortgage_mandate(api, advisor_user)
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:300]

    def series():
        with session_factory() as db:
            mandate = db.query(Mandate).filter(Mandate.id == mandate_id).one()
            inputs = pe._load_allocation_inputs(db, mandate, {})
            liabilities = inputs["external_foundation_projection"]["liability_series_rappen"]
            assert len(set(liabilities)) == 1  # Schuld in der Bilanz konstant (bis Property-P1)
            return [int(v) for v in inputs["cashflow_projection_series_rappen"]]

    after = series()
    with monkeypatch.context() as m:
        m.setattr(pe, "mortgage_amortization_adjustment_series", lambda positions, n, **_kw: [0] * int(n))
        before = series()
    diff = [a - b for a, b in zip(after, before)]
    print("E2E2-09 vorher:", before[:6], "nachher:", after[:6], "Differenz:", diff[:6])
    assert diff[:2] == [0, 0]
    assert diff[2] == 5_000_00
    assert all(value == 10_000_00 for value in diff[3:])
    assert len(diff) > 3
