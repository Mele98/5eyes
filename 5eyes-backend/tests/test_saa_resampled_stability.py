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
    assert significance["test"] == "paired_bootstrap_one_sided_lexicographic_v2"
    assert significance["comparison"] in {"goal_level", "volatility_tiebreak"}
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


# ---------------------------------------------------------------------------
# SAA-SIGNIFICANCE-LEXICOGRAPHIC-001 / SAA-SEED-FLOAT-ROBUST-001 (2026-10-17)
#
# Befund: die CH-Golden-Snapshots (eingefroren am 16.10.) fielen am 17.10. in
# CI durch. Wurzel 1: das Golden-Seeding setzte Zieldaten "heute + N Tage",
# der Inhalts-Seed hasht die Zieldaten -> jeder Tag ein anderer Wuerfel.
# Wurzel 2 (Methodik): beim Score-7-Fall kippte der Entscheid je nach Wuerfel
# zwischen Hausmatrix (68 % Aktien) und Optimierer (60 %), obwohl ALLE 40 Bags
# denselben Kandidaten lieferten. Ursache: die Skalar-Zielfunktion schaltet
# den Volatilitaetsterm pro Allokation erst zu, wenn deren Ziel-Stufe < 1e-12
# ist. Ein einziger Validierungspfad mit winzigem Fehlbetrag (8.1e-9) bei der
# Hausmatrix ersparte ihr den ganzen Volatilitaetsterm (2.2e4) -> sie "gewann"
# mit -14204 gegen einen Kandidaten, der auf beiden Stufen besser war.
# Gemessen ueber 8 Inhalts-Seeds: 6x Hausmatrix, 2x Optimierer.
# ---------------------------------------------------------------------------
from dataclasses import replace as _replace  # noqa: E402

from services.optimizer.resampling import lexicographic_improvement  # noqa: E402
from services.optimizer.scenario_cache import scenario_inputs_seed_digest  # noqa: E402
from services.optimizer.scenario_engine import ScenarioInputs  # noqa: E402
from services.optimizer.solver import optimizer_content_seed  # noqa: E402

_GOLDEN_ANCHOR_GOAL_LEVEL = 8.110173291668927e-09
_GOLDEN_ANCHOR_TIEBREAK = 2.187e4
_GOLDEN_CANDIDATE_TIEBREAK = 1.420e4


def _one_path_shortfall_pair(*, candidate_tiebreak: float, bad_path: int = 0):
    """Nachbau des gemessenen Golden-Falls (Score 7, Validierungs-Cube 16.10.).

    Anker (Hausmatrix): Fehlbetrag NUR auf Pfad ``bad_path`` (Stufe 1 =
    8.1e-9, solange der Pfad in der Stichprobe liegt), Volatilitaetsterm
    2.187e4. Kandidat: erfuellt alle Ziele, Volatilitaetsterm wie angegeben.
    """
    def loss_pair(idx):
        has_bad = True if idx is None else bool(np.any(idx == bad_path))
        anchor = (_GOLDEN_ANCHOR_GOAL_LEVEL if has_bad else 0.0, _GOLDEN_ANCHOR_TIEBREAK)
        candidate = (0.0, float(candidate_tiebreak))
        return anchor, candidate
    return loss_pair


def test_scalar_difference_reproduces_the_phase_switch_defect():
    """Pin des Defekts: die Skalar-Differenz bevorzugt die SCHLECHTERE Allokation."""
    anchor, candidate = _one_path_shortfall_pair(
        candidate_tiebreak=_GOLDEN_CANDIDATE_TIEBREAK
    )(None)
    anchor_scalar = anchor[0]  # Stufe 1 > 1e-12 -> kein Volatilitaetsterm
    candidate_scalar = candidate[0] + candidate[1]  # Stufe 2 -> mit Term
    old_improvement, _ = lexicographic_improvement(anchor_scalar, candidate_scalar)
    assert old_improvement < -1.0e4  # alte Regel: Hausmatrix "deutlich besser"

    improvement, level = lexicographic_improvement(anchor, candidate)
    assert level == "goal_level" and improvement > 0.0


