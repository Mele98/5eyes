"""ERASE-01 (Audit-Finding, 2026-10-07): DSG Art. 32 Erasure uebersah
client_nationalities.

services/client_erasure.py::erase_client_personal_data redigierte bisher
clients, client_opt_history, mandates, wealth_positions, cashflows,
wealth_inflows, goals, planning_assumptions, contract_documents und den
Kundenportal-Login -- aber NIE client_nationalities (country_code). Der
bestehende Seed in tests/test_client_erasure.py::_seed_full_client_chain
legt bereits eine Zeile ('nat-e1', country_code='CH') an, ohne sie jemals
zu pruefen -- dieses File schliesst genau diese Luecke mit einer
dedizierten, fokussierten Assertion.

Wiederverwendet exakt dieselben Fixtures/Helper wie test_client_erasure.py
(admin_client, session_factory, _seed_full_client_chain, _scalar), analog
zum etablierten Re-Use-Muster in test_client_creation_race_condition.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from test_client_erasure import (  # noqa: F401
    admin_client,
    session_factory,
    _scalar,
    _seed_full_client_chain,
)
from services.client_erasure import REDACTION_MARKER


def test_erase_client_redacts_nationality_country_code(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        # Vorbedingung: der Seed legt eine Nationalitaet mit country_code='CH' an.
        assert _scalar(session, "SELECT country_code FROM client_nationalities WHERE id='nat-e1'") == "CH"

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text

    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT country_code, is_primary, created_at FROM client_nationalities WHERE id='nat-e1'"
            )
        ).one()
        # country_code ist NOT NULL (models/clients.py) -- die Erasure setzt
        # deshalb den festen Redaction-Marker statt NULL (wie bei anderen
        # direkt identifizierenden String-Spalten, z.B. mandates.depot_bank).
        assert row.country_code == REDACTION_MARKER
        # is_primary/created_at tragen kein Re-Identifikationsrisiko und bleiben
        # unveraendert erhalten -- analog zum Umgang mit Boolean-/Datumsfeldern
        # auf client_due_diligence/client_tax_residencies.
        assert row.is_primary == 1
        assert row.created_at is not None


def test_erase_client_nationalities_redaction_counted_in_summary(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)

    response = admin_client.post(
        f"/clients/{ids['client_id']}/erase",
        json={"reason": "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["redacted"].get("client_nationalities") == 1
