"""REPORTING-BASIS-DURABILITY-001 -- Methodik des Projektionskanals dauerhaft.

Befund
------
Die Reporting-Kennzahlen werden auf der ``TargetAllocation`` persistiert
(``mc_max_drawdown_bps``, ``mc_var_95_bps``, ``mc_exp_vol_bps``,
``mc_exp_return_bps``). Ihre Methodik -- Tail-Modell, Rebalancing-Modus,
Transaktionskosten, Stress-Multiplikator und seit DRAWDOWN-TIME-GRID-001 das
Zeitgitter des Max-Drawdown -- lebte dagegen nur im Live-Payload
(``monte_carlo["model_basis"]``) und ueberlebte den Reload nicht.

Der Entscheidungskanal hatte das Problem nicht: ``optimization_model_basis``
wird in ``effective_constraints_json`` persistiert und beim Reload verbatim
zurueckgespielt, ausdruecklich damit "Reconstructing these fields from today's
settings would silently change seed/path/tax/IS disclosures on reload" nicht
passiert. Fuer den Projektionskanal galt genau diese Begruendung -- nur war sie
dort nicht umgesetzt.

Das ist kein theoretisches Problem: die Zeitgitter-Korrektur bewegt den
gespeicherten Drawdown um 3 bis 10 Prozentpunkte. An einem gespeicherten Wert
war nicht erkennbar, auf welchem Gitter er entstanden ist.

Die Suite deckt die Persistierung und das Replay: der gespeicherte Block wird
beim Reload wortgetreu abgespielt, eine Abweichung der heutigen Methodik als
"veraltet" offengelegt und Altbestand ohne Block als "Basis nicht
gespeichert" gekennzeichnet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.profiling import RiskAssessment
from services.drawdown_refinement import (
    DRAWDOWN_REFINEMENT_MODEL_VERSION,
    WEEKLY_SUB_STEPS,
)
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)

# Wiederverwendete CH-Fixture (Advisor + Client + Mandat + Referenzdaten +
# RiskAssessment + Position) aus der CMA-Drift-Suite, die denselben
# Generate-und-Reload-Pfad faehrt.
from tests.test_audit_f3_cma_drift import _seed, session_factory  # noqa: F401


def _generate(session_factory) -> tuple[str, str]:
    advisor_id, _cid, mandate_id, _aid = _seed(session_factory)
    with session_factory() as session:
        ensure_runtime_reference_data(session, advisor_id)
        session.commit()
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        generate_target_allocation(session, mandate, advisor_id, preferences=None)
        session.commit()
    return advisor_id, mandate_id


def _stored_reporting_basis(session_factory, mandate_id: str) -> dict:
    with session_factory() as session:
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id)
            .order_by(TargetAllocation.version.desc())
            .first()
        )
        assert allocation is not None
        raw = allocation.effective_constraints_json
    assert raw, "effective_constraints_json ist leer"
    return (json.loads(raw) or {}).get("reporting_model_basis") or {}


# ── Gefixt: die Projektions-Methodik wird persistiert ────────────────────────


def test_reporting_model_basis_is_persisted(session_factory) -> None:
    """Der Reporting-Basis-Block liegt neben dem Optimization-Basis-Block.

    Vorher existierte nur ``optimization_model_basis``; die Methodik des
    Kanals, der die persistierten Risiko-KPIs erzeugt, war nirgends dauerhaft.
    """
    _advisor_id, mandate_id = _generate(session_factory)
    basis = _stored_reporting_basis(session_factory, mandate_id)
    assert basis, (
        "effective_constraints_json fuehrt keinen reporting_model_basis -- die "
        "Methodik der persistierten Risiko-KPIs ist nicht nachlesbar"
    )
    assert basis["basis_id"] == "implementation_projection_v2"
    # Die Eintraege, die den gespeicherten Zahlen ihre Bedeutung geben.
    for key in (
        "tail_model",
        "portfolio_dynamics",
        "transaction_cost_bps",
        "stress_multiplier",
        "max_drawdown_time_grid",
        "bucket_correlation",
    ):
        assert key in basis, f"{key} fehlt im persistierten Reporting-Nachweis"


def test_persisted_basis_names_the_drawdown_time_grid(session_factory) -> None:
    """Die Methode hinter mc_max_drawdown_bps steht dauerhaft neben der Zahl.

    Das ist der konkrete Anlass dieses Befundes: ohne diesen Eintrag ist ein
    gespeicherter Drawdown nicht interpretierbar, weil dasselbe Mandat auf dem
    alten Jahresgitter 3 bis 10 Prozentpunkte weniger ausgewiesen haette.
    """
    _advisor_id, mandate_id = _generate(session_factory)
    grid = _stored_reporting_basis(session_factory, mandate_id)[
        "max_drawdown_time_grid"
    ]
    assert grid["model_version"] == DRAWDOWN_REFINEMENT_MODEL_VERSION
    assert grid["sub_steps_per_year"] == WEEKLY_SUB_STEPS
    assert grid["method"] == "brownian_bridge_refinement_of_annual_nodes"
    assert grid["volatility_source"] == "pooled_cross_path_annual_log_increments"


def test_persisted_drawdown_kpi_and_its_method_agree(session_factory) -> None:
    """Die Zahl und ihre Methode stehen auf derselben Zeile.

    Ohne diesen Zusammenhang waere die Persistierung nur Dekoration: geprueft
    wird, dass dieselbe Allokation, die den Drawdown traegt, auch die Methode
    traegt.
    """
    _advisor_id, mandate_id = _generate(session_factory)
    with session_factory() as session:
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id)
            .order_by(TargetAllocation.version.desc())
            .first()
        )
        drawdown_bps = allocation.mc_max_drawdown_bps
        raw = allocation.effective_constraints_json
    assert drawdown_bps is not None, "mc_max_drawdown_bps wurde nicht persistiert"
    grid = (
        (json.loads(raw) or {})
        .get("reporting_model_basis", {})
        .get("max_drawdown_time_grid", {})
    )
    assert grid.get("model_version") == DRAWDOWN_REFINEMENT_MODEL_VERSION


# ── Replay des gespeicherten Reporting-Blocks ───────────────────────────────


def _latest_allocation(session, mandate_id: str) -> TargetAllocation:
    return (
        session.query(TargetAllocation)
        .filter(TargetAllocation.mandate_id == mandate_id)
        .order_by(TargetAllocation.version.desc())
        .first()
    )


def _reload(session_factory, advisor_id: str, mandate_id: str) -> dict:
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        allocation = _latest_allocation(session, mandate_id)
        assessment = (
            session.query(RiskAssessment)
            .filter(RiskAssessment.id == allocation.based_on_assessment_id)
            .first()
        )
        policy, cma = ensure_runtime_reference_data(session, advisor_id)
        return build_target_payload_from_allocation(
            db=session,
            mandate=mandate,
            allocation=allocation,
            policy=policy,
            cma=cma,
            assessment=assessment,
            preferences=None,
        )


_FUTURE_GRID = {
    "model_version": "hypothetical_future_method_v9",
    "sub_steps_per_year": 999,
    "method": "something_else",
    "volatility_source": "something_else",
}


def _simulate_method_change(monkeypatch) -> None:
    """Methodenwechsel nach der Generierung: die Live-Basis wird im
    Modell-Basis-Modul gebaut, also dort patchen (nicht im Kern-Modul, das
    den Namen gar nicht fuehrt -- sonst waere der Test aus dem falschen Grund
    rot)."""
    import services.portfolio_engine_model_basis as model_basis_module

    monkeypatch.setattr(
        model_basis_module,
        "drawdown_time_grid_basis",
        lambda *args, **kwargs: dict(_FUTURE_GRID),
    )


def test_reload_replays_the_stored_reporting_basis_verbatim(
    session_factory, monkeypatch
) -> None:
    """Reload darf nicht die heutige Methodik ueber eine alte Zahl schreiben."""
    advisor_id, mandate_id = _generate(session_factory)
    stored = _stored_reporting_basis(session_factory, mandate_id)
    assert stored["max_drawdown_time_grid"]["model_version"] == (
        DRAWDOWN_REFINEMENT_MODEL_VERSION
    )

    _simulate_method_change(monkeypatch)
    payload = _reload(session_factory, advisor_id, mandate_id)

    reloaded = payload["model_basis"]["reporting"]
    assert reloaded["max_drawdown_time_grid"]["model_version"] == (
        DRAWDOWN_REFINEMENT_MODEL_VERSION
    ), (
        "Der Reload weist die heutige Drawdown-Methodik neben einer Zahl aus, "
        f"die unter einer anderen entstanden ist: {reloaded['max_drawdown_time_grid']}"
    )
    # Wortgetreu: der ganze gespeicherte Block, nicht nur das Zeitgitter.
    assert reloaded == stored


def test_method_change_after_generation_is_visible_as_stale(
    session_factory, monkeypatch
) -> None:
    """Die Abweichung wird offengelegt ("veraltet"), nie still ueberschrieben."""
    advisor_id, mandate_id = _generate(session_factory)
    _simulate_method_change(monkeypatch)
    payload = _reload(session_factory, advisor_id, mandate_id)

    replay = payload["reporting_model_basis_replay"]
    assert replay["status"] == "stale"
    assert replay["mode"] == "historical_replay"
    assert replay["analysis_basis"] == "persisted_snapshot"
    assert replay["divergent_keys"] == ["max_drawdown_time_grid"]
    assert replay["live_preview"]["max_drawdown_time_grid"] == _FUTURE_GRID
    assert "veraltet" in replay["message"]
    assert replay["message"] in payload["reasoning"]
    # Die Live-Projektion des Reloads ist eine HEUTIGE Rechnung und traegt
    # deshalb ehrlich die heutige Methodik -- getrennt von der gespeicherten.
    assert payload["monte_carlo"]["model_basis"]["max_drawdown_time_grid"] == (
        _FUTURE_GRID
    )


def test_unchanged_reload_is_verified_without_warning(session_factory) -> None:
    """Ohne Methodenwechsel: gespeicherte Basis, Status verified, kein Hinweis."""
    advisor_id, mandate_id = _generate(session_factory)
    stored = _stored_reporting_basis(session_factory, mandate_id)
    payload = _reload(session_factory, advisor_id, mandate_id)

    assert payload["model_basis"]["reporting"] == stored
    replay = payload["reporting_model_basis_replay"]
    assert replay["status"] == "verified"
    assert replay["divergent_keys"] == []
    assert replay["live_preview"] is None
    assert replay["message"] is None
    assert not any("Reporting-Methodik" in line for line in payload["reasoning"])


def test_allocation_without_stored_basis_is_labeled_not_persisted(
    session_factory,
) -> None:
    """Altbestand ohne Block: ehrlich "Basis nicht gespeichert", keine stille
    Neuberechnung, die wie ein gespeicherter Wert aussieht.

    Der Altbestand wird realistisch nachgebaut: Block entfernt UND den
    allocation_context_hash darauf neu gerechnet (so sahen Allokationen vor
    der Persistierung aus) -- sonst wuerde das Integritaets-Gate greifen.
    """
    from services.portfolio_engine_allocation_integrity import (
        allocation_context_hash_for,
    )

    advisor_id, mandate_id = _generate(session_factory)
    with session_factory() as session:
        allocation = _latest_allocation(session, mandate_id)
        constraints = json.loads(allocation.effective_constraints_json)
        constraints.pop("reporting_model_basis")
        allocation.effective_constraints_json = json.dumps(
            constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        targets = {
            "equities": int(allocation.target_equities_bps),
            "bonds": int(allocation.target_bonds_bps),
            "real_estate": int(allocation.target_real_estate_bps),
            "alternatives": int(allocation.target_alternatives_bps),
            "liquidity": int(allocation.target_liquidity_bps),
        }
        allocation.allocation_context_hash = allocation_context_hash_for(
            engine_version=constraints["engine_version"],
            policy_id=allocation.policy_id,
            cma_id=allocation.capital_market_assumptions_id,
            assessment_id=allocation.based_on_assessment_id,
            input_snapshot_hash=allocation.input_snapshot_hash,
            preferences_json=allocation.preferences_json,
            targets=targets,
            sub_allocations=json.loads(allocation.sub_allocations_json),
            effective_constraints=constraints,
            optimization_seed=allocation.optimization_seed,
        )
        session.commit()

    payload = _reload(session_factory, advisor_id, mandate_id)
    replay = payload["reporting_model_basis_replay"]
    assert replay["status"] == "not_persisted"
    assert replay["analysis_basis"] == "live_preview"
    assert replay["live_preview"] == payload["model_basis"]["reporting"]
    assert "Basis nicht gespeichert" in replay["message"]
    assert replay["message"] in payload["reasoning"]


def test_non_object_stored_basis_fails_closed() -> None:
    """Ein vorhandener, aber kaputter Block ist ein Integritaetsfehler."""
    from services.reporting_model_basis_replay import replay_reporting_model_basis

    with pytest.raises(ValueError, match="Reporting-Modellbasis"):
        replay_reporting_model_basis(
            {"optimization": {}, "reporting": {"basis_id": "x"}},
            {"reporting_model_basis": ["kein", "objekt"]},
        )
