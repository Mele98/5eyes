"""KGV-HORIZON-BINDING-001 and KGV-PROVENANCE-PUBLICATION-001 — round 49 red tests.

See docs/audits/2026-10-04-equity-valuation-kgv-calibration-horizon-and-publication-integrity-audit.md
(Kontrollrunde 47 per the audit's own numbering, auditing commit 23b5bfc).

KGV-HORIZON-BINDING-001
------------------------
The KGV mean-reversion model is explicitly horizon-dependent (a longer
horizon dampens the adjustment: ``max(0.3, 1 - 0.03*t)`` in
``mean_reversion.py``), and ``KGVMeanReversionModel.test_adjustment_dampening_for_long_horizon``
already proves this at the model level. But the only production call site,
``_compute_equity_kgv_adjustment()`` in services/optimizer/scenario_engine.py
(confirmed by direct reading), hardcodes:

    _KGV_DEFAULT_HORIZON_YEARS = 10
    ...
    adjustment = model.expected_annual_return_adjustment_bps(_KGV_DEFAULT_HORIZON_YEARS)

and ``scenario_inputs_from_cma(cma, sub_allocations=None)`` (confirmed via its
real signature) has no horizon parameter at all, so there is no way for a
5-year or 30-year run to pass its real horizon into this adjustment. Every
run, regardless of its actual horizon, gets the 10-year-calibrated number.

KGV-PROVENANCE-PUBLICATION-001
--------------------------------
``_build_kgv_status()`` in services/methodology_audit.py (confirmed by direct
reading) determines whether the KGV model counts as "active" purely from
three structured CMA fields (``equity_kgv_current_x10``,
``equity_kgv_fair_x10``, ``equity_kgv_alpha_x100``). The non-CH data pipeline
(jurisdiction/data_pipeline.py) can embed an already-computed KGV adjustment
directly into ``equity_home_return_bps`` without ever setting those three
structured fields (to avoid double-applying the model) — so a CMA that is
*genuinely* using KGV mean-reversion is reported as "Inaktiv" by the
methodology audit, which is then surfaced unchanged through
``advisory_report.py``, React ``Compliance.tsx`` and the PDF
``compliance_audit.py`` component.
"""
from __future__ import annotations

import pytest

from services.equity_valuation.mean_reversion import KGVMeanReversionModel
from services.optimizer.scenario_engine import scenario_inputs_from_cma
from services.methodology_audit import _build_kgv_status


class _BaseCMA:
    """Mirrors tests/equity_valuation/test_engine_integration.py's _BaseCMA
    fixture exactly, to stay consistent with the established test pattern
    for this module."""

    id = "base"
    bonds_chf_ig_return_bps = 200
    bonds_fx_hedged_return_bps = 250
    bonds_chf_ig_vol_bps = 400
    bonds_fx_hedged_vol_bps = 500
    bonds_hy_return_bps = None
    bonds_hy_vol_bps = None
    equity_ch_return_bps = 600
    equity_ch_vol_bps = 1500
    equity_intl_return_bps = 700
    equity_intl_vol_bps = 1700
    equity_em_return_bps = None
    equity_em_vol_bps = None
    real_estate_ch_return_bps = 400
    real_estate_ch_vol_bps = 800
    alternatives_gold_return_bps = 300
    alternatives_gold_vol_bps = 1200
    liquidity_return_bps = 50
    liquidity_vol_bps = 50
    correlation_matrix_json = ""
    bonds_ns_beta0_bps = None
    bonds_ns_beta1_bps = None
    bonds_ns_beta2_bps = None
    bonds_ns_lambda_x100 = None
    equity_kgv_current_x10 = None
    equity_kgv_fair_x10 = None
    equity_kgv_alpha_x100 = None


# ---------------------------------------------------------------------------
# KGV-HORIZON-BINDING-001
# ---------------------------------------------------------------------------


class _CMAOvervalued(_BaseCMA):
    equity_kgv_current_x10 = 250  # KGV 25.0
    equity_kgv_fair_x10 = 170     # fair 17.0
    equity_kgv_alpha_x100 = 15    # alpha 0.15


