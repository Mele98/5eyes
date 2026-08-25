"""Roadmap #83 - Performance-Budget fuer Strategie-Berechnung + Report-Aggregator.

Reine Test-Addition (kein Produktivcode geaendert). Zweck: eine GROBE
Regressions-Bremse, kein Millisekunden-SLA. Diese Suite misst Wandzeit
(time.perf_counter) fuer die zwei teuersten Aggregator-Einstiegspunkte:

1. services.portfolio_engine.generate_target_allocation() — die
   Strategie-/SAA-Berechnung (Monte-Carlo-Simulation, Optimizer, Bands).
2. services.advisory_report.compute_advisory_report() — der 25+-Sektionen
   Report-Aggregator.

WICHTIG — Baseline-Methodik (siehe auch Roadmap #83 Auftrag):
Die Budgets unten sind KEINE absoluten Performance-SLAs. Sie sind
Schnappschuesse der tatsaechlich gemessenen Laufzeit auf dem Dev-/CI-
Runner, zum Zeitpunkt der Testerstellung, multipliziert mit einem
grosszuegigen Sicherheitsfaktor (~3x). Zweck: eine 10x-Regression
(z.B. eine versehentlich eingebaute O(n^2)-Schleife oder ein N+1-Query-
Sturm) soll den Test rot faerben; normale System-Last (langsamere CI-
Maschine, paralleler Testlauf, kalter Dateicache) soll NICHT flaken.

Gemessene Baseline auf diesem Dev-Rechner (Windows 11, 3x Testlauf,
warmer Python-Import-Cache):
    generate_target_allocation():  siehe Kommentar bei BUDGET_GENERATE_S
    compute_advisory_report():      siehe Kommentar bei BUDGET_REPORT_S

2026-08-21-Nachtrag (Peer-Review-Nachlauf stochastischer Optimizer, PR #375):
generate_target_allocation() ruft jetzt zusaetzlich die strikte Risikoprofil-
Neuherleitung (services/risk_assessment_semantics.py::_validate_persisted_
derivation) sowie eine deutlich strengere Preference-Werte-/Typ-/Bereichs-
validierung auf (schemas/allocation.py) -- echte, gewollte Mehrarbeit fuer
staerkere Fail-Closed-Garantien, keine Ineffizienz. Neue lokale Baseline
(3 Laeufe): 2.46s / 2.40s / 2.67s (vorher 1.90s/1.95s/2.08s, ca. +25-30%).
Der GitHub-Actions-Runner lief bei diesem PR zusaetzlich deutlich langsamer
als der lokale Rechner (6.138s gemessen bei einem Einzellauf, obwohl lokal
nie ueber 2.7s) -- das Budget unten ist daher bewusst NICHT nur 3x die
lokale Baseline, sondern mit Sicherheitsabstand ÜBER dem real beobachteten
CI-Wert gesetzt.

Falls dieser Test auf einem deutlich langsameren CI-Runner dauerhaft
flakt, ist die richtige Reaktion: Budget anheben (mit neuer Baseline-
Messung dokumentieren), NICHT den Test loeschen — er ist die einzige
Regressions-Bremse gegen "Engine wird 10x langsamer und niemand merkt
es, bis der Kunde sich beschwert".
"""
from __future__ import annotations

import sys
import time
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

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.advisory_report import compute_advisory_report
from services.portfolio_engine import generate_target_allocation
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
)


_NOW = "2026-07-22T09:00:00.000Z"

# ---------------------------------------------------------------------------
# Budgets — siehe Modul-Docstring fuer die Methodik (~3x gemessene Baseline).
# ---------------------------------------------------------------------------
# Gemessen auf Dev-Rechner (Windows 11, 3 Laeufe, sqlite in tmp_path, kein
# Netzwerk, python -m pytest -s):
#   generate_target_allocation(): 1.90s / 1.95s / 2.08s  (Monte-Carlo-dominiert)
#   compute_advisory_report():    0.079s / 0.073s / 0.075s
#   kombiniert (beide seriell):   1.98s / 2.07s / 2.26s
# Budget = ca. 3x das langsamste der 3 gemessenen Laeufe (deckt eine
# 10x-Regression zuverlaessig, flakt nicht bei normaler System-Last):
#
# 2026-08-21-Nachtrag (PR #375, siehe Modul-Docstring): neue lokale Baseline
# nach der strikten Risikoprofil-/Preference-Validierung:
#   generate_target_allocation(): 2.46s / 2.40s / 2.67s
#   compute_advisory_report():    0.077s / 0.083s / 0.071s  (unveraendert)
#   kombiniert:                   2.19s / 2.10s / 2.72s
# GitHub-Actions-CI lief bei diesem PR spuerbar langsamer als lokal
# (generate=6.138s, kombiniert=7.006s in einem Einzellauf) -- Budget daher
# mit Sicherheitsabstand ueber dem real beobachteten CI-Wert gesetzt, nicht
# nur 3x lokal:
BUDGET_GENERATE_S = 9.0
BUDGET_REPORT_S = 1.0
BUDGET_COMBINED_S = 10.5


