"""DRAWDOWN-TIME-GRID-001 -- Blast Radius der Zeitgitter-Verfeinerung.

Die Verfeinerung des Max-Drawdown (``services/drawdown_refinement.py``) laeuft
NACH der Simulationsschleife und zieht aus einem eigenen, getrennt geseedeten
Zufallsstrom. Daraus folgt die Behauptung, auf der die Aenderung ruht:

    Ausser den Drawdown-Kennzahlen aendert sich kein einziger Wert des
    Simulationslaufs.

Das ist keine Nebenbemerkung. Haenge die Verfeinerung am Haupt-Zufallsstrom,
verschiebt sich die gesamte nachfolgende Zahlenfolge, und damit aendern sich
CAGR, VaR/CVaR, Verlustwahrscheinlichkeit, Vermoegensperzentile,
Erschoepfungswahrscheinlichkeiten, Zielerreichung und jede darauf gestuetzte
Zertifizierung -- eine Kennzahlen-Korrektur waere dann in Wahrheit eine
Neuberechnung des ganzen Mandats.

Dieser Test vergleicht deshalb einen Lauf MIT Verfeinerung gegen einen Lauf
mit auf Jahresgitter gezwungener Verfeinerung und verlangt Gleichheit fuer
jeden Schluessel, der nichts mit dem Drawdown zu tun hat.
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
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    users,
    wealth,
)

configure_mappers()

import services.portfolio_engine as pe
import services.portfolio_engine_mc_simulation as mc
from models.allocation import CapitalMarketAssumption
from services.drawdown_refinement import (
    DRAWDOWN_REFINEMENT_MODEL_VERSION,
    WEEKLY_SUB_STEPS,
    refine_max_drawdowns,
)
from services.portfolio_engine import (
    BUCKET_FIELDS,
    PortfolioSummary,
    _run_allocation_monte_carlo,
)

# Jeder Ausgabe-Schluessel, der die Drawdown-Kennzahl oder deren Nachweis
# betrifft. Alles andere MUSS identisch bleiben.
DRAWDOWN_KEYS = {
    "target_max_drawdown_p50_bps",
    "target_max_drawdown_p95_bps",
    "current_max_drawdown_p50_bps",
    "max_drawdown_model_version",
    "max_drawdown_sub_steps_per_year",
    "max_drawdown_bridge_log_volatility_bps",
    "target_max_drawdown_annual_grid_p50_bps",
    "target_max_drawdown_annual_grid_p95_bps",
    "current_max_drawdown_annual_grid_p50_bps",
}


def _cma_balanced() -> CapitalMarketAssumption:
    """Gemischtes Mandat -- genug Aktienquote, damit die Zeitgitter-Verzerrung
    ueberhaupt messbar ist (sie waechst mit der Volatilitaet)."""
    return CapitalMarketAssumption(
        id="cma-ddgrid",
        assumption_set_name="DDGRID",
        version=1,
        valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=170,
        bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=0,
        bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=600,
        equity_ch_vol_bps=1600,
        equity_intl_return_bps=600,
        equity_intl_vol_bps=1600,
        real_estate_ch_return_bps=0,
        real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0,
        alternatives_gold_vol_bps=0,
        liquidity_return_bps=0,
        liquidity_vol_bps=0,
        correlation_matrix_json="",
        sub_asset_class_assumptions_json="",
        created_by="t",
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


def _run(*, equities_bps: int = 5000, years: int = 15) -> dict:
    total = 1_000_000_00
    bonds_bps = 10000 - equities_bps
    adv = PortfolioSummary(
        amounts_rappen={
            key: (
                int(total * equities_bps / 10000)
                if key == "equities"
                else (int(total * bonds_bps / 10000) if key == "bonds" else 0)
            )
            for key in BUCKET_FIELDS
        },
        total_rappen=total,
    )
    targets = {
        key: (
            equities_bps
            if key == "equities"
            else (bonds_bps if key == "bonds" else 0)
        )
        for key in BUCKET_FIELDS
    }
    return _run_allocation_monte_carlo(
        advisory_summary=adv,
        cashflow_projection_series_rappen=[0] * years,
        goal_inflation_series_bps=[0] * years,
        targets=targets,
        minimums={key: 0 for key in BUCKET_FIELDS},
        maximums={key: 10000 for key in BUCKET_FIELDS},
        cma=_cma_balanced(),
        goals=[],
        advisory_wealth_rappen=adv.total_rappen,
        total_wealth_rappen=adv.total_rappen,
        policy=None,
        mandate_id="m-ddgrid-seed",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "calendar"},
        start_year=2026,
        target_total_rappen=adv.total_rappen,
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 600)


def _run_on_annual_grid(monkeypatch, **kwargs) -> dict:
    """Derselbe Lauf, aber mit der Verfeinerung auf sub_steps = 1 gezwungen.

    Reproduziert exakt das Verhalten vor DRAWDOWN-TIME-GRID-001, ohne den
    alten Code vorhalten zu muessen.
    """

    def _annual_only(paths, *, seed, **_ignored):
        return refine_max_drawdowns(paths, seed=seed, sub_steps=1)

    monkeypatch.setattr(mc, "refine_max_drawdowns", _annual_only)
    try:
        return _run(**kwargs)
    finally:
        monkeypatch.undo()


def test_refinement_changes_only_the_drawdown_keys(monkeypatch) -> None:
    """Jeder Schluessel ausserhalb von DRAWDOWN_KEYS bleibt bit-identisch.

    Derselbe Lauf zweimal -- einmal auf das Jahresgitter gezwungen, einmal mit
    aktiver Verfeinerung. Identischer Seed, identische Inputs; jede Differenz
    ausserhalb der Drawdown-Schluessel waere ein Leck des Bruecken-Zufallsstroms
    in die Haupt-Simulation.
    """
    annual_run = _run_on_annual_grid(monkeypatch)
    refined_run = _run()

    assert set(annual_run) == set(refined_run)

    differing = {
        key
        for key in annual_run
        if key not in DRAWDOWN_KEYS and annual_run[key] != refined_run[key]
    }
    assert not differing, (
        "Die Drawdown-Verfeinerung hat Werte ausserhalb der Drawdown-Kennzahlen "
        f"veraendert -- der Bruecken-Zufallsstrom leckt in die Haupt-Simulation: "
        f"{sorted(differing)}"
    )


def test_refinement_raises_the_reported_drawdown(monkeypatch) -> None:
    """Und die Drawdown-Kennzahlen selbst steigen messbar.

    Gegenstueck zum Test oben: ohne diese Schranke waere "nichts hat sich
    geaendert" auch dann erfuellt, wenn die Verfeinerung gar nicht greift.
    """
    annual_run = _run_on_annual_grid(monkeypatch)
    refined_run = _run()

    annual_p50 = annual_run["target_max_drawdown_p50_bps"]
    refined_p50 = refined_run["target_max_drawdown_p50_bps"]
    assert refined_p50 > annual_p50, (
        f"Verfeinerung ohne Wirkung: p50 {annual_p50} -> {refined_p50} bps"
    )
    assert refined_run["target_max_drawdown_p95_bps"] >= annual_run[
        "target_max_drawdown_p95_bps"
    ]
    # Der Jahresgitter-Wert wird als Nachweis mitgefuehrt und muss im
    # verfeinerten Lauf genau den Wert des Jahresgitter-Laufs reproduzieren --
    # er haengt nicht an der Verfeinerung.
    assert refined_run["target_max_drawdown_annual_grid_p50_bps"] == annual_p50


def test_evidence_fields_describe_the_applied_method() -> None:
    """Der Lauf weist die verwendete Methode aus, nicht nur die Zahl.

    Ohne diese Felder waere die Methodenaenderung im Audit-Trail nur ein
    unerklaerter Zahlensprung.
    """
    result = _run()
    assert result["max_drawdown_model_version"] == DRAWDOWN_REFINEMENT_MODEL_VERSION
    assert result["max_drawdown_sub_steps_per_year"] == WEEKLY_SUB_STEPS
    assert result["max_drawdown_bridge_log_volatility_bps"] > 0
    assert (
        result["target_max_drawdown_p50_bps"]
        >= result["target_max_drawdown_annual_grid_p50_bps"]
    )


def test_correction_is_larger_for_the_riskier_mandate() -> None:
    """Die Korrektur waechst mit dem Risiko -- durch die ganze Engine hindurch.

    Der eigentliche fachliche Schaden des Jahresgitters war nicht der absolute
    Fehler, sondern dass er die Spreizung zwischen den Risikoprofilen
    zusammendrueckt: riskante Mandate erschienen relativ sicherer als sie sind.
    Hier wird das nicht am Modul, sondern am echten Engine-Lauf geprueft.
    """
    defensive = _run(equities_bps=2000)
    aggressive = _run(equities_bps=8000)

    defensive_gap = (
        defensive["target_max_drawdown_p50_bps"]
        - defensive["target_max_drawdown_annual_grid_p50_bps"]
    )
    aggressive_gap = (
        aggressive["target_max_drawdown_p50_bps"]
        - aggressive["target_max_drawdown_annual_grid_p50_bps"]
    )
    assert aggressive_gap > defensive_gap, (
        "Korrektur muss beim riskanteren Mandat groesser sein, gemessen (bps): "
        f"defensiv={defensive_gap}, aggressiv={aggressive_gap}"
    )
