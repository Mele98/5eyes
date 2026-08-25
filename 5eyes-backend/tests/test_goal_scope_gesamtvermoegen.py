"""Regressions-Lock #83: goal_scope='Gesamtvermoegen' bewertet Vermoegensziele
gegen das GESAMTvermoegen — externe Assets wachsen KONSERVATIV nur mit Teuerung
(real 0%, keine Vola). User-Entscheid 2026-06-19.

Kern (gegen die fruehere B4-Drift-Falle): der externe Anteil ist eine
DETERMINISTISCHE Konstante und wird in beiden Pfaden (deterministisch +
Monte-Carlo) identisch addiert -> keine Drift zwischen den Pfaden.

Default-Scope ('Beratungsvermoegen') bleibt unveraendert (nur Beratungsvermoegen).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Alle Modelle registrieren, damit die Mapper-Relationships (Client<->WealthPosition)
# aufloesen, bevor wir ein Goal instanziieren.
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth, tenant,
)
from sqlalchemy.orm import configure_mappers

from models.wealth import Goal
from services.portfolio_engine import (
    _build_goal_analysis,
    _external_assets_inflation_value,
    _monte_carlo_goal_summary,
)

configure_mappers()

ADVISORY = 50_000_000        # 500'000 CHF (Rappen)
TOTAL = 150_000_000          # 1'500'000 CHF -> externes Vermoegen 1'000'000
EXTERNAL = TOTAL - ADVISORY
INFL = [150] * 12            # 1.5 % Teuerung p.a.
RETURN_BPS = 300             # 3 % Beratungsvermoegen-Rendite
YEARS = 10


def _ziel(scope: str) -> Goal:
    return Goal(
        id="g1",
        label="Vermoegensziel 1.2M",
        goal_type="Vermoegensziel",
        goal_scope=scope,
        target_wealth_rappen=120_000_000,
        value_mode="nominal",
        rank=1,
        horizon_years=YEARS,
        is_ongoing=0,
    )


def _analyse(scope: str, total: int = TOTAL) -> dict:
    return _build_goal_analysis(
        [_ziel(scope)],
        ADVISORY,
        total,
        [0] * YEARS,            # keine Cashflows
        INFL,
        RETURN_BPS,
        0,                       # reserve_needed
        None,                    # policy (im Body ungenutzt)
    )[0]


# ── externe Inflations-Hochrechnung: real 0 % ───────────────────────────────────

def test_external_growth_is_inflation_only_real_zero():
    grown = _external_assets_inflation_value(EXTERNAL, YEARS, INFL)
    assert grown == round(EXTERNAL * (1.015 ** YEARS))
    # real 0 %: nominal genau Teuerung, kein realer Zuwachs
    assert grown > EXTERNAL


# ── deterministischer Pfad ──────────────────────────────────────────────────────

def test_default_scope_ignores_external_assets():
    # Beratungsvermoegen-Scope haengt NICHT vom Gesamtvermoegen ab.
    with_external = _analyse("Beratungsvermögen", total=TOTAL)
    without_external = _analyse("Beratungsvermögen", total=ADVISORY)
    assert with_external["projected_value_rappen"] == without_external["projected_value_rappen"]


def test_total_scope_adds_exactly_inflation_grown_external():
    base = _analyse("Beratungsvermögen")
    total = _analyse("Gesamtvermögen")
    expected_external = _external_assets_inflation_value(EXTERNAL, YEARS, INFL)
    assert total["projected_value_rappen"] - base["projected_value_rappen"] == expected_external
    # Gesamtvermoegen-Scope hebt die Zielerreichung (mehr projiziertes Vermoegen).
    assert total["achievement_score"] >= base["achievement_score"]


def test_total_scope_deterministic():
    assert _analyse("Gesamtvermögen") == _analyse("Gesamtvermögen")


# ── Monte-Carlo-Pfad: gleiche Konstante, kein Drift ─────────────────────────────

def _mc(scope: str) -> dict:
    samples = [40_000_000, 50_000_000, 60_000_000, 70_000_000]
    path_values_by_year = [list(samples) for _ in range(YEARS + 2)]
    return _monte_carlo_goal_summary(
        _ziel(scope),
        path_values_by_year=path_values_by_year,
        annualized_return_samples_bps=[RETURN_BPS] * len(samples),
        inflation_series_bps=INFL,
        advisory_wealth_rappen=ADVISORY,
        total_wealth_rappen=TOTAL,
        start_year=2026,
        horizon_years=YEARS,
        policy=None,
    )


def test_mc_total_scope_shifts_distribution_by_external_constant():
    base = _mc("Beratungsvermögen")
    total = _mc("Gesamtvermögen")
    # index = min(YEARS, horizon) = YEARS
    expected_external = _external_assets_inflation_value(EXTERNAL, YEARS, INFL)
    for key in (
        "projected_value_p10_rappen",
        "projected_value_p25_rappen",
        "projected_value_p50_rappen",
        "projected_value_p90_rappen",
    ):
        assert total[key] - base[key] == expected_external, key


def test_mc_default_scope_unchanged_by_total_wealth():
    base = _mc("Beratungsvermögen")
    # Beratungsvermoegen-Scope ignoriert externes Vermoegen vollstaendig.
    assert base["projected_value_p50_rappen"] == 55_000_000  # Median von 40/50/60/70M
