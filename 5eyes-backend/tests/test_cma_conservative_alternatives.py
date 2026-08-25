"""Regressions-Lock (#97, 2026-06-18): konservative Default-Renditen fuer Alternatives.

User-Maxime „immer der tiefere Renditewert" (Ruhestandsgelder). Gold hat langfristig
~0% Realrendite, Private Equity / Krypto sind unsicher/spekulativ — die Default-CMA
darf diese NICHT wieder optimistisch hochsetzen.

Deckel (konservative Obergrenzen, nominal bps):
  Gold/Rohstoffe <= 150  ·  Private Equity <= 700  ·  Krypto <= 900
"""
from services.portfolio_engine import _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS


_CEILINGS_BPS = {
    "Gold / Rohstoffe": 150,
    "Private Equity": 700,
    "Krypto": 900,
}


def test_alternatives_default_returns_bleiben_konservativ():
    for name, ceiling in _CEILINGS_BPS.items():
        entry = _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.get(name)
        assert entry is not None, f"Sub-Asset-Klasse '{name}' fehlt in den Defaults"
        ret = int(entry.get("expected_return_bps", 0))
        assert ret <= ceiling, (
            f"{name}: Default-Rendite {ret} bps > konservativer Deckel {ceiling} bps "
            f"(Maxime 'immer tieferer Wert' verletzt)."
        )


def test_gold_real_etwa_null_annahme():
    # Gold konkret: deutlich unter der frueheren 3.0%-Annahme.
    gold = int(_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Gold / Rohstoffe"]["expected_return_bps"])
    assert gold <= 150, f"Gold-Default {gold} bps zu hoch (real ~0% erwartet)"
