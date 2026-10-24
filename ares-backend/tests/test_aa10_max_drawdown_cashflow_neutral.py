"""#AA-10 (2026-07-24): Max Drawdown ist cashflow-neutral (Markt-Index-Pfad).

Befund (aus Beratergespraech, Mandat mit starker Entnahme/Verzehr, ~59%
Obligationen — "super-defensives" Portfolio zeigte einen unplausibel hohen
Max Drawdown): `_max_drawdown_bps` lief vorher ueber target_by_year/
current_by_year — die enthalten den kumulierten Cashflow-Deficit (Entnahmen)
NETTO. Bei einem Entnahme-Mandat sinkt der "Pfad-Total"-Wert Jahr fuer Jahr
schon durch reine Ausgaben (Pensionsverzehr), unabhaengig vom Markt — dieser
geplante Verzehr wurde 1:1 als "Max Drawdown" (Marktrisiko-Kennzahl)
ausgewiesen.

CAGR (TWR, #AA-5) und VaR/CVaR/Loss-Prob (Jahr-1-Marktwert vor Cashflow,
#AA-4) waren bereits cashflow-bereinigt — Max Drawdown bekam diese
Behandlung nie. Fix: eigener Markt-Index-Pfad (derselbe post/pre-growth-
Faktor wie beim TWR, aber pro Jahr verkettet statt nur zum Endprodukt),
NIE durch Cashflow bewegt. Die Verzehr-Frage ("reicht das Geld?") deckt
weiterhin separat und korrekt `target_depletion_probability_pct` (#96) ab.
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from services.portfolio_engine import (
    BUCKET_FIELDS,
    PortfolioSummary,
    _run_allocation_monte_carlo,
    _max_drawdown_bps,
)
from models.allocation import CapitalMarketAssumption


def _cma_defensive() -> CapitalMarketAssumption:
    """~59% Obligationen-Profil: niedrige Rendite/Vola, wie ein 'super-
    defensives' Mandat — Bond-CMA-Werte konservativ (analog Session-Standard),
    keine High-Yield-Beimischung, um den reinen Bond-Markteffekt zu isolieren."""
    return CapitalMarketAssumption(
        id="cma-aa10", assumption_set_name="AA10", version=1, valid_from="2026-01-01", is_current=1,
        bonds_chf_ig_return_bps=170, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=0, bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=600, equity_ch_vol_bps=1600,
        equity_intl_return_bps=600, equity_intl_vol_bps=1600,
        real_estate_ch_return_bps=0, real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0, alternatives_gold_vol_bps=0,
        liquidity_return_bps=0, liquidity_vol_bps=0,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        created_by="t", created_at="2026-01-01T00:00:00.000Z", updated_at="2026-01-01T00:00:00.000Z",
    )


def _run(cashflow, targets_bonds_bps=5900):
    total = 1_000_000_00
    adv = PortfolioSummary(
        amounts_rappen={
            k: (int(total * targets_bonds_bps / 10000) if k == "bonds"
                else (total - int(total * targets_bonds_bps / 10000) if k == "equities" else 0))
            for k in BUCKET_FIELDS
        },
        total_rappen=total,
    )
    targets = {
        k: (targets_bonds_bps if k == "bonds"
            else (10000 - targets_bonds_bps if k == "equities" else 0))
        for k in BUCKET_FIELDS
    }
    return _run_allocation_monte_carlo(
        advisory_summary=adv,
        cashflow_projection_series_rappen=cashflow,
        goal_inflation_series_bps=[0] * len(cashflow),
        targets=targets,
        minimums={k: 0 for k in BUCKET_FIELDS},
        maximums={k: 10000 for k in BUCKET_FIELDS},
        cma=_cma_defensive(), goals=[],
        advisory_wealth_rappen=adv.total_rappen, total_wealth_rappen=adv.total_rappen,
        policy=None, mandate_id="m-aa10-seed",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "calendar"},
        start_year=2026, target_total_rappen=adv.total_rappen,
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 800)


def test_max_drawdown_unaffected_by_heavy_withdrawal_cashflow():
    """Herr-Holger-Szenario: identisches (defensives) Portfolio, aber mit
    starker jaehrlicher Entnahme (Pensionsverzehr) statt ohne Cashflow. Die
    Entnahme darf den ausgewiesenen Max Drawdown NICHT nach oben treiben --
    das ist eine reine Ausgaben-/Verzehr-Frage, keine Marktrisiko-Frage."""
    no_withdrawal = _run([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    # 8% p.a. Entnahme vom Startwert -- deutlich mehr als die defensive
    # Portfolio-Rendite (~1.7-2.2% Obligationen-dominiert) traegt.
    heavy_withdrawal = _run([-8_000_000] * 10)

    dd_no_cf = no_withdrawal["target_max_drawdown_p50_bps"]
    dd_heavy_cf = heavy_withdrawal["target_max_drawdown_p50_bps"]

    # Vor dem Fix waere dd_heavy_cf um GROESSENORDNUNGEN hoeher gewesen (die
    # Entnahme allein zehrt >60% des Vermoegens ueber 10 Jahre auf). Jetzt:
    # beide Werte spiegeln nur das (identische) Markt-Exposure.
    assert dd_heavy_cf == dd_no_cf, (
        f"Max Drawdown darf nicht von der Entnahme abhaengen: "
        f"ohne Cashflow={dd_no_cf}bps, mit starker Entnahme={dd_heavy_cf}bps"
    )


def test_max_drawdown_still_reflects_real_market_risk():
    """Sanity: ein aggressives (100% Aktien) Portfolio muss weiterhin einen
    hoeheren Max Drawdown zeigen als ein defensives (59% Obligationen) --
    der Fix darf die Kennzahl nicht auf 0 kappen, nur den Cashflow-Anteil
    entfernen."""
    defensive = _run([0] * 10, targets_bonds_bps=5900)
    aggressive = _run([0] * 10, targets_bonds_bps=0)
    assert aggressive["target_max_drawdown_p50_bps"] > defensive["target_max_drawdown_p50_bps"]
    assert defensive["target_max_drawdown_p50_bps"] > 0


def test_max_drawdown_deposit_neutral_like_twr():
    """Symmetrisch zur TWR-Cashflow-Neutralitaet (#AA-5): eine grosse
    EINZAHLUNG (statt Entnahme) darf den Max Drawdown ebenfalls nicht
    veraendern, wenn sie gleich in die Strategie investiert wird."""
    no_cf = _run([0, 0, 0, 0, 0])
    big_deposit = _run([50_000_000, 0, 0, 0, 0])
    assert no_cf["target_max_drawdown_p50_bps"] == big_deposit["target_max_drawdown_p50_bps"]


def test_current_max_drawdown_dramatically_lower_than_old_tainted_calc():
    """current_* (IST-Portfolio) bekommt dieselbe Markt-Index-Behandlung wie
    target_*. Anders als beim SOLL (calendar-rebalanced -> exakte Cashflow-
    Neutralitaet, siehe test_max_drawdown_unaffected_by_heavy_withdrawal_
    cashflow) wird das IST-Portfolio NIE rebalanced (das ist der Sinn von
    'IST' -- unveraendertes Halten). Eine Entnahme zehrt Buckets in fixer
    Reihenfolge (Liquiditaet, Obligationen, Aktien, ...) auf und verschiebt
    dadurch die KUENFTIGE Gewichtung -- ein legitimer, realer Kompositions-
    Drift-Effekt (das verbleibende Restportfolio wird tendenziell aktien-
    lastiger), keine Cashflow-Verzerrung. Exakte Gleichheit wie beim SOLL ist
    hier daher nicht das richtige Kriterium; stattdessen: der NEUE Wert muss
    weit unter dem liegen, was die ALTE (Cashflow-behaftete) Formel auf dem
    Netto-Vermoegenspfad geliefert haette (current_p50_series_rappen ist exakt
    dieser alte, ungefixte Pfad -- unveraendert im Response weiterhin
    verfuegbar, u.a. fuer die Endwert-Darstellung)."""
    heavy_withdrawal = _run([-8_000_000] * 10)
    new_dd = heavy_withdrawal["current_max_drawdown_p50_bps"]
    old_style_dd = _max_drawdown_bps(heavy_withdrawal["current_p50_series_rappen"])
    assert new_dd < old_style_dd * 0.5, (
        f"Neuer Max-Drawdown ({new_dd}bps) sollte weit unter dem alten, "
        f"cashflow-behafteten Wert ({old_style_dd}bps) liegen"
    )


def test_max_drawdown_helper_still_standard_peak_to_trough():
    """Die generische Funktion selbst ist unveraendert -- der Fix aendert nur,
    WELCHER Pfad ihr uebergeben wird, nicht ihre Mathematik."""
    assert _max_drawdown_bps([1000, 1200, 800, 1500, 600]) == 6000
