"""SAA-RESAMPLED-STABILITY-001 (2026-10-14): stabile SAA durch Inhalts-Seed,
Resampled Efficiency und Signifikanztest gegen die Hausmatrix.

Befund vorher (Fundament-Beispielmandat, nur der Monte-Carlo-Seed variiert):
Aktien 63.2-75.0 %, Immobilien 5.0-20.0 %, 10 Seeds -> 7 verschiedene SAAs;
der Seed hing an Datenbank-IDs, ein identisch neu erfasstes Ziel aenderte die
Strategie. Diese Tests pinnen die Eigenschaften, nicht exakte Quoten.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users,
    wealth,
)

configure_mappers()

import services.optimizer.solver as solver_module  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import Goal  # noqa: E402
from services.foundation_example import (  # noqa: E402
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)
from services.optimizer.resampling import (  # noqa: E402
    DEFAULT_RESAMPLING,
    paired_bootstrap_improvement,
)
from services.optimizer.scenario_engine import BUCKET_ORDER  # noqa: E402
from services.optimizer.solver import (  # noqa: E402
    build_optimizer_context,
    evaluate_weights,
    goal_economic_fingerprint,
    run_solver,
)
from services.portfolio_engine import generate_target_allocation  # noqa: E402


@pytest.fixture(scope="module")
def foundation(tmp_path_factory):
    """Fundament-Mandat einmal aufsetzen und die exakten Solver-kwargs mitschneiden."""
    db_path = tmp_path_factory.mktemp("saa_stab") / "saa_stab.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    session = session_factory()
    session.add(User(
        id="advisor-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at="2026-03-27T00:00:00.000Z",
        updated_at="2026-03-27T00:00:00.000Z",
    ))
    session.commit()
    upsert_foundation_example_case(session, session.get(User, "advisor-1"))
    session.commit()
    mandate = (
        session.query(Mandate)
        .filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER)
        .one()
    )

    captured: dict = {}
    original = solver_module.run_solver

    def _capture(**kwargs):
        result = original(**kwargs)
        captured.setdefault("kwargs", dict(kwargs))
        captured.setdefault("result", result)
        return result

    solver_module.run_solver = _capture
    try:
        generated = generate_target_allocation(
            db=session, mandate=mandate, user_id="advisor-1", preferences=None,
        )
        session.commit()
    finally:
        solver_module.run_solver = original
    kwargs = dict(captured["kwargs"])
    kwargs.pop("optimizer_context", None)
    try:
        yield {
            "session": session,
            "mandate": mandate,
            "kwargs": kwargs,
            "result": captured["result"],
            "allocation": generated["target_allocation"],
        }
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _weights(result) -> np.ndarray:
    return np.array([result.weights_bps[b] for b in BUCKET_ORDER], dtype=float)


def _context_kwargs(kwargs: dict) -> dict:
    return {k: v for k, v in kwargs.items() if k != "house_anchor_bps"}


def test_production_run_is_resampled_and_exposes_stability_audit(foundation):
    result = foundation["result"]
    resampling = result.resampling
    assert resampling["enabled"] is True
    assert resampling["n_bags"] == DEFAULT_RESAMPLING.n_bags
    assert resampling["n_bags_succeeded"] >= DEFAULT_RESAMPLING.n_bags // 2
    assert set(resampling["dispersion_bps"]) == set(BUCKET_ORDER)
    assert resampling["content_seed"] == result.seed
    # Entscheid und Test sind vollstaendig dokumentiert.
    significance = resampling["significance"]
    assert significance["decision"] in {"optimizer", "house_matrix"}
    assert significance["test"] == "paired_bootstrap_one_sided_v1"
    assert significance["p_value"] is not None
    assert resampling["final_weights_bps"] == result.weights_bps
    # Die publizierte Allokation erfuellt alle harten Constraints.
    evaluation = evaluate_weights(result.context, dict(result.weights_bps))
    assert evaluation.feasible, evaluation.constraint_violations
    assert any("Resampled Efficiency" in line for line in result.reasoning)

    # Persistiert: Modellbasis in effective_constraints_json, ohne Laufzeiten.
    import json

    stored = json.loads(foundation["allocation"].effective_constraints_json)
    basis = stored["optimization_model_basis"]["resampling"]
    assert basis["dispersion_bps"] == resampling["dispersion_bps"]
    assert basis["significance"]["decision"] == significance["decision"]
    assert "elapsed_ms" not in basis and "bags" not in basis


def test_identical_content_is_bitwise_reproducible(foundation):
    kwargs = foundation["kwargs"]
    first = run_solver(**kwargs)
    second = run_solver(**kwargs)
    assert first.seed == second.seed == foundation["result"].seed
    assert first.weights_bps == second.weights_bps == foundation["result"].weights_bps
    strip = lambda payload: {  # noqa: E731
        k: v for k, v in payload.items() if k not in {"elapsed_ms", "bags"}
    }
    assert strip(first.resampling) == strip(second.resampling)


def test_seed_variation_moves_each_bucket_by_less_than_one_point(foundation):
    """Vorher: Sigma 5.4 pp (Aktien) / 6.6 pp (Immobilien) ueber Seeds."""
    kwargs = _context_kwargs(foundation["kwargs"])
    rows = []
    for salt in range(4):
        context = build_optimizer_context(**{**kwargs, "seed": 7_000_000 + salt})
        rows.append(_weights(run_solver(
            **foundation["kwargs"], optimizer_context=context,
        )))
    spread_pp = (np.max(rows, axis=0) - np.min(rows, axis=0)) / 100.0
    # Range ueber 4 Seeds ~ 2 Sigma; Sigma < 1 pp -> Range klar < 2.5 pp.
    assert float(np.max(spread_pp)) < 2.5, spread_pp


def test_seed_does_not_depend_on_database_ids(foundation):
    """Ein geloeschtes und identisch neu erfasstes Ziel aendert die SAA nicht."""
    session = foundation["session"]
    mandate = foundation["mandate"]
    goals = (
        session.query(Goal)
        .filter(Goal.mandate_id == mandate.id, Goal.deleted_at.is_(None))
        .all()
    )
    assert goals
    before_fp = goal_economic_fingerprint(goals)
    victim = goals[0]
    clone = Goal(**{
        column.name: getattr(victim, column.name)
        for column in Goal.__table__.columns
    })
    clone.id = str(uuid.uuid4())
    clone.created_at = "2026-10-14T12:00:00.000Z"
    clone.updated_at = "2026-10-14T12:00:00.000Z"
    session.delete(victim)
    session.flush()
    session.add(clone)
    session.commit()
    after_goals = (
        session.query(Goal)
        .filter(Goal.mandate_id == mandate.id, Goal.deleted_at.is_(None))
        .all()
    )
    assert goal_economic_fingerprint(after_goals) == before_fp

    regenerated = generate_target_allocation(
        db=session, mandate=mandate, user_id="advisor-1", preferences=None,
    )
    session.commit()
    allocation = regenerated["target_allocation"]
    original = foundation["allocation"]
    assert int(allocation.optimization_seed) == int(original.optimization_seed)
    for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        assert getattr(allocation, f"target_{bucket}_bps") == getattr(
            original, f"target_{bucket}_bps"
        ), bucket


def test_insignificant_deviation_keeps_house_target(foundation, monkeypatch):
    """Ist die Verbesserung nicht signifikant, gilt die (projizierte) Hausmatrix.

    Die Statistik selbst testet `test_paired_bootstrap_detects_only_real_
    improvements`; hier geht es um die Verdrahtung des Entscheids. Ein
    "kleiner" Abstand zum Optimum reicht dafuer NICHT: gepaart auf denselben
    Pfaden ist auch eine 10-bps-Verschiebung oft signifikant (gemessen) --
    Signifikanz ist keine Materialitaet.
    """
    real_test = solver_module.paired_bootstrap_improvement

    def _not_significant(loss_pair, **kwargs):
        stats = real_test(loss_pair, **kwargs)
        return {**stats, "improvement_lower_bound": -1.0, "p_value": 0.31,
                "significant": False}

    monkeypatch.setattr(solver_module, "paired_bootstrap_improvement", _not_significant)
    anchor = {"equities": 6000, "bonds": 2000, "real_estate": 1000,
              "alternatives": 600, "liquidity": 400}
    result = run_solver(**{**foundation["kwargs"], "house_anchor_bps": anchor})
    significance = result.resampling["significance"]
    assert significance["significant"] is False
    assert result.resampling["decision"] == "house_matrix"
    projected = significance["house_anchor_projected_bps"]
    # Der Anker wird auf die harten Constraints projiziert (hier: die
    # Reserve-Untergrenze fixiert die Liquiditaet), nicht roh uebernommen.
    assert projected["liquidity"] == foundation["result"].weights_bps["liquidity"]
    assert result.weights_bps == projected
    assert evaluate_weights(result.context, dict(result.weights_bps)).feasible
    assert result.status == "converged"
    assert any(
        "Optimierer-Abweichung von der Hausmatrix ist statistisch nicht "
        "signifikant; Hausmatrix-Zielquote beibehalten" in line
        and "p = 0.3100" in line
        for line in result.reasoning
    )


def test_sensitivity_tests_against_the_same_house_anchor_as_generate(foundation):
    """Generate und Goal-Sensitivity muessen gegen DENSELBEN Anker testen.

    Sonst koennte der Sensitivity-Baseline-Lauf "Hausmatrix vs. Optimierer"
    anders entscheiden als die aktive Strategie, und das ausgewiesene Delta
    enthielte einen Entscheid-Sprung statt nur den Goal-Effekt.
    """
    import json

    import services.portfolio_engine as pe
    from services.portfolio_engine_optimizer_integration import (
        sensitivity_house_anchor_bps,
    )

    session = foundation["session"]
    mandate = foundation["mandate"]
    allocation = pe._current_target_allocation_or_none(session, mandate.id)
    stored = json.loads(allocation.effective_constraints_json)
    persisted_anchor = stored["optimization_model_basis"]["resampling"][
        "significance"
    ]["house_anchor_bps"]
    assert sensitivity_house_anchor_bps(allocation, None) == persisted_anchor
    # Ohne aktive Allokation: die live (wie Generate) aufgebaute Zielquote.
    live = {"equities": 6000, "bonds": 2000, "real_estate": 1000,
            "alternatives": 600, "liquidity": 400}
    assert sensitivity_house_anchor_bps(None, live) == live
    # Alt-Allokation ohne persistierten Anker: kein erfundener Anker.
    legacy = type("Legacy", (), {"effective_constraints_json": "{}"})()
    assert sensitivity_house_anchor_bps(legacy, None) is None

    goal = (
        session.query(Goal)
        .filter(Goal.mandate_id == mandate.id, Goal.deleted_at.is_(None))
        .first()
    )
    seen: list[dict] = []
    original = solver_module.run_solver

    def _capture(**kwargs):
        seen.append(kwargs.get("house_anchor_bps"))
        return original(**kwargs)

    solver_module.run_solver = _capture
    try:
        pe.evaluate_goal_sensitivity(
            session, mandate, "advisor-1", goal.id, target_delta_pct=0,
        )
    finally:
        solver_module.run_solver = original
        session.rollback()
    assert seen and all(anchor == persisted_anchor for anchor in seen), seen


def test_paired_bootstrap_detects_only_real_improvements():
    rng = np.random.default_rng(1)
    noise = rng.normal(size=4000)

    def loss_pair(shift):
        def _pair(idx):
            sample = noise if idx is None else noise[idx]
            anchor = float(np.mean(sample ** 2))
            candidate = float(np.mean((sample - shift) ** 2)) - 0.0
            return anchor, candidate
        return _pair

    # Kandidat schlechter (Verschiebung erhoeht den Verlust): nie signifikant.
    worse = paired_bootstrap_improvement(
        loss_pair(0.5), n_paths=4000, n_bootstrap=200, alpha=0.05, seed=3,
    )
    assert worse["significant"] is False and worse["improvement"] < 0
    # Gleiche Allokation: Verbesserung exakt 0 -> nicht signifikant.
    same = paired_bootstrap_improvement(
        loss_pair(0.0), n_paths=4000, n_bootstrap=200, alpha=0.05, seed=3,
    )
    assert same["significant"] is False

    def better(idx):
        sample = noise if idx is None else noise[idx]
        return float(np.mean((sample + 1.0) ** 2)), float(np.mean(sample ** 2))

    clear = paired_bootstrap_improvement(
        better, n_paths=4000, n_bootstrap=200, alpha=0.05, seed=3,
    )
    assert clear["significant"] is True
    assert clear["p_value"] < 0.05 and clear["improvement_lower_bound"] > 0
