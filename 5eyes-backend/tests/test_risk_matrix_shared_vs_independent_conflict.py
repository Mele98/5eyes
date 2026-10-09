"""Acceptance test for the real GOAL-ACHIEVABILITY-ATTRIBUTION-001 conflict-
dedup fix (CERT-GOAL-FUNDING-001), Spec Sec. 11.2 Golden Case 5: "Ein
gemeinsamer Engpass vs zwei unabhaengige Engpaesse: unterschiedliche
Event-Summaries, Detailcodes und Kundentexte."

This is a NEW test (not one of the four pre-existing permanent red tests).
The pre-existing red test
tests/test_risk_matrix_conflict_shared_cause_double_counted.py::
test_zielkonflikt_cannot_distinguish_shared_cause_from_independent_causes
cannot pin this fix: it asserts, as literal preconditions,
``result_shared_cause == "zielkonflikt"`` AND
``result_independent_causes == "zielkonflikt"`` AND
``result_shared_cause != result_independent_causes`` in the same test body --
three conditions that cannot jointly hold for any implementation, since the
first two force both strings to be identical and the third requires them to
differ. See the PR description / GOAL-ACHIEVABILITY-ATTRIBUTION-001 report
for the full reasoning; that test is intentionally left red/untouched.

This test exercises the real fix in services/risk_matrix.py
(`classify_limiting_factor` + `_conflict_cause_signature`) with
non-contradictory assertions.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.risk_matrix import classify_limiting_factor


def _base_kwargs() -> dict:
    return dict(
        allocation_bps={"liquidity": 1000},
        risky_fraction=5000,
        max_risky_fraction=6000,
        min_liquidity_bps=500,
        bands={},
        achievability=[],
        optimization_status="converged",
    )


def _shared_single_shortfall_event_rows() -> list[dict]:
    return [
        {
            "goal_id": "goalA",
            "label": "Goal A (hart, CHF 90, faellig Jahr 1)",
            "target_kind": "minimize",
            "probability": 0.10,
            "tau": 0.90,
            "status": "nicht_erreichbar",
            "hardness": "Hart",
            "due_year": 1,
            "shortfall_source": "shared-initial-wealth-pot",
        },
        {
            "goal_id": "goalB",
            "label": "Goal B (primaer, CHF 20, faellig Jahr 1)",
            "target_kind": "minimize",
            "probability": 0.10,
            "tau": 0.90,
            "status": "nicht_erreichbar",
            "hardness": "Primaer",
            "due_year": 1,
            "shortfall_source": "shared-initial-wealth-pot",
        },
    ]


def _two_independent_shortfall_events_rows() -> list[dict]:
    return [
        {
            "goal_id": "goalC",
            "label": "Goal C (hart, faellig Jahr 1)",
            "target_kind": "minimize",
            "probability": 0.10,
            "tau": 0.90,
            "status": "nicht_erreichbar",
            "hardness": "Hart",
            "due_year": 1,
            "shortfall_source": "shortfall-event-year-1",
        },
        {
            "goal_id": "goalD",
            "label": "Goal D (primaer, faellig Jahr 15)",
            "target_kind": "minimize",
            "probability": 0.10,
            "tau": 0.90,
            "status": "nicht_erreichbar",
            "hardness": "Primaer",
            "due_year": 15,
            "shortfall_source": "shortfall-event-year-15",
        },
    ]


def test_shared_single_cause_is_distinguished_from_two_independent_causes():
    kwargs_shared = _base_kwargs()
    kwargs_shared["achievability"] = _shared_single_shortfall_event_rows()

    kwargs_independent = _base_kwargs()
    kwargs_independent["achievability"] = _two_independent_shortfall_events_rows()

    result_shared = classify_limiting_factor(**kwargs_shared)
    result_independent = classify_limiting_factor(**kwargs_independent)

    assert result_shared != result_independent, (
        "A single shared liquidity-shortfall event (2 goal rows, 1 cause) "
        "must not be classified the same way as 2 genuinely independent "
        f"shortfalls. Got shared={result_shared!r} independent={result_independent!r}"
    )
    # Two genuinely independent causes remain a real "zielkonflikt" --
    # unchanged legacy semantics for distinct causes.
    assert result_independent == "zielkonflikt"
    # A single shared cause is no longer silently double-counted as a
    # two-goal conflict.
    assert result_shared != "zielkonflikt"


def test_legacy_rows_without_attribution_fields_keep_conservative_behaviour():
    """Rows without due_year/shortfall_source/failure_event_id are each
    treated as their own independent cause (today's exact behaviour) -- no
    legacy caller is silently merged into a shared-cause event it never
    declared (Hard Invariant: no silent legacy upgrade).
    """
    kwargs = _base_kwargs()
    kwargs["achievability"] = [
        {"status": "nicht_erreichbar", "hardness": "hart"},
        {"status": "nicht_erreichbar", "hardness": "Primaer"},
    ]
    assert classify_limiting_factor(**kwargs) == "zielkonflikt"


def test_explicit_failure_event_id_dedups_even_without_due_year():
    """A caller that already attaches a typed failure_event_id (Spec Sec.
    5.5) gets dedup even if due_year/shortfall_source are absent.
    """
    kwargs = _base_kwargs()
    kwargs["achievability"] = [
        {"status": "nicht_erreichbar", "hardness": "hart", "failure_event_id": "evt-1"},
        {"status": "nicht_erreichbar", "hardness": "primaer", "failure_event_id": "evt-1"},
    ]
    assert classify_limiting_factor(**kwargs) != "zielkonflikt"

    kwargs_independent = _base_kwargs()
    kwargs_independent["achievability"] = [
        {"status": "nicht_erreichbar", "hardness": "hart", "failure_event_id": "evt-1"},
        {"status": "nicht_erreichbar", "hardness": "primaer", "failure_event_id": "evt-2"},
    ]
    assert classify_limiting_factor(**kwargs_independent) == "zielkonflikt"
