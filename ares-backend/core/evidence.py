"""K-1 (A2 M4): kanonische Serialisierung und Evidence-Hash -- eine Quelle.

Belege (Signoffs, Snapshots, Integritaetsnachweise, Handoffs, Depot-
Snapshots, Ledger) werden als SHA-256 ueber eine kanonische JSON-Form
gebunden. Diese Form ist ein Regulierungsvertrag: ein gespeicherter Hash
muss sich auch Jahre spaeter aus denselben Feldern exakt reproduzieren
lassen. Bisher hat jedes Modul seine eigene ``json.dumps(...)``-Zeile
gefuehrt; die Kanonisierung unterschied sich dabei in Details, die ein
anderes Byte-Ergebnis erzeugen (``ensure_ascii``, Trennzeichen,
``default=str``, Sortierung).

Dieses Modul haelt jede im Bestand vorkommende Kanonisierung als
**benanntes Schema** fest. Ein Schema ist eine eingefrorene Menge von
``json.dumps``-Argumenten; seine Bytes duerfen sich nie aendern (sonst
gelten gespeicherte Belege als manipuliert). Ein neues Format bekommt ein
neues Schema, ein bestehendes wird nie umdefiniert.

- ``SCHEME_V1``: sortiert, kompakt, UTF-8 im Klartext (``ensure_ascii=False``).
  Standard fuer neue Belege.
- ``SCHEME_V1_ASCII``: sortiert, kompakt, Nicht-ASCII als ``\\uXXXX``.
- ``SCHEME_V1_STR_DEFAULT`` / ``SCHEME_V1_ASCII_STR_DEFAULT``: wie oben, aber
  nicht-serialisierbare Werte (Decimal, datetime, ...) via ``str()``.
- ``SCHEME_LEGACY_SPACED`` / ``SCHEME_LEGACY_SPACED_STR_DEFAULT``: sortiert,
  aber mit den ``json``-Standardtrennzeichen (``", "``/``": "``), ASCII.
- ``SCHEME_LEGACY_UNSORTED_UTF8``: unsortiert, Standardtrennzeichen, UTF-8
  (Handoff-Snapshot: die gespeicherten Bytes SIND der Beleg).

Gemeinsame Eigenschaften aller Schemata (bewusst unveraendert vom
``json``-Standard uebernommen, weil die Bestands-Hashes darauf beruhen):
Float-Darstellung = ``float.__repr__``; ``NaN``/``Infinity`` werden als
``NaN``/``Infinity`` geschrieben (``allow_nan`` bleibt True); ``Decimal``,
``datetime`` u. ae. werfen ``TypeError``, sofern das Schema kein
``default=str`` traegt; Tupel serialisieren wie Listen; Schluessel werden
nach ``str``-Umwandlung sortiert (gemischte Schluesseltypen werfen
``TypeError``).

Der Hash ist immer ``sha256(canonical_json(payload).encode("utf-8"))`` als
Hex-String. Eine Beleg-Art ("kind") ist bewusst NICHT Teil der
Hash-Eingabe: das wuerde jeden Bestands-Hash aendern. Die Art gehoert, wo
noetig, als Feld in den Payload.

Das Modul importiert nur die Standardbibliothek (Blatt im Import-Graph).
"""
from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

SCHEME_V1 = "v1"
SCHEME_V1_ASCII = "v1-ascii"
SCHEME_V1_STR_DEFAULT = "v1-str-default"
SCHEME_V1_ASCII_STR_DEFAULT = "v1-ascii-str-default"
SCHEME_LEGACY_SPACED = "legacy-spaced"
SCHEME_LEGACY_SPACED_STR_DEFAULT = "legacy-spaced-str-default"
SCHEME_LEGACY_UNSORTED_UTF8 = "legacy-unsorted-utf8"

_COMPACT = (",", ":")

