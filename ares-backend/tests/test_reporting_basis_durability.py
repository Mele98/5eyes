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

Die Suite deckt den gefixten Teil (Persistierung) und reproduziert den
verbleibenden (Replay) als strict xfail.
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


# ── Offen: Replay des gespeicherten Reporting-Blocks ─────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "REPORTING-BASIS-DURABILITY-001 (Replay offen): der gespeicherte "
        "reporting_model_basis wird beim Reload NICHT verbatim "
        "zurueckgespielt, sondern aus der aktuellen Umgebung neu gebaut -- "
        "anders als optimization_model_basis, wo genau das seit "
        "CERT-OPTIMIZER-OBJECTIVE-001 ausdruecklich geloest ist. Praeferenz- "
        "abhaengige Eintraege (Tail-Modell, Rebalancing, Transaktionskosten) "
        "sind unkritisch, weil der Reload-Pfad die Snapshot-Praeferenzen der "
        "Allokation verwendet. Kritisch sind die CODE- und UMGEBUNGS-"
        "bestimmten Eintraege: aendert sich die Drawdown-Methode oder die "
        "Intra-Korrelations-Einstellung nach der Generierung, weist der Reload "
        "die HEUTIGE Methodik neben einer Zahl aus, die unter der ALTEN "
        "entstanden ist -- und nichts erkennt die Abweichung. Fix: den "
        "gespeicherten Block durchreichen (Parameter analog "
        "stored_optimization_basis) und eine Divergenz melden statt sie zu "
        "ueberschreiben."
    ),
)
def test_reload_replays_the_stored_reporting_basis_verbatim(
    session_factory, monkeypatch
) -> None:
    """Reproducer: Reload darf nicht die heutige Methodik ueber eine alte Zahl schreiben."""
    import services.portfolio_engine as engine

    advisor_id, mandate_id = _generate(session_factory)
    stored = _stored_reporting_basis(session_factory, mandate_id)
    assert stored["max_drawdown_time_grid"]["model_version"] == (
        DRAWDOWN_REFINEMENT_MODEL_VERSION
    )

    # Methodenwechsel nach der Generierung simulieren.
    monkeypatch.setattr(
        engine,
        "drawdown_time_grid_basis",
        lambda *args, **kwargs: {
            "model_version": "hypothetical_future_method_v9",
            "sub_steps_per_year": 999,
            "method": "something_else",
            "volatility_source": "something_else",
        },
    )

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id)
            .order_by(TargetAllocation.version.desc())
            .first()
        )
        payload = build_target_payload_from_allocation(
            session, mandate, allocation, advisor_id
        )

    reloaded = payload["model_basis"]["reporting"]["max_drawdown_time_grid"]
    assert reloaded["model_version"] == DRAWDOWN_REFINEMENT_MODEL_VERSION, (
        "Der Reload weist die heutige Drawdown-Methodik neben einer Zahl aus, "
        f"die unter einer anderen entstanden ist: {reloaded['model_version']}"
    )
