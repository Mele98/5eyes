"""RISK-PROFILE-SCHEMA-PARITY-001: Profilbezeichnungen des Scorings vs. CHECK-Listen.

Befund: Das Bootstrap-Schema erlaubte fuer ``risk_assessments.
risk_willingness_profile`` nur 'Sicherheitsorientiert', 'Ausgewogen',
'Wachstumsorientiert', 'Dynamisch'. ``services.risk_scoring.
WILLINGNESS_SCORE_TO_PROFILE`` liefert aber 'Kapitalschutz', 'Defensiv',
'Ausgewogen', 'Wachstumsorientiert', 'Dynamisch', 'Aktien'. Auf einer
frischen Installation (``init_db()`` -> Raw-SQL-Bootstrap mit CHECKs) liess
sich ein Risikoprofil mit Bereitschafts-Summe 3-6 oder 12 deshalb nicht
speichern, und der Router meldete die CHECK-Verletzung faelschlich als
409 "gleichzeitig gespeichert". Tests mit ``Base.metadata.create_all()``
sehen das nie (ORM-Spalten ohne CHECK).

Gepinnt wird:
* frische Installation: Speichern je Bereitschafts-Summe 3..12 -> 201;
* Paritaets-Guard: jede vom Scoring (und vom Override-Schema) erzeugbare
  Profilbezeichnung steht in der CHECK-Liste der frischen DB;
* bestehende DB mit der alten, engen Liste: der Upgrade-Pfad von
  ``init_db()`` erweitert sie verlustfrei, danach Speichern -> 201;
* eine CHECK-Verletzung wird nicht mehr als Concurrency-Konflikt (409)
  gemeldet, sondern als 500 mit eigenem Code.
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
import typing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401,E501
configure_mappers()

from services.risk_scoring import (  # noqa: E402
    CAPACITY_TOTAL_TO_PROFILE,
    SCORE_TO_PROFILE,
    WILLINGNESS_SCORE_TO_PROFILE,
)
from services.sqlite_check_ddl import SupportedCheck, parse_table_ddl  # noqa: E402
from tests.risk_fixture_helpers import noop_lifespan, standard_risk_payload  # noqa: E402

SCHEMA_FILE = next(BACKEND_ROOT.glob("ares_schema.sql"))

OLD_WILLINGNESS_CHECK = (
    "'Sicherheitsorientiert','Ausgewogen','Wachstumsorientiert','Dynamisch'))"
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _init_fresh_install(db_path: Path, monkeypatch):
    """Echter Boot-Pfad einer Erstinstallation (wie main.py -> init_db())."""
    import database as db_module
    from config import settings

    test_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(settings, "db_path", str(db_path))
    # Sicherungen des CHECK-Upgrades nie ins Benutzer-Backupverzeichnis.
    monkeypatch.setattr(settings, "backup_dir", str(db_path.parent / "backups"))
    db_module.init_db()
    # Diese drei Schritte binden ihren Engine-Default beim Import; init_db()
    # ruft sie ohne Argument auf. Fuer die Wegwerf-DB explizit nachziehen.
    db_module.ensure_audit_log_actions(test_engine)
    db_module.ensure_audit_log_indexes(test_engine)
    db_module.ensure_audit_log_triggers(test_engine)
    return test_engine


def _bootstrap_with_narrow_willingness_check(tmp_path: Path, name: str) -> Path:
    """Bootstrap mit der alten, engen Bereitschafts-Liste (Stand vor dem Fix)."""
    import database as db_module

    reference_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    start = reference_sql.index("risk_willingness_profile    TEXT NOT NULL CHECK(")
    end = reference_sql.index("risk_willingness_score_x10", start)
    narrow_sql = (
        reference_sql[:start]
        + "risk_willingness_profile    TEXT NOT NULL CHECK(risk_willingness_profile IN ("
        + OLD_WILLINGNESS_CHECK + ",\n    "
        + reference_sql[end:]
    )
    narrow_schema = tmp_path / f"{name}_schema.sql"
    narrow_schema.write_text(narrow_sql, encoding="utf-8")
    db_path = tmp_path / f"{name}.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=narrow_schema)
    assert _check_lists(db_path, "risk_assessments")["risk_willingness_profile"] == {
        "Sicherheitsorientiert", "Ausgewogen", "Wachstumsorientiert", "Dynamisch",
    }
    return db_path


def _check_lists(db_path: Path, table: str) -> dict[str, set[str]]:
    con = sqlite3.connect(db_path)
    try:
        (ddl,) = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    finally:
        con.close()
    out: dict[str, set[str]] = {}
    for check in parse_table_ddl(ddl).checks:
        if isinstance(check, SupportedCheck):
            out.setdefault(check.column, set()).update(
                lit[1:-1].replace("''", "'") for lit in check.literals
            )
    return out


def _override_literal_values() -> set[str]:
    from schemas.profiling import RiskAssessmentOverride

    annotation = RiskAssessmentOverride.model_fields["override_profile"].annotation
    return set(typing.get_args(annotation))


@pytest.fixture()
def api_factory(monkeypatch):
    from database import get_db
    from main import app
    from models.users import User
    from services.auth import get_current_user

    clients_opened = []

    def _make(test_engine):
        sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=test_engine)
        now = _now()
        user = User(
            id="user-rp-parity", username="rp-parity", password_hash="h",
            full_name="Advisor Parity", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        )
        with sf() as session:
            session.add(user)
            session.commit()

        def override_db():
            with sf() as session:
                yield session

        monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(app)
        client.__enter__()
        clients_opened.append(client)
        return client, user

    yield _make
    from main import app as _app

    for client in clients_opened:
        client.__exit__(None, None, None)
    _app.dependency_overrides.clear()


def _new_mandate(client: TestClient, user, suffix: str) -> str:
    cr = client.post(
        "/clients",
        json={
            "client_number": f"RPP-{suffix}",
            "first_name": "Parity",
            "last_name": f"Tester {suffix}",
            "advisor_id": user.id,
            "household_type": "Einzelperson",
        },
    )
    assert cr.status_code == 201, cr.text
    mr = client.post(
        f"/clients/{cr.json()['id']}/mandates",
        json={"mandate_number": f"RPP-M-{suffix}", "mandate_type": "Anlageberatung"},
    )
    assert mr.status_code == 201, mr.text
    return mr.json()["id"]


def _willingness_indices(total: int) -> tuple[int, int, int]:
    """Antwort-Indizes (0..3 -> 1..4 Punkte) fuer eine Bereitschafts-Summe 3..12."""
    points = [1, 1, 1]
    rest = total - 3
    for i in range(3):
        step = min(3, rest)
        points[i] += step
        rest -= step
    assert rest == 0 and sum(points) == total
    return points[0] - 1, points[1] - 1, points[2] - 1


def _post_with_willingness(client: TestClient, mandate_id: str, total: int):
    goal, pref, behav = _willingness_indices(total)
    return client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json=standard_risk_payload(goal=goal, pref=pref, behav=behav),
    )


def test_fresh_install_check_lists_contain_every_scoring_profile(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_parity.db"
    _init_fresh_install(db_path, monkeypatch)
    checks = _check_lists(db_path, "risk_assessments")

    expected = {
        "risk_capacity_profile": set(CAPACITY_TOTAL_TO_PROFILE.values()),
        "risk_willingness_profile": set(WILLINGNESS_SCORE_TO_PROFILE.values()),
        "final_profile": set(SCORE_TO_PROFILE.values()),
        "override_profile": set(SCORE_TO_PROFILE.values()) | _override_literal_values(),
    }
    missing = {
        column: sorted(values - checks.get(column, set()))
        for column, values in expected.items()
        if not values <= checks.get(column, set())
    }
    assert not missing, f"CHECK-Listen der frischen DB fehlen Scoring-Werte: {missing}"


def test_fresh_install_saves_every_willingness_total(tmp_path, monkeypatch, api_factory):
    db_path = tmp_path / "fresh_save.db"
    test_engine = _init_fresh_install(db_path, monkeypatch)
    client, user = api_factory(test_engine)

    results = {}
    for total in range(3, 13):
        mandate_id = _new_mandate(client, user, str(total))
        response = _post_with_willingness(client, mandate_id, total)
        results[total] = (response.status_code, response.text[:200])
        if response.status_code == 201:
            assert response.json()["risk_willingness_total"] == total
    failed = {t: r for t, r in results.items() if r[0] != 201}
    assert not failed, f"Speichern scheiterte fuer Bereitschafts-Summen: {failed}"


def test_existing_db_with_narrow_willingness_check_is_widened_on_startup(tmp_path, monkeypatch, api_factory):
    """Bestehende Installation mit der alten, engen Liste: init_db() erweitert
    sie ueber den CHECK-Upgrade-Pfad (Vereinigungsmenge, Zeilen bleiben)."""
    db_path = _bootstrap_with_narrow_willingness_check(tmp_path, "existing_narrow")

    test_engine = _init_fresh_install(db_path, monkeypatch)
    widened = _check_lists(db_path, "risk_assessments")["risk_willingness_profile"]
    assert set(WILLINGNESS_SCORE_TO_PROFILE.values()) <= widened
    assert "Sicherheitsorientiert" in widened  # nie ein Wert entfernt

    client, user = api_factory(test_engine)
    mandate_id = _new_mandate(client, user, "old")
    response = _post_with_willingness(client, mandate_id, 3)
    assert response.status_code == 201, response.text


def test_check_violation_is_not_reported_as_concurrent_save(tmp_path, monkeypatch, api_factory):
    """CHECK-Verletzung != Concurrency-Konflikt: kein 409 mehr."""
    import services.sqlite_check_constraint_upgrade as check_upgrade

    db_path = _bootstrap_with_narrow_willingness_check(tmp_path, "narrow_no_upgrade")
    # Upgrade-Pfad gezielt abschalten, damit die enge Liste bestehen bleibt.
    monkeypatch.setattr(check_upgrade, "ensure_sqlite_check_in_lists_current", lambda *a, **k: None)
    test_engine = _init_fresh_install(db_path, monkeypatch)

    client, user = api_factory(test_engine)
    mandate_id = _new_mandate(client, user, "chk")
    response = _post_with_willingness(client, mandate_id, 3)
    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "RISK_PROFILE_CHECK_VIOLATION"
    assert "gleichzeitig" not in detail["message"]
