"""CERT-HANDOFF-EXECUTION-001 -- permanent repository reproducers.

Source of truth: the Ares/Codex audit worktree
`C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\asset-allocation-stochastic-core`
(branch `codex/asset-allocation-stochastic-core`),
`docs/audits/2026-10-08-portfolio-handoff-delivery-execution-and-integrity-certification-spec.md`.
That spec documents eight reproduced-but-not-committed findings for
`HANDOFF-DELIVERY-001`, `HANDOFF-VALUATION-001`, `HANDOFF-MATH-001`,
`HANDOFF-UI-CONTRACT-001`, `HANDOFF-INSTRUCTION-001`,
`HANDOFF-IDEMPOTENCY-001`, `HANDOFF-EXECUTION-001` and
`HANDOFF-INTEGRITY-001` (its own temporary reproducer was deliberately
removed after the run, per its `product_code_mutated: false` /
`tests_mutated: false` audit discipline). Step 1 of the spec's own
"Implementierungsreihenfolge fuer Claude" (Section 13) is to adopt these
eight reproducers as PERMANENT repository tests before touching any product
code. This file is that step.

All eight root causes below were independently re-verified against this
repo's actual current `develop` HEAD
(717ce3ab529d53c9fb355ee2b401932829ea0054) before writing these tests -- not
copied from the spec's historical evidence (recorded against the older
`e77910c5242d7033fb04787c8b768495b0877b29`) unchecked.

`HANDOFF-STATE-001` already has an atomic conditional update
(`routers/portfolio_handoff.py::_atomically_close_handoff_or_409`) and a
green two-session test
(`test_portfolio_handoff.py::test_concurrent_mark_executed_and_cancel_do_not_both_succeed`).
That is real, pre-existing fix evidence -- it is explicitly NOT in this
package's scope and is neither touched nor duplicated here.

Do not close any of these by weakening the assertion, deleting the test, or
loosening a schema/model field to make the symptom disappear without the
underlying evidence contract (immutable `ExecutionInstructionSnapshotV1`,
real holdings/price/FX coverage, reconciled per-trade/portfolio math, a pure
action-code UI contract, idempotent prepare, transactional outbox delivery
evidence, and append-only order/fill/settlement events -- spec Section 4-9).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.mandates import Mandate  # noqa: E402
from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from schemas.portfolio_handoff import (  # noqa: E402
    PortfolioHandoffCreate,
    PortfolioHandoffMarkExecuted,
    PortfolioHandoffResponse,
)
import services.portfolio_handoff as portfolio_handoff_service  # noqa: E402
from services.portfolio_engine_live_rebalancing import _build_live_position_drifts  # noqa: E402

# Reused fixtures/helpers -- identical convention to
# test_cert_product_eligibility_001_reproducers.py importing
# _seed_realistic_mandate from test_optimizer_shadow_mode.py.
from test_portfolio_handoff import (  # noqa: E402
    _FakeRequest,
    _create_handoff,
    _drift,
    _patch_engine,
    _seed_mandate_and_run,
    advisor_user,
    session_factory,
)

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# HANDOFF-DELIVERY-001 -- a local DB insert immediately claims "Gesendet"
# with no transport attempt, no outbox message, no recipient-endpoint
# identity and no delivery receipt (routers/portfolio_handoff.py:174-204 at
# the spec's historical head; create_portfolio_handoff() today still sets
# status=_OPEN_STATUS="Gesendet" synchronously with the local commit).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-DELIVERY-001 -- CERT-HANDOFF-EXECUTION-001")
def test_local_insert_must_not_claim_sent_without_transport_evidence(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        created = _create_handoff(session, advisor_user)

        # Soll (Spec Section 4.4/6/12.1 Nr.1): ohne Transportadapter,
        # Empfaenger-Endpoint-Identitaet und Provider-Message-ID darf ein
        # rein lokaler Insert hoechstens "PREPARED_FOR_MANUAL_DELIVERY" sein
        # -- nie "Gesendet". Heute setzt create_portfolio_handoff() den
        # Endzustand "Gesendet" synchron mit dem lokalen Commit.
        assert created.status != "Gesendet"


# ---------------------------------------------------------------------------
# HANDOFF-VALUATION-001 -- snapshot_handoff_trades() reads only
# position_drifts/live_total_value_rappen and ignores the valuation-coverage
# aggregates (holding_positions_count, implied_positions_count, etc.) that
# build_live_rebalancing_payload() already computes
# (services/portfolio_engine_live_rebalancing.py:598-652). A payload backed
# by zero real holdings still produces a handoff snapshot.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-VALUATION-001 -- CERT-HANDOFF-EXECUTION-001")
def test_snapshot_blocks_when_no_real_holding_backs_any_trade(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    payload = {
        "live_rebalancing": {
            "live_total_value_rappen": 1_000_000,
            "holding_positions_count": 0,
            "implied_positions_count": 1,
            "position_drifts": [_drift("prod-1", 50_000)],
        }
    }
    monkeypatch.setattr(portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()

        # Soll (Spec Section 3.2/4.3): eine ausschliesslich target-implied
        # Positionsbasis (holding_positions_count=0) ist eine
        # Anzeige-/Analysehilfe, kein Beweis eines realen Depotbestands, und
        # darf keinen ausfuehrungsnahen Execution-Snapshot erzeugen. Heute
        # liest snapshot_handoff_trades() nur position_drifts und
        # live_total_value_rappen und ignoriert die Coverage-Aggregate
        # komplett.
        with pytest.raises(ValueError):
            portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)


# ---------------------------------------------------------------------------
# HANDOFF-MATH-001 -- _build_live_position_drifts() recomputes
# rebalance_amount_rappen from live_total_value_rappen (line ~543) but
# passes the pre-existing target_amount_rappen through unchanged via
# {**entry, ...} (line ~549) -- IST + Delta no longer reconciles against the
# displayed SOLL once live_total_value_rappen has drifted from the
# historical advisory-wealth basis the SOLL amount was computed on. Uses the
# exact figures from the spec's own reproducer (Section 3.3).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-MATH-001 -- CERT-HANDOFF-EXECUTION-001")
def test_ist_plus_delta_must_equal_soll_on_same_live_basis():
    entries = [{
        "product_id": "prod-math",
        "current_market_value_rappen": 1_000_000,
        "target_weight_bps": 5000,
        "target_amount_rappen": 500_000,  # historischer SOLL (alte Advisory-Wealth-Basis)
        "latest_price_rappen": 10_000,
        "reference_price_rappen": 10_000,
    }]
    # live_total_value_rappen ist auf 1'500'000 gewachsen, seit der
    # historische SOLL-Betrag berechnet wurde (identisch zum Spec-Beispiel).
    drifts = _build_live_position_drifts(entries, live_total_value_rappen=1_500_000)
    entry = drifts[0]

    # Soll (Spec Section 5.1): current_market_value_rappen +
    # delta_notional_minor == target_market_value_minor (bis auf
    # dokumentierte Rundung) -- dieselbe Bewertungsbasis fuer IST, Delta und
    # SOLL. Heute bleibt target_amount_rappen auf der alten Basis stehen,
    # waehrend rebalance_amount_rappen auf der neuen Live-Basis neu
    # berechnet wird.
    assert entry["current_market_value_rappen"] + entry["rebalance_amount_rappen"] == entry["target_amount_rappen"]


# ---------------------------------------------------------------------------
# HANDOFF-UI-CONTRACT-001 -- openTradeList() in 5eyes_v2.html compares the
# localized label p.rebalance_action against 'BUY'/'SELL' for sums and
# colors, instead of the stable p.rebalance_action_code. Since
# rebalance_action is ALWAYS the German label ("Aufbauen"/"Reduzieren", see
# services/portfolio_engine_live_rebalancing.py::_rebalancing_action_meta),
# this comparison can never match in production.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-UI-CONTRACT-001 -- CERT-HANDOFF-EXECUTION-001")
def test_trade_list_ui_compares_action_code_not_localized_label():
    html = _html()
    start = html.index("function openTradeList()")
    end = html.index("function renderPortfolioHandoffSection()", start)
    body = html[start:end]

    # Soll (Spec Section 5.1/10): Fachlogik, Summen und Farben konsumieren
    # ausschliesslich rebalance_action_code (BUY/SELL/HOLD/...), niemals das
    # lokalisierte Label. Heute vergleicht openTradeList() direkt gegen
    # p.rebalance_action, das produktionsseitig immer der deutsche Label-Text
    # ist ('Aufbauen'/'Reduzieren') -- der Vergleich mit 'BUY'/'SELL' kann
    # dort nie zutreffen.
    assert "p.rebalance_action_code==='BUY'" in body
    assert "p.rebalance_action_code==='SELL'" in body
    assert "actionColor(p.rebalance_action_code)" in body


# ---------------------------------------------------------------------------
# HANDOFF-INSTRUCTION-001 -- the curated snapshot
# (services/portfolio_handoff.py::_SNAPSHOT_TRADE_FIELDS) drops instrument
# identity, custody account, quantity, price/FX anchors and order type even
# when the source drift entry carries them.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-INSTRUCTION-001 -- CERT-HANDOFF-EXECUTION-001")
def test_snapshot_preserves_executable_instruction_fields_when_source_has_them(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    drift = _drift(
        "prod-1", 50_000,
        isin="CH0012032048",
        custody_account_id="CUST-001",
        current_units_milli=1_000_000,
        fx_rate=1.0,
        order_type="LIMIT",
    )
    _patch_engine(monkeypatch, [drift])

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == "mandate-1").one()
        run = session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").one()
        trades, _total = portfolio_handoff_service.snapshot_handoff_trades(session, mandate, run, advisor_user.id)
    snapshot_trade = trades[0]

    # Soll (Spec Section 4.2/3.5): jede Tradezeile bindet Instrument, Konto,
    # Menge, Preis/FX-Anker und Ordertyp, wenn die Quelldaten sie enthalten
    # -- sonst ist es eine Rebalancing-Empfehlung, keine Handelsinstruktion.
    # Heute entfernt _SNAPSHOT_TRADE_FIELDS all diese Felder unbedingt.
    for required_field in (
        "isin", "custody_account_id", "current_units_milli",
        "reference_price_rappen", "fx_rate", "order_type",
    ):
        assert required_field in snapshot_trade, f"{required_field} fehlt im Snapshot"


# ---------------------------------------------------------------------------
# HANDOFF-IDEMPOTENCY-001 -- create_portfolio_handoff() takes no idempotency
# key and has no business unique-key; two identical create calls for the
# same run/recipient/trade payload produce two distinct open rows.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-IDEMPOTENCY-001 -- CERT-HANDOFF-EXECUTION-001")
def test_identical_create_retry_produces_exactly_one_open_handoff(session_factory, advisor_user, monkeypatch):
    _seed_mandate_and_run(session_factory, advisor_user)
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])
    body = PortfolioHandoffCreate(recipient_name="Bank XY Trading Desk")

    with session_factory() as session:
        first = create_portfolio_handoff(
            mandate_id="mandate-1", run_id="run-1", body=body,
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        # Identischer Retry -- z.B. Timeout-Resend, Tab-Duplikat oder
        # konkurrierender API-Aufruf, kein zweiter fachlicher Auftrag.
        second = create_portfolio_handoff(
            mandate_id="mandate-1", run_id="run-1", body=body,
            request=_FakeRequest(), db=session, current_user=advisor_user,
        )
        open_count = session.query(PortfolioHandoff).filter(
            PortfolioHandoff.mandate_id == "mandate-1",
            PortfolioHandoff.recommendation_run_id == "run-1",
        ).count()

        # Soll (Spec Section 7.1): gleicher Idempotency-/Business-Key und
        # gleicher Request-Hash => dasselbe Resultat, genau EIN
        # Snapshot/eine Outbox-Nachricht. Heute erzeugt jeder Aufruf eine
        # neue UUID und eine neue Zeile, ohne jede Pruefung auf einen
        # fachlich identischen offenen Handoff.
        assert open_count == 1
        assert first.id == second.id


# ---------------------------------------------------------------------------
# HANDOFF-EXECUTION-001 -- PortfolioHandoffMarkExecuted only defines the
# optional executed_note; a completely empty body is schema-valid and
# mark_portfolio_handoff_executed() accepts it as full execution proof with
# no external order ID, fill events, quantity/price or settlement evidence.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-EXECUTION-001 -- CERT-HANDOFF-EXECUTION-001")
def test_mark_executed_requires_fill_evidence_not_empty_body():
    # Soll (Spec Section 3.7/4.5): "Ausgefuehrt" muss aus vollstaendigen
    # Fill-Ereignissen (externe Order-ID, Menge, Preis, Settlement) abgeleitet
    # werden -- ein Advisor-Klick ohne jede Evidence ist eine Attestation,
    # kein Ausfuehrungsbeweis, und muss schema-seitig abgelehnt werden. Heute
    # ist executed_note optional und ein leerer Body damit gueltig.
    with pytest.raises(ValidationError):
        PortfolioHandoffMarkExecuted()


# ---------------------------------------------------------------------------
# HANDOFF-INTEGRITY-001 -- PortfolioHandoff has a free status string,
# unvalidated JSON snapshot content and an unreconciled position_count, with
# no DB/schema-level invariant tying any of them together.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="HANDOFF-INTEGRITY-001 -- CERT-HANDOFF-EXECUTION-001")
def test_response_schema_rejects_tampered_status_json_and_count(session_factory, advisor_user):
    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        tampered = PortfolioHandoff(
            id="handoff-tampered", mandate_id="mandate-1", recommendation_run_id="run-1",
            trade_list_snapshot_json="not-json", live_total_value_rappen=1_000_000,
            position_count=999, recipient_name="Bank XY",
            status="BROKEN", created_by=advisor_user.id,
            created_at="2026-08-08T08:00:00.000Z", updated_at="2026-08-08T08:00:00.000Z",
        )
        session.add(tampered)
        session.commit()
        session.refresh(tampered)

        # Soll (Spec Section 3.8/8): ein freier Status ausserhalb der
        # Zustandsmaschine, ungueltiges JSON im Snapshot und ein
        # position_count ohne Bezug zu tatsaechlich gespeicherten
        # Tradezeilen muessen vom Schema/DB abgelehnt werden. Heute
        # akzeptieren sowohl das ORM-Insert als auch PortfolioHandoffResponse
        # diesen manipulierten Datensatz unveraendert.
        with pytest.raises(ValidationError):
            PortfolioHandoffResponse.model_validate(tampered)
