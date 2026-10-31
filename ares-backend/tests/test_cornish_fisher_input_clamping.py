"""2026-07-24 (Formel-Audit): _cornish_fisher_transform validiert/clampt
skew/excess_kurt jetzt, statt sie ungeprueft in die (bei Extremwerten
nicht-monotone) CF-Expansion einfliessen zu lassen. Schutz gegen
Dateneingabefehler in der CMA-Admin-UI (z.B. Groessenordnungs-Tippfehler).
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _cornish_fisher_transform


def test_zero_skew_kurt_is_identity():
    assert _cornish_fisher_transform(1.5, 0.0, 0.0) == 1.5


def test_plausible_equity_like_values_unaffected_by_clamp():
    """Typische Aktien-Skew/-Kurt (z.B. -0.5 / 2.5) liegen weit innerhalb
    des Clamp-Bereichs -- Ergebnis identisch zur unveraenderten Formel."""
    z = 1.2
    skew, kurt = -0.5, 2.5
    z2, z3 = z * z, z * z * z
    expected = z + (z2 - 1.0) * skew / 6.0 + (z3 - 3.0 * z) * kurt / 24.0 - (2.0 * z3 - 5.0 * z) * skew * skew / 36.0
    assert abs(_cornish_fisher_transform(z, skew, kurt) - expected) < 1e-12


def test_extreme_skew_input_error_is_clamped_not_passed_through():
    """Ein Tippfehler (z.B. Faktor 100 zu gross) darf keine unbegrenzt
    wachsende Verzerrung erzeugen -- Ergebnis muss identisch zum Clamp-
    Grenzwert (skew=3.0) sein."""
    z = 1.0
    huge_skew_result = _cornish_fisher_transform(z, 300.0, 0.0)
    clamped_result = _cornish_fisher_transform(z, 3.0, 0.0)
    assert huge_skew_result == clamped_result


def test_extreme_negative_skew_is_clamped():
    z = 1.0
    assert _cornish_fisher_transform(z, -300.0, 0.0) == _cornish_fisher_transform(z, -3.0, 0.0)


def test_extreme_kurtosis_input_error_is_clamped():
    z = 1.0
    huge_kurt_result = _cornish_fisher_transform(z, 0.0, 5000.0)
    clamped_result = _cornish_fisher_transform(z, 0.0, 30.0)
    assert huge_kurt_result == clamped_result


def test_extreme_negative_kurtosis_is_clamped():
    z = 1.0
    assert _cornish_fisher_transform(z, 0.0, -500.0) == _cornish_fisher_transform(z, 0.0, -2.0)
