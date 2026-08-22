"""Server-seitiges Dokumenten-Archiv fuer generierte Kunden-PDFs.

Kundenfeedback 2026-08-20: Berater wollen in den Stammdaten eine "saubere,
sachliche Ablage" mit History -- verschiedene PDF-Versionen ueber die Zeit,
FINMA-tauglich (wer hat wann welches Dokument erzeugt, unveraenderlich).

ContractDocument (models/review.py) sah dafuer bereits version/
supersedes_id/checksum_sha256/pdf_path vor, aber niemand befuellte sie --
jeder Report-Endpoint (routers/pdf_reports.py) rendert PDF-Bytes rein
in-memory und schickt sie direkt an den Client, ohne Spur in der DB.

archive_generated_pdf() haengt sich an genau diese Endpoints und legt bei
jeder Generierung eine neue, unveraenderliche Version an -- AUSSER der
zugrundeliegende Fachinhalt ist unveraendert zur zuletzt archivierten
Version desselben (mandate_id, document_type) (content_hash-Vergleich):
wiederholtes Anschauen desselben unveraenderten Dokuments erzeugt dann
keinen Doppel-Eintrag, sondern liefert den bestehenden Datensatz zurueck.
Damit bleibt die History eine echte Aenderungs-Story ("verschiedene
PDFs"), kein Klick-Log.

Bewusst NICHT ueber die PDF-Byte-Checksum dedupliziert: ReportLab bettet
pro Rendering einen wechselnden Font-Subset-Tag ein (services/pdf/
reportlab_renderer.py), zwei Renderings desselben Inhalts ergeben also
unterschiedliche Bytes. content_hash wird vom Aufrufer VOR dem Rendern aus
dem *Data-Dataclass (services/pdf/base.py) berechnet und ist damit ein
echtes Fachinhalt-Fingerprint.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.review import ContractDocument
from models.users import User
from services.audit import log as audit_log


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def content_hash_for(data) -> str:
    """SHA-256 ueber ein *Data-Dataclass aus services/pdf/base.py.

    Aufrufer berechnen dies VOR dem Rendern (aus den Fachdaten, nicht aus
    den PDF-Bytes) und uebergeben das Ergebnis an archive_generated_pdf()
    -- siehe Modul-Docstring fuer den Grund.
    """
    payload = json.dumps(dataclasses.asdict(data), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def archive_generated_pdf(
    db: Session,
    *,
    mandate_id: str,
    document_type: str,
    title: str,
    pdf_bytes: bytes,
    content_hash: str,
    current_user: User,
    ip_address: str | None = None,
) -> ContractDocument:
    latest = (
        db.query(ContractDocument)
        .filter(
            ContractDocument.mandate_id == mandate_id,
            ContractDocument.document_type == document_type,
            ContractDocument.deleted_at.is_(None),
        )
        .order_by(ContractDocument.version.desc())
        .first()
    )
    if latest is not None and latest.content_hash == content_hash:
        return latest

    now = _now()
    doc = ContractDocument(
        id=new_uuid(),
        mandate_id=mandate_id,
        document_type=document_type,
        title=title,
        pdf_base64=base64.b64encode(pdf_bytes).decode("ascii"),
        checksum_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        content_hash=content_hash,
        pdf_generated_at=now,
        # "Archiviert" ist ein vorbestehender, bisher ungenutzter Status-Wert
        # (CHECK-Constraint in 5eyes_schema_v4.0_FINAL.sql) -- passt exakt:
        # ein automatisch abgelegtes Dokument ist weder Entwurf noch signiert.
        status="Archiviert",
        signed_by_advisor=0,
        signed_by_client=0,
        version=(latest.version + 1) if latest is not None else 1,
        supersedes_id=latest.id if latest is not None else None,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    audit_log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="contract_documents",
        record_id=doc.id,
        action="CREATE",
        mandate_id=mandate_id,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(doc)
    return doc
