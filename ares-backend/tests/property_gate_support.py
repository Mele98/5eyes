"""K1 Property-Gate: Testhilfe fuer die DORMANTE Property-Mechanik.

Seit dem Codex-Entscheid 2026-11-19 sind Collateral-Anrechnung,
Amortisations-/Refinanzierungsprojektion, abgeleitete Hypothekar-Cashflows und
die angenommene Immobilien-Wertsteigerung bis zur P1-Schliessung hart
deaktiviert (``services.property_advanced_gate``). Die Mechanik bleibt fuer die
Wiedereinschaltung (P1) im Code und wird weiter geprueft: Tests, die genau diese
Mechanik belegen, heben das Gate nur fuer sich auf. Es gibt keinen
Laufzeitschalter -- nur dieser Test-Monkeypatch der Code-Konstante.
Das Gate selbst belegt ``tests/test_k1_property_advanced_gate.py``.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def property_advanced_mechanics_enabled(monkeypatch):
    import services.property_advanced_gate as gate

    monkeypatch.setattr(gate, "PROPERTY_ADVANCED_FEATURES_ENABLED", True)
    yield
