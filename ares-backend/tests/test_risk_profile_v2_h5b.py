"""H5b Risikoprofil-Fragebogen v2 (Dok. 105, Entscheide E1-E4, E7).

* Fragen 1-11 und die Kernformel bleiben unveraendert; v1-Profile bleiben
  gueltig und werden nie mit v2-Regeln bewertet.
* v2 ergaenzt Q12 (Verlusttoleranz in CHF), Q13 (tatsaechliches Verhalten),
  Q14 (Dauer der Verlustphase) und den Q11-Knock-out -- ausschliesslich als
  Kappung der Risikobereitschaft (nie anheben). Property: v2 <= v1 fuer alle
  Kombinationen; bei voller Zustimmung v2 == v1.
* Konsistenz-Flags K1-K6: keine Profilaenderung, kein Block, aber
  Pflicht-Beraternotiz; Dokumentation im PDF.
* Feature-Flag, Default AUS (Grenzwerte 40/60/80 = Startwerte bis zur
  IC-/Compliance-Freigabe).
"""
from __future__ import annotations

import copy
import io
import itertools
import json
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

import services.risk_questionnaire_integrity as rqi
from models.profiling import RiskAssessment
from services import risk_profile_signoff as rps
from services.pdf.components.eignungspruefung import V2_QUESTION_CATALOG
from services.risk_assessment_semantics import (
    RiskAssessmentInputError,
    validate_risk_assessment_model_input,
)
from services.risk_scoring import (
    HORIZON_CAPACITY_MATRIX,
    Q11_KNOCKOUT_MAX_SCORE_X10,
    V2_WILLINGNESS_CAPS_X10,
    compute_scores,
    compute_willingness_v2,
    profile_for_score_x10,
)
from tests.risk_fixture_helpers import standard_risk_payload
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FULL_YES = {12: 3, 13: 3, 14: 3}   # ueber 20 % / zugekauft / ueber 4 Jahre
COLUMNS = {"questionnaire_version", "questionnaire_hash", "willingness_v2_json", "consistency_note"}
NOTE = "Widerspruch mit dem Kunden besprochen; er bleibt bei seinen Angaben."


def _will_core(q9, q10, q11) -> int:
    return compute_scores(
        q_income_points=4, q_obligations_points=4, q_savings_points=12, q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=q9, q_risk_preference_points=q10, q_risk_behavior_points=q11,
    ).risk_willingness_score_x10


# ── Scoring: nur absenkend ──────────────────────────────────────────────────────

def test_cap_table_uses_the_e3_start_values():
    assert V2_WILLINGNESS_CAPS_X10 == {12: (40, 60, 80, 100), 13: (40, 60, 100, 100, 100), 14: (40, 60, 100, 100)}
    assert Q11_KNOCKOUT_MAX_SCORE_X10 == 40 and profile_for_score_x10(40) == "Defensiv"


def test_v2_never_exceeds_v1_for_every_combination():
    capacities = sorted(set(HORIZON_CAPACITY_MATRIX.values()))
    checked = 0
    for q9, q10, q11 in itertools.product(range(1, 5), repeat=3):
        core = _will_core(q9, q10, q11)
        for o12, o13, o14 in itertools.product(range(4), range(5), range(4)):
            r = compute_willingness_v2(core_willingness_score_x10=core, q_risk_behavior_points=q11,
                                       q12_option=o12, q13_option=o13, q14_option=o14)
            assert r.effective_score_x10 <= core
            for cap in capacities:
                assert min(cap, r.effective_score_x10) <= min(cap, core)
            checked += 1
    assert checked == 64 * 80


def test_full_agreement_gives_exactly_the_v1_profile():
    for q9, q10, q11 in itertools.product(range(1, 5), range(1, 5), range(2, 5)):
        core = _will_core(q9, q10, q11)
        for o13 in (2, 3, 4):  # gehalten / zugekauft / nicht investiert
            for o14 in (2, 3):
                r = compute_willingness_v2(core_willingness_score_x10=core, q_risk_behavior_points=q11,
                                           q12_option=3, q13_option=o13, q14_option=o14)
                assert r.effective_score_x10 == core and r.caps == ()


