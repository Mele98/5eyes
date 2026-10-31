"""RESOURCE-002 (Codex-Audit 2026-08-27, docs/audits/2026-08-27-request-
ingestion-and-resource-governance-audit.md): ContractDocumentCreate.title
und .content_json hatten keine Zeichenschranke -- ein 4-MiB-title/
content_json wurde vom Audit klaglos akzeptiert.

Diese Tests decken nur die schema-seitige Feldschranke ab (Field(max_length))
-- die weitergehenden Forderungen des Audits (striktes typisiertes Schema
statt beliebiger JSON-String, normalisierte Notes-Tabelle, History-
Pagination, Retention-/Legal-Hold-Policy, Tenant-Speicherquota) bleiben ein
groesseres, separates Vorhaben.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.review import ContractDocumentCreate  # noqa: E402


def test_title_over_200_chars_is_rejected():
    with pytest.raises(ValidationError):
        ContractDocumentCreate(document_type="Sonstiges", title="x" * 201)


def test_title_at_exactly_200_chars_is_accepted():
    doc = ContractDocumentCreate(document_type="Sonstiges", title="x" * 200)
    assert len(doc.title) == 200


def test_empty_title_is_rejected():
    with pytest.raises(ValidationError):
        ContractDocumentCreate(document_type="Sonstiges", title="")


def test_content_json_over_500000_chars_is_rejected():
    with pytest.raises(ValidationError):
        ContractDocumentCreate(
            document_type="Sonstiges", title="ok", content_json="x" * 500_001,
        )


def test_content_json_at_exactly_500000_chars_is_accepted():
    doc = ContractDocumentCreate(
        document_type="Sonstiges", title="ok", content_json="x" * 500_000,
    )
    assert len(doc.content_json) == 500_000


def test_content_json_none_remains_valid():
    doc = ContractDocumentCreate(document_type="Sonstiges", title="ok")
    assert doc.content_json is None
