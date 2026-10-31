"""SIGN-ELIGIBILITY-001: nur eine finalisierte Empfehlung ist weiterleitbar.

create_portfolio_handoff() verlangt result_status == "Final"; Draft,
Superseded und Rejected werden mit 409 abgewiesen, ohne dass eine
Weiterleitung gespeichert wird.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.portfolio_handoff import PortfolioHandoff  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from test_portfolio_handoff import (  # noqa: E402,F401
    _create_handoff,
    _drift,
    _patch_engine,
    _seed_mandate_and_run,
    advisor_user,
    session_factory,
)


@pytest.mark.parametrize("status", ["Draft", "Superseded", "Rejected"])
def test_non_final_run_cannot_be_handed_off(session_factory, advisor_user, monkeypatch, status):
    _seed_mandate_and_run(session_factory, advisor_user)
    with session_factory() as session:
        session.query(RecommendationRun).filter(RecommendationRun.id == "run-1").update({"result_status": status})
        session.commit()
    _patch_engine(monkeypatch, [_drift("prod-1", 50_000)])

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            _create_handoff(session, advisor_user)
        assert exc.value.status_code == 409
        assert "nicht finalisiert" in str(exc.value.detail)
        assert session.query(PortfolioHandoff).count() == 0
