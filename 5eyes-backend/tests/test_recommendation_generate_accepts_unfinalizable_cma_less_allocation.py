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

Test
----
Dokumentiert Schritt 3+4 als IST-Zustand und markiert mit einer expliziten
``pytest.fail``, dass Generate dies eigentlich schon in Schritt 3 hätte
verhindern muessen. xfail(strict=True), bis der Fail-Fast-Gate ergaenzt ist.

Minimalfix (nicht Teil dieses rein-roten Tests)
------------------------------------------------
``generate_recommendation_run`` sollte, wenn eine explizit/implizit aktuelle
Allokation KEINE ``capital_market_assumptions_id`` traegt (unabhaengig vom
``input_snapshot_hash``-Zweig), mit einer klaren ``ValueError`` ablehnen statt
den Run gegen die Laufzeit-CMA zu generieren.
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
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TA-RECOMMENDATION-DEADEND-001 -- round 46 red test, see audit "
        "2026-10-04-target-allocation-editor-context-and-release-lifecycle-"
        "integrity-audit.md (not committed in this repo)"
    ),
)
def test_generate_accepts_cma_less_house_matrix_allocation_that_finalize_always_rejects(
    session_factory,
    monkeypatch,
):
    """Generate must fail fast instead of creating a permanently
    unfinalizable Draft for a CMA-less manual House-Matrix allocation."""
    with session_factory() as session:
        mandate = _seed_foundation(session)
        advisor = session.query(User).filter(User.id == "advisor-1").one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.is_current == 1
        ).one()
        current_cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1
        ).one()

        # Step 2: manually create a NEW current House-Matrix TargetAllocation
        # through the real endpoint code -- this is the artefact from the
        # sibling finding TA-LEGACY-FABRICATION-001. TargetAllocationCreate
        # has no capital_market_assumptions_id field, so the column stays
        # NULL no matter what the advisor submits.
        monkeypatch.setattr(allocation_router.settings, "optimizer_mode", "house_matrix")
        manual_ta = allocation_router.create_target_allocation(
            mandate.id,
            _manual_house_matrix_payload(policy.id),
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        assert manual_ta.is_current == 1
        assert manual_ta.capital_market_assumptions_id is None, (
            "Fixture assumption broken: a manually-created House-Matrix "
            "allocation must never bind a CMA on its own."
        )

        # Step 3: today's actual behaviour -- Recommendation-Generate accepts
        # this CMA-less allocation and persists a Draft against the CURRENT
        # runtime CMA, even though the allocation itself never referenced one.
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
        assert run.capital_market_assumptions_id == current_cma.id, (
            "Generate bound the Draft to the CURRENT CMA instead of "
            "refusing the CMA-less allocation."
        )

        # Step 4: confirm the dead end -- Finalize ALWAYS rejects this exact
        # Draft, because the allocation it is built on never bound a CMA.
        errors, _warnings = _validate_recommendation_for_finalization(
            session, mandate, run
        )
        assert any("CMA" in error for error in errors), (
            f"Expected Finalize to reject this Draft on CMA grounds, got: {errors}"
        )

        # Desired behaviour (red): Generate must never create a Draft that is
        # guaranteed, from the moment of its creation, to fail Finalize for
        # the exact same reason. Today it does -- this failure is the bug.
        pytest.fail(
            "TA-RECOMMENDATION-DEADEND-001: generate_recommendation_run() "
            f"accepted CMA-less allocation {manual_ta.id} and persisted "
            f"Draft run {run.id} against CURRENT CMA {run.capital_market_assumptions_id}. "
            f"_validate_recommendation_for_finalization() then always rejects it "
            f"with: {errors}. Generate must reject up front (fail fast) instead "
            "of ever creating this permanently unfinalizable Draft."
        )