@pytest.mark.parametrize("bad_path", [0, 7, 1999])
def test_candidate_better_on_both_levels_is_significant_on_every_cube(bad_path):
    """Kandidat besser auf Stufe 1 UND im Tiebreak -> signifikant, egal ob
    der eine schlechte Pfad im Bootstrap-Sample liegt oder nicht."""
    stats = paired_bootstrap_improvement(
        _one_path_shortfall_pair(
            candidate_tiebreak=_GOLDEN_CANDIDATE_TIEBREAK, bad_path=bad_path,
        ),
        n_paths=2000, n_bootstrap=400, alpha=0.05, seed=11,
    )
    assert stats["significant"] is True, stats
    assert stats["comparison"] == "goal_level"
    # Beide Ebenen kommen in den Replikationen vor (Pfad drin/nicht drin),
    # der Entscheid haengt trotzdem nicht davon ab.
    assert set(stats["replicate_comparisons"]) == {"goal_level", "volatility_tiebreak"}
    # Ueber gemischte Ebenen gibt es kein sinnvolles Quantil.
    assert stats["improvement_lower_bound"] is None


def test_cube_without_the_bad_path_decides_the_same_way():
    """Liegt der Pfad gar nicht im Validierungs-Cube, vergleicht schon die
    Punktschaetzung im Tiebreak -- und kommt zum selben Entscheid."""
    def loss_pair(idx):
        return (0.0, _GOLDEN_ANCHOR_TIEBREAK), (0.0, _GOLDEN_CANDIDATE_TIEBREAK)

    stats = paired_bootstrap_improvement(
        loss_pair, n_paths=2000, n_bootstrap=400, alpha=0.05, seed=11,
    )
    assert stats["comparison"] == "volatility_tiebreak"
    assert stats["significant"] is True


def test_one_path_advantage_against_higher_volatility_is_not_significant():
    """Gegenprobe: erkauft der Kandidat den einen Pfad mit HOEHERER
    Volatilitaet, ist das kein robuster Vorteil -> nicht signifikant."""
    stats = paired_bootstrap_improvement(
        _one_path_shortfall_pair(candidate_tiebreak=3.0e4),
        n_paths=2000, n_bootstrap=400, alpha=0.05, seed=11,
    )
    assert stats["improvement"] > 0.0  # Punktschaetzung: Stufe 1 entscheidet
    assert stats["significant"] is False, stats  # ~37 % der Replikationen dagegen


def test_soft_preference_counts_on_both_levels_but_does_not_switch_level():
    # Beide erfuellen die Ziele; die Praeferenz-Strafe zaehlt im Tiebreak mit.
    improvement, level = lexicographic_improvement((0.0, 100.0, 50.0), (0.0, 120.0, 0.0))
    assert level == "volatility_tiebreak" and improvement == pytest.approx(30.0)
    # Praeferenz-Strafe > epsilon schaltet NICHT auf Stufe 1 um.
    _, level = lexicographic_improvement((0.0, 1.0, 5.0), (0.0, 1.0, 0.0))
    assert level == "volatility_tiebreak"
    improvement, level = lexicographic_improvement((1e-6, 1.0, 0.0), (0.0, 9.0, 2e-6))
    assert level == "goal_level" and improvement == pytest.approx(-1e-6)


