"""ADMIN-HOUSE-MATRIX-PERCENT-001 / CIO-Entscheid 3: Engine-Machbarkeit einer
Hausmatrix-Zeile unter einer Policy -- eine Quelle fuer Aktivierungs-Gate und
Admin-Editor.

Regel (E1): Die *wirksamen* Minima ergeben hoechstens 100 % und die *wirksamen*
Maxima mindestens 100 %. "Wirksam" heisst so, wie die Engine sie fuer jede
Berechnung bildet -- ``_baseline_target_bands()``:

* Aktien-Minimum = max(``equity_min_bps``, ``equity_minimum_bps``)
* Immobilien-/Alternative-Maximum = min(Zeile, Policy-Cap), das Minimum folgt
  einer tieferen Obergrenze nach unten (Policy gewinnt)
* Liquiditaets-Minimum = max(Zeile, Policy-Mindestquote), das Maximum wird bei
  Bedarf angehoben

Ist die Regel verletzt, scheitert ``_rebalance_to_total()`` fuer jedes Mandat
im Score-Band (ValueError). Das Eingabe-Schema (``HouseMatrixRowInput``)
laesst solche Zeilen durch, weil es die Policy und die Aktien-Mindestquote
nicht verrechnet.

Der JS-Validator ``computeAdminPolicyValidation()`` im Monolithen spiegelt
genau diese Funktion; ``tests/test_admin_house_matrix_editor_validation.py``
prueft den Gleichlauf.
"""
from __future__ import annotations

from typing import Any, Iterable

REASON_CODE_INFEASIBLE = "HOUSE_MATRIX_ENGINE_INFEASIBLE"

REASON_MIN_SUM_OVER_100 = "effective_min_sum_over_100"
REASON_MAX_SUM_UNDER_100 = "effective_max_sum_under_100"
REASON_BAND_INVERTED = "band_inverted"


def house_matrix_row_feasibility(house_matrix: Any, policy: Any) -> dict:
    """Wirksame Band-Summen einer Zeile und ob die Engine sie normalisieren kann.

    Returns ``{"feasible", "reasons", "effective_min_sum_bps",
    "effective_max_sum_bps"}``.
    """
    from services.portfolio_engine_house_matrix import _baseline_target_bands

    try:
        _targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    except ValueError:
        return {
            "feasible": False,
            "reasons": [REASON_BAND_INVERTED],
            "effective_min_sum_bps": None,
            "effective_max_sum_bps": None,
        }
    min_sum = sum(int(v) for v in minimums.values())
    max_sum = sum(int(v) for v in maximums.values())
    reasons = []
    if min_sum > 10000:
        reasons.append(REASON_MIN_SUM_OVER_100)
    if max_sum < 10000:
        reasons.append(REASON_MAX_SUM_UNDER_100)
    return {
        "feasible": not reasons,
        "reasons": reasons,
        "effective_min_sum_bps": min_sum,
        "effective_max_sum_bps": max_sum,
    }


def policy_activation_violations(house_matrix_rows: Iterable[Any], policy: Any) -> list[dict]:
    """Alle Zeilen, mit denen die Engine unter ``policy`` keine Allokation bilden kann."""
    violations = []
    for row in sorted(house_matrix_rows, key=lambda r: int(r.score_from)):
        check = house_matrix_row_feasibility(row, policy)
        if check["feasible"]:
            continue
        violations.append({
            "score_from": int(row.score_from),
            "score_to": int(row.score_to),
            "profile_name": row.profile_name,
            "reasons": check["reasons"],
            "effective_min_sum_bps": check["effective_min_sum_bps"],
            "effective_max_sum_bps": check["effective_max_sum_bps"],
        })
    return violations
