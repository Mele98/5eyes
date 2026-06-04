"""Sprint U-44 (Roadmap-Punkt 44, 2026-06-04): HouseMatrix-Defaults YAML.

Pre-U-44
--------
HouseMatrix-Defaults waren als Tuple-Liste im portfolio_engine.py
hardcoded. Berater/Compliance konnte sie nicht ohne Code-Aenderung
anpassen.

Post-U-44
---------
- config/house_matrix_defaults.yaml mit allen 6 Profilen
- services/house_matrix_loader.py mit load_house_matrix_default_tuples()
- Fallback auf Hardcoded bei YAML-Fehler / Missing-File
- Identitaets-Tests: YAML == Hardcoded (Drift-Schutz)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.house_matrix_loader import (  # noqa: E402
    HOUSE_MATRIX_YAML_FIELDS,
    _HARDCODED_FALLBACK,
    _default_yaml_path,
    _entry_to_tuple,
    _validate_entry,
    load_house_matrix_default_tuples,
)


# ---------------------------------------------------------------------------
# Schema-Konstanten
# ---------------------------------------------------------------------------

def test_yaml_fields_count_is_20():
    """6 Profile mit je 20 Werten — Schema-Drift-Schutz."""
    assert len(HOUSE_MATRIX_YAML_FIELDS) == 20


def test_yaml_fields_order_matches_hardcoded():
    """Field-Order muss zu HouseMatrix-Engine-Tuple matchen."""
    expected_start = ("score_from", "score_to", "name")
    expected_end = ("max_risky_fraction_bps", "equity_minimum_bps")
    assert HOUSE_MATRIX_YAML_FIELDS[:3] == expected_start
    assert HOUSE_MATRIX_YAML_FIELDS[-2:] == expected_end


def test_hardcoded_fallback_has_6_profiles():
    assert len(_HARDCODED_FALLBACK) == 6


def test_hardcoded_fallback_each_profile_has_20_values():
    for profile in _HARDCODED_FALLBACK:
        assert len(profile) == 20


def test_hardcoded_fallback_profile_names():
    expected = (
        "Kapitalschutz", "Defensiv", "Ausgewogen",
        "Wachstumsorientiert", "Dynamisch", "Aktien",
    )
    actual = tuple(p[2] for p in _HARDCODED_FALLBACK)
    assert actual == expected


# ---------------------------------------------------------------------------
# load_house_matrix_default_tuples — Happy Path
# ---------------------------------------------------------------------------

def test_default_yaml_exists():
    """config/house_matrix_defaults.yaml MUSS existieren."""
    assert _default_yaml_path().exists()


def test_yaml_loads_6_profiles():
    tuples = load_house_matrix_default_tuples()
    assert len(tuples) == 6


def test_yaml_each_profile_has_20_values():
    tuples = load_house_matrix_default_tuples()
    for profile in tuples:
        assert len(profile) == 20


def test_yaml_identical_to_hardcoded_fallback():
    """KERN-Test: YAML-geladene Werte muessen IDENTISCH zu Hardcoded sein.
    Wenn jemand einen YAML-Wert aendert ohne Spec-Diskussion -> bricht hier."""
    tuples = load_house_matrix_default_tuples()
    assert tuples == _HARDCODED_FALLBACK


def test_yaml_identical_to_portfolio_engine_hardcoded():
    """Zusatz-Drift-Test: YAML muss auch zu portfolio_engine's inline-
    Hardcoded matchen (= unsere Truth in der Engine)."""
    source = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(
        encoding="utf-8",
    )
    marker = "_normalize_house_matrix_defaults(["
    start = source.find(marker)
    end = source.find("])", start)
    block = source[start + len(marker):end]

    engine_tuples = []
    for raw_line in block.splitlines():
        stripped = raw_line.strip().rstrip(",")
        if not stripped.startswith("("):
            continue
        tup = ast.literal_eval(stripped)
        engine_tuples.append(tup)

    yaml_tuples = load_house_matrix_default_tuples()
    assert tuple(engine_tuples) == yaml_tuples


# ---------------------------------------------------------------------------
# load_house_matrix_default_tuples — Fallback-Pfade
# ---------------------------------------------------------------------------

def test_missing_file_falls_back_to_hardcoded(tmp_path):
    nonexistent = tmp_path / "missing.yaml"
    tuples = load_house_matrix_default_tuples(nonexistent)
    assert tuples == _HARDCODED_FALLBACK


def test_invalid_yaml_falls_back(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not valid yaml: [unclosed", encoding="utf-8")
    tuples = load_house_matrix_default_tuples(bad)
    assert tuples == _HARDCODED_FALLBACK


def test_yaml_without_profiles_key_falls_back(tmp_path):
    bad = tmp_path / "no-profiles.yaml"
    bad.write_text("other_key: value", encoding="utf-8")
    tuples = load_house_matrix_default_tuples(bad)
    assert tuples == _HARDCODED_FALLBACK


def test_yaml_wrong_profile_count_falls_back(tmp_path):
    """5 Profile statt 6 -> fallback."""
    bad = tmp_path / "five.yaml"
    bad.write_text(
        "profiles:\n  - name: a\n  - name: b\n  - name: c\n  - name: d\n  - name: e",
        encoding="utf-8",
    )
    tuples = load_house_matrix_default_tuples(bad)
    assert tuples == _HARDCODED_FALLBACK


def test_yaml_missing_field_falls_back(tmp_path):
    """Profile ohne score_from -> fallback."""
    bad = tmp_path / "missing-field.yaml"
    yaml_content = """\
