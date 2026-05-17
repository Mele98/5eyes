"""Registry-Tests: @register_regime + resolve_regime_class."""
from __future__ import annotations

import pytest

from services.tax.registry import (
    REGIME_REGISTRY,
    list_registered_patterns,
    register_regime,
    resolve_regime_class,
)


def test_generic_regime_registered_as_catchall():
    """GenericFlatRateRegime ist als '*' registriert."""
    assert "*" in REGIME_REGISTRY
    from services.tax.regimes.generic import GenericFlatRateRegime
    assert REGIME_REGISTRY["*"] is GenericFlatRateRegime


def test_resolve_unknown_jurisdiction_falls_back_to_generic():
    """ID die niemand spezifisch matcht → Generic."""
    from services.tax.regimes.generic import GenericFlatRateRegime
    cls = resolve_regime_class("XX-UNKNOWN-LAND-123")
    assert cls is GenericFlatRateRegime


def test_resolve_exact_match_wins_over_glob():
    """Exakter Treffer schlaegt Glob."""
    from services.tax.regimes.generic import GenericFlatRateRegime

    @register_regime("TEST-LAND")
    class _ExactRegime(GenericFlatRateRegime):
        pass

    @register_regime("TEST-*")
    class _GlobRegime(GenericFlatRateRegime):
        pass

    try:
        assert resolve_regime_class("TEST-LAND") is _ExactRegime
        assert resolve_regime_class("TEST-OTHER") is _GlobRegime
    finally:
        REGIME_REGISTRY.pop("TEST-LAND", None)
        REGIME_REGISTRY.pop("TEST-*", None)


def test_resolve_specific_glob_wins_over_general_glob():
    """'US-NY-*' schlaegt 'US-*' fuer 'US-NY-MANHATTAN'."""
    from services.tax.regimes.generic import GenericFlatRateRegime

    @register_regime("US-NY-*")
    class _NyRegime(GenericFlatRateRegime):
        pass

    @register_regime("US-*")
    class _UsRegime(GenericFlatRateRegime):
        pass

    try:
        assert resolve_regime_class("US-NY-MANHATTAN") is _NyRegime
        assert resolve_regime_class("US-CA") is _UsRegime
    finally:
        REGIME_REGISTRY.pop("US-NY-*", None)
        REGIME_REGISTRY.pop("US-*", None)


def test_register_decorator_returns_class():
    from services.tax.regimes.generic import GenericFlatRateRegime

    @register_regime("DECORATOR-TEST")
    class _Foo(GenericFlatRateRegime):
        pass

    try:
        assert _Foo.__name__ == "_Foo"
        assert "DECORATOR-TEST" in REGIME_REGISTRY
    finally:
        REGIME_REGISTRY.pop("DECORATOR-TEST", None)


def test_list_registered_patterns_includes_generic():
    patterns = list_registered_patterns()
    assert "*" in patterns
    assert patterns == sorted(patterns)


def test_resolve_returns_class_not_instance():
    """resolve_regime_class gibt die KLASSE zurueck, nicht eine Instanz."""
    from services.tax.regimes.generic import GenericFlatRateRegime
    cls = resolve_regime_class("ANY-LAND")
    assert isinstance(cls, type)
    assert issubclass(cls, GenericFlatRateRegime)


def test_register_overrides_same_pattern_last_wins():
    """Doppelregistrierung mit gleichem Pattern: Last-Wins."""
    from services.tax.regimes.generic import GenericFlatRateRegime

    @register_regime("OVERWRITE")
    class _First(GenericFlatRateRegime):
        pass

    @register_regime("OVERWRITE")
    class _Second(GenericFlatRateRegime):
        pass

    try:
        assert resolve_regime_class("OVERWRITE") is _Second
    finally:
        REGIME_REGISTRY.pop("OVERWRITE", None)
