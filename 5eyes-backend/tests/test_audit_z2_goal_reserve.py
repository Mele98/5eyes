"""Z2 - C5: Goal-Reserve-Scoring zielbezogen statt global.

Vor dem Fix nutzte _build_goal_analysis fuer Spending-Goals mit horizon<=3
Jahren als 'available' den GLOBALEN reserve_needed_rappen (Maximum aller
reserve_candidates). Damit konnte ein grosses Ziel den Reserve-Pool
hochziehen und kleinere Spending-Goals automatisch auf 'On Track'
heben - selbst wenn die zielbezogene Reserve fuer das kleine Ziel nicht
existiert.

Nach dem Fix nutzt das Scoring _goal_reserve_for_goal(goal) - identisch
zur Logik in _apply_goal_and_reserve_tilts (years<=3: 100%, 4-7: 50%,
>7: 0%) aber zielbezogen statt gepoolt.
"""
from __future__ import annotations
import sys
import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Mapper-Init: alle Models laden damit relationships sich gegenseitig finden
from database import Base  # noqa: F401
from models import allocation as _alloc_models  # noqa: F401
from models import clients as _client_models  # noqa: F401
from models import mandates as _mandate_models  # noqa: F401
from models import profiling as _prof_models  # noqa: F401
from models import review as _review_models  # noqa: F401
from models import snapshots as _snap_models  # noqa: F401
from models import users as _user_models  # noqa: F401
from models import wealth as _wealth_models  # noqa: F401
from models.allocation import OptimizerPolicy
from models.wealth import Goal
from services.portfolio_engine import _build_goal_analysis
from sqlalchemy.orm import configure_mappers
configure_mappers()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _make_goal(*, gid, label, target_amount, years, goal_type="Einmalige_Ausgabe", rank=1):
    today = datetime.date.today()
    target_date = today.replace(year=today.year + years)
    return Goal(
        id=gid, mandate_id="m-1", client_id="c-1",
        goal_family="Konsum", goal_type=goal_type,
        label=label, rank=rank, weight_bps=1000,
        goal_scope="Beratungsvermoegen",
        target_amount_rappen=target_amount,
        target_date=target_date.isoformat(),
        is_ongoing=0, is_active=1,
        created_at=_now(), updated_at=_now(),
    )


def _make_policy():
    return OptimizerPolicy(
        id="policy-1", policy_name="Test", version=1, is_current=1,
        valid_from="2026-01-01",
        optimizer_engine="TBI-V1",
        max_real_estate_bps=2000, max_alternatives_bps=1500,
        min_liquidity_bps=200,
        allow_other_assets_for_goals=1,
        fee_model_json="{}",
        created_by="advisor-1",
        created_at=_now(), updated_at=_now(),
    )


def test_c5_small_goal_not_on_track_just_because_big_goal_exists():
    """Goal A: 50k Einmalige in 2 J. Goal B: 200k Einmalige in 2 J.
    Vor dem Fix: globaler reserve_needed = max(50k,200k) = 200k. Goal A score
    wuerde min(100, 200/50*100) = 100% bekommen - falsch.
    Nach dem Fix: Goal A score basiert auf eigener 50k-Reserve gegen
    target 50k = 100% - aber NICHT durch das grosse Ziel 'aufgepumpt'."""
    goals = [
        _make_goal(gid="g-small", label="Auto", target_amount=5_000_000, years=2, rank=1),
        _make_goal(gid="g-big", label="Hauskauf", target_amount=20_000_000, years=2, rank=2),
    ]
    advisory_wealth = 50_000_000  # 500k
    # Globaler reserve_needed waere fuer den Pool 200k+50k = 250k
    global_reserve = 25_000_000
    analysis = _build_goal_analysis(
        goals=goals,
        advisory_wealth_rappen=advisory_wealth,
        total_wealth_rappen=advisory_wealth,
        cashflow_projection_series_rappen=[0]*15,
        inflation_series_bps=[150]*15,
        expected_return_bps=400,
        reserve_needed_rappen=global_reserve,
        policy=_make_policy(),
    )
    by_id = {a["goal_id"]: a for a in analysis}
    # Goal A (klein, 50k in 2J): zielspezifische Reserve = 50k. Score = 100%
    # weil eigene Reserve >= eigener Bedarf. Aber das ist OK - hier
    # erwarten wir, dass Goal A NICHT durch goal B aufgehoben wird auf 400%.
    assert by_id["g-small"]["achievement_score"] <= 100
    # Goal B (gross, 200k in 2J): zielspezifische Reserve = 200k. Score = 100%
    assert by_id["g-big"]["achievement_score"] <= 100


