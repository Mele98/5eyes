"""KN3-B: Umlaute in Kunden-Texten (E2E3-03, N-917R2-04) und Firmenkopf (E2E3-04).

Ergaenzt den Kunden-PDF-Waechter (tests/test_livetest_kn3_b_customer_pdf_guard.py,
eigener CI-Job, rendert alle Kunden-PDFs) um Pruefungen, die in jedem
Backend-Shard laufen:

* E2E3-03: ``services/recommendation_release_gate.py`` (Aufsichtsstatus der
  Kundeninformation, KYC-/Kundeninformations-Sperrtexte) und die Text-Erzeuger
  des Advisory-Reports enthalten in Prosa-Literalen keine ASCII-Umschrift mehr.
  H-168 hatte das fuer das Release-Gate gemeldet, der Diff war leer (Dok. 118).
* N-917R2-04: datengebundene Sub-Anlageklassen-/Produktnamen erscheinen in
  Kunden-PDFs in der Anzeigeform (``core.customer_terms``).
* E2E3-04: der Firmenkopf kommt aus den Firmenangaben des Mandanten
  (rechtlicher Name, sonst Anzeigename), nie aus dem Beraternamen.

Gegenproben: Umschrift zurueck in ein Label -> Literal-Waechter rot;
``customer_term`` ohne Ersetzung -> rot; alter Rueckfall ``advisor_org = ...
or advisor_name`` bzw. ``brand = ... or ctx.advisor_name`` -> rot.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from tests.test_livetest_kn3_b_customer_pdf_guard import umlaut_transliterations

BACKEND = Path(__file__).resolve().parents[1]
# Text-Erzeuger kundenwirksamer Texte (Kundeninformation, Advisory-Report).
TEXT_PRODUCERS = (
    "services/recommendation_release_gate.py",
    "services/advisory_report.py",
    "services/methodology_audit.py",
    "services/liquidity_cascade_audit.py",
    # In H-168 als umgestellt gemeldet, aber nur teilweise (H-168 Nachtrag 1).
    "services/portfolio_handoff.py",
)


def _prose_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if " " in node.value:
                yield node.lineno, node.value


_CODE = re.compile(r"[A-Za-z0-9]*_[A-Za-z0-9_]*|True|False|None")


def test_customer_text_producers_have_no_ascii_umlaut_transliteration():
    offenders = {}
    for rel in TEXT_PRODUCERS:
        for lineno, value in _prose_literals(BACKEND / rel):
            # Bezeichner mit Unterstrich (SQL-Spalten, Codes) und Python-Literale
            # in Log-Texten sind keine Prosa.
            words = umlaut_transliterations(_CODE.sub(" ", value))
            if words:
                offenders[f"{rel}:{lineno}"] = words
    assert not offenders, offenders


def test_client_information_supervision_label_has_real_umlauts():
    from services.recommendation_release_gate import LEGAL_PROFILE_FIELDS, SUPERVISION_LABELS

    assert SUPERVISION_LABELS["vermoegensverwalter_finig"] == "Vermögensverwalter mit Bewilligung der FINMA (FINIG)"
    # Der Schluessel bleibt (gespeicherter Wert in tenant_legal_profiles).
    assert dict(LEGAL_PROFILE_FIELDS)["business_activity"] == "Tätigkeitsfeld"
    for label in (*SUPERVISION_LABELS.values(), *dict(LEGAL_PROFILE_FIELDS).values()):
        assert not umlaut_transliterations(label), label


def test_data_terms_are_shown_with_umlauts_in_customer_pdfs():
    from services.pdf.components.header import _esc
    from core.customer_terms import customer_term

    assert customer_term("Aktien Schwellenlaender") == "Aktien Schwellenländer"
    assert customer_term("Musterprodukt Thema Gluecksspiel CHF-abgesichert") == "Musterprodukt Thema Glücksspiel CHF-abgesichert"
    # Kein allgemeines Wort: Prosa wird an der Quelle korrigiert, nie halb umgestellt.
    assert customer_term("Liquiditaet (unabhaengig)") == "Liquiditaet (unabhaengig)"
    assert customer_term(None) == ""
    # Eigennamen bleiben unveraendert (abschliessende Liste, keine generische Ersetzung).
    assert customer_term("Mueller Vermoegensverwaltung AG") == "Mueller Vermoegensverwaltung AG"
    # Die zentralen Escape-Helfer der Kunden-PDFs wenden die Anzeigeform an.
    assert _esc("Aktien Schwellenlaender & Co") == "Aktien Schwellenländer &amp; Co"


def _session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'kn3_firm.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_firm_name_comes_from_the_firm_settings_never_from_the_advisor(tmp_path):
    from types import SimpleNamespace

    from models.tenant import Tenant, TenantLegalProfile
    from services.recommendation_release_gate import firm_display_name

    engine, sf = _session(tmp_path)
    now = "2026-11-19T00:00:00.000Z"
    mandate = SimpleNamespace(tenant_id="main", client_id="c-kn3")
    try:
        with sf() as db:
            db.add(Tenant(id="main", display_name="Default Tenant", slug="main", hosting_tier="tier1",
                          license_status="active", is_active=1, created_at=now, updated_at=now))
            db.commit()
            # Platzhalter der Default-Zeile ist keine Firma; ohne Angaben bleibt der Kopf leer.
            assert firm_display_name(db, mandate) is None
            db.get(Tenant, "main").display_name = "Testfirma Fiktiv Einzel GmbH"
            db.commit()
            assert firm_display_name(db, mandate) == "Testfirma Fiktiv Einzel GmbH"
            # Rechtliche Angaben (Kundeninformation) gehen vor.
            db.add(TenantLegalProfile(id="lp-1", tenant_id="main", legal_name="Testfirma Fiktiv Einzel GmbH (rechtlich)",
                                      revision=1, created_at=now, updated_at=now))
            db.commit()
            assert firm_display_name(db, mandate) == "Testfirma Fiktiv Einzel GmbH (rechtlich)"
    finally:
        engine.dispose()


def _render(ctx):
    from services.pdf.base import AnlagestrategieData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    data = AnlagestrategieData(target_allocation_bps={"equities": 5000, "bonds": 5000, "real_estate": 0,
                                                      "alternatives": 0, "liquidity": 0},
                               cma_expected_return_bps=300, cma_expected_vol_bps=800, horizon_years=10,
                               advisory_wealth_rappen=100_000_00)
    reader = PdfReader(BytesIO(ReportLabRenderer().render_anlagestrategie(ctx, data)))
    return " ".join((page.extract_text() or "") for page in reader.pages), str(reader.metadata.get("/Title", ""))


def test_header_without_firm_never_brands_the_advisor():
    from services.pdf.base import PDFContext

    ctx = PDFContext(mandate_name="Muster", advisor_name="Erika Testberaterin", advisor_org=None,
                     report_date=date(2026, 11, 19), audit_hash="abc123def456789012345678", locale="de-CH")
    text, title = _render(ctx)
    assert "ERIKA TESTBERATERIN" not in text, text[:400]
    assert "Erika Testberaterin" not in title
    firm = PDFContext(mandate_name="Muster", advisor_name="Erika Testberaterin",
                      advisor_org="Testfirma Fiktiv Einzel GmbH", report_date=date(2026, 11, 19),
                      audit_hash="abc123def456789012345678", locale="de-CH")
    text, title = _render(firm)
    assert "TESTFIRMA FIKTIV EINZEL GMBH" in text and title.startswith("Testfirma Fiktiv Einzel GmbH")
