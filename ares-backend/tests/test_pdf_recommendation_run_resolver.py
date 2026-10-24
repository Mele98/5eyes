"""Regression PDF-RUN-RESOLVER-001.

Kundendokumente (Anlagestrategie-PDF, Beratungsentscheid/Contract-Signoff,
Depot-Check-PDF, Advisory-Report) muessen den RecommendationRun mit DERSELBEN
Regel aufloesen wie das Portfolio-PDF (``_build_portfolio_data``):
Final, sonst Draft, jeweils gebunden an die AKTUELLE TargetAllocation;
Superseded nie. Vorher nahmen sie den juengsten Run per ``created_at`` --
nach einer Neugenerierung der Soll-Allokation (z.B. defensiv: Aktien 0 %)
standen so die NEUEN Bucket-Ziele neben den Produkten des ALTEN Runs
(Aktien ~70 %), waehrend das Portfolio-PDF genau diesen Run als
"passt nicht" (409) ablehnte.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import routers.pdf_reports as pdf  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from services import advisory_report as ar  # noqa: E402
from services.portfolio_engine import generate_target_allocation  # noqa: E402
from test_portfolio_generate_after_saa_recalc import (  # noqa: E402
    _seed_foundation,
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)


def _current_ta(s, mandate_id):
    return s.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).one()


def _regenerate_defensive(s, mandate):
    """Dokumentierter defensiver Override + Neugenerierung -> neue aktuelle TA,
    der bestehende Run bleibt an die alte TA gebunden."""
    ra = (
        s.query(RiskAssessment)
        .filter(RiskAssessment.mandate_id == mandate.id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    ra.is_overridden = 1
    ra.override_score_x10 = 30
    ra.override_profile = "Defensiv"
    ra.override_reason = "Kunde wuenscht nach Gespraech defensivere Ausrichtung"
    s.commit()
    generate_target_allocation(db=s, mandate=mandate, user_id="advisor-1", preferences=None)
    s.commit()
    ta2 = _current_ta(s, mandate.id)
    runs = s.query(RecommendationRun).filter(RecommendationRun.mandate_id == mandate.id).all()
    assert runs, "Fixture muss einen (jetzt veralteten) Run hinterlassen"
    assert all(str(r.target_allocation_id) != str(ta2.id) for r in runs), (
        "Fixture-Invariante verletzt: ein Run passt bereits zur neuen TA"
    )
    return ta2


def test_strategy_and_signoff_pdf_do_not_use_run_of_superseded_allocation(session_factory):
    with session_factory() as s:
        mandate = _seed_foundation(s)
        # Vorher: Run passt zur aktuellen TA -> Produkte vorhanden.
        assert pdf._build_anlagestrategie_data(mandate, s).products

        _regenerate_defensive(s, mandate)

        with pytest.raises(HTTPException) as exc:
            pdf._build_portfolio_data(mandate, s)
        assert exc.value.status_code == 409

        strategy = pdf._build_anlagestrategie_data(mandate, s)
        assert strategy.products == [], (
            "Anlagestrategie-PDF zeigt Produkte eines Runs der ueberholten Allokation"
        )
        assert strategy.recommendation_status == "keine aktuelle Produktempfehlung"

        # COST-RUN-RESOLVER-001: Beratungsentscheid ohne aktuellen Run wird
        # blockiert (ValueError -> 409), statt eine leere bzw. veraltete
        # Sub-Allokation zur Unterschrift vorzulegen.
        with pytest.raises(ValueError, match="keine aktuelle Produktempfehlung"):
            pdf._build_contract_signoff_data(mandate, s)


def test_depotcheck_and_advisory_report_do_not_fall_back_to_stale_run(session_factory):
    with session_factory() as s:
        mandate = _seed_foundation(s)
        _regenerate_defensive(s, mandate)

        assert ar._cached_latest_recommendation_run(s, mandate) is None, (
            "Advisory-Report (Berater-/PDF-Pfad) nutzt Run einer ueberholten Allokation"
        )
        positionen = ar._build_positionen(s, mandate)
        assert positionen["has_recommendation_run"] is False
        assert positionen["total_rappen"] == 0

        with pytest.raises(HTTPException) as exc:
            pdf._build_depotcheck_data(mandate, s)
        assert exc.value.status_code == 409


def test_resolver_prefers_final_then_draft_and_never_superseded(session_factory):
    from services.recommendation_run_resolver import resolve_current_recommendation_run

    with session_factory() as s:
        mandate = _seed_foundation(s)
        ta = _current_ta(s, mandate.id)
        run = (
            s.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        original_status = run.result_status
        assert resolve_current_recommendation_run(s, mandate.id, ta.id).id == run.id

        run.result_status = "Superseded"
        s.commit()
        assert resolve_current_recommendation_run(s, mandate.id, ta.id) is None
        run.result_status = original_status
        s.commit()
