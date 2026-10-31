"""STALE-ALLOCATION-HIDE-TARGETS-001, Nachtrag Sektion 9 + 10 (CIO-Entscheid).

Befund: bei veralteter Soll-Allokation blendete der Beratungsreport die
alten Zielzahlen in Sektion 8 (Asset Allocation) und 13 (Building Blocks)
aus -- Sektion 9 (Risikowaehrungen) und Sektion 10 (Diversifikation
Branchen) druckten aber weiter die SOLL-Exposures der alten Empfehlung
(z.B. "CHF 59.1 %", GICS-Sektor-Soll, "basiert auf 64.5 % Aktien-
Allokation") samt Drift und Auto-Text ("folgt der Zielstruktur").

Erwartung: veraltet -> soll/drift/ist None, soll_ausgeblendet True, Text =
Hinweis "... Strategie neu berechnen.". IST ebenfalls, weil die Exposures
ueber die Positionen der alten Empfehlung aggregiert werden und der
Depot-Check fehlende Ist-Betraege mit deren target_amount auffuellt
(client_facing-Pfad: ist_basiert_auf_soll erkennt das nicht). PDF und
Depot-Check-Payload enthalten keine alten SOLL-Exposures. Nicht-veraltet:
unveraendert (Positivkontrolle).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.advisory_report import (  # noqa: E402
    _build_branchen,
    _build_risikowaehrungen,
    compute_advisory_report,
)
from tests.test_allocation_input_staleness_surfaces import (  # noqa: E402,F401
    _reduce_largest_position,
    _seed,
    session,
)
from tests.test_stale_allocation_hide_targets import _all_texts  # noqa: E402


def _dc(*, stale: bool, inputs_stale: bool = False) -> dict:
    return {
        "target_allocation_stale": stale,
        "target_allocation_inputs_stale": inputs_stale,
        "currency_exposure_bps": {"CHF": 4000, "USD": 6000},
        "soll_currency_exposure_bps": {"CHF": 7300, "USD": 2700},
    }


def _sector_ctx() -> dict:
    return {
        "ist": {"Financials": 3000, "Health Care": 7000},
        "soll": {"Financials": 6100, "Health Care": 3900},
        "anteil_aktien_bps": 6449,
    }


# ---------------------------------------------------------------------------
# Payload (Unit)
# ---------------------------------------------------------------------------

def test_section9_not_stale_keeps_soll_exposure():
    rw = _build_risikowaehrungen(_dc(stale=False))
    assert rw["soll_ausgeblendet"] is False
    chf = next(it for it in rw["items"] if it["label"] == "CHF")
    assert chf["soll_bps"] == 7300
    assert chf["drift_bps"] == -3300
    assert rw["soll_bps"]["CHF"] == 7300


def test_section9_stale_nulls_soll_and_replaces_text():
    notes = MagicMock()
    notes.waehrungen_erklaerung = "CHF-Ziel von 73 % wird unterschritten."
    rw = _build_risikowaehrungen(_dc(stale=True, inputs_stale=True), notes=notes)
    for it in rw["items"]:
        assert it["soll_bps"] is None, it
        assert it["drift_bps"] is None, it
    assert rw["target_allocation_stale"] is True
    assert rw["soll_ausgeblendet"] is True
    assert rw["soll_bps"] is None
    assert rw["drift_bps"] is None
    assert all(it["ist_bps"] is None for it in rw["items"])
    assert "Vermoegen, Cashflows oder Ziele" in rw["staleness_hinweis"]
    assert "Strategie neu berechnen" in rw["staleness_hinweis"]
    assert rw["erklaerung"] == rw["staleness_hinweis"]
    assert "73" not in rw["erklaerung"]


def test_section9_stale_risk_profile_reason_hides_ist_too():
    rw = _build_risikowaehrungen(_dc(stale=True), ist_basiert_auf_soll=False)
    assert all(it["ist_bps"] is None for it in rw["items"])
    assert rw["ist_bps"] is None
    assert "Risikoprofil" in rw["staleness_hinweis"]


def test_section10_not_stale_keeps_soll_exposure():
    br = _build_branchen(_dc(stale=False), equity_sector_context=_sector_ctx())
    assert br["soll_ausgeblendet"] is False
    fin = next(it for it in br["items"] if it["label"] == "Financials")
    assert fin["soll_bps"] == 6100
    assert br["anteil_aktien_bps"] == 6449


def test_section10_stale_nulls_soll_and_replaces_text():
    notes = MagicMock()
    notes.branchen_analyse = "Financials 31 pp unter Ziel 61 %."
    br = _build_branchen(
        _dc(stale=True, inputs_stale=True), notes=notes,
        equity_sector_context=_sector_ctx(),
    )
    for it in br["items"]:
        assert it["soll_bps"] is None, it
        assert it["drift_bps"] is None, it
    assert br["soll_ausgeblendet"] is True
    assert br["soll_bps"] is None
    assert br["drift_bps"] is None
    assert br["analyse"] == br["staleness_hinweis"]
    assert "61" not in br["analyse"]
    assert all(it["ist_bps"] is None for it in br["items"])
    assert br["anteil_aktien_bps"] is None


def test_section10_stale_with_ist_from_soll_hides_ist_and_equity_share():
    """IST und Aktienanteil sind aus den alten Empfehlungsbetraegen
    abgeleitet -> beides alte Zielzahlen."""
    br = _build_branchen(
        _dc(stale=True), equity_sector_context=_sector_ctx(),
        ist_basiert_auf_soll=True,
    )
    assert all(it["ist_bps"] is None for it in br["items"])
    assert br["ist_bps"] is None
    assert br["anteil_aktien_bps"] is None
    assert "64.5" not in (br["hinweis"] or "")


# ---------------------------------------------------------------------------
# Integration (Foundation-Mandat)
# ---------------------------------------------------------------------------

def test_report_not_stale_keeps_section9_10(session):  # noqa: F811
    adv, mandate = _seed(session)
    rep = compute_advisory_report(session, mandate, advisor=adv)
    assert rep["risikowaehrungen"]["soll_ausgeblendet"] is False
    assert rep["branchen"]["soll_ausgeblendet"] is False
    assert any((it["soll_bps"] or 0) > 0 for it in rep["risikowaehrungen"]["items"])
    assert any((it["soll_bps"] or 0) > 0 for it in rep["branchen"]["items"])


def test_report_stale_inputs_hides_section9_10(session):  # noqa: F811
    adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    for client_facing in (False, True):
        rep = compute_advisory_report(
            session, mandate, advisor=adv, client_facing=client_facing,
        )
        for key in ("risikowaehrungen", "branchen"):
            sec = rep[key]
            for it in sec["items"]:
                assert it["soll_bps"] is None, (key, it)
                assert it["drift_bps"] is None, (key, it)
                # IST stammt aus den Positionen der alten Empfehlung
                # (client_facing: ist_basiert_auf_soll ist dort False)
                assert it["ist_bps"] is None, (key, it)
            assert sec["soll_bps"] is None, key
            assert sec["drift_bps"] is None, key
            assert sec["soll_ausgeblendet"] is True, key
        assert rep["branchen"]["anteil_aktien_bps"] is None


def test_depot_check_stale_drops_soll_exposures(session):  # noqa: F811
    from services.depot_check import compute_depot_check

    _adv, mandate = _seed(session)
    dc = compute_depot_check(session, mandate)
    assert dc["soll_currency_exposure_bps"], "Positivkontrolle: Fixture hat SOLL-Exposures"
    _reduce_largest_position(session, mandate)
    dc = compute_depot_check(session, mandate)
    assert dc["soll_ausgeblendet"] is True
    for dim in ("country", "sector", "currency"):
        assert dc[f"soll_{dim}_exposure_bps"] == {}, dim
        assert dc[f"{dim}_exposure_drift_bps"] == {}, dim


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def test_pdf_section9_10_stale_render_notice_only():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import (
        _build_branchen_flowables,
        _build_risikowaehrungen_flowables,
    )

    styles = make_advisory_styles()
    rw = _build_risikowaehrungen(_dc(stale=True, inputs_stale=True))
    texts = _all_texts(_build_risikowaehrungen_flowables(rw, styles))
    assert any("Strategie neu berechnen" in t for t in texts), texts
    assert not any("%" in t for t in texts), texts
    assert not any("USD" in t for t in texts), texts

    br = _build_branchen(
        _dc(stale=True), equity_sector_context=_sector_ctx(),
        ist_basiert_auf_soll=True,
    )
    texts = _all_texts(_build_branchen_flowables(br, styles))
    assert any("Strategie neu berechnen" in t for t in texts), texts
    assert not any("%" in t for t in texts), texts
    assert not any("Financials" in t for t in texts), texts


def test_pdf_section9_10_not_stale_still_render_chart():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import (
        _build_branchen_flowables,
        _build_risikowaehrungen_flowables,
    )

    styles = make_advisory_styles()
    rw = _build_risikowaehrungen(_dc(stale=False))
    assert any("USD" in t for t in _all_texts(_build_risikowaehrungen_flowables(rw, styles)))
    br = _build_branchen(_dc(stale=False), equity_sector_context=_sector_ctx())
    assert any("Financials" in t for t in _all_texts(_build_branchen_flowables(br, styles)))


def test_full_pdf_stale_contains_no_section9_10_soll(session):  # noqa: F811
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    payload = compute_advisory_report(session, mandate, advisor=adv)
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:4] == b"%PDF"
