"""Signierbares Artefakt eines Vertragsdokuments (CERT-SIGNED-PUBLICATION-001).

Eine Signatur bestaetigt genau die Bytes, die dem Kunden vorgelegt wurden.
Vor diesem Gate akzeptierte ``routers/review.py::sign_document`` jede
Dokumentzeile -- auch einen leeren Entwurf ohne archiviertes PDF
(SIGN-CONTEXT-001) und ein PDF, dessen gespeicherte Checksumme nicht zu den
gespeicherten Bytes passt (SIGN-HASH-001).

``assert_signable_artifact(doc)`` prueft VOR jeder Mutation:

1. archivierte PDF-Bytes, ``checksum_sha256`` und ``content_hash`` sind
   vorhanden (sonst gibt es nichts, was signiert werden koennte);
2. die Bytes sind gueltiges Base64 und ihr SHA-256 entspricht
   ``checksum_sha256`` (sonst wurde das Artefakt nach der Archivierung
   veraendert oder falsch abgelegt).

Fehler -> ``DomainError`` (409, detail={reason_code, message, channel}); der
zentrale Handler bildet ihn byte-gleich zur frueheren ``HTTPException`` ab
(K-2b).
``content_hash`` ist ein Fingerprint der Fachdaten VOR dem Rendern
(services/document_archive.py) und laesst sich aus den Bytes nicht
nachrechnen -- hier wird nur seine Existenz verlangt.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from core.reason_codes import DomainError, ReasonCode

SIGNATURE_ARTIFACT_MISSING = ReasonCode.SIGNATURE_ARTIFACT_MISSING.value
SIGNATURE_ARTIFACT_HASH_MISMATCH = ReasonCode.SIGNATURE_ARTIFACT_HASH_MISMATCH.value
# SIGN-IDENTITY-001: ein Berater-/Admin-Principal behauptet die Kundenrolle.
CLIENT_SIGNATURE_REQUIRES_CLIENT_PRINCIPAL = ReasonCode.CLIENT_SIGNATURE_REQUIRES_CLIENT_PRINCIPAL.value


def _blocked(reason_code: str, message: str) -> DomainError:
    return DomainError(reason_code, message, http_status=409, extra={"channel": "signature"})


def assert_signable_artifact(doc: Any) -> None:
    pdf_base64 = str(getattr(doc, "pdf_base64", None) or "").strip()
    checksum = str(getattr(doc, "checksum_sha256", None) or "").strip().lower()
    content_hash = str(getattr(doc, "content_hash", None) or "").strip()
    if not pdf_base64 or not checksum or not content_hash:
        raise _blocked(
            SIGNATURE_ARTIFACT_MISSING,
            "Das Dokument kann nicht unterzeichnet werden: es liegt kein "
            "archiviertes PDF mit Pruefsumme vor. Bitte das Dokument zuerst "
            "erzeugen (PDF-Export), dann die archivierte Version unterzeichnen.",
        )
    try:
        pdf_bytes = base64.b64decode(pdf_base64, validate=True)
    except (binascii.Error, ValueError):
        pdf_bytes = None
    if not pdf_bytes or hashlib.sha256(pdf_bytes).hexdigest() != checksum:
        raise _blocked(
            SIGNATURE_ARTIFACT_HASH_MISMATCH,
            "Das Dokument kann nicht unterzeichnet werden: die archivierten "
            "PDF-Bytes passen nicht zur gespeicherten Pruefsumme. Bitte das "
            "Dokument neu erzeugen.",
        )