def test_q11_panic_answer_caps_growth_profile_to_defensive():
    # G1: Q9=4, Q10=4, Q11=1 -> 9 Punkte -> 70 (Wachstumsorientiert) in v1.
    core = _will_core(4, 4, 1)
    assert core == 70
    r = compute_willingness_v2(core_willingness_score_x10=core, q_risk_behavior_points=1, **{
        f"q{q}_option": i for q, i in FULL_YES.items()})
    assert r.effective_score_x10 == 40 and r.effective_profile == "Defensiv"
    assert [c.source for c in r.caps] == ["Q11"]


@pytest.mark.parametrize("bad", [-1, 4, True])
def test_unknown_option_index_fails_closed(bad):
    with pytest.raises(ValueError):
        compute_willingness_v2(core_willingness_score_x10=70, q_risk_behavior_points=3,
                               q12_option=bad, q13_option=0, q14_option=0)


# ── Konsistenz-Flags ────────────────────────────────────────────────────────────

def test_consistency_flags_follow_the_documented_rules():
    aktien = json.dumps({"Aktien": {"known": 1, "informed": 0}})
    none = json.dumps({"Aktien": {"known": 0, "informed": 0}})
    f = rqi.consistency_flags
    assert f(q9=1, q10=3, q11=3, q13_option=2, effective_willingness_profile="Ausgewogen",
             knowledge_instruments_json=aktien) == ["K1", "K3"]
    assert f(q9=3, q10=3, q11=2, q13_option=2, effective_willingness_profile="Ausgewogen",
             knowledge_instruments_json=aktien) == ["K2"]
    assert f(q9=3, q10=3, q11=3, q13_option=4, effective_willingness_profile="Wachstumsorientiert",
             knowledge_instruments_json=none) == ["K4", "K5"]
    assert f(q9=3, q10=3, q11=3, q13_option=4, effective_willingness_profile="Ausgewogen",
             knowledge_instruments_json=none) == []
    # K6 nur mit aktiver Verlusttoleranz-Pruefung (P11)
    assert f(q9=2, q10=2, q11=2, q13_option=2, effective_willingness_profile="Defensiv",
             knowledge_instruments_json=aktien, loss_tolerance_breach=True) == ["K6"]
    assert set(rqi.CONSISTENCY_FLAGS) == {"K1", "K2", "K3", "K4", "K5", "K6"}


def test_v2_question_texts_are_identical_in_pdf_and_integrity():
    assert {q: t for q, (_s, t) in V2_QUESTION_CATALOG.items()} == rqi.V2_QUESTIONS


def test_flag_is_off_by_default_and_hash_is_stable():
    assert rqi.RISK_QUESTIONNAIRE_V2_ENABLED is False
    assert rqi.questionnaire_v2_enabled() is False
    policy = rqi.questionnaire_v2_policy()
    assert policy["v2_enabled"] is False and policy["active_version"] == "v1"
    assert "IC/Compliance" in policy["approval_status"]
    assert re.fullmatch(r"[0-9a-f]{64}", rqi.QUESTIONNAIRE_V2_HASH)


# ── API ─────────────────────────────────────────────────────────────────────────

def _v2_payload(*, q12=3, q13=3, q14=3, note=None, **kw) -> dict:
    payload = standard_risk_payload(**kw)
    payload["questionnaire_version"] = "v2"
    payload["questionnaire_v2_answers"] = [
        {"question_number": q, "answer_label": rqi.V2_OPTIONS[q][i]}
        for q, i in ((12, q12), (13, q13), (14, q14))
    ]
    if note is not None:
        payload["consistency_note"] = note
    return payload


def _reason(resp):
    detail = resp.json().get("detail")
    return detail.get("reason_code") if isinstance(detail, dict) else None


