"""OPTIMIZER-OBJECTIVE-VARIANTS-001 -- der Modus steht im Nachweis.

Die Lektion aus CERT-OPTIMIZER-OBJECTIVE-001: die Ziel-Gewichtung aenderte die
Solver-Mathematik um bis zu Faktor 50, war aber nicht Teil der Modellbasis --
zwei Laeufe, die genuin verschiedene Zielfunktionen optimiert hatten,
persistierten eine identische Basis und einen identischen
``allocation_context_hash``, ohne dass nachweisbar war, welche Mathematik
welche Allokation erzeugt hat.

Der austauschbare Primaerterm hat genau dasselbe Potenzial. Diese Suite
verlangt deshalb:

* Der Modus liegt im persistierten ``optimization_model_basis``.
* Ein anderer Modus erzeugt einen anderen ``allocation_context_hash``.
* Der Modus liegt im Sensitivitaets-Hash -- sonst koennte eine
  Modusaenderung als "Sensitivitaet" eines Ziels erscheinen.
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
from services.optimizer.objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
)
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)

from tests.test_audit_f3_cma_drift import _seed, session_factory  # noqa: F401


def _generate_and_read(session_factory, monkeypatch, mode: str | None) -> tuple[dict, str]:
    """Erzeugt eine Allokation im gegebenen Modus; liefert Basis + Kontext-Hash."""
    if mode is None:
        monkeypatch.delenv("OPTIMIZER_OBJECTIVE", raising=False)
    else:
        monkeypatch.setenv("OPTIMIZER_OBJECTIVE", mode)

    advisor_id, _cid, mandate_id, _aid = _seed(session_factory)
    with session_factory() as session:
        ensure_runtime_reference_data(session, advisor_id)
        session.commit()
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        generate_target_allocation(session, mandate, advisor_id, preferences=None)
        session.commit()
    with session_factory() as session:
        allocation = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mandate_id)
            .order_by(TargetAllocation.version.desc())
            .first()
        )
        assert allocation is not None
        raw = allocation.effective_constraints_json
        context_hash = allocation.allocation_context_hash
    basis = (json.loads(raw) or {}).get("optimization_model_basis") or {}
    return basis, str(context_hash or "")


def test_persisted_basis_names_the_objective_mode(session_factory, monkeypatch) -> None:
    basis, _hash = _generate_and_read(session_factory, monkeypatch, None)
    objective = basis.get("objective")
    assert objective, (
        "optimization_model_basis fuehrt keinen objective-Block -- wonach "
        "optimiert wurde, ist im Nachweis nicht nachlesbar"
    )
    assert objective["mode"] == OBJECTIVE_GOAL_SHORTFALL
    assert objective["goal_chance_constraint_active"] is True
    assert objective["description"]


def test_variant_mode_is_recorded_as_such(session_factory, monkeypatch) -> None:
    basis, _hash = _generate_and_read(
        session_factory, monkeypatch, OBJECTIVE_MAX_DRAWDOWN
    )
    objective = basis["objective"]
    assert objective["mode"] == OBJECTIVE_MAX_DRAWDOWN
    assert (
        objective["risk_measure_basis"]
        == "cashflow_neutral_portfolio_return_factors"
    )
    # Auch in einer Variante bleibt die Ziel-Untergrenze ausgewiesen aktiv.
    assert objective["goal_chance_constraint_active"] is True


def test_different_modes_produce_different_allocation_context_hashes(
    session_factory, monkeypatch
) -> None:
    """Zwei Laeufe mit verschiedener Zielfunktion sind im Audit-Trail unterscheidbar.

    Das ist die Eigenschaft, deren Fehlen CERT-OPTIMIZER-OBJECTIVE-001 fuer
    die Ziel-Gewichtung beanstandet hat.
    """
    # Zwei Versionen auf DEMSELBEN Mandat -- `_seed` legt einen Advisor mit
    # fester ID an und laesst sich pro Datenbank nur einmal aufrufen.
    advisor_id, _cid, mandate_id, _aid = _seed(session_factory)
    with session_factory() as session:
        ensure_runtime_reference_data(session, advisor_id)
        session.commit()

    hashes: dict[str, str] = {}
    for mode in (OBJECTIVE_GOAL_SHORTFALL, OBJECTIVE_MAX_DRAWDOWN):
        monkeypatch.setenv("OPTIMIZER_OBJECTIVE", mode)
        with session_factory() as session:
            mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
            generate_target_allocation(session, mandate, advisor_id, preferences=None)
            session.commit()
        with session_factory() as session:
            allocation = (
                session.query(TargetAllocation)
                .filter(TargetAllocation.mandate_id == mandate_id)
                .order_by(TargetAllocation.version.desc())
                .first()
            )
            hashes[mode] = str(allocation.allocation_context_hash or "")
            stored = json.loads(allocation.effective_constraints_json or "{}")
        assert stored["optimization_model_basis"]["objective"]["mode"] == mode

    assert all(hashes.values()), "allocation_context_hash wurde nicht gesetzt"
    assert hashes[OBJECTIVE_GOAL_SHORTFALL] != hashes[OBJECTIVE_MAX_DRAWDOWN], (
        "Verschiedene Zielfunktionen ergeben denselben allocation_context_hash "
        "-- im Audit-Trail nicht unterscheidbar"
    )


def test_objective_mode_is_part_of_the_sensitivity_hash() -> None:
    """Eine Modusaenderung darf nicht als Ziel-Sensitivitaet erscheinen.

    Der Sensitivitaets-Hash bindet den Modus; ohne diese Bindung waere die
    ausgewiesene "Sensitivitaet" eines Ziels teilweise der Effekt einer
    geaenderten Zielfunktion. Geprueft am Quelltext der Hash-Nutzlast, weil
    der Hash selbst nur als Hex-String sichtbar wird.

    OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: die zweite Assertion verlangte
    die SCHREIBWEISE ``sensitivity_objective_mode = resolve_objective_mode()``
    und damit genau den Live-Read, der inzwischen der Befund ist. Sie prueft
    jetzt die AUSSAGE: der Wert, der in den Hash geht, stammt aus dem
    eingefrorenen Lauf-Vertrag -- derselbe, den beide Solver-Laeufe benutzen.
    Nur so beschreibt der Hash die Mathematik, die tatsaechlich gelaufen ist,
    und nicht die, die beim Hashen gerade in der Umgebung stand.
    """
    engine_source = (
        BACKEND_ROOT / "services" / "portfolio_engine.py"
    ).read_text(encoding="utf-8")
    assert '"objective_mode": sensitivity_objective_mode' in engine_source, (
        "objective_mode fehlt in der _model_input_hash-Nutzlast"
    )
    assert (
        "sensitivity_objective_mode = sensitivity_objective_contract.objective_mode"
        in engine_source
    ), (
        "Der gehashte Modus stammt nicht aus dem eingefrorenen Lauf-Vertrag"
    )
    # Und der Vertrag wird GENAU EINMAL aufgeloest und an beide Laeufe
    # durchgereicht -- sonst koennte das Delta zwei Mathematiken vergleichen.
    assert (
        "sensitivity_objective_contract = resolve_objective_contract()"
        in engine_source
    )
    assert "objective_contract=sensitivity_objective_contract" in engine_source, (
        "Der aufgeloeste Vertrag wird nicht an die Solver-Laeufe uebergeben"
    )
