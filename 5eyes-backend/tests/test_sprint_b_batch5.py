"""Sprint B Batch 5 - B3 Vorsorge-Differenziert (pension_pillar).

PENSION-AHV-001 (Phase 0, 2026-09): dieses Modul pinnte urspruenglich das
Sprint-B3-Verhalten fest, bei dem ein pension_pillar='AHV'-Label ALLEIN
(ohne jeglichen Beleg fuer eine tatsaechliche AHV-Rente) ein
Pensionsausgabe-Goal als 100% staatlich gedeckt auswies -- 0 Reserve-Beitrag,
volle target_amount im Scoring. Audit-Repro: ein CHF 1'000'000/Jahr
AHV-Goal ohne jegliches Portfolio-Vermoegen ergab reserve_needed_external=0
und einen Score von 100%, rein aus dem Label. Es gibt (verifiziert in
schemas/wealth.py) kein Feld, das einen tatsaechlichen erwarteten
AHV-Betrag erfasst -- die 100%-Deckung war unbelegt.
Fix: der automatische Staatsfinanzierungs-Bonus entfaellt. Ein
AHV-Pensionsausgabe-Goal durchlaeuft jetzt dieselbe Reserve-/Scoring-Logik
wie jedes andere Ausgabenziel (identisch zu BVG/3a/1e/FZG/kein-Pillar).

Verifiziert (Phase 0, nach PENSION-AHV-001):
- _goal_pension_pillar liefert weiterhin die Saeule oder None bei ungueltig
  (reines FE-Anzeige-Label, unveraendert)
- _goal_pension_state_funded liefert JETZT IMMER False -- keine Saeule
  bekommt mehr einen automatischen Reserve-/Scoring-Bonus
- AHV-Goal traegt zur Reserve bei wie ein normales Ausgabenziel (kein
  Sonder-Reasoning mehr)
- AHV-Goal liefert in _goal_reserve_for_goal denselben Betrag wie ein
  ansonsten identisches Goal ohne pension_pillar -- fuer JEDEN Horizont,
  nicht nur zufaellig fuer years<=3
- BVG/3a/1e/FZG/AHV/kein-Pillar verhalten sich jetzt alle identisch
  (reines Metadata-Label)
- Schema-Validierung: nur AHV/BVG/3a/1e/FZG erlaubt (unveraendert)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe
from schemas.wealth import GoalCreate, GoalUpdate


def _pension_goal(target_rappen: int = 5_000_000, years: int = 10,
                  pension_pillar: str | None = None, label: str = "Pension"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    g = SimpleNamespace(
        id=f"g-pension-{years}", goal_type="Pensionsausgabe",
        target_amount_rappen=target_rappen, frequency="jaehrlich",
        start_date=target_date, target_date=None,
        horizon_years=years, is_ongoing=1, label=label,
    )
    if pension_pillar is not None:
        g.pension_pillar = pension_pillar
    return g


def _spending_goal(target_rappen: int = 5_000_000, years: int = 2,
                   pension_pillar: str | None = None, label: str = "G"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    g = SimpleNamespace(
        id=f"g-spend-{years}", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=target_rappen, frequency=None,
        start_date=None, target_date=target_date,
        horizon_years=years, is_ongoing=0, label=label,
    )
    if pension_pillar is not None:
        g.pension_pillar = pension_pillar
    return g


# ============================================================================
# Helper-Tests
# ============================================================================


@pytest.mark.parametrize("pillar,expected", [
    ("AHV", "AHV"),
    ("BVG", "BVG"),
    ("3a", "3a"),
    ("1e", "1e"),
    ("FZG", "FZG"),
    (None, None),
    ("", None),
    ("garbage", None),
    ("ahv", None),  # case-sensitive
])
def test_b3_pension_pillar_helper(pillar, expected):
    g = _pension_goal(pension_pillar=pillar)
    assert pe._goal_pension_pillar(g) == expected


def test_b3_pension_pillar_missing_attr():
    g = _pension_goal()  # ohne pension_pillar gesetzt
    if hasattr(g, "pension_pillar"):
        delattr(g, "pension_pillar")
    assert pe._goal_pension_pillar(g) is None


@pytest.mark.parametrize("pillar,goal_factory,expected", [
    # PENSION-AHV-001: AHV war vorher der einzige True-Fall (siehe git
    # history); es gibt keinen Beleg-Mechanismus fuer eine tatsaechliche
    # AHV-Rente, also liefert _goal_pension_state_funded jetzt fuer JEDE
    # Saeule (inkl. AHV) und JEDEN Goal-Type False.
    ("AHV", _pension_goal, False),
    ("BVG", _pension_goal, False),
    ("3a", _pension_goal, False),
    ("1e", _pension_goal, False),
    ("FZG", _pension_goal, False),
    (None, _pension_goal, False),
    ("AHV", _spending_goal, False),
])
def test_b3_no_pillar_is_state_funded_anymore(pillar, goal_factory, expected):
    g = goal_factory(pension_pillar=pillar)
    assert pe._goal_pension_state_funded(g) is expected


# ============================================================================
# Reserve-Pfad: PENSION-AHV-001 -- AHV traegt normal bei (kein Sonderfall mehr)
# ============================================================================


def test_b3_ahv_pension_contributes_normal_reserve():
    """PENSION-AHV-001: AHV Pensionsausgabe-Goal traegt wie jedes andere
    Nahziel (years<=3 -> 100%) zur Reserve bei -- NICHT mehr 0.
    Vorher (Sprint B3, jetzt entfernt) lieferte dieselbe Eingabe 0, weil
    pension_pillar='AHV' allein als 'staatlich gedeckt' galt."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 5_000_000


