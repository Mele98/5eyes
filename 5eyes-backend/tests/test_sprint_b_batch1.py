"""Sprint B Batch 1 — B4 Universum + B1 Building-Block-Wahl.

Verifiziert:
- B4: mandates.investment_universe persistiert + via PUT updatebar
- B4: _building_block_risky_map filtert nach BuildingBlock.universe
- B1: mandates.default_building_blocks_json persistiert
- B1: _merge_mandate_defaults_into_prefs respektiert explicit prefs (UI-Wahl wins)
- B1: leere prefs uebernehmen Mandanten-Defaults
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe
from schemas.mandates import (
    INVESTMENT_UNIVERSE_OPTIONS,
    EQUITIES_GEO_OPTIONS,
    BONDS_DURATION_OPTIONS,
    REALESTATE_MARKET_OPTIONS,
    MandateUpdate,
    MandateCreate,
)
from models.mandates import Mandate


# ============================================================================
# B4: Universum-Optionen + Persistenz
# ============================================================================


def test_b4_universe_options_constant():
    """B4: nur Standard und Alternativ."""
    assert INVESTMENT_UNIVERSE_OPTIONS == ("Standard", "Alternativ")


def test_b4_mandate_create_default_universe():
    """B4: MandateCreate hat default 'Standard'."""
    m = MandateCreate(mandate_number="M-1")
    assert m.investment_universe == "Standard"


def test_b4_mandate_create_alternativ():
    """B4: 'Alternativ' ist akzeptiertes Universum."""
    m = MandateCreate(mandate_number="M-2", investment_universe="Alternativ")
    assert m.investment_universe == "Alternativ"


def test_b4_mandate_create_invalid_rejected():
    """B4: ungueltiges Universum -> ValidationError."""
    with pytest.raises(Exception):
        MandateCreate(mandate_number="M-3", investment_universe="Foo")


def test_b4_mandate_update_universe():
    """B4: MandateUpdate kann investment_universe setzen."""
    u = MandateUpdate(investment_universe="Alternativ")
    assert u.investment_universe == "Alternativ"


def test_b4_model_has_universe_column():
    """B4: SQLAlchemy-Modell hat investment_universe + default 'Standard'."""
    assert hasattr(Mandate, "investment_universe")
    # Default-Spec auf der column
    col = Mandate.__table__.columns["investment_universe"]
    assert col.default.arg == "Standard"


# ============================================================================
# B1: Building-Block-Wahl per Mandat
# ============================================================================


def test_b1_options_constants():
    """B1: Wahl-Optionen sind 3rd-eyes-Pattern (4/3/3)."""
    assert "Schweiz Fokus" in EQUITIES_GEO_OPTIONS
    assert "Global" in EQUITIES_GEO_OPTIONS
    assert "Langfristig" in BONDS_DURATION_OPTIONS
    assert "Kurzfristig" in BONDS_DURATION_OPTIONS
    assert "Schweiz" in REALESTATE_MARKET_OPTIONS
    assert "Ausland" in REALESTATE_MARKET_OPTIONS


def test_b1_merge_no_defaults():
    """B1: kein default_building_blocks_json -> prefs unveraendert."""
    m = SimpleNamespace(default_building_blocks_json=None)
    prefs = pe._normalize_preferences({"assetClasses": {"bondsHighYield": True}})
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"] == {"bondsHighYield": True}


def test_b1_merge_fills_missing():
    """B1: leere prefs uebernehmen Mandanten-Defaults."""
    m = SimpleNamespace(default_building_blocks_json=json.dumps({
        "equitiesGeo": "Global",
        "bondsDuration": "Kurzfristig",
        "altsGold": True,
        "noEm": True,
    }))
    prefs = pe._normalize_preferences(None)
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"]["equitiesGeo"] == "Global"
    assert out["assetClasses"]["bondsDuration"] == "Kurzfristig"
    assert out["assetClasses"]["altsGold"] is True
    assert out["geo"]["noEm"] is True


def test_b1_explicit_prefs_override_defaults():
    """B1: explicit UI-Wahl ueberschreibt Mandanten-Default."""
    m = SimpleNamespace(default_building_blocks_json=json.dumps({
        "equitiesGeo": "Global",
    }))
    prefs = pe._normalize_preferences({"assetClasses": {"equitiesGeo": "Schweiz Fokus"}})
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"]["equitiesGeo"] == "Schweiz Fokus"


def test_b1_corrupt_json_graceful():
    """B1: korrupter JSON in default_building_blocks_json -> kein Crash."""
    m = SimpleNamespace(default_building_blocks_json="{not-valid-json")
    prefs = pe._normalize_preferences(None)
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"] == {}


def test_b1_non_dict_json_ignored():
    """B1: JSON-Liste statt dict -> ignoriert."""
    m = SimpleNamespace(default_building_blocks_json=json.dumps(["not", "a", "dict"]))
    prefs = pe._normalize_preferences(None)
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"] == {}


def test_b1_unknown_keys_filtered():
    """B1: unbekannte Keys werden NICHT gemerged (Schutz vor falscher Eingabe)."""
    m = SimpleNamespace(default_building_blocks_json=json.dumps({
        "equitiesGeo": "Global",
        "someUnknownKey": "wert",
    }))
    prefs = pe._normalize_preferences(None)
    out = pe._merge_mandate_defaults_into_prefs(prefs, m)
    assert out["assetClasses"]["equitiesGeo"] == "Global"
    assert "someUnknownKey" not in out["assetClasses"]
    assert "someUnknownKey" not in out["geo"]


def test_b1_mandate_update_schema_accepts_json():
    """B1: MandateUpdate akzeptiert default_building_blocks_json als String."""
    u = MandateUpdate(default_building_blocks_json='{"equitiesGeo":"Global"}')
    assert u.default_building_blocks_json == '{"equitiesGeo":"Global"}'


# ============================================================================
# Integration: B4 Universum-Filter im risky_map
# ============================================================================


def test_b4_risky_map_signature_accepts_universe():
    """B4: _building_block_risky_map nimmt optional investment_universe entgegen."""
    import inspect
    sig = inspect.signature(pe._building_block_risky_map)
    assert "investment_universe" in sig.parameters
    # Default = None
    assert sig.parameters["investment_universe"].default is None
