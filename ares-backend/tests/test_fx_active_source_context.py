"""FX-Fund 1: convert_rappen nutzt die aktive Context-FX-Quelle (DB-Rates aus der
PDF-Generierung) als Default statt der hardcodierten DEFAULT_FX_RATES.

Prioritaet: explizite source > aktive Context-Quelle > DEFAULT_FX_RATES.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from services.currency.converter import convert_rappen, set_active_fx_source


class _StubSource:
    def __init__(self, rate: float):
        self._rate = rate

    def cross_rate(self, from_ccy: str, to_ccy: str) -> float:
        return self._rate


@pytest.fixture(autouse=True)
def _reset_active_source():
    set_active_fx_source(None)
    yield
    set_active_fx_source(None)


def test_default_used_when_no_active_source():
    # Ohne aktive Quelle: hardcodierter DEFAULT (EUR->CHF != Sentinel 2.0).
    assert convert_rappen(100, "EUR", "CHF") != 200.0


def test_active_context_source_is_used():
    set_active_fx_source(_StubSource(2.0))
    assert convert_rappen(100, "EUR", "CHF") == 200.0


def test_explicit_source_overrides_active_context():
    set_active_fx_source(_StubSource(2.0))
    assert convert_rappen(100, "EUR", "CHF", source=_StubSource(3.0)) == 300.0


def test_reset_restores_default():
    default_val = convert_rappen(100, "EUR", "CHF")
    set_active_fx_source(_StubSource(2.0))
    assert convert_rappen(100, "EUR", "CHF") == 200.0
    set_active_fx_source(None)
    assert convert_rappen(100, "EUR", "CHF") == default_val


def test_identity_and_zero_unaffected():
    set_active_fx_source(_StubSource(2.0))
    assert convert_rappen(100, "CHF", "CHF") == 100.0  # Identity, keine Umrechnung
    assert convert_rappen(0, "EUR", "CHF") == 0.0
