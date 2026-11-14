"""E2a Nachhaltigkeitspraeferenzen im Risikoprofil-Flow (Dok. 106, Codex-
Vertrag E2 2026-11-08): Datenmodell InvestmentPreferenceDecisionV1 und API.

Uebernommen aus E1-E3 (#888, superseded) und neu geprueft; angepasst an die
Owner-Vorgaben 2026-11-08:

* versioniert je Mandat, append-only (Trigger), Supersession ueber
  sequence_no/supersedes_id, optimistische Sperre (expected_current_id);
* Pflichtzustaende getrennt: nicht erfasst / keine Praeferenz / keine
  Angabe / Praeferenz / dokumentierter Verzicht / veraltet;
* Frage 1 zuerst, Folgefragen nur bei "Ja" (Kenntnisnahme nur dort);
* Kanal, Fragebogen-Version, Definitions-Hash und Review-Policy-Version im
  Nachweis (veraltete Maske -> 409);
* Verzicht nur Anlageberatung, mit Begruendung (versiegelt);
* Ausschlusswuensche nur, wenn anbietbar (E2a: nie, 422 fail-closed);
* Review-Frist = Hauspolitik je Tenant (Default 36 Monate);
* Audit-Eintrag, Decision-Hash reproduzierbar.
"""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text

from core import sustainability_preference as sp
from core.evidence import evidence_hash
from models.profiling import InvestmentPreferenceDecision
from services.pii_vault import is_sealed, reveal
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)

WAIVER_REASON = "Kundin wünscht die Empfehlung trotz fehlendem Abgleich der Präferenz."


def _payload(**overrides) -> dict:
    body = {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION,
        "definition_hash": sp.definition_hash(),
        "response_status": "answered",
        "esg_relevance": "yes",
        "esg_characteristic": "esg_factors",
        "exclusions": [],
        "information_acknowledged": True,
        "client_confirmed": True,
        "capture_channel": "in_person",
    }
    body.update(overrides)
    return body


NOT_RELEVANT = {"esg_relevance": "not_relevant", "esg_characteristic": None, "information_acknowledged": False}
DECLINED = {"response_status": "declined", "esg_relevance": None, "esg_characteristic": None,
            "information_acknowledged": False}


def _post(client, mandate_id, **overrides):
    return client.post(f"/mandates/{mandate_id}/sustainability-preferences", json=_payload(**overrides))


def _reason(resp):
    detail = resp.json().get("detail")
    return detail.get("reason_code") if isinstance(detail, dict) else None


def _set_mandate_type(session_factory, mandate_id, mandate_type):
    with session_factory() as s:
        s.execute(text("UPDATE mandates SET mandate_type = :t WHERE id = :id"), {"t": mandate_type, "id": mandate_id})
        s.commit()


# ── Ableitung (Leaf) ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,relevance,characteristic,expected", [
    ("declined", None, None, "declined"),
    ("answered", "not_relevant", None, "no_preference"),
    ("answered", "yes", "sdg_alignment", "sdg_goals"),
    ("answered", "yes", "esg_factors", "esg_factors"),
    ("answered", "yes", "no_specific", "unspecified"),
])
def test_profile_derivation_is_neutral_code(status, relevance, characteristic, expected):
    assert sp.derive_profile(status, relevance, characteristic) == expected
    assert expected in sp.PROFILE_CODES


@pytest.mark.parametrize("status,relevance,characteristic", [
    ("declined", "yes", None),
    ("answered", None, None),
    ("answered", "yes", None),
    ("answered", "not_relevant", "esg_factors"),
    ("unanswered", None, None),
])
def test_contradictory_answers_are_rejected(status, relevance, characteristic):
    with pytest.raises(ValueError):
        sp.derive_profile(status, relevance, characteristic)


