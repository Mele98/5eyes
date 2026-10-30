"""DEPOT-E2E-SNAPSHOT-001 (c): Kosten-, Benchmark- und Stresskatalog-Inputs
des Depot-Checks sind im gespeicherten DepotCheckAnalysisSnapshot gebunden.

Vertrag:
* ``analysis["inputs"]`` haelt den verwendeten Kostenausweis (samt Hash und
  Nachweis-Hash), die HouseMatrix-Benchmark-Referenz (Gewichte + Status) und
  ``stress_catalog_hash()`` samt den damit gerechneten Stress-Szenarien.
* JSON (``GET /depot-check?analysis_snapshot_id=``) und PDF lesen diese
  gespeicherten Werte -- nie live nachgelesen.
* Weicht der Live-Stand ab, zeigt das PDF durchgehend den gespeicherten Stand
  mit Hinweis "Stand vom <Datum>" -- nie still gemischt.
* Ein Depot-Check ohne gebundene Inputs (Version 1) bleibt lesbar; das PDF
  weist die dann live gelesenen Inputs ausdruecklich aus.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from routers.allocation import get_depot_check  # noqa: E402
from routers.pdf_reports import _build_depotcheck_data  # noqa: E402
from services import backtest_stress  # noqa: E402
from services import depot_check_snapshot as dca  # noqa: E402
from services.depot_snapshot import _sha256  # noqa: E402
from tests.test_depot_e2e_snapshot_identity import (  # noqa: E402,F401
    _seed_with_holdings,
    _store_analysis,
    session_factory,
)


def _stored(session):
    mandate, advisor = _seed_with_holdings(session)
    _snapshot, created = _store_analysis(session, mandate, advisor)
    analysis = dca.load_depot_check_analysis(session, mandate, created["analysis_snapshot_id"])
    return mandate, advisor, created, analysis


@pytest.mark.timeout(300)
def test_analysis_binds_cost_benchmark_and_stress_catalog(session_factory):
    from services.cost_disclosure import build_cost_disclosure

    with session_factory() as session:
        mandate, _advisor, _created, analysis = _stored(session)
        live_cost = build_cost_disclosure(session, mandate)
    inputs = analysis["inputs"]
    assert analysis["analysis_version"] == "DepotCheckAnalysisV2"
    assert inputs["stress_catalog_hash"] == backtest_stress.stress_catalog_hash()
    assert inputs["cost_disclosure"]["cost_items"] == live_cost["cost_items"]
    assert inputs["cost_disclosure_hash"] == _sha256(inputs["cost_disclosure"])
    assert inputs["cost_evidence_content_hash"] == live_cost.get("content_hash")
    assert set(inputs["benchmark"]) == {"weights_bps", "status"}
    assert inputs["benchmark_hash"] == _sha256(inputs["benchmark"])
    assert inputs["stress"]["scenarios"], "Stress-Szenarien fehlen im Snapshot"
    assert len(inputs["captured_on"]) == 10


@pytest.mark.timeout(300)
def test_json_and_pdf_read_the_bound_inputs(session_factory, monkeypatch):
    import routers.pdf_reports as pdf_reports

    seen = []
    real_backtest = pdf_reports._build_backtest_data

    def _spy(*args, **kwargs):
        seen.append(kwargs.get("benchmark_weights_bps"))
        return real_backtest(*args, **kwargs)

    monkeypatch.setattr(pdf_reports, "_build_backtest_data", _spy)
    with session_factory() as session:
        mandate, advisor, created, analysis = _stored(session)
        json_payload = get_depot_check(
            mandate.id, analysis_snapshot_id=created["analysis_snapshot_id"],
            db=session, current_user=advisor,
        )
        pdf = _build_depotcheck_data(mandate, session, analysis=analysis)
    inputs = analysis["inputs"]
    assert json_payload["inputs"] == inputs
    assert created["inputs"] == inputs
    assert dict(pdf.cost_disclosure) == inputs["cost_disclosure"]
    assert list(pdf.stress_scenarios) == inputs["stress"]["scenarios"]
    assert pdf.performance["house_matrix_benchmark"] == inputs["benchmark"]["status"]
    # Der historische Vergleich rechnet mit der gebundenen Benchmark-Referenz.
    assert seen == [inputs["benchmark"]["weights_bps"] or None]
    assert pdf.inputs_note is None


@pytest.mark.timeout(300)
def test_pdf_shows_stored_inputs_with_stand_note_when_live_changed(session_factory, monkeypatch):
    with session_factory() as session:
        mandate, _advisor, _created, analysis = _stored(session)
        stored_cost = analysis["inputs"]["cost_disclosure"]
        changed = copy.deepcopy(stored_cost)
        changed["note"] = "Live-Kostenausweis inzwischen geaendert."
        monkeypatch.setattr(
            "services.cost_disclosure.build_cost_disclosure", lambda db, m, **kw: changed,
        )
        monkeypatch.setattr(backtest_stress, "stress_catalog_hash", lambda: "0" * 64)
        pdf = _build_depotcheck_data(mandate, session, analysis=analysis)
    assert dict(pdf.cost_disclosure) == stored_cost
    assert list(pdf.stress_scenarios) == analysis["inputs"]["stress"]["scenarios"]
    day = analysis["inputs"]["captured_on"]
    stand = f"{day[8:10]}.{day[5:7]}.{day[0:4]}"
    assert pdf.inputs_note and f"Stand vom {stand}" in pdf.inputs_note
    assert "Kostenausweis" in pdf.inputs_note and "Stresskatalog" in pdf.inputs_note
    assert "Benchmark" not in pdf.inputs_note


@pytest.mark.timeout(300)
def test_verify_rejects_tampered_inputs(session_factory):
    with session_factory() as session:
        _mandate, _advisor, _created, analysis = _stored(session)
    forged = copy.deepcopy(analysis)
    forged["inputs"]["stress_catalog_hash"] = "0" * 64
    with pytest.raises(dca.DepotCheckAnalysisIntegrityError):
        dca.verify_depot_check_analysis(forged)
    # Auch mit nachgerechnetem Gesamt-Hash: Teil-Hash passt nicht zum Inhalt.
    forged = copy.deepcopy(analysis)
    forged["inputs"]["cost_disclosure"]["note"] = "manipuliert"
    body = {key: forged[key] for key in dca._BODY_KEYS}
    forged["analysis_hash"] = _sha256(body)
    forged["analysis_snapshot_id"] = f"dca-{forged['analysis_hash'][:24]}"
    with pytest.raises(dca.DepotCheckAnalysisIntegrityError):
        dca.verify_depot_check_analysis(forged)


def test_render_shows_inputs_note():
    from datetime import date
    from io import BytesIO

    from pypdf import PdfReader

    from services.pdf.base import DepotCheckData, PDFContext
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(
        mandate_name="Muster Mandat", advisor_name="Anna Beratung",
        advisor_org="Beratungshaus", report_date=date(2026, 10, 30), audit_hash="dca-test",
    )
    pdf = ReportLabRenderer().render_depotcheck(ctx, DepotCheckData(
        mandate_number="M-DCA",
        cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
        performance={"data_pending": True, "note": "Daten ausstehend."},
        inputs_note="Stand vom 28.10.2026: Kostenausweis seither geaendert.",
    ))
    flat = " ".join(
        " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages).split()
    )
    assert "Stand vom 28.10.2026" in flat


@pytest.mark.timeout(300)
def test_v1_analysis_without_bound_inputs_stays_readable_and_is_marked(session_factory):
    with session_factory() as session:
        mandate, _advisor, _created, analysis = _stored(session)
        legacy = {key: analysis[key] for key in dca._BODY_KEYS_V1}
        legacy["analysis_version"] = "DepotCheckAnalysisV1"
        legacy["analysis_hash"] = _sha256(legacy)
        legacy["analysis_snapshot_id"] = f"dca-{legacy['analysis_hash'][:24]}"
        dca.verify_depot_check_analysis(legacy)
        assert "inputs" not in dca.public_depot_check_payload(legacy)
        pdf = _build_depotcheck_data(mandate, session, analysis=legacy)
    assert pdf.inputs_note and "aktueller Stand" in pdf.inputs_note
