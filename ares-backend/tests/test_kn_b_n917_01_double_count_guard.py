"""KN-B / N-917-01: Doppelzaehlungs-Guard erkennt deutsche Komposita.

Befund (H-167-Pruefung R5): Bei aktiver Hypothek wurden "Hypozins",
"Schuldzins Eigenheim", "Hypothekaramortisation" und "Amortisationszahlung
Hypothek" als manuelle Cashflows angenommen (201) -- die Belastung zaehlte
doppelt (abgeleitet + manuell). Die Wortgrenzen-Regex verfehlte Komposita.

Gegenprobe: alte Regeln (``\\b(tilgung|amortisation|amortization)\\b`` bzw.
"hypothek" UND "zins") -> die Positivliste wird rot.
"""
from __future__ import annotations

import pytest

from routers.wealth import _is_amortization_label, _is_mortgage_interest_label
from tests.test_k1_property_advanced_gate import _client, _mortgage
from tests.test_e2e_thierry_goessi_walkthrough import advisor_user, api, session_factory  # noqa: F401

INTEREST_POSITIVE = [
    "Hypothekarzins", "Hypozins", "Hypo-Zins", "Zins Hypothek", "Schuldzins (Eigenheim)", "Schuldzins Eigenheim",
    "Eigenheimzins", "Hypothekarzinsen 2027",
]
AMORTIZATION_POSITIVE = [
    "Amortisation", "Amortisation Hypothek", "Hypothekaramortisation", "Amortisationszahlung (Hypothek)",
    "Amortisationszahlung Hypothek", "Hypothekartilgung", "Tilgung", "Amortization",
]
NEGATIVE = [
    "Mietzins Wohnung", "Mietzins", "Sparzins", "Zins Sparkonto", "Zinsertrag Festgeld", "Lebensmittel",
    "Krankenkasse", "Ferien", "Säule 3a Einzahlung", "Steuern", "Nebenkosten Eigenheim", "Unterhalt Liegenschaft",
    "Versicherung Hausrat", "Leasing Auto",
]


@pytest.mark.parametrize("label", INTEREST_POSITIVE)
def test_interest_compounds_are_recognised(label):
    assert _is_mortgage_interest_label(label), label


@pytest.mark.parametrize("label", AMORTIZATION_POSITIVE)
def test_amortization_compounds_are_recognised(label):
    assert _is_amortization_label(label), label


@pytest.mark.parametrize("label", NEGATIVE)
def test_normal_expenses_are_not_blocked(label):
    assert not _is_mortgage_interest_label(label), label
    assert not _is_amortization_label(label), label


def test_api_blocks_compounds_and_accepts_normal_expenses(api, advisor_user):
    client_id = _client(api, advisor_user)
    assert api.post(f"/clients/{client_id}/wealth-positions", json=_mortgage()).status_code == 201

    def post(label):
        return api.post(f"/clients/{client_id}/cashflows", json={
            "cashflow_type": "Expense", "label": label, "amount_rappen": 8_400_00,
            "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic",
        })

    for label in ("Hypozins", "Schuldzins (Eigenheim)", "Hypothekaramortisation", "Amortisationszahlung (Hypothek)"):
        resp = post(label)
        assert resp.status_code == 422, (label, resp.text[:200])
    for label in ("Mietzins Wohnung", "Nebenkosten Eigenheim", "Sparzins"):
        resp = post(label)
        assert resp.status_code == 201, (label, resp.text[:200])
