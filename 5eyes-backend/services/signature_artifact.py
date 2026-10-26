"""Signierbares Artefakt eines Vertragsdokuments (CERT-SIGNED-PUBLICATION-001).

Eine Signatur bestaetigt genau die Bytes, die dem Kunden vorgelegt wurden.
Vor diesem Gate akzeptierte ``routers/review.py::sign_document`` jede
Dokumentzeile -- auch einen leeren Entwurf ohne archiviertes PDF
(SIGN-CONTEXT-001) und ein PDF, dessen gespeicherte Checksumme nicht zu den
gespeicherten Bytes passt (SIGN-HASH-001).

``assert_signable_artifact(doc)`` prueft VOR jeder Mutation:

1. archivierte PDF-Bytes, ``checksum_sha256`` und ``content_hash`` sind
   vorhanden (sonst gibt es nichts, was signiert werden koennte).

Fehler -> ``HTTPException(409, detail={reason_code, message})``.
``content_hash`` ist ein Fingerprint der Fachdaten VOR dem Rendern
(services/document_archive.py) und laesst sich aus den Bytes nicht
nachrechnen -- hier wird nur seine Existenz verlangt.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

SIGNATURE_ARTIFACT_MISSING = "SIGNATURE_ARTIFACT_MISSING"


def _blocked(reason_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"reason_code": reason_code, "message": message, "channel": "signature"},
    )


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
