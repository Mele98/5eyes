"""RISK-FALLBACK-WARNING-001 (Audit 2026-10-04, round 46, P2).

Befund: wenn der Risikobudget-Fallback auf die House-Matrix-Bandbreiten-Mitte
strukturell nicht ausreicht (Stufe-3-Eskalation in generate_target_allocation,
services/portfolio_engine.py), wird dieselbe WARN_FALLBACK-Warnung ZWEIMAL an
`warnings` angehaengt:

1. Innerhalb der Stufe-3-Eskalation (nachdem `_enforce_risk_budget(...,
   allow_best_effort=True)` die konservativste erreichbare Allokation
   zurueckgibt) -- services/portfolio_engine.py Zeile ~3885.
2. Unconditional am Ende des gesamten `except RiskBudgetExceeded:`-Blocks,
   sobald `risk_budget_fallback` True ist -- services/portfolio_engine.py
   Zeile ~3928.

Fuer das "strukturell unerreichbar"-Szenario (konservatives Kapitalschutz-
Mandat im `house_matrix`-Legacy-Modus, dessen Bonds-Floor die Risky-Fraction
auch nach Liquiditaets-Notfall-Cap nicht unter das Risikobudget drueckt)
feuern BEIDE Code-Zweige, und dieselbe (inhaltlich identische) Warnung landet
doppelt in `result["warnings"]`.

Reproduktion unten: _seed_realistic_mandate() + Kapitalschutz-Risikoprofil
(Score 10, wie in test_kapitalschutz_risk_budget_regression.py), mit
optimizer_mode auf das `house_matrix`-Legacy-/Notbetrieb-Modell gezwungen
(per Monkeypatch auf `services.portfolio_engine.settings.optimizer_mode`),
weil im Produktions-Default `stochastic` ein ValueError an dieser Stelle
sofort als `OptimizerInputError` propagiert wird (kein Fallback-Pfad, siehe
services/portfolio_engine.py Zeile ~3844) -- die Doppel-Warnung ist also nur
im `house_matrix`-Pfad sichtbar, existiert dort aber real.

Gewuenschtes Verhalten: die WARN_FALLBACK-Warnung erscheint GENAU EINMAL in
`result["warnings"]`, unabhaengig davon wie viele interne Eskalationsstufen
durchlaufen wurden.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: F401
import models.client_login  # noqa: F401
import models.protocol_bausteine  # noqa: F401
configure_mappers()

from models.mandates import Mandate
from models.profiling import RiskAssessment
from services import portfolio_engine
from services.portfolio_engine import generate_target_allocation
from test_optimizer_integration import _seed_realistic_mandate
from tests.risk_fixture_helpers import derive_current_risk_fields


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_fallback_warning_dup.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RISK-FALLBACK-WARNING-001 — round 46 red test, see audit "
        "2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_fallback_warning_appears_exactly_once_when_structurally_unreachable(
    session_factory, monkeypatch
):
    """Stufe-3-Eskalation (strukturell unerreichbares Risikobudget im
    `house_matrix`-Legacy-Pfad) darf WARN_FALLBACK nur EINMAL anhaengen.

    Heute (rot): die Warnung erscheint zweimal (Stufe-3-Branch + der
    unconditional Append am Ende des `except RiskBudgetExceeded:`-Blocks).
    """
    # Default-Produktionsmodus ist 'stochastic'; dort wirft ein ValueError an
    # dieser Stelle sofort OptimizerInputError (kein Fallback-Pfad). Die
    # Stufe-2/3-Eskalation mit der Doppel-Warnung existiert nur im
    # 'house_matrix'-Legacy-/Notbetrieb-Modus -- den erzwingen wir hier gezielt.
    monkeypatch.setattr(portfolio_engine.settings, "optimizer_mode", "house_matrix")

    advisor_id, cid, mid, aid = _seed_realistic_mandate(
        session_factory, suffix="rfw001"
    )
    risk_fields = derive_current_risk_fields(
        q_income_points=0,
        q_obligations_points=0,
        q_savings_points=0,
        q_wealth_points=0,
        investment_horizon_label="2 bis 3 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    assert risk_fields["final_score_x10"] == 10
    assert risk_fields["final_profile"] == "Kapitalschutz"

    with session_factory() as s:
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).first()
        for field, value in risk_fields.items():
            setattr(ra, field, value)
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    warnings = result.get("warnings") or []
    fallback_warnings = [w for w in warnings if w.get("code") == "WARN_FALLBACK"]

    # Sanity: das Szenario muss den Fallback ueberhaupt ausloesen, sonst
    # testen wir nichts.
    assert fallback_warnings, (
        "Testszenario loest den Risikobudget-Fallback nicht aus -- "
        f"warnings={warnings}"
    )

    assert len(fallback_warnings) == 1, (
        "WARN_FALLBACK darf nur EINMAL in den warnings erscheinen, nicht "
        f"{len(fallback_warnings)}x: {fallback_warnings}"
    )
