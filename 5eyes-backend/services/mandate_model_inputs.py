"""Fail-closed validation for opt-in mandate model components.

The feature flags in this module change the economic model.  Once a feature
is enabled, an incomplete input set must therefore be rejected at persistence
and runtime boundaries instead of silently switching that component off.
"""
from __future__ import annotations

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
        if reference_year is not None:
            model_year = int(reference_year)
        else:
            from services.mortality.horizon import mandate_reference_year
            model_year = mandate_reference_year(mandate)
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
    """Return complete mortality kwargs, or an empty dict when feature-off.

    Kontrollrunde 2026-09-19: mortality_fixed_offset_years carries the SAME
    deterministic, mandate-anchored death-year offset the report already
    shows as its "expected death" chart marker (services.mortality.horizon,
    shared with services/portfolio_engine_payload.py). The solver applies
    this identically to every Monte-Carlo path -- no more per-path random
    death sampling, which previously let an early-death path trivially
    satisfy any outflow_stream/cashflow_in_year goal regardless of whether
    the spending plan was actually sustainable while the client was alive.

    Computed here (not in the solver) so a resolution failure surfaces as
    the same MandateModelInputError -> OptimizerInputError fail-closed path
    as every other activated-feature validation in this module, rather than
    a separate error class deep in the solver.
    """
    validate_mortality_model_inputs(mandate)
    if not _feature_enabled(
        getattr(mandate, "use_mortality_simulation", 0),
        field_name="use_mortality_simulation",
    ):
        return {}
    from services.mortality.horizon import expected_death_year_offset_from_mandate
    try:
        offset_years = expected_death_year_offset_from_mandate(mandate)
    except Exception as exc:
        raise MandateModelInputError(
            "Activated mortality simulation could not resolve a death-year "
            "offset from the mandate's data."
        ) from exc
    return {
        "client_birth_year": int(mandate.client_birth_year),
        "client_sex": str(mandate.client_sex),
        "use_mortality_simulation": True,
        "mortality_fixed_offset_years": offset_years,
    }
