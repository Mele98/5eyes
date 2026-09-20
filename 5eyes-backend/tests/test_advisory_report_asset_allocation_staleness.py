"""Kontrollrunde 2026-09-20 (Depot-Check-Audit, direkte Folge von
SUITABILITY-ALLOCATION-STALENESS-001 vom selben Tag).

_check_asset_allocation (Sektion 7 Ampel) und _build_asset_allocation
(Sektion 8 IST/SOLL-Tabelle) mussten auf compute_depot_check's neuen
target_allocation_stale-Flag reagieren -- sonst konnte Sektion 7 "gruen,
alles in Ordnung" zeigen, waehrend Sektion 19 (Compliance-Audit) dasselbe
Mandat bereits als non-compliant auswies.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.advisory_report import _build_asset_allocation, _check_asset_allocation


def _dc(*, target_allocation_stale: bool, in_band: bool = True) -> dict:
    return {
        "target_allocation_stale": target_allocation_stale,
        "buckets": {
            "equities": {
                "label": "Aktien", "ist_bps": 5000, "soll_bps": 5000,
                "band_min_bps": 4500, "band_max_bps": 5500,
                "in_band": in_band,
            },
        },
    }


def test_check_asset_allocation_green_when_in_band_and_not_stale():
    result = _check_asset_allocation(_dc(target_allocation_stale=False), MagicMock())
    assert result["bewertung"] == "gruen"


def test_check_asset_allocation_not_assessable_when_stale_even_if_in_band():
    """Kernfall: alle Buckets in_band=True, aber die zugrunde liegende
    TargetAllocation ist veraltet -- darf NICHT 'gruen' zeigen."""
    result = _check_asset_allocation(_dc(target_allocation_stale=True, in_band=True), MagicMock())
    assert result["bewertung"] != "gruen"
    assert result["bewertung"] == "nicht_beurteilbar"
    assert "Risikoprofil" in result["beurteilung"]


def test_build_asset_allocation_surfaces_stale_flag_and_note():
    result = _build_asset_allocation(_dc(target_allocation_stale=True))
    assert result["target_allocation_stale"] is True
    assert "frueheren" in result["anmerkungen"] or "Risikoprofil" in result["anmerkungen"]


def test_build_asset_allocation_no_note_when_not_stale():
    result = _build_asset_allocation(_dc(target_allocation_stale=False))
    assert result["target_allocation_stale"] is False


def test_build_asset_allocation_stale_note_survives_advisor_override():
    """Der Staleness-Hinweis darf nicht durch eine vom Berater gepflegte
    Anmerkung verdeckt werden."""
    notes = MagicMock()
    notes.aa_anmerkungen = "Alles nach Plan."
    result = _build_asset_allocation(_dc(target_allocation_stale=True), notes=notes)
    assert "Risikoprofil" in result["anmerkungen"]
    assert "Alles nach Plan." in result["anmerkungen"]
