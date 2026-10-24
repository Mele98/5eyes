"""Fail-closed contracts for tax and FX inputs used by the allocation model."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

import services.tax  # noqa: F401  -- register the built-in regimes
from services.cashflow_timeline import _convert_cf_amount_to_target_currency
from services.currency.fx_rates import (
    DEFAULT_FX_RATE_SET_VERSION,
    FXRateLoadError,
    FXRateSource,
)
from services.optimizer.constraints import OptimizerInputError
from services.portfolio_engine_optimizer_integration import _build_tax_solver_kwargs
from services.wealth_cashflows import derive_tax_cashflow
from services.wealth_cashflows import _convert_position_rappen


def _mandate(**overrides):
    values = {
        "id": "mandate-tax-fx",
        "client_id": "client-tax-fx",
        "base_currency": "CHF",
        "tax_estimate_in_cashflow_enabled": 1,
        "tax_jurisdiction": "CH",
        "tax_overrides_json": None,
        "opened_at": "2026-01-01",
        "client_birth_year": None,
        "retirement_year": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _cashflow(*, currency: str = "USD", amount_rappen: int = 100_00):
    return SimpleNamespace(
        label="Test-Cashflow",
        currency=currency,
        amount_rappen=amount_rappen,
    )


def test_configured_unknown_tax_jurisdiction_is_not_hidden_by_cashflow_layer():
    mandate = _mandate(tax_jurisdiction="XX-UNKNOWN")

    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_tax_resolver_failure_is_not_hidden_by_cashflow_layer(monkeypatch):
    import services.tax.registry as registry

    def _raise(_jurisdiction):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(registry, "resolve_regime_class", _raise)

    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(_mandate(), 1_000_000_00)


@pytest.mark.parametrize(
    "overrides_json",
    [
        "{broken",
        "null",
        "[]",
        '{"wealth_tax_bps_pa": "100"}',
        '{"wealth_tax_bps_typo": 100}',
    ],
)
def test_configured_malformed_tax_overrides_fail_closed(overrides_json):
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        _build_tax_solver_kwargs(
            _mandate(tax_jurisdiction="CH", tax_overrides_json=overrides_json)
        )


def test_explicit_generic_tax_override_remains_supported():
    kwargs = _build_tax_solver_kwargs(
        _mandate(
            tax_jurisdiction="XX-EXPLICIT",
            tax_overrides_json='{"wealth_tax_bps_pa": 100}',
        )
    )

    assert kwargs["tax_regime"].wealth_tax_bps_pa == 100


@pytest.mark.parametrize(
    "overrides_json",
    [
        '{"dividend_tax_bps": -1}',
        '{"wealth_tax_bps_pa": 10000.0001}',
        '{"interest_tax_bps": 10001}',
    ],
)
def test_solver_tax_basis_rejects_rates_outside_zero_to_one_hundred_percent(
    overrides_json,
):
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        _build_tax_solver_kwargs(
            _mandate(tax_jurisdiction="CH", tax_overrides_json=overrides_json)
        )


@pytest.mark.parametrize("value", [0, 10_000])
def test_solver_tax_basis_accepts_inclusive_rate_boundaries(value):
    kwargs = _build_tax_solver_kwargs(
        _mandate(
            tax_jurisdiction="CH",
            tax_overrides_json=f'{{"dividend_tax_bps": {value}}}',
        )
    )

    assert kwargs["tax_regime"].dividend_tax_bps == value


def test_unknown_ch_canton_fails_closed_instead_of_using_country_average():
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        _build_tax_solver_kwargs(_mandate(tax_jurisdiction="CH-XX"))


def test_unknown_cashflow_currency_never_uses_silent_parity():
    with pytest.raises(ValueError, match="FX-Rate.*XYZ->CHF"):
        _convert_cf_amount_to_target_currency(
            _cashflow(currency="XYZ"), FXRateSource(), "CHF"
        )


@pytest.mark.parametrize("rate", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_invalid_effective_cashflow_cross_rate_fails_closed(rate):
    class _InvalidSource:
        def cross_rate(self, _from_currency, _to_currency):
            return rate

    with pytest.raises(ValueError, match="Ungueltige FX-Rate"):
        _convert_cf_amount_to_target_currency(
            _cashflow(), _InvalidSource(), "CHF"
        )


def test_foreign_mortgage_adjustment_without_fx_source_fails_closed():
    position = SimpleNamespace(currency="USD")

    with pytest.raises(ValueError, match="Keine FX-Quelle"):
        _convert_position_rappen(100_00, position, None, "CHF")


@pytest.mark.parametrize("rate", [0.0, -1.0, math.nan, math.inf])
def test_invalid_mortgage_adjustment_rate_fails_closed(rate):
    class _InvalidSource:
        def cross_rate(self, _from_currency, _to_currency):
            return rate

    with pytest.raises(ValueError, match="Ungueltiger FX-Kurs"):
        _convert_position_rappen(
            100_00,
            SimpleNamespace(currency="USD"),
            _InvalidSource(),
            "CHF",
        )


@pytest.mark.parametrize("rate", [math.nan, math.inf, -math.inf])
def test_non_finite_fx_source_rate_is_rejected(rate):
    with pytest.raises(ValueError, match="Invalid rate"):
        FXRateSource(rates_in_chf={"CHF": 1.0, "EUR": rate})


class _FakeQuery:
    def __init__(self, rows=None, error: Exception | None = None):
        self._rows = list(rows or [])
        self._error = error

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        if self._error is not None:
            raise self._error
        return self._rows


class _FakeDB:
    def __init__(self, rows=None, error: Exception | None = None):
        self._rows = rows
        self._error = error

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._rows, self._error)


def test_model_fx_loader_does_not_hide_database_failure():
    with pytest.raises(FXRateLoadError, match="FX-Rates"):
        FXRateSource.from_db_for_model(
            _FakeDB(error=RuntimeError("database unavailable"))
        )


@pytest.mark.parametrize(
    "row",
    [
        SimpleNamespace(currency="EUR", rate_x10000=0),
        SimpleNamespace(currency="EUR", rate_x10000=10_000_001),
        SimpleNamespace(currency="CHF", rate_x10000=9500),
        SimpleNamespace(currency="EU", rate_x10000=9500),
    ],
)
def test_model_fx_loader_does_not_replace_invalid_active_row_with_default(row):
    with pytest.raises(FXRateLoadError, match="ungueltig"):
        FXRateSource.from_db_for_model(_FakeDB(rows=[row]))


def test_model_fx_loader_rejects_ambiguous_duplicate_active_currency():
    rows = [
        SimpleNamespace(currency="EUR", rate_x10000=9500),
        SimpleNamespace(currency="eur", rate_x10000=9700),
    ]

    with pytest.raises(FXRateLoadError, match="Mehrere aktive FX-Rates"):
        FXRateSource.from_db_for_model(_FakeDB(rows=rows))


def test_empty_model_fx_table_uses_an_explicit_versioned_default_basis():
    source = FXRateSource.from_db_for_model(_FakeDB(rows=[]))

    assert source.basis_id == DEFAULT_FX_RATE_SET_VERSION
    assert source.uses_versioned_defaults is True
    assert source.rate_to_chf("EUR") > 0


def test_versioned_default_signature_contains_provenance_and_exact_rates():
    source = FXRateSource.from_db_for_model(_FakeDB(rows=[]))

    signature = source.canonical_model_signature(
        {"USD", "CHF"}, target_currency="CHF"
    )

    assert signature == {
        "basis_id": DEFAULT_FX_RATE_SET_VERSION,
        "uses_versioned_defaults": True,
        "target_currency": "CHF",
        "effective_rates_x1e8": [
            ["CHF", 100_000_000],
            ["USD", 88_000_000],
        ],
    }


def test_db_model_fx_basis_identifies_default_fill_and_exact_db_rows():
    source = FXRateSource.from_db_for_model(
        _FakeDB(
            rows=[
                SimpleNamespace(
                    id="fx-eur-current",
                    currency="EUR",
                    rate_x10000=9700,
                    valid_from="2026-08-11",
                    source="Manual",
                )
            ]
        )
    )

    assert source.basis_id.startswith(
        f"db_current_plus_{DEFAULT_FX_RATE_SET_VERSION}:"
    )
    assert source.uses_versioned_defaults is True
    assert source.rate_to_chf("EUR") == 0.97


def test_db_model_fx_basis_changes_when_effective_row_changes():
    def _source(rate_x10000: int):
        return FXRateSource.from_db_for_model(
            _FakeDB(
                rows=[
                    SimpleNamespace(
                        id="fx-eur-current",
                        currency="EUR",
                        rate_x10000=rate_x10000,
                        valid_from="2026-08-11",
                        source="Manual",
                    )
                ]
            )
        )

    first = _source(9500)
    second = _source(9700)

    assert first.basis_id != second.basis_id
    assert first.canonical_model_signature(
        {"EUR"}, target_currency="CHF"
    ) != second.canonical_model_signature({"EUR"}, target_currency="CHF")
