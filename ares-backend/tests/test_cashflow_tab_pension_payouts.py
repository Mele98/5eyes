"""CASHFLOW-TAB-PENSION-PAYOUTS-001 (2026-10-21).

Seit #642/#651 wird externe Vorsorge (3a/FZ/Police) beim Bezug genau einmal
freies Vermoegen (PensionTransferLedgerV1). Der Cashflow-Tab
(/clients/{id}/cashflow-projection) und die Reserve-Nachrechnung im
Advisory-Report rechneten aber nur mit den rohen Vermoegenszufluessen.

Vertraege:
1. API-Summen = Engine-Serie: capital_inflow + pension_payout je Jahr ist
   exakt die inflow_projection_series_rappen von _load_allocation_inputs.
2. Automatischer Bezug erscheint als eigene Komponente pension_payout_rappen
   (netto nach Kapitalbezugssteuer), in income/net enthalten, NICHT in
   capital_inflow.
3. Verknuepfter Bezug zaehlt genau einmal (als erfasster Zufluss), nie
   zusaetzlich als pension_payout.
4. Inkonsistente Verknuepfung -> 409 mit reason_code (fail-closed wie Engine).
5. Report-Reserve-Nachrechnung sieht dieselbe Zufluss-Serie wie die Engine.
6. Monolith: eigene, klar beschriftete Zeile aus der API (keine eigene Formel).
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe  # noqa: E402
from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import WealthInflow, WealthPosition  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: E402,F401

MONOLITH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"
HORIZON = 12
AUTO_GROSS = 80_000_00
AUTO_NET = AUTO_GROSS - 8_000_00  # 10 % Default-Kapitalbezugssteuer
LINKED_AMOUNT = 45_000_00
OTHER_INFLOW = 30_000_00


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _seed(session_factory, *, orphan_link: bool = False):  # noqa: F811
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"cftab-{uuid.uuid4().hex[:8]}",
    )
    start = datetime.date.today().year
    with session_factory() as s:
        s.add(WealthPosition(
            id=f"pos-3a-{uuid.uuid4().hex[:8]}", client_id=client_id, label="3a Konto",
            position_type="Vorsorge", assignment="Anderes Vermögen",
            current_value_rappen=AUTO_GROSS, currency="CHF", pension_type="Säule 3a",
            liquidity_available_from=f"{start + 1}-03-31",
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        fz_id = f"pos-fz-{uuid.uuid4().hex[:8]}"
        s.add(WealthPosition(
            id=fz_id, client_id=client_id, label="FZ Konto",
            position_type="Vorsorge", assignment="Anderes Vermögen",
            current_value_rappen=50_000_00, currency="CHF", pension_type="Freizügigkeit",
            liquidity_available_from=f"{start + 2}-06-30",
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.add(WealthInflow(
            id=f"inf-fz-{uuid.uuid4().hex[:8]}", client_id=client_id, label="Kapitalbezug FZ",
            source_type="Andere", amount_rappen=LINKED_AMOUNT, expected_year=start + 2,
            is_recurring=0, frequency="einmalig", value_mode="nominal",
            linked_position_id=("pos-gibt-es-nicht" if orphan_link else fz_id),
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.add(WealthInflow(
            id=f"inf-erb-{uuid.uuid4().hex[:8]}", client_id=client_id, label="Erbschaft",
            source_type="Erbschaft", amount_rappen=OTHER_INFLOW, expected_year=start + 4,
            is_recurring=0, frequency="einmalig", value_mode="nominal",
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.commit()
        advisor = s.query(User).filter(User.id == advisor_id).one()
    return advisor, client_id, mandate_id, start


@pytest.fixture()
def api(session_factory):  # noqa: F811
    def override_db():
        with session_factory() as session:
            yield session

    holder: dict = {}
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    with TestClient(app) as client:
        yield client, holder
    app.dependency_overrides.clear()


def _projection(api, user, client_id):
    client, holder = api
    holder["user"] = user
    return client.get(f"/clients/{client_id}/cashflow-projection?horizon_years={HORIZON}")


def _engine_inputs(session_factory, mandate_id, advisor_id):  # noqa: F811
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        return pe._load_allocation_inputs(session, mandate, {}, cma=cma)


def test_api_sums_equal_engine_inflow_series(api, session_factory):  # noqa: F811
    advisor, client_id, mandate_id, start = _seed(session_factory)
    response = _projection(api, advisor, client_id)
    assert response.status_code == 200, response.text
    body = response.json()
    years = body["years"]
    assert years[0]["year"] == start

    inputs = _engine_inputs(session_factory, mandate_id, advisor.id)
    engine = inputs["inflow_projection_series_rappen"]
    assert inputs["cashflow_totals"]["year"] == start
    overlap = min(len(engine), len(years))
    assert overlap >= 5
    # Seed hat keine Kapital-Cashflows: capital_inflow stammt nur aus Zufluessen.
    api_series = [
        row["capital_inflow_rappen"] + row["pension_payout_rappen"] for row in years[:overlap]
    ]
    assert api_series == [int(v) for v in engine[:overlap]]


def test_auto_payout_is_own_component_and_linked_counts_once(api, session_factory):  # noqa: F811
    advisor, client_id, _mandate_id, start = _seed(session_factory)
    body = _projection(api, advisor, client_id).json()
    by_year = {row["year"]: row for row in body["years"]}

    payout = by_year[start + 1]
    assert payout["pension_payout_rappen"] == AUTO_NET
    assert payout["capital_inflow_rappen"] == 0
    assert payout["income_rappen"] == payout["recurring_income_rappen"] + AUTO_NET

    linked = by_year[start + 2]
    assert linked["pension_payout_rappen"] == 0  # nicht doppelt
    assert linked["capital_inflow_rappen"] == LINKED_AMOUNT

    assert by_year[start + 4]["capital_inflow_rappen"] == OTHER_INFLOW
    assert sum(row["pension_payout_rappen"] for row in body["years"]) == AUTO_NET
    assert sum(row["capital_inflow_rappen"] for row in body["years"]) == LINKED_AMOUNT + OTHER_INFLOW

    # net enthaelt den Bezug: Differenz zum Vorjahr nur durch den Bezug.
    assert payout["net_rappen"] - by_year[start]["net_rappen"] in range(AUTO_NET - 5_000_00, AUTO_NET + 5_000_00)

    transfers = {t["origin"]: t for t in body["pension_transfers"]}
    assert transfers["auto"]["year"] == start + 1
    assert transfers["auto"]["gross_withdrawal_rappen"] == AUTO_GROSS
    assert transfers["auto"]["lumpsum_tax_rappen"] + transfers["auto"]["net_advisory_inflow_rappen"] == AUTO_GROSS
    assert transfers["linked_inflow"]["net_advisory_inflow_rappen"] == LINKED_AMOUNT
    assert body["pension_ledger_hash"]


def test_inconsistent_link_is_fail_closed_409(api, session_factory):  # noqa: F811
    advisor, client_id, _mandate_id, _start = _seed(session_factory, orphan_link=True)
    response = _projection(api, advisor, client_id)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason_code"] == "PENSION_SOURCE_LINK_ORPHAN"


def test_report_reserve_recompute_uses_engine_inflow_series(session_factory, monkeypatch):  # noqa: F811
    from services import advisory_report

    advisor, _client_id, mandate_id, _start = _seed(session_factory)
    inputs = _engine_inputs(session_factory, mandate_id, advisor.id)
    engine = [int(v) for v in inputs["inflow_projection_series_rappen"]]

    captured: dict = {}
    original = pe._compute_reserve_for_inputs

    def spy(**kwargs):
        captured["inflows"] = list(kwargs["inflow_projection_series_rappen"])
        return original(**kwargs)

    monkeypatch.setattr(pe, "_compute_reserve_for_inputs", spy)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        pe.ensure_runtime_reference_data(session, advisor.id)
        result = advisory_report._recompute_reserve_reasoning(
            session, mandate, SimpleNamespace(preferences_json=None), 500,
        )
    assert result is not None
    report = captured["inflows"]
    overlap = min(len(report), len(engine))
    assert overlap >= 5
    assert report[:overlap] == engine[:overlap]
    assert report[1] == AUTO_NET


def test_monolith_renders_labeled_pension_row_from_api_fields():
    html = MONOLITH.read_text(encoding="utf-8")
    assert 'id="pension-payout-rows"' in html
    assert "Vorsorgebezug (automatisch, netto)" in html
    start = html.index("function renderPensionPayoutRows(")
    body = html[start:html.index("function renderCashflowProjection(", start)]
    assert "pension_payout_rappen" in body and "pension_transfers" in body
    # Nur verknuepfte Bezuege sind origin=linked_inflow -> Zeile listet auto.
    assert "t.origin==='auto'" in body
    comp = html[html.index("function cashflowProjectionComponents("):]
    comp = comp[:comp.index("function normalizeConversationLabels(")]
    assert "pensionPayout" in comp and "+pensionPayout-recurringExpense" in comp