def test_positive_control_model_itself_is_genuinely_horizon_dependent():
    """Sanity/positive control: the underlying KGVMeanReversionModel really
    does dampen its adjustment for longer horizons (this is correct and
    must be preserved) -- the bug is specifically that production never
    passes a real horizon into it, not that the model is horizon-blind."""
    model = KGVMeanReversionModel(kgv_current=25.0, kgv_fair=17.0, alpha=0.15)
    adj_5 = model.expected_annual_return_adjustment_bps(5)
    adj_10 = model.expected_annual_return_adjustment_bps(10)
    adj_30 = model.expected_annual_return_adjustment_bps(30)
    assert adj_5 != adj_10 != adj_30
    # Audit's own reproduced numbers for this exact example:
    assert adj_5 == pytest.approx(-600.0, abs=0.01)
    assert adj_10 == pytest.approx(-494.117647, abs=0.01)
    assert adj_30 == pytest.approx(-211.764706, abs=0.01)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KGV-HORIZON-BINDING-001 -- round 49 red test (scenario_inputs_from_cma "
        "has no horizon parameter and _compute_equity_kgv_adjustment hardcodes "
        "_KGV_DEFAULT_HORIZON_YEARS=10, so a 5-year run materializes the same "
        "KGV adjustment as a 30-year run), see audit "
        "docs/audits/2026-10-04-equity-valuation-kgv-calibration-horizon-and-publication-integrity-audit.md"
    ),
)
def test_scenario_inputs_from_cma_should_reflect_the_run_horizon_not_a_fixed_10_years():
    """A 5-year run and a 30-year run share the same CMA (same KGV
    over-valuation), so a horizon-aware contract must produce two
    DIFFERENT materialized equity returns. Today scenario_inputs_from_cma
    takes no horizon argument at all, so both runs get the identical
    10-year-calibrated adjustment."""
    cma = _CMAOvervalued()
    base_equity = (600 + 700) / 2  # 650 bps, matches _BaseCMA pattern

    model = KGVMeanReversionModel(kgv_current=25.0, kgv_fair=17.0, alpha=0.15)
    expected_5y_equity = base_equity + model.expected_annual_return_adjustment_bps(5) / 100.0
    expected_30y_equity = base_equity + model.expected_annual_return_adjustment_bps(30) / 100.0

    # There is no way to even express "this run's horizon is 5 years" to
    # scenario_inputs_from_cma -- its signature is (cma, sub_allocations=None).
    # Both calls below are therefore byte-identical in production, which is
    # exactly the bug: assert that calling it under a stated 5-year context
    # and a stated 30-year context yields the horizon-correct, DIFFERENT
    # equity returns computed above.
    inputs_claimed_5y_horizon = scenario_inputs_from_cma(cma)
    inputs_claimed_30y_horizon = scenario_inputs_from_cma(cma)

    assert inputs_claimed_5y_horizon.mu_bps[0] == pytest.approx(
        expected_5y_equity, abs=0.01
    ), "a 5-year run must use the 5-year-calibrated KGV adjustment, not the fixed 10-year one"
    assert inputs_claimed_30y_horizon.mu_bps[0] == pytest.approx(
        expected_30y_equity, abs=0.01
    ), "a 30-year run must use the 30-year-calibrated KGV adjustment, not the fixed 10-year one"


# ---------------------------------------------------------------------------
# KGV-PROVENANCE-PUBLICATION-001
# ---------------------------------------------------------------------------


class _EmbeddedKgvCma:
    """Represents a data-derived non-CH CMA whose equity_home_return_bps
    already has the KGV mean-reversion effect baked in (per
    jurisdiction/data_pipeline.py's confirmed behavior), while the three
    structured KGV fields remain NULL to avoid double-applying the model."""

    id = "embedded-kgv-non-ch"
    equity_kgv_current_x10 = None
    equity_kgv_fair_x10 = None
    equity_kgv_alpha_x100 = None
    source_detail_json = (
        '{"equity_home_return_model": "nelson_siegel_plus_kgv_mean_reversion", '
        '"kgv_mean_reversion": {"kgv_current": 25.0, "kgv_fair": 17.0, '
        '"alpha": 0.15, "horizon_years": 10, "adjustment_bps": -494.117647}}'
    )


def test_positive_control_kgv_status_correctly_reports_inactive_when_truly_absent():
    """Positive control: a CMA with NO embedded KGV effect anywhere and no
    structured fields correctly reports inactive -- this must remain true."""
    class _NoKgvCma:
        equity_kgv_current_x10 = None
        equity_kgv_fair_x10 = None
        equity_kgv_alpha_x100 = None

    status = _build_kgv_status(_NoKgvCma())
    assert status["active"] is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KGV-PROVENANCE-PUBLICATION-001 -- round 49 red test (data-derived "
        "non-CH CMAs embed the KGV effect directly into equity_home_return_bps "
        "without setting the three structured KGV fields, so "
        "_build_kgv_status reports the model as inactive even though it is "
        "genuinely active and already applied), see audit "
        "docs/audits/2026-10-04-equity-valuation-kgv-calibration-horizon-and-publication-integrity-audit.md"
    ),
)
def test_kgv_status_must_not_report_inactive_when_effect_is_embedded_in_equity_return():
    """A CMA whose equity_home_return_bps already has KGV mean-reversion
    baked in (confirmed real behavior of the non-CH data pipeline) must be
    reported as KGV-active by the methodology audit, not inactive -- the
    advisor-facing compliance status must reflect the model that is
    actually shaping the published return, regardless of which of the two
    representations (raw structured parameters vs already-materialized
    return) produced it."""
    cma = _EmbeddedKgvCma()
    status = _build_kgv_status(cma)
    assert status["active"] is True, (
        "methodology audit reported KGV as inactive for a CMA whose "
        "equity return already embeds a genuine KGV mean-reversion "
        "adjustment -- this misrepresents the active model to React, PDF "
        "and advisory_report.py"
    )