def test_definition_hash_is_stable_and_binds_the_texts(monkeypatch):
    first = sp.definition_hash()
    assert first == sp.definition_hash() and len(first) == 64
    monkeypatch.setitem(sp.PROFILE_TEXTS, sp.PROFILE_SDG_GOALS, "geaendert")
    assert sp.definition_hash() != first


@pytest.mark.parametrize("start,months,expected", [
    ("2026-11-07", 36, "2029-11-07"),
    ("2026-01-31", 1, "2026-02-28"),
    ("2027-12-31", 2, "2028-02-29"),
    ("2026-11-07", 6, "2027-05-07"),
])
def test_add_months_clamps_month_end(start, months, expected):
    assert sp.add_months_iso(start, months) == expected


@pytest.mark.parametrize("value,expected", [(None, 36), (24, 24), (3, 36), (121, 36), (True, 36), ("24", 36)])
def test_review_months_default_is_house_policy(value, expected):
    assert sp.resolve_review_months(value) == expected
    assert "Hauspolitik" in sp.review_policy_label(expected)
    assert "keine gesetzliche Frist" in sp.review_policy_label(expected)


def test_states_are_distinct_and_labelled():
    assert len(set(sp.STATES)) == len(sp.STATES) == 7
    assert set(sp.STATE_LABELS) == set(sp.STATES)
    assert len(set(sp.STATE_LABELS.values())) == len(sp.STATES)
    assert sp.base_state(None) == sp.STATE_UNANSWERED
    assert sp.base_state({"response_status": "declined"}) == sp.STATE_DECLINED
    assert sp.base_state({"response_status": "answered", "esg_relevance": "not_relevant"}) == sp.STATE_NO_PREFERENCE
    assert sp.base_state({"response_status": "answered", "esg_relevance": "yes"}) == sp.STATE_PREFERENCE
    assert sp.base_state({"response_status": "answered", "esg_relevance": "yes",
                          "preference_waived": 1}) == sp.STATE_WAIVER


# ── API ───────────────────────────────────────────────────────────────────────

def test_state_without_capture_is_unanswered(client, mandate_id):
    resp = client.get(f"/mandates/{mandate_id}/sustainability-preferences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current"] is None and body["history"] == []
    assert body["state"] == "unanswered" and body["state"] != "no_preference"
    assert body["state_label"] == "Noch nicht erfasst"
    assert body["review_status"] == "missing"
    assert body["review_policy_months"] == 36
    assert body["waiver_allowed"] is True
    assert body["document_binding"] == sp.NO_DECISION_BINDING_PREFIX + mandate_id
    assert [o["key"] for o in body["exclusion_options"]] == list(sp.EXCLUSION_KEYS)
    assert not any(o["available"] for o in body["exclusion_options"])
    assert all(o["reason"] for o in body["exclusion_options"])


def test_definition_endpoint_returns_version_and_hash(client):
    resp = client.get("/sustainability-preferences/definition")
    assert resp.status_code == 200
    body = resp.json()
    assert body["questionnaire_version"] == sp.QUESTIONNAIRE_VERSION
    assert body["definition_hash"] == sp.definition_hash()
    assert [q["number"] for q in body["questions"]] == [1, 2, 3, 4]
    assert [q.get("only_if") for q in body["questions"][1:]] == [{"esg_relevance": "yes"}] * 3
    assert body["questions"][0]["declined_label"] == "Keine Angabe"
    assert body["display_text_status"] == sp.DISPLAY_TEXT_STATUS
    assert set(body["capture_channels"]) == {"in_person", "phone", "video", "written"}


