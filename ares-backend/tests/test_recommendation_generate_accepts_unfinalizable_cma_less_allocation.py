"""Round 46 red test -- TA-RECOMMENDATION-DEADEND-001.

Befund
------
Eine manuell erzeugte TargetAllocation im House-Matrix-Modus (siehe das
Schwester-Finding TA-LEGACY-FABRICATION-001: der POST
``/mandates/{id}/target-allocation``-Endpunkt, ``routers/allocation.py::
create_target_allocation``, nimmt ``TargetAllocationCreate`` entgegen -- dieses
Schema kennt gar kein ``capital_market_assumptions_id``-Feld, die Spalte bleibt
also NULL) hat **nie** eine gebundene CMA-Referenz.

Trotzdem akzeptiert Recommendation-Generate (``services/portfolio_engine.py::
generate_recommendation_run``) genau diese Allokation klaglos: die
Konsistenzprüfung dort (``elif getattr(allocation, "input_snapshot_hash", None):
raise ValueError(...)``) greift nur, wenn die Allokation einen
``input_snapshot_hash`` trägt -- bei einer manuellen House-Matrix-Allokation
ist der NIE gesetzt. Die Funktion faellt also durch, haengt den Run an die
AKTUELL gültige CMA (aus ``ensure_runtime_reference_data``) und persistiert
einen Draft-``RecommendationRun``.

Finalisierung (``routers/review.py::_validate_recommendation_for_finalization``)
vergleicht anschliessend explizit ``allocation.capital_market_assumptions_id``
gegen die CMA des Runs:

    if (
        allocation and cma
        and str(getattr(allocation, "capital_market_assumptions_id", "") or "")
        != str(cma.id)
    ):
        errors.append("Soll-Allokation und RecommendationRun referenzieren verschiedene CMA.")

Da ``allocation.capital_market_assumptions_id`` fuer diese Allokation IMMER
None ist, schlaegt dieser Vergleich IMMER an -- der Draft ist vom Moment
seiner Erzeugung an garantiert nie finalisierbar. Generate muesste diesen
Zustand VOR dem Anlegen des Drafts ablehnen (fail fast), tut es aber nicht.

Reproduktion
------------
1. Mandat mit vollstaendigem Risikoprofil + aktueller Policy + aktueller CMA
   (ueber die bestehende Foundation-Fixture) seeden.
2. Manuell eine neue aktuelle House-Matrix-TargetAllocation anlegen (echter
   ``create_target_allocation``-Endpoint-Code, kein Fake) -- diese hat
   ``capital_market_assumptions_id is None``.
3. ``generate_recommendation_run()`` mit dieser Allokation aufrufen: heute
   entsteht klaglos ein Draft, dessen ``capital_market_assumptions_id`` auf die
   AKTUELLE CMA zeigt (nicht auf die Allokation).
4. ``_validate_recommendation_for_finalization()`` auf genau diesen Draft
   anwenden: er wird (korrekt) abgelehnt -- aber eben erst hier, nicht beim
   Generate.

Status (2026-10-25): geschlossen
--------------------------------
Beide Seiten sind behoben (CERT-TA-WRITE-LIFECYCLE-001):

* ``generate_recommendation_run`` lehnt jede aktuelle Allokation ohne
  ``capital_market_assumptions_id`` mit ``ValueError`` ab, bevor ein Draft
  entsteht (unabhaengig von ``input_snapshot_hash``).
* ``create_target_allocation`` bindet beim manuellen Save die aktuelle CMA
  (gleiche Quelle wie Generate) und verlangt seit ALLOC-EDITOR-STALE-001 das
  Vorgaenger-Token.

Der urspruengliche rote Test lief deshalb nicht mehr bis zum Befund (er
scheiterte am Lost-Update-Schutz). Die Tests unten pruefen das Soll direkt:
(1) eine CMA-lose Alt-Allokation erzeugt keinen Draft, (2) ein manueller
Save bindet die CMA, und der daraus erzeugte Draft scheitert bei der
Finalisierung nicht am CMA-Abgleich.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe  # noqa: E402
import routers.allocation as allocation_router  # noqa: E402
from models.allocation import CapitalMarketAssumption, OptimizerPolicy  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402
from schemas.allocation import TargetAllocationCreate  # noqa: E402

from test_asset_allocation_reference_integrity_edges import (  # noqa: E402
    _stub_recommendation_tail,
)
from test_optimizer_production_contract import (  # noqa: E402
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)
from test_portfolio_generate_after_saa_recalc import _seed_foundation  # noqa: E402


def _request_stub():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _manual_house_matrix_payload(policy_id: str) -> TargetAllocationCreate:
    """Mirrors a real advisor-driven manual House-Matrix save: no CMA field
    exists on this schema at all (TA-LEGACY-FABRICATION-001)."""
    return TargetAllocationCreate(
        target_equities_bps=6000,
        target_bonds_bps=3000,
        target_real_estate_bps=0,
        target_alternatives_bps=0,
        target_liquidity_bps=1000,
        band_equities_min_bps=5000,
        band_equities_max_bps=7000,
        band_bonds_min_bps=2000,
        band_bonds_max_bps=4000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=1000,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=1000,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=2000,
        policy_id=policy_id,
        override_reason="Kunde wuenscht nach Beratungsgespraech eine angepasste Gewichtung der Anlageklassen.",
    )


def _seed_cma_less_current_allocation(session):
    """Legacy row: the current allocation carries no CMA anchor (pre-context
    data or a manual save from before the write-lifecycle fix)."""
    from models.allocation import TargetAllocation

    mandate = _seed_foundation(session)
    allocation = session.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
    ).one()
    allocation.capital_market_assumptions_id = None
    session.commit()
    return mandate, allocation


@pytest.mark.parametrize("explicit_id", [True, False])
def test_generate_rejects_cma_less_allocation_before_creating_a_draft(
    session_factory,
    monkeypatch,
    explicit_id,
):
    """Generate must fail fast instead of creating a permanently
    unfinalizable Draft for a CMA-less allocation (explicit id or implicit
    current allocation)."""
    from models.review import RecommendationRun

    with session_factory() as session:
        mandate, allocation = _seed_cma_less_current_allocation(session)
        advisor = session.query(User).filter(User.id == "advisor-1").one()
        runs_before = session.query(RecommendationRun).filter(
            RecommendationRun.mandate_id == mandate.id
        ).count()

        _stub_recommendation_tail(monkeypatch)
        with pytest.raises(ValueError, match="Kapitalmarktannahmen"):
            pe.generate_recommendation_run(
                db=session,
                mandate=mandate,
                user_id=advisor.id,
                preferences=None,
                target_allocation_id=allocation.id if explicit_id else None,
                run_type="Optimizer",
                depot_bank=None,
            )
        session.rollback()
        runs_after = session.query(RecommendationRun).filter(
            RecommendationRun.mandate_id == mandate.id
        ).count()
        assert runs_after == runs_before, (
            "Generate persisted a Draft for a CMA-less allocation."
        )


def test_manual_house_matrix_save_binds_cma_and_draft_passes_cma_check(
    session_factory,
    monkeypatch,
):
    """A manual House-Matrix save binds the current CMA, so the Draft built
    on it is not rejected by Finalize on CMA grounds."""
    from models.allocation import TargetAllocation

    with session_factory() as session:
        mandate = _seed_foundation(session)
        advisor = session.query(User).filter(User.id == "advisor-1").one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.is_current == 1
        ).one()
        current_cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1
        ).one()
        prev = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
        ).one()

        payload = _manual_house_matrix_payload(policy.id)
        payload.expected_current_allocation_id = prev.id
        payload.expected_current_allocation_version = int(prev.version or 0)
        monkeypatch.setattr(allocation_router.settings, "optimizer_mode", "house_matrix")
        manual_ta = allocation_router.create_target_allocation(
            mandate.id,
            payload,
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        assert manual_ta.is_current == 1
        assert manual_ta.capital_market_assumptions_id == current_cma.id

        _stub_recommendation_tail(monkeypatch)
        result = pe.generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor.id,
            preferences=None,
            target_allocation_id=manual_ta.id,
            run_type="Optimizer",
            depot_bank=None,
        )
        session.commit()
        run = result["run"]
        assert run.result_status == "Draft"
        assert run.capital_market_assumptions_id == manual_ta.capital_market_assumptions_id

        errors, _warnings = _validate_recommendation_for_finalization(
            session, mandate, run
        )
        assert not any("CMA" in error for error in errors), errors