@pytest.fixture()
def v2_on(monkeypatch):
    monkeypatch.setattr(rqi, "RISK_QUESTIONNAIRE_V2_ENABLED", True)


def test_policy_endpoint_reports_v2_disabled_by_default(client):
    resp = client.get("/risk-questionnaire/policy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["v2_enabled"] is False and body["questionnaire_hash"] == rqi.QUESTIONNAIRE_V2_HASH
    assert [q["number"] for q in body["questions"]] == [12, 13, 14]


def test_v2_submission_is_rejected_while_flag_is_off(client, mandate_id):
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=_v2_payload())
    assert resp.status_code == 422 and _reason(resp) == rqi.REASON_V2_DISABLED


def test_v1_submission_must_not_smuggle_v2_answers(client, mandate_id):
    payload = standard_risk_payload()
    payload["questionnaire_v2_answers"] = _v2_payload()["questionnaire_v2_answers"]
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)
    assert resp.status_code == 422 and _reason(resp) == rqi.REASON_NOT_STANDARD


def test_v1_save_is_unchanged_and_unversioned(client, mandate_id):
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=standard_risk_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["final_score_x10"] == 70
    assert body["questionnaire_version"] is None and body["willingness_v2_json"] is None


def test_v2_full_agreement_saves_identical_profile_to_v1(client, mandate_id, v2_on):
    v1 = client.post(f"/mandates/{mandate_id}/risk-assessments", json=standard_risk_payload()).json()
    v2 = client.post(f"/mandates/{mandate_id}/risk-assessments", json=_v2_payload(note=NOTE)).json()
    for key in ("risk_capacity_score_x10", "risk_willingness_score_x10", "risk_willingness_profile",
                "final_score_x10", "final_profile"):
        assert v2[key] == v1[key], key
    assert v2["questionnaire_version"] == "v2"
    assert v2["questionnaire_hash"] == rqi.QUESTIONNAIRE_V2_HASH
    evidence = json.loads(v2["willingness_v2_json"])
    assert evidence["caps"] == [] and evidence["core_willingness_score_x10"] == 70


def test_v2_knockout_lowers_profile_and_never_raises(client, mandate_id, v2_on):
    # goal=3, pref=3, behav=0 -> Q9=4, Q10=4, Q11=1 -> v1: 70 Wachstumsorientiert
    payload = _v2_payload(goal=3, pref=3, behav=0, note=NOTE)
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["risk_willingness_total"] == 9  # Kernsumme unveraendert
    assert body["risk_willingness_score_x10"] == 40
    assert body["final_score_x10"] == 40 and body["final_profile"] == "Defensiv"
    assert json.loads(body["willingness_v2_json"])["core_willingness_score_x10"] == 70


def test_consistency_flags_require_an_advisor_note_but_never_change_the_profile(client, mandate_id, v2_on):
    # Q9=1 (Kapitalerhalt) + Q10=3 -> K1, Spannweite -> K3
    payload = _v2_payload(goal=0, pref=2, behav=2)
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)
    assert resp.status_code == 422 and _reason(resp) == rqi.REASON_CONSISTENCY_NOTE_REQUIRED
    codes = [f["code"] for f in resp.json()["detail"]["consistency_flags"]]
    assert codes == ["K1", "K3"]
    payload["consistency_note"] = "zu kurz"
    assert _reason(client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)) == \
        rqi.REASON_CONSISTENCY_NOTE_REQUIRED
    payload["consistency_note"] = NOTE
    ok = client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)
    assert ok.status_code == 201, ok.text
    v1_equiv = compute_scores(
        q_income_points=payload["q_income_points"], q_obligations_points=payload["q_obligations_points"],
        q_savings_points=payload["q_savings_points"], q_wealth_points=payload["q_wealth_points"],
        investment_horizon_label=payload["investment_horizon_label"],
        q_investment_goal_points=1, q_risk_preference_points=3, q_risk_behavior_points=3,
    )
    assert ok.json()["final_score_x10"] == v1_equiv.final_score_x10
    assert ok.json()["consistency_note"] == NOTE
    assert json.loads(ok.json()["willingness_v2_json"])["consistency_flags"] == ["K1", "K3"]