def test_create_persists_version_hash_channel_and_audit(client, mandate_id, session_factory, advisor_user):
    resp = _post(client, mandate_id, capture_channel="video")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    current = body["current"]
    assert body["state"] == "preference_stated"
    assert current["sequence_no"] == 1 and current["supersedes_id"] is None
    assert current["profile_code"] == "esg_factors"
    assert current["capture_channel"] == "video"
    assert current["questionnaire_version"] == sp.QUESTIONNAIRE_VERSION
    assert current["definition_hash"] == sp.definition_hash()
    assert current["review_policy_version"] == sp.REVIEW_POLICY_VERSION
    assert current["review_policy_months"] == 36
    assert current["review_due_on"] == sp.add_months_iso(current["captured_at"][:10], 36)
    assert current["captured_by"] == advisor_user.id
    assert current["client_confirmed"] is True and current["information_acknowledged"] is True
    assert current["limit_texts"] == [sp.PROFILE_LIMIT_TEXTS["esg_factors"]]
    assert body["document_binding"] == current["decision_hash"]
    with session_factory() as s:
        row = s.query(InvestmentPreferenceDecision).one()
        columns = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        assert row.decision_hash == evidence_hash(sp.decision_snapshot(columns))
        audit = s.execute(text(
            "SELECT action, mandate_id, new_value FROM audit_log "
            "WHERE table_name = 'investment_preference_decisions'"
        )).all()
    assert [(a, m) for a, m, _ in audit] == [("CREATE", mandate_id)]
    assert '"state": "preference_stated"' in audit[0][2] and current["decision_hash"] in audit[0][2]


def test_new_capture_supersedes_and_needs_expected_current(client, mandate_id):
    first = _post(client, mandate_id).json()["current"]
    conflict = _post(client, mandate_id, **NOT_RELEVANT)
    assert conflict.status_code == 409 and _reason(conflict) == "SUSTAINABILITY_PREFERENCE_CONFLICT"
    second = _post(client, mandate_id, expected_current_id=first["id"], **NOT_RELEVANT)
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["state"] == "no_preference"
    assert body["current"]["sequence_no"] == 2
    assert body["current"]["supersedes_id"] == first["id"]
    assert [h["sequence_no"] for h in body["history"]] == [2, 1]


def test_rows_are_append_only(client, mandate_id, session_factory):
    _post(client, mandate_id)
    with session_factory() as s:
        db_path = s.get_bind().url.database
    conn = sqlite3.connect(db_path)
    try:
        for stmt in ("UPDATE investment_preference_decisions SET profile_code = 'declined'",
                     "DELETE FROM investment_preference_decisions"):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(stmt)
    finally:
        conn.close()


def test_declined_is_separate_from_not_relevant(client, mandate_id):
    declined = _post(client, mandate_id, **DECLINED)
    assert declined.status_code == 201, declined.text
    assert declined.json()["state"] == "declined"
    assert declined.json()["current"]["profile_code"] == "declined"
    not_relevant = _post(client, mandate_id, expected_current_id=declined.json()["current"]["id"], **NOT_RELEVANT)
    assert not_relevant.json()["state"] == "no_preference"


@pytest.mark.parametrize("overrides,code", [
    ({"esg_characteristic": None}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"esg_relevance": "not_relevant"}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"esg_relevance": None, "esg_characteristic": None}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"exclusions": ["weapons"]}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"information_acknowledged": False}, "SUSTAINABILITY_INFORMATION_REQUIRED"),
    ({**NOT_RELEVANT, "information_acknowledged": True}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"preference_waived": True, "waiver_reason": "zu kurz"}, "SUSTAINABILITY_WAIVER_INVALID"),
    ({"waiver_reason": WAIVER_REASON}, "SUSTAINABILITY_WAIVER_INVALID"),
    ({**NOT_RELEVANT, "preference_waived": True, "waiver_reason": WAIVER_REASON}, "SUSTAINABILITY_WAIVER_INVALID"),
    # N-888-03: Kundenbestaetigung ist Pflicht.
    ({"client_confirmed": False}, "SUSTAINABILITY_CONFIRMATION_REQUIRED"),
    # Nur Erfuellbares: in E2a ist kein Ausschluss anbietbar.
    ({"exclusions": ["tobacco"]}, "SUSTAINABILITY_OPTION_NOT_OFFERABLE"),
])
def test_invalid_captures_are_rejected_and_persist_nothing(client, mandate_id, session_factory, overrides, code):
    resp = _post(client, mandate_id, **overrides)
    assert resp.status_code == 422, resp.text
    assert _reason(resp) == code
    with session_factory() as s:
        assert s.query(InvestmentPreferenceDecision).count() == 0


