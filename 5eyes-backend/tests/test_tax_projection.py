"""Steuer-Schaetzung fuer die Cashflow-Projektion (#39)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.tax_projection import (
    estimate_annual_tax_rappen,
    taxable_wealth_rappen_from_positions,
)


def _pos(position_type, current_value_rappen, assignment="Anderes Vermögen"):
    return SimpleNamespace(
        position_type=position_type,
        assignment=assignment,
        current_value_rappen=current_value_rappen,
    )


def test_taxable_wealth_sums_assets_minus_debts_excludes_vorsorge():
    positions = [
        _pos("Depot", 500_000_00),
        _pos("Liquidität", 100_000_00),
        _pos("Immobilien", 1_000_000_00),
        _pos("Vorsorge", 300_000_00),                 # 2./3. Saeule -> NICHT vermoegenssteuerpflichtig
        _pos("Hypothek", 600_000_00, assignment="Verbindlichkeit"),  # Schuld -> mindert
    ]
    # 500k + 100k + 1'000k - 600k, Vorsorge ausgeschlossen = 1'000'000 CHF
    assert taxable_wealth_rappen_from_positions(positions) == 1_000_000_00


def test_taxable_wealth_never_negative():
    positions = [_pos("Hypothek", 800_000_00, assignment="Verbindlichkeit")]
    assert taxable_wealth_rappen_from_positions(positions) == 0
    assert taxable_wealth_rappen_from_positions([]) == 0


def test_ch_estimate_is_positive_and_income_plus_wealth():
    tax = estimate_annual_tax_rappen(
        country_code="CH", region="ZH",
        taxable_income_rappen=150_000_00, taxable_wealth_rappen=1_000_000_00,
        year=2026, civil_status="ledig",
    )
    assert tax > 0
    # Ohne Einkommen+Vermoegen ~ keine (oder minimale) Steuer.
    zero = estimate_annual_tax_rappen(
        country_code="CH", region="ZH",
        taxable_income_rappen=0, taxable_wealth_rappen=0, year=2026,
    )
    assert zero >= 0
    assert tax > zero


def test_married_not_higher_than_single():
    common = dict(country_code="CH", region="ZH", taxable_income_rappen=150_000_00,
                  taxable_wealth_rappen=1_000_000_00, year=2026)
    single = estimate_annual_tax_rappen(civil_status="ledig", **common)
    married = estimate_annual_tax_rappen(civil_status="verheiratet", **common)
    assert married <= single  # verheiratet nutzt guenstigere Tarife


def test_unknown_country_is_failsafe_zero():
    # Nicht registriertes Land -> 0 (darf die Projektion nie brechen).
    assert estimate_annual_tax_rappen(
        country_code="ZZ", region=None,
        taxable_income_rappen=150_000_00, taxable_wealth_rappen=1_000_000_00, year=2026,
    ) == 0