def test_b3_ahv_pension_matches_non_pillar_goal_for_every_horizon():
    """PENSION-AHV-001: fuer JEDEN Horizont (nicht nur zufaellig years<=3)
    liefert ein AHV-Goal denselben Reserve-Beitrag wie ein identisches Goal
    ohne pension_pillar. years=5 liegt im 4-7-Fenster (50%-Faktor) --
    vorher haette AHV hier trotzdem 0 geliefert (Sonderfall schlug den
    normalen Decay), das ist der klarste Beweis, dass der Sonderfall weg ist."""
    for years in (2, 5, 10):
        g_ahv = _pension_goal(target_rappen=5_000_000, years=years, pension_pillar="AHV")
        g_none = _pension_goal(target_rappen=5_000_000, years=years)
        needed_ahv, _ = pe._compute_reserve_for_inputs(
            goals=[g_ahv], limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        needed_none, _ = pe._compute_reserve_for_inputs(
            goals=[g_none], limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed_ahv == needed_none, f"years={years}"
    # years=5 (4-7 Fenster) muss > 0 sein -- vorher waere AHV hier trotzdem
    # 0 gewesen (Sonderfall gewann gegen den 50%-Decay).
    needed_5y, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=5, pension_pillar="AHV")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed_5y == 2_500_000  # 50% Decay-Faktor fuer 4-7 Jahre


def test_b3_ahv_repro_chf_1mio_no_longer_free_ride():
    """Audit-Repro (PENSION-AHV-001): CHF 1'000'000/Jahr AHV-Goal, nahes
    Ziel (years=2, 100%-Fenster) gegen ein CHF 1'000'000 Beratungsportfolio
    (advisory_wealth_rappen=100'000'000). Vorher ergab pension_pillar='AHV'
    allein reserve_needed_external=0 (voll 'staatlich gedeckt', kein Beleg
    noetig). Jetzt wird wie bei jedem normalen Ausgabenziel ein echter
    externer Reserve-Bedarf ausgewiesen."""
    needed, external = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=100_000_000, years=2, pension_pillar="AHV", label="AHV-Rente")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=100_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 100_000_000
    assert external == 90_000_000
    assert external > 0


def test_b3_bvg_pension_contributes_normally():
    """BVG Pensionsausgabe -> Engine-Phase-1: kein Sondercase, normaler Reserve-Beitrag."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="BVG")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    # _annualize_goal_amount * legacy 100% (years<=3)
    assert needed > 0


def test_b3_ahv_pension_reasoning_no_longer_claims_state_funded():
    """PENSION-AHV-001: das Reasoning darf NICHT mehr behaupten, das Ziel
    sei 'AHV-finanziert (staatliche Saeule)' und brauche keine Reserve --
    genau dieser Satz wurde vorher hier erzeugt (Sprint B3). Ein
    AHV-Pensionsausgabe-Goal bekommt jetzt dasselbe generische
    Nahziel-Reasoning wie jedes andere Ausgabenziel."""
    reasoning: list[str] = []
    pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV", label="Rente")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning,
    )
    joined = " ".join(reasoning)
    assert "Rente" in joined
    assert "kurzfristiger Liquiditaetsbedarf" in joined
    # Die alte, jetzt entfernte Sonder-Formulierung darf nicht mehr auftauchen.
    assert "staatliche" not in joined.lower()
    assert "benoetigt keine Liquiditaetsreserve" not in joined


def test_b3_no_pillar_default_unchanged():
    """Ohne pension_pillar -> Verhalten identisch zu pre-B3."""
    needed_with_attr, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar=None)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    g_no_attr = _pension_goal(target_rappen=5_000_000, years=2)
    if hasattr(g_no_attr, "pension_pillar"):
        delattr(g_no_attr, "pension_pillar")
    needed_no_attr, _ = pe._compute_reserve_for_inputs(
        goals=[g_no_attr],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed_with_attr == needed_no_attr
    assert needed_with_attr > 0


def test_b3_ahv_pillar_on_spending_goal_no_skip():
    """AHV-Pillar auf Einmalige_Ausgabe (nicht Pensionsausgabe) -> kein Skip."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 5_000_000


