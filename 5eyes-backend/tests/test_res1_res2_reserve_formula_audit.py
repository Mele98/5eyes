"""RES-1/RES-2 (2026-07-24, Formel-Audit): `_compute_reserve_for_inputs`
gegen Portfoliotheorie/Liquiditaetsplanung geprueft.

RES-1: near_term_shortfall_rappen nutzte die reine ENDSUMME der ersten 3
Jahre statt des tiefsten kumulativen Punkts (running minimum). Bei einer
gemischten Serie (z.B. grosse Ausgabe in Jahr 1, gefolgt von einem Zufluss)
unterschaetzte das den tatsaechlichen Liquiditaetsbedarf.

RES-2: external_reserve_rappen war ungecappt gegen advisory_wealth_rappen --
bei mehreren summierten Nahzielen (#AA-8) konnte der berechnete Bedarf das
gesamte Beratungsvermoegen uebersteigen, ohne jede Warnung.
"""
from __future__ import annotations
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _compute_reserve_for_inputs


def _future_date(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# RES-1: Running-Minimum statt Endsumme
# ---------------------------------------------------------------------------

def test_res1_running_minimum_catches_interim_low_point():
    """[-50k, +40k, -10k]: Endsumme=-20k, aber der tiefste Punkt liegt bei
    -50k in Jahr 1. Reserve muss den tieferen (=konservativeren) Wert
    widerspiegeln."""
    needed, _ = _compute_reserve_for_inputs(
        goals=[], limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[-50_000_00, 40_000_00, -10_000_00],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 50_000_00, f"Erwartet 50'000 (Running-Min), got {needed / 100}"


def test_res1_monotonic_series_unchanged_vs_old_endsum_formula():
    """Bei einer monotonen (nur negativen) Serie ist running_min == end_sum --
    kein Verhaltens-Unterschied zur alten Formel (Backwards-Compat fuer den
    Mehrheitsfall)."""
    needed, _ = _compute_reserve_for_inputs(
        goals=[], limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[-10_000_00, -10_000_00, -10_000_00],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 30_000_00


def test_res1_never_lower_than_old_formula():
    """Fuer eine Reihe zufaellig gemischter Serien: running-min-basierte
    Reserve ist NIE kleiner als die alte reine-Endsumme-Formel (mathematischer
    Beweis: running_min <= letzte Partialsumme, die Endsumme selbst ist eine
    der Partialsummen)."""
    series_cases = [
        [-50_000_00, 40_000_00, -10_000_00],
        [10_000_00, -80_000_00, 5_000_00],
        [-5_000_00, -5_000_00, 30_000_00],
        [0, 0, 0],
    ]
    for series in series_cases:
        old_formula = max(0, -sum(series))
        needed, _ = _compute_reserve_for_inputs(
            goals=[], limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=series,
            advisory_wealth_rappen=10_000_000_00,
            saa_liquidity_ceiling_bps=300,
        )
        assert needed >= old_formula, (series, needed, old_formula)


def test_res1_inflow_reduces_running_balance_per_year():
    """Ein Wealth-Inflow in Jahr 2 darf den Bedarf in Jahr 1 nicht senken
    (er kommt zeitlich zu spaet), aber Jahr 2/3 verbessern."""
    needed, _ = _compute_reserve_for_inputs(
        goals=[], limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[-50_000_00, -10_000_00, -10_000_00],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
        inflow_projection_series_rappen=[0, 100_000_00, 0],
    )
    # Jahr 1: -50k (kein Inflow noch). Jahr 2: -60k+100k=+40k. Jahr 3: +30k.
    # Tiefster Punkt bleibt -50k in Jahr 1 -> Inflow in Jahr 2 hilft nicht rueckwirkend.
    assert needed == 50_000_00


# ---------------------------------------------------------------------------
# RES-2: externe Reserve gecappt gegen advisory_wealth_rappen
# ---------------------------------------------------------------------------

def _near_term_goal(label, amount_rappen, days_out=300):
    return SimpleNamespace(
        id=f"g-{label}",
        label=label,
        goal_type="Einmalige_Ausgabe",
        pension_pillar=None,
        probability_pct=None,
        rank=1,
        hardness="Primaer",
        weight_bps=0,
        target_amount_rappen=amount_rappen,
        target_date=_future_date(days_out),
        start_date=None,
        horizon_years=None,
        frequency=None,
    )


def test_res2_external_reserve_capped_at_advisory_wealth():
    """Zwei Nahziele summieren sich (#AA-8) auf mehr als das gesamte
    Beratungsvermoegen -> externe Reserve darf das Vermoegen NICHT
    uebersteigen."""
    goals = [
        _near_term_goal("Hauskauf", 200_000_00),
        _near_term_goal("Ausbildung", 150_000_00),
    ]
    advisory_wealth_rappen = 300_000_00  # kleiner als 200k+150k=350k
    needed, external = _compute_reserve_for_inputs(
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 350_000_00  # der reine Bedarf bleibt unveraendert sichtbar
    assert external <= advisory_wealth_rappen, (
        f"Externe Reserve ({external / 100}) darf das Beratungsvermoegen "
        f"({advisory_wealth_rappen / 100}) nicht uebersteigen"
    )
    assert external == advisory_wealth_rappen


def test_res2_warning_added_when_reserve_exceeds_wealth():
    goals = [_near_term_goal("Hauskauf", 500_000_00)]
    reasoning: list[str] = []
    _compute_reserve_for_inputs(
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=100_000_00,
        saa_liquidity_ceiling_bps=300,
        reasoning=reasoning,
    )
    assert any("uebersteigt das" in text or "übersteigt das" in text for text in reasoning), reasoning


def test_res2_normal_case_unaffected_by_cap():
    """Wenn der Bedarf deutlich unter dem Vermoegen liegt, greift der Cap
    nicht -- kein Verhaltens-Unterschied im Normalfall."""
    goals = [_near_term_goal("Kleines Ziel", 10_000_00)]
    needed, external = _compute_reserve_for_inputs(
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 10_000_00
    assert external == 0


# ---------------------------------------------------------------------------
# RES-1-Nachtrag (2026-08-07, CEO/CFO/CIO-Audit): Cashflow-Defizit und
# Ziel-Reserve muessen sich ADDIEREN, nicht per max() konkurrieren.
# ---------------------------------------------------------------------------

def test_cashflow_shortfall_and_goal_reserve_add_up_not_max():
    """Ein Kunde mit sowohl einem Cashflow-Defizit (running-min -50k) ALS
    AUCH einem separaten Nahziel (Hauskauf 80k) braucht Bargeld fuer BEIDE
    Posten -- nicht nur fuer den groesseren. Erwartete Reserve: 50k+80k=130k,
    NICHT max(50k,80k)=80k."""
    goals = [_near_term_goal("Hauskauf", 80_000_00)]
    needed, _ = _compute_reserve_for_inputs(
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[-50_000_00, 10_000_00, 10_000_00],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 130_000_00, f"Erwartet 130'000 (additiv), got {needed / 100}"


def test_manual_reserve_floor_still_max_combined_not_added():
    """Die manuelle Reserve-Vorgabe bleibt ein FLOOR (max()), kein
    zusaetzlicher Geldabfluss -- wird NICHT zum computed_liquidity_need
    hinzuaddiert."""
    goals = [_near_term_goal("Kleinziel", 10_000_00)]
    needed, _ = _compute_reserve_for_inputs(
        goals=goals, limits_prefs={"minReserve": "200000"}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    # computed_liquidity_need=10k < manual floor 200k -> Floor gewinnt, keine Addition.
    assert needed == 200_000_00, f"Erwartet Floor 200'000, got {needed / 100}"
