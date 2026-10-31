"""MC-CONTEXT-001 Folgefix: Backtest-/Stress-Exporte folgen dem Report-
Projection-Gate (services/report_projection_gate.py, PR #663).

Befund: ``GET /mandates/{id}/reports/backtest.pdf`` und die zugehoerige API
``GET /mandates/{id}/backtest/strategy`` (sowie ``/backtest/stress-replays``
und der Performance-/Stress-Teil des Depotcheck-PDFs) lasen die aktuelle
Soll-Allokation direkt und projizierten deren Gewichte auf historische
Renditen -- ohne Staleness-Pruefung. Nach einem neuen Risikoprofil, nach
geaenderten Inputs oder ganz ohne eindeutig aktuelles Risikoprofil erschien
ein Soll-Backtest einer nicht mehr gueltigen Strategie, ausgewiesen als
aktuell.

Vertrag (identisch zum Advisory-Report):
* ein Gate-Entscheid ``resolve_report_projection_gate``; ``stale``,
  ``blocked`` (und jeder unbekannte Status) blenden fail-closed aus;
* ausgeblendet: Soll-Pfad, Soll-Kennzahlen, Soll-Gewichte, Stress-Szenarien;
* der Berater sieht den Gate-Hinweis ("Strategie neu berechnen" bzw.
  "Kein aktuelles Risikoprofil – Projektionen ausgeblendet");
* ein frei gewaehlter Benchmark-Mix haengt nicht von der Soll-Allokation ab
  und bleibt sichtbar;
* aktueller Kontext: alles befuellt (Positivkontrolle).
"""
from __future__ import annotations

import datetime
import uuid
from io import BytesIO

import pytest
from pypdf import PdfReader

from models.snapshots import AssetClassAnnualReturn
from models.mandates import Mandate
from models.wealth import WealthPosition
import services.portfolio_engine as pe
from services.report_projection_gate import HINT_NO_ASSESSMENT, RECOMPUTE_HINT
from tests.test_report_mc_allocation_staleness import (
    _generate,
    _replace_current_assessment,
)
from tests.test_report_projection_gate_blocked import _drop_current_assessment
from tests.test_sim_horizon_from_risk_profile_backend import (  # noqa: F401
    _seed_mandate,
    advisor_user,
    auth_client,
    session_factory,
)

_BENCHMARK_QS = (
    "benchmark_equities_bps=5000&benchmark_bonds_bps=5000"
    "&benchmark_real_estate_bps=0&benchmark_alternatives_bps=0"
    "&benchmark_liquidity_bps=0"
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _seed_annual_returns(session_factory) -> None:
    now = _now()
    data = [
        (2018, {"Aktien": -1000, "Obligationen": 100, "Immobilien": -500, "Alternative": -300, "Liquiditaet": 50}),
        (2019, {"Aktien": 2800, "Obligationen": 600, "Immobilien": 1500, "Alternative": 1000, "Liquiditaet": 40}),
        (2020, {"Aktien": 1500, "Obligationen": 700, "Immobilien": -200, "Alternative": 800, "Liquiditaet": 20}),
        (2021, {"Aktien": 2200, "Obligationen": -150, "Immobilien": 2400, "Alternative": 1200, "Liquiditaet": 10}),
    ]
    with session_factory() as s:
        existing = {
            (int(r.year), str(r.asset_class))
            for r in s.query(AssetClassAnnualReturn).all()
        }
        for year, returns in data:
            for asset_class, bps in returns.items():
                if (year, asset_class) in existing:
                    continue
                s.add(AssetClassAnnualReturn(
                    id=str(uuid.uuid4()), year=year, asset_class=asset_class,
                    return_bps=bps, source="test", created_at=now, updated_at=now,
                ))
        s.commit()


def _setup(session_factory, advisor_user) -> str:
    mid = _seed_mandate(session_factory, advisor_user.id)
    _seed_annual_returns(session_factory)
    _generate(session_factory, mid, advisor_user.id)
    return mid


def _make_inputs_stale(session_factory, mid: str) -> None:
    now = _now()
    with session_factory() as s:
        client_id = s.get(Mandate, mid).client_id
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client_id, label="Neues Depot",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=10000, alloc_bonds_bps=0, alloc_real_estate_bps=0,
            alloc_liquidity_bps=0, alloc_alternatives_bps=0, is_active=1,
            created_at=now, updated_at=now,
        ))
        s.commit()


