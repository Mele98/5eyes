"""Fail-closed domain contract for allocation-relevant risk assessments."""

from __future__ import annotations

from typing import Any

from services.override_reason_quality import validate_override_reason_quality
from services.risk_scoring import profile_for_score_x10


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

