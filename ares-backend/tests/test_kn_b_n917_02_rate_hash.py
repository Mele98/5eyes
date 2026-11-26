"""KN-B / N-917-02: "kein Satz" und "0 %" sind im Input-Hash verschieden.

Befund (H-167-Pruefung R6): ``int(mortgage_interest_rate_bps or 0)`` setzte
"kein Satz" mit "0 %" gleich. Eine mit bewusst erfasstem 0 % gerechnete
Allokation blieb FRESH, wenn der Satz danach geloescht wurde, waehrend ein
neues Generate mit ``MORTGAGE_INTEREST_RATE_MISSING`` sperrt.

Jetzt traegt eine Hypothek, die das Property-Gate als "ohne Satz" sperren
wuerde (Schuld > 0, Satz None), den Wert -1. Alle anderen Positionen behalten
ihren bisherigen Wert -- kein Bestand wird dadurch entwertet.

Gegenprobe: die Zeile in ``_pos_v2`` auf ``int(... or 0)`` zuruecksetzen -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

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
from tests.test_k1_property_advanced_gate import _mortgage


def _pos(**kwargs):
    base = dict(id="m1", current_value_rappen=500_000_00, assignment="Verbindlichkeit", position_type="Hypothek",
                is_active=1, deleted_at=None, mortgage_interest_rate_bps=0, currency="CHF")
    base.update(kwargs)
    return SimpleNamespace(**base)


def _hash(positions):
    from services.portfolio_engine import _compute_input_snapshot_hash

    return _compute_input_snapshot_hash(advisory_positions=[], all_positions=positions, cashflows=[], goals=[],
                                        advisory_wealth_rappen=0, total_wealth_rappen=0)


def test_missing_rate_differs_from_zero_rate():
    assert _hash([_pos(mortgage_interest_rate_bps=None)]) != _hash([_pos(mortgage_interest_rate_bps=0)])


def test_other_positions_keep_their_hash():
    """Ohne Schuld bzw. ohne Hypothek bleibt der bisherige Wert (kein Bestand stale)."""
    depot = dict(position_type="Depot", assignment="Beratungsvermögen")
    assert _hash([_pos(mortgage_interest_rate_bps=None, **depot)]) == _hash([_pos(mortgage_interest_rate_bps=0, **depot)])
    no_debt = dict(current_value_rappen=0)
    assert _hash([_pos(mortgage_interest_rate_bps=None, **no_debt)]) == _hash([_pos(mortgage_interest_rate_bps=0, **no_debt)])


def test_deleting_the_rate_makes_the_allocation_stale(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    created = api.post(f"/clients/{client_id}/wealth-positions",
                       json={**_mortgage(), "label": "Hypothek 0 Prozent", "mortgage_interest_rate_bps": 0})
    assert created.status_code == 201, created.text[:300]
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:300]
    assert api.get(f"/mandates/{mandate_id}/target-allocation/current/payload").status_code == 200

    cleared = api.put(f"/clients/{client_id}/wealth-positions/{created.json()['id']}",
                      json={"mortgage_interest_rate_bps": None})
    assert cleared.status_code == 200, cleared.text[:300]
    stale = api.get(f"/mandates/{mandate_id}/target-allocation/current/payload")
    assert stale.status_code == 409, stale.text[:300]
    # Ein neues Generate sperrt typisiert (unveraendert).
    blocked = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert blocked.status_code == 409 and "MORTGAGE_INTEREST_RATE_MISSING" in blocked.text
