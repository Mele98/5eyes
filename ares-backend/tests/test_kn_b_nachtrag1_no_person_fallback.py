"""KN-B Nachtrag 1: kein Personenname als Fallback in Kunden-PDFs.

Befund (H-168, CTO-Entscheid): Cover, Banner-Header, Einzelauszug-Cover und die
PDF-Metadaten fielen ohne Firmen- und Beratername auf einen fest verdrahteten
Personennamen zurueck. Jetzt bleibt die Zeile leer bzw. entfaellt -- es wird
nichts erfunden. Fehlende Firmenangaben sperrt bereits das bestehende Gate
(``client_onboarding_findings`` / ``CLIENT_INFORMATION_TENANT_DATA_MISSING``).

Waechter: der Name (Vor- und Nachname, auch einzeln) steht in keinem Literal
unter ``ares-backend`` (ausser Tests/Skripten) und ``ares-desktop/frontend``.
Digest-basiert, damit der Name selbst nicht im Repo steht.

Gegenprobe: alten Fallback in ``header.py`` zuruecksetzen -> rot.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[2]
NAME_DIGESTS = {
    "9306811d7f87e136896a67900a88a1b8c1a58db5f10afaf380c2cd21b4708921",
    "411d22060c84a20f83e3a96faa4e2f378066564bedf262780b9fdb03f4a0816e",
}
TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]{5,}")
SUFFIXES = {".py", ".js", ".html", ".ts", ".tsx", ".json", ".css"}
SKIP_PARTS = {"node_modules", "dist", "vendor", "tests", "__pycache__", "scripts", "coverage"}


def _hits(text: str) -> set[str]:
    return {hashlib.sha256(tok.lower().encode()).hexdigest()[:12]
            for tok in TOKEN.findall(text) if hashlib.sha256(tok.lower().encode()).hexdigest() in NAME_DIGESTS}


def _sources():
    for root in (REPO / "ares-backend", REPO / "ares-desktop" / "frontend"):
        for path in root.rglob("*"):
            if path.suffix in SUFFIXES and path.is_file() and not (SKIP_PARTS & set(path.relative_to(root).parts)):
                yield path


def test_no_person_name_literal_in_product_sources():
    found = {}
    for path in _sources():
        hits = _hits(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            found[path.relative_to(REPO).as_posix()] = sorted(hits)
    assert found == {}, found


def test_guard_detects_name_tokens():
    assert _hits("org = ctx.advisor_org or " + "Ema" + "nuele") and _hits("Konz" + "elmann")


def test_pdf_without_firm_and_advisor_invents_no_name():
    from services.pdf.base import AnlagestrategieData, PDFContext
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(mandate_name="Muster", advisor_name="", advisor_org="", report_date=date(2026, 11, 19),
                     audit_hash="abc123def456789012345678", locale="de-CH")
    data = AnlagestrategieData(target_allocation_bps={"equities": 5000, "bonds": 5000, "real_estate": 0,
                                                      "alternatives": 0, "liquidity": 0},
                               cma_expected_return_bps=300, cma_expected_vol_bps=800, horizon_years=10,
                               advisory_wealth_rappen=100_000_00)
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, data)
    reader = PdfReader(BytesIO(pdf))
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    assert not _hits(text)
    assert not _hits(str(reader.metadata.get("/Title", "")))
    assert not str(reader.metadata.get("/Title", "")).startswith(" - ")