# ============================================================================
# Scoring-Pfad: AHV liefert volle target zurueck (funded_ratio=100%)
# ============================================================================


def test_b3_goal_reserve_for_goal_ahv_matches_non_pillar_at_short_horizon():
    """PENSION-AHV-001: bei years<=3 liefert _goal_reserve_for_goal fuer ein
    AHV-Goal die volle target_amount -- aber jetzt, WEIL das die normale
    Nahziel-Regel (years<=3 -> 100%) ist, NICHT weil AHV als
    'staatlich gedeckt' gilt. Beweis: identisch zu einem Goal ganz ohne
    pension_pillar (siehe auch test_..._for_every_horizon unten)."""
    g_ahv = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="AHV")
    g_none = _pension_goal(target_rappen=12_000_000, years=2)
    if hasattr(g_none, "pension_pillar"):
        delattr(g_none, "pension_pillar")
    expected = pe._annualize_goal_amount(g_ahv)
    assert pe._goal_reserve_for_goal(g_ahv) == expected
    assert pe._goal_reserve_for_goal(g_ahv) == pe._goal_reserve_for_goal(g_none)
    assert expected > 0


def test_b3_goal_reserve_for_goal_ahv_no_longer_full_at_long_horizon():
    """PENSION-AHV-001 key regression guard: vor dem Fix lieferte ein
    AHV-Goal IMMER die volle target_amount, unabhaengig vom Horizont
    (Sonderfall schlug den normalen Decay). Bei years=10 (>7, normale
    Decay-Regel -> 0%) muss ein AHV-Goal jetzt GENAUSO 0 liefern wie ein
    identisches Nicht-Pillar-Goal -- nicht mehr die volle Summe."""
    g_ahv = _pension_goal(target_rappen=12_000_000, years=10, pension_pillar="AHV")
    g_none = _pension_goal(target_rappen=12_000_000, years=10)
    if hasattr(g_none, "pension_pillar"):
        delattr(g_none, "pension_pillar")
    assert pe._goal_reserve_for_goal(g_ahv) == 0
    assert pe._goal_reserve_for_goal(g_ahv) == pe._goal_reserve_for_goal(g_none)


def test_b3_goal_reserve_for_goal_bvg_uses_legacy_logic():
    """BVG-Goal -> normale legacy-Reserve-Logik (unveraendert seit Phase 1).
    Nach PENSION-AHV-001 verhaelt sich AHV jetzt ebenfalls so (siehe Tests
    oben) -- AHV/BVG/kein-Pillar sind ab jetzt alle aequivalent."""
    g_bvg = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="BVG")
    g_none = _pension_goal(target_rappen=12_000_000, years=2)
    if hasattr(g_none, "pension_pillar"):
        delattr(g_none, "pension_pillar")
    assert pe._goal_reserve_for_goal(g_bvg) == pe._goal_reserve_for_goal(g_none)


def test_b3_ahv_with_probability_combines():
    """AHV + probability: der Wahrscheinlichkeitsfaktor (Sprint B6) skaliert
    weiterhin korrekt -- PENSION-AHV-001 hat NUR den Staatsfinanzierungs-
    Bonus entfernt, die Bedingte-Goals-Logik bleibt unveraendert. Bei
    years=2 (Nahziel-Fenster, 100%-Decay) ist das Ergebnis
    base_target * prob_factor, unabhaengig vom pension_pillar-Wert."""
    g = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="AHV")
    g.probability_pct = 50
    expected = int(round(pe._annualize_goal_amount(g) * 0.5))
    assert pe._goal_reserve_for_goal(g) == expected


# ============================================================================
# Schema-Validierung
# ============================================================================


def _valid_pension_kwargs(**overrides):
    base = dict(
        goal_family="Cashflow",
        goal_type="Pensionsausgabe",
        label="Test",
        rank=1,
        target_amount_rappen=1_000_000,
        horizon_years=10,
        is_ongoing=True,
        frequency="jaehrlich",
        start_date="2035-01-01",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("pillar", ["AHV", "BVG", "3a", "1e", "FZG"])
def test_b3_schema_accepts_valid_pillars(pillar):
    g = GoalCreate(**_valid_pension_kwargs(pension_pillar=pillar))
    assert g.pension_pillar == pillar


def test_b3_schema_default_is_none():
    g = GoalCreate(**_valid_pension_kwargs())
    assert g.pension_pillar is None


@pytest.mark.parametrize("invalid", ["AHV1", "ahv", "Pillar2", "", "1a"])
def test_b3_schema_rejects_invalid_pillar(invalid):
    with pytest.raises(ValidationError):
        GoalCreate(**_valid_pension_kwargs(pension_pillar=invalid))


def test_b3_update_schema_accepts_pillar_or_none():
    g = GoalUpdate(pension_pillar="3a")
    assert g.pension_pillar == "3a"
    g2 = GoalUpdate()
    assert g2.pension_pillar is None
