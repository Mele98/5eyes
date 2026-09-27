"""CORNISH-FISHER-NON-MONOTONIC-CLAMP-BOUNDS-001 (Kontrollrunde 2026-09-27).

Der bestehende Skew/Kurtosis-Clamp (services.optimizer.distributions:
_MAX_SKEW=1.0, _MAX_EXCESS_KURT=8.0) wurde mit dem Kommentar "clampen daher
die Inputs auf sichere Bereiche" eingefuehrt. Numerisch verifiziert: dieser
Bereich ist NICHT sicher. Bei skew=-1.0 (Rand des Clamps) mit
excess_kurt=0.0 (der erlaubte Minimalwert -- beides plausible, jeweils
einzeln unauffaellige Eingaben) faellt die Cornish-Fisher-Quantilfunktion ab
z~1.8 monoton, sodass g(5.0) = -5.25 < g(-3.0) = -3.25 -- die Transformation
kehrt sich ueber weite Teile der rechten Flanke komplett um. Das ist keine
Kleinigkeit am Rand: rund 27-53% der Standardnormal-Wahrscheinlichkeitsmasse
liegen je nach Skew/Kurt-Kombination in der betroffenen Zone.

Diese Datei sperrt drei Ebenen:
1. cornish_fisher_is_monotonic() selbst erkennt die bekannte kaputte
   Kombination und akzeptiert plausible sichere Kombinationen.
2. services.optimizer.scenario_engine.scenario_inputs_from_cma() (der
   tatsaechliche, produktiv erzwungene Monte-Carlo-Pfad) lehnt eine kaputte
   Kombination fail-closed ab statt eine invertierte Ertragsverteilung
   unbemerkt in die Optimierung/Simulation einzuspeisen.
3. services.cma_validation.validate_runtime_cma_completeness() (der
   Reporting-Engine-Gate) lehnt dieselbe Kombination ebenfalls ab.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cma_validation import CMAValidationError, validate_runtime_cma_completeness
from services.optimizer.constraints import OptimizerInputError
from services.optimizer.distributions import cornish_fisher_is_monotonic
from services.optimizer.scenario_engine import scenario_inputs_from_cma


# ============================================================================
# Ebene 1: der reine Monotonie-Check
# ============================================================================


def test_known_broken_combination_is_detected():
    """skew=-1.0 (Clamp-Rand), excess_kurt=0.0 (erlaubter Minimalwert) --
    numerisch verifiziert nicht-monoton (g(5.0) < g(-3.0))."""
    assert cornish_fisher_is_monotonic(-1.0, 0.0) is False


def test_mirror_broken_combination_is_detected():
    assert cornish_fisher_is_monotonic(1.0, 0.0) is False


def test_zero_skew_zero_kurt_is_identity_and_monotonic():
    assert cornish_fisher_is_monotonic(0.0, 0.0) is True


def test_realistic_equity_skew_kurt_is_monotonic():
    """Laut Modul-Docstring typische Aktien-Realdaten 1928-2024: s~-0.5, k~4-6."""
    assert cornish_fisher_is_monotonic(-0.5, 5.0) is True


def test_max_skew_with_sufficient_kurtosis_is_monotonic():
    """Derselbe Skew-Extremwert wie im kaputten Fall, aber mit genuegend
    Exzess-Kurtosis (Clamp-Obergrenze) bleibt die Transformation monoton --
    zeigt dass der Fix nicht pauschal jede Extremkombination verbietet,
    sondern gezielt die tatsaechlich kaputten Paare."""
    assert cornish_fisher_is_monotonic(-1.0, 8.0) is True


def test_values_outside_clamp_are_evaluated_at_clamped_edge():
    """Ein Rohwert weit ausserhalb [-1,1]/[0,8] wird zur Laufzeit ohnehin auf
    den Clamp-Rand gezogen -- die Pruefung muss also das geclampte Paar
    bewerten, nicht den Rohwert."""
    assert cornish_fisher_is_monotonic(-300.0, -500.0) == cornish_fisher_is_monotonic(-1.0, 0.0)


# ============================================================================
# Ebene 2: der aktive Monte-Carlo-Pfad (services.optimizer.scenario_engine)
# ============================================================================


def _make_cma(**overrides):
    """Minimal-CMA mit allen von scenario_inputs_from_cma()/_weighted_bucket_
    metrics() gelesenen Feldern, Skew/Kurt default 0 (harmlos)."""
    defaults = {
        "bonds_chf_ig_return_bps": 220,
        "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 220,
        "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620,
        "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700,
        "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450,
        "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300,
        "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80,
        "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "equities_skewness_bps": 0,
        "equities_excess_kurt_bps": 0,
        "bonds_skewness_bps": 0,
        "bonds_excess_kurt_bps": 0,
        "real_estate_skewness_bps": 0,
        "real_estate_excess_kurt_bps": 0,
        "alternatives_skewness_bps": 0,
        "alternatives_excess_kurt_bps": 0,
        "liquidity_skewness_bps": 0,
        "liquidity_excess_kurt_bps": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_scenario_inputs_from_cma_allows_zero_skew_kurt():
    inputs = scenario_inputs_from_cma(_make_cma())
    assert inputs.skew_bps[0] == 0.0


def test_scenario_inputs_from_cma_rejects_broken_equities_combination():
    """equities_skewness_bps=-10000 (=-1.0) mit excess_kurt_bps=0 (default)
    ist genau die numerisch verifizierte kaputte Kombination -- der aktive
    Monte-Carlo-Pfad muss das fail-closed ablehnen statt eine invertierte
    Ertragsverteilung zu simulieren."""
    cma = _make_cma(equities_skewness_bps=-10_000, equities_excess_kurt_bps=0)
    with pytest.raises(OptimizerInputError, match="nicht-monoton"):
        scenario_inputs_from_cma(cma)


def test_scenario_inputs_from_cma_rejects_broken_bonds_combination():
    """Guard laeuft ueber alle 5 Buckets, nicht nur 'equities'. Fuer 'bonds'
    greift bereits der frueher im Aufrufpfad liegende Reporting-Gate
    (validate_runtime_cma_completeness via _weighted_bucket_metrics) --
    Verteidigung in der Tiefe, beide Guards lehnen fail-closed ab."""
    cma = _make_cma(bonds_skewness_bps=-10_000, bonds_excess_kurt_bps=0)
    with pytest.raises(OptimizerInputError, match="nicht-monoton"):
        scenario_inputs_from_cma(cma)


def test_scenario_inputs_from_cma_allows_realistic_equity_skew():
    cma = _make_cma(equities_skewness_bps=-5_000, equities_excess_kurt_bps=5_000)
    inputs = scenario_inputs_from_cma(cma)
    assert inputs.skew_bps[0] == -5_000.0


# ============================================================================
# Ebene 3: der Reporting-Engine-Gate (services.cma_validation)
# ============================================================================


class _FakeCMA:
    """Duck-typed CH-CMA mit allen von validate_runtime_cma_completeness()
    verlangten Pflichtfeldern; Skew/Kurt-Felder default 0 (harmlos)."""

    def __init__(self, **overrides):
        self.jurisdiction = "CH"
        self.equity_ch_return_bps = 500
        self.equity_intl_return_bps = 600
        self.bonds_chf_ig_return_bps = 100
        self.bonds_fx_hedged_return_bps = 150
        self.real_estate_ch_return_bps = 300
        self.alternatives_gold_return_bps = 200
        self.liquidity_return_bps = 50
        self.equity_ch_vol_bps = 1500
        self.equity_intl_vol_bps = 1800
        self.bonds_chf_ig_vol_bps = 400
        self.bonds_fx_hedged_vol_bps = 450
        self.real_estate_ch_vol_bps = 900
        self.alternatives_gold_vol_bps = 1200
        self.liquidity_vol_bps = 10
        for key, value in overrides.items():
            setattr(self, key, value)


def test_runtime_completeness_allows_default_zero_skew_kurt():
    validate_runtime_cma_completeness(_FakeCMA())


def test_runtime_completeness_rejects_broken_skew_kurt_combination():
    cma = _FakeCMA(equities_skewness_bps=-10_000, equities_excess_kurt_bps=0)
    with pytest.raises(CMAValidationError, match="nicht-monoton"):
        validate_runtime_cma_completeness(cma)


def test_runtime_completeness_allows_realistic_equity_skew_kurt():
    cma = _FakeCMA(equities_skewness_bps=-5_000, equities_excess_kurt_bps=5_000)
    validate_runtime_cma_completeness(cma)
