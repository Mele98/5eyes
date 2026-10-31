"""CMA-001 / CMA-CORR-001: keine fachlichen Defaults durch blosse Abwesenheit.

Entscheidungsdokument 2026-10-27, Abschnitt 5 ("Bestaetigte Code-Luecken"):

* Die Schweizer Default-Korrelationsmatrix darf fuer Nicht-CH-CMAs ohne
  eigenen Payload nicht mehr einspringen (fail-closed); fuer CH nur als
  benannte, versionierte Policy (CMA-CORR-001, nicht ADR-12a).
* Die festen Ersatzwerte in ``_asset_class_expected_metrics`` (u. a.
  500 bps Aktien) sind entfernt -- ein fehlendes Pflichtfeld ist auch
  jenseits der vorgelagerten Validierung ein Domaenenfehler.

Alle Zahlen hier sind Test-Platzhalter, keine Fachannahmen.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402

from database import Base  # noqa: E402,F401
import models  # noqa: E402,F401
from models import allocation, clients, mandates, profiling, review, users, wealth  # noqa: E402,F401

configure_mappers()

from models.allocation import CapitalMarketAssumption  # noqa: E402
from services import portfolio_engine_cma  # noqa: E402
from services.cma_correlation_provenance import (  # noqa: E402
    CORRELATION_DECISION_ID,
    JURISDICTION_DEFAULT_CORRELATION_POLICIES,
    jurisdiction_default_correlation_policy,
    resolve_bucket_correlation_matrix,
)
from services.cma_validation import (  # noqa: E402
    CORRELATION_DEFAULT_POLICY_JURISDICTIONS,
    CMAValidationError,
    validate_runtime_cma_completeness,
)
from services.portfolio_engine import _DEFAULT_CORRELATION_MATRIX  # noqa: E402

_PLACEHOLDER_MATRIX = [[1.0 if i == j else 0.1 for j in range(5)] for i in range(5)]


def _complete_cma(jurisdiction, *, correlation=None, **overrides):
    values = dict(
        id=f"cma-corr001-{jurisdiction or 'ch'}",
        assumption_set_name="T", version=1, valid_from="2026-01-01", is_current=1,
        jurisdiction=jurisdiction,
        correlation_matrix_json=json.dumps(correlation) if correlation else None,
        alternatives_gold_return_bps=1, alternatives_gold_vol_bps=1,
        liquidity_return_bps=1, liquidity_vol_bps=1,
    )
    if jurisdiction in (None, "CH"):
        for field in (
            "equity_ch", "equity_intl", "bonds_chf_ig", "bonds_fx_hedged", "real_estate_ch",
        ):
            values[f"{field}_return_bps"] = 1
            values[f"{field}_vol_bps"] = 1
    else:
        for field in ("equity_home", "bonds_home_ig", "real_estate_home"):
            values[f"{field}_return_bps"] = 1
            values[f"{field}_vol_bps"] = 1
    values.update(overrides)
    return CapitalMarketAssumption(**values)


# ── Korrelation ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("jurisdiction", ["DE", "US", "AT"])
def test_non_ch_without_payload_is_refused(jurisdiction):
    cma = _complete_cma(jurisdiction)
    with pytest.raises(CMAValidationError, match="CMA-CORR-001"):
        validate_runtime_cma_completeness(cma)
    with pytest.raises(CMAValidationError, match="Fremdmarkt"):
        resolve_bucket_correlation_matrix(cma, default_matrix=_DEFAULT_CORRELATION_MATRIX)


def test_non_ch_with_own_payload_runs_on_that_payload():
    cma = _complete_cma("DE", correlation=_PLACEHOLDER_MATRIX)
    validate_runtime_cma_completeness(cma)
    matrix = resolve_bucket_correlation_matrix(cma, default_matrix=_DEFAULT_CORRELATION_MATRIX)
    assert [list(row) for row in matrix] == _PLACEHOLDER_MATRIX


@pytest.mark.parametrize("jurisdiction", [None, "CH"])
def test_ch_default_only_via_named_policy(jurisdiction):
    cma = _complete_cma(jurisdiction)
    validate_runtime_cma_completeness(cma)
    policy = jurisdiction_default_correlation_policy(cma)
    assert policy is not None
    assert policy["decision_id"] == CORRELATION_DECISION_ID == "CMA-CORR-001"
    assert policy["version"] and policy["approval_status"]
    matrix = resolve_bucket_correlation_matrix(cma, default_matrix=_DEFAULT_CORRELATION_MATRIX)
    assert [list(row) for row in matrix] == _DEFAULT_CORRELATION_MATRIX


def test_policy_registry_and_validation_agree():
    assert set(JURISDICTION_DEFAULT_CORRELATION_POLICIES) == set(
        CORRELATION_DEFAULT_POLICY_JURISDICTIONS
    ) == {"CH"}
    for policy in JURISDICTION_DEFAULT_CORRELATION_POLICIES.values():
        assert "ADR-12a" not in json.dumps(policy)


def test_optimizer_refuses_non_ch_without_payload():
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    with pytest.raises((OptimizerInputError, CMAValidationError)):
        scenario_inputs_from_cma(_complete_cma("DE"))


def test_reporting_cholesky_refuses_non_ch_without_payload():
    with pytest.raises(CMAValidationError):
        portfolio_engine_cma._build_cholesky_from_cma(_complete_cma("DE"))


# ── tote Ersatzwerte ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "jurisdiction, field",
    [
        (None, "equity_ch_return_bps"),
        (None, "liquidity_vol_bps"),
        ("DE", "equity_home_return_bps"),
        ("DE", "real_estate_home_vol_bps"),
    ],
)
def test_missing_field_has_no_fallback_even_without_upstream_validation(
    monkeypatch, jurisdiction, field,
):
    """Guard: selbst wenn die vorgelagerte Validierung entfiele, entsteht
    kein Ersatzwert, sondern ein Domaenenfehler."""
    monkeypatch.setattr(portfolio_engine_cma, "validate_runtime_cma_completeness", lambda cma: None)
    cma = _complete_cma(jurisdiction, correlation=_PLACEHOLDER_MATRIX, **{field: None})
    with pytest.raises(CMAValidationError, match=field):
        portfolio_engine_cma._asset_class_expected_metrics(cma, apply_market_adjustments=False)


def test_explicit_zero_is_preserved():
    cma = _complete_cma(None, equity_ch_return_bps=0, equity_intl_return_bps=0)
    returns, _vols = portfolio_engine_cma._asset_class_expected_metrics(
        cma, apply_market_adjustments=False,
    )
    assert returns["equities"] == 0


def test_no_fixed_fallback_values_left_in_bucket_metrics():
    source = inspect.getsource(portfolio_engine_cma._asset_class_expected_metrics)
    assert "_cma_value_or_default" not in source
    assert " else 500" not in source
    assert not hasattr(portfolio_engine_cma, "_cma_value_or_default")


# ── Offenlegung (Methodik-Audit) ──────────────────────────────────────────


@pytest.mark.parametrize(
    "jurisdiction, payload, expected_source",
    [
        (None, None, "named_default_policy"),
        ("DE", None, "missing"),
        ("DE", _PLACEHOLDER_MATRIX, "cma_payload"),
    ],
)
def test_bucket_correlation_is_disclosed(jurisdiction, payload, expected_source):
    from services.methodology_audit import _build_correlation_disclosure

    disclosure = _build_correlation_disclosure(_complete_cma(jurisdiction, correlation=payload))
    assert disclosure["decision_id"] == "CMA-CORR-001"
    assert disclosure["bucket_correlation"]["source"] == expected_source
    assert len(disclosure["notes"]) == 2


@pytest.mark.parametrize(
    "rho, kind",
    [(1.0, "no_diversification_stress_case"), (0.5, "configured_without_approved_policy")],
)
def test_global_rho_is_disclosed_not_silent(monkeypatch, rho, kind):
    from config import settings
    from services.methodology_audit import _build_correlation_disclosure

    monkeypatch.setattr(settings, "sub_class_intra_correlation", rho)
    disclosure = _build_correlation_disclosure(_complete_cma(None))
    assert disclosure["sub_class_intra_correlation"] == {
        "value_x100": int(round(rho * 100)), "kind": kind,
    }
    assert any("Intra-Bucket-Korrelation" in note for note in disclosure["notes"])