def test_missing_channel_is_a_schema_error(client, mandate_id, session_factory):
    body = _payload()
    body.pop("capture_channel")
    resp = client.post(f"/mandates/{mandate_id}/sustainability-preferences", json=body)
    assert resp.status_code == 422
    with session_factory() as s:
        assert s.query(InvestmentPreferenceDecision).count() == 0


def test_not_offerable_exclusion_message_is_short_with_detail(client, mandate_id):
    resp = _post(client, mandate_id, exclusions=["tobacco", "fossil"])
    detail = resp.json()["detail"]
    assert detail["message"].startswith("Ausschluss nicht wählbar (Fossile Energie, Tabak).")
    assert "Frage 3" in detail["message"]
    assert "Nicht wählbar" in detail["detail"]  # Grund je Thema (E2b: Abdeckung)


def test_outdated_definition_hash_is_rejected(client, mandate_id):
    resp = _post(client, mandate_id, definition_hash="0" * 64)
    assert resp.status_code == 409 and _reason(resp) == "SUSTAINABILITY_DEFINITION_OUTDATED"


def test_waiver_only_in_investment_advice(client, mandate_id, session_factory):
    _set_mandate_type(session_factory, mandate_id, "Vermögensverwaltung")
    resp = _post(client, mandate_id, preference_waived=True, waiver_reason=WAIVER_REASON)
    assert resp.status_code == 409 and _reason(resp) == "SUSTAINABILITY_WAIVER_NOT_ALLOWED"
    state = client.get(f"/mandates/{mandate_id}/sustainability-preferences").json()
    assert state["waiver_allowed"] is False and state["state"] == "unanswered"


def test_waiver_reason_is_sealed_and_state_documented(client, mandate_id, session_factory):
    resp = _post(client, mandate_id, preference_waived=True, waiver_reason=WAIVER_REASON)
    assert resp.status_code == 201, resp.text
    assert resp.json()["state"] == "waiver_documented"
    assert resp.json()["current"]["preference_waived"] is True
    with session_factory() as s:
        row = s.query(InvestmentPreferenceDecision).one()
        assert is_sealed(row.waiver_reason_sealed)
        assert reveal(s, row.waiver_reason_sealed) == WAIVER_REASON


def test_waiver_becomes_stale_when_mandate_leaves_investment_advice(client, mandate_id, session_factory):
    _post(client, mandate_id, preference_waived=True, waiver_reason=WAIVER_REASON)
    _set_mandate_type(session_factory, mandate_id, "Vermögensverwaltung")
    state = client.get(f"/mandates/{mandate_id}/sustainability-preferences").json()
    assert state["state"] == "stale" and state["stale_reasons"] == ["waiver_void"]
    assert state["answer_state"] == "waiver_documented"


