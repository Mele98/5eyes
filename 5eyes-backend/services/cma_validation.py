"""Pure, shared validation for CMA JSON model inputs.

The API schema, reporting engine and stochastic optimizer all call these
helpers.  Missing optional payloads remain backwards compatible; a present
payload is never silently replaced with defaults after a parse/domain error.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np


CORRELATION_DIMENSION = 5
NELSON_SIEGEL_DEFAULT_MATURITY_YEARS = 5.0
_MATRIX_TOLERANCE = 1e-8
_PSD_TOLERANCE = 1e-10
_SUB_CMA_ENTRY_FIELDS = frozenset({
    "asset_class",
    "expected_return_bps",
    "expected_volatility_bps",
})
_NELSON_SIEGEL_FIELDS = (
    "bonds_ns_beta0_bps",
    "bonds_ns_beta1_bps",
    "bonds_ns_beta2_bps",
    "bonds_ns_lambda_x100",
)
_EQUITY_KGV_FIELDS = (
    "equity_kgv_current_x10",
    "equity_kgv_fair_x10",
    "equity_kgv_alpha_x100",
)


class CMAValidationError(ValueError):
    """Invalid capital-market assumption input (never a fallback condition)."""


def validate_runtime_cma_completeness(cma: Any) -> None:
    """Require every bucket moment consumed by a live stochastic run.

    Runtime defaults are appropriate when materialising the initial reference
    dataset, not when interpreting an explicitly persisted current CMA.  A
    missing value here would make reporting and the optimizer silently invent
    a different model. Explicit zero remains a valid value.
    """
    jurisdiction = str(getattr(cma, "jurisdiction", None) or "CH").strip().upper()
    if jurisdiction == "CH":
        return_fields = (
            "equity_ch_return_bps",
            "equity_intl_return_bps",
            "bonds_chf_ig_return_bps",
            "bonds_fx_hedged_return_bps",
            "real_estate_ch_return_bps",
            "alternatives_gold_return_bps",
            "liquidity_return_bps",
        )
        volatility_fields = (
            "equity_ch_vol_bps",
            "equity_intl_vol_bps",
            "bonds_chf_ig_vol_bps",
            "bonds_fx_hedged_vol_bps",
            "real_estate_ch_vol_bps",
            "alternatives_gold_vol_bps",
            "liquidity_vol_bps",
        )
    else:
        return_fields = (
            "equity_home_return_bps",
            "bonds_home_ig_return_bps",
            "real_estate_home_return_bps",
            "alternatives_gold_return_bps",
            "liquidity_return_bps",
        )
        volatility_fields = (
            "equity_home_vol_bps",
            "bonds_home_ig_vol_bps",
            "real_estate_home_vol_bps",
            "alternatives_gold_vol_bps",
            "liquidity_vol_bps",
        )

    missing = [
        field_name
        for field_name in (*return_fields, *volatility_fields)
        if getattr(cma, field_name, None) is None
    ]
    if missing:
        raise CMAValidationError(
            "Aktuelle CMA ist fuer den stochastischen Lauf unvollstaendig; "
            f"fehlende Modellfelder: {', '.join(missing)}."
        )

    for field_name in return_fields:
        value = _finite_scaled_integer(
            getattr(cma, field_name), field_name=field_name
        )
        if value <= -10_000:
            raise CMAValidationError(
                f"{field_name} muss groesser als -100 % sein."
            )
    for field_name in volatility_fields:
        value = _finite_scaled_integer(
            getattr(cma, field_name), field_name=field_name
        )
        if value < 0:
            raise CMAValidationError(
                f"{field_name} darf nicht negativ sein."
            )


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token!r}")


def _load_json_payload(raw_payload: str, *, field_name: str) -> Any:
    if not isinstance(raw_payload, str):
        raise CMAValidationError(f"{field_name} must be a JSON string.")
    try:
        return json.loads(raw_payload, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CMAValidationError(
            f"{field_name} ist kein gültiges JSON (not valid JSON): {exc}"
        ) from exc


def _finite_number(value: Any, *, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CMAValidationError(f"{location} muss eine Zahl sein.")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise CMAValidationError(f"{location} muss endlich (finite) sein.") from exc
    if not math.isfinite(number):
        raise CMAValidationError(f"{location} muss endlich (finite) sein.")
    return number


def _complete_optional_group(
    source: Any,
    fields: Sequence[str],
) -> tuple[Any, ...] | None:
    """Return a complete optional group; any missing member keeps it inactive.

    Historical rows deliberately allow partially populated advanced models.
    They are inactive until every field is present. Once complete, however,
    the group is model input and must pass strict domain validation.
    """
    values = tuple(getattr(source, field, None) for field in fields)
    if any(value is None for value in values):
        return None
    return values


def _finite_scaled_integer(value: Any, *, field_name: str) -> int:
    number = _finite_number(value, location=field_name)
    if not number.is_integer():
        raise CMAValidationError(
            f"{field_name} muss eine endliche Ganzzahl (scaled integer) sein."
        )
    # Preserve exact database integers. Converting them back from float would
    # otherwise round values above 2**53 before the range/derived checks.
    return int(value) if isinstance(value, int) else int(number)


def validate_nelson_siegel_parameters(
    cma: Any,
) -> tuple[float, float, float, float] | None:
    """Validate an active Nelson-Siegel CMA group.

    Values use the persisted scaled units (betas in bps, lambda * 100).
    A partial group remains inactive for historical compatibility. A complete
    group must be finite, integral in its persisted units, have lambda > 0,
    and produce economically defined (> -100%) short-, long- and runtime
    maturity yields.
    """
    raw_values = _complete_optional_group(cma, _NELSON_SIEGEL_FIELDS)
    if raw_values is None:
        return None

    beta0, beta1, beta2, lambda_x100 = (
        _finite_scaled_integer(value, field_name=field_name)
        for field_name, value in zip(_NELSON_SIEGEL_FIELDS, raw_values)
    )
    if lambda_x100 <= 0:
        raise CMAValidationError("bonds_ns_lambda_x100 muss groesser als 0 sein.")

    lambda_ = float(lambda_x100) / 100.0
    maturity = NELSON_SIEGEL_DEFAULT_MATURITY_YEARS
    lambda_maturity = lambda_ * maturity
    if not math.isfinite(lambda_maturity):
        raise CMAValidationError(
            "bonds_ns_lambda_x100 ist ausserhalb des berechenbaren Bereichs."
        )
    factor1 = -math.expm1(-lambda_maturity) / lambda_maturity
    factor2 = factor1 - math.exp(-lambda_maturity)
    beta0_float = float(beta0)
    beta1_float = float(beta1)
    beta2_float = float(beta2)
    yields = {
        "bonds_ns_short_rate_bps": beta0_float + beta1_float,
        "bonds_ns_long_rate_bps": beta0_float,
        "bonds_ns_5y_yield_bps": (
            beta0_float + beta1_float * factor1 + beta2_float * factor2
        ),
    }
    for field_name, value in yields.items():
        if not math.isfinite(value):
            raise CMAValidationError(f"{field_name} muss endlich (finite) sein.")
        if value <= -10_000.0:
            raise CMAValidationError(
                f"{field_name} muss groesser als -100 % sein."
            )

    return float(beta0), float(beta1), float(beta2), lambda_


def validate_equity_kgv_parameters(
    cma: Any,
) -> tuple[float, float, float] | None:
    """Validate an active KGV mean-reversion CMA group.

    Persisted units are KGV * 10 and alpha * 100. Thus alpha_x100=15 means
    0.15 and the inclusive unit-interval contract is 0..100 in the database.
    Partial groups remain inactive; complete invalid groups fail closed.
    """
    raw_values = _complete_optional_group(cma, _EQUITY_KGV_FIELDS)
    if raw_values is None:
        return None

    current_x10, fair_x10, alpha_x100 = (
        _finite_scaled_integer(value, field_name=field_name)
        for field_name, value in zip(_EQUITY_KGV_FIELDS, raw_values)
    )
    if current_x10 <= 0:
        raise CMAValidationError("equity_kgv_current_x10 muss groesser als 0 sein.")
    if fair_x10 <= 0:
        raise CMAValidationError("equity_kgv_fair_x10 muss groesser als 0 sein.")
    if not 0 <= alpha_x100 <= 100:
        raise CMAValidationError(
            "equity_kgv_alpha_x100 muss im Bereich [0, 100] liegen."
        )

    current = float(current_x10) / 10.0
    fair = float(fair_x10) / 10.0
    alpha = float(alpha_x100) / 100.0
    # Guard the downstream formula against overflow even though every
    # individual parameter is finite.
    relative_undervaluation = (fair - current) / fair
    if not math.isfinite(relative_undervaluation * alpha * 10_000.0):
        raise CMAValidationError(
            "equity_kgv_current_x10/equity_kgv_fair_x10 erzeugen kein "
            "endliches Mean-Reversion-Adjustment."
        )

    return current, fair, alpha


def validate_correlation_matrix(
    matrix: Sequence[Sequence[Any]],
    *,
    dimension: int = CORRELATION_DIMENSION,
    field_name: str = "correlation_matrix_json",
) -> tuple[tuple[float, ...], ...]:
    """Validate shape/range/symmetry and positive semidefiniteness."""
    if isinstance(matrix, np.ndarray):
        matrix = matrix.tolist()
    if (
        isinstance(matrix, (str, bytes))
        or not isinstance(matrix, Sequence)
        or len(matrix) != dimension
        or any(
            isinstance(row, (str, bytes))
            or not isinstance(row, Sequence)
            or len(row) != dimension
            for row in matrix
        )
    ):
        raise CMAValidationError(
            f"{field_name} muss eine {dimension}x{dimension}-Matrix "
            f"(Liste von {dimension} Listen mit je {dimension} Zahlen) sein."
        )

    normalized: list[list[float]] = []
    for i, row in enumerate(matrix):
        normalized_row: list[float] = []
        for j, value in enumerate(row):
            number = _finite_number(value, location=f"{field_name}[{i}][{j}]")
            if number < -1.0 or number > 1.0:
                raise CMAValidationError(
                    f"{field_name}[{i}][{j}]={number} liegt ausserhalb "
                    "des gueltigen Korrelationsbereichs [-1, 1]."
                )
            normalized_row.append(number)
        if abs(normalized_row[i] - 1.0) > _MATRIX_TOLERANCE:
            raise CMAValidationError(
                f"{field_name} Diagonale [{i}][{i}]={normalized_row[i]} muss "
                "1.0 sein (Korrelation eines Assets mit sich selbst)."
            )
        normalized.append(normalized_row)

    array = np.asarray(normalized, dtype=np.float64)
    if not np.allclose(
        array,
        array.T,
        rtol=0.0,
        atol=_MATRIX_TOLERANCE,
    ):
        mismatch = np.argwhere(np.abs(array - array.T) > _MATRIX_TOLERANCE)[0]
        i, j = int(mismatch[0]), int(mismatch[1])
        raise CMAValidationError(
            f"{field_name} ist nicht symmetrisch bei [{i}][{j}]="
            f"{array[i, j]} vs [{j}][{i}]={array[j, i]}."
        )

    min_eigenvalue = float(np.linalg.eigvalsh(array)[0])
    if min_eigenvalue < -_PSD_TOLERANCE:
        raise CMAValidationError(
            f"{field_name} muss positiv semidefinit sein; kleinster "
            f"Eigenwert ist {min_eigenvalue:.6g}."
        )

    return tuple(tuple(float(value) for value in row) for row in array)


def parse_correlation_matrix_json(
    raw_payload: str | None,
    *,
    default_matrix: Sequence[Sequence[Any]] | None = None,
    dimension: int = CORRELATION_DIMENSION,
) -> tuple[tuple[float, ...], ...] | None:
    """Parse a correlation payload; only an absent payload may use defaults."""
    if raw_payload is None or raw_payload == "":
        if default_matrix is None:
            return None
        return validate_correlation_matrix(default_matrix, dimension=dimension)

    parsed = _load_json_payload(
        raw_payload,
        field_name="correlation_matrix_json",
    )
    return validate_correlation_matrix(parsed, dimension=dimension)


def correlation_factor(
    matrix: Sequence[Sequence[Any]],
) -> np.ndarray:
    """Return ``F`` with ``F @ F.T == matrix`` for any valid PSD matrix.

    Positive-definite inputs retain the historical lower-triangular Cholesky
    representation.  Singular but valid PSD correlations use an eigen-factor
    instead of being replaced by an unrelated default or identity matrix.
    """
    normalized = validate_correlation_matrix(matrix, dimension=len(matrix))
    array = np.asarray(normalized, dtype=np.float64)
    try:
        return np.linalg.cholesky(array)
    except np.linalg.LinAlgError:
        eigenvalues, eigenvectors = np.linalg.eigh(array)
        if float(eigenvalues[0]) < -_PSD_TOLERANCE:
            # Defensive: validate_correlation_matrix already enforces this.
            raise CMAValidationError("Correlation matrix is not positive semidefinite.")
        clipped = np.clip(eigenvalues, 0.0, None)
        return eigenvectors @ np.diag(np.sqrt(clipped))


def _integral_bps(value: Any, *, location: str) -> int:
    if isinstance(value, bool):
        raise CMAValidationError(
            f"{location} must be an integer number of basis points."
        )
    number = _finite_number(value, location=location)
    if not number.is_integer():
        raise CMAValidationError(
            f"{location} must be an integer number of basis points."
        )
    return int(number)


def _optional_entry_value(
    raw: Mapping[str, Any],
    defaults: Mapping[str, Any],
    key: str,
) -> Any:
    value = raw.get(key) if key in raw else None
    if value is None:
        value = defaults.get(key)
    return value


def parse_sub_asset_class_assumptions_json(
    raw_payload: str | None,
    *,
    defaults: Mapping[str, Mapping[str, Any]] | None = None,
    require_complete: bool = False,
) -> dict[str, dict[str, int | str]]:
    """Parse and normalize Sub-CMA assumptions.

    ``0`` is an explicit value.  ``None``/a missing key alone inherits a
    known default for backwards compatibility with historical partial rows.
    """
    defaults = defaults or {}
    parsed: Any = {}
    if raw_payload is not None and raw_payload != "":
        parsed = _load_json_payload(
            raw_payload,
            field_name="sub_asset_class_assumptions_json",
        )
    if not isinstance(parsed, Mapping):
        raise CMAValidationError(
            "sub_asset_class_assumptions_json must be a JSON object."
        )

    normalized: dict[str, dict[str, int | str]] = {}
    labels = list(defaults)
    labels.extend(label for label in parsed if label not in defaults)
    for raw_label in labels:
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise CMAValidationError(
                "sub_asset_class_assumptions_json keys must be non-empty strings."
            )
        label = raw_label.strip()
        raw_entry = parsed.get(raw_label, {})
        if not isinstance(raw_entry, Mapping):
            raise CMAValidationError(
                f"sub_asset_class_assumptions_json[{label!r}] must be a JSON object."
            )
        unknown_fields = sorted(
            set(raw_entry.keys()) - _SUB_CMA_ENTRY_FIELDS,
            key=str,
        )
        if unknown_fields:
            raise CMAValidationError(
                f"sub_asset_class_assumptions_json[{label!r}] contains unknown "
                f"fields: {unknown_fields}."
            )
        default_entry = defaults.get(raw_label, {})

        asset_class_value = _optional_entry_value(
            raw_entry,
            default_entry,
            "asset_class",
        )
        if asset_class_value is not None and (
            not isinstance(asset_class_value, str)
            or not asset_class_value.strip()
        ):
            raise CMAValidationError(
                f"sub_asset_class_assumptions_json[{label!r}].asset_class "
                "must be a non-empty string."
            )
        if asset_class_value is None and require_complete:
            raise CMAValidationError(
                f"sub_asset_class_assumptions_json[{label!r}] is missing "
                "asset_class."
            )
        default_asset_class = default_entry.get("asset_class")
        if (
            default_asset_class is not None
            and "asset_class" in raw_entry
            and raw_entry.get("asset_class") is not None
            and str(asset_class_value).strip() != str(default_asset_class).strip()
        ):
            raise CMAValidationError(
                f"sub_asset_class_assumptions_json[{label!r}].asset_class "
                f"must remain {default_asset_class!r}."
            )

        return_value = _optional_entry_value(
            raw_entry,
            default_entry,
            "expected_return_bps",
        )
        volatility_value = _optional_entry_value(
            raw_entry,
            default_entry,
            "expected_volatility_bps",
        )

        if return_value is None:
            if require_complete:
                raise CMAValidationError(
                    f"sub_asset_class_assumptions_json[{label!r}] is missing "
                    "expected_return_bps."
                )
            return_bps = None
        else:
            return_bps = _integral_bps(
                return_value,
                location=(
                    f"sub_asset_class_assumptions_json[{label!r}]"
                    ".expected_return_bps"
                ),
            )
            if return_bps <= -10_000:
                raise CMAValidationError(
                    f"sub_asset_class_assumptions_json[{label!r}]"
                    ".expected_return_bps must be greater than -100%."
                )

        if volatility_value is None:
            if require_complete:
                raise CMAValidationError(
                    f"sub_asset_class_assumptions_json[{label!r}] is missing "
                    "expected_volatility_bps."
                )
            volatility_bps = None
        else:
            volatility_bps = _integral_bps(
                volatility_value,
                location=(
                    f"sub_asset_class_assumptions_json[{label!r}]"
                    ".expected_volatility_bps"
                ),
            )
            if volatility_bps < 0:
                raise CMAValidationError(
                    f"sub_asset_class_assumptions_json[{label!r}]"
                    ".expected_volatility_bps must be non-negative."
                )

        # Schema validation may intentionally validate a partial historical
        # row without materialising missing defaults. Runtime callers pass the
        # full defaults and require_complete=True, producing complete entries.
        entry: dict[str, int | str] = {}
        if asset_class_value is not None:
            entry["asset_class"] = str(asset_class_value).strip()
        if return_bps is not None:
            entry["expected_return_bps"] = return_bps
        if volatility_bps is not None:
            entry["expected_volatility_bps"] = volatility_bps
        normalized[label] = entry

    return normalized
