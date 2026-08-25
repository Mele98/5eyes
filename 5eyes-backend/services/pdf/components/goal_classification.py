"""Goal classification for Advisory-Report Monte-Carlo PDF charts.

This mirrors the reporting frontend's `goalClassification.ts` logic:
same status strings, same boundary rules, and the same defensive fallback
behaviour when Monte-Carlo paths are pending or malformed.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


GOAL_STATUS_ERREICHBAR = "erreichbar"
GOAL_STATUS_KNAPP = "knapp"
GOAL_STATUS_NICHT_ERREICHBAR = "nicht_erreichbar"
GOAL_STATUS_PAST = "past"
GOAL_STATUS_BEYOND_HORIZON = "beyond_horizon"
GOAL_STATUS_UNKNOWN = "unknown"


def classify_goals(
    goals: Iterable[dict[str, Any]],
    mc: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Classify each goal against p5/p50/p75 Monte-Carlo wealth paths.

    Rules copied from the frontend:
    - p50[t] >= target          -> erreichbar
    - p75[t] >= target > p50[t] -> knapp
    - p75[t] < target           -> nicht_erreichbar
    - target year before/after time_axis -> past / beyond_horizon
    - pending or malformed data -> unknown
    """
    goal_list = list(goals or [])
    if not mc or mc.get("data_pending"):
        return [_unknown(_goal_id(g)) for g in goal_list]

    time_axis = list(mc.get("time_axis") or [])
    p5 = list(mc.get("p5") or [])
    p50 = list(mc.get("p50") or [])
    p75 = list(mc.get("p75") or [])

    if (
        not time_axis
        or len(p5) != len(time_axis)
        or len(p50) != len(time_axis)
        or len(p75) != len(time_axis)
    ):
        return [_unknown(_goal_id(g)) for g in goal_list]

    start_year = _parse_int(time_axis[0])
    end_year = _parse_int(time_axis[-1])
    if start_year is None or end_year is None:
        return [_unknown(_goal_id(g)) for g in goal_list]

    out: list[dict[str, Any]] = []
    for goal in goal_list:
        goal_id = _goal_id(goal)
        target_year = _parse_year(goal.get("target_date"))
        target_amount = _parse_float(goal.get("target_amount_rappen"))

        if target_year is None or target_amount is None or target_amount <= 0:
            out.append(_unknown(goal_id))
            continue
        if target_year < start_year:
            out.append(_unknown(goal_id) | {"status": GOAL_STATUS_PAST})
            continue
        if target_year > end_year:
            out.append(_unknown(goal_id) | {"status": GOAL_STATUS_BEYOND_HORIZON})
            continue

        t_index = target_year - start_year
        try:
            p5_at_target = _parse_float(p5[t_index])
            p50_at_target = _parse_float(p50[t_index])
            p75_at_target = _parse_float(p75[t_index])
        except IndexError:
            out.append(_unknown(goal_id))
            continue

        if p5_at_target is None or p50_at_target is None or p75_at_target is None:
            out.append(_unknown(goal_id))
            continue

        if p50_at_target >= target_amount:
            status = GOAL_STATUS_ERREICHBAR
        elif p75_at_target >= target_amount:
            status = GOAL_STATUS_KNAPP
        else:
            status = GOAL_STATUS_NICHT_ERREICHBAR

        out.append({
            "goal_id": goal_id,
            "status": status,
            "t_index": t_index,
            "p5_at_target": p5_at_target,
            "p50_at_target": p50_at_target,
            "p75_at_target": p75_at_target,
        })
    return out


def _unknown(goal_id: str) -> dict[str, Any]:
    return {
        "goal_id": goal_id,
        "status": GOAL_STATUS_UNKNOWN,
        "t_index": None,
        "p5_at_target": None,
        "p50_at_target": None,
        "p75_at_target": None,
    }


def _goal_id(goal: dict[str, Any]) -> str:
    return str(goal.get("goal_id") or "")


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d{4})", str(value))
    if not match:
        return None
    return _parse_int(match.group(1))


def _parse_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "GOAL_STATUS_BEYOND_HORIZON",
    "GOAL_STATUS_ERREICHBAR",
    "GOAL_STATUS_KNAPP",
    "GOAL_STATUS_NICHT_ERREICHBAR",
    "GOAL_STATUS_PAST",
    "GOAL_STATUS_UNKNOWN",
    "classify_goals",
]
