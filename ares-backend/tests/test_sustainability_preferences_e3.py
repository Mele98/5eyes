"""E3 Nachhaltigkeitspraeferenzen (Dok. 106): Protokoll und Untergrenze.

* Beratungsprotokoll-PDF: Abschnitt "Nachhaltigkeitspraeferenzen" mit
  Antworten, Version, Bestaetigung, Review-Frist als Hauspolitik und dem
  Hinweis, was im Portfolio heute nicht beruecksichtigt wird; fehlende
  Erfassung wird ausgewiesen. Dazu die Risikofragebogen-Version (H5 v1/v2).
* Kundenausschluesse sind die Untergrenze der Strategiebausteine: Generieren
  mit gelockertem Thema -> 422 SUSTAINABILITY_PREFERENCE_FLOOR_VIOLATED, vor
  jeder Berechnung; dokumentierter Kundenverzicht hebt die Untergrenze fuer
  genau dieses Thema auf.
* Claim-Waechter: kein Kundentext nennt Produkte/Portfolio "nachhaltig" oder
  "verantwortungsbewusst" (FINMA-AM 05/2021).
"""
from __future__ import annotations

import itertools
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from core import sustainability_preference as sp
from services.pdf.base import PDFContext, ProtokollData
from services.pdf.reportlab_renderer import ReportLabRenderer
from services.portfolio_engine_payload import (
    ESG_CUSTOMER_CLAIM_LABELS,
    THEME_DISPLAY_NAMES,
    THEME_SUB_ASSET_CLASSES,
    effective_theme_screening,
)
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)
from tests.test_sustainability_preferences_e1 import WAIVER_REASON, _payload

TILT_MODES = (None, "exclude", "underweight", "neutral", "allow", "overweight")


# ── Leaf-Paritaet mit den Strategiebausteinen ─────────────────────────────────

def test_exclusion_vocabulary_matches_strategy_building_blocks():
    assert tuple(sp.EXCLUSION_KEYS) == tuple(THEME_SUB_ASSET_CLASSES)
    assert set(sp.EXCLUSION_LABELS) == set(THEME_DISPLAY_NAMES)


@pytest.mark.parametrize("policy", [None, "none", "negative_screening", "esg_integration"])
def test_floor_semantics_equal_effective_theme_screening(policy):
    for mode in TILT_MODES:
        for key in sp.EXCLUSION_KEYS:
            tilts = {} if mode is None else {key: mode}
            prefs = {"tilts": tilts, "policy": {} if policy is None else {"esg": policy}}
            assert sp.screened_themes(prefs) == frozenset(effective_theme_screening(prefs)), (policy, mode, key)


def test_floor_violations_respect_waiver():
    prefs = {"tilts": {"tobacco": "allow", "defense": "exclude"}}
    assert sp.floor_violations(prefs, ["tobacco", "defense"], []) == ["tobacco"]
    assert sp.floor_violations(prefs, ["tobacco", "defense"], ["tobacco"]) == []
    assert sp.floor_violations({}, ["gaming"], []) == ["gaming"]
    assert sp.floor_violations({"policy": {"esg": "negative_screening"}}, ["gaming"], []) == []


# ── Claim-Waechter ────────────────────────────────────────────────────────────

def test_claim_guard_blocks_both_template_labels():
    lowered = [label.lower() for label in ESG_CUSTOMER_CLAIM_LABELS]
    assert "nachhaltig" in lowered and "verantwortungsbewusst" in lowered
    assert sp.customer_text_claim_hits("Ein nachhaltiges Portfolio", ESG_CUSTOMER_CLAIM_LABELS)
    assert sp.customer_text_claim_hits("verantwortungsbewusst investieren", ESG_CUSTOMER_CLAIM_LABELS)
    assert not sp.customer_text_claim_hits("Ihre Nachhaltigkeitspräferenz", ESG_CUSTOMER_CLAIM_LABELS)


