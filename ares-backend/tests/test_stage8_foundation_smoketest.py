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

F17 (Codex-Entscheid Runde 3, 2026-11-07): kein bekannter Flake. Der Test
mischte Fachlogik mit realer Laufzeit -- parallele Runnerlast (xdist-Shard)
erzeugte einen fachlich falschen RED (elapsed_ms 22447 > 15000, alle anderen
Kriterien erfuellt). Getrennt in:

- deterministische Fachtests mit INJIZIERTER Laufzeit (Naht
  ``portfolio_engine_optimizer_integration.optimizer_wallclock``) im normalen
  Shard; die Budget-Logik (8000/15000 ms) wird ueber die echte Pipeline und
  an den Grenzen fachlich geprueft;
- einen echten seriellen Laufzeit-Sentinel unter ``wallclock_budget`` (CI-Job
  "Backend Test Wallclock Budgets (serial)", Runnerklasse dort dokumentiert),
  der den Messwert als JUnit-Property ``elapsed_ms`` festhaelt.

Kein Rerun: ein roter Erstlauf bleibt rot (Guard:
tests/test_f17_foundation_runtime_split.py).
"""
from __future__ import annotations

import sys
import warnings
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
import services.portfolio_engine_optimizer_integration as optimizer_integration
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
    classify_shadow_verdict,
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


# F17: injizierte Optimierer-Laufzeit der Fachtests (weit unter 8000 ms, damit
# das Verdikt nur von der Fachlogik abhaengt).
INJECTED_ELAPSED_MS = 1234
# F17: Fruehwarnschwelle des seriellen Sentinels (Warnung, nicht rot).
FOUNDATION_EARLY_WARNING_MS = 13000


class _InjectedWallclock:
    """Ersetzt ``optimizer_wallclock``: erster Aufruf = Start, jeder weitere
    = Start + injizierte Laufzeit. Deterministisch, unabhaengig von Runnerlast."""

    def __init__(self, elapsed_ms: int) -> None:
        self.elapsed_s = elapsed_ms / 1000.0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 1000.0 if self.calls == 1 else 1000.0 + self.elapsed_s


def _run_shadow_stochastic_on_foundation(
    session_factory, monkeypatch, *, elapsed_ms: int | None = INJECTED_ELAPSED_MS
) -> dict:
    """Foundation-Case unter shadow_stochastic durchlaufen und Verdict liefern.

    Liefert das volle Per-Mandate-Payload aus build_shadow_comparison_payload.
    ``elapsed_ms``: injizierte Laufzeit (Default); None = echte Wanduhr (nur
    fuer den seriellen wallclock_budget-Sentinel).
    """
    advisor_id, mandate_id = _seed_foundation(session_factory)
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    if elapsed_ms is not None:
        monkeypatch.setattr(
            optimizer_integration, "optimizer_wallclock", _InjectedWallclock(elapsed_ms)
        )
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
        # Diagnose (PR #659): Verdikt-Gruende und Solver-Laufzeit explizit,
        # damit ein RED aus der Laufzeitgrenze (elapsed_ms > 15000) von einem
        # fachlichen RED unterscheidbar ist. Schwellen unveraendert.
        f"verdict_reasons={notes}\n"
        f"elapsed_ms={payload.get('elapsed_ms')}"
    )
    # F17: die Laufzeit ist injiziert -- das Verdikt haengt nur an der Fachlogik.
    assert payload["elapsed_ms"]["stochastic"] == INJECTED_ELAPSED_MS, diagnostic
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
# 3b. F17: Laufzeit-Budget fachlich (injizierte Uhr) und als serieller Sentinel
# ---------------------------------------------------------------------------

def test_injected_runtime_over_hard_budget_turns_foundation_red(
    session_factory, monkeypatch
):
    """Ende-zu-Ende ueber die echte Pipeline: die injizierte Laufzeit erreicht
    das Verdikt; 15001 ms ist der einzige RED-Grund (Fachkriterien erfuellt)."""
    payload = _run_shadow_stochastic_on_foundation(
        session_factory, monkeypatch, elapsed_ms=15001
    )
    assert payload["elapsed_ms"]["stochastic"] == 15001
    assert payload["verdict"] == "red"
    assert payload["verdict_notes"] == ["elapsed_ms > 15000"]


def _foundation_metrics(payload: dict) -> dict:
    return dict(
        total_drift_bps=payload["total_drift_bps"],
        risky_drift_bps=payload["risky_drift_bps"],
        budget_compliance_st=payload["budget_compliance"]["stochastic"],
        n_hard_unreachable_st=payload["goal_counts"]["n_hard_unreachable_st"],
        limiting_factor=payload["limiting_factor"],
        optimization_status=payload["optimization_status"],
    )


def test_runtime_budget_boundaries_on_foundation_metrics(session_factory, monkeypatch):
    """Budget-Logik an den Grenzen mit den echten Foundation-Kennzahlen (ein
    Pipeline-Lauf). Bis 8000 ms bestimmt nur die Fachlogik; 22447 ms ist der
    rote CI-Erstlauf aus H-131 -- RED, aber nur als Laufzeitbefund."""
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch)
    metrics = _foundation_metrics(payload)
    baseline = classify_shadow_verdict(elapsed_ms=INJECTED_ELAPSED_MS, **metrics)
    assert not any("elapsed_ms" in r for r in baseline["reasons"])
    for elapsed_ms in (0, 8000):
        assert classify_shadow_verdict(elapsed_ms=elapsed_ms, **metrics) == baseline
    for elapsed_ms in (8001, 15000):
        result = classify_shadow_verdict(elapsed_ms=elapsed_ms, **metrics)
        assert result["status"] == "YELLOW", (elapsed_ms, result)
        assert "8000 < elapsed_ms <= 15000" in result["reasons"]
    for elapsed_ms in (15001, 22447):
        result = classify_shadow_verdict(elapsed_ms=elapsed_ms, **metrics)
        assert result == {"status": "RED", "reasons": ["elapsed_ms > 15000"]}, (elapsed_ms, result)


@pytest.mark.wallclock_budget
def test_foundation_wallclock_budget_sentinel(session_factory, monkeypatch, record_property):
    """Echter Laufzeit-Sentinel (F17): reale Wanduhr, nur im seriellen Job
    "Backend Test Wallclock Budgets (serial)" (``-m wallclock_budget``,
    ``-p no:xdist``; Runnerklasse siehe .github/workflows/test.yml). Der
    Messwert steht als JUnit-Property ``elapsed_ms`` im Job-Artefakt (Trend).
    Kein Rerun: rot bleibt rot. Ob der 15-s-Vertrag hart bleibt, entscheidet
    die Messung auf der freigegebenen Zielhardware (Owner)."""
    payload = _run_shadow_stochastic_on_foundation(session_factory, monkeypatch, elapsed_ms=None)
    elapsed = int(payload["elapsed_ms"]["stochastic"])
    record_property("elapsed_ms", elapsed)
    record_property("verdict", payload["verdict"])
    # F17-Empfehlung (Pruefrunde H4): Fruehwarnung ab 13000 ms -- Warnung im
    # Testbericht (und ::warning:: im CI-Job), NICHT rot. Hart bleibt 15000.
    record_property("early_warning", elapsed > FOUNDATION_EARLY_WARNING_MS)
    if elapsed > FOUNDATION_EARLY_WARNING_MS:
        warnings.warn(
            f"Foundation-Laufzeit {elapsed} ms > Fruehwarnschwelle "
            f"{FOUNDATION_EARLY_WARNING_MS} ms (hart: 15000 ms)",
            stacklevel=1,
        )
    assert payload["verdict"] in {"green", "yellow"}, payload.get("verdict_notes")
    assert elapsed <= 15000, f"Foundation-Laufzeit {elapsed} ms > 15000 ms (Laufzeitbefund)"


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
