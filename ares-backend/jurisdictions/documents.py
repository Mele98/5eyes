"""DocumentSet der Laenderpakete (Design 80, Schritt X3).

Rechts- und Pflichttexte liegen als Daten unter
``<code>/documents/<locale>/<namespace>.yaml``:

    namespace: legal
    texts:
      "footer.disclaimer": "..."          # Text
      "disclaimer.paragraphs": ["...", ...] # Liste von Texten
      "metrics.definitions": [["Begriff", "Erklaerung"], ...]  # Paare

Der volle Schluessel ist ``<namespace>.<Schluessel>``, z.B.
``legal.footer.disclaimer``. Der Dateiname muss dem Namespace entsprechen.
Jede deklarierte Locale des Packs muss dieselbe Schluesselmenge liefern.

Verhaltensneutralitaet (X3): Die Texte sind byte-gleich aus den bisherigen
Kernkonstanten uebernommen. Die Kern-Komponenten lesen ueber
``default_documents()`` den Pack der Altsemantik "NULL = CH"; das entspricht
exakt dem bisherigen Verhalten (die Texte waren fuer jedes Mandat hart die
CH-Texte). Eine mandatsabhaengige Auswahl folgt mit dem RunContext (K-3).

Dieses Modul importiert kein Backend-Modul ausserhalb von ``jurisdictions``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Union

import yaml

from jurisdictions.api import JurisdictionPack
from jurisdictions.registry import PACKS_ROOT, PackRegistryError, content_hash, default_registry
from jurisdictions.resolve import LEGACY_DEFAULT_CODE

DOCUMENTS_DIR = "documents"

TextValue = Union[str, tuple[str, ...], tuple[tuple[str, ...], ...]]

_FILE_KEYS = frozenset({"namespace", "texts"})


class DocumentKeyError(KeyError):
    """Unbekannter Schluessel oder unbekannte Locale (fail-closed, kein Fallback)."""


@dataclass(frozen=True)
class PackDocumentSet:
    """Texte eines Packs je Locale (implementiert ``api.DocumentSet``).

    ``required_documents`` (Pflichtdokumente je Mandatstyp) und ``template``
    sind in X3 noch nicht befuellt. ``locked_namespaces``: alle Namespaces
    (O-7: Rechtstexte sind nicht tenant-ueberschreibbar; einen
    Tenant-Override gibt es noch nicht).
    """

    code: str
    version: str
    locales: tuple[str, ...]
    entries: Mapping[str, Mapping[str, TextValue]]
    documents_hash: str
    sources: tuple[str, ...]
    locked_namespaces: frozenset[str]
    required_documents: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def default_locale(self) -> str:
        return self.locales[0]

    def _locale_entries(self, locale: str | None) -> Mapping[str, TextValue]:
        loc = self.default_locale if locale is None else locale
        try:
            return self.entries[loc]
        except KeyError:
            raise DocumentKeyError(f"{self.code}@{self.version}: Locale {loc!r} nicht vorhanden") from None

    def keys(self, locale: str | None = None) -> tuple[str, ...]:
        return tuple(sorted(self._locale_entries(locale)))

    def value(self, key: str, locale: str | None = None) -> TextValue:
        entries = self._locale_entries(locale)
        try:
            return entries[key]
        except KeyError:
            raise DocumentKeyError(f"{self.code}@{self.version}: Schluessel {key!r} fehlt") from None

    def text(self, key: str, locale: str | None = None, **params: Any) -> str:
        value = self.value(key, locale)
        if not isinstance(value, str):
            raise DocumentKeyError(f"{key!r} ist kein Einzeltext")
        return value.format(**params) if params else value

    def paragraphs(self, key: str, locale: str | None = None) -> tuple[str, ...]:
        value = self.value(key, locale)
        if not (isinstance(value, tuple) and all(isinstance(v, str) for v in value)):
            raise DocumentKeyError(f"{key!r} ist keine Textliste")
        return value

    def pairs(self, key: str, locale: str | None = None) -> tuple[tuple[str, ...], ...]:
        value = self.value(key, locale)
        if not (isinstance(value, tuple) and all(isinstance(v, tuple) for v in value)):
            raise DocumentKeyError(f"{key!r} ist keine Paarliste")
        return value

    def template(self, document: str, locale: str) -> Any:
        raise NotImplementedError("X3 liefert nur Texte; Dokumentvorlagen folgen spaeter")


def _freeze(value: Any, where: str) -> TextValue:
    if isinstance(value, str):
        if value.strip() == "":
            raise PackRegistryError(f"{where}: leerer Text")
        return value
    if isinstance(value, list) and value:
        if all(isinstance(v, str) for v in value):
            return tuple(_freeze(v, where) for v in value)
        if all(isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v) for v in value):
            return tuple((_freeze(v[0], where), _freeze(v[1], where)) for v in value)
    raise PackRegistryError(f"{where}: Wert muss Text, Textliste oder Liste von [Begriff, Text]-Paaren sein")


def _load_locale(folder: Path, root: Path) -> tuple[dict[str, TextValue], list[str], set[str]]:
    entries: dict[str, TextValue] = {}
    sources: list[str] = []
    namespaces: set[str] = set()
    files = sorted(folder.glob("*.yaml"))
    if not files:
        raise PackRegistryError(f"{folder.relative_to(root).as_posix()}: keine Textdateien")
    for path in files:
        source = path.relative_to(root).as_posix()
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, Mapping) or set(raw) != _FILE_KEYS:
            raise PackRegistryError(f"{source}: Schluessel muessen genau {sorted(_FILE_KEYS)} sein")
        namespace = raw["namespace"]
        if namespace != path.stem:
            raise PackRegistryError(f"{source}: namespace {namespace!r} passt nicht zum Dateinamen")
        texts = raw["texts"]
        if not isinstance(texts, Mapping) or not texts:
            raise PackRegistryError(f"{source}: texts muss ein nicht-leeres Mapping sein")
        for key, value in texts.items():
            if not isinstance(key, str) or key.strip() == "":
                raise PackRegistryError(f"{source}: ungueltiger Schluessel {key!r}")
            full = f"{namespace}.{key}"
            if full in entries:
                raise PackRegistryError(f"{source}: Schluessel {full!r} doppelt")
            entries[full] = _freeze(value, f"{source} {key}")
        namespaces.add(namespace)
        sources.append(source)
    return entries, sources, namespaces


def load_document_set(pack: JurisdictionPack, root: Path = PACKS_ROOT) -> PackDocumentSet:
    base = root / pack.code.lower() / DOCUMENTS_DIR
    entries: dict[str, dict[str, TextValue]] = {}
    sources: list[str] = []
    namespaces: set[str] | None = None
    for locale in pack.locales:
        folder = base / locale
        if not folder.is_dir():
            raise PackRegistryError(f"{pack.code}@{pack.version}: Texte fuer Locale {locale!r} fehlen ({folder.name})")
        loc_entries, loc_sources, loc_namespaces = _load_locale(folder, root)
        if entries:
            reference = next(iter(entries.values()))
            if set(loc_entries) != set(reference):
                missing = sorted(set(reference) ^ set(loc_entries))
                raise PackRegistryError(f"{pack.code}@{pack.version}: Locale {locale!r} weicht in Schluesseln ab: {missing}")
        entries[locale] = loc_entries
        sources.extend(loc_sources)
        namespaces = loc_namespaces if namespaces is None else namespaces | loc_namespaces
    return PackDocumentSet(
        code=pack.code,
        version=pack.version,
        locales=tuple(pack.locales),
        entries=entries,
        documents_hash=content_hash(entries),
        sources=tuple(sources),
        locked_namespaces=frozenset(namespaces or ()),
    )


def document_paths(root: Path = PACKS_ROOT) -> list[Path]:
    """Alle Textdateien eingebauter Packs (fuer das Desktop-Bundle)."""
    return sorted(
        p
        for p in root.glob(f"*/{DOCUMENTS_DIR}/*/*.yaml")
        if not p.parts[-4].startswith(("_", "."))
    )


@lru_cache(maxsize=None)
def documents_for(code: str, version: str | None = None) -> PackDocumentSet:
    registry = default_registry()
    pack = registry.latest(code) if version is None else registry.get(code, version)
    if pack is None:
        raise DocumentKeyError(f"kein registrierter Pack {code!r}{'' if version is None else '@' + version}")
    return load_document_set(pack)


def default_documents() -> PackDocumentSet:
    """DocumentSet der Altsemantik "NULL = CH" (bisheriges Verhalten)."""
    return documents_for(LEGACY_DEFAULT_CODE)
