"""MANUAL-SAVE-REQUIRES-BASIS-001: Test-Hilfe fuer den manuellen POST
/mandates/{id}/target-allocation.

Seit dem CIO-Entscheid gilt fuer das manuelle Speichern dieselbe
Datenbasis-Regel wie fuer Generate (_assert_allocation_has_basis): ohne
Beratungsvermoegen und ohne Cashflows -> 409. Tests, die den Speicherpfad
selbst pruefen, brauchen deshalb eine minimale Vermoegensbasis.
"""
from __future__ import annotations

import uuid

from models.wealth import WealthPosition

NOW = "2026-10-16T00:00:00.000Z"


def seed_advisory_basis(session, client_id: str, value_rappen: int = 500_000_00) -> None:
    session.add(WealthPosition(
        id=f"pos-basis-{uuid.uuid4().hex[:12]}", client_id=client_id,
        label="Depot", position_type="Depot", assignment="Beratungsvermögen",
        current_value_rappen=value_rappen, currency="CHF",
        alloc_equities_bps=4000, alloc_bonds_bps=3000,
        alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
        alloc_alternatives_bps=1000,
        is_active=1, created_at=NOW, updated_at=NOW,
    ))
    session.commit()
