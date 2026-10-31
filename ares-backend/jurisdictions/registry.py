"""Registry der Laenderpakete (Design 80, Abschnitte 2.3/2.4).

- ``PackRegistry``: ``(code, version)`` ist eindeutig; ein Duplikat ist ein
  Fehler und wird nie still ueberschrieben.
- ``load_builtin_packs()``: liest jedes ``<code>/pack.yaml`` dieses Pakets
  (Unterordner mit fuehrendem ``_`` sind ausgenommen), validiert das Manifest
  und berechnet ``content_hash`` = SHA-256 ueber das kanonisierte Manifest
  (``canonical_json``). Kommentare und YAML-Formatierung beeinflussen den Hash
  nicht, jede inhaltliche Aenderung schon.
- ``default_registry()``: einmal geladene, prozessweite Registry.

Status-Durchsetzung (nur ``approved``) und Tenant-Zulassung sind NICHT Teil
von X1; sie kommen mit dem Fail-closed-Gate (X14). Eine Entry-Point-Discovery
externer Packs folgt erst mit Konformitaets-Testkit und Owner-Entscheid O-15.

Dieses Modul importiert kein Backend-Modul ausserhalb von ``jurisdictions``.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from jurisdictions.api import (
    PACK_AREAS,
    PACK_STATUSES,
    AreaSpec,
    Approval,
    JurisdictionPack,
    NotProvided,
    PendingExtraction,
)

PACKS_ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "pack.yaml"

_CODE_RE = re.compile(r"^[A-Z]{2}$")
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_MANIFEST_KEYS = frozenset(
    {
        "code",
        "version",
        "status",
        "home_currency",
        "locales",
        "timezone",
        "effective_from",
        "approvals",
        "areas",
    }
)
_APPROVAL_KINDS = frozenset({"legal", "compliance", "ic"})


class PackRegistryError(ValueError):
    """Ungueltiges Manifest oder Registry-Konflikt (z.B. Duplikat)."""


# --------------------------------------------------------------------------
# Kanonisierung und Hash
# --------------------------------------------------------------------------


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        items = [(_canonical(k), _canonical(v)) for k, v in value.items()]
        if all(isinstance(k, str) for k, _ in items):
            return {k: v for k, v in sorted(items, key=lambda kv: kv[0])}
        return sorted(([k, v] for k, v in items), key=lambda kv: json.dumps(kv[0], sort_keys=True))
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise PackRegistryError(f"nicht kanonisierbarer Wert vom Typ {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Deterministische JSON-Form (sortierte Schluessel, kompakt, UTF-8).

    Mengen werden sortiert, Tupel wie Listen behandelt, Mappings mit
    Nicht-String-Schluesseln als sortierte ``[key, value]``-Paare.
    """
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Manifest -> JurisdictionPack
# --------------------------------------------------------------------------


def _require(cond: bool, source: str, message: str) -> None:
    if not cond:
        raise PackRegistryError(f"{source}: {message}")


def _parse_area(name: str, raw: Any, source: str) -> AreaSpec | NotProvided | PendingExtraction:
    where = f"{source} areas.{name}"
    _require(isinstance(raw, Mapping), where, "muss ein Mapping sein")
    for marker, cls in (("not_provided", NotProvided), ("pending_extraction", PendingExtraction)):
        if marker in raw:
            _require(set(raw) == {marker}, where, f"{marker} schliesst andere Schluessel aus")
            reason = raw[marker]
            _require(isinstance(reason, str) and reason.strip() != "", where, f"{marker} braucht eine Begruendung")
            return cls(reason=reason)
    _require(set(raw) <= {"references", "parameters"}, where, f"unbekannte Schluessel {sorted(set(raw))}")
    refs = raw.get("references", [])
    _require(isinstance(refs, list), where, "references muss eine Liste sein")
    for ref in refs:
        _require(
            isinstance(ref, str) and bool(_REFERENCE_RE.match(ref)),
            where,
            f"Referenz {ref!r} ist nicht in der Form 'modul:ATTRIBUT'",
        )
    _require(len(set(refs)) == len(refs), where, "doppelte Referenz")
    params = raw.get("parameters")
    _require(params is None or isinstance(params, Mapping), where, "parameters muss ein Mapping sein")
    _require(bool(refs) or bool(params), where, "leerer Bereich; stattdessen not_provided mit Begruendung")
    return AreaSpec(references=tuple(refs), parameters=dict(params) if params else None)


