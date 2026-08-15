"""Regressionstests fuer den Berater-Audit "Restriktionen & Tilts" (2026-08-03).

Der Berater hat explizit angezweifelt, dass Anlagepraeferenzen -- insbesondere
manuelle Bandbreiten-Restriktionen und die verschiedenen Tilt-Mechanismen --
saubere verdrahtet sind. Ein 5-Agenten-Adversarial-Audit fand mehrere
vorbestehende (nicht durch den ADR-014-Split verursachte) fachliche Bugs, bei
denen eine vom Berater gesetzte Mindest-/Maximalgrenze durch einen Tilt oder
den Risikobudget-Fallback stillschweigend verletzt oder verworfen wurde.

Jeder Test unten sperrt genau EINEN der live reproduzierten Befunde:

1. Manuelle min_bps/max_bps-Restriktionen ueberleben den Risikobudget-
   Fallback (`_apply_band_min_max_overrides`, aufgerufen nach
   `_house_matrix_mid_targets` in `generate_target_allocation`).
2. Der Goal-Horizont-Tilt (Kapitalerhalt/Vermoegensziel, kurzer Horizont)
   clipt seine Empfaenger-Seite (bonds/liquidity) gegen die AKTUELLEN
   (ggf. ueberschriebenen) Maximalgrenzen.
3. Der External-Exposure-Tilt clipt Spender- UND Empfaenger-Seite gegen die
   AKTUELLEN Grenzen (nicht die statischen House-Matrix-Defaults).
4. Der Illiquiditaets-Cap (`_apply_illiquid_cap`) respektiert die
   Liquiditaets-Maximalgrenze, wenn kein liquider Alternatives-Sleeve
   vorhanden ist, um den freigewordenen PE-Anteil aufzunehmen.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pydantic
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from schemas.allocation import AllocationPreferencesPayload
from services.portfolio_engine import PortfolioSummary
from services.portfolio_engine_house_matrix import (
    _apply_band_min_max_overrides,
    _apply_external_exposure_tilts,
    _apply_goal_and_reserve_tilts,
    _apply_illiquid_cap,
)


# ===========================================================================
# 1. _apply_band_min_max_overrides — Ueberleben des Risikobudget-Fallbacks
# ===========================================================================


def test_band_min_max_override_restores_after_house_matrix_reset():
    """Simuliert exakt den Fallback-Pfad: _house_matrix_mid_targets() setzt
    minimums/maximums auf die Haus-Matrix-Defaults zurueck (hier: kein
    Aktien-Limit), danach MUSS die Berater-Restriktion (Aktien max. 20%)
    wiederhergestellt werden."""
    # Zustand NACH _house_matrix_mid_targets() (Defaults, kein Limit)
    minimums = {"equities": 1000, "bonds": 2000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 10000, "bonds": 10000, "real_estate": 3000, "alternatives": 2000, "liquidity": 2000}
    bands = {"Aktien": {"max_bps": 2000}}

    restored = _apply_band_min_max_overrides(bands, minimums, maximums)

    assert restored is True
    assert maximums["equities"] == 2000, "Berater-Maximum wurde beim Fallback nicht wiederhergestellt"
    # Andere Buckets bleiben unveraendert
    assert maximums["bonds"] == 10000
    assert minimums["equities"] == 1000


def test_band_min_max_override_restores_min_and_max_together():
    minimums = {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 10000, "bonds": 10000, "real_estate": 10000, "alternatives": 10000, "liquidity": 10000}
    bands = {"bonds": {"min_bps": 3000, "max_bps": 6000}}

    restored = _apply_band_min_max_overrides(bands, minimums, maximums)

    assert restored is True
    assert minimums["bonds"] == 3000
    assert maximums["bonds"] == 6000


def test_band_min_max_override_ignores_target_only_entries():
    """Ein reiner target_bps-Override (ohne min/max) darf hier keine
    Wirkung/Wiederherstellung ausloesen -- target_bps ist baseline-abhaengig
    und wird bewusst NICHT erneut angewendet (siehe Docstring der Funktion)."""
    minimums = {"equities": 1000, "bonds": 2000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 10000, "bonds": 10000, "real_estate": 3000, "alternatives": 2000, "liquidity": 2000}
    bands = {"Aktien": {"target_bps": 3500}}

    restored = _apply_band_min_max_overrides(bands, minimums, maximums)

    assert restored is False
    assert maximums["equities"] == 10000
    assert minimums["equities"] == 1000


def test_band_min_max_override_no_bands_is_noop():
    minimums = {"equities": 1000}
    maximums = {"equities": 10000}
    assert _apply_band_min_max_overrides(None, minimums, maximums) is False
    assert _apply_band_min_max_overrides({}, minimums, maximums) is False
    assert minimums["equities"] == 1000
    assert maximums["equities"] == 10000


def test_band_min_max_override_unknown_bucket_key_ignored():
    minimums = {"equities": 1000}
    maximums = {"equities": 10000}
    restored = _apply_band_min_max_overrides({"Kryptowaehrung": {"max_bps": 500}}, minimums, maximums)
    assert restored is False
    assert maximums["equities"] == 10000


# ===========================================================================
# 2. Goal-Horizont-Tilt (Kapitalerhalt/Vermoegensziel) — Empfaenger-Clipping
# ===========================================================================


def _goal(goal_type: str, horizon_years: int, **over) -> SimpleNamespace:
    base = dict(
        id=f"g-{goal_type}", label=f"Ziel {goal_type}",
        goal_type=goal_type, hardness="Sekundär",
        target_return_bps=None, target_amount_rappen=None,
        target_wealth_rappen=None, horizon_years=horizon_years,
        target_date=None, start_date=None, weight_bps=5000,
        is_ongoing=0, frequency=None, rank=2,
        success_probability_min_x100=None, probability_pct=100,
        pension_pillar=None, value_mode="nominal",
        is_inflation_linked=0, notes=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_goal_horizon_tilt_respects_tight_bonds_and_liquidity_maximums():
    """Vorher: der Tilt reduzierte Aktien um bis zu 200 bps und verteilte sie
    hart 50/50 auf bonds/liquidity, OHNE zu prufen ob dort ueberhaupt Platz
    unter dem (ggf. vom Berater gesenkten) Maximum ist. Jetzt: eq_reduction
    wird auf den verfuegbaren Platz geclippt."""
    targets = {"equities": 5000, "bonds": 2980, "real_estate": 1000, "alternatives": 500, "liquidity": 520}
    minimums = {"equities": 2000, "bonds": 2000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    # Bonds-Maximum vom Berater auf 3000 gesenkt -> nur 20 bps Platz;
    # Liquidity-Maximum auf 600 -> nur 80 bps Platz.
    maximums = {"equities": 6000, "bonds": 3000, "real_estate": 2000, "alternatives": 1000, "liquidity": 600}
    goals = [_goal("Kapitalerhalt", horizon_years=3)]
    reasoning: list[str] = []

    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )

    assert targets["bonds"] <= maximums["bonds"], "Bonds-Maximum wurde durch den Goal-Tilt verletzt"
    assert targets["liquidity"] <= maximums["liquidity"], "Liquidity-Maximum wurde durch den Goal-Tilt verletzt"


def test_goal_horizon_tilt_unclipped_case_still_applies_full_200bps():
    """Backwards-Compat: mit genuegend Platz bleibt der Tilt bei den
    urspruenglichen 200 bps (100/100 Split bonds/liquidity)."""
    targets = {"equities": 5000, "bonds": 2500, "real_estate": 1000, "alternatives": 500, "liquidity": 1000}
    minimums = {"equities": 2000, "bonds": 2000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 6000, "bonds": 10000, "real_estate": 2000, "alternatives": 1000, "liquidity": 10000}
    goals = [_goal("Vermoegensziel", horizon_years=2)]
    reasoning: list[str] = []
    eq_before = targets["equities"]

    _apply_goal_and_reserve_tilts(
        targets=targets, minimums=minimums, maximums=maximums,
        goals=goals, limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0] * 11,
        advisory_wealth_rappen=1_000_000_00, reasoning=reasoning,
    )

    assert targets["equities"] == eq_before - 200
    assert reasoning and "Vermoegensziel" in reasoning[0]


# ===========================================================================
# 3. _apply_external_exposure_tilts — Clipping gegen AKTUELLE Grenzen
# ===========================================================================


def _total_summary(equities_bps: int, real_estate_bps: int = 0, total_rappen: int = 1_000_000_00) -> PortfolioSummary:
    return PortfolioSummary(
        amounts_rappen={
            "equities": int(total_rappen * equities_bps / 10000),
            "real_estate": int(total_rappen * real_estate_bps / 10000),
            "bonds": 0, "alternatives": 0, "liquidity": 0,
        },
        total_rappen=total_rappen,
    )


def test_external_exposure_tilt_respects_manually_lowered_bonds_maximum():
    """Vorher: die Bonds-Empfaenger-Seite wurde gegen das STATISCHE
    House-Matrix-Maximum geclippt, nicht gegen die per Bandbreiten-Override
    bereits gesenkte AKTUELLE Grenze -- der Tilt konnte eine Berater-
    Restriktion auf bonds unbemerkt ueberschreiten."""
    targets = {"equities": 4000, "bonds": 2990, "real_estate": 1000, "alternatives": 500, "liquidity": 1510}
    minimums = {"equities": 1000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    # Bonds-Maximum vom Berater auf 3000 gesenkt -> nur 10 bps Platz,
    # obwohl der Tilt bis zu 400 bps auf bonds verschieben wollen wuerde.
    maximums = {"equities": 6000, "bonds": 3000, "real_estate": 2000, "alternatives": 1000, "liquidity": 2000}
    house_matrix = SimpleNamespace(equity_minimum_bps=1000)
    total_summary = _total_summary(equities_bps=8000)  # 80% externes Equity-Exposure -> triggert Tilt
    reasoning: list[str] = []

    _apply_external_exposure_tilts(targets, minimums, maximums, total_summary, house_matrix, False, reasoning)

    assert targets["bonds"] <= maximums["bonds"], "Bonds-Maximum wurde durch den External-Exposure-Tilt verletzt"


def test_external_exposure_tilt_respects_manually_raised_equity_minimum():
    """Symmetrischer Fall: wenn der Berater das Aktien-Minimum ueber den
    House-Matrix-Default angehoben hat, darf der reduzierende Tilt nicht
    darunter fallen."""
    targets = {"equities": 3500, "bonds": 3000, "real_estate": 1500, "alternatives": 1000, "liquidity": 1000}
    # Berater-Minimum 3400 -- deutlich ueber dem House-Matrix-equity_minimum_bps=500.
    minimums = {"equities": 3400, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 6000, "bonds": 10000, "real_estate": 2000, "alternatives": 2000, "liquidity": 2000}
    house_matrix = SimpleNamespace(equity_minimum_bps=500)
    total_summary = _total_summary(equities_bps=9000)  # starker Reduktions-Tilt
    reasoning: list[str] = []

    _apply_external_exposure_tilts(targets, minimums, maximums, total_summary, house_matrix, False, reasoning)

    assert targets["equities"] >= 3400, "Manuell angehobenes Aktien-Minimum wurde durch den Tilt unterschritten"


def test_external_exposure_tilt_skips_when_manual_override_active():
    targets = {"equities": 4000, "bonds": 3000, "real_estate": 1500, "alternatives": 1000, "liquidity": 500}
    before = dict(targets)
    minimums = {"equities": 1000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    maximums = {"equities": 6000, "bonds": 10000, "real_estate": 2000, "alternatives": 2000, "liquidity": 2000}
    house_matrix = SimpleNamespace(equity_minimum_bps=1000)
    total_summary = _total_summary(equities_bps=9000, real_estate_bps=6000)
    reasoning: list[str] = []

    _apply_external_exposure_tilts(targets, minimums, maximums, total_summary, house_matrix, True, reasoning)

    assert targets == before
    assert reasoning == []


# ===========================================================================
# 4. _apply_illiquid_cap — Liquiditaets-Maximum bei fehlendem liquiden Sleeve
# ===========================================================================


def test_illiquid_cap_respects_liquidity_maximum_when_no_liquid_alt_sleeve():
    """Ohne liquiden Alternatives-Sleeve (nur Private Equity) wird der
    freiwerdende Betrag in die Liquiditaet verschoben. Vorher: das passierte
    ungeprueft gegen ein bereits am/ueber dem Maximum liegendes
    Liquiditaets-Ziel. Jetzt: der effektive Cap wird VOR der Skalierung so
    angepasst, dass die Liquiditaets-Maximalgrenze nicht ueberschritten wird
    -- auch wenn das bedeutet, dass das Illiquiditaets-Limit selbst nicht
    voll erreicht wird (Bandbreiten-Restriktion hat Vorrang)."""
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 1000, "rationale": ""},
    ]
    targets = {"equities": 4000, "bonds": 3000, "real_estate": 1500, "alternatives": 1000, "liquidity": 500}
    # Liquiditaets-Maximum vom Berater auf 550 gesetzt -> nur 50 bps Platz,
    # obwohl der Cap (300) 700 bps aus PE freisetzen wollen wuerde.
    maximums = {"equities": 6000, "bonds": 4000, "real_estate": 2000, "alternatives": 2000, "liquidity": 550}
    reasoning: list[str] = []

    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 300, reasoning, maximums=maximums)

    assert out_targets["liquidity"] <= maximums["liquidity"], (
        "Liquiditaets-Maximum wurde durch den Illiquiditaets-Cap-Fallback verletzt"
    )
    assert any("Vorrang" in r or "Liquiditaets" in r for r in reasoning)


def test_illiquid_cap_reaches_full_target_when_liquidity_room_sufficient():
    """Gegenprobe: ist genuegend Platz unter dem Liquiditaets-Maximum
    vorhanden, wird der Cap wie zuvor voll erreicht (kein Verhaltenswechsel
    im Normalfall)."""
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 1000, "rationale": ""},
    ]
    targets = {"equities": 4000, "bonds": 3000, "real_estate": 1500, "alternatives": 1000, "liquidity": 500}
    maximums = {"equities": 6000, "bonds": 4000, "real_estate": 2000, "alternatives": 2000, "liquidity": 5000}
    reasoning: list[str] = []

    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 300, reasoning, maximums=maximums)

    pe = next(s for s in out_subs if s["sub_asset_class"] == "Private Equity")
    assert pe["target_weight_bps"] == 300
    assert out_targets["liquidity"] == 1200
    assert not any("Vorrang" in r for r in reasoning)


def test_illiquid_cap_without_maximums_param_keeps_legacy_behaviour():
    """Backwards-Compat: ohne `maximums`-Argument (alle existierenden
    Aufrufer vor diesem Fix) bleibt das Verhalten exakt wie zuvor."""
    subs = [
        {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 1000, "rationale": ""},
    ]
    targets = {"equities": 4000, "bonds": 3000, "real_estate": 1500, "alternatives": 1000, "liquidity": 500}
    reasoning: list[str] = []

    out_subs, out_targets = _apply_illiquid_cap(subs, targets, 300, reasoning)

    pe = next(s for s in out_subs if s["sub_asset_class"] == "Private Equity")
    assert pe["target_weight_bps"] == 300
    assert out_targets["liquidity"] == 1200


# ===========================================================================
# 5. Voller Engine-Pfad (generate_target_allocation) — Wachstums-Cashflow-Tilt
#    respektiert die Empfaenger-Decke; Netto-Tilt-Effekt im Reasoning.
#
# Nutzt die realistische Mandats-Fixtur aus test_optimizer_shadow_mode.py
# (Score 7/Wachstumsorientiert, positiver Cashflow, Vermoegensziel-Goal) --
# genau das Profil, das den Wachstums-Cashflow-Tilt in der Praxis ausloest.
# ===========================================================================

from main import app  # noqa: E402,F401 (erzwingt vollstaendige Modell-Registrierung, inkl. tenants)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401
from models.mandates import Mandate  # noqa: E402


def _run_engine(session_factory, mid, advisor_id, preferences=None):
    import services.portfolio_engine as pe
    with session_factory() as s:
        m = s.query(Mandate).filter(Mandate.id == mid).one()
        return pe.generate_target_allocation(s, m, advisor_id, preferences=preferences)


def test_growth_cashflow_tilt_fires_without_manual_restriction(session_factory, monkeypatch):
    # 2026-08 (asset-allocation-stochastic-core, config.py): Produktions-
    # Default von optimizer_mode ist jetzt 'stochastic' statt 'house_matrix'.
    # Der Wachstums-Cashflow-Tilt ist bewusst eine House-Matrix-Heuristik
    # (siehe `not optimizer_replaced_targets`-Guard in generate_target_
    # allocation) -- sie greift nur, wenn der Solver NICHT bereits konvergierte
    # Ziele geliefert hat. Dieser Test prueft explizit den House-Matrix-Pfad.
    import services.portfolio_engine as pe
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="growthfire")
    result = _run_engine(session_factory, mid, advisor_id, preferences=None)
    reasoning = result.get("reasoning") or []
    assert any("Wachstumsziele" in r for r in reasoning), (
        "Wachstums-Cashflow-Tilt hat bei diesem (dafuer ausgelegten) Profil nicht ausgeloest"
    )
    assert any("Netto-Effekt aller Exposure-Tilts" in r for r in reasoning), (
        "Netto-Tilt-Effekt-Reasoning (Befund 4) fehlt im Response"
    )


def test_growth_cashflow_tilt_respects_manually_lowered_equity_maximum(session_factory, monkeypatch):
    """Sicherheits-Fix (2026-08-03): mit einem Berater-Maximum, das nur noch
    50 bps Platz laesst (< 150 bps Tilt-Groesse), darf der Tilt NICHT
    feuern -- vorher wurde die Empfaenger-Seite (equities) gar nicht gegen
    das aktuelle Maximum geprueft."""
    # house_matrix: siehe Kommentar in test_growth_cashflow_tilt_fires_without_
    # manual_restriction -- dieser Test braucht denselben Heuristik-Pfad.
    import services.portfolio_engine as pe
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="growthcap")
    baseline = _run_engine(session_factory, mid, advisor_id, preferences=None)
    baseline_equities = next(b["target_weight_bps"] for b in baseline["buckets"] if b["asset_class"] == "Aktien")
    pre_tilt_equities = baseline_equities - 150  # Baseline vor dem (im Default-Fall feuernden) Tilt

    prefs = {
        "policy": {}, "tilts": {}, "product": {}, "geo": {}, "assetClasses": {},
        "limits": {}, "simulation": {"monteCarloRuns": 50},
        "bands": {"Aktien": {"max_bps": pre_tilt_equities + 50}},
    }
    capped = _run_engine(session_factory, mid, advisor_id, preferences=prefs)
    capped_equities = next(b["target_weight_bps"] for b in capped["buckets"] if b["asset_class"] == "Aktien")
    reasoning = capped.get("reasoning") or []

    assert capped_equities <= pre_tilt_equities + 50, (
        f"Manuelles Aktien-Maximum ({pre_tilt_equities + 50} bps) durch den "
        f"Wachstums-Cashflow-Tilt verletzt (Ergebnis: {capped_equities} bps)"
    )
    assert not any("Wachstumsziele" in r for r in reasoning), (
        "Wachstums-Cashflow-Tilt hat trotz fehlendem Platz unter dem manuellen Maximum ausgeloest"
    )


# ===========================================================================
# 6. Schema-Validierung: AllocationPreferencesPayload.tilts / .bands
# ===========================================================================


def test_schema_accepts_valid_tilts_and_bands():
    payload = AllocationPreferencesPayload(
        tilts={"fossil": "exclude", "defense": "neutral"},
        bands={"Aktien": {"max_bps": 2000}, "bonds": {"min_bps": 1000, "target_bps": 3000, "max_bps": 5000}},
    )
    assert payload.tilts == {"fossil": "exclude", "defense": "neutral"}
    assert set(payload.bands.keys()) == {"Aktien", "bonds"}


def test_schema_rejects_unknown_tilt_key():
    with pytest.raises(pydantic.ValidationError, match="Tilt-Key"):
        AllocationPreferencesPayload(tilts={"tabacco": "exclude"})


def test_schema_rejects_unknown_tilt_value():
    with pytest.raises(pydantic.ValidationError, match="Tilt-Modus"):
        AllocationPreferencesPayload(tilts={"fossil": "ban"})


def test_schema_rejects_unknown_band_key():
    with pytest.raises(pydantic.ValidationError, match="Bandbreiten-Key"):
        AllocationPreferencesPayload(bands={"Kryptowaehrung": {"max_bps": 500}})


@pytest.mark.parametrize("key", ["fossil", "defense", "tobacco", "alcohol", "gaming", "nuclear"])
def test_schema_accepts_all_documented_tilt_keys(key):
    AllocationPreferencesPayload(tilts={key: "underweight"})


@pytest.mark.parametrize("bucket", ["equities", "bonds", "real_estate", "alternatives", "liquidity",
                                     "Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"])
def test_schema_accepts_all_documented_band_key_aliases(bucket):
    AllocationPreferencesPayload(bands={bucket: {"max_bps": 5000}})
