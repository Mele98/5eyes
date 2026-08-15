"""Roadmap #39 (Standpunkt 2026-08-07): geschaetzte Vermoegenssteuer als
optionale, abgeleitete Cashflow-Ausgabe.

services.wealth_cashflows.derive_tax_cashflow() nutzt denselben Tax-Regime-
Resolver wie der steuer-bewusste Optimizer-Pfad (_build_tax_solver_kwargs) --
Kanton-Overrides etc. muessen identisch wirken.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.tax  # noqa: F401,E402  -- loest @register_regime fuer alle Regimes aus
import pytest  # noqa: E402
from services.optimizer.constraints import OptimizerInputError  # noqa: E402
from services.wealth_cashflows import derive_tax_cashflow  # noqa: E402


def _mandate(**kw):
    base = dict(
        id="m1", client_id="c1", base_currency="CHF",
        tax_estimate_in_cashflow_enabled=1,
        tax_jurisdiction="CH", tax_overrides_json=None,
        opened_at="2026-01-15", client_birth_year=None, retirement_year=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_disabled_flag_returns_empty_list():
    mandate = _mandate(tax_estimate_in_cashflow_enabled=0)
    assert derive_tax_cashflow(mandate, 1_000_000_00) == []


def test_disabled_flag_default_falsy_value():
    """0/None/False sind alle 'aus' -- kein Crash bei unterschiedlichen Falsy-Repraesentationen."""
    for falsy in (0, None, False):
        mandate = _mandate(tax_estimate_in_cashflow_enabled=falsy)
        assert derive_tax_cashflow(mandate, 1_000_000_00) == []


def test_zero_or_negative_wealth_returns_empty_list():
    mandate = _mandate()
    assert derive_tax_cashflow(mandate, 0) == []
    assert derive_tax_cashflow(mandate, -100) == []


def test_enabled_tax_estimate_without_jurisdiction_fails_closed():
    """Aktivierte Steuerschaetzung braucht eine explizite Steuerbasis."""
    mandate = _mandate(tax_jurisdiction=None)
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_ch_default_wealth_tax_computed_correctly():
    """CH-Pauschale wealth_tax_bps_pa=40 (0.4%) auf CHF 1'000'000 = CHF 4'000."""
    mandate = _mandate(tax_jurisdiction="CH")
    rows = derive_tax_cashflow(mandate, 1_000_000_00)
    assert len(rows) == 1
    cf = rows[0]
    assert cf.cashflow_type == "Expense"
    assert cf.amount_rappen == 400_000  # CHF 4'000 in Rappen
    assert "Vermögenssteuer" in cf.label
    assert cf.currency == "CHF"
    assert cf.source == "tax_estimate"


def test_canton_override_changes_amount():
    """CH-GE hat 85bps statt CH-Pauschale 40bps -- Kanton-Resolution muss wirken
    (identischer Pfad wie der Solver, siehe test_tax_solver_wiring.py)."""
    mandate_ch = _mandate(tax_jurisdiction="CH")
    mandate_ge = _mandate(tax_jurisdiction="CH-GE")
    amount_ch = derive_tax_cashflow(mandate_ch, 1_000_000_00)[0].amount_rappen
    amount_ge = derive_tax_cashflow(mandate_ge, 1_000_000_00)[0].amount_rappen
    assert amount_ge > amount_ch


def test_unknown_canton_fails_closed_instead_of_using_country_average():
    import pytest
    from services.optimizer.constraints import OptimizerInputError

    mandate = _mandate(tax_jurisdiction="CH-XX")
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_tax_overrides_json_applied():
    import json
    mandate = _mandate(
        tax_jurisdiction="CH",
        tax_overrides_json=json.dumps({"wealth_tax_bps_pa": 100.0}),
    )
    rows = derive_tax_cashflow(mandate, 1_000_000_00)
    assert rows[0].amount_rappen == 1_000_000  # CHF 10'000 = 1.0% von 1 Mio


def test_unknown_generic_regime_without_explicit_overrides_fails_closed():
    """Unbekannte Jurisdiktion darf nicht wie steuerfrei behandelt werden."""
    import pytest
    from services.optimizer.constraints import OptimizerInputError

    mandate = _mandate(tax_jurisdiction="XX-UNKNOWN-COUNTRY")
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_negative_wealth_tax_override_fails_closed_before_cashflow_projection():
    """Eine ungueltige Rate darf nicht als steuerfreie Projektion erscheinen."""
    import json
    import pytest
    from services.optimizer.constraints import OptimizerInputError

    mandate = _mandate(
        tax_jurisdiction="CH",
        tax_overrides_json=json.dumps({"wealth_tax_bps_pa": -500.0}),
    )
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_over_hundred_percent_wealth_tax_override_fails_closed_before_projection():
    import json
    import pytest
    from services.optimizer.constraints import OptimizerInputError

    mandate = _mandate(
        tax_jurisdiction="CH",
        tax_overrides_json=json.dumps({"wealth_tax_bps_pa": 10_001.0}),
    )
    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 1_000_000_00)


def test_currency_matches_mandate_base_currency():
    mandate = _mandate(base_currency="EUR", tax_jurisdiction="CH")
    rows = derive_tax_cashflow(mandate, 1_000_000_00)
    assert rows[0].currency == "EUR"


def test_label_includes_regime_display_name():
    mandate = _mandate(tax_jurisdiction="CH-ZH")
    rows = derive_tax_cashflow(mandate, 1_000_000_00)
    assert "Z" in rows[0].label  # "Zuerich" im display_name