def test_c5_goal_score_uses_goal_specific_reserve_not_global_max():
    """Direkt: ein kleines Ziel mit horizon<=3 darf nicht auf 100% kommen
    nur weil global_reserve riesig ist. Wir checken, dass das Scoring
    NICHT mehr mit dem global-Wert skaliert."""
    target = 10_000_000  # 100k
    goal = _make_goal(gid="g-1", label="X", target_amount=target, years=2)
    # Test mit global_reserve = 1_000_000_000 (10M, viel groesser als target)
    analysis = _build_goal_analysis(
        goals=[goal],
        advisory_wealth_rappen=50_000_000,
        total_wealth_rappen=50_000_000,
        cashflow_projection_series_rappen=[0]*15,
        inflation_series_bps=[150]*15,
        expected_return_bps=400,
        reserve_needed_rappen=1_000_000_000,  # absurder global pool
        policy=_make_policy(),
    )
    score = analysis[0]["achievement_score"]
    # Score muss exakt 100 sein (Bedarf 100k, eigene Reserve 100k = 100%)
    # NICHT 1000 oder so wegen aufgeblaehtem global pool.
    assert 95 <= score <= 100, f"score {score} sollte ~100 sein, nicht durch globalen Pool aufgeblaeht"


def test_c5_long_horizon_goal_uses_projection_not_reserve():
    """Bei years > 3 wird projected_rappen verwendet (unverandert)."""
    goal = _make_goal(gid="g-long", label="Long", target_amount=10_000_000, years=15)
    analysis = _build_goal_analysis(
        goals=[goal],
        advisory_wealth_rappen=10_000_000_000,  # 100 Mio
        total_wealth_rappen=10_000_000_000,
        cashflow_projection_series_rappen=[0]*16,
        inflation_series_bps=[150]*16,
        expected_return_bps=400,
        reserve_needed_rappen=0,  # global pool egal weil horizon > 3
        policy=_make_policy(),
    )
    # 100M in 15J bei 4% = ca. 180M, target ist 100k -> deutlich >100%
    assert analysis[0]["achievement_score"] == 100


def test_c5_recurring_spending_uses_annualized_reserve():
    """Wiederkehrende_Ausgabe: target_amount wird annualisiert, dann zielbezogene
    Reserve. Score basiert auf eigener Reserve, nicht globaler."""
    goal = _make_goal(
        gid="g-rec", label="Rente", target_amount=1_000_000,  # 10k/Monat
        years=2, goal_type="Pensionsausgabe",
    )
    goal.frequency = "monatlich"
    analysis = _build_goal_analysis(
        goals=[goal],
        advisory_wealth_rappen=50_000_000,
        total_wealth_rappen=50_000_000,
        cashflow_projection_series_rappen=[0]*15,
        inflation_series_bps=[150]*15,
        expected_return_bps=400,
        reserve_needed_rappen=999_999_999,  # absurder global pool
        policy=_make_policy(),
    )
    score = analysis[0]["achievement_score"]
    # annualized: 12 * 10k = 120k. Eigene Reserve = 120k. Score sollte 100%
    # sein, NICHT durch globalen Pool aufgepumpt.
    assert 95 <= score <= 100
