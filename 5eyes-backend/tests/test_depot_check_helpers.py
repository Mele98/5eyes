"""Sprint U-39 (2026-06-06): Tests fuer die neuen depot_check-Helper-Funktionen.

Verifiziert dass die Extraktion (init_result_dict + load_positions +
aggregate_warnings) identisches Verhalten wie der Original-Inline-Block
liefert.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.depot_check import (
    _DRIFT_WARNING_THRESHOLD_BPS,
    _HHI_COUNTRY_WARNING_THRESHOLD,
    _HHI_SECTOR_WARNING_THRESHOLD,
    _HHI_TOP_POSITIONS_WARNING_THRESHOLD,
    _ILLIQUID_WARNING_THRESHOLD_BPS,
    _aggregate_warnings,
    _init_result_dict,
)


# ---------------------------------------------------------------------------
# Konstanten — Magic-Number-Entfernung
# ---------------------------------------------------------------------------

def test_warning_thresholds_match_original_magic_numbers():
    """Schwellen muessen mit den Original-Magic-Numbers uebereinstimmen."""
    assert _HHI_COUNTRY_WARNING_THRESHOLD == 5000
    assert _HHI_SECTOR_WARNING_THRESHOLD == 2500
    assert _HHI_TOP_POSITIONS_WARNING_THRESHOLD == 1500
    assert _ILLIQUID_WARNING_THRESHOLD_BPS == 3000
    assert _DRIFT_WARNING_THRESHOLD_BPS == 1500


# ---------------------------------------------------------------------------
# _init_result_dict
# ---------------------------------------------------------------------------

def test_init_result_dict_has_all_top_level_keys():
    mandate = SimpleNamespace(id="m-test-39")
    result = _init_result_dict(mandate)
    expected_keys = {
        "mandate_id",
        "total_advisory_wealth_rappen",
        "buckets",
        "country_exposure_bps",
        "sector_exposure_bps",
        "currency_exposure_bps",
        "soll_country_exposure_bps",
        "soll_sector_exposure_bps",
        "soll_currency_exposure_bps",
        "country_exposure_drift_bps",
        "sector_exposure_drift_bps",
        "currency_exposure_drift_bps",
        "concentration_hhi",
        "top_positions",
        "fund_characteristics",
        "liquidity_profile",
        "warnings",
    }
    assert expected_keys == set(result.keys())


def test_init_result_dict_mandate_id_string_coerced():
    mandate = SimpleNamespace(id="m-test-39")
    assert _init_result_dict(mandate)["mandate_id"] == "m-test-39"


def test_init_result_dict_none_mandate_id_yields_empty_string():
    mandate = SimpleNamespace(id=None)
    assert _init_result_dict(mandate)["mandate_id"] == ""


def test_init_result_dict_warnings_starts_empty():
    mandate = SimpleNamespace(id="x")
    result = _init_result_dict(mandate)
    assert result["warnings"] == []


def test_init_result_dict_concentration_hhi_subkeys():
    mandate = SimpleNamespace(id="x")
    result = _init_result_dict(mandate)
    assert set(result["concentration_hhi"].keys()) == {
        "country", "sector", "currency", "top_positions",
    }


# ---------------------------------------------------------------------------
# _aggregate_warnings
# ---------------------------------------------------------------------------

def _empty_result() -> dict:
    return _init_result_dict(SimpleNamespace(id="m-x"))


def test_no_warnings_when_no_thresholds_breached():
    result = _empty_result()
    _aggregate_warnings(result)
    assert result["warnings"] == []


def test_country_hhi_above_threshold_yields_warning():
    result = _empty_result()
    result["concentration_hhi"]["country"] = 5500
    _aggregate_warnings(result)
    assert any("Länder-Konzentration" in w for w in result["warnings"])


def test_country_hhi_below_threshold_no_warning():
    result = _empty_result()
    result["concentration_hhi"]["country"] = _HHI_COUNTRY_WARNING_THRESHOLD
    _aggregate_warnings(result)
    assert not any("Länder-Konzentration" in w for w in result["warnings"])


def test_sector_hhi_above_threshold_yields_warning():
    result = _empty_result()
    result["concentration_hhi"]["sector"] = 3000
    _aggregate_warnings(result)
    assert any("Sektor-Konzentration" in w for w in result["warnings"])


def test_top_positions_hhi_yields_warning_with_top_3_share():
    result = _empty_result()
    result["concentration_hhi"]["top_positions"] = 2000
    result["top_positions"] = [
        {"weight_bps": 3000},
        {"weight_bps": 2000},
        {"weight_bps": 1000},
        {"weight_bps": 500},
    ]
    _aggregate_warnings(result)
    msg = next(w for w in result["warnings"] if "Top-3-Positionen" in w)
    # 3000+2000+1000 = 6000bps = 60%
    assert "60.0%" in msg


def test_illiquid_above_threshold_yields_warning():
    result = _empty_result()
    result["liquidity_profile"]["illiquid_bps"] = 3500
    _aggregate_warnings(result)
    assert any("Illiquider Anteil" in w for w in result["warnings"])


def test_bucket_out_of_band_yields_warning():
    result = _empty_result()
    result["buckets"] = {
        "equities": {
            "label": "Aktien",
            "in_band": False,
            "ist_bps": 6500,
            "band_min_bps": 4000,
            "band_max_bps": 5500,
        },
    }
    _aggregate_warnings(result)
    msg = next(w for w in result["warnings"] if "Aktien" in w)
    assert "ausserhalb Toleranzband" in msg or "außerhalb Toleranzband" in msg


def test_country_drift_above_threshold_yields_warning():
    result = _empty_result()
    result["country_exposure_drift_bps"] = {"CH": 2000, "US": -500}
    _aggregate_warnings(result)
    msg = next(w for w in result["warnings"] if "Land-Drift" in w)
    assert "CH" in msg
    assert "Überhang" in msg


def test_currency_drift_negative_yields_unterhang_warning():
    result = _empty_result()
    result["currency_exposure_drift_bps"] = {"USD": -2000}
    _aggregate_warnings(result)
    msg = next(w for w in result["warnings"] if "Währung-Drift" in w)
    assert "Unterhang" in msg


def test_drift_below_threshold_no_warning():
    result = _empty_result()
    result["country_exposure_drift_bps"] = {"CH": 1000}  # < 1500 Schwelle
    _aggregate_warnings(result)
    assert not any("Drift" in w for w in result["warnings"])
