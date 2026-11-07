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


def _pdf(text: str = FOOTER, fonts: tuple[str, ...] = ("Inter", "CormorantGaramond")) -> bytes:
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


def test_footer_prefix_is_from_the_country_pack_and_below_the_footer_cut():
    assert FOOTER.startswith("Dieses Dokument wurde in Übereinstimmung mit dem Bundesgesetz")
    assert len(FOOTER) == smoke.FOOTER_REQUIRED_PREFIX_CHARS
    max_chars = int(re.search(r"max_chars = (\d+)", FOOTER_SOURCE.read_text(encoding="utf-8")).group(1))
    assert smoke.FOOTER_REQUIRED_PREFIX_CHARS <= max_chars - 3


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


# --- C-853-01 (Codex 2026-11-05): Einbettung am Font-Stream, nicht am Namen ---
def _rewrite_fonts(pdf: bytes, mutate) -> bytes:
    """Jeden Seiten-Font mit /FontDescriptor an ``mutate(writer, fonts, key, font)``
    geben und das PDF neu schreiben."""
    import pypdf

    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf)))
    for page in writer.pages:
        fonts = page["/Resources"]["/Font"].get_object()
        for key in list(fonts.keys()):
            font = fonts[key].get_object()
            if "/FontDescriptor" in font:
                mutate(writer, fonts, key, font)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _drop_font_files(writer, fonts, key, font):
    descriptor = font["/FontDescriptor"].get_object()
    for name in smoke.FONT_FILE_KEYS:
        if name in descriptor:
            del descriptor[name]


def _empty_font_files(writer, fonts, key, font):
    descriptor = font["/FontDescriptor"].get_object()
    for name in smoke.FONT_FILE_KEYS:
        if name in descriptor:
            descriptor[name].get_object().set_data(b"")


def _font_file2_as_font_file3(writer, fonts, key, font):
    from pypdf.generic import NameObject

    descriptor = font["/FontDescriptor"].get_object()
    descriptor[NameObject("/FontFile3")] = descriptor["/FontFile2"]
    del descriptor["/FontFile2"]


def _as_type0(*, with_stream: bool = True, with_descendants: bool = True):
    """Einfachen TrueType-Font in einen Type0/CIDFontType2-Font umbauen
    (gleicher /BaseFont, gleicher /FontDescriptor)."""

    def mutate(writer, fonts, key, font):
        from pypdf.generic import ArrayObject, DictionaryObject, NameObject

        if not with_stream:
            _drop_font_files(writer, fonts, key, font)
        cid = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/CIDFontType2"),
            NameObject("/BaseFont"): font["/BaseFont"],
            NameObject("/FontDescriptor"): font.raw_get("/FontDescriptor"),
        })
        type0 = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): font["/BaseFont"],
            NameObject("/Encoding"): NameObject("/Identity-H"),
        })
        if with_descendants:
            type0[NameObject("/DescendantFonts")] = ArrayObject([writer._add_object(cid)])
        fonts[NameObject(key)] = writer._add_object(type0)

    return mutate


def test_c_853_01_reportlab_fonts_are_embedded_as_font_file2():
    import pypdf

    used, _ = smoke._font_resource_usage(pypdf.PdfReader(io.BytesIO(_pdf())).pages)
    embedded = {u.base_font: u.state for u in used if u.state.startswith("eingebettet (/FontFile2")}
    assert any("+Inter" in n for n in embedded) and any("+CormorantGaramond" in n for n in embedded)


