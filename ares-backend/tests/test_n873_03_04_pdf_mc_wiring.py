"""N-873-03 / N-873-04 (Dok. 86, Pruefrunde H2): MC-Kennzahlen 0 im PDF.

* N-873-03: Die Verdrahtung in ``_build_anlagestrategie_data`` und die
  SOLL/IST-Tabelle waren nicht getestet (Mutanten blieben gruen).
* N-873-04: Der MC-Erzeuger liefert fuer leere Stichproben den Platzhalter 0;
  ohne auswertbare Verteilung (< 2 Pfade, Horizont < 1) sind die Kennzahlen
  None. Das aeussere ``has_metrics``-Gate folgt derselben Regel wie die
  Kennzahlen-Kachel.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from pypdf import PdfReader

import services.portfolio_engine as pe
from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.components.sollist_vergleich import make_sollist_kennzahlen_table
from services.pdf.reportlab_renderer import ReportLabRenderer
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401
    _create_client_and_mandate,
    _seed_products,
    _seed_risk_profile,
    advisor_user,
    api,
    session_factory,
)

MC_KEYS = {
    "target_max_drawdown_p50_bps": "max_drawdown_bps",
    "target_var_95_1y_bps": "var_95_bps",
    "target_annualized_return_p50_bps": "median_cagr_bps",
    "current_annualized_return_p50_bps": "current_annualized_return_p50_bps",
    "target_volatility_1y_bps": "target_volatility_1y_bps",
    "current_volatility_1y_bps": "current_volatility_1y_bps",
}


def _strategy_data(api, advisor_user, session_factory, monkeypatch, mc_override: dict):
    from models.mandates import Mandate
    from routers.pdf_reports import _build_anlagestrategie_data

    cid, mid = _create_client_and_mandate(api, advisor_user)
    r = api.post(f"/clients/{cid}/wealth-positions", json={
        "label": "Konto Synth", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
        "current_value_rappen": 50_000_00, "currency": "CHF",
        "liquidity_instrument": "Kontoguthaben", "data_classification": "synthetic",
    })
    assert r.status_code == 201, r.text
    _seed_risk_profile(api, mid)
    _seed_products(api, advisor_user)
    alloc = api.post(f"/mandates/{mid}/target-allocation/generate", json={})
    assert alloc.status_code in (200, 201), alloc.text

    real = pe.build_target_payload_from_allocation

    def _payload(*args, **kwargs):
        payload = real(*args, **kwargs)
        payload["monte_carlo"] = {**(payload.get("monte_carlo") or {}), **mc_override}
        return payload

    monkeypatch.setattr(pe, "build_target_payload_from_allocation", _payload)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        return _build_anlagestrategie_data(mandate, db)


def test_builder_passes_computed_zero_through(api, advisor_user, session_factory, monkeypatch):
    override = {key: 0 for key in MC_KEYS} | {"simulations": 500, "horizon_years": 10}
    data = _strategy_data(api, advisor_user, session_factory, monkeypatch, override)
    for field in MC_KEYS.values():
        assert getattr(data, field) == 0, field


def test_builder_treats_degenerate_distribution_as_missing(api, advisor_user, session_factory, monkeypatch):
    override = {key: 0 for key in MC_KEYS} | {"simulations": 1, "horizon_years": 10}
    data = _strategy_data(api, advisor_user, session_factory, monkeypatch, override)
    for field in MC_KEYS.values():
        assert getattr(data, field) is None, field


def test_sollist_table_renders_with_zero_return_only():
    common = dict(
        target_median_end_rappen=None, target_p90_end_rappen=None, target_p10_end_rappen=None,
        current_median_end_rappen=None, current_p90_end_rappen=None, current_p10_end_rappen=None,
        target_volatility_1y_bps=0, current_volatility_1y_bps=0,
    )
    assert make_sollist_kennzahlen_table(target_cagr_bps=0, current_cagr_bps=0, **common)
    assert make_sollist_kennzahlen_table(target_cagr_bps=None, current_cagr_bps=None, **common) == []


CTX = PDFContext(mandate_name="Muster", advisor_name="Berater", advisor_org="Muster AG",
                 report_date=date(2026, 11, 7), audit_hash="abc123def456789012345678", locale="de-CH")
TARGET = {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 10000}


def test_outer_gate_shows_computed_zero_metrics():
    data = AnlagestrategieData(
        target_allocation_bps=TARGET, cma_expected_return_bps=0, cma_expected_vol_bps=0,
        horizon_years=10, advisory_wealth_rappen=100_000_00,
        max_drawdown_bps=0, var_95_bps=0, median_cagr_bps=0,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(CTX, data)
    flat = " ".join(" ".join((pg.extract_text() or "") for pg in PdfReader(BytesIO(pdf)).pages).split()).upper()
    assert "NOCH KEINE MONTE-CARLO-SIMULATION" not in flat
    assert "VAR 95% 0.00%" in flat