def test_tenant_review_policy_and_due_notice(client, mandate_id, session_factory):
    with session_factory() as s:
        s.execute(text(
            "INSERT INTO tenants (id, display_name, slug, hosting_tier, license_status, "
            "sustainability_review_months, kek_version, default_retrocession_reimbursement, "
            "discretionary_management_licensed, is_active, created_at, updated_at) VALUES "
            "('t-e1', 'Tenant E1', 't-e1', 'tier1_self_hosted', 'trial', 24, 1, 0, 1, 1, 'x', 'x')"
        ))
        s.execute(text("UPDATE mandates SET tenant_id = 't-e1' WHERE id = :id"), {"id": mandate_id})
        s.execute(text("UPDATE clients SET tenant_id = 't-e1'"))
        s.commit()
    created = _post(client, mandate_id).json()["current"]
    assert created["review_policy_months"] == 24
    assert created["review_due_on"] == sp.add_months_iso(created["captured_at"][:10], 24)
    assert sp.review_status(created["review_due_on"], created["review_due_on"]) == "current"
    assert sp.review_status(created["review_due_on"], "2999-01-01") == "due"
    assert "Eignungsprüfung fällig" in sp.review_due_text(created["review_due_on"])
    # Policy-Aenderung macht die Erfassung veraltet (Negativfall 4).
    with session_factory() as s:
        s.execute(text("UPDATE tenants SET sustainability_review_months = 12 WHERE id = 't-e1'"))
        s.commit()
    state = client.get(f"/mandates/{mandate_id}/sustainability-preferences").json()
    assert state["state"] == "stale" and "review_policy_changed" in state["stale_reasons"]


# ── Migration: Alembic (einziger Head) + SQLite-Laufzeitpatch ────────────────

def _alembic_cfg(db_url):
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    root = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_alembic_single_head_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1
    assert script.get_revision("f3a8c1e5b7d2").down_revision == "f2a4c6e8b0d1"  # RC-CH-1 I-03: hinter H10
    db_url = f"sqlite:///{tmp_path / 'alembic.db'}"
    cfg = _alembic_cfg(db_url)

    def _assert_upgraded():
        engine = create_engine(db_url)
        insp = inspect(engine)
        assert "investment_preference_decisions" in insp.get_table_names()
        assert "sustainability_review_months" in {c["name"] for c in insp.get_columns("tenants")}
        assert "bound_preference_decision_hash" in {c["name"] for c in insp.get_columns("contract_documents")}
        assert "sustainability_evidence_json" in {c["name"] for c in insp.get_columns("recommendation_runs")}
        cols = {c["name"] for c in insp.get_columns("investment_preference_decisions")}
        assert {"preference_waived", "waiver_reason_sealed", "capture_channel", "review_policy_version"} <= cols
        with engine.connect() as conn:
            triggers = {r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='investment_preference_decisions'"
            ))}
        assert {"trg_investment_preference_decisions_no_update",
                "trg_investment_preference_decisions_no_delete",
                "trg_investment_preference_decisions_tenant_guard"} <= triggers
        engine.dispose()

    command.upgrade(cfg, "head")
    _assert_upgraded()
    command.downgrade(cfg, "f2a4c6e8b0d1")
    engine = create_engine(db_url)
    insp = inspect(engine)
    assert "investment_preference_decisions" not in insp.get_table_names()
    assert "bound_preference_decision_hash" not in {c["name"] for c in insp.get_columns("contract_documents")}
    assert "sustainability_review_months" not in {c["name"] for c in insp.get_columns("tenants")}
    engine.dispose()
    command.upgrade(cfg, "head")
    _assert_upgraded()


def test_orm_bootstrap_and_runtime_patch_have_the_same_columns(tmp_path, monkeypatch):
    from pathlib import Path

    from sqlalchemy import create_engine

    import database as db_module

    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=root / "ares_schema.sql")
    with sqlite3.connect(str(db_path)) as conn:
        boot_cols = [r[1] for r in conn.execute("PRAGMA table_info(investment_preference_decisions)")]
        conn.execute("DROP TABLE investment_preference_decisions")
        conn.commit()
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(str(db_path)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        patch_cols = [r[1] for r in conn.execute("PRAGMA table_info(investment_preference_decisions)")]
        doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(contract_documents)")}
    assert "trg_investment_preference_decisions_no_update" in names
    orm_cols = [c.name for c in InvestmentPreferenceDecision.__table__.columns]
    assert boot_cols == patch_cols
    assert set(orm_cols) == set(patch_cols)
    assert "bound_preference_decision_hash" in doc_cols