def test_c_853_01_subset_name_without_font_stream_fails():
    pdf = _rewrite_fonts(_pdf(), _drop_font_files)
    with pytest.raises(smoke.SmokeError, match="Editorial-Font Inter nicht eingebettet.*ohne Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


def test_c_853_01_empty_font_stream_fails():
    pdf = _rewrite_fonts(_pdf(), _empty_font_files)
    with pytest.raises(smoke.SmokeError, match="Editorial-Font Inter nicht eingebettet.*leerer Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


def test_c_853_01_font_file3_stream_counts_as_embedded():
    pdf = _rewrite_fonts(_pdf(), _font_file2_as_font_file3)
    assert "1 Seite(n)" in smoke.check_pdf_bytes(pdf, "x.pdf", ())


def test_c_853_01_embedded_type0_cid_font_passes():
    import pypdf

    pdf = _rewrite_fonts(_pdf(), _as_type0())
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    subtypes = {
        str(f.get_object()["/Subtype"]) for f in reader.pages[0]["/Resources"]["/Font"].values()
    }
    assert "/Type0" in subtypes
    assert "1 Seite(n)" in smoke.check_pdf_bytes(pdf, "x.pdf", ())


def test_c_853_01_type0_without_descendant_stream_fails():
    pdf = _rewrite_fonts(_pdf(), _as_type0(with_stream=False))
    with pytest.raises(smoke.SmokeError, match="nicht eingebettet.*ohne Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", ())


def test_c_853_01_type0_without_descendant_fonts_fails():
    pdf = _rewrite_fonts(_pdf(), _as_type0(with_descendants=False))
    with pytest.raises(smoke.SmokeError, match="nicht eingebettet.*Type0 ohne /DescendantFonts"):
        smoke.check_pdf_bytes(pdf, "x.pdf", ())


# --- C-853-02 (Codex 2026-11-05): je TATSAECHLICH verwendeter Font-Resource ---
# Pruefgegenstand ist die Resource, mit der Text gezeigt wird -- nicht der
# /BaseFont-Name. Eine unbenutzte eingebettete Dublette belegt nichts.
EDITORIAL = ("+Inter", "+CormorantGaramond")


def _is_editorial(font) -> bool:
    return any(tag in str(font.get_object().get("/BaseFont", "")) for tag in EDITORIAL)


def _unembedded_copy(writer, font_ref, *, empty: bool = False):
    """Kopie der Font-Resource mit eigenem /FontDescriptor ohne (bzw. mit leerem)
    Font-Stream; gleicher /BaseFont, das Original bleibt unveraendert."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    font = font_ref.get_object()
    descriptor = font["/FontDescriptor"].get_object()
    stripped = DictionaryObject(
        {k: v for k, v in descriptor.items() if k not in smoke.FONT_FILE_KEYS}
    )
    if empty:
        stripped[NameObject("/FontFile2")] = writer._add_object(DecodedStreamObject())
    copy = DictionaryObject(dict(font.items()))
    copy[NameObject("/FontDescriptor")] = writer._add_object(stripped)
    return writer._add_object(copy)


def _own_font_dict(page):
    """Seite bekommt eigene /Resources und /Font (ReportLab teilt sie)."""
    from pypdf.generic import DictionaryObject, NameObject

    resources = DictionaryObject(dict(page["/Resources"].get_object().items()))
    fonts = DictionaryObject(dict(resources["/Font"].get_object().items()))
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    return fonts


def _writer(pdf: bytes):
    import pypdf

    return pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf)))


def _write(writer) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _set_contents(writer, page, data: bytes) -> None:
    from pypdf.generic import DecodedStreamObject, NameObject

    content = DecodedStreamObject()
    content.set_data(data)
    page[NameObject("/Contents")] = writer._add_object(content)


def _with_unused_embedded_duplicate(pdf: bytes, *, empty: bool = False) -> bytes:
    """Codex-Reproducer: der vom Inhalt verwendete Key zeigt auf eine Resource
    ohne Stream; das eingebettete Original bleibt unbenutzt unter ``<Key>Dup``."""
    from pypdf.generic import NameObject

    writer = _writer(pdf)
    for page in writer.pages:
        fonts = _own_font_dict(page)
        for key in list(fonts.keys()):
            if _is_editorial(fonts[key]):
                original = fonts.raw_get(key)
                fonts[NameObject(key + "Dup")] = original
                fonts[NameObject(key)] = _unembedded_copy(writer, original, empty=empty)
    return _write(writer)


def _two_page_pdf() -> bytes:
    from services.pdf.fonts import register_editorial_fonts

    assert register_editorial_fonts()
    buf = io.BytesIO()
    canvas = Canvas(buf)
    for _ in range(2):
        y = 800
        for font in ("Inter", "CormorantGaramond"):
            canvas.setFont(font, 6)
            canvas.drawString(20, y, FOOTER)
            y -= 20
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


def _second_page_unembedded(pdf: bytes, *, empty: bool = False) -> bytes:
    from pypdf.generic import NameObject

    writer = _writer(pdf)
    fonts = _own_font_dict(writer.pages[1])
    for key in list(fonts.keys()):
        if _is_editorial(fonts[key]):
            fonts[NameObject(key)] = _unembedded_copy(writer, fonts.raw_get(key), empty=empty)
    return _write(writer)


def _key_for(fonts, family: str) -> str:
    return next(k for k in fonts if f"+{family}" in str(fonts[k].get_object()["/BaseFont"]))


def _forms_pdf(*, nested: bool, embedded: bool) -> bytes:
    """Die Seite zeigt Text nur in Cormorant und ruft das Form-XObject /Fm0 auf;
    dort (bzw. im darin aufgerufenen /Inner) wird mit Inter Text gezeigt --
    eingebettet oder als Kopie ohne Stream. Die eingebettete Inter-Resource
    bleibt zusaetzlich unbenutzt in den Seiten-Resources deklariert."""
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject

    writer = _writer(_pdf(fonts=("CormorantGaramond",)))
    page = writer.pages[0]
    page_text = page.get_contents().get_data()
    fonts = _own_font_dict(page)
    inter_writer = _writer(_pdf(fonts=("Inter",)))
    inter_fonts = inter_writer.pages[0]["/Resources"]["/Font"]
    inter = writer._add_object(inter_fonts[_key_for(inter_fonts, "Inter")].get_object().clone(writer))
    fonts[NameObject("/FInterDeclared")] = inter
    font_ref = inter if embedded else _unembedded_copy(writer, inter)

    def form(content: bytes, resources):
        stream = DecodedStreamObject()
        stream.set_data(content)
        stream.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(600), FloatObject(600)]),
            NameObject("/Resources"): resources,
        })
        return writer._add_object(stream)

    top = form(b"BT /FX 6 Tf 20 600 Td (Formtext) Tj ET",
               DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/FX"): font_ref})}))
    if nested:
        top = form(b"q /Inner Do Q", DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Inner"): top})}))
    resources = page["/Resources"]
    xobjects = DictionaryObject(dict((resources.get("/XObject") or DictionaryObject()).items()))
    xobjects[NameObject("/Fm0")] = top
    resources[NameObject("/XObject")] = xobjects
    _set_contents(writer, page, page_text + b"\nq /Fm0 Do Q\n")
    return _write(writer)


def test_c_853_02_unused_embedded_duplicate_does_not_mask_used_font_without_stream():
    pdf = _with_unused_embedded_duplicate(_pdf())
    with pytest.raises(smoke.SmokeError, match=r"Editorial-Font Inter nicht eingebettet.*Seite 1 Seite /F[\w+]+ [A-Z]{6}\+Inter-Regular: ohne Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


def test_c_853_02_unused_embedded_duplicate_does_not_mask_used_empty_stream():
    pdf = _with_unused_embedded_duplicate(_pdf(), empty=True)
    with pytest.raises(smoke.SmokeError, match="Editorial-Font Inter nicht eingebettet.*leerer Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


@pytest.mark.parametrize("empty", [False, True], ids=["ohne_stream", "leerer_stream"])
def test_c_853_02_embedded_page_one_does_not_mask_unembedded_page_two(empty):
    assert "2 Seite(n)" in smoke.check_pdf_bytes(_two_page_pdf(), "x.pdf", (FOOTER,))
    pdf = _second_page_unembedded(_two_page_pdf(), empty=empty)
    with pytest.raises(smoke.SmokeError, match=r"verwendete Font-Resource nicht eingebettet: .*Seite 2 Seite /F[\w+]+ [A-Z]{6}\+Inter-Regular"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


def test_c_853_02_two_embedded_resources_of_one_family_pass():
    from pypdf.generic import NameObject

    writer = _writer(_pdf())
    fonts = _own_font_dict(writer.pages[0])
    for key in list(fonts.keys()):
        if _is_editorial(fonts[key]):
            fonts[NameObject(key + "Dup")] = fonts.raw_get(key)
    assert "1 Seite(n)" in smoke.check_pdf_bytes(_write(writer), "x.pdf", (FOOTER,))


@pytest.mark.parametrize("nested", [False, True], ids=["form", "form_in_form"])
def test_c_853_02_font_used_only_in_form_xobject_without_stream_fails(nested):
    pdf = _forms_pdf(nested=nested, embedded=False)
    where = "Seite>/Fm0>/Inner" if nested else "Seite>/Fm0"
    with pytest.raises(smoke.SmokeError, match=rf"Seite 1 {where} /FX [A-Z]{{6}}\+Inter-Regular: ohne Font-Stream"):
        smoke.check_pdf_bytes(pdf, "x.pdf", ())


@pytest.mark.parametrize("nested", [False, True], ids=["form", "form_in_form"])
def test_c_853_02_font_used_only_in_form_xobject_embedded_passes(nested):
    import pypdf

    pdf = _forms_pdf(nested=nested, embedded=True)
    used, _ = smoke._font_resource_usage(pypdf.PdfReader(io.BytesIO(pdf)).pages)
    inter = [u for u in used if "+Inter" in u.base_font]
    assert inter and all(u.where.startswith("Seite>/Fm0") for u in inter)
    assert "1 Seite(n)" in smoke.check_pdf_bytes(pdf, "x.pdf", ())


def test_c_853_02_type0_descendant_without_stream_masked_by_duplicate_fails():
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject

    writer = _writer(_pdf())
    fonts = _own_font_dict(writer.pages[0])
    for key in list(fonts.keys()):
        if not _is_editorial(fonts[key]):
            continue
        original = fonts.raw_get(key)
        stripped = _unembedded_copy(writer, original).get_object()

        def cid(descriptor):
            return writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType2"),
                NameObject("/BaseFont"): stripped["/BaseFont"],
                NameObject("/FontDescriptor"): descriptor,
            }))

        type0 = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): stripped["/BaseFont"],
            NameObject("/Encoding"): NameObject("/Identity-H"),
            # erster Descendant eingebettet, zweiter ohne Stream
            NameObject("/DescendantFonts"): ArrayObject([
                cid(original.get_object().raw_get("/FontDescriptor")),
                cid(stripped.raw_get("/FontDescriptor")),
            ]),
        })
        fonts[NameObject(key + "Dup")] = original
        fonts[NameObject(key)] = writer._add_object(type0)
    # Identity-H ohne /ToUnicode: Text nicht extrahierbar, deshalb ohne Pflichttext.
    with pytest.raises(smoke.SmokeError, match="Inter nicht eingebettet.*Type0-Descendant ohne Font-Stream"):
        smoke.check_pdf_bytes(_write(writer), "x.pdf", ())


def test_c_853_02_used_standard_14_font_without_embedding_fails():
    pdf = _pdf(fonts=("Inter", "CormorantGaramond", "Helvetica"))
    with pytest.raises(smoke.SmokeError, match="verwendete Font-Resource nicht eingebettet: .*Helvetica: ohne /FontDescriptor"):
        smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))


def test_c_853_02_declared_but_unused_standard_14_font_is_not_a_use():
    """ReportLab setzt je Seite ``/F1 12 Tf`` (Helvetica) ohne Textausgabe."""
    import pypdf

    used, declared = smoke._font_resource_usage(pypdf.PdfReader(io.BytesIO(_pdf())).pages)
    assert any(d.base_font == "Helvetica" for d in declared)
    assert not any(u.base_font == "Helvetica" for u in used)
    assert {u.base_font.split("+")[1] for u in used} == {"Inter-Regular", "CormorantGaramond-Regular"}


@pytest.mark.parametrize(
    "snippet,needle",
    [
        (b"BT 20 20 Td (x) Tj ET", "Textausgabe ohne Font"),
        (b"BT /Fnope 6 Tf 20 20 Td (x) Tj ET", r"/Fnope \?: Resource fehlt"),
        (b"q /Xnope Do Q", "nicht lesbar: ValueError: XObject /Xnope fehlt"),
    ],
    ids=["ohne_tf", "unbekannter_font_key", "unbekanntes_xobject"],
)
def test_c_853_02_unresolvable_font_use_fails_closed(snippet, needle):
    writer = _writer(_pdf())
    page = writer.pages[0]
    _set_contents(writer, page, snippet + b"\n" + page.get_contents().get_data())
    with pytest.raises(smoke.SmokeError, match=needle):
        smoke.check_pdf_bytes(_write(writer), "x.pdf", (FOOTER,))


def test_c_853_02_real_ares_pdfs_pass():
    """Echte Ares-Renderer: die Smoke-Dokumente Risikoprofil und Vertrag sowie
    die 19-seitige Anlagestrategie bestehen die verschaerfte Pruefung."""
    from datetime import date

    from services.pdf.base import AnlagestrategieData, PDFContext, RisikoprofilData, VertragData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(mandate_name="Hans Muster", advisor_name="Anna Berater",
                     advisor_org="Muster & Partner AG", report_date=date(2026, 5, 17),
                     audit_hash="abc123def456789012345678", locale="de-CH")
    renderer = ReportLabRenderer()
    pdfs = {
        "risikoprofil.pdf": renderer.render_risikoprofil(ctx, RisikoprofilData(
            risk_profile_label="Ausgewogen", risk_capacity_score=65, risk_tolerance_score=58,
            knowledge_services={"Anlageberatung": True}, knowledge_instruments={"Aktien": True},
            experience_years=8, suitability_note="kompatibel")),
        "vertrag.pdf": renderer.render_vertrag(ctx, VertragData(praeambel="P", haftungsklausel="H")),
        "anlagestrategie.pdf": renderer.render_anlagestrategie(ctx, AnlagestrategieData(
            target_allocation_bps={"equities": 4000, "bonds": 3000, "real_estate": 1500,
                                   "alternatives": 1000, "liquidity": 500},
            cma_expected_return_bps=485, cma_expected_vol_bps=1120, horizon_years=15,
            monte_carlo_stats={"p10": 80_000_000, "p50": 150_000_000, "p90": 250_000_000},
            optimizer_reasoning="Begruendung", risk_profile_label="Ausgewogen")),
    }
    for label, pdf in pdfs.items():
        summary = smoke.check_pdf_bytes(pdf, label, ())
        assert summary.startswith(label) and "verwendete Font-Resource(n) eingebettet" in summary


# --- N-853-6/7 (Pruefrunde 2026-11-07): eindeutige Orte, alle Inhaltstraeger ---
def _n(name: str):
    from pypdf.generic import NameObject

    return NameObject(name)


def _helvetica(writer):
    from pypdf.generic import DictionaryObject

    return writer._add_object(DictionaryObject({
        _n("/Type"): _n("/Font"), _n("/Subtype"): _n("/Type1"), _n("/BaseFont"): _n("/Helvetica"),
    }))


def _stream(writer, content: bytes, entries: dict | None = None):
    from pypdf.generic import DecodedStreamObject

    stream = DecodedStreamObject()
    stream.set_data(content)
    for key, value in (entries or {}).items():
        stream[_n(key)] = value
    return writer._add_object(stream)


def _font_resources(key: str, ref):
    from pypdf.generic import DictionaryObject

    return DictionaryObject({_n("/Font"): DictionaryObject({_n(key): ref})})


def _text(key: str) -> bytes:
    return f"BT {key} 6 Tf 10 10 Td (Text) Tj ET".encode()


def _base_writer():
    """Echtes ReportLab-PDF (Inter + Cormorant eingebettet) mit eigener Seiten-
    /Resources; liefert (writer, Seite, Font-Dict, eingebettete Inter-Resource)."""
    writer = _writer(_pdf())
    page = writer.pages[0]
    fonts = _own_font_dict(page)
    inter = fonts.raw_get(_key_for(fonts, "Inter"))
    return writer, page, fonts, inter


def _form(writer, content: bytes, resources):
    from pypdf.generic import ArrayObject, FloatObject

    return _stream(writer, content, {
        "/Type": _n("/XObject"), "/Subtype": _n("/Form"),
        "/BBox": ArrayObject([FloatObject(0), FloatObject(0), FloatObject(100), FloatObject(100)]),
        "/Resources": resources,
    })


def _add_annotation(writer, page, appearance: dict, **extra):
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject

    annot = DictionaryObject({
        _n("/Type"): _n("/Annot"), _n("/Subtype"): _n(extra.pop("subtype", "/Square")),
        _n("/Rect"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(10), FloatObject(10)]),
    })
    if appearance:
        annot[_n("/AP")] = DictionaryObject({_n(k): v for k, v in appearance.items()})
    for key, value in extra.items():
        annot[_n("/" + key)] = value
    annots = page.get("/Annots")
    annots = ArrayObject(list(annots)) if annots is not None else ArrayObject()
    annots.append(writer._add_object(annot))
    page[_n("/Annots")] = annots


def _check(writer, required=(FOOTER,)):
    return smoke.check_pdf_bytes(_write(writer), "x.pdf", required)


def test_n_853_6_second_annotation_with_same_key_is_checked():
    writer, page, _, inter = _base_writer()
    _add_annotation(writer, page, {"/N": _form(writer, _text("/FA"), _font_resources("/FA", inter))})
    assert "1 Seite(n)" in _check(writer)  # Positivkontrolle: Inter eingebettet
    helv = _helvetica(writer)
    _add_annotation(writer, page, {"/N": _form(writer, _text("/FA"), _font_resources("/FA", helv))})
    with pytest.raises(smoke.SmokeError, match=r"Seite 1 Annotation\[1\]/N /FA Helvetica: ohne /FontDescriptor"):
        _check(writer)


def test_n_853_6_appearance_state_dict_checks_every_state():
    from pypdf.generic import DictionaryObject

    writer, page, _, inter = _base_writer()
    states = DictionaryObject({
        _n("/On"): _form(writer, _text("/FA"), _font_resources("/FA", inter)),
        _n("/Off"): _form(writer, _text("/FA"), _font_resources("/FA", _helvetica(writer))),
    })
    _add_annotation(writer, page, {"/N": states})
    with pytest.raises(smoke.SmokeError, match=r"Annotation\[0\]/N/Off /FA Helvetica"):
        _check(writer)


@pytest.mark.parametrize("ap_key", ["/D", "/R"])
def test_n_853_7_down_and_rollover_appearances_are_checked(ap_key):
    writer, page, _, inter = _base_writer()
    _add_annotation(writer, page, {
        "/N": _form(writer, _text("/FA"), _font_resources("/FA", inter)),
        ap_key: _form(writer, _text("/FA"), _font_resources("/FA", _helvetica(writer))),
    })
    with pytest.raises(smoke.SmokeError, match=rf"Annotation\[0\]{ap_key} /FA Helvetica"):
        _check(writer)


def _tiling_pattern(writer, font_ref):
    from pypdf.generic import ArrayObject, FloatObject, NumberObject

    return _stream(writer, _text("/FP"), {
        "/Type": _n("/Pattern"), "/PatternType": NumberObject(1), "/PaintType": NumberObject(1),
        "/TilingType": NumberObject(1),
        "/BBox": ArrayObject([FloatObject(0), FloatObject(0), FloatObject(50), FloatObject(50)]),
        "/XStep": NumberObject(50), "/YStep": NumberObject(50),
        "/Resources": _font_resources("/FP", font_ref),
    })


@pytest.mark.parametrize("embedded", [True, False], ids=["inter", "helvetica"])
def test_n_853_7_text_in_tiling_pattern_is_checked(embedded):
    from pypdf.generic import DictionaryObject

    writer, page, _, inter = _base_writer()
    pattern = _tiling_pattern(writer, inter if embedded else _helvetica(writer))
    page["/Resources"][_n("/Pattern")] = DictionaryObject({_n("/P0"): pattern})
    _set_contents(writer, page, page.get_contents().get_data() + b"\n/Pattern cs /P0 scn 0 0 100 100 re f\n")
    if embedded:
        assert "1 Seite(n)" in _check(writer)
    else:
        with pytest.raises(smoke.SmokeError, match=r"Seite>Pattern/P0 /FP Helvetica"):
            _check(writer)


def test_n_853_7_text_in_smask_group_is_checked():
    from pypdf.generic import DictionaryObject

    writer, page, _, _ = _base_writer()
    group = _form(writer, _text("/FS"), _font_resources("/FS", _helvetica(writer)))
    smask = DictionaryObject({_n("/Type"): _n("/Mask"), _n("/S"): _n("/Luminosity"), _n("/G"): group})
    page["/Resources"][_n("/ExtGState")] = DictionaryObject({
        _n("/GS0"): DictionaryObject({_n("/Type"): _n("/ExtGState"), _n("/SMask"): smask})})
    _set_contents(writer, page, page.get_contents().get_data() + b"\nq /GS0 gs 0 0 10 10 re f Q\n")
    with pytest.raises(smoke.SmokeError, match=r"Seite>SMask/GS0 /FS Helvetica"):
        _check(writer)


def _type3(writer, inter, charproc: bytes, *, copied_font_file: bool):
    """Type3-Font /T3 (Glyph 'a'); optional mit aus Inter kopiertem /FontFile2
    im Descriptor -- der darf nicht als Einbettung zaehlen."""
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NumberObject

    t3 = DictionaryObject({
        _n("/Type"): _n("/Font"), _n("/Subtype"): _n("/Type3"),
        _n("/FontBBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(1), FloatObject(1)]),
        _n("/FontMatrix"): ArrayObject([FloatObject(0.001), FloatObject(0), FloatObject(0),
                                        FloatObject(0.001), FloatObject(0), FloatObject(0)]),
        _n("/CharProcs"): DictionaryObject({_n("/a"): _stream(writer, charproc)}),
        _n("/Encoding"): DictionaryObject({_n("/Type"): _n("/Encoding"),
                                           _n("/Differences"): ArrayObject([NumberObject(97), _n("/a")])}),
        _n("/FirstChar"): NumberObject(97), _n("/LastChar"): NumberObject(97),
        _n("/Widths"): ArrayObject([NumberObject(500)]),
        _n("/Resources"): _font_resources("/FH", _helvetica(writer)),
    })
    if copied_font_file:
        t3[_n("/FontDescriptor")] = inter.get_object().raw_get("/FontDescriptor")
    return writer._add_object(t3)


def test_n_853_7_type3_charproc_text_must_use_embedded_font():
    writer, page, fonts, inter = _base_writer()
    fonts[_n("/T3")] = _type3(writer, inter, b"500 0 d0 BT /FH 6 Tf (x) Tj ET", copied_font_file=True)
    _set_contents(writer, page, page.get_contents().get_data() + b"\nBT /T3 12 Tf 10 10 Td (a) Tj ET\n")
    with pytest.raises(smoke.SmokeError, match=r"Seite>/T3/CharProc/a /FH Helvetica: ohne /FontDescriptor"):
        _check(writer)


def test_n_853_7_type3_with_path_only_charprocs_is_embedded_but_no_editorial_proof():
    import pypdf

    writer, page, fonts, inter = _base_writer()
    fonts[_n("/T3")] = _type3(writer, inter, b"500 0 0 0 500 500 d1 0 0 500 500 re f",
                              copied_font_file=True)
    _set_contents(writer, page, page.get_contents().get_data() + b"\nBT /T3 12 Tf 10 10 Td (a) Tj ET\n")
    pdf = _write(writer)
    assert "1 Seite(n)" in smoke.check_pdf_bytes(pdf, "x.pdf", (FOOTER,))
    used, _ = smoke._font_resource_usage(pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert [u.state for u in used if u.key == "/T3"] == ["eingebettet (Type3, 1 CharProcs)"]


def test_n_853_7_type3_does_not_prove_editorial_embedding():
    """Ein Type3 mit Editorial-Namen und kopiertem /FontFile2 ersetzt nicht
    den eingebetteten Inter-Font."""
    writer = _writer(_pdf(fonts=("CormorantGaramond",)))
    page = writer.pages[0]
    fonts = _own_font_dict(page)
    inter_fonts = _writer(_pdf(fonts=("Inter",))).pages[0]["/Resources"]["/Font"]
    inter = writer._add_object(inter_fonts[_key_for(inter_fonts, "Inter")].get_object().clone(writer))
    t3 = _type3(writer, inter, b"500 0 0 0 500 500 d1 0 0 500 500 re f", copied_font_file=True)
    t3.get_object()[_n("/BaseFont")] = inter.get_object()["/BaseFont"]
    fonts[_n("/T3")] = t3
    _set_contents(writer, page, page.get_contents().get_data() + b"\nBT /T3 12 Tf 10 10 Td (a) Tj ET\n")
    with pytest.raises(smoke.SmokeError, match="Editorial-Font Inter nicht eingebettet"):
        smoke.check_pdf_bytes(_write(writer), "x.pdf", ())


def test_n_853_7_font_set_via_extgstate_is_checked():
    from pypdf.generic import ArrayObject, DictionaryObject, NumberObject

    writer, page, _, _ = _base_writer()
    page["/Resources"][_n("/ExtGState")] = DictionaryObject({_n("/GF"): DictionaryObject({
        _n("/Type"): _n("/ExtGState"), _n("/Font"): ArrayObject([_helvetica(writer), NumberObject(6)])})})
    _set_contents(writer, page, page.get_contents().get_data() + b"\nBT /GF gs 10 10 Td (x) Tj ET\n")
    with pytest.raises(smoke.SmokeError, match=r"Seite /GF/Font Helvetica"):
        _check(writer)


def _postscript_xobject(writer, page):
    from pypdf.generic import DictionaryObject

    page["/Resources"][_n("/XObject")] = DictionaryObject({
        _n("/PS0"): _stream(writer, b"%!", {"/Type": _n("/XObject"), "/Subtype": _n("/PS")})})
    _set_contents(writer, page, page.get_contents().get_data() + b"\n/PS0 Do\n")


def _shading_only_pattern_type(kind):
    def mutate(writer, page):
        from pypdf.generic import DictionaryObject, NumberObject

        page["/Resources"][_n("/Pattern")] = DictionaryObject({_n("/P9"): DictionaryObject({
            _n("/Type"): _n("/Pattern"), _n("/PatternType"): NumberObject(kind)})})
    return mutate


def _smask_without_group(writer, page):
    from pypdf.generic import DictionaryObject

    page["/Resources"][_n("/ExtGState")] = DictionaryObject({_n("/GS0"): DictionaryObject({
        _n("/SMask"): DictionaryObject({_n("/S"): _n("/Luminosity")})})})


def _widget_without_appearance(writer, page):
    from pypdf.generic import TextStringObject

    _add_annotation(writer, page, {}, subtype="/Widget", DA=TextStringObject("/Helv 0 Tf 0 g"))


def _need_appearances(writer, page):
    from pypdf.generic import BooleanObject, DictionaryObject

    writer._root_object[_n("/AcroForm")] = DictionaryObject({_n("/NeedAppearances"): BooleanObject(True)})


def _q_underflow(writer, page):
    _set_contents(writer, page, page.get_contents().get_data() + b"\nQ\n")


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (_postscript_xobject, r"XObject /PS0 nicht auswertbar \(Subtype /PS"),
        (_shading_only_pattern_type(3), r"Pattern /P9 nicht auswertbar \(PatternType 3"),
        (_smask_without_group, r"/SMask ohne Gruppe /G"),
        (_widget_without_appearance, r"Annotation\[0\] auf Seite 1: Text ohne Erscheinungsbild"),
        (_need_appearances, r"/NeedAppearances"),
        (_q_underflow, r"Q ohne q"),
    ],
    ids=["ps_xobject", "pattern_typ_3", "smask_ohne_g", "widget_ohne_ap", "need_appearances", "q_unterlauf"],
)
def test_n_853_7_unevaluable_content_carriers_fail_closed(mutate, needle):
    writer, page, _, _ = _base_writer()
    mutate(writer, page)
    with pytest.raises(smoke.SmokeError, match=needle):
        _check(writer)


def test_n_853_7_shading_pattern_is_not_a_text_carrier():
    writer, page, _, _ = _base_writer()
    _shading_only_pattern_type(2)(writer, page)
    assert "1 Seite(n)" in _check(writer)