def _strategy(auth_client, mid: str) -> dict:
    resp = auth_client.get(f"/mandates/{mid}/backtest/strategy?{_BENCHMARK_QS}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_soll_hidden(body: dict, *, status: str, hint_fragment: str) -> None:
    assert body["soll"] is None, "Soll-Backtest einer ungueltigen Allokation publiziert"
    assert body["soll_weights_bps"] == {}
    gate = body["projection_gate"]
    assert gate["status"] == status
    assert gate["projections_hidden"] is True
    joined = " ".join(body["warnings"])
    assert hint_fragment in joined, body["warnings"]
    # Benchmark-Mix haengt nicht von der Soll-Allokation ab -> bleibt.
    assert body["benchmark"] is not None
    assert body["benchmark"]["rebalanced"]["wealth_path_rappen"]


def _pdf_main_page_text(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    return reader.pages[1].extract_text() or ""


# ---------------------------------------------------------------------------
# API /backtest/strategy
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_strategy_backtest_api_current_then_stale_assessment_hides_soll(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)

    fresh = _strategy(auth_client, mid)
    # Positivkontrolle: sonst waere das Ausblenden unten trivial gruen.
    assert fresh["projection_gate"]["status"] == "current"
    assert fresh["projection_gate"]["projections_hidden"] is False
    assert fresh["soll"]["rebalanced"]["wealth_path_rappen"]
    assert sum(fresh["soll_weights_bps"].values()) == 10000

    _replace_current_assessment(session_factory, mid, advisor_user.id)
    _assert_soll_hidden(
        _strategy(auth_client, mid), status="stale", hint_fragment=RECOMPUTE_HINT,
    )


@pytest.mark.timeout(180)
def test_strategy_backtest_api_changed_inputs_hide_soll(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)
    _make_inputs_stale(session_factory, mid)
    _assert_soll_hidden(
        _strategy(auth_client, mid), status="stale", hint_fragment=RECOMPUTE_HINT,
    )


@pytest.mark.timeout(180)
def test_strategy_backtest_api_blocked_without_current_assessment(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)
    _drop_current_assessment(session_factory, mid)
    _assert_soll_hidden(
        _strategy(auth_client, mid), status="blocked",
        hint_fragment=HINT_NO_ASSESSMENT,
    )


# ---------------------------------------------------------------------------
# Backtest-PDF
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_backtest_pdf_current_then_blocked_hides_soll_keeps_benchmark(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)

    fresh = auth_client.get(f"/mandates/{mid}/reports/backtest.pdf?{_BENCHMARK_QS}")
    assert fresh.status_code == 200, fresh.text
    fresh_text = _pdf_main_page_text(fresh.content)
    assert "SOLL-Strategie" in fresh_text
    assert "Projektionen ausgeblendet" not in fresh_text

    _drop_current_assessment(session_factory, mid)
    resp = auth_client.get(f"/mandates/{mid}/reports/backtest.pdf?{_BENCHMARK_QS}")
    assert resp.status_code == 200, resp.text
    text = _pdf_main_page_text(resp.content)
    assert HINT_NO_ASSESSMENT in text, text
    assert "SOLL-Strategie" not in text, text
    # Benchmark-Historie bleibt sichtbar.
    assert "Benchmark" in text


@pytest.mark.timeout(180)
def test_backtest_pdf_stale_assessment_shows_recompute_hint(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)
    _replace_current_assessment(session_factory, mid, advisor_user.id)
    resp = auth_client.get(f"/mandates/{mid}/reports/backtest.pdf")
    assert resp.status_code == 200, resp.text
    text = _pdf_main_page_text(resp.content)
    assert "Strategie neu berechnen" in text, text
    assert "SOLL-Strategie" not in text, text


# ---------------------------------------------------------------------------
# Weitere Soll-Projektionen: Stress-Replays-API, Depotcheck-PDF
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_stress_replays_api_current_then_blocked_hides_scenarios(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)
    fresh = auth_client.get(f"/mandates/{mid}/backtest/stress-replays")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["scenarios"]

    _drop_current_assessment(session_factory, mid)
    resp = auth_client.get(f"/mandates/{mid}/backtest/stress-replays")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenarios"] == []
    assert body["weights_bps"] == {}
    assert body["projection_gate"]["status"] == "blocked"
    assert body["projection_gate"]["projections_hidden"] is True
    assert HINT_NO_ASSESSMENT in body["warning"]


@pytest.mark.timeout(180)
def test_depotcheck_pdf_blocked_refuses_soll_projection(
    session_factory, advisor_user, auth_client  # noqa: F811
):
    mid = _setup(session_factory, advisor_user)
    _drop_current_assessment(session_factory, mid)
    resp = auth_client.get(f"/mandates/{mid}/reports/depotcheck.pdf")
    assert resp.status_code == 409, resp.text
    assert HINT_NO_ASSESSMENT in resp.json()["detail"]
