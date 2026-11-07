"""H7 C-6 (Compliance-Audit 2026-11-07, Luecke 6): Fristen und Zitate.

Befunde an der Basis 2e5dfcc3:
* ``RETENTION_NOTES``/DSG-Export an den Kunden zitierten "OR Art. 962"
  (Rechnungslegungsstandards, nicht Aufbewahrung) und FIDLEG-Artikel als
  Aufbewahrungsnorm.
* ``advisory_log.retain_until = entry_datetime + 10 Jahre`` statt ab
  Mandats-/Beziehungsende.
* Aufbewahrungsmatrix leer, ohne gesetzliche Vorlage.
* Code-Kommentare "FINMA-RS 2016/7 Sorgfaltspflichten" (RS 2016/7 betrifft
  Video-/Online-Identifizierung).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, migrate_advisory_log_retention_from_mandate_end
from services import privacy_erasure as pe
from services import privacy_erasure_inventory as inv
from services.advisory_log_integrity import (
    compute_relationship_retain_until,
    extended_retain_until,
)
from services.data_export import RETENTION_NOTES

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WRONG_FIDLEG_RETENTION = re.compile(r"FIDLEG Art\. (6|9|11|17|19|21)\b")


# ---------------------------------------------------------------- Zitate

def test_retention_notes_cite_correct_norms():
    joined = " ".join(RETENTION_NOTES.values())
    assert "962" not in joined
    assert not WRONG_FIDLEG_RETENTION.search(joined), joined
    assert "OR Art. 958f" in joined
    assert "GwG Art. 7 Abs. 3" in RETENTION_NOTES["clients"]
    assert "Art. 15 FIDLEG" in RETENTION_NOTES["advisory_log"]
    for key in ("advisory_log", "risk_assessments", "contract_documents", "clients", "mandates"):
        assert "Ende" in RETENTION_NOTES[key], key  # Fristbeginn = Beziehungs-/Mandatsende


def test_export_legal_basis_cites_958f_not_962():
    source = (BACKEND_ROOT / "services" / "data_export.py").read_text(encoding="utf-8")
    block = source[source.index('"supplementary": ['):source.index('"format":')]
    assert "962" not in block
    assert "OR Art. 958f" in block
    assert "FIDLEG Art. 15" in block
    assert "FIDLEG Art. 11 (Dokumentationspflicht)" not in block


@pytest.mark.parametrize("rel", [
    "models/clients.py", "routers/clients.py", "services/advisory_log_integrity.py",
    "services/client_erasure.py",
])
def test_no_wrong_circular_or_article_citations_in_code(rel):
    source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
    assert "2016/7" not in source
    assert "FIDLEG Art. 17" not in source
    assert "OR Art. 962 (kaufmaennische" not in source


# ---------------------------------------------------------------- retain_until-Regel

def test_open_mandate_has_no_running_retention_period():
    assert compute_relationship_retain_until("2026-05-28T14:00:00Z", None) is None
    assert compute_relationship_retain_until("2026-05-28T14:00:00Z", "  ") is None


def test_closed_mandate_retention_runs_from_mandate_end():
    assert compute_relationship_retain_until("2020-03-01T10:00:00Z", "2026-11-30") == "2036-11-30"


def test_entry_after_mandate_end_is_never_shorter_than_entry_plus_ten_years():
    assert compute_relationship_retain_until("2027-06-01T10:00:00Z", "2026-11-30") == "2037-06-01"


def test_extension_is_never_shortening():
    # bestehende, spaetere Frist bleibt
    assert extended_retain_until("2040-01-01", "2020-01-01T00:00:00Z", "2026-01-01") == "2040-01-01"
    # bestehende, fruehere Frist wird verlaengert
    assert extended_retain_until("2030-01-01", "2020-01-01T00:00:00Z", "2026-01-01") == "2036-01-01"
    # N-884-06: Mandat wieder offen -> bisherige Frist bleibt als Mindestfrist
    assert extended_retain_until("2036-12-31", "2020-01-01T00:00:00Z", None) == "2036-12-31"
    # nie beendetes Mandat bleibt unbefristet
    assert extended_retain_until(None, "2020-01-01T00:00:00Z", None) is None
    # Wiedereroeffnen und frueheres Ende: nie kuerzer als vor dem Wiedereroeffnen
    kept = extended_retain_until("2036-12-31", "2020-01-01T00:00:00Z", None)
    assert extended_retain_until(kept, "2020-01-01T00:00:00Z", "2026-01-15") == "2036-12-31"
    # unlesbarer Altwert des Eintrags verhindert die Berechnung nicht
    assert extended_retain_until(None, "kaputt", "2026-01-01") == "2036-01-01"


# ---------------------------------------------------------------- Bestandsmigration (SQLite)

@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'c6.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE mandates (id TEXT PRIMARY KEY, closed_at TEXT)"))
        conn.execute(text(
            "CREATE TABLE advisory_log (id TEXT PRIMARY KEY, mandate_id TEXT, "
            "entry_datetime TEXT, retain_until TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO mandates VALUES ('open', NULL), ('closed', '2026-11-30'), ('bad', 'irgendwann')"
        ))
        conn.execute(text(
            "INSERT INTO advisory_log VALUES "
            "('a-open', 'open', '2020-01-01T10:00:00Z', '2030-01-01'),"
            "('a-closed', 'closed', '2020-01-01T10:00:00Z', '2030-01-01'),"
            "('a-later', 'closed', '2020-01-01T10:00:00Z', '2045-05-05'),"
            "('a-bad', 'bad', '2020-01-01T10:00:00Z', '2030-01-01'),"
            "('a-orphan', 'gone', '2020-01-01T10:00:00Z', '2030-01-01'),"
            "('a-reopened', 'open', '2020-01-01T10:00:00Z', '2036-12-31'),"
            "('a-leap', 'open', '2024-02-29T10:00:00Z', '2034-02-28')"
        ))
    yield eng
    eng.dispose()


def _retain(eng):
    with eng.connect() as conn:
        return dict(conn.execute(text("SELECT id, retain_until FROM advisory_log")).all())


def test_sqlite_inventory_migration_moves_retention_to_mandate_end(engine):
    changed = migrate_advisory_log_retention_from_mandate_end(engine)
    values = _retain(engine)
    assert values["a-open"] is None            # Mandat offen: Altfrist entfaellt
    assert values["a-reopened"] == "2036-12-31"  # N-884-06: Mindestfrist bleibt
    assert values["a-leap"] is None            # Altfrist 29.02. -> 28.02. erkannt
    assert values["a-closed"] == "2036-11-30"  # Mandatsende + 10 J.
    assert values["a-later"] == "2045-05-05"   # nie verkuerzend
    assert values["a-bad"] is None             # unlesbares Ende: nicht befristet
    assert values["a-orphan"] == "2030-01-01"  # ohne Mandat unveraendert
    assert changed == 4
    # idempotent
    assert migrate_advisory_log_retention_from_mandate_end(engine) == 0
    assert _retain(engine) == values


def test_alembic_migration_rule_matches_runtime_rule():
    import importlib.util

    path = BACKEND_ROOT / "alembic" / "versions" / "e1c6a7d4b2f9_advisory_log_retain_until_from_mandate_end.py"
    spec = importlib.util.spec_from_file_location("mig_e1c6", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # offenes Mandat: Altfrist (Eintrag + 10 J.) -> NULL, sonst bleibt die Frist
    assert module._target("2030-01-01", "2020-01-01T10:00:00Z", None) is None
    assert module._target("2034-02-28", "2024-02-29T10:00:00Z", None) is None
    assert module._target("2036-12-31", "2020-01-01T10:00:00Z", None) == "2036-12-31"
    assert module._target(None, "2020-01-01T10:00:00Z", None) is None
    cases = [
        ("2030-01-01", "2020-01-01T10:00:00Z", "2026-11-30"),
        ("2045-05-05", "2020-01-01T10:00:00Z", "2026-11-30"),
        (None, "kaputt", "2026-01-01"),
        ("2030-01-01", "2024-02-29T00:00:00Z", "2020-01-01"),
    ]
    for current, entry, end in cases:
        assert module._target(current, entry, end) == extended_retain_until(current, entry, end), (current, entry, end)
    assert module.down_revision == "d3b7f1a5c9e2"


# ---------------------------------------------------------------- Aufbewahrungsmatrix-Vorlage

@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'c6_privacy.db'}")
    Base.metadata.create_all(bind=eng)
    factory = sessionmaker(bind=eng, expire_on_commit=False)
    with factory() as s:
        pe.ensure_privacy_tables(s)
        yield s
    eng.dispose()


def test_baseline_covers_every_evidence_type_with_sound_legal_basis():
    assert set(pe.RETENTION_BASELINE) == set(inv.EVIDENCE_TYPES)
    for evidence_type, row in pe.RETENTION_BASELINE.items():
        assert row["legal_basis"] and "962" not in row["legal_basis"], evidence_type
        assert row["purpose"], evidence_type
        if row["disposition"] == inv.RETAIN_RESTRICTED:
            assert row["retention_trigger"] == "RELATIONSHIP_END", evidence_type
            assert row["retention_months"] >= 120, evidence_type
    assert "GwG Art. 7 Abs. 3" in pe.RETENTION_BASELINE["kyc_due_diligence"]["legal_basis"]
    assert "OR Art. 958f" in pe.RETENTION_BASELINE["mandate_contract"]["legal_basis"]


def test_baseline_proposes_but_never_approves(session):
    created = pe.propose_retention_baseline(session, tenant_id="t1", proposed_by="admin-a")
    assert {p.evidence_type for p in created} == set(inv.EVIDENCE_TYPES)
    assert all(p.status == "PROPOSED" for p in created)
    # Ohne Betreiberangaben nicht genehmigungsfaehig (keine erfundenen Werte).
    kyc = next(p for p in created if p.evidence_type == "kyc_due_diligence")
    problems = pe.policy_approval_problems(kyc)
    assert any("controller" in problem for problem in problems)
    assert json.loads(kyc.matrix_json)["purpose"] == "Nachweis der Sorgfaltspflichten nach GwG"
    # zweiter Aufruf legt nichts doppelt an
    assert pe.propose_retention_baseline(session, tenant_id="t1", proposed_by="admin-a") == []


def test_baseline_with_operator_values_is_approvable(session):
    operator = {key: f"Betreiberangabe {key}" for key in pe.REQUIRED_MATRIX_KEYS}
    created = pe.propose_retention_baseline(
        session, tenant_id="t2", proposed_by="admin-a", operator_matrix=operator,
    )
    for policy in created:
        assert pe.policy_approval_problems(policy) == [], policy.evidence_type
        if policy.evidence_type != "client_portal_account":
            assert policy.retention_months >= 120


def test_baseline_endpoint_is_admin_only_and_returns_proposals():
    from main import app

    route = next(
        r for r in app.routes
        if getattr(r, "path", "") == "/privacy/policies/baseline" and "POST" in getattr(r, "methods", set())
    )
    assert route.status_code == 201


# ---------------------------------------------------------------- Laufzeit: Protokoll + Mandatsende

from test_advisory_log_endpoints import (  # noqa: E402,F401
    _valid_payload,
    http_client,
    session_factory as advisory_session_factory,
)


@pytest.fixture()
def session_factory(advisory_session_factory):
    return advisory_session_factory


def _retain_until(session, entry_id):
    session.expire_all()
    return session.execute(
        text("SELECT retain_until FROM advisory_log WHERE id = :id"), {"id": entry_id},
    ).scalar()


def test_advisory_log_retention_follows_mandate_end(http_client):
    client, _advisor, mandate, session = http_client
    created = client.post(f"/mandates/{mandate.id}/advisory-log", json=_valid_payload())
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    # Basis: "2036-05-28" (Eintrag + 10 J.) -- jetzt laeuft die Frist erst ab Mandatsende.
    assert created.json()["retain_until"] is None

    closed = client.put(f"/mandates/{mandate.id}", json={"closed_at": "2026-12-31"})
    assert closed.status_code == 200, closed.text
    assert _retain_until(session, entry_id) == "2036-12-31"

    reopened = client.put(f"/mandates/{mandate.id}", json={"closed_at": None})
    assert reopened.status_code == 200, reopened.text
    # N-884-06: Wiedereroeffnen verwirft die bisherige Frist nicht.
    assert _retain_until(session, entry_id) == "2036-12-31"

    client.put(f"/mandates/{mandate.id}", json={"closed_at": "2026-01-15"})
    # frueheres Ende nach Wiedereroeffnung: nie kuerzer als zuvor
    assert _retain_until(session, entry_id) == "2036-12-31"
