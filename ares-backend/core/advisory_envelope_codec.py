"""CCX-P1: kanonische Serialisierung ``ares/advisory-envelope/1`` (Vertrag
2026-11-13 §3).

Ein Beratungsentscheid wird genau einmal als unveraenderlicher Envelope
versiegelt. Sein Hash muss sich Jahre spaeter aus denselben Feldern exakt
reproduzieren lassen und darf weder von der Python-Version, der
Dict-Reihenfolge, der Datenbank noch von der Darstellung abhaengen. Dieses
Modul erzeugt die kanonischen Bytes:

* UTF-8, Unicode NFC, keine BOM; kompaktes JSON ohne Leerzeichen.
* Objektschluessel in der im **Schema** festgelegten Reihenfolge (nicht
  alphabetisch); unbekannte und fehlende Felder sind ein Fehler; ``null``
  wird explizit uebertragen.
* Strings bleiben Strings, Booleans bleiben Booleans, Integer bleiben Integer
  (signed 64 bit). IEEE-Floats, ``NaN``, Infinity, ``Decimal`` und Bytes
  sind verboten -- Geld steht in Minor Units, Quoten in bps,
  Wahrscheinlichkeiten in ppm.
* UTC-Zeit ausschliesslich ``YYYY-MM-DDTHH:MM:SS.ffffffZ``.
* Listen werden fachlich sortiert (Sortierschluessel steht im Schema); ein
  doppelter Sortierschluessel ist ein Fehler (sonst waere die Reihenfolge
  nicht eindeutig).
* Hash: SHA-256 ueber ``Domaene + kanonische Bytes``, lowercase 64-hex; die
  Domaene stammt aus ``core.evidence`` (Root bzw. ``.../<kind>`` fuer
  Kind-Hashes).

Daneben die Projektion bestehender Datenbankzeilen (``row_projection``) fuer
Kind-Hashes ueber Fachobjekte, deren Spalten zum Teil Gleitkommawerte
speichern: solche Werte werden NICHT als JSON-Zahl, sondern als exakte,
endliche Dezimal-Zeichenkette (``repr``) gebunden; ``NaN``/Infinity sind auch
dort ein Fehler.

Keine DB-ID, die erst nach dem Hash entsteht, darf Teil desselben Hashes
sein -- die Schemata unten enthalten deshalb weder die Envelope-ID noch
Zeitstempel der Versiegelung (identische Inputs -> identischer Hash).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import unicodedata
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from core.evidence import (
    ADVISORY_ENVELOPE_SCHEMA,
    advisory_domain,
    domain_sha256_hex,
)

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1
_HEX = frozenset("0123456789abcdef")


class CanonicalPayloadError(ValueError):
    """Payload verletzt den Serialisierungsvertrag (fail-closed)."""


# ── Feldtypen ────────────────────────────────────────────────────────────────


class _Type:
    nullable = False

    def encode(self, value: Any, path: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class _Str(_Type):
    def __init__(self, *, nullable: bool = False, allow_empty: bool = False,
                 const: str | None = None) -> None:
        self.nullable = nullable
        self.allow_empty = allow_empty
        self.const = const

    def encode(self, value: Any, path: str) -> str:
        if value is None:
            if self.nullable:
                return "null"
            raise CanonicalPayloadError(f"{path}: null nicht erlaubt")
        text = canonical_text(value, path)
        if not text and not self.allow_empty:
            raise CanonicalPayloadError(f"{path}: leere Zeichenkette")
        if self.const is not None and text != self.const:
            raise CanonicalPayloadError(f"{path}: erwartet {self.const!r}")
        return _dump_str(text)


class _Int(_Type):
    def __init__(self, *, nullable: bool = False, minimum: int | None = None) -> None:
        self.nullable = nullable
        self.minimum = minimum

    def encode(self, value: Any, path: str) -> str:
        if value is None:
            if self.nullable:
                return "null"
            raise CanonicalPayloadError(f"{path}: null nicht erlaubt")
        number = canonical_int(value, path)
        if self.minimum is not None and number < self.minimum:
            raise CanonicalPayloadError(f"{path}: {number} < {self.minimum}")
        return str(number)


class _Bool(_Type):
    def __init__(self, *, nullable: bool = False) -> None:
        self.nullable = nullable

    def encode(self, value: Any, path: str) -> str:
        if value is None and self.nullable:
            return "null"
        if type(value) is not bool:
            raise CanonicalPayloadError(f"{path}: Boolean erwartet")
        return "true" if value else "false"


class _Hash(_Type):
    def __init__(self, *, nullable: bool = False) -> None:
        self.nullable = nullable

    def encode(self, value: Any, path: str) -> str:
        if value is None:
            if self.nullable:
                return "null"
            raise CanonicalPayloadError(f"{path}: null nicht erlaubt")
        if not is_sha256_hex(value):
            raise CanonicalPayloadError(f"{path}: kein lowercase SHA-256-Hex")
        return _dump_str(value)


class _Utc(_Type):
    def __init__(self, *, nullable: bool = False) -> None:
        self.nullable = nullable

    def encode(self, value: Any, path: str) -> str:
        if value is None:
            if self.nullable:
                return "null"
            raise CanonicalPayloadError(f"{path}: null nicht erlaubt")
        if not is_canonical_utc(value):
            raise CanonicalPayloadError(f"{path}: UTC-Zeit YYYY-MM-DDTHH:MM:SS.ffffffZ erwartet")
        return _dump_str(value)


class Obj(_Type):
    """Objekt mit fester Feldreihenfolge ``fields = ((name, type), ...)``."""

    def __init__(self, fields: Sequence[tuple[str, _Type]], *, nullable: bool = False) -> None:
        names = [name for name, _ in fields]
        if len(names) != len(set(names)):
            raise ValueError("doppelter Feldname im Schema")
        self.fields = tuple(fields)
        self.names = tuple(names)
        self.nullable = nullable

    def encode(self, value: Any, path: str) -> str:
        if value is None and self.nullable:
            return "null"
        if not isinstance(value, Mapping):
            raise CanonicalPayloadError(f"{path}: Objekt erwartet")
        unknown = sorted(str(k) for k in value if k not in self.names)
        if unknown:
            raise CanonicalPayloadError(f"{path}: unbekannte Felder {unknown}")
        missing = [name for name in self.names if name not in value]
        if missing:
            raise CanonicalPayloadError(f"{path}: fehlende Felder {missing}")
        parts = [
            _dump_str(name) + ":" + kind.encode(value[name], f"{path}.{name}")
            for name, kind in self.fields
        ]
        return "{" + ",".join(parts) + "}"


class SortedList(_Type):
    """Liste, fachlich sortiert nach ``sort_fields`` (Feldnamen des Elements)."""

    def __init__(self, item: Obj, sort_fields: Sequence[str]) -> None:
        missing = [f for f in sort_fields if f not in item.names]
        if missing or not sort_fields:
            raise ValueError(f"Sortierfelder nicht im Element-Schema: {missing}")
        self.item = item
        self.sort_fields = tuple(sort_fields)

    def encode(self, value: Any, path: str) -> str:
        if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
            raise CanonicalPayloadError(f"{path}: Liste erwartet")
        items = list(value)
        encoded: list[tuple[tuple, str]] = []
        for index, element in enumerate(items):
            text = self.item.encode(element, f"{path}[{index}]")
            encoded.append((self._key(element, f"{path}[{index}]"), text))
        keys = [k for k, _ in encoded]
        if len(keys) != len(set(keys)):
            raise CanonicalPayloadError(f"{path}: doppelter Sortierschluessel {self.sort_fields}")
        encoded.sort(key=lambda pair: pair[0])
        return "[" + ",".join(text for _, text in encoded) + "]"

    def _key(self, element: Mapping, path: str) -> tuple:
        key: list[tuple[int, Any]] = []
        for name in self.sort_fields:
            raw = element.get(name)
            # null sortiert vor jedem Wert; Strings nach NFC-Codepoints.
            if raw is None:
                key.append((0, ""))
            elif isinstance(raw, str):
                key.append((1, canonical_text(raw, f"{path}.{name}")))
            else:
                key.append((1, canonical_int(raw, f"{path}.{name}")))
        return tuple(key)


STR = _Str()
STR_NULLABLE = _Str(nullable=True)
INT = _Int()
INT_NULLABLE = _Int(nullable=True)
NON_NEGATIVE_INT = _Int(minimum=0)
BOOL = _Bool()
HASH = _Hash()
HASH_NULLABLE = _Hash(nullable=True)
UTC = _Utc()
UTC_NULLABLE = _Utc(nullable=True)


def const(value: str) -> _Str:
    return _Str(const=value)


# ── Skalare ──────────────────────────────────────────────────────────────────


def canonical_text(value: Any, path: str = "value") -> str:
    if not isinstance(value, str):
        raise CanonicalPayloadError(f"{path}: Zeichenkette erwartet")
    text = unicodedata.normalize("NFC", value)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:  # einzelne Surrogate
        raise CanonicalPayloadError(f"{path}: kein gueltiges UTF-8") from exc
    if text.startswith("﻿"):
        raise CanonicalPayloadError(f"{path}: BOM nicht erlaubt")
    return text


def canonical_int(value: Any, path: str = "value") -> int:
    if type(value) is not int:  # bool/float/Decimal/str sind keine Integer
        raise CanonicalPayloadError(f"{path}: Integer erwartet (keine Floats/Booleans)")
    if not INT64_MIN <= value <= INT64_MAX:
        raise CanonicalPayloadError(f"{path}: ausserhalb signed 64 bit")
    return value


def is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def is_canonical_utc(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 27 or not value.endswith("Z"):
        return False
    if value[4] != "-" or value[7] != "-" or value[10] != "T" or value[13] != ":" \
            or value[16] != ":" or value[19] != ".":
        return False
    try:
        _dt.datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        return False
    return True


def utc_now() -> str:
    """Aktuelle UTC-Zeit im Vertragsformat (fuer Zeilenmetadaten, nie im Hash)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dump_str(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


# ── Kanonische Bytes und Hash ────────────────────────────────────────────────


def canonical_bytes(payload: Mapping[str, Any], schema: Obj) -> bytes:
    """Kanonische UTF-8-Bytes von ``payload`` nach ``schema``."""
    return schema.encode(payload, "$").encode("utf-8")


def root_hash(canonical: bytes) -> str:
    """Envelope-Hash: SHA-256 ueber Root-Domaene + kanonische Bytes."""
    return domain_sha256_hex(advisory_domain(), canonical)


def child_hash(kind: str, canonical: bytes) -> str:
    """Kind-Hash: gleichartig domaenensepariert (``.../<kind>``)."""
    return domain_sha256_hex(advisory_domain(kind), canonical)


def parse_canonical(text: str, schema: Obj) -> dict[str, Any]:
    """Liest gespeichertes kanonisches JSON und prueft, dass es byte-gleich
    wieder erzeugt wird (sonst ``CanonicalPayloadError``)."""
    def _no_float(raw: str) -> Any:
        raise CanonicalPayloadError("Gleitkommazahl im kanonischen Payload")

    def _no_constant(raw: str) -> Any:
        raise CanonicalPayloadError(f"{raw} im kanonischen Payload")

    try:
        data = json.loads(text, parse_float=_no_float, parse_constant=_no_constant)
    except json.JSONDecodeError as exc:
        raise CanonicalPayloadError("kein gueltiges JSON") from exc
    if canonical_bytes(data, schema) != text.encode("utf-8"):
        raise CanonicalPayloadError("gespeicherter Payload ist nicht kanonisch")
    return data


# ── Projektion bestehender Zeilen fuer Kind-Hashes ───────────────────────────


def _projection_scalar(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(canonical_int(value, path))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalPayloadError(f"{path}: NaN/Infinity nicht erlaubt")
        return _dump_str(repr(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalPayloadError(f"{path}: NaN/Infinity nicht erlaubt")
        return _dump_str(format(value.normalize(), "f"))
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return _dump_str(value.isoformat())
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _dump_str("hex:" + bytes(value).hex())
    if isinstance(value, str):
        return _dump_str(canonical_text(value, path))
    raise CanonicalPayloadError(f"{path}: nicht projizierbarer Typ {type(value).__name__}")


def row_projection(columns: Sequence[str], values: Callable[[str], Any], path: str) -> str:
    """Eine Zeile als JSON-Objekt in Spaltenreihenfolge des Schemas."""
    return "{" + ",".join(
        _dump_str(name) + ":" + _projection_scalar(values(name), f"{path}.{name}")
        for name in columns
    ) + "}"


def rows_child_hash(kind: str, columns: Sequence[str], rows: Sequence[Any],
                    sort_key: Callable[[Any], tuple]) -> str:
    """Kind-Hash ueber eine fachlich sortierte Zeilenmenge.

    ``rows`` sind Objekte mit Attributzugriff (ORM) oder Mappings;
    ``columns`` ist die Spaltenliste aus dem ORM-Mapping (Schema-Reihenfolge).
    Die Spaltenliste selbst ist Teil der Hash-Eingabe, damit eine
    Schemaaenderung nie still denselben Hash ergibt.
    """
    def _getter(row: Any) -> Callable[[str], Any]:
        if isinstance(row, Mapping):
            return row.get
        return lambda name: getattr(row, name)

    ordered = sorted(rows, key=sort_key)
    keys = [sort_key(row) for row in ordered]
    if len(keys) != len(set(keys)):
        raise CanonicalPayloadError(f"{kind}: doppelter Sortierschluessel")
    body = (
        "{" + _dump_str("columns") + ":[" + ",".join(_dump_str(c) for c in columns) + "],"
        + _dump_str("rows") + ":["
        + ",".join(row_projection(columns, _getter(row), f"{kind}[{i}]") for i, row in enumerate(ordered))
        + "]}"
    )
    return child_hash(kind, body.encode("utf-8"))


def none_sort_key(value: Any) -> tuple[int, Any]:
    """Sortierschluessel-Baustein: ``None`` vor jedem Wert, sonst als String."""
    return (0, "") if value is None else (1, str(value))


# ── Schemata ``ares/advisory-envelope/1`` ────────────────────────────────────

# Reihenfolge der Bindings: (kind, ordinal, object_id) -- Vertrag §3.
BINDING_SCHEMA = Obj((
    ("binding_kind", STR),
    ("ordinal", NON_NEGATIVE_INT),
    ("object_type", STR),
    ("object_id", STR),
    ("object_version", INT_NULLABLE),
    ("child_hash", HASH),
))

ENVELOPE_PAYLOAD_SCHEMA = Obj((
    ("schema_version", const(ADVISORY_ENVELOPE_SCHEMA)),
    ("tenant_id", STR),
    ("mandate_id", STR),
    ("locale", STR),
    ("base_currency", STR),
    ("rounding_policy_version", STR),
    ("predecessor_envelope_hash", HASH_NULLABLE),
    ("effective_input_manifest_hash", HASH),
    ("bindings", SortedList(BINDING_SCHEMA, ("binding_kind", "ordinal", "object_id"))),
))

MANIFEST_KIND = "effective-input-manifest"
MANIFEST_SCHEMA_VERSION = ADVISORY_ENVELOPE_SCHEMA + "/" + MANIFEST_KIND
# Komponenten des Effective-Input-Manifests (Vertrag §4), Schema-Reihenfolge.
MANIFEST_COMPONENTS: tuple[str, ...] = (
    "client_hash", "mandate_hash", "goals_hash", "cashflows_hash", "risk_hash",
    "preference_hash", "cma_hash", "policy_hash", "constraints_hash", "holdings_hash",
)
MANIFEST_SCHEMA = Obj(
    (("schema_version", const(MANIFEST_SCHEMA_VERSION)),
     ("tenant_id", STR_NULLABLE),
     ("mandate_id", STR_NULLABLE))
    + tuple((name, _Str(nullable=True)) for name in MANIFEST_COMPONENTS)
    + (("engine_version", STR_NULLABLE),
       ("random_stream_id", STR_NULLABLE),
       ("rounding_policy_version", STR_NULLABLE))
)

CACHE_SCOPE_KIND = "cache-scope"
CACHE_SCOPE_SCHEMA = Obj((
    ("tenant_id", STR),
    ("mandate_id", STR),
    ("envelope_hash", STR),
    ("consumer_contract_version", STR),
))


def manifest_hash(record: Mapping[str, Any]) -> str:
    """Manifest-Hash (Kind-Hash ``effective-input-manifest``)."""
    return child_hash(MANIFEST_KIND, canonical_bytes(record, MANIFEST_SCHEMA))


def envelope_hash(payload: Mapping[str, Any]) -> tuple[str, str]:
    """``(canonical_payload_json, envelope_hash)`` eines Envelope-Payloads."""
    canonical = canonical_bytes(payload, ENVELOPE_PAYLOAD_SCHEMA)
    return canonical.decode("utf-8"), root_hash(canonical)


__all__ = [
    "BINDING_SCHEMA",
    "CACHE_SCOPE_KIND",
    "CACHE_SCOPE_SCHEMA",
    "CanonicalPayloadError",
    "ENVELOPE_PAYLOAD_SCHEMA",
    "MANIFEST_COMPONENTS",
    "MANIFEST_KIND",
    "MANIFEST_SCHEMA",
    "MANIFEST_SCHEMA_VERSION",
    "Obj",
    "SortedList",
    "canonical_bytes",
    "canonical_int",
    "canonical_text",
    "child_hash",
    "envelope_hash",
    "is_canonical_utc",
    "is_sha256_hex",
    "manifest_hash",
    "none_sort_key",
    "parse_canonical",
    "root_hash",
    "row_projection",
    "rows_child_hash",
    "utc_now",
]
