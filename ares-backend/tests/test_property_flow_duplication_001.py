"""PROPERTY-FLOW-DUPLICATION-001 (Audit 2026-09-14, User-Entscheid 2026-09-16:
"Bestehenden Blocker symmetrisch erweitern"):

Der bestehende B3-Guard (services/routers/wealth.py) blockierte nur einen
manuellen Tilgungs-Cashflow, wenn beim SCHREIBEN bereits eine aktive Hypothek
existierte. Drei Luecken blieben:

1. Ein manueller Hypothekarzins-Cashflow war UNGEBLOCKT erlaubt, obwohl
   derive_wealth_cashflows() denselben Zins laengst automatisch aus jeder
   aktiven Hypothek ableitet -- Doppelzaehlung.
2. Ein manueller Mietertrags-Cashflow war UNGEBLOCKT erlaubt, obwohl
   derive_wealth_cashflows() dieselbe Miete laengst automatisch aus jeder
   aktiven Immobilie (Wert > 0) ableitet -- Doppelzaehlung.
3. Die Pruefung lief nur in EINER Richtung (Cashflow-Write gegen bestehende
   Position). Ein zuerst angelegter manueller Cashflow, gefolgt von der
   passenden Hypothek/Immobilie, wurde nicht erkannt (Audit-Repro 3: erst
   10'000 manuelle Tilgung, dann Hypothek angelegt -> 20'000 statt 10'000).

Dieses Modul testet alle drei Luecken. Es importiert die Test-Infrastruktur
aus test_audit_b3_mortgage_amortization.py, um dieselbe Fixture-Basis
(auth_client, session_factory, advisor, _make_client_with_mortgage) nicht zu
duplizieren.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.clients import Client
from models.users import User
from models.wealth import WealthPosition
from test_audit_b3_mortgage_amortization import (  # noqa: F401
    _make_client_with_mortgage,
    _make_client_without_mortgage,
    _now,
    advisor,
    auth_client,
    session_factory,
)


def _make_client_with_rental_property(session_factory, advisor) -> str:
    cid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id,
                     created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"prop-{cid[:6]}", client_id=cid,
            label="Renditeliegenschaft", position_type="Immobilien",
            assignment="Anderes Vermögen",
            current_value_rappen=800_000_00, currency="CHF",
            property_usage="Renditeobjekt",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


# ============================================================================
# Luecke 1: manueller Hypothekarzins wird jetzt blockiert (siehe auch
# test_b3_create_zinsen_with_mortgage_blocked in test_audit_b3_...)
# ============================================================================


@pytest.mark.parametrize("label", [
    "Hypothekarzins",
    "Zins Hypothek UBS",
    "Hypothek-Zinsen 2026",
])
def test_various_mortgage_interest_labels_blocked_with_active_mortgage(
    auth_client, session_factory, advisor, label
):
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": label,
            "amount_rappen": 9_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 422, f"Label {label!r} sollte blockiert sein: {resp.text}"


def test_mortgage_interest_label_allowed_without_active_mortgage(
    auth_client, session_factory, advisor
):
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothekarzins",
            "amount_rappen": 9_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 201, resp.text


# ============================================================================
# Luecke 2: manueller Mietertrag wird jetzt blockiert
# ============================================================================


@pytest.mark.parametrize("label", [
    "Mieteinnahmen",
    "Miete Renditeliegenschaft",
    "Mietertrag 2026",
])
def test_various_rental_income_labels_blocked_with_active_property(
    auth_client, session_factory, advisor, label
):
    cid = _make_client_with_rental_property(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": label,
            "amount_rappen": 24_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 422, f"Label {label!r} sollte blockiert sein: {resp.text}"


def test_rental_income_label_allowed_without_active_property(
    auth_client, session_factory, advisor
):
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Mieteinnahmen",
            "amount_rappen": 24_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 201, resp.text


# ============================================================================
# Luecke 3: Gegenrichtung -- Position wird NACH dem manuellen Cashflow
# angelegt (Audit-Repro 3)
# ============================================================================


def test_creating_mortgage_after_manual_amortization_cashflow_is_blocked(
    auth_client, session_factory, advisor
):
    """Audit-Repro 3: erst manueller Tilgungsflow (10'000), dann Hypothek
    angelegt -> vorher 20'000 (Doppelzaehlung), jetzt 422 beim Anlegen der
    Hypothek."""
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp_cf = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothek-Tilgung",
            "amount_rappen": 10_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp_cf.status_code == 201, resp_cf.text

    resp_wp = auth_client.post(
        f"/clients/{cid}/wealth-positions",
        json={
            "label": "Hypothek Eigenheim",
            "position_type": "Hypothek",
            "assignment": "Verbindlichkeit",
            "current_value_rappen": 600_000_00,
            "mortgage_bank": "UBS",
            "mortgage_type": "Festhypothek",
        },
    )
    assert resp_wp.status_code == 422, resp_wp.text
    assert "Tilgung" in resp_wp.text


def test_creating_mortgage_after_manual_interest_cashflow_is_blocked(
    auth_client, session_factory, advisor
):
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp_cf = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothekarzins",
            "amount_rappen": 9_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp_cf.status_code == 201, resp_cf.text

    resp_wp = auth_client.post(
        f"/clients/{cid}/wealth-positions",
        json={
            "label": "Hypothek Eigenheim",
            "position_type": "Hypothek",
            "assignment": "Verbindlichkeit",
            "current_value_rappen": 600_000_00,
            "mortgage_bank": "UBS",
            "mortgage_type": "Festhypothek",
        },
    )
    assert resp_wp.status_code == 422, resp_wp.text


def test_creating_property_after_manual_rental_income_cashflow_is_blocked(
    auth_client, session_factory, advisor
):
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp_cf = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Mieteinnahmen",
            "amount_rappen": 24_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp_cf.status_code == 201, resp_cf.text

    resp_wp = auth_client.post(
        f"/clients/{cid}/wealth-positions",
        json={
            "label": "Renditeliegenschaft",
            "position_type": "Immobilien",
            "assignment": "Anderes Vermögen",
            "current_value_rappen": 800_000_00,
            "property_usage": "Renditeobjekt",
        },
    )
    assert resp_wp.status_code == 422, resp_wp.text


def test_creating_mortgage_without_any_manual_flow_still_allowed(
    auth_client, session_factory, advisor
):
    """Regressionsschutz: das haeufige Standard-Szenario (Hypothek anlegen
    ohne vorherigen manuellen Cashflow) bleibt unveraendert erlaubt."""
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp_wp = auth_client.post(
        f"/clients/{cid}/wealth-positions",
        json={
            "label": "Hypothek Eigenheim",
            "position_type": "Hypothek",
            "assignment": "Verbindlichkeit",
            "current_value_rappen": 600_000_00,
            "mortgage_bank": "UBS",
            "mortgage_type": "Festhypothek",
        },
    )
    assert resp_wp.status_code == 201, resp_wp.text


def test_creating_property_with_zero_value_ignores_conflicting_manual_rent(
    auth_client, session_factory, advisor
):
    """Regressionsschutz: derive_wealth_cashflows() leitet Miete nur bei
    Wert > 0 ab (siehe rental_income-Docstring) -- eine neu angelegte
    Immobilie mit Wert 0 darf deshalb nicht blockiert werden, auch wenn ein
    manueller Miet-Cashflow existiert."""
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp_cf = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Mieteinnahmen",
            "amount_rappen": 24_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp_cf.status_code == 201, resp_cf.text

    resp_wp = auth_client.post(
        f"/clients/{cid}/wealth-positions",
        json={
            "label": "Bauland (noch kein Wert erfasst)",
            "position_type": "Immobilien",
            "assignment": "Anderes Vermögen",
            "current_value_rappen": 0,
        },
    )
    assert resp_wp.status_code == 201, resp_wp.text
