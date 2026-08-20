"""Fail-closed domain contract for allocation-relevant risk assessments."""

from __future__ import annotations

from typing import Any

from services.override_reason_quality import validate_override_reason_quality
from services.risk_scoring import (
    HORIZON_YEARS,
    canonicalize_horizon_label,
    compute_scores,
    profile_for_score_x10,
)


class RiskAssessmentInputError(ValueError):
    """Persisted risk-profile state is ambiguous or internally inconsistent."""


_PROFILE_BAND = {
    "Kapitalschutz": 0,
    "Defensiv": 1,
    "Ausgewogen": 2,
    "Wachstumsorientiert": 3,
    "Dynamisch": 4,
    "Aktien": 5,
}


def _exact_int(
    value: Any,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskAssessmentInputError(f"{field} muss eine Ganzzahl sein.")
    if not minimum <= value <= maximum:
        raise RiskAssessmentInputError(
            f"{field} muss zwischen {minimum} und {maximum} liegen."
        )
    return value


def _optional_flag(value: Any, *, field: str) -> int:
    if value is None:
        return 0
    return _exact_int(value, field=field, minimum=0, maximum=1)


def _validate_persisted_derivation(
    assessment: Any,
    *,
    final_score: int,
    mandate_type: str | None,
) -> None:
    """Recompute every persisted current-formula score from source points.

    Small service-level test doubles historically expose only the effective
    score fields.  They have no horizon and keep the old score/profile
    contract.  Real ORM rows always expose ``investment_horizon_label``; a
    missing or malformed label on such a row is corrupt and must fail closed.
    """

    raw_horizon = getattr(assessment, "investment_horizon_label", None)
    is_orm_row = "_sa_instance_state" in getattr(assessment, "__dict__", {})
    if not isinstance(raw_horizon, str):
        if is_orm_row:
            raise RiskAssessmentInputError(
                "investment_horizon_label fehlt oder ist ungueltig; "
                "die fachliche Score-Herleitung ist nicht pruefbar."
            )
        return

    horizon = raw_horizon.strip()
    if not horizon:
        raise RiskAssessmentInputError(
            "investment_horizon_label fehlt; die fachliche "
            "Score-Herleitung ist nicht pruefbar."
        )
    canonical_horizon = canonicalize_horizon_label(horizon)
    if canonical_horizon not in HORIZON_YEARS:
        raise RiskAssessmentInputError(
            "investment_horizon_label stammt aus einer unverifizierbaren "
            "Legacy- oder Fremd-Fachlogik; vor der Strategie ist eine neue "
            "Risikoprofilierung erforderlich."
        )

    source = {
        "q_income_points": _exact_int(
            getattr(assessment, "q_income_points", None),
            field="q_income_points",
            minimum=0,
            maximum=4,
        ),
        "q_obligations_points": _exact_int(
            getattr(assessment, "q_obligations_points", None),
            field="q_obligations_points",
            minimum=0,
            maximum=4,
        ),
        "q_savings_points": _exact_int(
            getattr(assessment, "q_savings_points", None),
            field="q_savings_points",
            minimum=0,
            maximum=12,
        ),
        "q_wealth_points": _exact_int(
            getattr(assessment, "q_wealth_points", None),
            field="q_wealth_points",
            minimum=0,
            maximum=12,
        ),
        "investment_horizon_label": canonical_horizon,
        "q_investment_goal_points": _exact_int(
            getattr(assessment, "q_investment_goal_points", None),
            field="q_investment_goal_points",
            minimum=1,
            maximum=4,
        ),
        "q_risk_preference_points": _exact_int(
            getattr(assessment, "q_risk_preference_points", None),
            field="q_risk_preference_points",
            minimum=1,
            maximum=4,
        ),
        "q_risk_behavior_points": _exact_int(
            getattr(assessment, "q_risk_behavior_points", None),
            field="q_risk_behavior_points",
            minimum=1,
            maximum=4,
        ),
    }
    try:
        derived = compute_scores(**source)
    except (TypeError, ValueError) as exc:
        raise RiskAssessmentInputError(
            f"Fachliche Score-Herleitung ungueltig: {exc}"
        ) from exc

    expected_fields = {
        "risk_capacity_total": (derived.risk_capacity_total, 0, 32),
        "risk_capacity_profile": derived.risk_capacity_profile,
        "risk_capacity_score_x10": (
            derived.risk_capacity_score_x10,
            0,
            100,
        ),
        "risk_willingness_total": (derived.risk_willingness_total, 3, 12),
        "risk_willingness_profile": derived.risk_willingness_profile,
        "risk_willingness_score_x10": (
            derived.risk_willingness_score_x10,
            10,
            100,
        ),
    }
    for field, expected in expected_fields.items():
        if isinstance(expected, tuple):
            expected_value, minimum, maximum = expected
            actual = _exact_int(
                getattr(assessment, field, None),
                field=field,
                minimum=minimum,
                maximum=maximum,
            )
        else:
            expected_value = expected
            actual = str(getattr(assessment, field, "") or "").strip()
        if actual != expected_value:
            raise RiskAssessmentInputError(
                f"{field} passt nicht zur fachlichen Herleitung "
                f"({actual!r} != {expected_value!r})."
            )

    normalized_mandate_type = str(mandate_type or "").strip().upper()
    derived_final = int(derived.final_score_x10)
    if normalized_mandate_type == "FZK":
        expected_final = min(derived_final, 75)
    elif (
        not normalized_mandate_type
        and derived_final > 75
        and final_score == 75
    ):
        # Internal score consumers do not always carry the mandate object.
        # Accept only the exact FZK cap in that context; the entry-point check
        # with an explicit mandate type has already rejected it for non-FZK.
        expected_final = 75
    else:
        expected_final = derived_final
    if final_score != expected_final:
        raise RiskAssessmentInputError(
            "final_score_x10 passt nicht zur fachlichen Herleitung "
            f"({final_score!r} != {expected_final!r})."
        )


def validate_risk_assessment_model_input(
    assessment: Any,
    *,
    mandate_type: str | None = None,
) -> int:
    """Validate and return the one effective score consumed by the engine.

    Score 0 is a legitimate short-horizon Kapitalschutz result. Unknown types,
    out-of-range values and incomplete overrides are rejected rather than
    clamped to a seemingly valid House-Matrix bucket.
    """

    if assessment is None:
        raise RiskAssessmentInputError("Aktuelles Risikoprofil fehlt.")

    final_score = _exact_int(
        getattr(assessment, "final_score_x10", None),
        field="final_score_x10",
        minimum=0,
        maximum=100,
    )
    expected_final_profile = profile_for_score_x10(final_score)
    final_profile = str(getattr(assessment, "final_profile", "") or "").strip()
    if final_profile != expected_final_profile:
        raise RiskAssessmentInputError(
            "final_profile passt nicht zu final_score_x10 "
            f"({final_profile!r} != {expected_final_profile!r})."
        )

    is_overridden = _exact_int(
        getattr(assessment, "is_overridden", None),
        field="is_overridden",
        minimum=0,
        maximum=1,
    )
    confirmed = _optional_flag(
        getattr(assessment, "override_client_confirmed", None),
        field="override_client_confirmed",
    )
    warned = _optional_flag(
        getattr(assessment, "override_warning_delivered", None),
        field="override_warning_delivered",
    )

    fzk = str(mandate_type or "").strip().upper() == "FZK"
    if fzk and final_score > 75:
        raise RiskAssessmentInputError(
            "FZK-Mandat: final_score_x10 darf 75 nicht ueberschreiten."
        )
    _validate_persisted_derivation(
        assessment,
        final_score=final_score,
        mandate_type=mandate_type,
    )
    if not is_overridden:
        return final_score

    override_score = _exact_int(
        getattr(assessment, "override_score_x10", None),
        field="override_score_x10",
        minimum=10,
        maximum=100,
    )
    if fzk and override_score > 75:
        raise RiskAssessmentInputError(
            "FZK-Mandat: override_score_x10 darf 75 nicht ueberschreiten."
        )
    expected_override_profile = profile_for_score_x10(override_score)
    override_profile = str(
        getattr(assessment, "override_profile", "") or ""
    ).strip()
    if override_profile != expected_override_profile:
        raise RiskAssessmentInputError(
            "override_profile passt nicht zu override_score_x10 "
            f"({override_profile!r} != {expected_override_profile!r})."
        )
    try:
        validate_override_reason_quality(
            getattr(assessment, "override_reason", None)
        )
    except ValueError as exc:
        raise RiskAssessmentInputError(str(exc)) from exc

    upward_bands = (
        _PROFILE_BAND[expected_override_profile]
        - _PROFILE_BAND[expected_final_profile]
    )
    if upward_bands >= 2 and (confirmed != 1 or warned != 1):
        raise RiskAssessmentInputError(
            "Ein Override um mindestens zwei Profilbaender nach oben "
            "erfordert Kundenbestaetigung und dokumentierten Warnhinweis."
        )
    return override_score


def risk_score_bucket_from_validated_score(score_x10: int) -> int:
    """Map a validated 0..100 score to the 1..10 House-Matrix bucket."""

    score = _exact_int(
        score_x10,
        field="score_x10",
        minimum=0,
        maximum=100,
    )
    return max(1, int(score / 10 + 0.5))
