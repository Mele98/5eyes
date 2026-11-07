"""H8 Luecke 10 (Compliance-Audit 2026-11-07, Dok. 104): Vertretung und
Verfuegungsberechtigung nach ZGB (Vollmacht, Vorsorgeauftrag, Beistandschaft,
Gemeinschaftsdepot) dokumentarisch, mit Hinweis im Beratungsprotokoll-PDF.
An der Basis rot: keine Felder, kein Abschnitt.
"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, codes, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.clients import ClientRepresentation  # noqa: E402
from routers.clients import create_representation, revoke_representation  # noqa: E402
from schemas.clients import ClientRepresentationCreate, ClientRepresentationRevoke  # noqa: E402

def test_representation_fields_and_protocol_hint(sf):
    with pytest.raises(ValidationError):
        ClientRepresentationCreate(representation_type="vorsorgeauftrag", representative_name="Max",
                                   scope="Vermoegenssorge", evidence_reference="KESB-Entscheid 1")
    with pytest.raises(ValidationError):
        ClientRepresentationCreate(representation_type="gemeinschaftsdepot", representative_name="Max",
                                   scope="Depot", evidence_reference="Depotvertrag")
    from routers.pdf_reports import _protocol_representation_lines

    with sf() as db:
        adv = user(db, "adv-1")
        rep = create_representation(client_id="c-1", body=ClientRepresentationCreate(
            representation_type="beistandschaft", representative_name="Anna Beistand",
            scope="Vermoegensverwaltung (ZGB 395)", evidence_reference="KESB-Entscheid 2026/17",
            effective_from="2026-03-01"), request=Req(), db=db, current_user=adv)
        create_representation(client_id="c-1", body=ClientRepresentationCreate(
            representation_type="gemeinschaftsdepot", representative_name="Paul Muster",
            scope="Gemeinschaftsdepot Ehegatten", evidence_reference="Depotvertrag Bank X",
            disposal_rule="gemeinsam"), request=Req(), db=db, current_user=adv)
        lines = _protocol_representation_lines(db, mandate(db))
        assert len(lines) == 2
        assert any("Beistandschaft" in line and "KESB-Entscheid 2026/17" in line for line in lines)
        assert any("Verfuegung gemeinsam" in line for line in lines)
        revoke_representation(client_id="c-1", representation_id=rep.id,
                              body=ClientRepresentationRevoke(reason="Beistandschaft aufgehoben"),
                              request=Req(), db=db, current_user=adv)
        assert len(_protocol_representation_lines(db, mandate(db))) == 1
        assert db.query(ClientRepresentation).count() == 2  # Widerruf statt Loeschen


def test_protocol_pdf_renders_representation_section_with_vbvv_hint():
    import re
    from datetime import date
    from io import BytesIO

    from pypdf import PdfReader

    from services.pdf.base import PDFContext, ProtokollData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(mandate_name="Eva Muster", advisor_name="Berater", advisor_org="Firma",
                     report_date=date(2026, 11, 7), audit_hash="h8" * 12, locale="de-CH")
    data = ProtokollData(mandate_number="M-1", entries=[], representation_lines=(
        "Beistandschaft (ZGB 390 ff.): Anna Beistand -- Umfang: Vermoegensverwaltung; Beleg: KESB 1.",))
    pdf = ReportLabRenderer().render_protokoll(ctx, data)
    text = re.sub(r"\s+", " ", " ".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(pdf)).pages))
    assert "VERTRETUNG UND VERFÜGUNGSBERECHTIGUNG" in text
    assert "Anna Beistand" in text and "VBVV" in text
    empty = ReportLabRenderer().render_protokoll(ctx, ProtokollData(mandate_number="M-1", entries=[]))
    empty_text = " ".join(pg.extract_text() or "" for pg in PdfReader(BytesIO(empty)).pages)
    assert "VERTRETUNG UND" not in empty_text  # ohne Eintrag kein Abschnitt (Goldens unveraendert)


def test_alembic_postgres_ddl_creates_representation_table():
    from h8_support import h8_postgres_ddl

    assert "CREATE TABLE client_representations" in h8_postgres_ddl()
