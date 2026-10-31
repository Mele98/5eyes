"""Produktname in neu erzeugten Ausgaben (Spec §3/§5, Minimalbranding).

API-Dokumentation, PDF (Inhalt und Metadaten), E-Mails, Alert-Webhook,
Backup-Alerts und Kalenderanzeige nennen das Produkt ``Ares``. Archivierte
Dokumente sind nicht betroffen; geprueft wird nur, was jetzt erzeugt wird.
"""
from __future__ import annotations

import inspect
import io
from datetime import date
from types import SimpleNamespace

import pytest

PRODUCT = "Ares"


def test_openapi_title_and_description():
    from main import app

    info = app.openapi()["info"]
    assert info["title"] == "Ares API"
    assert info["description"].startswith(f"{PRODUCT} — ")


def test_openapi_title_is_decoupled_from_health_app_name():
    """Der Health-Handshake (`app_name`) ist eine eigene Kette (W2-i) und
    bleibt hier unberuehrt; der OpenAPI-Titel haengt nicht mehr daran."""
    from config import settings
    from main import app

    assert app.title == "Ares API"
    assert isinstance(settings.app_name, str) and settings.app_name


def _pdf_reader(pdf: bytes):
    pypdf = pytest.importorskip("pypdf")
    return pypdf.PdfReader(io.BytesIO(pdf))


def test_advisory_report_pdf_metadata_and_page_chrome():
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    from tests.test_advisory_report_pdf import _make_minimal_payload

    reader = _pdf_reader(render_advisory_report_pdf_from_payload(_make_minimal_payload()))
    meta = reader.metadata
    assert meta.creator == PRODUCT
    assert meta.producer == PRODUCT
    assert meta.title.startswith("Ares Advisory Report — ")
    cover = reader.pages[0].extract_text() or ""
    assert PRODUCT in cover
    second = reader.pages[1].extract_text() or ""
    assert "Ares Advisory Report" in second
    assert "Depotcheck" in second


def test_generic_pdf_renderer_sets_creator_and_producer():
    from services.pdf.base import PDFContext, RisikoprofilData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 17),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )
    data = RisikoprofilData(
        risk_profile_label="Ausgewogen",
        risk_capacity_score=65,
        risk_tolerance_score=58,
        knowledge_services={"Anlageberatung": True},
        knowledge_instruments={"Aktien": True},
        experience_years=8,
        suitability_note="kompatibel",
    )
    meta = _pdf_reader(ReportLabRenderer().render_risikoprofil(ctx, data)).metadata
    assert meta.creator == PRODUCT
    assert meta.producer == PRODUCT


def test_mail_subjects_and_signature():
    from services import mailer

    invite = mailer._build_invite_message("a@example.test", "Anna", "https://x.example.test/i")
    assert "Ares" in invite["Subject"]
    assert invite.get_content().rstrip().endswith("— Ares")
    reset = mailer._build_password_reset_message("a@example.test", "Anna", "https://x.example.test/r")
    assert reset["Subject"].startswith("Ares — ")
    assert reset.get_content().rstrip().endswith("— Ares")


def test_cross_validation_webhook_text():
    from services.market_data.notifier import build_alert_payload

    result = SimpleNamespace(is_alert=True, symbol="X", diff_bps=400, median_close="1", n_providers=3)
    payload = build_alert_payload([result], "2026-10-01", 300)
    assert payload["text"].startswith("Ares Cross-Validation Alert: ")


def test_backup_alert_texts_name_product():
    import backup_scheduler

    src = inspect.getsource(backup_scheduler)
    assert 'text="Ares: Offsite-Backup-Replikation fehlgeschlagen."' in src
    assert 'text="Ares: Geplantes Datenbank-Backup fehlgeschlagen."' in src


class _EmptyQuery:
    def __getattr__(self, _name):
        return lambda *a, **k: self

    def all(self):
        return []


def test_calendar_display_texts():
    from services.review_calendar_feed import _all_day_event, build_ics_feed

    feed = build_ics_feed(SimpleNamespace(query=lambda *a: _EmptyQuery()), SimpleNamespace(id="u1"))
    assert "X-WR-CALNAME:Ares" in feed.splitlines()
    event = _all_day_event(
        uid="uid-1", dtstamp="20260101T000000Z", due_date="2026-02-01",
        summary="Ares Review: Jahresreview -- Hans Muster", description="d",
    )
    assert "CATEGORIES:Ares,Review,Compliance" in event


def test_calendar_summary_and_download_name_in_source():
    from routers import review
    from services import review_calendar_feed

    assert 'summary = f"Ares Review: ' in inspect.getsource(review_calendar_feed)
    assert "filename=ares-reviews.ics" in inspect.getsource(review)
