"""Sprint U-18 (Roadmap-Punkt 18): N+1-Query-Audit fuer compute_advisory_report.

Diese Suite misst die Anzahl SQL-Queries pro compute()-Aufruf via
sqlalchemy event-hook. Ziel: Regression-Schutz beim N+1-Refactor.

Strategie
---------
- Seed ein realistisches Mandat (Client + Mandate + RecommendationRun +
  RiskAssessment + TargetAllocation + Goals + Cashflows + WealthPositions)
- compute_advisory_report() aufrufen, alle SQL-Statements zaehlen
- Assertion: <= UPPER_BOUND_QUERIES
- UPPER_BOUND wird bei U-18-Fix abgesenkt; pre-U-18 nur Doku der
  Baseline

Vor-U-18-Baseline (mit realistischen Daten):
- ~50-90 Queries pro compute() Aufruf
- Hot-Spots:
  * _latest_recommendation_positions wird 3x aufgerufen (latest_run +
    rec_positions je 1 Query)
  * RecommendationRun-Lookups 3x
  * RiskAssessment-Lookups 3x (in _resolve_risk_profile,
    _check_risikoprofil, _build_risikoprofilierung)
  * TargetAllocation-Lookups 5x (key_metrics + 4 Sektionen)
  * Goals 3x, Cashflows 2x

Post-U-18-Ziel: < 30 Queries (call-scoped Cache eliminiert die Duplikate)
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.tenant  # noqa: F401  (Sprint T1)
configure_mappers()
from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import (
    Product,
    RecommendationPosition,
    RecommendationRun,
)
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.advisory_report import compute_advisory_report


_NOW = "2026-05-31T08:00:00.000Z"


class _QueryCounter:
    """SQLAlchemy event listener that counts SELECTs during compute()."""

    def __init__(self) -> None:
        self.count = 0
        self.statements: list[str] = []

    def __enter__(self) -> "_QueryCounter":
        event.listen(Engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(Engine, "before_cursor_execute", self._before)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        # Nur SELECTs zaehlen — INSERT/UPDATE/DELETE sind nicht das N+1-Risiko
        if statement.lstrip().upper().startswith("SELECT"):
            self.count += 1
            # Statement komplett behalten — fuer by_table-Heuristik koennen
            # FROM-Clausen weit nach dem Spalten-Block kommen.
            self.statements.append(statement)

    def by_table(self) -> dict[str, int]:
        """Aggregiert SELECTs nach erkanntem Ziel-Table.

        SQLAlchemy generiert oft `SELECT ... FROM table_name`. Wir
        suchen nach dem ersten Identifier nach FROM, ignorieren
        Whitespace/Newlines.
        """
        import re
        out: dict[str, int] = {}
        for s in self.statements:
            # erste FROM-Klausel finden
            match = re.search(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", s, re.IGNORECASE)
            table = match.group(1).upper() if match else "OTHER"
            out[table] = out.get(table, 0) + 1
        return out


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'n1.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_realistic_mandate(s):
    """Vollstaendiges Mandat mit Recommendation, TA, RA, Goals etc."""
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beraterin",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(advisor)
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Hans",
        last_name="Muster",
        date_of_birth="1976-03-14",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(client)
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        retirement_year=2041,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(mandate)
    s.add(RiskAssessment(
        id=str(uuid.uuid4()), mandate_id=mandate.id,
        version=1, is_current=1, valid_from=_NOW,
        q_income_points=3, q_obligations_points=2,
        q_savings_points=3, q_wealth_points=3,
        risk_capacity_total=11,
        risk_capacity_profile="Wachstumsorientiert",
        investment_horizon_years=15,
        investment_horizon_label="Langfristig",
        risk_capacity_score_x10=75,
        q_investment_goal_points=4,
        q_risk_preference_points=3,
        q_risk_behavior_points=2,
        risk_willingness_total=9,
        risk_willingness_profile="Ausgewogen",
        risk_willingness_score_x10=60,
        final_score_x10=68,
        final_profile="Ausgewogen",
        assessed_at=_NOW, assessed_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    policy = OptimizerPolicy(
        id=str(uuid.uuid4()),
        version=1, is_current=1,
        policy_name="Test-Policy",
        valid_from=_NOW,
        created_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(policy)
    ta = TargetAllocation(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        version=1, is_current=1,
        policy_id=policy.id,
        risky_fraction_bps=7500,
        risk_budget_bps_at_generation=8000,
        target_equities_bps=4000, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=1000,
        target_liquidity_bps=500,
        band_equities_min_bps=3500, band_equities_max_bps=4500,
        band_bonds_min_bps=3000, band_bonds_max_bps=4000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=500, band_alternatives_max_bps=1500,
        band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
        set_by=advisor.id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(ta)
    rec_run = RecommendationRun(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        client_id=client.id,
        target_allocation_id=ta.id,
        policy_id=policy.id,
        run_type="full",
        result_status="Approved",
        created_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(rec_run)
    # 5 Produkte + 5 RecommendationPositions
    for i, ac in enumerate(["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"]):
        product = Product(
            id=str(uuid.uuid4()),
            isin=f"CH{i:09d}",
            product_name=f"Test-{ac}",
            product_type="ETF",
            asset_class=ac,
            sub_asset_class=ac,
            currency="CHF",
            ter_bps=20,
            provider="Test",
            is_active=1,
            created_at=_NOW, updated_at=_NOW,
        )
        s.add(product)
        s.add(RecommendationPosition(
            id=str(uuid.uuid4()),
            run_id=rec_run.id,
            product_id=product.id,
            target_amount_rappen=2_000_000,
            target_weight_bps=2000,
            created_at=_NOW, updated_at=_NOW,
        ))
    # 3 Goals
    for rank, label in enumerate(["Pension", "Liegenschaft", "Reserve"]):
        s.add(Goal(
            id=str(uuid.uuid4()),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Vermoegensaufbau",
            goal_type=label,
            label=label,
            target_amount_rappen=10_000_000,
            target_date="2041-03-14",
            hardness="Primaer",
            rank=rank + 1,
            is_active=1,
            created_at=_NOW, updated_at=_NOW,
        ))
    # 3 Cashflows
    for i in range(3):
        s.add(Cashflow(
            id=str(uuid.uuid4()),
            client_id=client.id,
            cashflow_type="Income" if i == 0 else "Expense",
            label=f"CF-{i}",
            amount_rappen=500_000,
            frequency="monatlich",
            is_active=1,
            created_at=_NOW, updated_at=_NOW,
        ))
    # 4 WealthPositions
    for i in range(4):
        s.add(WealthPosition(
            id=str(uuid.uuid4()),
            client_id=client.id,
            position_type="Bankkonto" if i < 2 else "Aktienportfolio",
            label=f"WP-{i}",
            current_value_rappen=5_000_000,
            currency="CHF",
            assignment="Beratungsvermögen",
            is_active=1,
            created_at=_NOW, updated_at=_NOW,
        ))
    s.flush()
    return mandate, client, advisor


# ---------------------------------------------------------------------------
# Baseline-Messung
# ---------------------------------------------------------------------------

def test_compute_advisory_report_query_count_below_budget(session_factory):
    """compute() darf nicht mehr als BUDGET SELECTs ausloesen.

    Baseline (pre-U-18): 35 SELECTs mit Hotspots TA 7x, RR/RP/RA je 4x.
    Post-U-18 (2026-06-01-Original): <= 25 (Reduktion ~30% durch
    call-scoped Cache fuer RR/RP).
    Post-Aggregator-Sprint #163 (2026-06-05): Sektionen 19-25 dazu
    (suitability/methodology/recommendation/lock/cascade/optimizer-
    history/performance-attribution) — neue Queries auf TA, OPTIMIZER_RUNS,
    ADVISORY_LOG, OPTIMIZER_POLICIES. Plus Bug-#13a Bausteine.
    Effective neue Baseline: ~45 SELECTs.
    Diese Test-Assertion bleibt Drift-Wache: wer eine NAIVE Query in
    einem bestehenden _build_*-Funktion ergaenzt, ueberschreitet 50.
    """
    BUDGET = 50

    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate(s)
        s.commit()

        with _QueryCounter() as counter:
            payload = compute_advisory_report(s, mandate, advisor=advisor)

    # Output ist gueltig
    assert payload["schema_version"] == 2
    assert payload["mandate_id"] == mandate.id

    # Query-Budget eingehalten
    by_table = counter.by_table()
    assert counter.count <= BUDGET, (
        f"compute() macht {counter.count} SELECTs — Budget {BUDGET}.\n"
        f"Hotspots (per Tabelle): {sorted(by_table.items(), key=lambda kv: -kv[1])[:10]}"
    )


def test_specific_tables_are_queried_at_most_twice(session_factory):
    """Spezifische Drift-Schutz-Asserts. U-18-Original-Ziel war strikt
    <=2 fuer RR/RP und <=3 fuer TA/RA. Nach Aggregator-Sprint #163 sind
    neue Sektionen dazu gekommen (Hotspots: TA 7x, OPTIMIZER_RUNS 5x,
    ADVISORY_LOG 4x).

    U-18-Cache wirkt weiter auf RR/RP (<=2 stabil). Fuer TA/OPTIMIZER_RUNS
    folgt mit einem Aggregator-Cache-v2-Sprint die naechste Stufe.
    """
    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate(s)
        s.commit()

        with _QueryCounter() as counter:
            compute_advisory_report(s, mandate, advisor=advisor)

    by_table = counter.by_table()

    # U-18-Original-Cache-Wirkung haelt fuer RR/RP/GOALS.
    # 2026-07-20: Baseline 2 -> 3. Die neue Kostenausweis-Sektion (FIDLEG Art.
    # 8/9, services/cost_disclosure.build_cost_disclosure) laedt den letzten
    # RecommendationRun (Fee-Snapshot-Quelle) einmal zusaetzlich. Bewusster,
    # bounded +1-Query fuer eine legitime Sektion — kein N+1-Wildwuchs.
    assert by_table.get("RECOMMENDATION_RUNS", 0) <= 3, (
        f"RECOMMENDATION_RUNS soll <=3, war {by_table.get('RECOMMENDATION_RUNS')}"
    )
    # 2026-07-20: Baseline 2 -> 3 analog RECOMMENDATION_RUNS — build_cost_disclosure
    # laedt zur Kostenberechnung auch die RecommendationPositions des letzten Runs
    # einmal zusaetzlich. Bewusster, bounded +1-Query.
    assert by_table.get("RECOMMENDATION_POSITIONS", 0) <= 3, (
        f"RECOMMENDATION_POSITIONS soll <=3, war {by_table.get('RECOMMENDATION_POSITIONS')}"
    )
    assert by_table.get("GOALS", 0) <= 1, (
        f"GOALS soll <=1, war {by_table.get('GOALS')}"
    )
    # Post-#163-Werte (Soll-Aggregator-Cache-v2-Sprint senkt diese)
    assert by_table.get("TARGET_ALLOCATIONS", 0) <= 8, (
        f"TARGET_ALLOCATIONS soll <=8, war {by_table.get('TARGET_ALLOCATIONS')}"
    )
    assert by_table.get("RISK_ASSESSMENTS", 0) <= 5, (
        f"RISK_ASSESSMENTS soll <=5, war {by_table.get('RISK_ASSESSMENTS')}"
    )
    assert by_table.get("CASHFLOWS", 0) <= 1, (
        f"CASHFLOWS soll <=1, war {by_table.get('CASHFLOWS')}"
    )


def test_compute_advisory_report_output_unchanged(session_factory):
    """Sicherheits-Test: nach dem N+1-Refactor muessen 2 aufeinander-
    folgende compute()-Aufrufe das EXAKT gleiche Payload liefern (das
    `generated_at` weicht natuerlich ab — wir ignorieren es)."""
    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate(s)
        s.commit()
        payload_a = compute_advisory_report(s, mandate, advisor=advisor)
        payload_b = compute_advisory_report(s, mandate, advisor=advisor)

    payload_a.pop("generated_at", None)
    payload_b.pop("generated_at", None)
    import json
    assert json.dumps(payload_a, sort_keys=True) == json.dumps(payload_b, sort_keys=True)


def test_cache_aware_helpers_fall_back_when_no_cache_active(session_factory):
    """Wichtige Defensive: die _cached_*-Helper duerfen NICHT crashen wenn
    sie ohne aktives compute()-Cache aufgerufen werden (z.B. in Tests oder
    aus depot_check.py das nur compute_advisory_report indirekt erreicht).

    Wenn db.info[_CACHE_KEY] nicht gesetzt ist, soll _aggregator_cache_get
    factory() direkt aufrufen — ohne Caching, aber auch ohne Crash.
    """
    from services.advisory_report import (
        _cached_latest_recommendation_run,
        _cached_current_ta,
        _cached_current_ra,
        _cached_active_goals,
        _cached_active_cashflows,
    )
    with session_factory() as s:
        mandate, client, _advisor = _seed_realistic_mandate(s)
        s.commit()

        # Kein Cache aktiv -> Helper duerfen trotzdem korrekt liefern
        assert "_advisory_aggregator_call_cache" not in s.info
        run = _cached_latest_recommendation_run(s, mandate)
        ta = _cached_current_ta(s, mandate)
        ra = _cached_current_ra(s, mandate)
        goals = _cached_active_goals(s, mandate)
        cashflows = _cached_active_cashflows(s, client.id)

    assert run is not None
    assert ta is not None
    assert ra is not None
    assert len(goals) == 3
    assert len(cashflows) == 3


def test_cache_is_isolated_between_calls(session_factory):
    """compute() darf KEINE Cache-Reste zwischen Aufrufen behalten — sonst
    sieht Aufruf 2 stale Daten von Aufruf 1, wenn die DB sich zwischen den
    Aufrufen geaendert hat.

    Wir testen: nach compute() ist db.info sauber, und ein zweiter
    compute()-Aufruf sieht aktualisierte DB-State.
    """
    with session_factory() as s:
        mandate, client, advisor = _seed_realistic_mandate(s)
        s.commit()
        first = compute_advisory_report(s, mandate, advisor=advisor)
        # Cache muss leer sein nach compute()
        assert "_advisory_aggregator_call_cache" not in s.info

        # DB aendern: neue Goal hinzufuegen
        from models.wealth import Goal
        s.add(Goal(
            id=str(uuid.uuid4()),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Vermoegensaufbau",
            goal_type="NEW-GOAL-AFTER-FIRST-COMPUTE",
            label="NEW-GOAL-AFTER-FIRST-COMPUTE",
            target_amount_rappen=1_000_000,
            target_date="2050-01-01",
            hardness="Primaer",
            rank=99,
            is_active=1,
            created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()

        # Zweiter compute() muss neuen Goal sehen
        second = compute_advisory_report(s, mandate, advisor=advisor)

    first_goal_labels = {g.get("label") for g in first["ausgangslage"]["wealth_summary"]["ziele"]}
    second_goal_labels = {g.get("label") for g in second["ausgangslage"]["wealth_summary"]["ziele"]}
    assert "NEW-GOAL-AFTER-FIRST-COMPUTE" not in first_goal_labels
    assert "NEW-GOAL-AFTER-FIRST-COMPUTE" in second_goal_labels