def pack_from_manifest(raw: Any, source: str) -> JurisdictionPack:
    _require(isinstance(raw, Mapping), source, "Manifest muss ein Mapping sein")
    keys = set(raw)
    _require(keys == _MANIFEST_KEYS, source, f"Schluessel {sorted(keys)} != {sorted(_MANIFEST_KEYS)}")

    code = raw["code"]
    _require(isinstance(code, str) and bool(_CODE_RE.match(code)), source, f"code {code!r} ist kein ISO-3166-1-alpha-2-Code")
    version = raw["version"]
    _require(isinstance(version, str) and bool(_VERSION_RE.match(version)), source, f"version {version!r} ist kein SemVer")
    status = raw["status"]
    _require(status in PACK_STATUSES, source, f"status {status!r} nicht in {PACK_STATUSES}")
    currency = raw["home_currency"]
    _require(isinstance(currency, str) and bool(_CURRENCY_RE.match(currency)), source, f"home_currency {currency!r} ist kein ISO-4217-Code")
    locales = raw["locales"]
    _require(
        isinstance(locales, list) and bool(locales) and all(isinstance(x, str) and _LOCALE_RE.match(x) for x in locales),
        source,
        f"locales {locales!r} ungueltig",
    )
    tz = raw["timezone"]
    _require(isinstance(tz, str) and tz != "", source, "timezone fehlt")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise PackRegistryError(f"{source}: timezone {tz!r} ist keine IANA-Zone") from exc
    effective_from = raw["effective_from"]
    _require(
        isinstance(effective_from, str) and bool(_DATE_RE.match(effective_from)),
        source,
        "effective_from muss ein ISO-Datum als String sein",
    )

    approvals_raw = raw["approvals"]
    _require(isinstance(approvals_raw, list), source, "approvals muss eine Liste sein")
    approvals: list[Approval] = []
    for item in approvals_raw:
        _require(
            isinstance(item, Mapping) and set(item) == {"kind", "reference", "approved_on"},
            source,
            "approval braucht kind/reference/approved_on",
        )
        _require(item["kind"] in _APPROVAL_KINDS, source, f"approval.kind {item['kind']!r} unbekannt")
        approvals.append(Approval(kind=item["kind"], reference=str(item["reference"]), approved_on=str(item["approved_on"])))
    if status == "approved":
        _require(
            {a.kind for a in approvals} == _APPROVAL_KINDS,
            source,
            "status approved verlangt legal-, compliance- und ic-Approval",
        )

    areas_raw = raw["areas"]
    _require(isinstance(areas_raw, Mapping), source, "areas muss ein Mapping sein")
    _require(
        set(areas_raw) == set(PACK_AREAS),
        source,
        f"areas {sorted(areas_raw)} != {sorted(PACK_AREAS)} (fehlende Bereiche als not_provided fuehren)",
    )
    areas = {name: _parse_area(name, areas_raw[name], source) for name in PACK_AREAS}

    return JurisdictionPack(
        code=code,
        version=version,
        status=status,
        home_currency=currency,
        locales=tuple(locales),
        timezone=tz,
        effective_from=effective_from,
        approvals=tuple(approvals),
        areas=areas,
        content_hash=content_hash(raw),
        source=source,
    )


def load_manifest(path: Path, root: Path = PACKS_ROOT) -> JurisdictionPack:
    source = path.relative_to(root).as_posix()
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    pack = pack_from_manifest(raw, source)
    folder = path.parent.name
    _require(folder == pack.code.lower(), source, f"Ordner {folder!r} passt nicht zu code {pack.code!r}")
    return pack


def builtin_manifest_paths(root: Path = PACKS_ROOT) -> list[Path]:
    return sorted(
        p
        for p in root.glob(f"*/{MANIFEST_NAME}")
        if not p.parent.name.startswith(("_", "."))
    )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class PackRegistry:
    """Code -> Versionen. Duplikate ``(code, version)`` sind ein Fehler."""

    def __init__(self, packs: Iterable[JurisdictionPack] = ()) -> None:
        self._packs: dict[str, dict[str, JurisdictionPack]] = {}
        for pack in packs:
            self.register(pack)

    def register(self, pack: JurisdictionPack) -> None:
        versions = self._packs.setdefault(pack.code, {})
        if pack.version in versions:
            raise PackRegistryError(
                f"Pack {pack.code}@{pack.version} ist bereits registriert "
                f"({versions[pack.version].source}); Duplikate werden nicht ueberschrieben."
            )
        versions[pack.version] = pack

    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))

    def versions(self, code: str) -> tuple[str, ...]:
        return tuple(sorted(self._packs.get(code, {}), key=_version_key))

    def get(self, code: str, version: str) -> JurisdictionPack | None:
        return self._packs.get(code, {}).get(version)

    def latest(self, code: str) -> JurisdictionPack | None:
        """Hoechste registrierte Version eines Codes (exakter, unnormalisierter
        Vergleich). Ohne Status-Filter -- der kommt mit X14."""
        versions = self._packs.get(code)
        if not versions:
            return None
        return versions[max(versions, key=_version_key)]

    def all(self) -> tuple[JurisdictionPack, ...]:
        return tuple(self._packs[c][v] for c in self.codes() for v in self.versions(c))


def load_builtin_packs(root: Path = PACKS_ROOT) -> PackRegistry:
    return PackRegistry(load_manifest(p, root) for p in builtin_manifest_paths(root))


@lru_cache(maxsize=1)
def default_registry() -> PackRegistry:
    return load_builtin_packs()
