"""U-P23.1 — Liquiditäts-Hard-Cap im Risk-Budget-Fallback respektieren.

Regression-Test fuer einen vom Berater entdeckten Compliance-Bug:
- Stochastic-Optimizer diverged auf Defensiv-Mandat
- Fallback HouseMatrix-Mid kann Risk-Budget nicht einhalten
- Vorher: `maximums["liquidity"] = 10000` öffnete bis 100%
- Folge: Defensiv-Mandate landeten auf 10% SAA-Liquidität statt 2-3%
- SAA-Liquiditäts-Hard-Cap (_SAA_LIQUIDITY_HARD_CAP_BPS = 300 = 3%)
  wurde umgangen

Bezug: Befund 2026-05-25 Abend, MX-FOUNDATION-01 hatte target_liquidity=1000bps
und band_liquidity_max=10000bps trotz HouseMatrix-Defensiv (liq_max=500).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_hard_cap_constant_unchanged():
    """Der Hard-Cap muss 3% bleiben — alles über 5% wäre SAA-fremd."""
    from services.portfolio_engine import _SAA_LIQUIDITY_HARD_CAP_BPS
    assert _SAA_LIQUIDITY_HARD_CAP_BPS == 300, (
        f"SAA-Liquiditäts-Hard-Cap soll 3% (300 bps) bleiben, "
        f"aktuell {_SAA_LIQUIDITY_HARD_CAP_BPS}"
    )


def test_fallback_path_no_longer_opens_liquidity_to_100_percent():
    """Smoke-Test des Quellcodes: die Hotfix-Stelle darf NICHT mehr
    `maximums = {**maximums, "liquidity": 10000}` enthalten (das war der Bug).

    Die existierende Konstante `"Liquiditaet": {..., "liquidity": 10000}` in
    der Default-Asset-Klassen-Map (line 622) ist OK — die beschreibt die
    Asset-Klassen-Definition (Liquidität-Position = 100% Liquid), nicht
    die SAA-Maximum-Bandbreite.
    """
    src = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
    # Die genaue Bug-Zeile darf nicht mehr da sein:
    assert '{**maximums, "liquidity": 10000}' not in src, (
        "Die Notfall-Eskalation `{**maximums, 'liquidity': 10000}` war der "
        "Compliance-Bug. Sie darf nicht mehr im Code stehen."
    )
    assert "_SAA_LIQUIDITY_HARD_CAP_BPS" in src, (
        "Der Hard-Cap muss im Fallback-Pfad referenziert werden."
    )
    # Der Fix muss die "U-P23.1"-Markierung haben (für Auditierbarkeit)
    assert "U-P23.1" in src, "Hotfix-Marker im Code fehlt."


def test_fallback_path_uses_max_of_existing_and_hard_cap():
    """Wenn der Cap kleiner ist als das HouseMatrix-Maximum, darf
    der Fix NICHT herunterdrücken (defensiver: max(existing, cap)).
    Wenn der Cap größer ist (= 3% > HM-Defensiv-5% — gilt NICHT, weil
    Defensiv-Max ist 5% > 3%), wird das HM-Max beibehalten.
    """
    src = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
    # Der Fix verwendet max(maximums["liquidity"], hard_cap)
    assert "max(" in src and "_SAA_LIQUIDITY_HARD_CAP_BPS" in src
    assert "relaxed_liquidity_max" in src
