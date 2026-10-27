"""CMA-001 / ADR-12a-Release-Hold: KGV-aktive CMA blockiert finale Kanaele.

Entscheidungsdokument 2026-10-27, Abschnitt 5 ("Nomenklatur- und
Release-Hold fuer ADR-12a"): solange der Investment-Ausschuss Formel und
Kalibrierung der KGV-Bewertungsanpassung nicht entschieden hat, bleibt jede
kundenrelevante Finalisierung blockiert, in der das Adjustment tatsaechlich
wirkt. Nachweislich KGV-deaktivierte CMAs laufen unveraendert weiter.

Geprueft wird nur das Gate -- KEIN KGV-Wert und keine Formel. Die im Test
gesetzten Spaltenwerte sind beliebige gueltige Platzhalter, deren einzige
Aufgabe ist, die Spaltengruppe "gesetzt" zu machen.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.allocation import CapitalMarketAssumption, TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import ContractDocument, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers import pdf_reports  # noqa: E402
from routers.pdf_reports import get_advisory_report_pdf  # noqa: E402
from routers.portfolio_handoff import create_portfolio_handoff  # noqa: E402
from routers.review import finalize_recommendation, sign_document  # noqa: E402
from schemas.portfolio_handoff import PortfolioHandoffCreate  # noqa: E402
from schemas.review import ContractDocumentSign  # noqa: E402
from services.cma_valuation_hold import (  # noqa: E402
    CMA_ADR12A_HOLD,
    REPRESENTATION_EMBEDDED,
    REPRESENTATION_EXPLICIT,
    REPRESENTATION_UNVERIFIABLE,
    adr12a_hold_finding,
    adr12a_hold_status,
    kgv_adjustment_representation,
)
from services.recommendation_release_gate import (  # noqa: E402
    CHANNEL_ADVISORY_PDF,
    CHANNEL_CLIENT_PDF,
    assert_current_allocation_without_adr12a_hold,
    assert_recommendation_release_eligible,
)
from test_finalization_ignores_risk_budget_violated_lock import (  # noqa: E402
    _FakeRequest,
    _add_full_position,
    _allocation_policy_and_cma,
    _current_allocation_id,
    _make_run,
    _seed_realistic_mandate,
    session_factory,
)
from test_risk_budget_release_gate_channels import _add_document  # noqa: E402

_SIGNATURE = "data:image/png;base64,iVBORw0KGgo="

# Beliebige, gueltige Platzhalter (siehe Modul-Docstring) -- kein Fachwert.
_KGV_COLUMNS_SET = {
    "equity_kgv_current_x10": 200,
    "equity_kgv_fair_x10": 200,
    "equity_kgv_alpha_x100": 10,
}


def _cma(**overrides):
    base = {
        "equity_kgv_current_x10": None,
        "equity_kgv_fair_x10": None,
        "equity_kgv_alpha_x100": None,
        "equity_home_return_bps": None,
        "source_detail": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


_EMBEDDED_DETAIL = json.dumps({
    "equity_kgv_mean_reversion": {"pe_proxy_value_kgv_current": 1.0},
})


# ── reine Erkennung ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cma, expected",
    [
        (_cma(), None),
        (_cma(**_KGV_COLUMNS_SET), REPRESENTATION_EXPLICIT),
        # Teilgruppe ist kein Deaktivierungsnachweis.
        (_cma(equity_kgv_alpha_x100=10), REPRESENTATION_EXPLICIT),
        (_cma(equity_home_return_bps=1, source_detail=_EMBEDDED_DETAIL), REPRESENTATION_EMBEDDED),
        # Nachweis ohne eingerechneten Wert wirkt nicht.
        (_cma(source_detail=_EMBEDDED_DETAIL), None),
        # Uebersprungener KGV-Schritt der Pipeline wirkt nicht.
        (
            _cma(
                equity_home_return_bps=1,
                source_detail=json.dumps({"equity_kgv_mean_reversion": {"skipped_reason": "x"}}),
            ),
            None,
        ),
        (_cma(equity_home_return_bps=1, source_detail="Freitext"), None),
        (None, REPRESENTATION_UNVERIFIABLE),
    ],
)
def test_kgv_representation_matrix(cma, expected):
    assert kgv_adjustment_representation(cma) == expected
    finding = adr12a_hold_finding(cma)
    status = adr12a_hold_status(cma)
    if expected is None:
        assert finding is None
        assert status["blocks_finalization"] is False
        assert status["reason_code"] is None
    else:
        assert finding is not None and finding[0] == CMA_ADR12A_HOLD
        assert status["blocks_finalization"] is True
        assert status["reason_code"] == CMA_ADR12A_HOLD


# ── Kanaele ────────────────────────────────────────────────────────────────


def _setup(session_factory, suffix, *, kgv: str):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=suffix,
    )
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    _policy, cma_id = _allocation_policy_and_cma(session_factory, alloc_id)
    with session_factory() as db:
        cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == cma_id
        ).one()
        # Vorbedingung: das Seed traegt keine KGV-Anpassung, sonst prueft
        # der Test den falschen Grund.
        assert kgv_adjustment_representation(cma) is None
        if kgv == "explicit":
            for column, value in _KGV_COLUMNS_SET.items():
                setattr(cma, column, value)
        elif kgv == "embedded":
            cma.equity_home_return_bps = cma.equity_home_return_bps or 1
            cma.source_detail = _EMBEDDED_DETAIL
        db.commit()
    return advisor_id, mid, aid, alloc_id


@pytest.mark.parametrize("kgv", ["explicit", "embedded"])
def test_advisory_pdf_blocked_before_render(session_factory, monkeypatch, kgv):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, f"adr12a-pdf-{kgv}", kgv=kgv)
    rendered = []
    import services.pdf.documents.advisory_report as adv

    monkeypatch.setattr(
        adv, "render_advisory_report_pdf",
        lambda *a, **k: rendered.append(1) or b"%PDF",
    )
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            get_advisory_report_pdf(mandate_id=mid, db=db, current_user=advisor)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    assert "ADR-12a" in exc.value.detail["message"]
    assert rendered == []


def test_kgv_deactivated_cma_passes_hold(session_factory):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, "adr12a-off", kgv="off")
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        assert_recommendation_release_eligible(db, mandate, channel=CHANNEL_ADVISORY_PDF)
        assert_recommendation_release_eligible(db, mandate, channel="handoff", run=run)
        assert_current_allocation_without_adr12a_hold(db, mandate, channel=CHANNEL_CLIENT_PDF)


def test_missing_cma_reference_is_not_proof_of_deactivation(session_factory):
    advisor_id, mid, _aid, alloc_id = _setup(session_factory, "adr12a-nocma", kgv="off")
    with session_factory() as db:
        db.query(TargetAllocation).filter(TargetAllocation.id == alloc_id).update(
            {"capital_market_assumptions_id": "does-not-exist"}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(HTTPException) as exc:
            assert_current_allocation_without_adr12a_hold(
                db, mandate, channel=CHANNEL_CLIENT_PDF,
            )
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    assert exc.value.detail["kgv_representation"] == REPRESENTATION_UNVERIFIABLE


def test_allocation_without_cma_reference_is_left_to_other_gates(session_factory):
    """Ohne CMA-Referenz ist die Allokation nicht finalisierbar (eigenes
    Gate); der Hold selbst greift nur bei gesetzter Referenz."""
    advisor_id, mid, _aid, alloc_id = _setup(session_factory, "adr12a-nullcma", kgv="off")
    with session_factory() as db:
        db.query(TargetAllocation).filter(TargetAllocation.id == alloc_id).update(
            {"capital_market_assumptions_id": None}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        assert_current_allocation_without_adr12a_hold(
            db, mandate, channel=CHANNEL_CLIENT_PDF,
        )


def test_signature_of_recommendation_document_blocked(session_factory):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, "adr12a-sign", kgv="explicit")
    doc_id = _add_document(session_factory, mid, advisor_id, "Anlagestrategie")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            sign_document(
                mandate_id=mid, doc_id=doc_id,
                body=ContractDocumentSign(
                    signed_by_advisor=True, signature_image=_SIGNATURE,
                    signer_name="Berater",
                ),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    with session_factory() as db:
        doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).one()
        assert doc.signed_by_advisor == 0
        assert doc.status == "Entwurf"


def test_handoff_blocked_without_persisting(session_factory, monkeypatch):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, "adr12a-ho", kgv="explicit")
    with session_factory() as db:
        db.query(Mandate).filter(Mandate.id == mid).update(
            {"mandate_type": "Vermögensverwaltung"}
        )
        db.commit()
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(
        session_factory, mid, alloc_id, aid, advisor_id, policy, cma,
        result_status="Final",
    )
    _add_full_position(session_factory, run_id)
    snapshots = []
    import routers.portfolio_handoff as ho

    monkeypatch.setattr(
        ho, "snapshot_handoff_trades",
        lambda *a, **k: snapshots.append(1) or ([{"isin": "X"}], 1),
    )
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id=mid, run_id=run_id,
                body=PortfolioHandoffCreate(recipient_name="AM"),
                request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    assert snapshots == []
    with session_factory() as db:
        assert db.query(PortfolioHandoff).filter(
            PortfolioHandoff.mandate_id == mid
        ).count() == 0


def test_finalization_blocked_with_reason_code(session_factory):
    advisor_id, mid, aid, alloc_id = _setup(session_factory, "adr12a-final", kgv="explicit")
    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(
        session_factory, mid, alloc_id, aid, advisor_id, policy, cma,
        result_status="Draft",
    )
    _add_full_position(session_factory, run_id)
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(),
                db=db, current_user=advisor,
            )
    assert exc.value.status_code == 422
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    with session_factory() as db:
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        assert run.result_status == "Draft"


@pytest.mark.parametrize(
    "route",
    ["get_anlagestrategie_pdf", "get_portfolio_pdf", "get_protokoll_pdf", "get_cost_disclosure_pdf"],
)
def test_client_pdfs_carrying_the_strategy_are_blocked(session_factory, monkeypatch, route):
    advisor_id, mid, _aid, _alloc = _setup(session_factory, f"adr12a-{route}", kgv="explicit")
    built = []
    monkeypatch.setattr(
        pdf_reports, "_build_pdf_context", lambda *a, **k: built.append(1),
    )
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        handler = getattr(pdf_reports, route)
        kwargs = {"mandate_id": mid, "db": db, "current_user": advisor}
        import inspect

        params = inspect.signature(handler).parameters
        if "request" in params:
            kwargs["request"] = _FakeRequest()
        for name in ("expected_allocation_id", "run_id"):
            if name in params:
                kwargs[name] = None
        with pytest.raises(HTTPException) as exc:
            handler(**kwargs)
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == CMA_ADR12A_HOLD
    assert exc.value.detail["channel"] == CHANNEL_CLIENT_PDF
    assert built == []


def test_risk_profile_pdf_is_not_held(session_factory, monkeypatch):
    """Das Risikoprofil-PDF haengt nicht an der CMA -- kein Hold."""
    advisor_id, mid, _aid, _alloc = _setup(session_factory, "adr12a-rp", kgv="explicit")
    calls = []
    import services.recommendation_release_gate as gate

    original = gate.assert_current_allocation_without_adr12a_hold
    monkeypatch.setattr(
        gate, "assert_current_allocation_without_adr12a_hold",
        lambda *a, **k: calls.append(1) or original(*a, **k),
    )

    class _Stop(Exception):
        pass

    def _stop(*a, **k):
        raise _Stop()

    monkeypatch.setattr(pdf_reports, "_build_pdf_context", _stop)
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(_Stop):
            pdf_reports.get_risikoprofil_pdf(
                mandate_id=mid, request=_FakeRequest(), db=db, current_user=advisor,
            )
    assert calls == []
