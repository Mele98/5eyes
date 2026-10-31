"""RetentionPolicy der Laenderpakete (Design 80, Schritt X4).

Aufbewahrung und Datenschutz liegen als Daten unter
``<code>/retention/policy.yaml``:

    privacy_regime: ch_dsg          # Kennung des Datenschutzregimes
    retention_years:                # Kategorie -> Aufbewahrungsfrist in Jahren
      advisory_log: 10
    pending_extraction:             # Teile, die noch im Kern liegen (Begruendung Pflicht)
      notes: "..."
      erasure_rules: "..."

Verhaltensneutralitaet (X4): Die Werte sind byte-gleich aus den bisherigen
Kernkonstanten uebernommen. Der Kern liest ueber ``default_retention()`` den
Pack der Altsemantik "NULL = CH" (bisher galten die Konstanten fuer jedes
Mandat). ``years(category)`` ist fail-closed: eine unbekannte Kategorie ist
ein Fehler, nie ein stiller Default.

Dieses Modul importiert kein Backend-Modul ausserhalb von ``jurisdictions``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from jurisdictions.api import JurisdictionPack, PendingExtraction
from jurisdictions.registry import PACKS_ROOT, PackRegistryError, content_hash, default_registry
from jurisdictions.resolve import LEGACY_DEFAULT_CODE

RETENTION_DIR = "retention"
POLICY_NAME = "policy.yaml"

_POLICY_KEYS = frozenset({"privacy_regime", "retention_years", "pending_extraction"})
_PENDING_PARTS = frozenset({"notes", "erasure_rules"})
_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class RetentionCategoryError(KeyError):
    """Unbekannte Aufbewahrungskategorie (fail-closed, kein Default)."""


@dataclass(frozen=True)
class PackRetentionPolicy:
    """Aufbewahrungs- und Datenschutzregeln eines Packs
    (implementiert ``api.RetentionPolicy``).

    ``notes`` (Kategorie -> DocumentSet-Schluessel) und ``erasure_rules``
    sind ``PendingExtraction``, solange die Daten noch im Kern liegen.
    """

    code: str
    version: str
    privacy_regime: str
    retention_years: Mapping[str, int]
    notes: Mapping[str, str] | PendingExtraction
    erasure_rules: Any
    policy_hash: str
    source: str

    def years(self, category: str) -> int:
        try:
            return self.retention_years[category]
        except KeyError:
            raise RetentionCategoryError(
                f"{self.code}@{self.version}: keine Aufbewahrungsfrist fuer Kategorie {category!r}"
            ) from None


def _require(cond: bool, source: str, message: str) -> None:
    if not cond:
        raise PackRegistryError(f"{source}: {message}")


def load_retention_policy(pack: JurisdictionPack, root: Path = PACKS_ROOT) -> PackRetentionPolicy:
    path = root / pack.code.lower() / RETENTION_DIR / POLICY_NAME
    source = f"{pack.code.lower()}/{RETENTION_DIR}/{POLICY_NAME}"
    _require(path.is_file(), source, "Aufbewahrungsregeln fehlen")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    _require(isinstance(raw, Mapping) and set(raw) <= _POLICY_KEYS, source, f"Schluessel muessen Teilmenge von {sorted(_POLICY_KEYS)} sein")
    _require({"privacy_regime", "retention_years"} <= set(raw), source, "privacy_regime und retention_years sind Pflicht")

    regime = raw["privacy_regime"]
    _require(isinstance(regime, str) and bool(_IDENT_RE.match(regime)), source, f"privacy_regime {regime!r} ungueltig")

    years_raw = raw["retention_years"]
    _require(isinstance(years_raw, Mapping) and bool(years_raw), source, "retention_years muss ein nicht-leeres Mapping sein")
    years: dict[str, int] = {}
    for category, value in years_raw.items():
        _require(isinstance(category, str) and bool(_IDENT_RE.match(category)), source, f"Kategorie {category!r} ungueltig")
        _require(type(value) is int and value > 0, source, f"retention_years.{category} muss eine positive ganze Zahl sein")
        years[category] = value

    pending_raw = raw.get("pending_extraction") or {}
    _require(isinstance(pending_raw, Mapping) and set(pending_raw) <= _PENDING_PARTS, source, f"pending_extraction nur fuer {sorted(_PENDING_PARTS)}")
    pending: dict[str, PendingExtraction] = {}
    for part, reason in pending_raw.items():
        _require(isinstance(reason, str) and reason.strip() != "", source, f"pending_extraction.{part} braucht eine Begruendung")
        pending[part] = PendingExtraction(reason=reason)
    _require(set(pending) == _PENDING_PARTS, source, "notes und erasure_rules muessen geliefert oder als pending_extraction begruendet sein")

    return PackRetentionPolicy(
        code=pack.code,
        version=pack.version,
        privacy_regime=regime,
        retention_years=years,
        notes=pending["notes"],
        erasure_rules=pending["erasure_rules"],
        policy_hash=content_hash(raw),
        source=source,
    )


def retention_policy_paths(root: Path = PACKS_ROOT) -> list[Path]:
    """Alle Aufbewahrungsdateien eingebauter Packs (fuer das Desktop-Bundle)."""
    return sorted(
        p
        for p in root.glob(f"*/{RETENTION_DIR}/{POLICY_NAME}")
        if not p.parent.parent.name.startswith(("_", "."))
    )


@lru_cache(maxsize=None)
def retention_for(code: str, version: str | None = None) -> PackRetentionPolicy:
    registry = default_registry()
    pack = registry.latest(code) if version is None else registry.get(code, version)
    if pack is None:
        raise RetentionCategoryError(f"kein registrierter Pack {code!r}{'' if version is None else '@' + version}")
    return load_retention_policy(pack)


def default_retention() -> PackRetentionPolicy:
    """RetentionPolicy der Altsemantik "NULL = CH" (bisheriges Verhalten)."""
    return retention_for(LEGACY_DEFAULT_CODE)