def test_unknown_v2_option_or_missing_question_is_rejected(client, mandate_id, v2_on):
    payload = _v2_payload(note=NOTE)
    payload["questionnaire_v2_answers"][0]["answer_label"] = "Bis 3 %"
    assert _reason(client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)) == rqi.REASON_NOT_STANDARD
    payload = _v2_payload(note=NOTE)
    payload["questionnaire_v2_answers"].pop()
    assert _reason(client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)) == rqi.REASON_NOT_STANDARD


def test_q12_label_may_carry_the_precomputed_franc_amount_only(client, mandate_id, v2_on):
    payload = _v2_payload(note=NOTE)
    payload["questionnaire_v2_answers"][0]["answer_label"] = (
        "Über 20 % · über ca. CHF 50'000 bei CHF 250'000 Anlagebetrag")
    assert client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload).status_code == 201
    payload["questionnaire_v2_answers"][0]["answer_label"] = "Über 20 % · beliebiger Text"
    assert _reason(client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)) == rqi.REASON_NOT_STANDARD


# ── Gespeicherte Profile: Versionsbindung, fail-closed ──────────────────────────

def _current(session_factory, mandate_id) -> RiskAssessment:  # noqa: F811
    with session_factory() as s:
        ra = s.query(RiskAssessment).filter_by(mandate_id=mandate_id, is_current=1).one()
        s.expunge(ra)
        return ra


def test_v1_profile_stays_valid_and_is_never_rescored_after_enabling_v2(
    client, mandate_id, session_factory, monkeypatch,  # noqa: F811
):
    payload = standard_risk_payload(goal=3, pref=3, behav=0)  # v1: Panik-Antwort, 70
    assert client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload).status_code == 201
    monkeypatch.setattr(rqi, "RISK_QUESTIONNAIRE_V2_ENABLED", True)
    ra = _current(session_factory, mandate_id)
    assert ra.questionnaire_version is None
    assert validate_risk_assessment_model_input(ra, mandate_type="Anlageberatung") == 70


def test_tampered_v2_evidence_or_unknown_version_fails_closed(
    client, mandate_id, session_factory, v2_on,  # noqa: F811
):
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments",
                       json=_v2_payload(goal=3, pref=3, behav=0, note=NOTE))
    assert resp.status_code == 201, resp.text
    ra = _current(session_factory, mandate_id)
    assert validate_risk_assessment_model_input(ra, mandate_type="Anlageberatung") == 40

    lifted = copy.copy(ra)
    evidence = json.loads(ra.willingness_v2_json)
    evidence["answers"][0]["answer_label"] = rqi.V2_OPTIONS[12][3]
    evidence["answers"][0]["option_index"] = 3
    lifted.willingness_v2_json = json.dumps(evidence)
    lifted.risk_willingness_score_x10 = 70
    lifted.final_score_x10 = 70
    lifted.final_profile = "Wachstumsorientiert"
    lifted.risk_willingness_profile = "Wachstumsorientiert"
    with pytest.raises(RiskAssessmentInputError):  # Q11-Knock-out bleibt wirksam
        validate_risk_assessment_model_input(lifted, mandate_type="Anlageberatung")

    for field, value in (("questionnaire_version", "v3"), ("questionnaire_hash", "0" * 64),
                         ("willingness_v2_json", "{}")):
        broken = copy.copy(ra)
        setattr(broken, field, value)
        with pytest.raises(RiskAssessmentInputError):
            validate_risk_assessment_model_input(broken, mandate_type="Anlageberatung")


