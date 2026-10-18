"""VORSORGE-PROJECTION-001 (2026-10-18), Teil Fortschreibung/Bezug/Doppelzaehlung.

Befund develop d3c9a67 (Reproducer mit Zahlen, siehe
test_linked_manual_inflow_is_transfer_neutral): eine BVG-Position CHF 300'000
("Anderes Vermoegen") zaehlt im Gesamtvermoegen fuer ALLE Jahre (MC-Total-Pfad
und external_goal_funding_series fuer Gesamtvermoegens-Ziele). Erfasst der
Berater zusaetzlich den Kapitalbezug als WealthInflow (300'000 im Bezugsjahr),
fliesst derselbe Betrag ein zweites Mal ein:

    Beratungsvermoegen 100'000 Liquiditaet, CMA = 0 %, Bezug Offset 2:
    develop Total-Pfad:  [400k, 400k, 400k, 700k, 700k, 700k]   (+300k aus dem Nichts)
    korrekt:             [400k, 400k, 400k, 400k, 400k, 400k]   (Umbuchung)

Fachentscheid (User, 2026-10-18): Vorsorge wird deterministisch nominal
fortgeschrieben (3a-/FZ-Konto 0 %, -Wertschriften 3 %, Police Rueckkaufswert ->
garantierter Ablaufwert, BVG erfasster Zins / 0 %) und beim Bezug GENAU EINMAL
freies Vermoegen. Ein mit der Position verknuepfter WealthInflow IST der
Bezug (automatischer Bezug entfaellt).
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401,E402 -- registriert alle Models
import services.portfolio_engine as pe  # noqa: E402
from test_external_direct_property_total_paths_contract import (  # noqa: E402
    _deterministic,
    _monte_carlo,
    _zero_cma,
)

START = 2026  # = start_year in _deterministic/_monte_carlo
H = 5


def _pension(**overrides):
    values = dict(
        id="p1", label="3a Konto", position_type="Vorsorge",
        assignment="Anderes Vermögen", current_value_rappen=100_000,
        currency="CHF", pension_type="Säule 3a", pension_vehicle=None,
        pension_interest_rate_bps=None, pension_maturity_value_rappen=None,
        pension_maturity_date=None, pension_retirement_age=None,
        pension_payout_form=None, liquidity_available_from=f"{START + 2}-06-30",
        alloc_equities_bps=0, alloc_bonds_bps=0, alloc_real_estate_bps=0,
        alloc_liquidity_bps=0, alloc_alternatives_bps=0,
        asset_expected_return_bps=0, property_rental_income_rappen=0,
        mortgage_amortization_rappen=0, mortgage_amortization_type=None,
        is_active=1, deleted_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _cash(value=100_000):
    return _pension(
        id="cash", label="Konto", position_type="Liquidität", pension_type=None,
        assignment="Beratungsvermögen", current_value_rappen=value,
        liquidity_available_from=None,
    )


def _inflow(**overrides):
    values = dict(
        id="i1", label="Kapitalbezug", source_type="Andere", amount_rappen=300_000,
        expected_year=START + 2, is_recurring=0, frequency=None, duration_years=None,
        value_mode="nominal", is_active=1, linked_position_id="p1", currency="CHF",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _mandate(**overrides):
    values = dict(
        tax_jurisdiction=None, tax_overrides_json=None, tax_estimate_in_cashflow_enabled=0,
        opened_at=f"{START}-01-01", client_birth_year=None, retirement_year=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _foundation(positions, inflows=(), mandate=None):
    return pe._build_external_foundation_projection(
        positions, horizon_years=H, wealth_inflows=list(inflows),
        start_year=START, mandate=mandate or _mandate(),
    )


def _projection(positions, inflows=(), mandate=None):
    return pe._external_pension_projection(
        positions, list(inflows), start_year=START, horizon_years=H,
        mandate=mandate or _mandate(),
    )


def _cashflows(positions, inflows=(), mandate=None):
    foundation = _foundation(positions, inflows, mandate)
    series = pe._wealth_inflow_series_rappen(list(inflows), H, START, [0] * H)
    return pe._with_pension_payouts(series, foundation), foundation


def _total_summary(positions):
    return pe._summarize_positions([p for p in positions if p.assignment != "Verbindlichkeit"])


# ---------------------------------------------------------------------------
# Fortschreibung je Vorsorgeart
# ---------------------------------------------------------------------------


def test_3a_konto_default_zero_rate_paid_out_once():
    foundation = _foundation([_pension()])
    assert foundation["pension_series_rappen"] == [100_000, 100_000, 100_000, 0, 0, 0]
    assert foundation["pension_payout_series_rappen"] == [0, 0, 100_000, 0, 0]


def test_3a_wertschriften_default_three_percent_nominal():
    foundation = _foundation([_pension(pension_vehicle="Wertschriften")])
    assert foundation["pension_series_rappen"] == [100_000, 103_000, 106_090, 0, 0, 0]
    # Bezug Offset 2 entnimmt den Wert, den die Position in Serie[3] haette
    assert foundation["pension_payout_series_rappen"] == [0, 0, 109_273, 0, 0]


def test_recorded_rate_overrides_default():
    foundation = _foundation([_pension(pension_vehicle="Wertschriften", pension_interest_rate_bps=100)])
    assert foundation["pension_series_rappen"][:3] == [100_000, 101_000, 102_010]


def test_freizuegigkeit_konto_uses_zero_default():
    foundation = _foundation([_pension(pension_type="Freizügigkeit")])
    assert foundation["pension_series_rappen"] == [100_000, 100_000, 100_000, 0, 0, 0]


def test_police_runs_from_surrender_to_guaranteed_maturity_value():
    police = _pension(
        pension_type="Säule 3b", pension_vehicle=None, current_value_rappen=50_000,
        pension_maturity_value_rappen=80_000, pension_maturity_date=f"{START + 3}-12-31",
        liquidity_available_from=None,
    )
    foundation = _foundation([police])
    series = foundation["pension_series_rappen"]
    assert series[0] == 50_000
    assert series[4] == 0 and series[5] == 0
    assert series[1] < series[2] < series[3] < 80_000
    # Faelligkeit START+3 -> Offset 3; Bezug = garantierter Ablaufwert, 3b steuerfrei
    assert foundation["pension_payout_series_rappen"] == [0, 0, 0, 80_000, 0]


def test_bvg_is_only_projected_no_automatic_payout():
    bvg = _pension(pension_type="BVG", pension_interest_rate_bps=125, current_value_rappen=300_000,
                   pension_payout_form="Kapital", pension_retirement_age=65,
                   liquidity_available_from=None)
    projection = _projection([bvg], mandate=_mandate(client_birth_year=START - 63))
    assert projection.series_rappen == [300_000, 303_750, 307_547, 311_391, 315_284, 319_225]
    assert projection.payout_series_rappen == [0] * H
    assert any("nur Fortschreibung" in note for note in projection.notes)


def test_payout_year_from_birth_year_and_retirement_age():
    pos = _pension(liquidity_available_from=None, pension_retirement_age=64)
    foundation = _foundation([pos], mandate=_mandate(client_birth_year=START + 1 - 64))
    assert foundation["pension_payout_series_rappen"] == [0, 100_000, 0, 0, 0]


def test_payout_year_falls_back_to_mandate_retirement_year():
    pos = _pension(liquidity_available_from=None)
    foundation = _foundation([pos], mandate=_mandate(retirement_year=START + 3))
    assert foundation["pension_payout_series_rappen"] == [0, 0, 0, 100_000, 0]


def test_without_payout_year_position_stays_bound_and_is_disclosed():
    pos = _pension(liquidity_available_from=None)
    projection = _projection([pos])
    assert projection.series_rappen == [100_000] * (H + 1)
    assert projection.payout_series_rappen == [0] * H
    assert any("kein Bezugsjahr" in note for note in projection.notes)


def test_no_pension_positions_keep_foundation_contract_unchanged():
    assert set(_foundation([_cash()])) == {
        "property_series_rappen", "liability_series_rappen", "pledged_asset_series_rappen",
    }


# ---------------------------------------------------------------------------
# Kapitalbezugssteuer
# ---------------------------------------------------------------------------


def test_lumpsum_tax_applied_with_tax_domicile():
    foundation = _foundation([_pension()], mandate=_mandate(tax_jurisdiction="CH"))
    # CH-Regime pauschal 600 bps -> 6'000 Steuer auf 100'000
    assert foundation["pension_payout_series_rappen"] == [0, 0, 94_000, 0, 0]


def test_lumpsum_tax_missing_domicile_is_disclosed():
    projection = _projection([_pension()])
    assert any("Kapitalbezugssteuer" in n and "kein Steuerdomizil" in n for n in projection.notes)


def test_3b_police_payout_not_lumpsum_taxed():
    police = _pension(pension_type="Säule 3b", current_value_rappen=50_000,
                      pension_maturity_value_rappen=60_000,
                      pension_maturity_date=f"{START + 1}-01-01", liquidity_available_from=None)
    foundation = _foundation([police], mandate=_mandate(tax_jurisdiction="CH"))
    assert foundation["pension_payout_series_rappen"] == [0, 60_000, 0, 0, 0]


# ---------------------------------------------------------------------------
# Doppelzaehlung: verknuepfter Zufluss IST der Bezug
# ---------------------------------------------------------------------------


def test_linked_manual_inflow_is_transfer_neutral():
    bvg = _pension(pension_type="BVG", current_value_rappen=300_000, liquidity_available_from=None)
    positions = [_cash(), bvg]
    inflows = [_inflow()]
    cashflows, foundation = _cashflows(positions, inflows)
    result = _deterministic(
        cma=_zero_cma(), cashflows=cashflows,
        total_summary=_total_summary(positions), foundation=foundation,
    )
    # develop: [400k, 400k, 400k, 700k, 700k, 700k]
    assert result["total_mix_current_series_rappen"] == [400_000] * 6
    assert result["total_mix_target_series_rappen"] == [400_000] * 6


def test_linked_manual_inflow_suppresses_automatic_payout():
    pos = _pension()  # automatischer Bezug waere START+2
    inflows = [_inflow(amount_rappen=95_000, expected_year=START + 1)]
    foundation = _foundation([pos], inflows)
    assert foundation["pension_payout_series_rappen"] == [0] * H
    assert foundation["pension_series_rappen"] == [100_000, 100_000, 0, 0, 0, 0]


def test_automatic_payout_counts_exactly_once_in_total_and_advisory_paths():
    positions = [_cash(), _pension()]
    cashflows, foundation = _cashflows(positions)
    result = _deterministic(
        cma=_zero_cma(), cashflows=cashflows,
        total_summary=_total_summary(positions), foundation=foundation,
    )
    assert result["total_mix_current_series_rappen"] == [200_000] * 6
    assert cashflows == [0, 0, 100_000, 0, 0]  # freies Vermoegen erst ab Bezug


def test_tax_reduces_total_wealth_by_exactly_the_tax():
    positions = [_cash(), _pension()]
    cashflows, foundation = _cashflows(positions, mandate=_mandate(tax_jurisdiction="CH"))
    result = _deterministic(
        cma=_zero_cma(), cashflows=cashflows,
        total_summary=_total_summary(positions), foundation=foundation,
    )
    assert result["total_mix_current_series_rappen"] == [200_000] * 3 + [194_000] * 3


def test_unlinked_payout_like_inflow_in_payout_year_is_flagged():
    inflows = [_inflow(linked_position_id=None, source_type="Saeule3b", label="3a Auszahlung")]
    projection = _projection([_pension()], inflows)
    assert any("Möglicher Doppelbezug" in note for note in projection.notes)


def test_unrelated_unlinked_inflow_is_not_flagged():
    inflows = [_inflow(linked_position_id=None, source_type="Erbschaft", label="Erbe Tante")]
    projection = _projection([_pension()], inflows)
    assert not any("Doppelbezug" in note for note in projection.notes)


def test_monte_carlo_total_paths_follow_deterministic_pension(monkeypatch):
    cma = _zero_cma()
    cma.bonds_chf_ig_vol_bps = 500
    cma.equity_ch_vol_bps = 1500
    positions = [_cash(), _pension(pension_vehicle="Wertschriften")]
    cashflows, foundation = _cashflows(positions)
    result = _monte_carlo(
        monkeypatch=monkeypatch, cma=cma, cashflows=cashflows,
        total_summary=_total_summary(positions), foundation=foundation,
    )
    expected = [200_000, 203_000, 206_090, 209_273, 209_273, 209_273]
    for prefix in ("total_current", "total_target"):
        assert result[f"{prefix}_p10_series_rappen"] == expected, prefix
        assert result[f"{prefix}_p90_series_rappen"] == expected, prefix


def test_external_goal_funding_series_uses_pension_series_not_cpi():
    positions = [_cash(), _pension(pension_type="BVG", current_value_rappen=300_000,
                                   liquidity_available_from=None)]
    series = pe._build_external_goal_funding_series(
        external_gross_assets_rappen=300_000,
        external_foundation_projection=_foundation(positions, [_inflow()]),
        inflation_series_bps=[100] * H,
        horizon_years=H,
    )
    # develop: 300k mit CPI fuer alle Jahre -> neben dem Zufluss doppelt
    assert series == [300_000, 300_000, 300_000, 0, 0, 0]


# ---------------------------------------------------------------------------
# End-to-End: _load_allocation_inputs gegen SQLite
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401


def test_load_allocation_inputs_books_automatic_payout(session_factory):  # noqa: F811
    from models.mandates import Mandate
    from models.wealth import WealthPosition

    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"vor-proj-{uuid.uuid4().hex[:8]}",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)
        start_year = baseline["cashflow_totals"]["year"]
        session.add(WealthPosition(
            id=f"pos-3a-{uuid.uuid4().hex[:8]}", client_id=client_id, label="3a Konto",
            position_type="Vorsorge", assignment="Anderes Vermögen",
            current_value_rappen=80_000_00, currency="CHF", pension_type="Säule 3a",
            liquidity_available_from=f"{start_year + 3}-03-31",
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        session.flush()
        inputs = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    assert inputs["total_summary"].pension_bound_rappen == 80_000_00
    pension = inputs["external_foundation_projection"]["pension_series_rappen"]
    assert pension[:4] == [80_000_00] * 4 and set(pension[4:]) <= {0}
    delta = [
        a - b for a, b in zip(
            inputs["inflow_projection_series_rappen"], baseline["inflow_projection_series_rappen"],
        )
    ]
    from services import portfolio_engine_pension_positions as pp

    expected_tax = 0
    if str(getattr(mandate, "tax_jurisdiction", "") or "").strip():
        expected_tax = pp.mandate_lumpsum_tax(mandate)(80_000_00, start_year + 3, 3)
    assert delta[3] == 80_000_00 - expected_tax
    assert sum(delta) == delta[3]
    assert any("3a Konto" in note for note in inputs["total_summary"].assumption_notes)
