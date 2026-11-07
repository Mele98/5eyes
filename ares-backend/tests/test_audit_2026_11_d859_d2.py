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


def _banner(messages):
    """firstVisibleAllocationMessage() aus ares.html: erst conflict, dann warning."""
    rows = [m for m in messages if isinstance(m, dict)]
    return ([m for m in rows if m.get("severity") == "conflict"] + [m for m in rows if m.get("severity") == "warning"] or [None])[0]


@pytest.mark.parametrize("mode", ["stochastic", "house_matrix"])
def test_f1_standard_mandate_extension_is_info_without_banner(session_factory, monkeypatch, mode):
    """F-1 (Pruefrunde #859): Standardmandat Score 8 ohne Praeferenzen --
    die Erweiterung um 1 bp (2.01 % statt 2.00 %) ist eine Info mit
    Reasoning-Satz, kein Banner. Vorher war sie in jedem Standardfall der
    erste gelbe Banner (AA- und Review-Maske)."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"f1{mode[:3]}")
    result = _generate(session_factory, mid, adv, None)
    ta = result["target_allocation"]
    extended = f"{int(ta.band_liquidity_max_bps) / 100:.2f} %"
    assert int(ta.band_liquidity_max_bps) - 200 < 25
    codes = [m.get("code") for m in result["messages"]]
    assert "WARN_LIQUIDITY_BAND_SYSTEM_EXTENDED" not in codes
    info = [m for m in result["messages"] if m.get("code") == "INFO_LIQUIDITY_BAND_SYSTEM_EXTENDED"]
    assert len(info) == 1 and info[0]["severity"] == "info" and info[0]["actions"] == []
    banner = _banner(result["messages"])
    assert banner is None or banner.get("code") != "INFO_LIQUIDITY_BAND_SYSTEM_EXTENDED"
    # Reasoning-Satz bleibt (mit Umlaut, weit oben, passiert den Kartenfilter).
    index = [i for i, r in enumerate(result["reasoning"]) if "Liquiditätsband systembedingt auf" in r]
    assert index and index[0] <= 2, result["reasoning"]
    line = result["reasoning"][index[0]]
    import re as _re
    assert extended in line and "Hausmatrix-Maximum 2.00 %" in line, line
    assert not _re.search(r"Liquiditaet|Reserve|Cashflow|House Matrix fuer Score|Risky Fraction|Pfadsimulation", line)
    # Kundentext passt zur Quelle: das Testmandat hat eine extern empfohlene
    # Reserve (CHF 2'352), wie im Reasoning ausgewiesen.
    assert any("externe Reserve ausserhalb des Beratungsmandats empfohlen" in r for r in result["reasoning"])
    assert "ausserhalb des Mandats empfohlen" in info[0]["body_client"], info[0]["body_client"]


def test_f1_extension_from_25_bps_is_warning_behind_band_deviation():
    from services.allocation_messages import format_message
    from services.portfolio_engine_house_matrix import (
        LIQUIDITY_BAND_EXTENSION_WARNING_THRESHOLD_BPS,
        disclose_system_liquidity_band_extension,
    )

    assert LIQUIDITY_BAND_EXTENSION_WARNING_THRESHOLD_BPS == 25
    for floor, expected in ((224, "INFO_LIQUIDITY_BAND_SYSTEM_EXTENDED"), (225, "WARN_LIQUIDITY_BAND_SYSTEM_EXTENDED")):
        reasoning: list[str] = []
        extra: list = []
        disclose_system_liquidity_band_extension(floor, 200, reasoning, extra, reserve_driven=True)
        assert [m["code"] for m in extra] == [expected]
    # Reihenfolge wie in generate: begruendungspflichtige Meldungen zuerst.
    band = format_message("WARN_BAND_OUTSIDE_HOUSE_MATRIX", bucket_label="Aktien")
    assert _banner([band] + extra)["code"] == "WARN_BAND_OUTSIDE_HOUSE_MATRIX"


def test_f1_generate_orders_band_deviation_before_liquidity_message(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="f1ord")
    result = _generate(session_factory, mid, adv, {"bands": {"equities": {"min_bps": 7600, "max_bps": 8500}}})
    codes = [m.get("code") for m in result["messages"]]
    liq = [i for i, c in enumerate(codes) if c and "LIQUIDITY_BAND_SYSTEM_EXTENDED" in c]
    band = codes.index("WARN_BAND_OUTSIDE_HOUSE_MATRIX")
    assert liq and band < liq[0], codes
    assert _banner(result["messages"])["code"] in ("CONFLICT_BAND_REASON_MISSING", "WARN_BAND_OUTSIDE_HOUSE_MATRIX")


def test_f1_body_client_follows_source():
    from services.portfolio_engine_house_matrix import disclose_system_liquidity_band_extension

    cases = {
        (True, True): "ausserhalb des Mandats empfohlen",
        (True, False): "im Mandat vorgesehene Reserve",
        (False, False): "Mindestliquidität vorsieht",
    }
    for (reserve_driven, external), text in cases.items():
        extra: list = []
        disclose_system_liquidity_band_extension(250, 200, [], extra, reserve_driven=reserve_driven, external_reserve=external)
        assert text in extra[0]["body_client"], (reserve_driven, external, extra[0]["body_client"])
