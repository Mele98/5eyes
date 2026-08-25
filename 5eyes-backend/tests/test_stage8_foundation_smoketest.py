"""Stage 8 Pre-Owner-Verifikation: Foundation-Case Smoketest.

Methodology §1 verlangt, dass der Foundation-Case deterministisch
reproduzierbar GREEN landet, BEVOR die realen Mandate verglichen werden.
Wenn diese Bedingung schon im CI bricht, hilft die UI dem Owner nicht —
er bekommt nur das gleiche RED nochmal vor Augen.

Dieser Test schließt die Lücke vor der Owner-Aktion. Er ruft den ECHTEN
Stochastic-Solver auf (kein Mock), damit das Foundation-Resultat keine
Test-Konstante ist.

Bezug:
- Methodology `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md`
  §1 Voraussetzungen + §2.1 Foundation-Case + §4 GREEN-Schwellen.
- Stage 8 Foundation `services/shadow_comparison.py::aggregate_shadow_comparisons`
  (verfügbar seit develop@bf0f4b2).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.users import User
from services.foundation_example import (
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from services.shadow_comparison import (
    aggregate_shadow_comparisons,
    build_shadow_comparison_payload,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'stage8_foundation.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_foundation(session_factory) -> tuple[str, str]:
    """Foundation-Case + Advisor anlegen, Runtime-Referenzen sicherstellen.

    Returns: (advisor_id, mandate_id)
    """
    advisor_id = "advisor-foundation-smoketest"
    with session_factory() as s:
        advisor = User(
            id=advisor_id,
            username="advisor-foundation",
            password_hash="h",
            full_name="Foundation Advisor",
            role="advisor",
            is_active=1,
            created_at="2026-05-24T00:00:00.000Z",
            updated_at="2026-05-24T00:00:00.000Z",
        )
        s.add(advisor)
        s.commit()
        upsert_foundation_example_case(s, advisor)
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
        mandate = (
            s.query(Mandate)
            .filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER)
            .one()
        )
        return advisor_id, mandate.id


def _run_shadow_stochastic_on_foundation(session_factory, monkeypatch) -> dict:
    """Foundation-Case unter shadow_stochastic durchlaufen und Verdict liefern.

    Liefert das volle Per-Mandate-Payload aus build_shadow_comparison_payload.
    """
    advisor_id, mandate_id = _seed_foundation(session_factory)
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        result = generate_target_allocation(
            s, mandate, advisor_id, preferences=None
        )
        ta = result["target_allocation"]
        s.commit()
        # Pre-Condition: Shadow-Optimization MUSS persistiert sein, sonst ist
        # die Pipeline gebrochen (z.B. solver gar nicht gelaufen).
        assert ta.shadow_optimization_json, (
            "shadow_optimization_json fehlt — Shadow-Mode hat keinen "
            "Stochastic-Pass ausgeführt."
        )
    with session_factory() as s:
        return build_shadow_comparison_payload(s, mandate_id)


# ---------------------------------------------------------------------------
# 1. Foundation-Pipeline läuft durch (Methodology §1 Pre-Condition)
# ---------------------------------------------------------------------------

def test_foundation_case_pipeline_persists_shadow_payload(
    session_factory, monkeypatch
):
    """Pipeline-Smoketest: Foundation → shadow_stochastic → Payload existiert.

    Wenn dieser Test rot wird, ist Stage 5 (Shadow-Persistenz) oder Stage 2
    (Foundation-Schema) gebrochen — die Owner-Aktion ist unmöglich.
    """
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch)
    assert payload["mandate_id"]
    assert payload["shadow_engine"] == "stochastic"
    assert payload["active_engine"] == "house_matrix"
    # Methodology §3.5 Reasoning-Trace-Vollständigkeit
    assert payload["limiting_factor"], (
        "limiting_factor fehlt im Shadow-Payload — Stage 2/3 verletzt §3.5."
    )
    assert isinstance(payload["goal_achievability"], list)


# ---------------------------------------------------------------------------
# 2. Foundation-Case landet in der Aggregat-Sicht
# ---------------------------------------------------------------------------

def test_foundation_case_appears_in_aggregate(session_factory, monkeypatch):
    """Aggregator findet das Foundation-Mandat und klassifiziert es korrekt."""
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch)
    foundation_verdict = payload["verdict"]
    with session_factory() as s:
        agg = aggregate_shadow_comparisons(s)
    assert agg["counts"]["total"] == 1, (
        f"Aggregator findet {agg['counts']['total']} Mandate, erwartet 1 "
        f"(nur Foundation gepersistiert)."
    )
    # Das Foundation-Mandat MUSS in seinem Verdict-Beispiel auftauchen.
    examples_for_verdict = agg["examples"][foundation_verdict]
    assert len(examples_for_verdict) == 1
    assert examples_for_verdict[0]["mandate_id"] == payload["mandate_id"]
    # Gesamt-Verdikt blockt — entweder wegen Stichprobe < 3 ODER (bei RED-
    # Verdict) wegen Hard-Block durch RED. Beide Reasons sind valide
    # Default-Switch-Blocker per Methodology §4.
    assert agg["default_switch_ready"] is False
    reason = agg["default_switch_reason"]
    assert ("mindestens 3" in reason) or ("RED" in reason), (
        f"Unerwarteter default_switch_reason: {reason!r}"
    )


# ---------------------------------------------------------------------------
# 3. Foundation-Verdikt — Methodology §4 GREEN-Erwartung
# ---------------------------------------------------------------------------

def test_foundation_case_yields_green_or_yellow_verdict(
    session_factory, monkeypatch
):
    """Foundation MUSS mindestens YELLOW liefern (RED = sofortiger Stop).

    GREEN ist die Spec-Erwartung, YELLOW noch akzeptabel (mit Owner-Review),
    RED ist die Stop-Bedingung — Foundation darf nie hart zerbrechen.
    """
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch)
    verdict = payload["verdict"]
    notes = payload.get("verdict_notes") or []
    # Diagnose-Output bei Test-Fehlschlag (zeigt sofort den limiting_factor +
    # Schwellen-Bruch, ohne dass man pytest -s braucht).
    diagnostic = (
        f"\nFoundation-Verdict={verdict}\n"
        f"limiting_factor={payload.get('limiting_factor')}\n"
        f"optimization_status={payload.get('optimization_status')}\n"
        f"total_drift_bps={payload.get('total_drift_bps')}\n"
        f"risky_drift_bps={payload.get('risky_drift_bps')}\n"
        f"budget_compliance={payload.get('budget_compliance')}\n"
        f"goal_counts={payload.get('goal_counts')}\n"
        f"verdict_notes={notes}"
    )
    assert verdict in {"green", "yellow"}, (
        f"Foundation-Case wurde als {verdict.upper()} klassifiziert — "
        f"Methodology §1 Pre-Condition gebrochen, kein Owner-Run starten "
        f"bevor das gefixt ist.{diagnostic}"
    )
    # Methodology §3.5: n_hard_unreachable_st == 0 ist hartes Foundation-Krit.
    assert payload["goal_counts"]["n_hard_unreachable_st"] == 0, (
        f"Foundation hat hart-unerreichbare Goals — Daten-Problem oder "
        f"Solver-Bug.{diagnostic}"
    )


# ---------------------------------------------------------------------------
# 4. Konsistenz Per-Mandate vs. Aggregat
# ---------------------------------------------------------------------------

def test_foundation_per_mandate_and_aggregate_verdicts_match(
    session_factory, monkeypatch
):
    """Beide Endpoints MÜSSEN dasselbe Verdikt liefern (Aggregat liest §3.x
    Metriken aus Per-Mandate-Payload, nicht aus separater Quelle).
    """
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch)
    with session_factory() as s:
        agg = aggregate_shadow_comparisons(s)
    # Foundation ist das einzige Mandat — alle 3 Beispiel-Listen zusammen
    # enthalten genau dieses eine Mandat in seinem Verdict-Bucket.
    represented_in: list[str] = []
    for verdict in ("green", "yellow", "red"):
        for example in agg["examples"][verdict]:
            if example["mandate_id"] == payload["mandate_id"]:
                represented_in.append(verdict)
    assert represented_in == [payload["verdict"]], (
        f"Per-Mandate-Verdict={payload['verdict']} aber Aggregat hat es in "
        f"Buckets {represented_in}."
    )
