"""Sprint U-33 (2026-06-06): Tests fuer CH->EU Wegzugsbesteuerung Calculator."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.tax.wegzug_ch_eu import (
    DE_MIN_RESIDENCE_YEARS,
    DE_SUBSTANTIAL_PARTICIPATION_PCT,
    DEFAULT_ADMINISTRATIVE_COSTS_RAPPEN,
    EU_STEP_UP_COUNTRIES,
    WegzugTaxEstimate,
    estimate_ch_eu_wegzug,
)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

def test_default_admin_costs_5000_chf():
    assert DEFAULT_ADMINISTRATIVE_COSTS_RAPPEN == 500_000


def test_de_substantial_participation_threshold():
    assert DE_SUBSTANTIAL_PARTICIPATION_PCT == 1.0


def test_de_min_residence_years_7():
    """§ 6 AStG: 7 Jahre Mindest-Aufenthalt fuer Wegzugsbesteuerung."""
    assert DE_MIN_RESIDENCE_YEARS == 7


def test_eu_step_up_countries_include_main_western():
    for c in ("DE", "FR", "IT", "AT", "ES"):
        assert c in EU_STEP_UP_COUNTRIES


# ---------------------------------------------------------------------------
# Standard-Faelle: privates Vermoegen ohne wesentliche Beteiligung
# ---------------------------------------------------------------------------

def test_standard_case_zero_ch_exit_tax():
    """Privatvermoegen ohne wesentliche Beteiligung -> kein CH-Exit-Tax."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
        unrealized_gains_rappen=200_000_00,
        has_substantial_participation=False,
    )
    assert result.estimated_ch_exit_tax_rappen == 0


def test_standard_case_admin_costs_default():
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
    )
    assert result.administrative_costs_rappen == DEFAULT_ADMINISTRATIVE_COSTS_RAPPEN


def test_standard_case_step_up_country_yes():
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
    )
    assert result.has_step_up_basis is True


def test_standard_case_step_up_country_no():
    """Nicht-EU-Land -> kein dokumentiertes Step-Up."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="XX",  # unbekannt
    )
    assert result.has_step_up_basis is False


# ---------------------------------------------------------------------------
# Wesentliche Beteiligung + DE-Wegzugsbesteuerung
# ---------------------------------------------------------------------------

def test_substantial_participation_de_triggers_exit_tax():
    """DE § 6 AStG: wesentliche Beteiligung + 7+J CH -> Exit-Tax 30%."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
        unrealized_gains_rappen=500_000_00,
        has_substantial_participation=True,
        ch_residence_years=10,
    )
    # 30% von 500'000 = 150'000 CHF = 15_000_000 Rappen
    assert result.estimated_ch_exit_tax_rappen == 15_000_000


def test_substantial_participation_de_short_residence_no_trigger():
    """< 7 Jahre CH -> kein § 6 AStG Trigger."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
        unrealized_gains_rappen=500_000_00,
        has_substantial_participation=True,
        ch_residence_years=5,
    )
    assert result.estimated_ch_exit_tax_rappen == 0


def test_substantial_participation_not_de_no_trigger():
    """Wegzug nach AT mit wesentlicher Beteiligung -> kein CH-Exit-Tax
    (DE § 6 AStG ist DE-spezifisch)."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="AT",
        unrealized_gains_rappen=500_000_00,
        has_substantial_participation=True,
        ch_residence_years=10,
    )
    assert result.estimated_ch_exit_tax_rappen == 0


# ---------------------------------------------------------------------------
# Eingangsland-Vermoegenssteuer
# ---------------------------------------------------------------------------

def test_target_country_wealth_tax_computed():
    """ES Vermoegenssteuer 100 bps = 1% von 1M -> 10'000 CHF = 1'000'000 Rappen."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="ES",
        target_country_annual_wealth_tax_bps=100,
    )
    assert result.estimated_target_country_first_year_tax_rappen == 1_000_000


def test_target_country_no_wealth_tax_yields_zero():
    """DE hat keine allg. Vermoegenssteuer -> 0 bei default."""
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="DE",
    )
    assert result.estimated_target_country_first_year_tax_rappen == 0


# ---------------------------------------------------------------------------
# Total + Notes
# ---------------------------------------------------------------------------

def test_total_sums_three_components():
    result = estimate_ch_eu_wegzug(
        wealth_rappen=1_000_000_00,
        target_country="ES",
        target_country_annual_wealth_tax_bps=50,
    )
    expected = (
        result.estimated_ch_exit_tax_rappen
        + result.estimated_target_country_first_year_tax_rappen
        + result.administrative_costs_rappen
    )
    assert result.total_estimated_burden_rappen == expected


def test_notes_include_steuerberater_pflicht_warnung():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="DE")
    combined = " ".join(result.notes)
    assert "Steuerberater" in combined


def test_notes_include_quellensteuer_hinweis():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="DE")
    combined = " ".join(result.notes)
    assert "Quellensteuer" in combined


def test_notes_include_step_up_explanation_when_applicable():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="DE")
    combined = " ".join(result.notes)
    assert "Step-Up" in combined


def test_notes_include_no_step_up_warning_for_unknown_country():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="XX")
    combined = " ".join(result.notes)
    assert "Detail-Pruefung" in combined or "nicht dokumentiert" in combined


# ---------------------------------------------------------------------------
# Serialisierung
# ---------------------------------------------------------------------------

def test_to_dict_serializable():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="DE")
    d = result.to_dict()
    assert set(d.keys()) == {
        "estimated_ch_exit_tax_rappen",
        "estimated_target_country_first_year_tax_rappen",
        "administrative_costs_rappen",
        "total_estimated_burden_rappen",
        "target_country",
        "has_step_up_basis",
        "notes",
    }
    assert isinstance(d["notes"], list)


# ---------------------------------------------------------------------------
# Target-Country Normalisierung
# ---------------------------------------------------------------------------

def test_target_country_lowercase_normalized():
    """target_country='de' wird zu 'DE' normalisiert."""
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="de")
    assert result.target_country == "DE"


def test_target_country_whitespace_stripped():
    result = estimate_ch_eu_wegzug(wealth_rappen=1_000_000_00, target_country="  FR  ")
    assert result.target_country == "FR"
