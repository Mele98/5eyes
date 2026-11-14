"""E2a Nachhaltigkeitspraeferenzen (Dok. 106): Beratungsprotokoll und
Claim-Waechter. Uebernommen aus E1-E3 (#888, superseded), ohne Untergrenze
(die folgt erst mit E2b) und neu geprueft.

* Beratungsprotokoll-PDF: Abschnitt "Nachhaltigkeitspraeferenzen" mit
  Zustand, Antworten, Version, Kanal, Bestaetigung, Review-Frist als
  Hauspolitik, vollem Nachweis-Hash und dem Hinweis, was im Portfolio heute
  nicht beruecksichtigt wird; fehlende Erfassung wird als "Noch nicht erfasst"
  ausgewiesen (nie als "keine Praeferenz").
* Claim-Waechter: kein Kundentext nennt Produkte/Portfolio "nachhaltig" oder
  "verantwortungsbewusst" (FINMA-AM 05/2021); zur Laufzeit 409.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from core import sustainability_preference as sp
from services.pdf.base import PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer
from services.portfolio_engine_payload import (
    ESG_CUSTOMER_CLAIM_LABELS,
    THEME_DISPLAY_NAMES,
    THEME_SUB_ASSET_CLASSES,
)
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)
from tests.test_sustainability_preferences_e1 import DECLINED, NOT_RELEVANT, WAIVER_REASON, _payload


def test_exclusion_vocabulary_matches_strategy_building_blocks():
    assert tuple(sp.EXCLUSION_KEYS) == tuple(THEME_SUB_ASSET_CLASSES)
    assert set(sp.EXCLUSION_LABELS) == set(THEME_DISPLAY_NAMES)


# ── Claim-Waechter ────────────────────────────────────────────────────────────

def test_claim_guard_blocks_both_template_labels():
    lowered = [label.lower() for label in ESG_CUSTOMER_CLAIM_LABELS]
    assert "nachhaltig" in lowered and "verantwortungsbewusst" in lowered
    assert sp.customer_text_claim_hits("Ein nachhaltiges Portfolio", ESG_CUSTOMER_CLAIM_LABELS)
    assert sp.customer_text_claim_hits("verantwortungsbewusst investieren", ESG_CUSTOMER_CLAIM_LABELS)
    assert not sp.customer_text_claim_hits("Ihre Nachhaltigkeitspräferenz", ESG_CUSTOMER_CLAIM_LABELS)


def test_all_customer_texts_of_the_definition_pass_the_claim_guard():
    texts = [sp.INTRO_TEXT, sp.INFORMATION_TEXT, sp.WAIVER_TEXT, sp.WAIVER_NOT_ALLOWED_TEXT,
             sp.NO_RISK_EFFECT_TEXT, sp.NOT_CAPTURED_TEXT, sp.EXCLUSION_LOCKED_REASON,
             sp.review_policy_label(36), sp.review_due_text("2026-01-01"),
             sp.DOCUMENT_OUTDATED_TEXT, sp.DOCUMENT_UNBOUND_TEXT,
             sp.release_block_message({"state": "stale"}, "finalize"),
             sp.release_block_message({"state": "unreadable"}, "signature")]
    texts += list(sp.PROFILE_TEXTS.values()) + list(sp.PROFILE_LIMIT_TEXTS.values())
    texts += list(sp.STATE_LABELS.values()) + list(sp.STALE_REASON_TEXTS.values())
    texts += list(sp.CAPTURE_CHANNELS.values())
    for question in sp.QUESTIONS:
        texts.append(question["text"])
        texts += [o["label"] for o in question["options"]]
    for text_ in texts:
        assert not sp.customer_text_claim_hits(text_, ESG_CUSTOMER_CLAIM_LABELS), text_


def test_version_identifiers_are_claim_free():
    for value in (sp.QUESTIONNAIRE_VERSION, sp.DERIVATION_VERSION, sp.SCHEMA_VERSION, sp.REVIEW_POLICY_VERSION):
        assert not sp.customer_text_claim_hits(value, ESG_CUSTOMER_CLAIM_LABELS), value


def test_runtime_claim_guard_blocks_the_protocol(monkeypatch):
    from core.reason_codes import DomainError
    from routers.pdf_reports import _assert_sustainability_texts_claim_free

    with pytest.raises(DomainError) as exc:
        _assert_sustainability_texts_claim_free({"lines": (("Ergebnis", "Nachhaltiges Portfolio"),), "notes": ()})
    assert exc.value.reason_code == "SUSTAINABILITY_CLAIM_TEXT_BLOCKED"
    _assert_sustainability_texts_claim_free({"lines": (("Ergebnis", sp.PROFILE_TEXTS["sdg_goals"]),), "notes": ()})


# ── Beratungsprotokoll ────────────────────────────────────────────────────────

@pytest.fixture()
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster", advisor_name="Anna Berater", advisor_org="Muster AG",
        report_date=date(2026, 11, 7), audit_hash="abc123def456789012345678", locale="de-CH",
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)


def _protocol_text(mandate_id, session_factory, ctx):
    from models.mandates import Mandate
    from routers.pdf_reports import _build_protokoll_data

    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mandate_id), s)
    return _pdf_text(ReportLabRenderer().render_protokoll(ctx, data)), data


def _capture(client, mandate_id, **overrides):
    resp = client.post(f"/mandates/{mandate_id}/sustainability-preferences", json=_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_protocol_documents_missing_preference_as_not_captured(mandate_id, session_factory, ctx):
    text_, data = _protocol_text(mandate_id, session_factory, ctx)
    flat = " ".join(text_.split())
    assert data.sustainability_state == "unanswered"
    assert "NACHHALTIGKEITSPRÄFERENZEN" in text_.upper()
    assert "Noch nicht erfasst" in flat and "Nicht erfasst" in flat
    assert "Keine Präferenz" not in flat
    assert "Risikofragebogen" not in text_


@pytest.mark.parametrize("overrides,state", [
    ({}, "preference_stated"),
    ({"esg_characteristic": "sdg_alignment", "capture_channel": "phone"}, "preference_stated"),
    ({"esg_characteristic": "no_specific", "preference_waived": True, "waiver_reason": WAIVER_REASON},
     "waiver_documented"),
    (NOT_RELEVANT, "no_preference"),
    (DECLINED, "declined"),
])
def test_protocol_section_and_claim_guard(client, mandate_id, session_factory, ctx, overrides, state):
    body = _capture(client, mandate_id, **overrides)
    current = body["current"]
    text_, data = _protocol_text(mandate_id, session_factory, ctx)
    flat = " ".join(text_.split())
    assert data.sustainability_state == state == body["state"]
    assert sp.STATE_LABELS[state] in flat
    assert sp.QUESTIONNAIRE_VERSION in flat
    assert sp.CAPTURE_CHANNELS[current["capture_channel"]] in flat
    assert "Hauspolitik" in flat and "keine gesetzliche Frist" in flat
    assert "bestätigt" in flat
    assert sp.format_date_ch(current["review_due_on"]) in flat
    assert sp.NO_RISK_EFFECT_TEXT in flat
    assert current["decision_hash"] in flat.replace(" ", "")
    for limit in current["limit_texts"]:
        assert " ".join(limit.split()) in flat
    if current["preference_waived"]:
        assert "Verzicht" in flat and WAIVER_REASON not in flat
    if current["esg_relevance"] != "yes":
        assert "Frage 2" not in flat  # Folgefragen nur bei "Ja"
    section = flat[flat.upper().index("NACHHALTIGKEITSPRÄFERENZEN"):]
    assert not sp.customer_text_claim_hits(section, ESG_CUSTOMER_CLAIM_LABELS), section


def test_protocol_flags_stale_review(client, mandate_id, session_factory, ctx, monkeypatch):
    _capture(client, mandate_id)
    import services.recommendation_release_gate as release_gate

    monkeypatch.setattr(release_gate, "_today", lambda: "2999-01-01")
    text_, data = _protocol_text(mandate_id, session_factory, ctx)
    assert data.sustainability_state == "stale"
    flat = " ".join(text_.split())
    assert "Erneute Erhebung erforderlich" in flat
    assert sp.STALE_REASON_TEXTS["review_due"] in flat