@pytest.mark.parametrize("relative", [1e-12, -1e-12])
def test_lexicographic_decision_is_stable_under_float_noise(relative):
    """1e-12-Stoerungen aller Terme kippen weder Ebene noch Vorzeichen."""
    rng = np.random.default_rng(5)
    for _ in range(200):
        anchor = (float(rng.choice([0.0, rng.uniform(1e-9, 1e-3)])),
                  float(rng.uniform(1e3, 3e4)), 0.0)
        candidate = (float(rng.choice([0.0, rng.uniform(1e-9, 1e-3)])),
                     float(rng.uniform(1e3, 3e4)), 0.0)
        base, base_level = lexicographic_improvement(anchor, candidate)
        noisy = tuple(v * (1.0 + relative) for v in anchor)
        moved, moved_level = lexicographic_improvement(noisy, candidate)
        assert moved_level == base_level
        assert np.sign(moved) == np.sign(base)


def _realistic_inputs() -> ScenarioInputs:
    correlation = np.array([
        [1.00, 0.10, 0.45, 0.35, 0.00],
        [0.10, 1.00, 0.25, 0.05, 0.10],
        [0.45, 0.25, 1.00, 0.30, 0.00],
        [0.35, 0.05, 0.30, 1.00, 0.00],
        [0.00, 0.10, 0.00, 0.00, 1.00],
    ])
    return ScenarioInputs(
        mu_bps=np.array([612.37, 187.91, 401.55, 455.02, 61.4]),
        sigma_bps=np.array([1534.871234, 412.66, 1088.13, 1210.9, 52.3]),
        skew_bps=np.array([-41.2, 3.3, -17.9, -22.4, 0.0]),
        excess_kurt_bps=np.array([180.5, 22.0, 95.3, 110.1, 0.0]),
        cholesky=np.linalg.cholesky(correlation),
    )


def _content_seed(inputs: ScenarioInputs) -> int:
    return optimizer_content_seed(
        scenario_inputs=inputs, goals=[], score_x10=70,
        horizon_years=15, scenario_horizon_years=30, n_paths=2000,
    )


@pytest.mark.parametrize("relative", [1e-12, -1e-12, 3e-15])
def test_content_seed_ignores_float_noise_in_scenario_inputs(relative):
    """Letzte Bits aus BLAS/LAPACK/libm duerfen den Seed nicht wechseln --
    sonst zoege eine andere Maschine andere Bag-Wuerfel."""
    inputs = _realistic_inputs()
    noisy = _replace(inputs, **{
        name: np.asarray(getattr(inputs, name)) * (1.0 + relative)
        for name in ("mu_bps", "sigma_bps", "skew_bps", "excess_kurt_bps", "cholesky")
    })
    assert scenario_inputs_seed_digest(noisy) == scenario_inputs_seed_digest(inputs)
    assert _content_seed(noisy) == _content_seed(inputs)


def test_content_seed_still_reacts_to_economic_input_changes():
    inputs = _realistic_inputs()
    bumped_mu = np.array(inputs.mu_bps, dtype=float)
    bumped_mu[0] += 0.01  # 0.01 bps
    assert _content_seed(_replace(inputs, mu_bps=bumped_mu)) != _content_seed(inputs)


def test_goal_dates_enter_the_seed_relative_to_the_valuation_year():
    def goal(target_date):
        return {"goal_type": "Vermoegensziel", "target_wealth_rappen": 300_000_00,
                "target_date": target_date, "start_date": None, "is_active": 1}

    fp = goal_economic_fingerprint
    # Gleicher Jahres-Offset, gleicher Monat/Tag -> gleicher Fingerabdruck.
    assert fp([goal("2036-06-30")], valuation_year=2026) == fp(
        [goal("2037-06-30")], valuation_year=2027
    )
    # Anderer Tag bzw. anderer Offset -> anderer Fingerabdruck.
    assert fp([goal("2036-06-30")], valuation_year=2026) != fp(
        [goal("2036-07-01")], valuation_year=2026
    )
    assert fp([goal("2036-06-30")], valuation_year=2026) != fp(
        [goal("2036-06-30")], valuation_year=2027
    )
    # Datum mit Zeitanteil wird wie das Datum behandelt.
    assert fp([goal("2036-06-30T00:00:00Z")], valuation_year=2026) == fp(
        [goal("2036-06-30")], valuation_year=2026
    )
