"""AUDIT-2026-11 A3: der Kurzfrist-Tilt fuer Vermoegensziele bis 5 Jahre war
ab Score 7 wirkungslos.

Befund (Audit 01, Asset Allocation): Der Fix vom 2026-08-03 (Commit
"manuelle Bandbreiten-Restriktionen ueberleben Tilts") begrenzte die
Aktien-Reduktion auf ``min(eq_reduction, 2*liquidity_room, 2*bonds_room)``,
damit kein Empfaenger seine (ggf. vom Berater gesetzte) Obergrenze
ueberschreitet. In den Zeilen Wachstum/Dynamisch/Aktien ist das
Liquiditaets-Ziel gleich dem Liquiditaets-Max, also liquidity_room = 0 und
damit Reduktion 0 -- ohne Reasoning-Satz.

Gemessen vor dem Fix (Testmandat Score 8, Hausmatrix-Modus): Vermoegensziel
in 4.9 Jahren -> 6800/1600/800/600/200, identisch zu 6 oder 10 Jahren.

Fix nach dem Sinn des 2026-08-03-Fixes: Grenzen bleiben unverletzt, der
Anteil, den ein Empfaenger nicht aufnehmen kann, geht an den anderen.
Ist kein Raum vorhanden, erscheint ein Hinweis statt stiller Wirkungslosigkeit.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.wealth import Goal  # noqa: E402
from services.portfolio_engine_house_matrix import _apply_goal_and_reserve_tilts  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

HOUSE_TARGETS = {"equities": 6800, "bonds": 1600, "real_estate": 800, "alternatives": 600, "liquidity": 200}
HOUSE_MIN = {"equities": 6000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 0}
HOUSE_MAX = {"equities": 7500, "bonds": 2500, "real_estate": 2000, "alternatives": 1000, "liquidity": 200}


def _short_goal(years: float = 4.9):
    return SimpleNamespace(
        goal_type="Vermoegensziel", label="Kurzfristig", hardness="Primär",
        target_date=(date.today() + timedelta(days=int(365.25 * years))).isoformat(),
        start_date=None, horizon_years=None, target_return_bps=None,
        target_wealth_rappen=100_000_00, target_amount_rappen=None,
        is_ongoing=0, frequency=None, value_mode="nominal", rank=1,
    )


def _tilt(targets, minimums, maximums, goals, locked=()):
    reasoning: list[str] = []
    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums, goals=goals,
        limits_prefs={}, asset_class_prefs={}, recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 10,
        advisory_wealth_rappen=0, reasoning=reasoning, locked_buckets=locked,
    )
    return reasoning


def test_short_horizon_tilt_routes_to_bonds_when_liquidity_is_full():
    targets = dict(HOUSE_TARGETS)
    reasoning = _tilt(targets, HOUSE_MIN, HOUSE_MAX, [_short_goal()])
    assert targets["equities"] == 6600
    assert targets["bonds"] == 1800
    assert targets["liquidity"] == 200  # Liquiditaets-Max nicht verletzt
    assert sum(targets.values()) == 10000
    assert any("kurzem Horizont reduziert" in line for line in reasoning)


def test_short_horizon_tilt_keeps_half_split_when_both_have_room():
    targets = {**HOUSE_TARGETS, "liquidity": 100, "bonds": 1700}
    maximums = {**HOUSE_MAX, "liquidity": 500}
    _tilt(targets, HOUSE_MIN, maximums, [_short_goal()])
    assert (targets["equities"], targets["bonds"], targets["liquidity"]) == (6600, 1800, 200)


def test_short_horizon_tilt_respects_manual_bond_max_and_discloses_no_room():
    """Berater-Maximum Obligationen 16 %: keine Verletzung, sichtbarer Hinweis."""
    targets = dict(HOUSE_TARGETS)
    maximums = {**HOUSE_MAX, "bonds": 1600}
    reasoning = _tilt(targets, HOUSE_MIN, maximums, [_short_goal()])
    assert targets == HOUSE_TARGETS
    assert any("Obergrenze" in line and "Kurzfristig" in line for line in reasoning), reasoning


def test_short_horizon_tilt_partial_room_goes_to_bonds_up_to_its_max():
    targets = dict(HOUSE_TARGETS)
    maximums = {**HOUSE_MAX, "bonds": 1650}
    _tilt(targets, HOUSE_MIN, maximums, [_short_goal()])
    assert (targets["equities"], targets["bonds"], targets["liquidity"]) == (6750, 1650, 200)


def test_short_horizon_tilt_is_effective_in_generate_house_matrix_mode(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="a3hm")
    short_date = (date.today() + timedelta(days=int(365.25 * 4.9))).isoformat()
    with session_factory() as s:
        goal = s.query(Goal).filter(Goal.mandate_id == mid, Goal.goal_type == "Vermoegensziel").one()
        goal.target_date = short_date
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, None)
        s.commit()
    ta = result["target_allocation"]
    assert ta.target_equities_bps == 6600, ta.target_equities_bps
    assert ta.target_bonds_bps == 1800
    assert ta.target_liquidity_bps == 200


# --------------------------------------------------------------------------
# H-859-6 (Pruefrunde #859): Wegfall der Ziel-Tilts bei fixierter Klasse
# wird ausgewiesen; der A3-Satz nennt den tatsaechlichen Grund.
# --------------------------------------------------------------------------


def test_short_horizon_tilt_skipped_for_locked_equities_is_explained():
    targets = {**HOUSE_TARGETS, "equities": 7000, "bonds": 1400}
    reasoning = _tilt(targets, HOUSE_MIN, HOUSE_MAX, [_short_goal()], locked={"equities"})
    assert targets["equities"] == 7000
    assert any("Aktienquote ist als Berater-Ziel fixiert, der Tilt entfaellt" in r for r in reasoning), reasoning


def test_short_horizon_no_room_names_locked_vs_full_receiver():
    targets = dict(HOUSE_TARGETS)
    reasoning = _tilt(targets, HOUSE_MIN, HOUSE_MAX, [_short_goal()], locked={"bonds"})
    assert targets == HOUSE_TARGETS
    line = [r for r in reasoning if "Kurzfristig" in r]
    assert line and "Obligationen als Berater-Ziel fixiert" in line[0] and "Liquiditaet an der Obergrenze" in line[0], reasoning


def test_return_goal_tilt_skipped_for_locked_equities_is_explained():
    goal = SimpleNamespace(
        goal_type="Renditeziel", label="Rendite", hardness="Primär", target_return_bps=500,
        target_date=None, start_date=None, horizon_years=10, target_wealth_rappen=None,
        target_amount_rappen=None, is_ongoing=0, frequency=None, value_mode="nominal", rank=1,
    )
    targets = {**HOUSE_TARGETS, "equities": 7000, "bonds": 1400}
    reasoning = _tilt(targets, HOUSE_MIN, HOUSE_MAX, [goal], locked={"equities"})
    assert targets["equities"] == 7000
    assert any("Renditeziel 'Rendite'" in r and "Aktien ist als Berater-Ziel fixiert" in r for r in reasoning), reasoning
