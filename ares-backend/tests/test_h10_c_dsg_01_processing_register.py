"""H10 C-DSG-01: Verzeichnis der Bearbeitungstaetigkeiten.

* Vollstaendigkeits-Gate: jede Tabelle des Schemas ist einer Bearbeitung
  zugeordnet oder begruendet ohne Personendaten gefuehrt; Tabellen des
  Loeschinventars sind mit ihren Nachweisarten abgedeckt; TOM-Nachweise
  existieren. Positivkontrollen belegen, dass das Gate rot wird.
* Owner-Angaben sind nie vorbelegt; offene Pflichtfelder sperren die
  kundenwirksame Ausgabe; Aenderungen sind versioniert, auditiert und
  mandantengetrennt; nur Administration darf lesen/schreiben.
"""
from __future__ import annotations

import copy
import json

from sqlalchemy import Column, MetaData, String, Table, text

from database import Base
from services import processing_activity_register as reg
from services.postgres_rls import import_tenant_models
from tests.h10_support import ADMIN_ID, OTHER_TENANT, api, confirm_all_owner_fields, reason, sample_value, user

import_tenant_models()


def test_register_covers_every_table_of_the_schema():
    assert reg.register_problems(Base.metadata.tables) == []


def test_register_file_is_the_versioned_machine_readable_artifact():
    raw = json.loads(reg.REGISTER_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1 and raw["register_version"]
    for activity in raw["activities"]:
        for key in reg.REQUIRED_ACTIVITY_KEYS:
            assert key in activity, (activity["id"], key)


def test_gate_flags_a_synthetic_table_without_assignment():
    tables = dict(Base.metadata.tables)
    tables["synthetic_personal_notes"] = Table(
        "synthetic_personal_notes", MetaData(), Column("id", String, primary_key=True), Column("client_id", String),
    )
    problems = reg.register_problems(tables)
    assert any("synthetic_personal_notes" in p for p in problems), problems


def test_gate_flags_an_uncovered_evidence_type_and_non_personal_contradiction():
    register = reg.load_register()
    pa04 = next(a for a in register["activities"] if a["id"] == "PA-04")
    pa04["data_categories"].remove("suitability_evidence")
    problems = reg.register_problems(Base.metadata.tables, register)
    assert any("suitability_checks: Nachweisart suitability_evidence" in p for p in problems), problems

    register = reg.load_register()
    pa01 = next(a for a in register["activities"] if a["id"] == "PA-01")
    pa01["tables"].remove("clients")
    register["non_personal_tables"]["clients"] = "falsch"
    problems = reg.register_problems(Base.metadata.tables, register)
    assert any("clients: im Loeschinventar" in p for p in problems), problems


def test_gate_flags_missing_tom_evidence_unknown_categories_and_duplicate_owner_fields():
    register = reg.load_register()
    register["toms"]["TOM-AUDIT-TRAIL"]["evidence"] = ["ares-backend/services/does_not_exist.py"]
    register["activities"][0]["data_categories"].append("erfundene_kategorie")
    register["activities"][1]["retention"]["basis"] = copy.deepcopy(register["activities"][0]["retention"]["basis"])
    problems = reg.register_problems(Base.metadata.tables, register)
    assert any("does_not_exist.py existiert nicht" in p for p in problems)
    assert any("unbekannte Datenkategorie erfundene_kategorie" in p for p in problems)
    assert any("mehrfach definiert" in p for p in problems)


def test_owner_values_are_never_prefilled_in_the_register():
    register = reg.load_register()
    fields = reg.iter_owner_fields(register, source="register")
    keys = {f["key"] for f in fields}
    assert {"controller.name", "controller.address", "controller.privacy_contact"} <= keys
    assert {f"activity.PA-0{i}.retention_basis" for i in range(1, 10)} <= keys

    def walk(node):
        if isinstance(node, dict):
            if reg.OWNER_FIELD in node:
                assert "value" not in node and "status" not in node, node
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(register)


def test_api_register_is_blocked_until_owner_values_are_confirmed(tmp_path):
    with api(tmp_path) as (client, current, factory):
        view = client.get("/privacy/processing-register")
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["complete"] is True and body["problems"] == []
        assert body["customer_output_ready"] is False
        open_keys = {f["key"] for f in body["open_blocking_fields"]}
        assert "controller.name" in open_keys and "activity.PA-01.retention_basis" in open_keys
        controller = body["register"]["controller"]["name"]
        assert controller["status"] == "OPEN" and controller["value"] is None

        confirm_all_owner_fields(client, only_blocking=True)
        body = client.get("/privacy/processing-register").json()
        assert body["open_blocking_fields"] == []
        assert body["customer_output_ready"] is False
        assert body["approval_reason_codes"] == ["PROCESSING_ACTIVITY_MISSING"]
        approve = client.post("/privacy/processing-register/approve", json={})
        assert approve.status_code == 200, approve.text
        body = approve.json()
        assert body["customer_output_ready"] is True and body["approval_reason_codes"] == []
        assert body["register"]["controller"]["name"] == {
            "owner_field": "controller.name", "label": "Verantwortliche Firma (Name)",
            "status": "CONFIRMED", "value": sample_value("controller.name"),
        }

        export = client.get("/privacy/processing-register/export")
        assert export.status_code == 200
        document = export.json()
        assert document["export_kind"] == "ProcessingActivityRegisterExportV1"
        assert len(document["export_sha256"]) == 64 and document["customer_output_ready"] is True
        with factory() as s:
            actions = s.execute(text(
                "SELECT action FROM audit_log WHERE table_name = 'privacy_owner_values' ORDER BY sequence"
            )).scalars().all()
        assert "EXPORT" in actions and actions.count("UPDATE") >= 10


def test_owner_value_changes_are_versioned_validated_and_audited(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        unknown = client.put("/privacy/owner-fields/controller.erfunden", json={"value": "x"})
        assert unknown.status_code == 422 and reason(unknown) == "PRIVACY_OWNER_FIELD_UNKNOWN"
        blank = client.put("/privacy/owner-fields/controller.name", json={"value": "   "})
        assert blank.status_code == 422 and reason(blank) == "PRIVACY_OWNER_VALUE_INVALID"

        first = client.put("/privacy/owner-fields/controller.name", json={"value": "TESTWERT Firma A"}).json()
        second = client.put("/privacy/owner-fields/controller.name", json={"value": "TESTWERT Firma B"}).json()
        assert (first["revision"], second["revision"]) == (1, 2)
        with factory() as s:
            rows = s.execute(text(
                "SELECT revision, status FROM privacy_owner_values WHERE field_key = 'controller.name' "
                "ORDER BY revision"
            )).all()
            audit = s.execute(text(
                "SELECT old_value, new_value FROM audit_log WHERE table_name = 'privacy_owner_values' "
                "AND field_name = 'controller.name' ORDER BY sequence"
            )).all()
        assert [tuple(r) for r in rows] == [(1, "RETIRED"), (2, "CONFIRMED")]
        assert [tuple(a) for a in audit] == [(None, "TESTWERT Firma A"), ("TESTWERT Firma A", "TESTWERT Firma B")]


def test_owner_values_are_tenant_scoped_and_admin_only(tmp_path):
    with api(tmp_path) as (client, current, _factory):
        assert client.put("/privacy/owner-fields/controller.name", json={"value": "TESTWERT A"}).status_code == 200
        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        fields = {f["key"]: f for f in client.get("/privacy/owner-fields").json()}
        assert fields["controller.name"]["status"] == "OPEN"
        current["user"] = user("advisor-1", role="advisor")
        for response in (
            client.get("/privacy/processing-register"),
            client.get("/privacy/processing-register/export"),
            client.get("/privacy/owner-fields"),
            client.put("/privacy/owner-fields/controller.name", json={"value": "TESTWERT X"}),
        ):
            assert response.status_code == 403
        current["user"] = user(ADMIN_ID)
        fields = {f["key"]: f for f in client.get("/privacy/owner-fields").json()}
        assert fields["controller.name"]["value"] == "TESTWERT A"


def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models.privacy import PrivacyOwnerValue
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("e2f7c4a9d1b3", "d66fbf0588e3")
    assert_sqlite_upgrade_downgrade_upgrade(tmp_path, "e2f7c4a9d1b3", {"privacy_owner_values": PrivacyOwnerValue})


def test_alembic_postgres_ddl_creates_owner_values():
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl("d66fbf0588e3", "e2f7c4a9d1b3")
    assert "CREATE TABLE privacy_owner_values" in ddl
    assert "ck_privacy_owner_value_status" in ddl


def test_register_file_is_packaged_with_the_backend():
    script = (reg.REPO_ROOT / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "'config/processing_activities.json'" in script


def test_runtime_view_is_complete_even_if_the_app_has_not_loaded_every_model(tmp_path, monkeypatch):
    """Verhaltensprobe 9051: die App laedt Marktdaten-Modelle erst bei Bedarf;
    die Registeransicht registriert vor der Pruefung alle Modelle."""
    from services import privacy_owner_values

    calls = []
    monkeypatch.setattr(privacy_owner_values, "import_tenant_models", lambda: calls.append(1))
    with api(tmp_path) as (client, _current, _factory):
        assert client.get("/privacy/processing-register").json()["complete"] is True
    assert calls, "Registeransicht muss alle Modelle registrieren"