def test_all_customer_texts_of_the_definition_pass_the_claim_guard():
    texts = [sp.INTRO_TEXT, sp.INFORMATION_TEXT, sp.HARD_EXCLUSION_LOCKED_NOTE,
             sp.EXCLUSION_LIMIT_TEXT, sp.EXCLUSION_DEVIATION_TEXT.format(labels="Tabak"),
             sp.EXCLUSION_NO_STRATEGY_TEXT, sp.WAIVER_VOID_TEXT,
             sp.floor_stale_notice({"status": "violated", "themes": ["tobacco"]}),
             sp.floor_message({"status": "violated", "themes": ["tobacco"]}, "finalize"),
             sp.NO_RISK_EFFECT_TEXT, sp.review_policy_label(36),
             sp.review_due_text("2026-01-01")]
    texts += list(sp.PROFILE_TEXTS.values()) + list(sp.PROFILE_LIMIT_TEXTS.values())
    for question in sp.QUESTIONS:
        texts.append(question["text"])
        texts += [o["label"] for o in question["options"]]
    for text_ in texts:
        assert not sp.customer_text_claim_hits(text_, ESG_CUSTOMER_CLAIM_LABELS), text_


# ── Untergrenze beim Generieren ───────────────────────────────────────────────

@pytest.fixture()
def generate_probe(monkeypatch):
    """Generieren ohne Engine: erreicht der Aufruf die Engine, meldet die
    Sonde 409 'ENGINE-ERREICHT' (= Untergrenze hat nicht blockiert)."""
    import routers.allocation as allocation_router

    monkeypatch.setattr(allocation_router.settings, "require_suitability_before_recommendation", False)

    def _engine(**_kwargs):
        raise ValueError("ENGINE-ERREICHT")

    monkeypatch.setattr(allocation_router, "generate_target_allocation", _engine)


def _generate(client, mandate_id, tilts=None):
    body = {} if tilts is None else {"preferences": {"tilts": tilts}}
    if tilts:
        reasons = {k: WAIVER_REASON for k, v in tilts.items() if v == "allow"}
        if reasons:
            body["preferences"]["tiltReasons"] = reasons
    return client.post(f"/mandates/{mandate_id}/target-allocation/generate", json=body)


def _capture(client, mandate_id, **overrides):
    resp = client.post(f"/mandates/{mandate_id}/sustainability-preferences", json=_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()["current"]


def test_loosened_customer_exclusion_blocks_generate(client, mandate_id, generate_probe):
    _capture(client, mandate_id, exclusions=["tobacco"])
    resp = _generate(client, mandate_id, {"tobacco": "allow"})
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["reason_code"] == "SUSTAINABILITY_PREFERENCE_FLOOR_VIOLATED"
    assert detail["themes"] == ["tobacco"]
    assert "Tabak" in detail["message"] and "Kundenverzicht" in detail["message"]


def test_missing_tilts_count_as_loosened(client, mandate_id, generate_probe):
    _capture(client, mandate_id, exclusions=["gaming"])
    resp = _generate(client, mandate_id)  # keine Praeferenzen, keine Soll-Allokation
    assert resp.status_code == 422 and resp.json()["detail"]["themes"] == ["gaming"]


@pytest.mark.parametrize("mode", ["exclude", "underweight"])
def test_respected_floor_reaches_the_engine(client, mandate_id, generate_probe, mode):
    _capture(client, mandate_id, exclusions=["tobacco"])
    resp = _generate(client, mandate_id, {"tobacco": mode})
    assert resp.status_code == 409 and "ENGINE-ERREICHT" in resp.text


def test_documented_waiver_lifts_the_floor_for_that_theme_only(client, mandate_id, generate_probe):
    _capture(client, mandate_id, exclusions=["tobacco", "defense"], waivers={"tobacco": WAIVER_REASON})
    assert "ENGINE-ERREICHT" in _generate(client, mandate_id, {"tobacco": "allow", "defense": "exclude"}).text
    resp = _generate(client, mandate_id, {"tobacco": "allow", "defense": "neutral"})
    assert resp.status_code == 422 and resp.json()["detail"]["themes"] == ["defense"]


def test_without_preference_generate_is_unchanged(client, mandate_id, generate_probe):
    assert "ENGINE-ERREICHT" in _generate(client, mandate_id, {"tobacco": "allow"}).text


# ── Beratungsprotokoll ────────────────────────────────────────────────────────

@pytest.fixture()
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster", advisor_name="Anna Berater", advisor_org="Muster AG",
        report_date=date(2026, 11, 7), audit_hash="abc123def456789012345678", locale="de-CH",
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)


def _protocol_text(client, mandate_id, session_factory, ctx) -> str:
    from routers.pdf_reports import _build_protokoll_data
    from models.mandates import Mandate

    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mandate_id), s)
    return _pdf_text(ReportLabRenderer().render_protokoll(ctx, data)), data


