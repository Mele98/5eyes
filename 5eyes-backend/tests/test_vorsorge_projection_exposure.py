"""VORSORGE-PROJECTION-001 (2026-10-18), Teil Exposure/Darstellung.

Befund (develop d3c9a67): ``_default_weights_for_position`` ordnete jede
Vorsorge-Position pauschal 45 % Aktien / 45 % Obligationen / 10 % Liquiditaet
zu. Ueber ``_summarize_positions`` -> ``total_summary`` floss das in
``_apply_external_exposure_tilts`` und in die Gesamtvermoegens-Darstellung.
Ein Saeule-3a-Konto (Zins, kein Aktienrisiko) zaehlte so zu 45 % als Aktie.

Fachentscheid (User, 2026-10-18): Vorsorgegelder werden nicht verwaltet und
nicht auf Anlageklassen geraten. Externe Vorsorge ist eine eigene Kategorie
"Vorsorge (gebunden)", ausserhalb der Exposure-Tilts -- ausser der Berater
erfasst bewusst eine vollstaendige Aufteilung.

Reproducer mit Zahlen (test_tilt_ignores_unsplit_pension):
Beratungsdepot 60'000 Aktien + 40'000 Liquiditaet, Saeule-3a-Konto 100'000.
  develop: Aktien-Exposure (60k + 45k) / 200k = 52.5 % -> Reduktion 50 bps
           (das 3a-Konto wird als 45k Aktien angerechnet und verduennt zugleich)
  neu:     Aktien-Exposure 60k / 100k = 60.0 % -> Reduktion 200 bps
           (Vorsorge weder im Zaehler noch im Nenner)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401,E402 -- registriert alle Models
import services.portfolio_engine as pe  # noqa: E402
from services.portfolio_engine import BUCKET_FIELDS  # noqa: E402
from services.portfolio_engine_gesamtvermoegen import _build_total_wealth_allocation  # noqa: E402
from services.portfolio_engine_house_matrix import _apply_external_exposure_tilts  # noqa: E402


def _pos(**overrides):
    values = dict(
        id="pos", label="Position", position_type="Vorsorge",
        assignment="Anderes Vermögen", current_value_rappen=100_000_00,
        currency="CHF", pension_type="Säule 3a",
        alloc_equities_bps=0, alloc_bonds_bps=0, alloc_real_estate_bps=0,
        alloc_liquidity_bps=0, alloc_alternatives_bps=0,
        is_active=1, deleted_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _depot(equities_bps, value, **overrides):
    return _pos(
        id=overrides.pop("id", "depot"), position_type="Depot",
        assignment="Beratungsvermögen", pension_type=None,
        current_value_rappen=value, alloc_equities_bps=equities_bps,
        alloc_liquidity_bps=10000 - equities_bps, **overrides,
    )


def _tilt(summary):
    targets = {"equities": 5000, "bonds": 3000, "real_estate": 500, "alternatives": 500, "liquidity": 1000}
    reasoning: list[str] = []
    _apply_external_exposure_tilts(
        targets, {k: 0 for k in BUCKET_FIELDS}, {k: 10000 for k in BUCKET_FIELDS},
        summary, SimpleNamespace(equity_minimum_bps=0), False, reasoning,
    )
    return targets, reasoning


# ---------------------------------------------------------------------------
# total_summary: eigene Kategorie statt geratener Anlageklassen
# ---------------------------------------------------------------------------


def test_external_pension_is_bound_not_distributed():
    for pension_type in ("BVG", "Säule 3a", "Freizügigkeit", "Säule 3b", "Lebensversicherung", None):
        summary = pe._summarize_positions([_pos(pension_type=pension_type)])
        assert summary.amounts_rappen == {k: 0 for k in BUCKET_FIELDS}, pension_type
        assert summary.pension_bound_rappen == 100_000_00
        assert summary.total_rappen == 100_000_00  # Gesamtvermoegen bleibt vollstaendig


def test_recorded_split_counts_as_exposure_but_stays_bound():
    pos = _pos(alloc_equities_bps=8000, alloc_bonds_bps=2000)
    summary = pe._summarize_positions([pos])
    assert summary.amounts_rappen == {k: 0 for k in BUCKET_FIELDS}
    assert summary.pension_bound_rappen == 100_000_00
    assert summary.pension_exposure_amounts_rappen["equities"] == 80_000_00
    assert summary.pension_exposure_amounts_rappen["bonds"] == 20_000_00


def test_advisory_pension_position_keeps_bucket_mapping():
    """Vorsorge im BERATUNGSvermoegen (vom Berater bewusst als verwaltet
    erfasst) bleibt im Bucket-Modell -- dieser PR aendert nur externe
    Vorsorge."""
    advisory = _pos(assignment="Beratungsvermögen")
    summary = pe._summarize_positions([advisory])
    assert summary.pension_bound_rappen == 0
    assert summary.amounts_rappen["equities"] == 45_000_00


# ---------------------------------------------------------------------------
# Exposure-Tilt (Reproducer mit Zahlen)
# ---------------------------------------------------------------------------


def test_tilt_ignores_unsplit_pension():
    summary = pe._summarize_positions([_depot(6000, 100_000_00), _pos(id="3a")])
    targets, _ = _tilt(summary)
    # develop: 4950 (52.5 % Schein-Exposure inkl. 45k "Aktien" aus dem 3a-Konto)
    assert targets["equities"] == 4800
    assert targets["bonds"] == 3200


def test_tilt_ignores_pension_for_real_estate_share_too():
    house = _pos(id="house", position_type="Immobilien", pension_type=None,
                 current_value_rappen=400_000_00)
    cash = _pos(id="cash", position_type="Liquidität", pension_type=None,
                assignment="Beratungsvermögen", current_value_rappen=600_000_00)
    bvg = _pos(id="bvg", pension_type="BVG", current_value_rappen=1_000_000_00)
    targets, _ = _tilt(pe._summarize_positions([house, cash, bvg]))
    # Immobilienanteil 40 % des nicht-gebundenen Vermoegens -> -250 bps
    # (develop: 20 %, weil die BVG den Nenner verdoppelte -> kein Tilt)
    assert targets["real_estate"] == 250


def test_tilt_counts_recorded_pension_split():
    summary = pe._summarize_positions([
        _depot(6000, 100_000_00), _pos(id="3a", alloc_equities_bps=10000),
    ])
    targets, _ = _tilt(summary)
    # (60k + 100k) / 200k = 80 % -> min(400, 600) = 400
    assert targets["equities"] == 4600


def test_projection_notes_are_disclosed_in_reasoning():
    summary = pe._summarize_positions([_pos()])
    summary.assumption_notes = ("Vorsorge 'X' (Säule 3a, Konto): gebunden.",)
    _targets, reasoning = _tilt(summary)
    assert "Vorsorge 'X' (Säule 3a, Konto): gebunden." in reasoning


# ---------------------------------------------------------------------------
# Gesamtvermoegens-Darstellung: fixer Block, Summen konsistent
# ---------------------------------------------------------------------------


def test_total_allocation_shows_pension_as_fixed_block():
    positions = [_depot(6000, 100_000_00), _pos(id="3a", current_value_rappen=50_000_00)]
    summary = pe._summarize_positions(positions)
    payload = _build_total_wealth_allocation(
        summary, 0, summary.total_rappen,
        {"equities": 5000, "bonds": 5000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        direct_property_rappen=0,
    )
    rows = {row["asset_class"]: row for row in payload["allocation"]}
    pension = rows["Vorsorge (gebunden)"]
    assert pension["current_amount_rappen"] == 50_000_00
    assert pension["target_amount_rappen"] == 50_000_00  # nie umgeschichtet
    assert pension["is_pension_bound"] is True
    assert payload["financial_base_rappen"] == 100_000_00
    assert sum(r["current_amount_rappen"] for r in payload["allocation"]) == 150_000_00
    assert sum(r["target_amount_rappen"] for r in payload["allocation"]) == 150_000_00
    assert sum(r["current_weight_bps"] for r in payload["allocation"]) == 10000
    assert sum(r["target_weight_bps"] for r in payload["allocation"]) == 10000
    assert rows["Aktien"]["target_amount_rappen"] == 50_000_00


def test_total_allocation_without_pension_is_unchanged():
    summary = pe._summarize_positions([_depot(6000, 100_000_00)])
    payload = _build_total_wealth_allocation(
        summary, 0, summary.total_rappen,
        {"equities": 5000, "bonds": 5000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        direct_property_rappen=0,
    )
    assert len(payload["allocation"]) == 5
    assert "pension_bound_rappen" not in payload
