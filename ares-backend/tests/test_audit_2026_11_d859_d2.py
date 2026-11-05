"""Delta-Pruefung #859 (Dok. 86): D-2 (gemeinsamer Kontext siehe unten).

D-1: Einzelziel-Kappung im Hausmatrix-Modus (Aktien-Ziel 75 % + Berater-
Minimum Obligationen 20 %): die Liquiditaet sinkt von 2 % auf 0 %, das
Reasoning sagte aber zugleich "Die SAA-Liquiditaet bleibt auf 2.0%." (Satz
der Reserve-Berechnung VOR der Projektion). Im Hausmatrix-Modus gilt die
Liquiditaets-Untergrenze der Hausmatrix (hier 0 %), nicht die globale
2-%-Untergrenze des stochastischen Modells -- das wird jetzt ausgewiesen.

D-2: systembedingte Erweiterung des Liquiditaetsbands ueber das
Hausmatrix-Maximum (M2) wird als Reasoning-Satz und Info-Meldung
ausgewiesen.

D-4: H-859-1 ohne Fallback -- gekapptes Einzelziel, Warnung und
body_client nennen die gespeicherte Quote, in beiden Modi.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

SINGLE_CAPPED = {"bands": {"equities": {"target_bps": 7500}, "bonds": {"min_bps": 2000}}}


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def test_d2_system_liquidity_band_extension_is_disclosed(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="d2")
    result = _generate(session_factory, mid, adv, None)
    ta = result["target_allocation"]
    extended = f"{int(ta.band_liquidity_max_bps) / 100:.2f} %"
    assert int(ta.band_liquidity_max_bps) > 200  # Hausmax Score 8
    lines = [r for r in result["reasoning"] if "Liquiditaetsband systembedingt auf" in r]
    assert lines and extended in lines[0] and "Hausmatrix-Maximum 2.00 %" in lines[0], result["reasoning"]
    info = [m for m in result["messages"] if m.get("code") == "INFO_LIQUIDITY_BAND_SYSTEM_EXTENDED"]
    assert len(info) == 1 and info[0]["severity"] == "info" and extended in info[0]["body_advisor"]


def test_d2_extension_message_also_in_house_mode_since_e1(session_factory, monkeypatch):
    """Seit E-1 gilt die Zielreserve-Untergrenze auch im Hausmatrix-Modus;
    die Erweiterung ueber das Hausmax wird dort ebenso ausgewiesen."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="d2h")
    result = _generate(session_factory, mid, adv, None)
    assert any(m.get("code") == "INFO_LIQUIDITY_BAND_SYSTEM_EXTENDED" for m in result["messages"])


