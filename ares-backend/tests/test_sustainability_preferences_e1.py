"""E1 Nachhaltigkeitspraeferenzen (Dok. 106, Entscheid E0, 2026-11-07).

Datenmodell InvestmentPreferenceDecisionV1 und API:

* versioniert je Mandat, append-only (Trigger), Supersession ueber
  sequence_no/supersedes_id, optimistische Sperre (expected_current_id);
* neutraler Profilcode aus Frage 1/2, getrennte Zustaende answered/declined
  und "nicht erfasst";
* Fragebogen-Version + Definitions-Hash (veraltete Maske -> 409);
* Kenntnisnahme Pflicht, Kundenbestaetigung dokumentiert;
* Kundenverzicht nur Anlageberatung, mit Begruendung (versiegelt) und
  Bestaetigung; harte Ausschluesse gesperrt (Codex F10);
* Review-Frist = Hauspolitik je Tenant (Default 36 Monate), Ablauf ->
  Hinweis "Eignungspruefung faellig", kein Sperren;
* Audit-Eintrag, Decision-Hash reproduzierbar.
"""
from __future__ import annotations

import json
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

WAIVER_REASON = "Kunde akzeptiert Tabak im breiten Fonds nach Besprechung der Alternativen."


def _payload(**overrides) -> dict:
    body = {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION,
        "definition_hash": sp.definition_hash(),
        "response_status": "answered",
        "esg_relevance": "yes",
        "esg_characteristic": "esg_factors",
        "exclusions": ["tobacco", "defense"],
        "information_acknowledged": True,
        "client_confirmed": True,
    }
    body.update(overrides)
    return body


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


# ── API ───────────────────────────────────────────────────────────────────────

def test_state_without_capture_is_missing(client, mandate_id):
    resp = client.get(f"/mandates/{mandate_id}/sustainability-preferences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current"] is None and body["history"] == []
    assert body["review_status"] == "missing"
    assert body["review_policy_months"] == 36
    assert body["hard_exclusions_available"] is False
    assert body["waiver_allowed"] is True


def test_definition_endpoint_returns_version_and_hash(client):
    resp = client.get("/sustainability-preferences/definition")
    assert resp.status_code == 200
    body = resp.json()
    assert body["questionnaire_version"] == sp.QUESTIONNAIRE_VERSION
    assert body["definition_hash"] == sp.definition_hash()
    assert [q["number"] for q in body["questions"]] == [1, 2, 3]
    assert body["display_text_status"] == sp.DISPLAY_TEXT_STATUS


def test_create_persists_version_hash_and_audit(client, mandate_id, session_factory, advisor_user):
    resp = _post(client, mandate_id)
    assert resp.status_code == 201, resp.text
    current = resp.json()["current"]
    assert current["sequence_no"] == 1 and current["supersedes_id"] is None
    assert current["profile_code"] == "esg_factors"
    assert current["exclusions"] == ["defense", "tobacco"]
    assert current["questionnaire_version"] == sp.QUESTIONNAIRE_VERSION
    assert current["definition_hash"] == sp.definition_hash()
    assert current["review_policy_months"] == 36
    assert current["review_due_on"] == sp.add_months_iso(current["captured_at"][:10], 36)
    assert current["captured_by"] == advisor_user.id
    assert current["client_confirmed"] is True
    assert "Nachhaltigkeitspräferenz" in current["profile_text"]
    assert sp.EXCLUSION_LIMIT_TEXT in current["limit_texts"]
    with session_factory() as s:
        row = s.query(InvestmentPreferenceDecision).one()
        columns = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        assert row.decision_hash == evidence_hash(sp.decision_snapshot(columns))
        audit = s.execute(text(
            "SELECT action, mandate_id FROM audit_log WHERE table_name = 'investment_preference_decisions'"
        )).all()
    assert audit == [("CREATE", mandate_id)]


def test_new_capture_supersedes_and_needs_expected_current(client, mandate_id):
    first = _post(client, mandate_id).json()["current"]
    stale = _post(client, mandate_id, esg_relevance="not_relevant", esg_characteristic=None, exclusions=[])
    assert stale.status_code == 409 and _reason(stale) == "SUSTAINABILITY_PREFERENCE_CONFLICT"
    second = _post(client, mandate_id, esg_relevance="not_relevant", esg_characteristic=None,
                   exclusions=[], expected_current_id=first["id"])
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["current"]["sequence_no"] == 2
    assert body["current"]["supersedes_id"] == first["id"]
    assert body["current"]["profile_code"] == "no_preference"
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
    resp = _post(client, mandate_id, response_status="declined", esg_relevance=None,
                 esg_characteristic=None, exclusions=[])
    assert resp.status_code == 201, resp.text
    assert resp.json()["current"]["profile_code"] == "declined"


@pytest.mark.parametrize("overrides,code", [
    ({"esg_characteristic": None}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"esg_relevance": "not_relevant"}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"esg_relevance": "not_relevant", "esg_characteristic": None}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"exclusions": ["weapons"]}, "SUSTAINABILITY_PREFERENCE_INVALID"),
    ({"information_acknowledged": False}, "SUSTAINABILITY_INFORMATION_REQUIRED"),
    ({"hard_exclusion_requested": True}, "SUSTAINABILITY_HARD_EXCLUSION_LOCKED"),
    ({"waivers": {"tobacco": "zu kurz"}}, "SUSTAINABILITY_WAIVER_INVALID"),
    ({"waivers": {"alcohol": WAIVER_REASON}}, "SUSTAINABILITY_WAIVER_INVALID"),
    ({"waivers": {"tobacco": WAIVER_REASON}, "client_confirmed": False}, "SUSTAINABILITY_WAIVER_INVALID"),
])
def test_invalid_captures_are_rejected_and_persist_nothing(client, mandate_id, session_factory, overrides, code):
    resp = _post(client, mandate_id, **overrides)
    assert resp.status_code == 422, resp.text
    assert _reason(resp) == code
    with session_factory() as s:
        assert s.query(InvestmentPreferenceDecision).count() == 0


def test_outdated_definition_hash_is_rejected(client, mandate_id):
    resp = _post(client, mandate_id, definition_hash="0" * 64)
    assert resp.status_code == 409 and _reason(resp) == "SUSTAINABILITY_DEFINITION_OUTDATED"


def test_waiver_only_in_investment_advice(client, mandate_id, session_factory):
    _set_mandate_type(session_factory, mandate_id, "Vermögensverwaltung")
    resp = _post(client, mandate_id, waivers={"tobacco": WAIVER_REASON})
    assert resp.status_code == 409 and _reason(resp) == "SUSTAINABILITY_WAIVER_NOT_ALLOWED"
    state = client.get(f"/mandates/{mandate_id}/sustainability-preferences").json()
    assert state["waiver_allowed"] is False


def test_waiver_reason_is_sealed(client, mandate_id, session_factory):
    resp = _post(client, mandate_id, waivers={"tobacco": WAIVER_REASON})
    assert resp.status_code == 201, resp.text
    current = resp.json()["current"]
    assert current["waived_exclusions"] == ["tobacco"]
    # Nur der nicht verzichtete Ausschluss wirkt; Hinweis bleibt.
    assert sp.EXCLUSION_LIMIT_TEXT in current["limit_texts"]
    with session_factory() as s:
        row = s.query(InvestmentPreferenceDecision).one()
        assert is_sealed(row.waiver_reasons_sealed)
        assert json.loads(reveal(s, row.waiver_reasons_sealed)) == {"tobacco": WAIVER_REASON}


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