def test_protocol_documents_missing_preference_and_risk_version(client, mandate_id, session_factory, ctx):
    text_, data = _protocol_text(client, mandate_id, session_factory, ctx)
    assert data.sustainability_state == "missing"
    assert "NACHHALTIGKEITSPRÄFERENZEN" in text_.upper()
    assert "Nicht erfasst" in text_
    assert data.risk_questionnaire_line == ("Risikofragebogen", "Kein aktuelles Risikoprofil")


@pytest.mark.parametrize("overrides", [
    {},
    {"esg_characteristic": "sdg_alignment", "exclusions": []},
    {"esg_characteristic": "no_specific", "exclusions": ["fossil"], "waivers": {"fossil": WAIVER_REASON}},
    {"esg_relevance": "not_relevant", "esg_characteristic": None, "exclusions": []},
    {"response_status": "declined", "esg_relevance": None, "esg_characteristic": None, "exclusions": []},
])
def test_protocol_section_and_claim_guard(client, mandate_id, session_factory, ctx, overrides):
    current = _capture(client, mandate_id, **overrides)
    text_, data = _protocol_text(client, mandate_id, session_factory, ctx)
    flat = " ".join(text_.split())
    assert data.sustainability_state == "current"
    assert "NACHHALTIGKEITSPRÄFERENZEN" in text_.upper()
    assert sp.QUESTIONNAIRE_VERSION in flat
    assert "Hauspolitik" in flat and "keine gesetzliche Frist" in flat
    assert "bestätigt" in flat
    assert sp.format_date_ch(current["review_due_on"]) in flat
    assert sp.NO_RISK_EFFECT_TEXT in flat
    for limit in current["limit_texts"]:
        assert " ".join(limit.split()) in flat
    if set(current["exclusions"]) - set(current["waived_exclusions"]):
        assert " ".join(sp.HARD_EXCLUSION_LOCKED_NOTE.split()) in flat
    if current["waived_exclusions"]:
        assert "Kundenverzicht" in flat and WAIVER_REASON not in flat
    section = flat[flat.upper().index("NACHHALTIGKEITSPRÄFERENZEN"):]
    assert not sp.customer_text_claim_hits(section, ESG_CUSTOMER_CLAIM_LABELS), section


def test_protocol_flags_due_review(client, mandate_id, session_factory, ctx, monkeypatch):
    _capture(client, mandate_id)
    import routers.pdf_reports as pdf_reports

    class _Future(date):
        @classmethod
        def today(cls):
            return date(2999, 1, 1)

    monkeypatch.setattr(pdf_reports, "date", _Future)
    text_, data = _protocol_text(client, mandate_id, session_factory, ctx)
    assert data.sustainability_state == "due"
    assert "Eignungsprüfung fällig" in " ".join(text_.split())


@pytest.mark.parametrize("version,digest,expected", [
    (None, None, "Version v1 (Standard-Fragebogen)"),
    ("v2", "a" * 64, "Version v2 · Definition aaaaaaaaaaaaaaaa…"),
])
def test_risk_questionnaire_version_line(version, digest, expected):
    from types import SimpleNamespace

    from routers.pdf_reports import _risk_questionnaire_version_line

    ra = SimpleNamespace(questionnaire_version=version, questionnaire_hash=digest)
    assert _risk_questionnaire_version_line(ra) == ("Risikofragebogen", expected)


def test_protocol_renders_risk_version_row(ctx):
    data = ProtokollData(mandate_number="M-1", risk_questionnaire_line=("Risikofragebogen", "Version v2"))
    assert "Risikofragebogen" in _pdf_text(ReportLabRenderer().render_protokoll(ctx, data))


def test_version_identifiers_are_claim_free():
    for value in (sp.QUESTIONNAIRE_VERSION, sp.DERIVATION_VERSION, sp.SCHEMA_VERSION):
        assert not sp.customer_text_claim_hits(value, ESG_CUSTOMER_CLAIM_LABELS), value


def test_every_profile_text_combination_is_claim_free():
    for code, exclusions in itertools.product(sp.PROFILE_CODES, ([], ["tobacco"])):
        for text_ in [sp.PROFILE_TEXTS[code], *sp.limit_texts(code, exclusions)]:
            assert not sp.customer_text_claim_hits(text_, ESG_CUSTOMER_CLAIM_LABELS)
