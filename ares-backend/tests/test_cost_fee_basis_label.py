"""FIDLEG: Gebührenbasis-Label muss die tatsaechlich verwendete Basis widerspiegeln.

Faellt das echte Beratungsvermoegen weg (advisory_wealth_rappen<=0), wird als
Naeherung das investierte Produktvolumen als Basis genutzt. Dann darf die Basis
NICHT als "Beratungsvermoegen" ausgewiesen werden (irrefuehrend; bei nicht
investiertem Barvermoegen sonst zu tiefe Jahresgebuehr).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cost_disclosure import calculate_cost_disclosure

_POSITIONS = [{"amount_rappen": 50_000_000, "ter_bps": 20}]
_FEE = {"default_advisory_fee_bps": 75}


def _annual_service_items(data):
    return [
        i for i in data["cost_items"]
        if i.get("frequency") == "jährlich" and i.get("category") == "Dienstleistungskosten"
    ]


def test_basis_label_beratungsvermoegen_when_provided():
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    items = _annual_service_items(data)
    assert items, "keine jaehrliche Dienstleistungskosten-Position"
    assert all(i["basis_label"] == "Beratungsvermögen" for i in items)


def test_basis_label_produktvolumen_when_advisory_wealth_missing():
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=0, positions=_POSITIONS, fee_model=_FEE,
    )
    items = _annual_service_items(data)
    assert items
    assert all(i["basis_label"] == "Empfohlenes Produktvolumen" for i in items)
    assert any("Produktvolumen" in w for w in data["warnings"])
    # Basis-Betrag ist das investierte Volumen (Fallback), nicht 0.
    assert all(i["basis_rappen"] == 50_000_000 for i in items)
