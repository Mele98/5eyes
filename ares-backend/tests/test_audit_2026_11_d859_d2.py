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


@pytest.mark.parametrize("mode", ["stochastic", "house_matrix"])
def test_d2_system_liquidity_band_extension_is_disclosed(session_factory, monkeypatch, mode):
    """D-2/E-2: Erweiterung ueber das Hausmax als Reasoning-Satz (mit
    Umlaut, weit oben -- die Karte "Leitplanken & Engine" filtert ASCII-
    "Liquiditaet" und zeigt nur zwei Saetze) und als warning ohne Aktion
    (Banner). Seit E-1 auch im Hausmatrix-Modus."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"d2{mode[:3]}")
    result = _generate(session_factory, mid, adv, None)
    ta = result["target_allocation"]
    extended = f"{int(ta.band_liquidity_max_bps) / 100:.2f} %"
    assert int(ta.band_liquidity_max_bps) > 200  # Hausmax Score 8
    index = [i for i, r in enumerate(result["reasoning"]) if "Liquiditätsband systembedingt auf" in r]
    assert index and index[0] <= 2, result["reasoning"]
    line = result["reasoning"][index[0]]
    assert extended in line and "Hausmatrix-Maximum 2.00 %" in line and "Zielreserve" in line, line
    # Filter der Karte "Leitplanken & Engine" (ares.html) laesst den Satz durch.
    import re as _re
    assert not _re.search(r"Liquiditaet|Reserve|Cashflow|House Matrix fuer Score|Risky Fraction|Pfadsimulation", line)
    msg = [m for m in result["messages"] if m.get("code") == "WARN_LIQUIDITY_BAND_SYSTEM_EXTENDED"]
    assert len(msg) == 1 and msg[0]["severity"] == "warning" and msg[0]["actions"] == []
    assert extended in msg[0]["body_advisor"]
    assert "Zielreserve" in msg[0]["body_client"]


def test_e2_body_client_names_model_floor_when_not_reserve_driven():
    from services.portfolio_engine_house_matrix import disclose_system_liquidity_band_extension

    reasoning: list[str] = []
    messages: list = []
    disclose_system_liquidity_band_extension(200, 100, reasoning, messages, reserve_driven=False)
    assert "Mindestliquidität des Modells" in reasoning[0]
    assert "Mindestliquidität vorsieht" in messages[0]["body_client"]
    assert "Zielreserve" not in messages[0]["body_client"]
