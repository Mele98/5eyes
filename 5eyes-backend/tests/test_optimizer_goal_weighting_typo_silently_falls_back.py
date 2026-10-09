"""Red test for OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001 (Kontrollrunde 36, Repro C).

Finding: `_goal_weighting_mode()` in services/optimizer/objective.py reads
`OPTIMIZER_GOAL_WEIGHTING` directly from `os.environ`, unvalidated:

    def _goal_weighting_mode() -> str:
        return (os.environ.get("OPTIMIZER_GOAL_WEIGHTING", "equal") or "equal").strip().lower()

Only the exact string "hardness" (after normalization) activates the
10x / 1x / 0.2x hardness-weighting multipliers (HARDNESS_WEIGHT). ANY other
value -- including an unset env var, or a typo like "hardnes" -- silently
falls back to equal weighting (factor 1.0 for every goal), with NO error, NO
warning, and no fail-closed behaviour. A typo therefore produces the exact
same (wrong, if "hardness" was intended) result as an unset variable, and a
caller/operator has no way to detect the misconfiguration.

This file documents the CONFIRMED repro (two goals -- one "Hart", one
"Opportunistisch" -- with identical shortfall):

    OPTIMIZER_GOAL_WEIGHTING unset:              ratio hard/opp = 1   (equal weighting)
    OPTIMIZER_GOAL_WEIGHTING="hardness" (exact):  ratio hard/opp = 50  (10 / 0.2)
    OPTIMIZER_GOAL_WEIGHTING="hardnes"  (typo):   ratio hard/opp = 1   (SAME as unset!)

See docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import shortfall_objective


def _make_liab(
    *,
    goal_id: str,
    hardness: str,
    weight_bps: int = 10000,
    target_kind: str = "wealth_at_t",
    target_amount_rappen: int = 1_000_000,
    target_year_index: int = 5,
    horizon_years: int = 10,
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=f"Test {goal_id}",
        goal_type="Vermoegensziel",
        target_kind=target_kind,
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=[0] * horizon_years,
        hardness_key=hardness,
        weight_bps=weight_bps,
    )


def _hard_vs_opportunistic_ratio() -> float:
    """Two goals, identical shortfall, differing only in hardness_key.

    Returns obj_hart / obj_opp under whatever OPTIMIZER_GOAL_WEIGHTING is
    currently set (or unset) in the environment -- caller controls that via
    monkeypatch before invoking this helper.
    """
    hart = _make_liab(goal_id="h", hardness="hart")
    opp = _make_liab(goal_id="o", hardness="opportunistisch")
    # Beide Goals werden um 1000 verfehlt (Wealth=999000 in Jahr 5), identischer Shortfall.
    wealth = np.full((10, 11), 999_000, dtype=np.float64)
    obj_hart = shortfall_objective([hart], wealth, initial_wealth_rappen=500_000, horizon_years=10)
    obj_opp = shortfall_objective([opp], wealth, initial_wealth_rappen=500_000, horizon_years=10)
    return obj_hart / obj_opp


# ============================================================================
# RED: typo silently falls back to equal weighting, no error, indistinguishable
# from "unset" -- this is the bug (OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001).
# ============================================================================


def test_typo_in_goal_weighting_env_var_should_not_silently_equal_unset(monkeypatch):
    """A typo'd OPTIMIZER_GOAL_WEIGHTING value must be rejected/flagged, not
    silently treated as equivalent to 'unset' (equal weighting).

    Today's (buggy) behaviour: ratio_typo == ratio_unset == 1.0, with zero
    distinction and zero error -- i.e. the typo is indistinguishable from a
    correctly-unset variable even though the operator's intent ("hardness")
    is never honoured. This assertion documents the fail-closed behaviour we
    WANT (either an exception, or at minimum a ratio that differs from the
    silent-fallback unset case) and currently FAILS against the real code.
    """
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
    ratio_unset = _hard_vs_opportunistic_ratio()
    assert ratio_unset == pytest.approx(1.0)

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardnes")  # typo for "hardness"

    # Desired fail-closed behaviour: an unrecognized value should raise ...
    with pytest.raises(ValueError):
        ratio_typo = _hard_vs_opportunistic_ratio()
        # ... or, if it does not raise, it must at least NOT silently equal
        # the unset ratio (i.e. it must not be mistaken for correctly-unset
        # equal weighting). Both branches currently fail: no exception is
        # raised, AND ratio_typo == ratio_unset == 1.0 exactly.
        assert ratio_typo != pytest.approx(ratio_unset)


# ============================================================================
# Positive controls (NOT xfail): lock in today's CORRECT behaviour as a
# baseline so a future fix for the above does not accidentally regress these.
# ============================================================================


def test_positive_control_unset_env_var_gives_equal_weighting_ratio_1(monkeypatch):
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
    ratio = _hard_vs_opportunistic_ratio()
    assert ratio == pytest.approx(1.0)


def test_positive_control_exact_hardness_value_gives_ratio_50(monkeypatch):
    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    ratio = _hard_vs_opportunistic_ratio()
    # hart=10.0 / opportunistisch=0.2 => 50x
    assert ratio == pytest.approx(50.0)
