"""CMA-TAIL-MISSINGNESS-SEMANTICS-001 (Kontrollrunde 50, round 53 red test).

Audit doc: docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-
parity-integrity-audit.md

Claim under test: a CMA's per-bucket skewness/excess-kurtosis fields
(``{bucket}_skewness_bps`` / ``{bucket}_excess_kurt_bps``) are all nullable.
Both the stochastic optimizer (services/optimizer/scenario_engine.py) and the
main Monte Carlo engine (services/portfolio_engine_mc_simulation.py)
independently read them via the identical pattern
``getattr(cma, f"{bucket}_skewness_bps", 0) or 0``. That pattern makes
``None`` (nobody ever estimated/reviewed this moment) and an explicit ``0``
(a model owner reviewed the bucket and approved a symmetric/Gaussian
assumption) produce the IDENTICAL runtime value with no distinguishing state
anywhere downstream -- in ``ScenarioInputs``, in the main-MC log-parameters,
or in the CMA object itself (no per-field review/approval flag exists in
models/allocation.py, database.py or schemas/allocation.py; confirmed by
grep across the codebase).

``services/database.py`` documents this as a deliberate, known design choice
(~line 510: "Cornish-Fisher fat-tail Sampling. NULL/0 -> Normal-Verteilung"),
not an oversight. ``services/cma_validation.validate_runtime_cma_
completeness()`` -- the one Live-Gate that runs before every stochastic run
-- does not check these tail-moment fields for presence at all (it only
requires the 7 return/volatility fields to be non-None per jurisdiction); it
reads skew/kurt with the exact same ``getattr(..., None) or 0`` fallback
(lines ~161-162) purely to feed the Cornish-Fisher monotonicity guard, so a
CMA with every tail moment NULL passes "runtime completeness" today.

The existing test ``test_scenario_inputs_falls_back_to_zero_when_skew_kurt_
none`` (tests/test_optimizer_scenario_engine.py:428) already asserts this
None-becomes-zero collapse as the *expected* behaviour -- that is the
audit's own cited evidence that the ambiguity is baked into the test suite,
not merely into the implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cma_validation import validate_runtime_cma_completeness
from services.optimizer.scenario_engine import BUCKET_ORDER, scenario_inputs_from_cma


def _make_cma(**overrides):
    """Minimal CMA stub -- same field set/pattern as tests/test_optimizer_
    scenario_engine.py::_make_cma. All 7 jurisdiction-CH return/vol fields are
    present so scenario_inputs_from_cma() and validate_runtime_cma_
    completeness() both succeed; only the tail-moment fields vary per test."""
    defaults = {
        "jurisdiction": "CH",
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
        "equities_skewness_bps": None,
        "equities_excess_kurt_bps": None,
        "bonds_skewness_bps": None,
        "bonds_excess_kurt_bps": None,
        "real_estate_skewness_bps": None,
        "real_estate_excess_kurt_bps": None,
        "alternatives_skewness_bps": None,
        "alternatives_excess_kurt_bps": None,
        "liquidity_skewness_bps": None,
        "liquidity_excess_kurt_bps": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-TAIL-MISSINGNESS-SEMANTICS-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-"
        "parity-integrity-audit.md"
    ),
)
def test_never_estimated_vs_explicitly_gaussian_skew_are_indistinguishable():
    """RED: 'never estimated' and 'explicitly approved as Gaussian' must stay
    distinguishable somewhere in the runtime representation -- they currently
    do not.

    cma_never_estimated: equities_skewness_bps/excess_kurt_bps = None (nobody
    has ever estimated/reviewed this bucket's tail moments).
    cma_explicitly_gaussian: the same fields = 0 (a model owner reviewed the
    bucket and explicitly approved a symmetric/Gaussian assumption).

    Both go through the real production call path, scenario_inputs_from_cma()
    (services/optimizer/scenario_engine.py), which applies
    ``int(getattr(cma, f"{b}_skewness_bps", 0) or 0)``.
    """
    cma_never_estimated = _make_cma(
        equities_skewness_bps=None, equities_excess_kurt_bps=None,
    )
    cma_explicitly_gaussian = _make_cma(
        equities_skewness_bps=0, equities_excess_kurt_bps=0,
    )

    inputs_never_estimated = scenario_inputs_from_cma(cma_never_estimated)
    inputs_explicitly_gaussian = scenario_inputs_from_cma(cma_explicitly_gaussian)

    eq_idx = BUCKET_ORDER.index("equities")

    # This is the bug itself: both produce the identical skew/kurt value.
    assert inputs_never_estimated.skew_bps[eq_idx] == 0.0
    assert inputs_explicitly_gaussian.skew_bps[eq_idx] == 0.0

    # The two input objects have no field anywhere that distinguishes
    # "never estimated" from "explicitly reviewed and approved as Gaussian".
    # ScenarioInputs exposes no per-bucket provenance/state field at all, so
    # we probe for ANY plausible name a fix might introduce; today none
    # exists and the two namespaces are fully equal on every attribute that
    # is actually populated.
    never_state = getattr(inputs_never_estimated, "skew_state", None)
    gaussian_state = getattr(inputs_explicitly_gaussian, "skew_state", None)

    assert never_state != gaussian_state, (
        "scenario_inputs_from_cma() must distinguish an unestimated tail "
        "moment from an explicitly-approved-Gaussian one, but both "
        "currently collapse to the identical skew_bps=0.0/excess_kurt_bps="
        f"0.0 with no distinguishing state anywhere "
        f"(never_state={never_state!r}, gaussian_state={gaussian_state!r})."
    )


def test_runtime_completeness_gate_accepts_all_null_tail_moments_today():
    """POSITIVE CONTROL (not xfail): document precisely how far validate_
    runtime_cma_completeness()'s current scope extends.

    It is the one Live-Gate that runs before every stochastic run, but it
    only requires the 7 jurisdiction return/volatility fields to be
    non-None. A CMA whose tail moments (skewness/excess-kurtosis, all 5
    buckets) are entirely NULL -- i.e. nobody has ever estimated or reviewed
    them -- passes as "runtime complete" today. This confirms the
    ambiguity is not accidentally caught by a guard elsewhere.
    """
    cma_all_tail_moments_null = _make_cma(
        equities_skewness_bps=None,
        equities_excess_kurt_bps=None,
        bonds_skewness_bps=None,
        bonds_excess_kurt_bps=None,
        real_estate_skewness_bps=None,
        real_estate_excess_kurt_bps=None,
        alternatives_skewness_bps=None,
        alternatives_excess_kurt_bps=None,
        liquidity_skewness_bps=None,
        liquidity_excess_kurt_bps=None,
    )

    # Must not raise -- this is today's accepted (if ambiguous) behaviour.
    validate_runtime_cma_completeness(cma_all_tail_moments_null)
