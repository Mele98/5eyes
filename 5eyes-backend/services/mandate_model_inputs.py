"""Fail-closed validation for opt-in mandate model components.

The feature flags in this module change the economic model.  Once a feature
is enabled, an incomplete input set must therefore be rejected at persistence
and runtime boundaries instead of silently switching that component off.
"""
from __future__ import annotations

from datetime import date

from services.tax.overrides import parse_overrides_json
from services.mandate_preferences import (
    MandatePreferenceError,
    parse_default_building_blocks_json,
)


class MandateModelInputError(ValueError):
    """An activated mandate model component has incomplete domain inputs."""


def _feature_enabled(value, *, field_name: str) -> bool:
    if value is None or value is False or (type(value) is int and value == 0):
        return False
    if value is True or (type(value) is int and value == 1):
        return True
    raise MandateModelInputError(
        f"{field_name} muss als boolescher Wert (0/1) gespeichert sein."
    )


def validate_mortality_model_inputs(
    mandate,
    *,
    reference_year: int | None = None,
) -> None:
    """Validate the activated mortality model and its exact table domain.

    ``jurisdiction=None`` remains the documented legacy alias for ``CH``.
    Birth-year plausibility follows the exact supported BFS table range so a
    persisted activation can always be evaluated by the stochastic runtime.
    """
    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH").strip().upper()
    mortality_enabled = _feature_enabled(
        getattr(mandate, "use_mortality_simulation", 0),
        field_name="use_mortality_simulation",
    )
    if mortality_enabled:
        if jurisdiction != "CH":
            raise MandateModelInputError(
                "Activated mortality simulation requires jurisdiction CH, "
                "because only the Swiss BFS mortality table is approved."
            )
        birth_year = getattr(mandate, "client_birth_year", None)
        if isinstance(birth_year, bool) or not isinstance(birth_year, int):
            raise MandateModelInputError(
                "Activated mortality simulation requires client_birth_year "
                "in the supported BFS range and client_sex M/F."
            )
        model_year = int(reference_year if reference_year is not None else date.today().year)
        from services.mortality.bfs import BFS_2020_2022

        current_age = model_year - birth_year
        if current_age < 0 or current_age > int(BFS_2020_2022.max_age):
            raise MandateModelInputError(
                "Activated mortality simulation requires client_birth_year "
                "in the supported BFS range "
                f"(current age must be 0..{BFS_2020_2022.max_age})."
            )
        if getattr(mandate, "client_sex", None) not in ("M", "F"):
            raise MandateModelInputError(
                "Activated mortality simulation requires client_birth_year "
                "in the supported BFS range and client_sex M/F."
            )


def validate_tax_model_inputs(mandate) -> None:
    """Validate activated tax estimate and configured tax overrides."""
    tax_jurisdiction = str(
        getattr(mandate, "tax_jurisdiction", None) or ""
    ).strip()
    tax_estimate_enabled = _feature_enabled(
        getattr(mandate, "tax_estimate_in_cashflow_enabled", 0),
        field_name="tax_estimate_in_cashflow_enabled",
    )
    try:
        tax_overrides = parse_overrides_json(
            getattr(mandate, "tax_overrides_json", None)
        )
    except ValueError as exc:
        raise MandateModelInputError(str(exc)) from exc
    if tax_estimate_enabled and not tax_jurisdiction:
        raise MandateModelInputError(
            "tax_estimate_in_cashflow_enabled erfordert tax_jurisdiction."
        )
    if tax_overrides and not tax_jurisdiction:
        raise MandateModelInputError(
            "tax_overrides_json erfordert tax_jurisdiction."
        )


def validate_mandate_model_inputs(
    mandate,
    *,
    reference_year: int | None = None,
) -> None:
    """Validate all opt-in inputs that materially alter allocation results."""
    validate_mortality_model_inputs(mandate, reference_year=reference_year)
    validate_tax_model_inputs(mandate)
    try:
        parse_default_building_blocks_json(
            getattr(mandate, "default_building_blocks_json", None),
            jurisdiction=getattr(mandate, "jurisdiction", None),
        )
    except MandatePreferenceError as exc:
        raise MandateModelInputError(str(exc)) from exc


def mortality_solver_kwargs_from_mandate(mandate) -> dict:
    """Return complete mortality kwargs, or an empty dict when feature-off."""
    validate_mortality_model_inputs(mandate)
    if not _feature_enabled(
        getattr(mandate, "use_mortality_simulation", 0),
        field_name="use_mortality_simulation",
    ):
        return {}
    return {
        "client_birth_year": int(mandate.client_birth_year),
        "client_sex": str(mandate.client_sex),
        "use_mortality_simulation": True,
    }
