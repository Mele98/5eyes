"""Regression-Lock für den tax-aware Solver-Pfad (Roadmap #39/46).

Der Pfad in `portfolio_engine._run_stochastic_optimizer_pass` importierte eine
nie existierende Klasse `TaxConfig` aus `services.tax.base` und konstruierte
`regime_cls(TaxConfig(jurisdiction_id=...))`. Der `ImportError` wurde vom breiten
`except Exception` verschluckt → das `tax_kwargs`-Dict blieb leer → `run_solver`
lief ohne `tax_regime` → `simulate_wealth_paths` rechnete bei JEDEM Mandat
tax-naiv (kein Steuer-Drag), egal welche `tax_jurisdiction` gesetzt war.

Diese Tests schlagen ohne den Fix fehl.
"""
from __future__ import annotations

from pathlib import Path

import services.tax  # noqa: F401  -- löst @register_regime für alle Regimes aus
from services.tax.registry import resolve_regime_class


def test_taxconfig_symbol_does_not_exist() -> None:
    """Belegt, dass der alte Import `from services.tax.base import TaxConfig` tot war."""
    import services.tax.base as base

    assert not hasattr(base, "TaxConfig")


def test_resolve_and_construct_regime_without_config() -> None:
    """Exakt der Engine-Pfad: resolve_regime_class(jid) + no-arg-Konstruktion.

    Vor dem Fix scheiterte dieser Pfad zur Laufzeit (ImportError bzw. falscher
    Konstruktor-Vertrag). Regimes sind frozen dataclasses mit Defaults und damit
    ohne jegliches Config-Objekt konstruierbar.
    """
    for jid in ("CH", "DE", "VN"):
        regime_cls = resolve_regime_class(jid)
        regime = regime_cls()  # darf KEIN TaxConfig-Argument benötigen
        assert hasattr(regime, "country_code")
        assert isinstance(regime.id, str)


def test_engine_no_longer_imports_taxconfig() -> None:
    """Source-Lock: der tote Import und die falsche Konstruktion sind entfernt."""
    engine = Path(__file__).resolve().parents[1] / "services" / "portfolio_engine.py"
    src = engine.read_text(encoding="utf-8")
    assert "from services.tax.base import TaxConfig" not in src
    assert "regime_cls(TaxConfig(" not in src
    assert "regime_cls()" in src


# ── E2E-Wiring (TAX-1/2/3): _build_tax_solver_kwargs liefert das, was run_solver bekommt ──

from types import SimpleNamespace  # noqa: E402

from services.portfolio_engine import _build_tax_solver_kwargs  # noqa: E402


def _mandate(**kw):
    base = dict(
        tax_jurisdiction=None, tax_overrides_json=None, opened_at="2030-01-15",
        client_birth_year=None, retirement_year=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_no_jurisdiction_yields_empty_kwargs() -> None:
    """Ohne tax_jurisdiction -> kein tax_regime (Solver tax-naiv, Backwards-Compat)."""
    assert _build_tax_solver_kwargs(_mandate(tax_jurisdiction=None)) == {}
    assert _build_tax_solver_kwargs(_mandate(tax_jurisdiction="")) == {}


def test_jurisdiction_ch_reaches_solver_with_regime() -> None:
    """TAX-3: gesetztes tax_jurisdiction -> nicht-None tax_regime an run_solver."""
    kw = _build_tax_solver_kwargs(_mandate(tax_jurisdiction="CH"))
    assert kw.get("tax_regime") is not None
    assert kw["tax_regime"].country_code == "CH"
    # Landes-Pauschale (kein Kanton): Basis-Wealth-Tax.
    assert kw["tax_regime"].wealth_tax_bps_pa == 40


def test_canton_factory_used_for_region_id() -> None:
    """TAX-1: 'CH-GE' nutzt die Kanton-Factory (GE 85 bps), nicht den CH-Default 40."""
    kw = _build_tax_solver_kwargs(_mandate(tax_jurisdiction="CH-GE"))
    assert kw["tax_regime"].wealth_tax_bps_pa == 85
    assert kw["tax_regime"].region_code == "GE"


def test_unknown_canton_falls_back_to_base_regime() -> None:
    """Unbekannte Region crasht nicht, sondern faellt auf das Basis-CH-Regime zurueck."""
    kw = _build_tax_solver_kwargs(_mandate(tax_jurisdiction="CH-XX"))
    assert kw.get("tax_regime") is not None
    assert kw["tax_regime"].country_code == "CH"


def test_base_calendar_year_from_opened_at_not_hardcoded() -> None:
    """TAX-2: base_calendar_year kommt aus opened_at, nicht aus dem nie-existenten
    valid_from_year (das frueher immer 2026 ergab)."""
    kw = _build_tax_solver_kwargs(_mandate(tax_jurisdiction="CH", opened_at="2034-07-01"))
    assert kw["base_calendar_year"] == 2034


def test_age_and_retired_relative_to_real_year() -> None:
    kw = _build_tax_solver_kwargs(
        _mandate(tax_jurisdiction="CH", opened_at="2040-01-01",
                 client_birth_year=1975, retirement_year=2038)
    )
    assert kw["mandate_age_at_start"] == 65  # 2040 - 1975
    assert kw["is_retired"] is True  # 2040 >= 2038
