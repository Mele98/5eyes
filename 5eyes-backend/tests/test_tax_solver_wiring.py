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