# Eingefroren: Aenderungen an diesen Argumenten aendern Bestands-Hashes.
_SCHEMES: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    SCHEME_V1: MappingProxyType(
        {"sort_keys": True, "separators": _COMPACT, "ensure_ascii": False}
    ),
    SCHEME_V1_ASCII: MappingProxyType(
        {"sort_keys": True, "separators": _COMPACT, "ensure_ascii": True}
    ),
    SCHEME_V1_STR_DEFAULT: MappingProxyType(
        {"sort_keys": True, "separators": _COMPACT, "ensure_ascii": False, "default": str}
    ),
    SCHEME_V1_ASCII_STR_DEFAULT: MappingProxyType(
        {"sort_keys": True, "separators": _COMPACT, "ensure_ascii": True, "default": str}
    ),
    SCHEME_LEGACY_SPACED: MappingProxyType(
        {"sort_keys": True, "ensure_ascii": True}
    ),
    SCHEME_LEGACY_SPACED_STR_DEFAULT: MappingProxyType(
        {"sort_keys": True, "ensure_ascii": True, "default": str}
    ),
    SCHEME_LEGACY_UNSORTED_UTF8: MappingProxyType(
        {"sort_keys": False, "ensure_ascii": False}
    ),
})

SCHEMES: tuple[str, ...] = tuple(_SCHEMES)


def scheme_dumps_kwargs(scheme: str) -> dict[str, Any]:
    """Die ``json.dumps``-Argumente eines Schemas (Kopie, fuer Nachweise)."""
    try:
        return dict(_SCHEMES[scheme])
    except KeyError:
        raise ValueError(f"Unbekanntes Evidence-Schema: {scheme!r}") from None


def canonical_json(obj: Any, *, scheme: str = SCHEME_V1) -> str:
    """Kanonische JSON-Form von ``obj`` nach ``scheme``."""
    return json.dumps(obj, **scheme_dumps_kwargs(scheme))


def sha256_hex(text: str) -> str:
    """SHA-256 (Hex) ueber die UTF-8-Bytes eines bereits kanonischen Texts."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evidence_hash(payload: Any, *, scheme: str = SCHEME_V1) -> str:
    """SHA-256 (Hex) ueber ``canonical_json(payload, scheme=scheme)``."""
    return sha256_hex(canonical_json(payload, scheme=scheme))


# CCX-P1 (Vertrag 2026-11-13 §3): domaenensepariertes Hashschema fuer den
# Beratungsentscheid. Anders als die JSON-Schemata oben ist das kein
# ``json.dumps``-Argumentsatz: die kanonischen Bytes erzeugt
# ``core/advisory_envelope_codec.py`` (Schluesselreihenfolge laut Schema,
# Integer-Rohwerte, NFC). Hier steht nur die Domaene als einzige Quelle; sie
# ist Teil jeder Hash-Eingabe, damit ein Envelope-Hash nie mit einem anderen
# Beleg (oder einem Kind-Hash) kollidieren kann.
ADVISORY_ENVELOPE_SCHEMA = "ares/advisory-envelope/1"
ADVISORY_ENVELOPE_DOMAIN = b"Ares\x00ares/advisory-envelope/1\x00"


def advisory_domain(kind: str | None = None) -> bytes:
    """Hash-Domaene: Root ``Ares<NUL>ares/advisory-envelope/1<NUL>``, Kind-Hashes
    ``Ares<NUL>ares/advisory-envelope/1/<kind><NUL>`` (gleichartig separiert)."""
    if kind is None:
        return ADVISORY_ENVELOPE_DOMAIN
    if not kind or "\x00" in kind or "/" in kind:
        raise ValueError(f"Ungueltige Kind-Domaene: {kind!r}")
    return b"Ares\x00" + (ADVISORY_ENVELOPE_SCHEMA + "/" + kind).encode("utf-8") + b"\x00"


def domain_sha256_hex(domain: bytes, canonical: bytes) -> str:
    """SHA-256 (lowercase Hex) ueber ``domain + canonical``."""
    return hashlib.sha256(domain + canonical).hexdigest()


__all__ = [
    "ADVISORY_ENVELOPE_DOMAIN",
    "ADVISORY_ENVELOPE_SCHEMA",
    "SCHEMES",
    "SCHEME_LEGACY_SPACED",
    "SCHEME_LEGACY_SPACED_STR_DEFAULT",
    "SCHEME_LEGACY_UNSORTED_UTF8",
    "SCHEME_V1",
    "SCHEME_V1_ASCII",
    "SCHEME_V1_ASCII_STR_DEFAULT",
    "SCHEME_V1_STR_DEFAULT",
    "advisory_domain",
    "canonical_json",
    "domain_sha256_hex",
    "evidence_hash",
    "scheme_dumps_kwargs",
    "sha256_hex",
]
