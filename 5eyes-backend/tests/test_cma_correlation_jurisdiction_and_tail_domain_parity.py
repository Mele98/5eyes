"""CMA-CORRELATION-JURISDICTION-PROVENANCE-001 and
CMA-TAIL-PARAMETER-DOMAIN-PARITY-001 -- round 51 red tests.

See docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md
(Kontrollrunde 50 per the audit's own numbering, auditing commit 9148e28).

CMA-CORRELATION-JURISDICTION-PROVENANCE-001
---------------------------------------------
Confirmed by direct reading of services/portfolio_engine_cma.py::_build_cholesky_from_cma:
it reads only `cma.correlation_matrix_json` (via `parse_correlation_matrix_json`,
falling back to the module-level `_DEFAULT_CORRELATION_MATRIX` from
services/portfolio_engine.py, itself documented in scenario_engine.py as
"CH-Markt, konservativ") -- the function signature is
`_build_cholesky_from_cma(cma, crisis_strength=0.0)` and never reads any
jurisdiction field at all. A CH, DE or US CMA with an empty
correlation_matrix_json therefore all materialize the byte-identical
hardcoded Swiss-market correlation factor.

CMA-TAIL-PARAMETER-DOMAIN-PARITY-001
---------------------------------------
Confirmed by direct reading of three call sites that all ultimately invoke
the shared `bounded_cornish_fisher()` (services/return_moments.py) with
DIFFERENT pre-clamped domains for the same stored skew/excess-kurtosis
values:

- services/optimizer/scenario_engine.py::cornish_fisher_array() clamps to
  skew in [-1, 1] (`_MAX_SKEW = 1.0`) and excess kurtosis in [0, 8]
  (`_MAX_EXCESS_KURT = 8.0`) BEFORE calling bounded_cornish_fisher.
- services/portfolio_engine_mc_simulation.py's main Monte Carlo path reads
  `skew_per_bucket`/`excess_kurt_per_bucket` directly from the CMA
  (`float(getattr(cma, f"{b}_skewness_bps", 0) or 0) / 10000.0`, no clamp
  at all) and passes these RAW values straight into the same
  bounded_cornish_fisher() call.

The same persisted (skew=2.0, excess_kurt=-1.0) pair therefore produces a
genuinely different innovation from the optimizer path (which silently
clamps it to skew=1.0, excess_kurt=0.0 first) than from the main-MC path
(which uses 2.0/-1.0 unclamped) -- for the identical CMA row.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.portfolio_engine_cma import _build_cholesky_from_cma
from services.optimizer.scenario_engine import cornish_fisher_array
from services.return_moments import bounded_cornish_fisher


def _make_cma_jurisdiction_stub(jurisdiction):
    """Minimal CMA stub, same pattern as tests/test_cholesky_and_horizon.py's
    _make_cma -- only sets the fields the function actually reads, plus a
    jurisdiction field to prove it is never consulted."""
    return SimpleNamespace(correlation_matrix_json=None, jurisdiction=jurisdiction)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-CORRELATION-JURISDICTION-PROVENANCE-001 -- round 51 red test "
        "(_build_cholesky_from_cma reads no jurisdiction field at all; CH, "
        "DE and US CMAs with an empty correlation payload all materialize "
        "the identical hardcoded 'CH-Markt, konservativ' default matrix), "
        "see audit docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md"
    ),
)
def test_correlation_factor_should_differ_by_jurisdiction():
    """CH, DE and US capital-market assumptions with no explicit
    correlation payload must NOT all silently inherit the identical
    hardcoded Swiss-market correlation matrix -- each jurisdiction needs
    its own provenanced basis (or an explicit, scoped, evidenced fallback),
    not an anonymous shared default."""
    ch = _build_cholesky_from_cma(_make_cma_jurisdiction_stub("CH"))
    de = _build_cholesky_from_cma(_make_cma_jurisdiction_stub("DE"))
    us = _build_cholesky_from_cma(_make_cma_jurisdiction_stub("US"))

    assert ch != de or ch != us, (
        "CH, DE and US all produced the identical correlation factor from "
        "an empty payload -- the jurisdiction field is not influencing the "
        "effective risk basis at all"
    )


def test_positive_control_correlation_factor_is_deterministic_and_valid():
    """Positive control: calling the function twice with the same input
    gives the same, numerically valid (PSD) factor -- this correctness
    property must be preserved by any future jurisdiction-aware fix."""
    import numpy as np

    a = _build_cholesky_from_cma(_make_cma_jurisdiction_stub("CH"))
    b = _build_cholesky_from_cma(_make_cma_jurisdiction_stub("CH"))
    assert a == b
    factor = np.asarray(a)
    reconstructed = factor @ factor.T
    # Diagonal of a reconstructed correlation matrix must be 1.0.
    assert np.allclose(np.diag(reconstructed), 1.0, atol=1e-6)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-TAIL-PARAMETER-DOMAIN-PARITY-001 -- round 51 red test "
        "(optimizer path clamps skew to [-1,1]/excess-kurt to [0,8] before "
        "bounded_cornish_fisher; main-MC path passes raw unclamped CMA "
        "values to the same function, so identical stored tail moments "
        "produce different innovations between consumers), see audit "
        "docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md"
    ),
)
def test_optimizer_and_main_mc_should_apply_same_tail_moment_domain():
    """The same persisted (skew, excess_kurt) pair must produce the SAME
    Cornish-Fisher innovation whether consumed by the stochastic optimizer
    or by the general-purpose Monte Carlo engine -- today they silently
    diverge because only one of the two call sites clamps to the shared
    domain before calling the common bounded_cornish_fisher() primitive."""
    import numpy as np

    z = np.array([-2.0, 0.0, 2.0])
    raw_skew, raw_excess_kurt = 2.0, -1.0

    # Optimizer path: clamps first (skew -> 1.0, excess_kurt -> 0.0), then
    # calls the shared primitive.
    optimizer_result = cornish_fisher_array(
        z, np.array([raw_skew]), np.array([raw_excess_kurt])
    )

    # Main-MC path: calls the identical shared primitive directly with the
    # RAW, unclamped stored values (exact call shape from
    # portfolio_engine_mc_simulation.py).
    main_mc_result = np.array([
        bounded_cornish_fisher(zi, raw_skew, raw_excess_kurt) for zi in z
    ])

    assert np.allclose(optimizer_result.flatten(), main_mc_result), (
        f"optimizer path (clamped) gave {optimizer_result.flatten()} but "
        f"main-MC path (raw) gave {main_mc_result} for the identical "
        f"persisted skew={raw_skew}/excess_kurt={raw_excess_kurt} -- the "
        f"same CMA produces a consumer-dependent return distribution"
    )


def test_positive_control_in_domain_values_agree_across_consumers():
    """Positive control: for a skew/excess-kurt pair already INSIDE the
    optimizer's clamp domain ([-1,1]/[0,8]), both paths must agree exactly,
    since clamping is then a no-op -- this proves the divergence above is
    specifically caused by out-of-domain values, not a general mismatch
    between the two call sites."""
    import numpy as np

    z = np.array([-2.0, 0.0, 2.0])
    in_domain_skew, in_domain_excess_kurt = 0.5, 3.0

    optimizer_result = cornish_fisher_array(
        z, np.array([in_domain_skew]), np.array([in_domain_excess_kurt])
    )
    main_mc_result = np.array([
        bounded_cornish_fisher(zi, in_domain_skew, in_domain_excess_kurt) for zi in z
    ])

    assert np.allclose(optimizer_result.flatten(), main_mc_result)
