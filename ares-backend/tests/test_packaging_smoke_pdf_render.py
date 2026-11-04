"""B-9 (Rest, Dok. 100 I2): Packaging-Smoke rendert PDFs in der gepackten EXE.

``/health/ready`` sagt nichts ueber die PDF-Erzeugung: fehlen Fonts oder
Laenderpaket-Texte im Bundle oder fehlt ein Modul, scheitert erst der
PDF-Aufruf -- oder der Renderer faellt still auf Standard-Fonts zurueck.
Der Smoke legt deshalb ueber die API Admin, Kunde und Mandat an, laesst
Kunden-PDFs rendern und prueft die Bytes. Hier: die Pruefung der Bytes,
der API-Ablauf gegen eine Attrappe und die Verdrahtung im Start-Smoke.
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import json
import re
import sys
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

REPO_ROOT = Path(__file__).resolve().parents[2]
FOOTER_SOURCE = REPO_ROOT / "ares-backend" / "services" / "pdf" / "components" / "footer.py"


def _load_smoke():
    name = "_ares_packaging_smoke_pdf_under_test"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "packaging_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()
FOOTER = smoke.expected_footer_disclaimer()


def _pdf(text: str = FOOTER + " Erstellt am 02.11.2026.", fonts: tuple[str, ...] = ("Inter", "CormorantGaramond")) -> bytes:
    from services.pdf.fonts import register_editorial_fonts

    assert register_editorial_fonts(), "Editorial-Fonts im Quellbaum nicht registrierbar"
    buf = io.BytesIO()
    canvas = Canvas(buf)
    y = 800
    for font in fonts or ("Helvetica",):
        canvas.setFont(font, 6)
        canvas.drawString(20, y, text)
        y -= 20
    canvas.showPage()
    canvas.save()
    return buf.getvalue()


def test_footer_check_uses_full_country_pack_text_and_creation_date():
    """N-858-1: die Fusszeile kuerzt nicht mehr (footer.py), der Smoke prueft
    deshalb den vollen Laenderpaket-Text samt "Erstellt am"."""
    from jurisdictions.documents import default_documents

    assert FOOTER == default_documents().text(smoke.FOOTER_DISCLAIMER_KEY)
    assert FOOTER.endswith("Ergebnisse.")
    assert smoke.FOOTER_CREATED_MARKER == "Erstellt am"
    assert "(footer, FOOTER_CREATED_MARKER)" in inspect.getsource(smoke.run_pdf_render_smoke)
    assert not re.search(r"max_chars|\[:\s*\w*max", FOOTER_SOURCE.read_text(encoding="utf-8")), (
        "Fusszeile darf den Pflichttext nicht kuerzen"
    )


def test_truncated_footer_in_pdf_fails():
    with pytest.raises(smoke.SmokeError, match="Pflichttext fehlt"):
        smoke.check_pdf_bytes(_pdf(FOOTER[:217] + "..."), "x.pdf", (FOOTER,))


def test_rendered_pdf_with_footer_and_editorial_fonts_passes():
    summary = smoke.check_pdf_bytes(_pdf(), "x.pdf", (FOOTER,))
    assert summary.startswith("x.pdf (") and "1 Seite(n)" in summary


def test_non_pdf_response_fails():
    with pytest.raises(smoke.SmokeError, match="kein PDF"):
        smoke.check_pdf_bytes(b"<html>Fehler</html>", "x.pdf", (FOOTER,))


def test_truncated_pdf_fails():
    with pytest.raises(smoke.SmokeError, match="unvollstaendig"):
        smoke.check_pdf_bytes(_pdf()[:-1100], "x.pdf", (FOOTER,))


def test_corrupt_pdf_body_fails():
    pdf = _pdf()
    broken = pdf[:10] + b"\x00" * (len(pdf) - 1100) + pdf[-1090:]
    with pytest.raises(smoke.SmokeError, match="nicht lesbar|Pflichttext|Editorial-Font"):
        smoke.check_pdf_bytes(broken, "x.pdf", (FOOTER,))


def test_pdf_without_country_pack_footer_fails():
    with pytest.raises(smoke.SmokeError, match="Pflichttext fehlt"):
        smoke.check_pdf_bytes(_pdf(text="Anderer Text"), "x.pdf", (FOOTER,))


def test_stock_font_fallback_fails():
    with pytest.raises(smoke.SmokeError, match="Editorial-Font Inter nicht eingebettet"):
        smoke.check_pdf_bytes(_pdf(fonts=("Helvetica",)), "x.pdf", (FOOTER,))


def test_missing_serif_family_fails():
    with pytest.raises(smoke.SmokeError, match="Editorial-Font CormorantGaramond nicht eingebettet"):
        smoke.check_pdf_bytes(_pdf(fonts=("Inter",)), "x.pdf", (FOOTER,))


def test_font_fallback_warning_in_backend_log_fails():
    smoke.assert_no_font_fallback("INFO alles gut\n")
    with pytest.raises(smoke.SmokeError, match="Font-Fallback"):
        smoke.assert_no_font_fallback(
            "WARNING | services.pdf.fonts | Editorial PDF fonts missing in X: Inter-Regular.ttf."
        )


class _FakeApi:
    def __init__(self, pdf: bytes, overrides: dict | None = None):
        self.pdf = pdf
        self.overrides = overrides or {}
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, url, *, method="GET", json_body=None, headers=None, timeout=5.0):
        path = url.split("http://smoke", 1)[1]
        self.calls.append((method, path, dict(headers or {})))
        for key, response in self.overrides.items():
            if key in path:
                return response
        if path == "/auth/bootstrap-admin":
            return 201, {}, json.dumps({"access_token": "tok", "user": {"id": "u1"}}).encode()
        if path == "/clients":
            assert json_body["advisor_id"] == "u1"
            return 201, {}, json.dumps({"id": "c1"}).encode()
        if path == "/clients/c1/mandates":
            return 201, {}, json.dumps({"id": "m1"}).encode()
        if path.startswith("/mandates/m1/reports/"):
            return 200, {"Content-Type": "application/pdf"}, self.pdf
        return 404, {}, b"{}"


def test_render_flow_creates_mandate_and_checks_each_pdf(monkeypatch):
    api = _FakeApi(_pdf())
    monkeypatch.setattr(smoke, "http_request", api)
    rendered = smoke.run_pdf_render_smoke("http://smoke")
    assert [r.split(" ")[0] for r in rendered] == ["risikoprofil.pdf", "vertrag.pdf"]
    paths = [c[1] for c in api.calls]
    assert paths == [
        "/auth/bootstrap-admin", "/clients", "/clients/c1/mandates",
        "/mandates/m1/reports/risikoprofil.pdf", "/mandates/m1/reports/vertrag.pdf",
    ]
    assert all(c[2].get("Authorization") == "Bearer tok" for c in api.calls[1:])


@pytest.mark.parametrize(
    "key,response,needle",
    [
        ("/auth/bootstrap-admin", (409, {}, b"{}"), "Ersteinrichtung"),
        ("/clients/c1/mandates", (422, {}, b"{}"), "Mandat anlegen"),
        ("vertrag.pdf", (500, {"Content-Type": "application/json"}, b'{"detail":"x"}'),
         "vertrag.pdf antwortet HTTP 500"),
        ("risikoprofil.pdf", (200, {"Content-Type": "text/html"}, b"<html>"),
         "risikoprofil.pdf antwortet HTTP 200 \\(text/html\\)"),
    ],
    ids=["bootstrap_refused", "mandate_refused", "render_error", "wrong_content_type"],
)
def test_render_flow_fails_closed(monkeypatch, key, response, needle):
    monkeypatch.setattr(smoke, "http_request", _FakeApi(_pdf(), {key: response}))
    with pytest.raises(smoke.SmokeError, match=needle):
        smoke.run_pdf_render_smoke("http://smoke")


def test_render_flow_with_fallback_pdf_fails(monkeypatch):
    monkeypatch.setattr(smoke, "http_request", _FakeApi(_pdf(fonts=("Helvetica",))))
    with pytest.raises(smoke.SmokeError, match="Editorial-Font"):
        smoke.run_pdf_render_smoke("http://smoke")


def test_start_smoke_renders_pdfs_and_rejects_font_fallback():
    source = inspect.getsource(smoke.run_start_smoke)
    assert "run_pdf_render_smoke(base)" in source
    assert "assert_no_font_fallback(logtext)" in source
    assert source.index("run_pdf_render_smoke(base)") < source.index("stop_process(proc, port, grace)")
