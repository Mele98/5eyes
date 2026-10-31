"""W2-804-02: externe Marktdaten-Provider erreichen die echte Factory.

Abnahme: ``test_explicit_external_market_provider_reaches_real_factory`` ist
der uebernommene Codex-Reproducer (ohne xfail). Die uebrigen Tests belegen
die fail-closed-Invarianten (Ladefehler, Kollision, ungueltige Klasse,
fehlender expliziter Provider ohne Rueckfall) und dass Default-
Installationen unveraendert bleiben.

Isolation: keine Netzwerkaufrufe (Provider werden nur konstruiert), keine
Datenbank (Health-Registry wird durch None ersetzt), keine echten
Entry-Points (Discovery wird pro Test gefaelscht).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.market_data import factory, provider_discovery, provider_registry
from services.market_data.base import MarketDataProvider
from services.market_data.provider_registry import ProviderConfigurationError
from services.market_data.providers import (
    AlphaVantageProvider,
    StooqProvider,
    YFinanceProvider,
)


class _Stub(MarketDataProvider):
    name = "stub"

    def get_eod(self, *args, **kwargs):  # pragma: no cover - construction only
        raise NotImplementedError

    def get_history(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def lookup_isin(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _named(name: str) -> MarketDataProvider:
    cls = type(f"Ext_{name}", (_Stub,), {"name": name})
    return cls()


@pytest.fixture(autouse=True)
def _no_health_registry_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.market_data import provider_health_registry

    def _refuse():
        raise RuntimeError("Health-Registry im Test deaktiviert (keine DB)")

    monkeypatch.setattr(provider_health_registry, "build_default_registry", _refuse)


def _settings(providers: str) -> SimpleNamespace:
    return SimpleNamespace(
        market_data_providers=providers,
        market_data_unhealthy_ttl_seconds=300,
        alphavantage_api_key=None,
        twelvedata_api_key=None,
    )


def _discovery(monkeypatch: pytest.MonkeyPatch, providers: list) -> list[int]:
    calls: list[int] = []

    def fake():
        calls.append(1)
        return list(providers)

    monkeypatch.setattr(provider_discovery, "discover_external_providers", fake)
    return calls


# --------------------------------------------------------------------------
# Abnahme (Codex-Reproducer, ohne xfail)
# --------------------------------------------------------------------------


def test_explicit_external_market_provider_reaches_real_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExternalProvider(MarketDataProvider):
        name = "synthetic-external"

        def get_eod(self, *args, **kwargs):  # pragma: no cover - construction only
            raise NotImplementedError

        def get_history(self, *args, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def lookup_isin(self, *args, **kwargs):  # pragma: no cover
            raise NotImplementedError

    external = ExternalProvider()
    monkeypatch.setattr(
        provider_discovery,
        "discover_external_providers",
        lambda: [external],
    )
    settings = SimpleNamespace(
        market_data_providers=external.name,
        market_data_unhealthy_ttl_seconds=300,
    )

    aggregator = factory.build_default_aggregator(settings)
    assert aggregator.providers == [external]


# --------------------------------------------------------------------------
# Reihenfolge und einmaliges Laden
# --------------------------------------------------------------------------


def test_mixed_builtin_and_external_keep_configured_order_and_load_once(monkeypatch):
    ext = _named("licensed-feed")
    calls = _discovery(monkeypatch, [ext])

    agg = factory.build_default_aggregator(_settings("Licensed-Feed, yfinance"))

    assert agg.providers[0] is ext
    assert isinstance(agg.providers[1], YFinanceProvider)
    assert len(agg.providers) == 2
    assert calls == [1]


# --------------------------------------------------------------------------
# Fail-closed: kein stiller Rueckfall
# --------------------------------------------------------------------------


def test_missing_explicit_provider_raises_without_fallback(monkeypatch):
    _discovery(monkeypatch, [])
    with pytest.raises(ProviderConfigurationError, match="licensed-feed"):
        factory.build_default_aggregator(_settings("licensed-feed"))


def test_missing_explicit_provider_next_to_builtin_still_raises(monkeypatch):
    """Frueher: unbekannter Name uebersprungen, yfinance allein geliefert."""
    _discovery(monkeypatch, [])
    with pytest.raises(ProviderConfigurationError, match="licensed-feed"):
        factory.build_default_aggregator(_settings("licensed-feed,yfinance"))


def test_external_load_failure_of_configured_provider_raises(monkeypatch):
    """Echte Discovery: Entry-Point laesst sich nicht importieren."""

    class _BrokenEP:
        name = "licensed-feed"

        def load(self):
            raise ImportError("Paket kaputt")

    monkeypatch.setattr(
        provider_discovery, "entry_points", lambda *, group: [_BrokenEP()]
    )
    with pytest.raises(ProviderConfigurationError, match="licensed-feed"):
        factory.build_default_aggregator(_settings("licensed-feed"))


def test_invalid_provider_class_of_configured_provider_raises(monkeypatch):
    """Echte Discovery: Entry-Point liefert keine MarketDataProvider-Klasse."""

    class _NotAProvider:
        name = "licensed-feed"

        def get_eod(self, *a, **k): ...
        def get_history(self, *a, **k): ...
        def lookup_isin(self, *a, **k): ...

    class _EP:
        name = "licensed-feed"

        def load(self):
            return _NotAProvider

    monkeypatch.setattr(provider_discovery, "entry_points", lambda *, group: [_EP()])
    with pytest.raises(ProviderConfigurationError, match="licensed-feed"):
        factory.build_default_aggregator(_settings("licensed-feed"))


def test_discovered_object_that_is_not_a_provider_instance_raises(monkeypatch):
    _discovery(monkeypatch, [object()])
    with pytest.raises(ProviderConfigurationError, match="MarketDataProvider"):
        factory.build_default_aggregator(_settings("yfinance"))


def test_duplicate_configured_name_raises(monkeypatch):
    _discovery(monkeypatch, [])
    with pytest.raises(ProviderConfigurationError, match="mehrfach"):
        factory.build_default_aggregator(_settings("yfinance,YFinance"))


# --------------------------------------------------------------------------
# Kollisionen
# --------------------------------------------------------------------------


def test_external_colliding_with_builtin_raises(monkeypatch):
    _discovery(monkeypatch, [_named("YFinance")])
    with pytest.raises(ProviderConfigurationError, match="Namenskollision"):
        factory.build_default_aggregator(_settings("yfinance"))


def test_two_externals_with_same_name_raise(monkeypatch):
    _discovery(monkeypatch, [_named("licensed-feed"), _named("licensed-feed")])
    with pytest.raises(ProviderConfigurationError, match="Namenskollision"):
        factory.build_default_aggregator(_settings("licensed-feed"))


def test_real_discovery_passes_duplicate_names_to_factory(monkeypatch):
    """Discovery verwirft Duplikate nicht mehr still (kein First-Wins)."""

    def _ep(name):
        cls = type(f"Ext_{name}_{id(object())}", (_Stub,), {"name": "dup"})
        return SimpleNamespace(name=name, load=lambda: cls)

    monkeypatch.setattr(
        provider_discovery, "entry_points", lambda *, group: [_ep("a"), _ep("b")]
    )
    assert [p.name for p in provider_discovery.discover_external_providers()] == [
        "dup",
        "dup",
    ]
    with pytest.raises(ProviderConfigurationError, match="Namenskollision"):
        factory.build_default_aggregator(_settings("dup"))


# --------------------------------------------------------------------------
# Default-Installationen unveraendert
# --------------------------------------------------------------------------


def test_empty_configuration_uses_defaults_without_discovery(monkeypatch):
    calls = _discovery(monkeypatch, [_named("would-be-ignored")])
    agg = factory.build_default_aggregator(_settings(""))
    assert [type(p) for p in agg.providers] == [YFinanceProvider, StooqProvider]
    assert calls == []


def test_shipped_default_configuration_is_unchanged(monkeypatch):
    """Ausgelieferter Default (config.py) ohne externe Pakete."""
    from config import Settings

    shipped = Settings.model_fields["market_data_providers"].default
    assert shipped == "yfinance,stooq,alphavantage"
    _discovery(monkeypatch, [])
    agg = factory.build_default_aggregator(_settings(shipped))
    assert [type(p) for p in agg.providers] == [
        YFinanceProvider,
        StooqProvider,
        AlphaVantageProvider,
    ]


def test_unrelated_broken_external_package_does_not_break_default_boot(monkeypatch):
    class _BrokenEP:
        name = "unrelated"

        def load(self):
            raise ImportError("Paket kaputt")

    monkeypatch.setattr(
        provider_discovery, "entry_points", lambda *, group: [_BrokenEP()]
    )
    agg = factory.build_default_aggregator(_settings("yfinance,stooq"))
    assert [type(p) for p in agg.providers] == [YFinanceProvider, StooqProvider]


def test_builtin_names_are_the_four_known_providers():
    assert sorted(provider_registry.BUILTIN_PROVIDERS) == [
        "alphavantage",
        "stooq",
        "twelvedata",
        "yfinance",
    ]
    assert provider_registry.DEFAULT_PROVIDER_NAMES == ("yfinance", "stooq")
