"""Testhelfer: archiviertes, pruefsummengesichertes PDF fuer Vertragsdokumente.

CERT-SIGNED-PUBLICATION-001: ``sign_document`` signiert nur noch Dokumente
mit archivierten PDF-Bytes, passender ``checksum_sha256`` und
``content_hash`` (services/signature_artifact.py) -- genau das, was
``services/document_archive.py::archive_generated_pdf`` ablegt. Positivtests
der Signatur bilden diesen realen Zustand ab, statt einen leeren Entwurf zu
signieren.
"""
from __future__ import annotations

import base64
import hashlib

_PDF_BYTES = b"%PDF-1.4\n% signable test artefact\n%%EOF\n"


def archived_pdf_fields(pdf_bytes: bytes = _PDF_BYTES) -> dict:
    return {
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "checksum_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "content_hash": hashlib.sha256(b"content:" + pdf_bytes).hexdigest(),
    }


def attach_archived_pdf(session, doc) -> None:
    """Setzt die Archiv-Felder auf einem bestehenden ContractDocument."""
    for key, value in archived_pdf_fields().items():
        setattr(doc, key, value)
    session.commit()
    session.refresh(doc)
