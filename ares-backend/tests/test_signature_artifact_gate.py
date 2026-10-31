"""CERT-SIGNED-PUBLICATION-001: services/signature_artifact.py.

SIGN-CONTEXT-001: ohne archiviertes PDF, Pruefsumme und content_hash gibt es
nichts zu signieren. SIGN-HASH-001: die Pruefsumme wird vor jeder Signatur
aus den gespeicherten Bytes neu berechnet.
"""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.reason_codes import DomainError  # noqa: E402  K-2b: Gates werfen DomainError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services.signature_artifact import (  # noqa: E402
    SIGNATURE_ARTIFACT_HASH_MISMATCH,
    SIGNATURE_ARTIFACT_MISSING,
    assert_signable_artifact,
)
from signable_document_fixture import archived_pdf_fields  # noqa: E402


def _doc(**overrides):
    return SimpleNamespace(**{**archived_pdf_fields(), **overrides})


def test_archived_document_with_matching_checksum_is_signable():
    assert_signable_artifact(_doc())


def test_checksum_comparison_ignores_case():
    fields = archived_pdf_fields()
    assert_signable_artifact(_doc(checksum_sha256=fields["checksum_sha256"].upper()))


@pytest.mark.parametrize("field", ["pdf_base64", "checksum_sha256", "content_hash"])
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_missing_artifact_part_blocks(field, empty):
    with pytest.raises(DomainError) as exc:
        assert_signable_artifact(_doc(**{field: empty}))
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == SIGNATURE_ARTIFACT_MISSING


@pytest.mark.parametrize("overrides", [
    {"checksum_sha256": hashlib.sha256(b"andere Bytes").hexdigest()},
    {"pdf_base64": base64.b64encode(b"nachtraeglich veraendert").decode("ascii")},
    {"pdf_base64": "kein base64 !!"},
])
def test_byte_checksum_drift_blocks(overrides):
    with pytest.raises(DomainError) as exc:
        assert_signable_artifact(_doc(**overrides))
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == SIGNATURE_ARTIFACT_HASH_MISMATCH
