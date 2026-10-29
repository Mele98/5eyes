"""Query-Budgets (N+1-Wache) fuer die meistgenutzten Lese-Endpunkte.

Ergaenzt ``test_aggregator_n1_baseline.py`` (Report-Aggregator) und den
Query-Anteil von ``test_performance_budget.py`` um die Listen-Endpunkte der
Beratungsmasken: Kundenliste, Mandate, Vermoegen, Cashflows, Ziele,
Dokumente, Beratungsprotokoll, Review-Trigger, Risikoprofile,
Eignungspruefungen, Audit-Log und Produktuniversum.

Methode
-------
Je Endpunkt werden zwei frische SQLite-Datenbanken befuellt: einmal mit 1,
einmal mit N=10 Datensaetzen der gelisteten Art. Gezaehlt werden die SELECTs
waehrend genau EINES Requests, und zwar nur auf der Test-Engine (nicht
prozessweit auf ``Engine``) -- Hintergrund-Threads anderer Engines koennen das
Ergebnis so nicht verfaelschen.

Invarianten
-----------
1. Die Anzahl SELECTs ist konstant in N (kein N+1).
2. Sie liegt nicht ueber dem Budget, das exakt auf den gemessenen Wert
   gesetzt ist (kein Puffer). Wer eine Query ergaenzt, muss das Budget hier
   bewusst und begruendet anpassen.
3. Die Antwort enthaelt alle N Datensaetze (das Budget wird nicht durch eine
   leere oder abgeschnittene Antwort erreicht).

Bei einer Verletzung zeigt die Fehlermeldung die komplette SQL-Liste.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment, SuitabilityCheck  # noqa: E402
from models.review import (  # noqa: E402
    AdvisoryLog,
    AuditLog,
    ContractDocument,
    Product,
    ReviewTrigger,
)
from models.users import User  # noqa: E402
from models.wealth import Cashflow, Goal, WealthPosition  # noqa: E402
from services.auth import get_current_user, require_admin, require_advisor  # noqa: E402

_NOW = "2026-10-26T08:00:00.000Z"
_N = 10

_ADMIN_ID = "qb-admin"
_CLIENT_ID = "qb-client"
_MANDATE_ID = "qb-mandate"


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------

class _SelectCounter:
    """Zaehlt SELECTs auf genau einer Engine (Muster aus
    test_aggregator_n1_baseline.py, aber engine-gebunden)."""

    def __init__(self, engine) -> None:
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self) -> "_SelectCounter":
        event.listen(self._engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(self._engine, "before_cursor_execute", self._before)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            self.statements.append(" ".join(statement.split()))

    @property
    def count(self) -> int:
        return len(self.statements)

    def dump(self) -> str:
        return "\n".join(f"  {i + 1:>2}. {s}" for i, s in enumerate(self.statements))


def _admin_user() -> User:
    return User(
        id=_ADMIN_ID,
        username="qb-admin",
        password_hash="h",
        full_name="Query Budget Admin",
        role="admin",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _seed_base(s: Session) -> None:
    s.add(_admin_user())
    s.add(Client(
        id=_CLIENT_ID,
        client_number="QB-0000",
        first_name="Erika",
        last_name="Beispiel",
        date_of_birth="1970-01-01",
        advisor_id=_ADMIN_ID,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.add(Mandate(
        id=_MANDATE_ID,
        client_id=_CLIENT_ID,
        mandate_number="QB-M-0000",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        retirement_year=2035,
        created_at=_NOW,
        updated_at=_NOW,
    ))


def _seed_clients(s: Session, n: int) -> None:
    # Der Basis-Kunde zaehlt mit; es kommen n-1 weitere dazu.
    for i in range(1, n):
        s.add(Client(
            id=f"qb-client-{i}",
            client_number=f"QB-{i:04d}",
            first_name=f"Vorname{i}",
            last_name=f"Nachname{i}",
            date_of_birth="1975-06-15",
            advisor_id=_ADMIN_ID,
            country_of_residence="CH",
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_mandates(s: Session, n: int) -> None:
    for i in range(1, n):
        s.add(Mandate(
            id=f"qb-mandate-{i}",
            client_id=_CLIENT_ID,
            mandate_number=f"QB-M-{i:04d}",
            mandate_type="Anlageberatung",
            opened_at=_NOW,
            retirement_year=2035,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_wealth_positions(s: Session, n: int) -> None:
    for i in range(n):
        s.add(WealthPosition(
            id=f"qb-wp-{i}",
            client_id=_CLIENT_ID,
            position_type="Bankkonto",
            label=f"Konto {i}",
            current_value_rappen=1_000_000 + i,
            currency="CHF",
            assignment="Beratungsvermögen",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_cashflows(s: Session, n: int) -> None:
    for i in range(n):
        s.add(Cashflow(
            id=f"qb-cf-{i}",
            client_id=_CLIENT_ID,
            cashflow_type="Expense",
            label=f"Ausgabe {i:02d}",
            amount_rappen=100_000 + i,
            frequency="monatlich",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_goals(s: Session, n: int) -> None:
    for i in range(n):
        s.add(Goal(
            id=f"qb-goal-{i}",
            mandate_id=_MANDATE_ID,
            client_id=_CLIENT_ID,
            goal_family="Vermoegensaufbau",
            goal_type="Vermoegensziel",
            label=f"Ziel {i}",
            target_amount_rappen=5_000_000,
            target_date="2040-12-31",
            hardness="Primaer",
            rank=i + 1,
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_documents(s: Session, n: int) -> None:
    for i in range(n):
        s.add(ContractDocument(
            id=f"qb-doc-{i}",
            mandate_id=_MANDATE_ID,
            document_type="Beratungsprotokoll",
            title=f"Dokument {i}",
            created_by=_ADMIN_ID,
            created_at=f"2026-10-{i + 1:02d}T08:00:00.000Z",
            updated_at=_NOW,
        ))


def _seed_advisory_log(s: Session, n: int) -> None:
    for i in range(n):
        s.add(AdvisoryLog(
            id=f"qb-log-{i}",
            mandate_id=_MANDATE_ID,
            entry_type="Beratungsgespraech",
            title=f"Eintrag {i}",
            advisor_id=_ADMIN_ID,
            entry_date=f"2026-10-{i + 1:02d}",
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_triggers(s: Session, n: int) -> None:
    for i in range(n):
        s.add(ReviewTrigger(
            id=f"qb-trg-{i}",
            mandate_id=_MANDATE_ID,
            trigger_type="Periodisch",
            trigger_name=f"Review {i}",
            next_due_at=f"2027-{(i % 12) + 1:02d}-01",
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_risk_assessments(s: Session, n: int) -> None:
    for i in range(n):
        s.add(RiskAssessment(
            id=f"qb-ra-{i}",
            mandate_id=_MANDATE_ID,
            version=i + 1,
            is_current=1 if i == n - 1 else 0,
            valid_from=_NOW,
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
            assessed_at=f"2026-10-{i + 1:02d}T08:00:00.000Z",
            assessed_by=_ADMIN_ID,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_suitability_checks(s: Session, n: int) -> None:
    for i in range(n):
        s.add(SuitabilityCheck(
            id=f"qb-sc-{i}",
            mandate_id=_MANDATE_ID,
            client_id=_CLIENT_ID,
            duty_type="Eignungspruefung",
            result="Geeignet",
            checked_by=_ADMIN_ID,
            checked_at=f"2026-10-{i + 1:02d}T08:00:00.000Z",
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _seed_audit_log(s: Session, n: int) -> None:
    for i in range(n):
        s.add(AuditLog(
            id=f"qb-audit-{i}",
            user_id=_ADMIN_ID,
            user_name="Query Budget Admin",
            table_name="clients",
            record_id=_CLIENT_ID,
            action="UPDATE",
            client_id=_CLIENT_ID,
            created_at=f"2026-10-{i + 1:02d}T08:00:00.000Z",
        ))


def _seed_products(s: Session, n: int) -> None:
    for i in range(n):
        s.add(Product(
            id=f"qb-prod-{i}",
            isin=f"CH{i:010d}",
            product_name=f"Produkt {i:02d}",
            product_type="ETF",
            asset_class="Aktien",
            sub_asset_class="Aktien Schweiz",
            currency="CHF",
            ter_bps=20,
            provider="Anbieter",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        ))


def _len_list(body) -> int:
    return len(body)


def _len_audit_page(body) -> int:
    return len(body["entries"])


@dataclass(frozen=True)
class _Case:
    name: str
    path: str
    seed: Callable[[Session, int], None]
    budget: int
    size: Callable[[object], int] = _len_list


# Budgets: exakt gemessen (SQLite, 2026-10-26), konstant fuer N=1 und N=10.
CASES: tuple[_Case, ...] = (
    _Case("clients_list", "/clients", _seed_clients, budget=1),
    _Case("client_mandates", f"/clients/{_CLIENT_ID}/mandates", _seed_mandates, budget=2),
    _Case("wealth_positions", f"/clients/{_CLIENT_ID}/wealth-positions", _seed_wealth_positions, budget=2),
    _Case("cashflows", f"/clients/{_CLIENT_ID}/cashflows", _seed_cashflows, budget=2),
    _Case("goals", f"/mandates/{_MANDATE_ID}/goals", _seed_goals, budget=2),
    _Case("documents", f"/mandates/{_MANDATE_ID}/documents", _seed_documents, budget=3),
    _Case("advisory_log", f"/mandates/{_MANDATE_ID}/advisory-log", _seed_advisory_log, budget=2),
    _Case("review_triggers", f"/mandates/{_MANDATE_ID}/triggers", _seed_triggers, budget=2),
    # PRIVACY-001: +1 SELECT fuer das Sperrarchiv-Gate (gesperrte Risiko-Evidenz).
    _Case("risk_assessments", f"/mandates/{_MANDATE_ID}/risk-assessments", _seed_risk_assessments, budget=4),
    _Case("suitability_checks", f"/mandates/{_MANDATE_ID}/suitability-checks", _seed_suitability_checks, budget=2),
    _Case("audit_log", "/admin/system/audit-log", _seed_audit_log, budget=2, size=_len_audit_page),
    _Case("products", "/products", _seed_products, budget=1),
)


@contextmanager
def _api_on_fresh_db(tmp_path: Path, label: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / f'{label}.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with SF() as session:
            yield session

    user = _admin_user()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_advisor] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    try:
        yield engine, SF, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _measure(tmp_path: Path, case: _Case, n: int):
    with _api_on_fresh_db(tmp_path, f"{case.name}_{n}") as (engine, SF, client):
        with SF() as s:
            _seed_base(s)
            case.seed(s, n)
            s.commit()
        with _SelectCounter(engine) as counter:
            response = client.get(case.path)
    assert response.status_code == 200, f"{case.path}: {response.status_code} {response.text[:500]}"
    return counter, response.json()


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_read_endpoint_query_count_is_constant_and_within_budget(tmp_path, case):
    one, body_one = _measure(tmp_path, case, 1)
    many, body_many = _measure(tmp_path, case, _N)

    assert case.size(body_one) == 1, f"{case.path}: erwartet 1 Datensatz, erhalten {case.size(body_one)}"
    assert case.size(body_many) == _N, f"{case.path}: erwartet {_N} Datensaetze, erhalten {case.size(body_many)}"

    assert many.count == one.count, (
        f"{case.path}: N+1 -- {one.count} SELECTs bei 1 Datensatz, {many.count} bei {_N}.\n"
        f"SQL bei N={_N}:\n{many.dump()}"
    )
    assert many.count <= case.budget, (
        f"{case.path}: {many.count} SELECTs, Budget {case.budget}.\nSQL:\n{many.dump()}"
    )
