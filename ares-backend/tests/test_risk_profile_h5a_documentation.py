"""H5a Risikoprofil-Dokumentation (Dok. 105, Entscheid E5 + Kleinbefund 3.3).

Sofort wirksam, ohne Score-Wirkung:

* Fussnote zu Frage 10 (Bandbreite ~80 % der Faelle ueber ein Jahr) im
  Risikoprofil-PDF -- und wortgleich in der Maske (Paritaet in
  test_frontend_risk_questionnaire_v2.py).
* Anlagehorizont im PDF als Kundenantwort (Antwortlabel Frage 8) statt als
  interner Matrix-Stuetzwert; das irrefuehrende Feld ``experience_years``
  ist ersetzt durch ``investment_horizon_label``.
* Das PDF weist aus, ob die Risikofaehigkeit oder die Risikobereitschaft das
  Profil bestimmt.

Fragen 1-11, Punkte und Scores bleiben unveraendert (eigene Gegenprobe).
"""
from __future__ import annotations

import dataclasses
import io
import re
from datetime import date

import pytest

from services.pdf.base import PDFContext, RisikoprofilData
from services.pdf.components.eignungspruefung import (
    QUESTION_CATALOG,
    Q10_BAND_FOOTNOTE,
    make_eignungspruefung_section,
)
from services.pdf.documents.risikoprofil import binding_side_text, build_risikoprofil_flowables
from tests.risk_fixture_helpers import standard_risk_payload
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)


def _texts(flowables) -> str:
    out = []

    def walk(obj):
        text = getattr(obj, "text", None)
        if isinstance(text, str):
            out.append(text)
        for row in getattr(obj, "_cellvalues", None) or []:
            for cell in row:
                for item in cell if isinstance(cell, (list, tuple)) else [cell]:
                    walk(item)

    for f in flowables:
        walk(f)
    return "\n".join(out)


def _ctx() -> PDFContext:
    return PDFContext(mandate_name="Test", advisor_name="Berater", report_date=date(2026, 11, 7))


# ── Fussnote Frage 10 ───────────────────────────────────────────────────────────

def test_q10_footnote_states_80_percent_band_over_one_year():
    assert "80 %" in Q10_BAND_FOOTNOTE
    assert "eines Jahres" in Q10_BAND_FOOTNOTE
    assert "10 %" in Q10_BAND_FOOTNOTE
    assert "grösser" in Q10_BAND_FOOTNOTE  # Verlust kann die untere Grenze unterschreiten


def test_q10_footnote_is_rendered_under_question_10_in_the_pdf():
    text = _texts(make_eignungspruefung_section(answers=[]))
    assert Q10_BAND_FOOTNOTE in text
    # genau einmal, und nur bei Frage 10
    assert text.count("Hinweis zu Frage 10") == 1
    q10 = text.index("Frage 10</font>")
    q11 = text.index("Frage 11</font>")
    assert q10 < text.index("Hinweis zu Frage 10") < q11


def test_question_texts_1_to_11_are_unchanged():
    # Owner-Regel: Fragen wortgleich nach Vorlage. Die Fussnote ist ein Zusatz,
    # kein geaenderter Fragetext.
    assert sorted(QUESTION_CATALOG) == list(range(1, 12))
    assert QUESTION_CATALOG[10][1] == (
        "Risikoverhalten – Anlagen mit höherer erwarteter Rendite haben auch ein höheres erwartetes Risiko."
    )


# ── Anlagehorizont als Kundenantwort ────────────────────────────────────────────

def test_pdf_data_has_no_misnamed_experience_years_field():
    names = {f.name for f in dataclasses.fields(RisikoprofilData)}
    assert "experience_years" not in names
    assert "investment_horizon_label" in names


@pytest.mark.parametrize("label", ["Mehr als 12 Jahre", "Bis 2 Jahre", "3 bis 5 Jahre"])
def test_summary_shows_the_answer_label_not_the_matrix_support_value(label):
    data = RisikoprofilData(
        risk_profile_label="Ausgewogen", risk_capacity_score=60, risk_tolerance_score=60,
        investment_horizon_label=label,
    )
    text = _texts(build_risikoprofil_flowables(_ctx(), data))
    assert label in text
    assert "15 Jahre" not in text and "1 Jahre" not in text


def test_summary_without_horizon_says_not_documented():
    data = RisikoprofilData(risk_profile_label="Ausgewogen", risk_capacity_score=60, risk_tolerance_score=60)
    assert "Nicht dokumentiert" in _texts(build_risikoprofil_flowables(_ctx(), data))


# ── Bindende Seite ─────────────────────────────────────────────────────────────

def _data(cap, will, **kw):
    return RisikoprofilData(risk_profile_label="x", risk_capacity_score=cap, risk_tolerance_score=will, **kw)


def test_binding_side_capacity_when_capacity_is_lower():
    assert "ist die Risikofähigkeit" in binding_side_text(_data(40, 70))


def test_binding_side_willingness_when_willingness_is_lower():
    assert "ist die Risikobereitschaft" in binding_side_text(_data(100, 70))


def test_binding_side_both_when_equal():
    assert "gemeinsam" in binding_side_text(_data(60, 60))


def test_binding_side_names_fzk_cap_and_override():
    text = binding_side_text(_data(100, 100, mandate_type="FZK", is_overridden=True))
    assert "Freizügigkeitsmandat" in text and "übersteuert" in text
    assert "Freizügigkeitsmandat" not in binding_side_text(_data(70, 70, mandate_type="FZK"))


def test_binding_side_is_empty_without_scores():
    assert binding_side_text(_data(0, 0)) == ""


def test_binding_side_is_rendered_in_the_risk_profile_pdf():
    text = _texts(build_risikoprofil_flowables(_ctx(), _data(100, 70)))
    assert "Bestimmend für das Risikoprofil ist die Risikobereitschaft" in text


# ── End-to-End: gespeichertes Profil -> Risikoprofil-PDF ─────────────────────────

def _pdf_text(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in reader.pages))


def test_saved_profile_pdf_shows_horizon_answer_footnote_and_binding_side(client, mandate_id):
    # horizon=5 -> "Mehr als 12 Jahre" (Matrix-Stuetzwert 15); Faehigkeit 100,
    # Bereitschaft 70 -> die Bereitschaft bestimmt.
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=standard_risk_payload(horizon=5))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["risk_capacity_score_x10"], body["risk_willingness_score_x10"]) == (100, 70)
    pdf = client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    assert pdf.status_code == 200, pdf.text
    text = _pdf_text(pdf.content)
    assert "Mehr als 12 Jahre" in text
    assert "15 Jahre" not in text
    assert "Matrix-Faktor" not in text  # interner Zusatz auch nicht in der Antwort zu Frage 8
    assert "Hinweis zu Frage 10" in text
    assert "Bestimmend für das Risikoprofil ist die Risikobereitschaft" in text