def test_signoff_input_hash_binds_v2_evidence_but_keeps_v1_payload():
    v1 = SimpleNamespace(**{name: f"x-{name}" for name in rps._INPUT_FIELDS})
    base = rps.assessment_input_hash(None, v1)
    v1.questionnaire_version = None
    v1.willingness_v2_json = "ignored"
    assert rps.assessment_input_hash(None, v1) == base
    v2 = SimpleNamespace(**{name: f"x-{name}" for name in rps._INPUT_FIELDS},
                         questionnaire_version="v2", questionnaire_hash="h", willingness_v2_json="a",
                         consistency_note="n")
    h1 = rps.assessment_input_hash(None, v2)
    v2.willingness_v2_json = "b"
    assert rps.assessment_input_hash(None, v2) != h1
    v2.willingness_v2_json = "a"
    v2.consistency_note = "redigiert"  # Freitext ist nicht gebunden (Loeschung)
    assert rps.assessment_input_hash(None, v2) == h1


# ── PDF ─────────────────────────────────────────────────────────────────────────

def _pdf_text(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in reader.pages))


def test_v2_pdf_documents_version_answers_cap_reason_flags_and_note(client, mandate_id, v2_on):
    payload = _v2_payload(goal=3, pref=3, behav=0, q12=1, note=NOTE)
    assert client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload).status_code == 201
    text = _pdf_text(client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf").content)
    assert "Fragebogen-Version v2" in text and "Erhebungsdatum" in text
    assert "Frage 12" in text and "5 bis 10 %" in text and "Frage 14" in text
    assert "Frage 11: Bei einem Verlust von 20 % alle Anlagen sofort verkaufen" in text
    assert "höchstens «Defensiv»" in text
    assert "Konsistenzhinweis K2" in text  # Q10=4, Q11=1
    assert "Beraternotiz zu den Konsistenzhinweisen" in text


def test_v1_pdf_has_no_v2_section(client, mandate_id):
    assert client.post(f"/mandates/{mandate_id}/risk-assessments", json=standard_risk_payload()).status_code == 201
    text = _pdf_text(client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf").content)
    assert "Fragebogen-Version" not in text and "Frage 12" not in text


# ── Schema: ORM, Bootstrap-SQL, Laufzeitpatch, Alembic ──────────────────────────

def _columns(db_path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(risk_assessments)")}


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_columns_exist_in_orm_bootstrap_and_runtime_patch(tmp_path, monkeypatch):
    import database as db_module

    assert COLUMNS <= {c.name for c in RiskAssessment.__table__.columns}
    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=BACKEND_ROOT / "ares_schema.sql")
    assert COLUMNS <= _columns(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        for column in sorted(COLUMNS):
            conn.execute(f"ALTER TABLE risk_assessments DROP COLUMN {column}")
        conn.commit()
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    assert COLUMNS <= _columns(db_path)


def test_alembic_single_head_adds_and_removes_the_columns(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    # E1 Nachhaltigkeitspraeferenzen (Dok. 106) setzt f3a8c1e5b7d2 als
    # einzigen Head auf e7c4a9b2d6f1; die H5b-Revision bleibt in der Kette.
    assert script.get_heads() == ["f3a8c1e5b7d2"]
    assert script.get_revision("f3a8c1e5b7d2").down_revision == "e7c4a9b2d6f1"
    assert script.get_revision("e7c4a9b2d6f1").down_revision == "d3b7f1a5c9e2"
    db_url = f"sqlite:///{tmp_path / 'alembic.db'}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert COLUMNS <= {c["name"] for c in inspect(engine).get_columns("risk_assessments")}
    engine.dispose()
    command.downgrade(cfg, "d3b7f1a5c9e2")
    engine = create_engine(db_url)
    assert not COLUMNS & {c["name"] for c in inspect(engine).get_columns("risk_assessments")}
    engine.dispose()


def test_consistency_note_is_redacted_on_erasure():
    from services.privacy_erasure_inventory import PERSONAL_DATA_INVENTORY

    columns = {
        col for cat in PERSONAL_DATA_INVENTORY["risk_assessments"].categories for col in cat.columns
    }
    assert "consistency_note" in columns
    source = (BACKEND_ROOT / "services" / "client_erasure.py").read_text(encoding="utf-8")
    assert '("consistency_note", "")' in source


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