class _QueryCounter:
    """SQLAlchemy event listener that counts SELECTs (Muster aus
    test_aggregator_n1_baseline.py) — hier als zweite, orthogonale
    Regressions-Dimension neben der reinen Wandzeit."""

    def __init__(self) -> None:
        self.count = 0

    def __enter__(self) -> "_QueryCounter":
        event.listen(Engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(Engine, "before_cursor_execute", self._before)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            self.count += 1


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'perf_budget.db'}",
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


def _seed_realistic_mandate_for_perf(s):
    """Mandat 'realistischer Groesse': 6 Wealth-Positionen (Depot,
    2x Bankkonto, Aktienportfolio, Eigenheim, Hypothek), 4 Cashflows,
    3 Ziele, ein vollstaendiges (strategie-bereites) Risikoprofil.

    Muster kombiniert aus tests/test_audit_f23_mc_total_paths.py
    (_seed_mandate_with_total_wealth — Risikoprofil-Readiness) und
    tests/test_aggregator_n1_baseline.py (_seed_realistic_mandate —
    Wealth/Cashflow/Goal-Groessenordnung).
    """
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Perf Beraterin",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(advisor)
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Perf",
        last_name="Budget",
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

    # 6 Wealth-Positionen: Beratungsvermoegen + Gesamtvermoegen + Verbindlichkeit
    s.add(WealthPosition(
        id=str(uuid.uuid4()), client_id=client.id,
        label="Depot", position_type="Depot", assignment="Beratungsvermögen",
        current_value_rappen=300_000_00, currency="CHF",
        alloc_equities_bps=4000, alloc_bonds_bps=3000,
        alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
        alloc_alternatives_bps=1000,
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    for i in range(2):
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client.id,
            label=f"Bankkonto-{i}", position_type="Bankkonto",
            assignment="Beratungsvermögen",
            current_value_rappen=50_000_00, currency="CHF",
            alloc_liquidity_bps=10000,
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
    s.add(WealthPosition(
        id=str(uuid.uuid4()), client_id=client.id,
        label="Aktienportfolio", position_type="Aktienportfolio",
        assignment="Beratungsvermögen",
        current_value_rappen=150_000_00, currency="CHF",
        alloc_equities_bps=10000,
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    s.add(WealthPosition(
        id=str(uuid.uuid4()), client_id=client.id,
        label="Eigenheim", position_type="Liegenschaft",
        assignment="Gesamtvermögen",
        current_value_rappen=800_000_00, currency="CHF",
        alloc_real_estate_bps=10000,
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    s.add(WealthPosition(
        id=str(uuid.uuid4()), client_id=client.id,
        label="Hypothek", position_type="Hypothek",
        assignment="Verbindlichkeit",
        current_value_rappen=600_000_00, currency="CHF",
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))

    # 4 Cashflows (Einkommen + Ausgaben)
    s.add(Cashflow(
        id=str(uuid.uuid4()), client_id=client.id,
        cashflow_type="Income", label="Lohn",
        amount_rappen=1_200_000, currency="CHF",
        frequency="monatlich", nature="wiederkehrend",
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    s.add(Cashflow(
        id=str(uuid.uuid4()), client_id=client.id,
        cashflow_type="Income", label="Sparplan",
        amount_rappen=30_000_00, currency="CHF",
        frequency="jährlich", nature="wiederkehrend",
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))
    for i, label in enumerate(["Miete/Nebenkosten", "Lebenshaltung"]):
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client.id,
            cashflow_type="Expense", label=label,
            amount_rappen=250_000, currency="CHF",
            frequency="monatlich", nature="wiederkehrend",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))

    # 3 Ziele
    # 2026-08 (asset-allocation-stochastic-core): _validate_active_goal_inputs()
    # verlangt jetzt einen kanonischen goal_type (services/portfolio_engine.py
    # _SUPPORTED_GOAL_TYPE_KEYS) statt eines beliebigen Anzeige-Labels; die
    # Ziel-ANZEIGE bleibt label, nur goal_type wird kanonisch.
    for rank, label in enumerate(["Pension", "Liegenschaft", "Reserve"]):
        s.add(Goal(
            id=str(uuid.uuid4()), mandate_id=mandate.id, client_id=client.id,
            goal_family="Vermoegensaufbau", goal_type="vermoegensziel", label=label,
            target_wealth_rappen=10_000_000, target_date="2041-03-14",
            hardness="Primaer", rank=rank + 1, is_active=1,
            created_at=_NOW, updated_at=_NOW,
        ))

    # Vollstaendiges, strategie-bereites Risikoprofil (Readiness-Gate in
    # generate_target_allocation -> require_strategy_ready_assessment).
    aid = str(uuid.uuid4())
    s.add(RiskAssessment(
        id=aid, mandate_id=mandate.id, version=1, is_current=1,
        valid_from=_NOW[:10],
        q_income_points=3, q_obligations_points=2,
        q_savings_points=3, q_wealth_points=3,
        risk_capacity_total=11, risk_capacity_profile="Wachstumsorientiert",
        risk_capacity_score_x10=75,
        investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=4, q_risk_preference_points=3,
        q_risk_behavior_points=2,
        risk_willingness_total=9, risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=70,
        final_score_x10=70, final_profile="Wachstumsorientiert",
        is_overridden=0,
        **CURRENT_RISK_SCHEMA_MARKERS,
        assessed_at=_NOW, assessed_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    add_current_risk_answers(s, aid, _NOW)

    s.flush()
    return mandate, client, advisor


# ---------------------------------------------------------------------------
# Performance-Budget-Tests
# ---------------------------------------------------------------------------

def test_generate_target_allocation_within_time_budget(session_factory):
    """generate_target_allocation() fuer ein realistisch grosses Mandat
    muss innerhalb von BUDGET_GENERATE_S laufen. Grobe 10x-Regressions-
    Bremse, kein Millisekunden-SLA (siehe Modul-Docstring)."""
    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate_for_perf(s)
        s.commit()

        start = time.perf_counter()
        result = generate_target_allocation(s, mandate, advisor.id, preferences=None)
        elapsed = time.perf_counter() - start

    print(f"\n[perf] generate_target_allocation: {elapsed:.4f}s")
    assert result.get("target_allocation") is not None, (
        "generate_target_allocation muss eine target_allocation liefern"
    )
    assert elapsed < BUDGET_GENERATE_S, (
        f"generate_target_allocation() dauerte {elapsed:.3f}s — "
        f"Budget {BUDGET_GENERATE_S}s ueberschritten (moegliche Performance-"
        f"Regression, siehe Roadmap #83)."
    )


def test_compute_advisory_report_within_time_budget(session_factory):
    """compute_advisory_report() fuer dasselbe realistische Mandat muss
    innerhalb von BUDGET_REPORT_S laufen. Grobe 10x-Regressions-Bremse."""
    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate_for_perf(s)
        s.commit()
        # Strategie zuerst laufen lassen, damit der Report eine echte
        # TargetAllocation/Simulation vorfindet (realistischer Pfad).
        generate_target_allocation(s, mandate, advisor.id, preferences=None)
        s.commit()

        start = time.perf_counter()
        report = compute_advisory_report(s, mandate, advisor=advisor)
        elapsed = time.perf_counter() - start

    print(f"\n[perf] compute_advisory_report: {elapsed:.4f}s")
    assert report["schema_version"] == 2
    assert elapsed < BUDGET_REPORT_S, (
        f"compute_advisory_report() dauerte {elapsed:.3f}s — "
        f"Budget {BUDGET_REPORT_S}s ueberschritten (moegliche Performance-"
        f"Regression, siehe Roadmap #83)."
    )


def test_generate_then_report_combined_within_time_budget_and_query_count(session_factory):
    """Kombinierter End-to-End-Pfad (Strategie-Generierung + Report-
    Aggregation fuer dasselbe Mandat) — zweite, orthogonale Dimension
    neben reiner Zeit: SELECT-Query-Anzahl von compute_advisory_report()
    darf nicht explodieren (Muster aus test_aggregator_n1_baseline.py)."""
    with session_factory() as s:
        mandate, _client, advisor = _seed_realistic_mandate_for_perf(s)
        s.commit()

        start = time.perf_counter()
        generate_target_allocation(s, mandate, advisor.id, preferences=None)
        s.commit()

        with _QueryCounter() as counter:
            report = compute_advisory_report(s, mandate, advisor=advisor)
        elapsed = time.perf_counter() - start

    print(f"\n[perf] combined generate+report: {elapsed:.4f}s, queries={counter.count}")
    assert report["schema_version"] == 2
    assert elapsed < BUDGET_COMBINED_S, (
        f"Kombinierter Pfad dauerte {elapsed:.3f}s — "
        f"Budget {BUDGET_COMBINED_S}s ueberschritten."
    )
    # Query-Budget grosszuegig (>= aktueller N+1-Baseline-Test-Budget von 50)
    # gehalten — Ziel hier ist nicht N+1-Feinschliff (das deckt bereits
    # test_aggregator_n1_baseline.py ab), sondern eine 10x-Explosion
    # (z.B. eine neu eingebaute Schleife mit Query pro Item) zu fangen.
    assert counter.count <= 150, (
        f"compute_advisory_report() loeste {counter.count} SELECTs aus "
        f"(Budget 150) — moegliche N+1-Regression, siehe Roadmap #83."
    )
