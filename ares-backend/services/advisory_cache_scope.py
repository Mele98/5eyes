"""CCX-10 / CCX-P1: Cache-Scope fuer Beratungsartefakte.

Ein gecachtes Beratungsergebnis gehoert genau einem Mandanten, einem Mandat
und einem versiegelten Entscheid. Der Schluessel ist deshalb der
domaenenseparierte Kind-Hash (``ares/advisory-envelope/1/cache-scope``) ueber
``(tenant_id, mandate_id, envelope_hash, consumer_contract_version)`` --
ein Mandatswechsel A -> B -> A, ein anderer Mandant oder ein neuer Envelope
kann nie denselben Eintrag treffen.

Ohne versiegelten Entscheid steht dort der explizite Marker ``"none"``
(kein Hash, kollidiert also nie mit einem echten Envelope).
"""
from __future__ import annotations

from core.advisory_envelope_codec import (
    CACHE_SCOPE_KIND,
    CACHE_SCOPE_SCHEMA,
    canonical_bytes,
    child_hash,
)

NO_ENVELOPE = "none"
ADVISORY_REPORT_CONSUMER = "ares/advisory-report-cache/1"


def advisory_cache_key(
    tenant_id: str,
    mandate_id: str,
    envelope_hash: str | None,
    consumer_contract_version: str = ADVISORY_REPORT_CONSUMER,
) -> str:
    """Lowercase 64-hex Cache-Schluessel (fail-closed bei leerem Scope)."""
    record = {
        "tenant_id": tenant_id,
        "mandate_id": mandate_id,
        "envelope_hash": envelope_hash or NO_ENVELOPE,
        "consumer_contract_version": consumer_contract_version,
    }
    return child_hash(CACHE_SCOPE_KIND, canonical_bytes(record, CACHE_SCOPE_SCHEMA))


__all__ = ["ADVISORY_REPORT_CONSUMER", "NO_ENVELOPE", "advisory_cache_key"]
