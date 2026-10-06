"""Red test for GOAL-ACHIEVABILITY-ATTRIBUTION-001 (round 47 audit, "Wirkung" point 3).

See docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

Context
-------
``services/portfolio_engine.py`` (around line 3941-3951) reads
``goal_achievability`` straight off the optimizer result and hands it, as-is,
to ``services.risk_matrix.classify_limiting_factor``::

    goal_achievability = list(getattr(optimizer_result, "goal_achievability", ()) or [])
    ...
    limiting_factor = classify_limiting_factor(
        allocation_bps=targets,
        ...,
        achievability=goal_achievability,
        optimization_status=optimization_status_for_limits,
    )

Each row in ``goal_achievability`` is produced by
``services/optimizer/objective.py::chance_constraint_penalty`` and only ever
carries these keys::

    {"goal_id", "label", "target_kind", "probability", "tau", "status", "hardness"}

There is no field anywhere in that row shape identifying *why* a goal became
unreachable -- no shared wealth-depletion-event id, no due-year correlation
key, nothing. ``classify_limiting_factor`` (services/risk_matrix.py:101-124)
then decides "zielkonflikt" (goal conflict) purely by counting rows::

    nicht_erreicht = [row for row in (achievability or [])
                      if row.get("status") == "nicht_erreichbar"
                      and _hardness_key(row.get("hardness")) in ("hart", "primär")]
    if len(nicht_erreicht) >= 2:
        return "zielkonflikt"

This is a pure row-count on ``status``/``hardness``. It cannot distinguish:

  (a) TWO hard/primary goals that are both unreachable because of the SAME
      single underlying liquidity shortfall (e.g. two one-off goals due in
      the identical year, both starved by the identical insufficient pot of
      wealth -- there is really only ONE conflict event), from

  (b) TWO hard/primary goals that are unreachable for two genuinely
      INDEPENDENT reasons (e.g. different due years, unrelated shortfalls --
      a real, distinct double-conflict).

Both scenarios produce byte-identical ``achievability`` row shapes (just
``status``/``hardness`` twice) and therefore the exact same
``classify_limiting_factor`` output, "zielkonflikt", with no way for a
caller to recover how many *distinct* underlying causes actually exist.

This test constructs both scenarios directly as ``classify_limiting_factor``
input (matching the dict shape used throughout
tests/test_risk_matrix_helpers.py -- no stochastic solver needed, since the
function only ever reads ``status``/``hardness`` off each row) and asserts
that the outputs can be told apart. They currently cannot, so this test is a
documented red test, wrapped in ``xfail(strict=True)`` so it turns into a
hard failure (not a silent skip) the moment someone "fixes" classification
without actually adding shared-cause attribution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.risk_matrix import classify_limiting_factor


def _base_kwargs() -> dict:
    """Mirrors tests/test_risk_matrix_helpers.py::_base_kwargs — the function's
    only non-achievability inputs, held constant so the classification
    outcome depends solely on the ``achievability`` rows under test.
    """
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
    """Two hard/primary goals, both due the SAME year, both starved by the
    SAME insufficient pot of wealth (CHF 100 initial, no growth, CHF 90 +
    CHF 20 due year 1 -- the audit's confirmed two-hard-goal shortfall
    scenario). There is exactly ONE underlying liquidity shortfall event
    here, reflected in extra descriptive keys (``due_year``,
    ``shortfall_source``) that a correct implementation would need in order
    to deduplicate -- but which classify_limiting_factor never looks at."""
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
    """Two hard/primary goals that are unreachable for two genuinely
    DIFFERENT reasons: different due years, unrelated shortfall sources.
    This is a real double-conflict -- two distinct underlying causes."""
    return [
        {
            "goal_id": "goalC",
            "label": "Goal C (hart, faellig Jahr 1, Liquiditaetsengpass Jahr 1)",
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
            "label": "Goal D (primaer, faellig Jahr 15, Marktpfad-Drawdown Jahr 15)",
            "target_kind": "minimize",
            "probability": 0.10,
            "tau": 0.90,
            "status": "nicht_erreichbar",
            "hardness": "Primaer",
            "due_year": 15,
            "shortfall_source": "shortfall-event-year-15",
        },
    ]


def test_achievability_rows_carry_no_shared_cause_or_event_identity():
    """Documents the absence directly: the achievability row shape produced
    by services/optimizer/objective.py::chance_constraint_penalty (goal_id,
    label, target_kind, probability, tau, status, hardness) has no field
    classify_limiting_factor actually reads besides status/hardness -- i.e.
    even the extra due_year/shortfall_source attribution keys we attach above
    for realism are invisible to the classifier. This is not a bug in this
    test; it is the documented absence under audit."""
    shared_rows = _shared_single_shortfall_event_rows()
    independent_rows = _two_independent_shortfall_events_rows()

    # Both scenarios differ in due_year / shortfall_source (the actual
    # root-cause attribution) but classify_limiting_factor's own kwargs
    # signature has no parameter that could ever receive such a thing --
    # it is only ever given status/hardness via dict.get(...).
    import inspect

    signature = inspect.signature(classify_limiting_factor)
    assert "achievability" in signature.parameters
    assert not any(
        "event" in name or "cause" in name for name in signature.parameters
    ), (
        "classify_limiting_factor has no parameter for a shared failure-event "
        "or root-cause id -- confirming GOAL-ACHIEVABILITY-ATTRIBUTION-001: "
        "there is no shared-cause attribution concept anywhere in this "
        f"function's signature: {list(signature.parameters)}"
    )

    # Sanity: the two scenarios really are different underlying situations.
    assert shared_rows[0]["due_year"] == shared_rows[1]["due_year"]
    assert independent_rows[0]["due_year"] != independent_rows[1]["due_year"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-ACHIEVABILITY-ATTRIBUTION-001 -- round 47 red test (conflict "
        "double-counting of shared failure event), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-"
        "attribution-audit.md"
    ),
)
def test_zielkonflikt_cannot_distinguish_shared_cause_from_independent_causes():
    """The core finding: classify_limiting_factor produces the IDENTICAL
    "zielkonflikt" verdict for a single shared liquidity-shortfall event
    (counted twice via two hard/primary rows) and for two genuinely
    independent shortfalls. A correct implementation would need to tell
    these apart -- e.g. report 1 conflict event vs. 2 -- but today's
    row-counting logic (``len(nicht_erreicht) >= 2``) cannot, because it
    never inspects anything beyond status/hardness.
    """
    kwargs_shared_cause = _base_kwargs()
    kwargs_shared_cause["achievability"] = _shared_single_shortfall_event_rows()

    kwargs_independent_causes = _base_kwargs()
    kwargs_independent_causes["achievability"] = _two_independent_shortfall_events_rows()

    result_shared_cause = classify_limiting_factor(**kwargs_shared_cause)
    result_independent_causes = classify_limiting_factor(**kwargs_independent_causes)

    # Documents today's (buggy) behaviour: both are classified "zielkonflikt".
    assert result_shared_cause == "zielkonflikt"
    assert result_independent_causes == "zielkonflikt"

    # What SHOULD hold: a single shared failure event must not be reported
    # the same way as two independent ones -- the caller (and ultimately the
    # advisor-facing PDF) needs to be able to tell "1 real conflict" apart
    # from "2 real conflicts". Today both produce the exact same string with
    # no distinguishing signal whatsoever, so this fails.
    assert result_shared_cause != result_independent_causes, (
        "classify_limiting_factor returned the SAME verdict "
        f"({result_shared_cause!r}) for a single shared liquidity-shortfall "
        "event (2 goal rows, 1 underlying cause) and for 2 genuinely "
        "independent shortfalls (2 goal rows, 2 underlying causes). The "
        "function has no shared-failure-event deduplication -- it is a pure "
        "row count on status/hardness -- so a single common cause can be "
        "double-counted as an independent multi-goal 'Zielkonflikt'."
    )