profiles:
"""
    for _ in range(6):
        yaml_content += "  - name: x\n"
    bad.write_text(yaml_content, encoding="utf-8")
    tuples = load_house_matrix_default_tuples(bad)
    assert tuples == _HARDCODED_FALLBACK


# ---------------------------------------------------------------------------
# _validate_entry
# ---------------------------------------------------------------------------

def _full_entry():
    return {
        "score_from": 1, "score_to": 2, "name": "X",
        "liquidity_min": 0, "liquidity_target": 100, "liquidity_max": 200,
        "bonds_min": 0, "bonds_target": 100, "bonds_max": 200,
        "equities_min": 0, "equities_target": 100, "equities_max": 200,
        "real_estate_min": 0, "real_estate_target": 100, "real_estate_max": 200,
        "alternatives_min": 0, "alternatives_target": 100, "alternatives_max": 200,
        "max_risky_fraction_bps": 5000,
        "equity_minimum_bps": 0,
    }


def test_validate_entry_happy_path():
    _validate_entry(_full_entry(), idx=0)  # no raise


def test_validate_entry_missing_field_raises():
    entry = _full_entry()
    del entry["score_from"]
    with pytest.raises(ValueError, match="score_from"):
        _validate_entry(entry, idx=0)


def test_validate_entry_score_inversion_raises():
    entry = _full_entry()
    entry["score_from"] = 5
    entry["score_to"] = 3
    with pytest.raises(ValueError, match="score_from > score_to"):
        _validate_entry(entry, idx=0)


def test_validate_entry_bucket_inversion_raises():
    """min > target -> Error."""
    entry = _full_entry()
    entry["bonds_min"] = 500
    entry["bonds_target"] = 200
    with pytest.raises(ValueError, match="bonds"):
        _validate_entry(entry, idx=0)


# ---------------------------------------------------------------------------
# Pinned-Critical-Values
# ---------------------------------------------------------------------------

def test_yaml_kapitalschutz_cap_3000():
    """U-P23.3 Pinned: Kapitalschutz cap = 3000."""
    tuples = load_house_matrix_default_tuples()
    kap = next(t for t in tuples if t[2] == "Kapitalschutz")
    assert kap[18] == 3000


def test_yaml_defensiv_cap_4500():
    """U-P23.2 Pinned: Defensiv cap = 4500."""
    tuples = load_house_matrix_default_tuples()
    defensiv = next(t for t in tuples if t[2] == "Defensiv")
    assert defensiv[18] == 4500


def test_yaml_wachstum_cap_8000():
    """U-40 Pinned: Wachstumsorientiert cap = 8000."""
    tuples = load_house_matrix_default_tuples()
    wachstum = next(t for t in tuples if t[2] == "Wachstumsorientiert")
    assert wachstum[18] == 8000
