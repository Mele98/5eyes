"""2026-07-24 (Formel-Audit, Folgefund zum Cornish-Fisher-Clamp):
correlation_matrix_json wurde bisher NUR auf Shape (5x5) geprueft
(services/portfolio_engine.py::_build_cholesky_from_cma), NICHT auf
Werte-Range/Diagonale/Symmetrie. Der Laufzeit-Fallback (_is_valid_cholesky)
prueft nur numerische Entartung, nicht ob es fachlich eine gueltige
Korrelationsmatrix ist -- ein Tippfehler wie 1.05 statt 0.95 kann eine
weiterhin positiv-definite ("gueltige") Matrix ergeben und liefe unbemerkt
in die Simulation. Diese Tests sperren die neue Pydantic-Validierung
(analog SCHEMA-03).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from schemas.allocation import CapitalMarketAssumptionCreate


def _identity_5x5() -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(5)] for i in range(5)]


def test_valid_identity_matrix_ok():
    cma = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01",
        correlation_matrix_json=json.dumps(_identity_5x5()),
    )
    assert json.loads(cma.correlation_matrix_json) == _identity_5x5()


def test_valid_realistic_matrix_ok():
    matrix = _identity_5x5()
    matrix[0][1] = matrix[1][0] = 0.6
    matrix[0][2] = matrix[2][0] = 0.3
    cma = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01",
        correlation_matrix_json=json.dumps(matrix),
    )
    assert cma.correlation_matrix_json is not None


def test_none_or_empty_skips_validation():
    cma = CapitalMarketAssumptionCreate(valid_from="2026-01-01", correlation_matrix_json=None)
    assert cma.correlation_matrix_json is None


def test_invalid_json_rejected():
    with pytest.raises(ValidationError, match="gültiges JSON"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json="{not valid json",
        )


def test_wrong_shape_rejected_not_5x5():
    matrix = [[1.0, 0.0], [0.0, 1.0]]
    with pytest.raises(ValidationError, match="5x5"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_value_above_one_rejected():
    """Der konkrete Tippfehler-Fall aus dem Audit: 1.05 statt 0.95."""
    matrix = _identity_5x5()
    matrix[0][1] = matrix[1][0] = 1.05
    with pytest.raises(ValidationError, match=r"\[-1, 1\]"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_value_below_minus_one_rejected():
    matrix = _identity_5x5()
    matrix[2][3] = matrix[3][2] = -1.5
    with pytest.raises(ValidationError, match=r"\[-1, 1\]"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_diagonal_not_one_rejected():
    matrix = _identity_5x5()
    matrix[2][2] = 0.9
    with pytest.raises(ValidationError, match="Diagonale"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_asymmetric_matrix_rejected():
    matrix = _identity_5x5()
    matrix[0][1] = 0.5
    matrix[1][0] = 0.3  # asymmetrisch
    with pytest.raises(ValidationError, match="symmetrisch"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_non_numeric_cell_rejected():
    matrix = _identity_5x5()
    matrix[1][2] = "hoch"
    matrix[2][1] = "hoch"
    with pytest.raises(ValidationError, match="Zahl"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )


def test_boolean_cell_rejected():
    """bool ist in Python ein int-Subtyp -- explizit ausschliessen, sonst
    wuerde True/False als 1/0 durchrutschen."""
    matrix = _identity_5x5()
    matrix[0][3] = True
    matrix[3][0] = True
    with pytest.raises(ValidationError, match="Zahl"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01", correlation_matrix_json=json.dumps(matrix),
        )
