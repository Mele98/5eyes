"""CCX-09 / CCX-P1: Integritaet eines versiegelten Beratungsentscheids.

Der Root-Hash (``envelope_hash``) entsteht aus den kanonischen Bytes des
Payloads, und der Payload enthaelt die Kind-Hashes aller Bindungen sowie den
Manifest-Hash. Jede Mutation eines Kindes (anderer Kind-Hash, fehlende oder
zusaetzliche Bindung, veraendertes Manifest) bricht damit die Kette:

* Payload nicht kanonisch / Root-Hash weicht ab / Identitaet (Mandant,
  Mandat, Schema, Waehrung, Sprache) passt nicht zur Zeile
  -> ``CCX_ENVELOPE_HASH_MISMATCH``
* Status nicht SEALED/SUPERSEDED oder Siegelfelder fehlen
  -> ``CCX_ENVELOPE_UNSEALED``
* Bindungszeilen != Bindungen im Payload -> ``CCX_BINDING_MISSING``
* Manifestzeile fehlt, ihr Hash laesst sich nicht aus den gespeicherten
  Komponenten reproduzieren oder weicht vom Payload/der Bindung ab
  -> ``CCX_INPUT_MANIFEST_MISMATCH``

Rein funktional: die Zeilen liest ``services/advisory_decision_envelope.py``.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from core.advisory_envelope_codec import (
    BINDING_SCHEMA,
    ENVELOPE_PAYLOAD_SCHEMA,
    MANIFEST_COMPONENTS,
    CanonicalPayloadError,
    Obj,
    SortedList,
    canonical_bytes,
    envelope_hash,
    is_sha256_hex,
    manifest_hash,
    parse_canonical,
    root_hash,
)
from core.evidence import ADVISORY_ENVELOPE_SCHEMA
from core.reason_codes import ReasonCode
from services.effective_input_manifest import build_effective_input_record

MANIFEST_BINDING_KIND = "effective_input_manifest"
_BINDING_FIELDS = ("binding_kind", "ordinal", "object_type", "object_id", "object_version", "child_hash")
_CHILDREN_KIND = "children"


def _children_root(children: Mapping[str, Any]) -> str:
    """Root-Hash einer reinen Kind-Abbildung ``kind -> child_hash`` (gleiche
    Root-Domaene wie der Envelope; Kinder nach Art sortiert, NFC)."""
    schema = Obj((("bindings", SortedList(BINDING_SCHEMA, ("binding_kind", "ordinal", "object_id"))),))
    bindings = [
        {"binding_kind": str(kind), "ordinal": 0, "object_type": _CHILDREN_KIND,
         "object_id": str(kind), "object_version": None, "child_hash": value}
        for kind, value in children.items()
    ]
    return root_hash(canonical_bytes({"bindings": bindings}, schema))


def verify_root_hash(envelope: Mapping[str, Any]) -> bool:
    """True genau dann, wenn der gespeicherte Root-Hash aus dem Inhalt folgt.

    Formen: ``{"canonical_payload_json", "envelope_hash"}`` (Zeile),
    ``{"payload", "envelope_hash"}`` oder ``{"children", "root_hash"}``.
    Alle Hashes sind domaenensepariert (Vertrag §3)."""
    try:
        if "canonical_payload_json" in envelope:
            parse_canonical(envelope["canonical_payload_json"], ENVELOPE_PAYLOAD_SCHEMA)
            canonical = str(envelope["canonical_payload_json"]).encode("utf-8")
            return root_hash(canonical) == envelope.get("envelope_hash")
        if "payload" in envelope:
            return envelope_hash(envelope["payload"])[1] == envelope.get("envelope_hash")
        if "children" in envelope:
            children = envelope["children"]
            if not isinstance(children, Mapping) or not all(is_sha256_hex(v) for v in children.values()):
                return False
            return _children_root(children) == envelope.get("root_hash")
    except (CanonicalPayloadError, TypeError, ValueError):
        return False
    return False


def _binding_tuple(item: Any) -> tuple:
    get = item.get if isinstance(item, Mapping) else (lambda name: getattr(item, name, None))
    return tuple(get(name) for name in _BINDING_FIELDS)


def envelope_integrity_defect(
    envelope: Any,
    bindings: Iterable[Any],
    manifest: Any | None,
) -> tuple[str, str] | None:
    """``None`` oder ``(reason_code, detail)`` fuer eine Envelope-Zeile samt
    ihrer Bindungs- und Manifestzeile. Prueft in fester Reihenfolge: Siegel,
    Root-Hash, Identitaet, Bindungen, Manifest."""
    status = getattr(envelope, "status", None)
    if status not in ("SEALED", "SUPERSEDED") or not getattr(envelope, "sealed_at", None) \
            or not getattr(envelope, "sealed_by", None):
        return ReasonCode.CCX_ENVELOPE_UNSEALED, "status"
    text = getattr(envelope, "canonical_payload_json", None)
    stored_hash = getattr(envelope, "envelope_hash", None)
    if not isinstance(text, str) or not is_sha256_hex(stored_hash):
        return ReasonCode.CCX_ENVELOPE_HASH_MISMATCH, "payload"
    try:
        payload = parse_canonical(text, ENVELOPE_PAYLOAD_SCHEMA)
    except CanonicalPayloadError:
        return ReasonCode.CCX_ENVELOPE_HASH_MISMATCH, "canonical"
    if root_hash(text.encode("utf-8")) != stored_hash:
        return ReasonCode.CCX_ENVELOPE_HASH_MISMATCH, "root"
    identity = {
        "schema_version": ADVISORY_ENVELOPE_SCHEMA,
        "tenant_id": getattr(envelope, "tenant_id", None),
        "mandate_id": getattr(envelope, "mandate_id", None),
        "locale": getattr(envelope, "locale", None),
        "base_currency": getattr(envelope, "base_currency", None),
    }
    if getattr(envelope, "schema_version", None) != ADVISORY_ENVELOPE_SCHEMA or any(
        payload.get(key) != value for key, value in identity.items()
    ):
        return ReasonCode.CCX_ENVELOPE_HASH_MISMATCH, "identity"
    stored = sorted(_binding_tuple(row) for row in bindings)
    expected = sorted(_binding_tuple(item) for item in payload["bindings"])
    if stored != expected:
        return ReasonCode.CCX_BINDING_MISSING, "bindings"
    manifest_bindings = [item for item in payload["bindings"] if item["binding_kind"] == MANIFEST_BINDING_KIND]
    if len(manifest_bindings) != 1:
        return ReasonCode.CCX_BINDING_MISSING, "manifest_binding"
    if manifest is None or str(getattr(manifest, "id", "")) != manifest_bindings[0]["object_id"]:
        return ReasonCode.CCX_INPUT_MANIFEST_MISMATCH, "manifest_row"
    record = build_effective_input_record({
        "tenant_id": getattr(manifest, "tenant_id", None),
        "mandate_id": getattr(manifest, "mandate_id", None),
        **{name: getattr(manifest, name, None) for name in MANIFEST_COMPONENTS},
        "engine_version": getattr(manifest, "engine_version", None),
        "random_stream_id": getattr(manifest, "random_stream_id", None),
        "rounding_policy_version": getattr(manifest, "rounding_policy_version", None),
    })
    try:
        recomputed = manifest_hash(record)
    except CanonicalPayloadError:
        return ReasonCode.CCX_INPUT_MANIFEST_MISMATCH, "manifest_canonical"
    if not (
        recomputed == getattr(manifest, "manifest_hash", None)
        == payload["effective_input_manifest_hash"] == manifest_bindings[0]["child_hash"]
    ) or getattr(manifest, "tenant_id", None) != identity["tenant_id"] \
            or getattr(manifest, "mandate_id", None) != identity["mandate_id"]:
        return ReasonCode.CCX_INPUT_MANIFEST_MISMATCH, "manifest_hash"
    return None


__all__ = ["MANIFEST_BINDING_KIND", "envelope_integrity_defect", "verify_root_hash"]
