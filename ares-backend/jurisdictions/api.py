"""Datentypen und Protocols der Laenderpakete (Design 80, Abschnitt 2.2).

Schritt X1 (OPTIMIZATION, verhaltensneutral): Es gibt noch keinen Konsumenten.
Die Protocols beschreiben die Zielschnittstellen der Pack-Bereiche; die
konkreten Implementierungen folgen in X3 bis X13. Bis dahin liefert der
CH-Pack je Bereich nur Referenzen auf die bestehenden Konstanten
(``AreaSpec.references``) oder ``NotProvided`` mit Begruendung.

Dieses Modul importiert kein Backend-Modul.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping, Protocol

PackStatus = Literal["draft", "pending_review", "approved", "retired"]
PACK_STATUSES: tuple[str, ...] = ("draft", "pending_review", "approved", "retired")

# Bereiche eines Packs in fester Reihenfolge (Design 80, 2.2 ``JurisdictionPack``).
PACK_AREAS: tuple[str, ...] = (
    "legal",
    "suitability",
    "risk_questionnaires",
    "tax",
    "pension",
    "mortality",
    "market",
    "products",
    "documents",
    "retention",
    "formatting",
    "calendar",
)

# Herkunft des aufgeloesten Codes (``ResolvedPack.source``).
ResolutionSource = Literal["mandate", "explicit", "tenant", "legacy_default"]


@dataclass(frozen=True)
class NotProvided:
    """Bereich wird vom Pack bewusst nicht geliefert; ``reason`` ist Pflicht.

    Der Kern schaltet die abhaengige Faehigkeit dann fail-closed ab (ab den
    jeweiligen Extraktionsschritten; in X1 ohne Wirkung).
    """

    reason: str


@dataclass(frozen=True)
class PendingExtraction:
    """Bereich gehoert inhaltlich zum Pack, liegt aber noch unveraendert im
    Kern; ``reason`` nennt den Extraktionsschritt (z.B. "X9 Formatting").

    Im Unterschied zu ``NotProvided`` ist die Faehigkeit vorhanden.
    """

    reason: str


@dataclass(frozen=True)
class AreaSpec:
    """Inhalt eines Pack-Bereichs im Geruest-Stadium.

    ``references``: ``"modul:ATTRIBUT"``-Verweise auf bestehende Konstanten
    (nichts wird verschoben). ``parameters``: kleine Skalar-Parameter aus dem
    Manifest (z.B. ``tax_regime_pattern``).
    """

    references: tuple[str, ...] = ()
    parameters: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Approval:
    kind: str  # legal / compliance / ic
    reference: str
    approved_on: str  # ISO-Datum


@dataclass(frozen=True)
class JurisdictionPack:
    """Ein versioniertes, gehashtes Laenderpaket (Manifest-Ebene)."""

    code: str
    version: str
    status: str
    home_currency: str
    locales: tuple[str, ...]
    timezone: str
    effective_from: str
    approvals: tuple[Approval, ...]
    areas: Mapping[str, AreaSpec | NotProvided | PendingExtraction]
    content_hash: str
    source: str  # Pfad des Manifests relativ zum Paket, z.B. "ch/pack.yaml"

    @property
    def references(self) -> tuple[str, ...]:
        refs: list[str] = []
        for area in PACK_AREAS:
            spec = self.areas.get(area)
            if isinstance(spec, AreaSpec):
                refs.extend(spec.references)
        return tuple(refs)


@dataclass(frozen=True)
class ResolvedPack:
    """Ergebnis von ``resolve_pack``: eingefrorener Code plus (falls
    registriert) der Pack.

    ``code`` ist exakt der Wert, den die heutige Formel
    ``getattr(mandate, "jurisdiction", None) or "CH"`` liefert -- ohne
    Normalisierung (kein ``strip``/``upper``). Unbekannte Codes bleiben
    unveraendert und ergeben ``pack=None``; fail-closed folgt erst in X14.
    """

    code: Any
    pack: JurisdictionPack | None
    source: str

    @property
    def is_registered(self) -> bool:
        return self.pack is not None

    @property
    def version(self) -> str | None:
        return self.pack.version if self.pack is not None else None

    @property
    def content_hash(self) -> str | None:
        return self.pack.content_hash if self.pack is not None else None


# --------------------------------------------------------------------------
# Protocols der Pack-Bereiche (Zielschnittstellen, noch ohne Implementierung).
# Typen, die erst in spaeteren Schritten konkret werden, sind ``Any``.
# --------------------------------------------------------------------------


class LegalProfile(Protocol):
    code: str
    legal_basis_keys: Mapping[str, str]
    region_codes: frozenset[str]
    aml_profile: Any

    def license_rule(self, service_mode: str) -> Any: ...


class SuitabilityRules(Protocol):
    client_classes: tuple[Any, ...]
    duty_types: tuple[str, ...]
    freshness_max_days: int
    override_rules: Any

    def requires_suitability(self, client_class: str, service_mode: str) -> bool: ...


class RiskQuestionnaire(Protocol):
    id: str
    version: str
    scoring_version: str
    definition: Any
    knowledge_catalog: Any

    def score(self, answers: Any) -> Any: ...

    def is_complete_current(self, answers: Any) -> bool: ...

    def profile_for_score(self, score_x10: int) -> str: ...


class PensionSystem(Protocol):
    vehicle_types: tuple[Any, ...]
    lumpsum_tax_default_bps: int

    def default_rate_bps(self, vehicle: str, pension_type: str) -> int: ...

    def classify(self, free_text: str) -> str | None: ...


class MarketReference(Protocol):
    home_currency: str
    correlation: Any
    home_bias: Mapping[str, int]
    sub_asset_catalog: tuple[Any, ...]
    inflation_baseline_bps: int
    house_matrix_defaults: Any

    def cma(self, tenant_id: str | None, as_of: date) -> Any: ...


class ProductEligibilityPolicy(Protocol):
    default_rule_set_id: str
    reference_products: tuple[Any, ...]
    currency_rules: Any


class DocumentSet(Protocol):
    locales: tuple[str, ...]
    required_documents: Mapping[str, tuple[str, ...]]
    locked_namespaces: frozenset[str]

    def text(self, key: str, locale: str, **params: Any) -> str: ...

    def template(self, document: str, locale: str) -> Any: ...


class RetentionPolicy(Protocol):
    privacy_regime: str
    notes: Mapping[str, str]
    erasure_rules: Any

    def years(self, category: str) -> int: ...


class Formatting(Protocol):
    locale: str
    timezone: str
    date_pattern: str
    number: Any


class Calendar(Protocol):
    def is_business_day(self, d: date) -> bool: ...
