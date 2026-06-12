"""#AA-6 (2026-06-12): _annualized_return_bps floort aufgebrauchte Pfade auf -100%.

Vor dem Fix gab _annualized_return_bps fuer aufgebrauchte Pfade (end_value <= 0)
0 zurueck — ein Totalverlust zaehlte also als "0% Rendite". Das verzerrte den
Median der annualisierten Renditen und die Erfolgsrate nach oben. _return_bps
floorte bereits korrekt auf -10000 (-100%); _annualized_return_bps zieht jetzt
nach.
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _annualized_return_bps, _return_bps


def test_depleted_path_returns_total_loss():
    """end_value <= 0 -> -10000 bps (-100%), nicht 0."""
    assert _annualized_return_bps(1_000_000, 0, 10) == -10000
    assert _annualized_return_bps(1_000_000, -5000, 10) == -10000


def test_consistent_with_return_bps_on_depletion():
    """Floor-Verhalten konsistent zu _return_bps."""
    assert _annualized_return_bps(1_000_000, 0, 5) == _return_bps(1_000_000, 0)


def test_healthy_path_unchanged():
    """Gesunde Pfade rechnen weiter korrekt: Verdopplung in 10 J ~ 7.18% p.a."""
    bps = _annualized_return_bps(1_000_000, 2_000_000, 10)
    assert 700 <= bps <= 730  # 2^(1/10)-1 = 7.177%


def test_degenerate_inputs_return_zero():
    """Degenerierte Inputs (start<=0 oder years<=0) bleiben 0 (nicht berechenbar),
    solange end_value > 0."""
    assert _annualized_return_bps(0, 1_000_000, 10) == 0
    assert _annualized_return_bps(1_000_000, 1_000_000, 0) == 0


def test_no_growth_is_zero():
    """Unveraenderter Wert -> 0% annualisiert."""
    assert _annualized_return_bps(1_000_000, 1_000_000, 10) == 0
