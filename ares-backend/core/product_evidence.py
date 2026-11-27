"""C-COMP-02: Produktevidenz v1 -- Vertrag, Identitaet und Auswertung.

Die EINE Quelle fuer Pflichtarten, Produkt-/Anteilsklassenidentitaet, Auswertung
und den Abgleich "gebundener Evidenzsatz == heute wirksamer Evidenzsatz".
Eligibility-Gate, Freigabe-Gate, Frische-Pruefung (P2/P5) und Kostenausweis
rechnen damit identisch; es gibt keine zweite Eligibility-Engine und keine
eigene Nachbildung je Kanal.

Reine Funktionen ueber einfachen Dictionaries; die Datenbank liest der Aufrufer
(``query`` = ``(sql, parameter) -> [dict]``). Stdlib-Blatt (architecture
ratchets, FAN_OUT_EXEMPT_LEAVES): dieselbe Regel ohne neue Modulkopplung.

Die Reason-Codes stehen hier als Zeichenketten; katalogisiert sind sie in
``core/reason_codes.py`` (Test sichert die Deckung).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterable, Mapping

PRODUCT_EVIDENCE_KINDS: tuple[str, ...] = (
    "instrument_identity",
    "kid",
    "costs",
    "retrocession",
    "suitability",
    "liquidity",
    "currency",
    "sustainability",
    "price_source",
)
# C-COMP-02 (Vorab-Entscheid 6.3): Satzschema 2 bindet je Dimension
# (Eignung, Kosten, Interessenkonflikt) einen typisierten, gehashten Snapshot;
# ein Satz des Schemas 1 (ohne diese Bindung) ist LEGACY und damit STALE --
# historisch lesbar, nie still hochgestuft. Die Hash-Domaene bleibt; das
# Schema steht im gehashten Payload.
PRODUCT_EVIDENCE_SCHEMA = "ares-product-evidence/v2"
PRODUCT_EVIDENCE_SCHEMA_LEGACY = "ares-product-evidence/v1"
PRODUCT_EVIDENCE_EVALUATOR = "ares-product-evidence/2"
PRODUCT_EVIDENCE_DOMAIN = b"ares-product-evidence/v1\n"
STATUS_VERIFIED = "verified"
NOT_APPLICABLE = "not_applicable"
# Arten, die einen Wert ODER den belegten Nichtanwendungsstatus tragen muessen.
RATE_KINDS: tuple[str, ...] = ("costs", "retrocession")

# Synthetische Nachweise (Test/Demo) tragen dieses Praefix im Quellentyp. Sie
# zaehlen nur, wenn die Laufzeit es ausdruecklich erlaubt; Vorgabe ist NEIN.
# ``config`` hinterlegt dafuer die Abfrage ``not settings.production_mode``
# (bei jeder Auswertung neu gefragt, kein eigener Schalter).
SYNTHETIC_SOURCE_PREFIX = "synthetic"
_RUNTIME_POLICY: dict[str, Any] = {"synthetic_allowed": None}

MISSING = "PRODUCT_EVIDENCE_MISSING"
STALE = "PRODUCT_EVIDENCE_STALE"
CONFLICT = "PRODUCT_EVIDENCE_CONFLICT"
REVOKED = "PRODUCT_EVIDENCE_REVOKED"
HASH_MISMATCH = "PRODUCT_EVIDENCE_HASH_MISMATCH"
SHARE_CLASS_MISMATCH = "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"
MISSING_BY_KIND: dict[str, str] = {
    "costs": "PRODUCT_EVIDENCE_COST_MISSING",
    "kid": "PRODUCT_EVIDENCE_KID_MISSING",
    "retrocession": "PRODUCT_EVIDENCE_RETROCESSION_MISSING",
    "suitability": "PRODUCT_EVIDENCE_SUITABILITY_MISSING",
}
# Auswertungsstatus je Code (geschlossene Abbildung; sonst "missing").
STATUS_BY_CODE: dict[str, str] = {
    STALE: "stale",
    CONFLICT: "conflict",
    REVOKED: "revoked",
    HASH_MISMATCH: "hash_mismatch",
    SHARE_CLASS_MISMATCH: "conflict",
}

# Tenantgrenze in der Datenbank: der Nachweis eines tenanteigenen Produkts gehoert
# demselben Tenant, ein Plattform-Nachweis (tenant_id NULL) zu einem Plattform-
# Produkt. Gemeinsame DDL fuer Modell und SQLite-Laufzeit-Patch (das Rohschema
# kennt products.tenant_id erst nach dem Patch).
TENANT_MISMATCH_SQL = (
    "EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND p.tenant_id IS NOT NULL "
    "AND (NEW.tenant_id IS NULL OR p.tenant_id <> NEW.tenant_id))"
)
TENANT_MISMATCH_MESSAGE = "product_evidence_items: Produkt und Nachweis gehoeren zu verschiedenen Tenants"
SQLITE_TENANT_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_tenant_insert "
    "BEFORE INSERT ON product_evidence_items FOR EACH ROW "
    f"WHEN {TENANT_MISMATCH_SQL} "
    f"BEGIN SELECT RAISE(ABORT, '{TENANT_MISMATCH_MESSAGE}'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_tenant_update "
    "BEFORE UPDATE OF tenant_id, product_id ON product_evidence_items FOR EACH ROW "
    f"WHEN {TENANT_MISMATCH_SQL} "
    f"BEGIN SELECT RAISE(ABORT, '{TENANT_MISMATCH_MESSAGE}'); END",
)

# C-COMP-02 (Vorab-Entscheid 6.4): Produkt-/Anteilsklassenidentitaet auch an
# der DB-Grenze (Trigger SQLite + PostgreSQL) -- dieselbe Regel wie
# ``product_identity``/``identity_matches``: Instrument = erstes nichtleeres von
# isin, internal_product_id, figi, id; Anteilsklasse = share_class_figi; leer
# (nur Leerraum) == NULL; beide ohne Anteilsklasse oder beide mit derselben.
# Ein direkter INSERT/UPDATE einer fremden oder abweichenden Anteilsklassen-
# zeile scheitert damit an der Datenbank, nicht erst in der Auswertung. Der
# Trigger feuert nur auf INSERT und auf UPDATE der Identitaetsspalten; ein
# Widerruf nach einer spaeteren Produktaenderung bleibt moeglich (die
# Auswertung meldet die Abweichung dann fail-closed als Konflikt).
IDENTITY_MISMATCH_MESSAGE = (
    "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH: product_evidence_items: Nachweis gehoert nicht "
    "zur Produkt- oder Anteilsklassenidentitaet"
)
_SQLITE_BLANK = "' ' || char(9) || char(10) || char(11) || char(12) || char(13)"
_PG_BLANK = "' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)"


def identity_mismatch_sql(dialect: str) -> str:
    """Bedingung ``Nachweisidentitaet != Produktidentitaet`` fuer einen Trigger."""
    if dialect == "postgresql":
        def norm(expr: str) -> str:
            return f"NULLIF(btrim({expr}::text, {_PG_BLANK}), '')"
        differs = "IS DISTINCT FROM"
    else:
        def norm(expr: str) -> str:
            return f"NULLIF(trim({expr}, {_SQLITE_BLANK}), '')"
        differs = "IS NOT"
    stable = f"COALESCE({norm('p.isin')}, {norm('p.internal_product_id')}, {norm('p.figi')}, p.id)"
    return (
        "EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND ("
        f"{norm('NEW.stable_instrument_id')} {differs} {stable} "
        f"OR {norm('NEW.share_class_id')} {differs} {norm('p.share_class_figi')}))"
    )


# Ausgeschrieben (Stdlib-Blatt ohne Modul-Seiteneffekte); identisch mit
# ``identity_mismatch_sql`` (Test sichert die Deckung).
SQLITE_IDENTITY_MISMATCH_SQL = (
    'EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND (NULLIF(trim(NEW.stable_instrum'
    "ent_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), '') IS NOT COALESCE(NUL"
    "LIF(trim(p.isin, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), NULLIF(tr"
    "im(p.internal_product_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), "
    "NULLIF(trim(p.figi, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), p.id) "
    "OR NULLIF(trim(NEW.share_class_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13"
    ")), '') IS NOT NULLIF(trim(p.share_class_figi, ' ' || char(9) || char(10) || char(11) || char(12"
    ") || char(13)), '')))"
)
PG_IDENTITY_MISMATCH_SQL = (
    'EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND (NULLIF(btrim(NEW.stable_instru'
    "ment_id::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), '') IS DISTINCT FROM "
    "COALESCE(NULLIF(btrim(p.isin::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), "
    "''), NULLIF(btrim(p.internal_product_id::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) ||"
    " chr(13)), ''), NULLIF(btrim(p.figi::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr"
    "(13)), ''), p.id) OR NULLIF(btrim(NEW.share_class_id::text, ' ' || chr(9) || chr(10) || chr(11) "
    "|| chr(12) || chr(13)), '') IS DISTINCT FROM NULLIF(btrim(p.share_class_figi::text, ' ' || chr(9"
    ") || chr(10) || chr(11) || chr(12) || chr(13)), '')))"
)
SQLITE_IDENTITY_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_identity_insert "
    "BEFORE INSERT ON product_evidence_items FOR EACH ROW "
    f"WHEN {SQLITE_IDENTITY_MISMATCH_SQL} "
    f"BEGIN SELECT RAISE(ABORT, '{IDENTITY_MISMATCH_MESSAGE}'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_identity_update "
    "BEFORE UPDATE OF product_id, stable_instrument_id, share_class_id ON product_evidence_items FOR EACH ROW "
    f"WHEN {SQLITE_IDENTITY_MISMATCH_SQL} "
    f"BEGIN SELECT RAISE(ABORT, '{IDENTITY_MISMATCH_MESSAGE}'); END",
)
PG_IDENTITY_FUNCTION = f"""
CREATE OR REPLACE FUNCTION product_evidence_items_identity()
RETURNS trigger AS $$
BEGIN
    IF {PG_IDENTITY_MISMATCH_SQL} THEN
        RAISE EXCEPTION '{IDENTITY_MISMATCH_MESSAGE}';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
PG_IDENTITY_TRIGGER = (
    "CREATE TRIGGER trg_product_evidence_identity BEFORE INSERT OR UPDATE OF "
    "product_id, stable_instrument_id, share_class_id ON product_evidence_items FOR EACH ROW "
    "EXECUTE FUNCTION product_evidence_items_identity()"
)

# Deutsche Meldungen; technische Details stehen nur im Audit.
KIND_LABELS: dict[str, str] = {
    "instrument_identity": "Produktidentität",
    "kid": "Basisinformationsblatt",
    "costs": "Kosten",
    "retrocession": "Retrozession",
    "suitability": "Eignung",
    "liquidity": "Liquidität",
    "currency": "Währung",
    "sustainability": "Nachhaltigkeit",
    "price_source": "Preisquelle",
    "snapshot": "Nachweissatz der Empfehlung",
}
MESSAGES: dict[str, str] = {
    MISSING: "Für das Produkt fehlt ein freigegebener Pflichtnachweis.",
    "PRODUCT_EVIDENCE_COST_MISSING": "Für das Produkt fehlt ein freigegebener Kostennachweis.",
    "PRODUCT_EVIDENCE_KID_MISSING": "Für das Produkt fehlt der freigegebene Nachweis zum Basisinformationsblatt.",
    "PRODUCT_EVIDENCE_RETROCESSION_MISSING": "Für das Produkt fehlt ein freigegebener Retrozessionsnachweis.",
    "PRODUCT_EVIDENCE_SUITABILITY_MISSING": "Für das Produkt fehlt ein freigegebener Eignungsnachweis.",
    STALE: "Ein Produktnachweis ist abgelaufen, noch nicht gültig oder wurde ersetzt.",
    CONFLICT: "Mehrere gleichzeitig gültige Produktnachweise widersprechen sich.",
    REVOKED: "Ein Produktnachweis wurde widerrufen.",
    HASH_MISMATCH: "Die Integrität eines Produktnachweises ist nicht belegt.",
    SHARE_CLASS_MISMATCH: "Der Produktnachweis gehört nicht zu dieser Produkt- oder Anteilsklassenidentität.",
}

Query = Callable[[str, Mapping[str, Any]], Iterable[Mapping[str, Any]]]


class ProductEvidenceDefect:
    """Befund: Code, betroffenes Produkt, Nachweisart (``snapshot`` = Satz)."""

    def __init__(self, code: str, product_id: str | None, kind: str) -> None:
        self.code = code
        self.product_id = product_id
        self.kind = kind

    def status(self) -> str:
        return STATUS_BY_CODE.get(self.code, "missing")

    def message(self) -> str:
        return f"{MESSAGES[self.code]} (Nachweisart: {KIND_LABELS.get(self.kind, self.kind)})"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status(), "reason_code": self.code, "product_id": self.product_id,
                "evidence_kind": self.kind, "message": self.message()}


def configure_synthetic_evidence(allowed: Callable[[], bool] | None) -> Callable[[], bool] | None:
    """Hinterlegt die Abfrage, ob synthetische Nachweise zaehlen (None = nie);
    liefert die vorherige."""
    previous = _RUNTIME_POLICY["synthetic_allowed"]
    _RUNTIME_POLICY["synthetic_allowed"] = allowed
    return previous


def synthetic_evidence_allowed() -> bool:
    allowed = _RUNTIME_POLICY["synthetic_allowed"]
    return allowed is not None and allowed() is True


def is_synthetic(source_type: Any) -> bool:
    return str(source_type or "").strip().casefold().startswith(SYNTHETIC_SOURCE_PREFIX)


# -- Identitaet --------------------------------------------------------------


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def product_identity(product: Mapping[str, Any]) -> tuple[str, str | None]:
    """Kanonische ``(Instrument, Anteilsklasse)``-Identitaet eines Produkts.

    Einzige Definition fuer Erfassung, Auswertung und Snapshot."""
    stable = (
        _clean(product.get("isin")) or _clean(product.get("internal_product_id"))
        or _clean(product.get("figi")) or str(product["id"])
    )
    return stable, _clean(product.get("share_class_figi"))


def evidence_identity(item: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return _clean(item.get("stable_instrument_id")), _clean(item.get("share_class_id"))


def identity_matches(item: Mapping[str, Any], product: Mapping[str, Any]) -> bool:
    """Exakt und symmetrisch: beide ohne Anteilsklasse oder beide mit derselben."""
    return evidence_identity(item) == product_identity(product)


# -- Integritaet -------------------------------------------------------------


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def stored_json_hash(text: Any, *, domain: bytes = b"") -> str | None:
    """Hash der gespeicherten kanonischen Form oder None, wenn sie es nicht ist."""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if canonical != text:
        return None
    return hashlib.sha256(domain + canonical.encode("utf-8")).hexdigest()


def rate_terms(payload: Any) -> tuple[str, int | None]:
    """``(Status, Satz in bps)``: ``known`` | ``not_applicable`` | ``missing``.

    NULL, fehlend und nicht anwendbar bleiben drei Zustaende -- nie 0."""
    if not isinstance(payload, dict):
        return "missing", None
    value = payload.get("value")
    if payload.get("status") == NOT_APPLICABLE:
        # Nichtanwendung und Wert schliessen sich aus.
        return (NOT_APPLICABLE, None) if value is None else ("missing", None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "missing", None
    return "known", value


def payload_defect_code(kind: str, payload: Any, source_reference: Any) -> str | None:
    if kind not in RATE_KINDS:
        return None
    if rate_terms(payload)[0] == "missing" or _clean(source_reference) is None:
        return MISSING_BY_KIND[kind]
    return None


# -- Auswertung --------------------------------------------------------------


def _in_force(item: Mapping[str, Any], today: str) -> bool:
    return str(item["valid_from"]) <= today and (
        item["valid_until"] is None or today <= str(item["valid_until"])
    )


def _scope(rows: list[Mapping[str, Any]], tenant_id: str) -> list[Mapping[str, Any]]:
    """Tenant-Nachweis vor Plattform-Nachweis. Ein blosser Entwurf oder ein
    stillgelegter Tenant-Nachweis verdraengt den Plattform-Nachweis nicht, ein
    freigegebener oder widerrufener schon (fail-closed)."""
    tenant = [r for r in rows if r["tenant_id"] == tenant_id and r["status"] in ("approved", "revoked")]
    return tenant or [r for r in rows if r["tenant_id"] is None and r["status"] in ("approved", "revoked")]


def _evaluate_kind(
    product: Mapping[str, Any], kind: str, rows: list[Mapping[str, Any]], *, tenant_id: str, today: str,
) -> tuple[str | None, Mapping[str, Any] | None]:
    scoped = _scope([r for r in rows if identity_matches(r, product)], tenant_id)
    approved = [r for r in scoped if r["status"] == "approved"]
    active = [r for r in approved if _in_force(r, today)]
    if len(active) > 1:
        return CONFLICT, None
    if not active:
        if any(r["status"] == "revoked" for r in scoped):
            return REVOKED, None
        if approved:
            return STALE, None
        if any(r["status"] == "approved" and _in_force(r, today) for r in _scope(rows, tenant_id)):
            return SHARE_CLASS_MISMATCH, None
        return MISSING_BY_KIND.get(kind, MISSING), None
    item = active[0]
    if (
        not is_sha256(item["canonical_payload_hash"])
        or stored_json_hash(item["canonical_payload_json"]) != item["canonical_payload_hash"]
        or not is_sha256(item["source_document_sha256"])
    ):
        return HASH_MISMATCH, None
    code = payload_defect_code(kind, json.loads(item["canonical_payload_json"]), item["source_reference"])
    return (code, None) if code is not None else (None, item)


def negotiated_cost_defect(
    item: Mapping[str, Any], negotiated_bps: int | None, *, tenant_id: str,
) -> str | None:
    """C-COMP-02 (Vorab-Entscheid 6.5): eine ausgehandelte Kondition
    (``override_ter_bps`` des Tenants) wirkt nur ueber einen tenantgebundenen,
    freigegebenen, gueltigen Kostennachweis mit genau diesem Satz. Fehlt er
    (nur Plattform-Nachweis, anderer Satz, kein Wert), sperrt die Auswertung
    mit ``PRODUCT_EVIDENCE_COST_MISSING``: der Override wird nie angewendet und
    es gibt keinen stillen Rueckfall auf den Standardwert."""
    if negotiated_bps is None:
        return None
    status, rate = rate_terms(json.loads(item["canonical_payload_json"]))
    if item["tenant_id"] != tenant_id or status != "known" or rate != negotiated_bps:
        return MISSING_BY_KIND["costs"]
    return None


def evaluate_items(
    product: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, tenant_id: str, jurisdiction: str, today: str,
    negotiated_ter_bps: int | None = None,
) -> tuple[list[ProductEvidenceDefect], list[Mapping[str, Any]]]:
    """Alle Pflichtarten eines Produkts; ``(Befunde, wirksame Nachweise)``.

    ``negotiated_ter_bps``: ausgehandelte Tenant-Kondition (6.5) oder None."""
    product_id = str(product["id"])
    own = [
        r for r in rows
        if str(r["product_id"]) == product_id and r["jurisdiction"] == jurisdiction
        and (r["tenant_id"] is None or r["tenant_id"] == tenant_id)
        and (synthetic_evidence_allowed() or not is_synthetic(r["source_type"]))
    ]
    defects: list[ProductEvidenceDefect] = []
    selected: list[Mapping[str, Any]] = []
    for kind in PRODUCT_EVIDENCE_KINDS:
        code, item = _evaluate_kind(
            product, kind, [r for r in own if r["evidence_kind"] == kind], tenant_id=tenant_id, today=today,
        )
        if code is None and item is not None and kind == "costs":
            code = negotiated_cost_defect(item, negotiated_ter_bps, tenant_id=tenant_id)
            item = None if code is not None else item
        if code is not None:
            defects.append(ProductEvidenceDefect(code, product_id, kind))
        elif item is not None:
            selected.append(item)
    return defects, selected


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def item_sort_key(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(_text(item[name]) for name in (
        "tenant_id", "stable_instrument_id", "share_class_id", "jurisdiction", "evidence_kind",
        "valid_from", "id", "canonical_payload_hash",
    ))


def lifecycle_fingerprint(items: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, ...], ...]:
    """Sortierte ``(Nachweis, Inhalt, Lebenszyklus)``-Menge fuer die Revalidierung."""
    return tuple(sorted(
        tuple(_text(item[name]) for name in (
            "id", "canonical_payload_hash", "source_document_sha256", "status", "approved_by", "approved_at",
            "approval_mode", "valid_from", "valid_until", "retired_or_revoked_at",
        )) for item in items
    ))


def item_binding(item: Mapping[str, Any]) -> dict[str, Any]:
    """Im Snapshot gebundene Felder eines Nachweises (ohne Notiz/UI-Text)."""
    stable, share_class = evidence_identity(item)
    return {
        "id": str(item["id"]),
        "tenant_id": item["tenant_id"],
        "product_id": str(item["product_id"]),
        "stable_instrument_id": stable,
        "share_class_id": share_class,
        "jurisdiction": item["jurisdiction"],
        "evidence_kind": item["evidence_kind"],
        "canonical_payload_hash": item["canonical_payload_hash"],
        "source_document_sha256": item["source_document_sha256"],
        "as_of": item["as_of"],
        "valid_from": item["valid_from"],
        "valid_until": item["valid_until"],
        "status": item["status"],
        "approved_by": item["approved_by"],
        "approved_at": item["approved_at"],
        "approval_mode": item["approval_mode"],
    }


# -- Dimensions-Snapshots (Vorab-Entscheid 6.3) ------------------------------

# Je Dimension die Nachweisarten, aus denen ihr Snapshot besteht. Ein Snapshot
# ist IMMER gebunden (nie NULL): ``bound`` mit den Quellen und Freigaben der
# wirksamen Nachweise oder -- wenn jeder dieser Nachweise belegt nicht
# anwendbar ist -- typisiert ``not_applicable`` mit denselben Quellen,
# Freigaben und eigenem SHA-256-Hash. Die ID ist inhaltsadressiert
# (``<dimension>:<sha256>``) und liegt im unveraenderlichen Satz-Snapshot.
DIMENSION_KINDS: dict[str, tuple[str, ...]] = {
    "eligibility": ("suitability",),
    "cost": ("costs", "retrocession"),
    "conflict": ("retrocession",),
}
DIMENSION_COLUMNS: dict[str, str] = {
    "eligibility": "eligibility_snapshot_id",
    "cost": "cost_snapshot_id",
    "conflict": "conflict_snapshot_id",
}
DIMENSION_SCHEMA = "ares-product-evidence-dimension/1"
DIMENSION_DOMAIN = b"ares-product-evidence-dimension/1\n"
DIMENSION_BOUND = "bound"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dimension_snapshot_hash(record: Mapping[str, Any]) -> str:
    """SHA-256 (Hex) ueber Domaene + kanonischen Inhalt (ohne Hash/ID)."""
    body = {key: value for key, value in record.items() if key not in ("snapshot_hash", "snapshot_id")}
    return hashlib.sha256(DIMENSION_DOMAIN + _canonical_json(body).encode("utf-8")).hexdigest()


def dimension_snapshot_id(dimension: str, digest: str) -> str:
    return f"{dimension}:{digest}"


def dimension_id_check_sql(column: str, dimension: str) -> str:
    """Dialektneutrale Formpruefung ``<dimension>:<64 hex>`` (Trigger)."""
    prefix = f"{dimension}:"
    return (
        f"({column} IS NOT NULL AND substr({column}, 1, {len(prefix)}) = '{prefix}' "
        f"AND length({column}) = {len(prefix) + 64} "
        f"AND ltrim(substr({column}, {len(prefix) + 1}), '0123456789abcdef') = '')"
    )


SNAPSHOT_UNBOUND_MESSAGE = (
    "product_evidence_snapshots: Eignungs-, Kosten- und Konfliktsnapshot muessen gebunden sein "
    "(Schema ares-product-evidence/v2)"
)
# Ausgeschrieben; identisch mit ``dimension_id_check_sql`` je Dimension + Schema 2
# (Test sichert die Deckung).
SNAPSHOT_BINDING_SQL = (
    "(NEW.eligibility_snapshot_id IS NOT NULL AND substr(NEW.eligibility_snapshot_id, 1, 12) = 'eligi"
    "bility:' AND length(NEW.eligibility_snapshot_id) = 76 AND ltrim(substr(NEW.eligibility_snapshot_"
    "id, 13), '0123456789abcdef') = '') AND (NEW.cost_snapshot_id IS NOT NULL AND substr(NEW.cost_sna"
    "pshot_id, 1, 5) = 'cost:' AND length(NEW.cost_snapshot_id) = 69 AND ltrim(substr(NEW.cost_snapsh"
    "ot_id, 6), '0123456789abcdef') = '') AND (NEW.conflict_snapshot_id IS NOT NULL AND substr(NEW.co"
    "nflict_snapshot_id, 1, 9) = 'conflict:' AND length(NEW.conflict_snapshot_id) = 73 AND ltrim(subs"
    "tr(NEW.conflict_snapshot_id, 10), '0123456789abcdef') = '') AND NEW.schema_version = 'ares-produ"
    "ct-evidence/v2'"
)
# 6.3 an der DB-Grenze: kein neuer Satz ohne die drei Dimensionsbindungen
# (Altbestand bleibt unberuehrt und wird in der Auswertung LEGACY/STALE).
SQLITE_SNAPSHOT_BINDING_TRIGGER = (
    "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_snapshot_binding_insert "
    "BEFORE INSERT ON product_evidence_snapshots FOR EACH ROW "
    f"WHEN NOT ({SNAPSHOT_BINDING_SQL}) "
    f"BEGIN SELECT RAISE(ABORT, '{SNAPSHOT_UNBOUND_MESSAGE}'); END"
)
PG_SNAPSHOT_BINDING_FUNCTION = f"""
CREATE OR REPLACE FUNCTION product_evidence_snapshots_binding()
RETURNS trigger AS $$
BEGIN
    IF NOT ({SNAPSHOT_BINDING_SQL}) THEN
        RAISE EXCEPTION '{SNAPSHOT_UNBOUND_MESSAGE}';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
PG_SNAPSHOT_BINDING_TRIGGER = (
    "CREATE TRIGGER trg_product_evidence_snapshot_binding BEFORE INSERT ON product_evidence_snapshots "
    "FOR EACH ROW EXECUTE FUNCTION product_evidence_snapshots_binding()"
)


def _payload_status(item: Mapping[str, Any]) -> Any:
    try:
        payload = json.loads(item["canonical_payload_json"])
    except (TypeError, ValueError):
        return None
    return payload.get("status") if isinstance(payload, dict) else None


def dimension_snapshots(
    items: Iterable[Mapping[str, Any]], negotiated: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Typisierte, gehashte Snapshots je Dimension aus den wirksamen
    Nachweisen eines Satzes (deterministisch, nur gebundene Werte)."""
    rows = sorted(items, key=item_sort_key)
    conditions = negotiated or {}
    out: dict[str, dict[str, Any]] = {}
    for dimension, kinds in DIMENSION_KINDS.items():
        members = [item for item in rows if item["evidence_kind"] in kinds]
        if not members:
            raise ValueError(f"Dimension {dimension} ohne wirksamen Nachweis")
        not_applicable = all(_payload_status(item) == NOT_APPLICABLE for item in members)
        record: dict[str, Any] = {
            "schema_version": DIMENSION_SCHEMA,
            "dimension": dimension,
            "status": NOT_APPLICABLE if not_applicable else DIMENSION_BOUND,
            "evidence_kinds": list(kinds),
            "sources": [{
                "item_id": str(item["id"]), "product_id": str(item["product_id"]),
                "evidence_kind": item["evidence_kind"], "source_type": item["source_type"],
                "source_reference": item["source_reference"],
                "source_document_sha256": item["source_document_sha256"],
                "canonical_payload_hash": item["canonical_payload_hash"],
                "valid_from": item["valid_from"], "valid_until": item["valid_until"],
            } for item in members],
            "approvals": [{
                "item_id": str(item["id"]), "approved_by": item["approved_by"],
                "approved_at": item["approved_at"], "approval_mode": item["approval_mode"],
            } for item in members],
        }
        if dimension == "cost":
            record["negotiated_conditions"] = [
                {"product_id": str(item["product_id"]), "override_ter_bps": conditions[str(item["product_id"])],
                 "item_id": str(item["id"])}
                for item in members
                if item["evidence_kind"] == "costs" and str(item["product_id"]) in conditions
            ]
        digest = dimension_snapshot_hash(record)
        record["snapshot_hash"] = digest
        record["snapshot_id"] = dimension_snapshot_id(dimension, digest)
        out[dimension] = record
    return out


def _dimensions_consistent(row: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    bound = payload.get("dimension_snapshots")
    if not isinstance(bound, dict) or set(bound) != set(DIMENSION_KINDS):
        return False
    for dimension, column in DIMENSION_COLUMNS.items():
        record = bound[dimension]
        if not isinstance(record, dict) or record.get("dimension") != dimension:
            return False
        digest = dimension_snapshot_hash(record)
        if record.get("snapshot_hash") != digest or record.get("snapshot_id") != dimension_snapshot_id(dimension, digest):
            return False
        if row[column] != record["snapshot_id"]:
            return False
    return True


# -- Gebundener Satz eines Laufs ---------------------------------------------

# Lauf, Mandat, Snapshot und Positionsprodukte in EINER Abfrage (Query-Budgets).
RUN_STATE_SQL = (
    "SELECT r.id AS run_id, r.product_evidence_hash AS run_hash, "
    "r.product_evidence_status, r.mandate_id AS run_mandate_id, m.tenant_id AS mandate_tenant_id, "
    "m.jurisdiction AS mandate_jurisdiction, s.id AS snapshot_id, s.tenant_id, s.mandate_id, "
    "s.recommendation_run_id, s.product_ids_json, s.item_ids_json, s.item_hashes_json, s.status, "
    "s.canonical_payload_json, s.product_evidence_hash, "
    "s.eligibility_snapshot_id, s.cost_snapshot_id, s.conflict_snapshot_id, "
    "rp.product_id, p.id, p.isin, p.internal_product_id, p.figi, p.share_class_figi, "
    "ue.override_ter_bps AS negotiated_ter_bps "
    "FROM recommendation_runs r JOIN mandates m ON m.id = r.mandate_id "
    "LEFT JOIN product_evidence_snapshots s ON s.id = r.product_evidence_snapshot_id "
    "LEFT JOIN recommendation_positions rp ON rp.run_id = r.id "
    "LEFT JOIN products p ON p.id = rp.product_id "
    # 6.5: hoechstens ein aktiver Universumseintrag je (Tenant, Jurisdiktion,
    # Produkt) (ux_product_universe_active_entry) -- keine Zeilenvervielfachung.
    "LEFT JOIN product_universe_entries ue ON ue.product_id = p.id AND ue.tenant_id = s.tenant_id "
    "AND ue.jurisdiction = COALESCE(NULLIF(m.jurisdiction, ''), 'CH') AND ue.deleted_at IS NULL "
    "AND ue.override_ter_bps IS NOT NULL "
    "WHERE r.id = :run_id"
)
RUN_PRODUCT_IDS_SQL = "SELECT DISTINCT product_id FROM recommendation_positions WHERE run_id = :run_id"
RUN_ITEMS_SQL = (
    "SELECT * FROM product_evidence_items WHERE product_id IN "
    "(SELECT product_id FROM recommendation_positions WHERE run_id = :run_id)"
)


def _bound(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Integritaetsgeprueftes Snapshot-Payload eines Laufs oder None."""
    if not is_sha256(row["product_evidence_hash"]) or row["run_hash"] != row["product_evidence_hash"]:
        return None
    if stored_json_hash(row["canonical_payload_json"], domain=PRODUCT_EVIDENCE_DOMAIN) != row["product_evidence_hash"]:
        return None
    payload = json.loads(row["canonical_payload_json"])
    if payload.get("schema_version") != PRODUCT_EVIDENCE_SCHEMA:
        return LEGACY_SET
    try:
        consistent = (
            payload["recommendation_run_id"] == str(row["run_id"]) == str(row["recommendation_run_id"])
            and payload["mandate_id"] == str(row["run_mandate_id"]) == str(row["mandate_id"])
            and payload["tenant_id"] == row["tenant_id"]
            and row["mandate_tenant_id"] in (None, row["tenant_id"])
            and payload["status"] == row["status"] == STATUS_VERIFIED
            and json.loads(row["product_ids_json"]) == payload["product_ids"]
            and json.loads(row["item_ids_json"]) == [item["id"] for item in payload["items"]]
            and json.loads(row["item_hashes_json"]) == [item["canonical_payload_hash"] for item in payload["items"]]
            and _dimensions_consistent(row, payload)
        )
    except (KeyError, TypeError, ValueError):
        return None
    return payload if consistent else None


# Satz des Schemas 1 (vor den Dimensions-Snapshots): integer gespeichert, aber
# ohne die verlangte Bindung -> STALE (neu pruefen und binden), nie beschaedigt.
LEGACY_SET: dict[str, Any] = {"legacy": True}


def run_evidence_state(
    query: Query, run_id: str, *, today: str,
) -> tuple[ProductEvidenceDefect | None, dict[str, Any] | None, list[Mapping[str, Any]]]:
    """``(Befund, Snapshot-Payload, gebundene Nachweise)`` eines Laufs.

    Ein Befund ist jede Abweichung des heute wirksamen Satzes vom gebundenen:
    fehlend, abgelaufen, widerrufen, ersetzt (auch inhaltsgleich), neuer
    Tenant-Vorrang, andere Anteilsklasse, andere Produkte, manipulierter Hash."""
    rows = list(query(RUN_STATE_SQL, {"run_id": str(run_id)}))
    row = rows[0] if rows else None
    if row is None or row["snapshot_id"] is None or row["product_evidence_status"] != STATUS_VERIFIED:
        return ProductEvidenceDefect(MISSING, None, "snapshot"), None, []
    payload = _bound(row)
    if payload is None:
        return ProductEvidenceDefect(HASH_MISMATCH, None, "snapshot"), None, []
    if payload is LEGACY_SET:
        return ProductEvidenceDefect(STALE, None, "snapshot"), None, []
    if row["mandate_jurisdiction"] != payload["mandate_jurisdiction"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    product_rows = [r for r in rows if r["product_id"] is not None]
    for product in product_rows:
        if product["id"] is None:
            return ProductEvidenceDefect(MISSING, str(product["product_id"]), "instrument_identity"), payload, []
    products = {str(p["id"]): p for p in product_rows}
    if sorted(products) != payload["product_ids"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    negotiated = {
        str(p["id"]): int(p["negotiated_ter_bps"]) for p in product_rows if p["negotiated_ter_bps"] is not None
    }
    items = list(query(RUN_ITEMS_SQL, {"run_id": str(run_id)}))
    effective: list[Mapping[str, Any]] = []
    for product_id in payload["product_ids"]:
        defects, selected = evaluate_items(
            products[product_id], items, tenant_id=payload["tenant_id"],
            jurisdiction=payload["jurisdiction"], today=today, negotiated_ter_bps=negotiated.get(product_id),
        )
        if defects:
            return defects[0], payload, []
        effective.extend(selected)
    effective.sort(key=item_sort_key)
    if [item_binding(item) for item in effective] != payload["items"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    # 6.3/6.5: Dimensions-Snapshots (inkl. gebundener ausgehandelter Kondition)
    # muessen dem heute wirksamen Stand entsprechen.
    if dimension_snapshots(effective, negotiated) != payload["dimension_snapshots"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    return None, payload, effective


def item_terms(item: Mapping[str, Any]) -> dict[str, Any]:
    status, rate = rate_terms(json.loads(item["canonical_payload_json"]))
    return {"status": status, "bps": rate, "source": item["source_reference"], "as_of": item["as_of"],
            "item_id": str(item["id"]), "payload_hash": item["canonical_payload_hash"]}


def bound_rate_terms(query: Query, run_id: Any, *, today: str) -> dict[str, dict[str, dict[str, Any]]]:
    """``{Produkt: {"costs"|"retrocession": Konditionen}}`` ausschliesslich aus
    dem gebundenen, heute gueltigen Satz. Kein Satz oder ein Befund -> leer
    (unbekannt, nie 0 und nie Stammdaten)."""
    if not run_id:
        return {}
    defect, _payload, items = run_evidence_state(query, str(run_id), today=today)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    if defect is not None:
        return out
    for item in items:
        if item["evidence_kind"] in RATE_KINDS:
            out.setdefault(str(item["product_id"]), {})[item["evidence_kind"]] = item_terms(item)
    return out


def bound_term(terms: Mapping[str, Any], product_id: Any, kind: str) -> tuple[str, int | None]:
    """``(Status, bps)`` eines Produkts aus ``bound_rate_terms``."""
    entry = (terms.get(str(product_id)) or {}).get(kind)
    return ("missing", None) if entry is None else (entry["status"], entry["bps"])


def unresolved_retrocession(query: Query, run_id: Any, *, today: str) -> bool:
    """True, wenn mindestens ein Produkt des Laufs eine positive oder nicht
    belegte Retrozession traegt."""
    terms = bound_rate_terms(query, run_id, today=today)
    for product in query(RUN_PRODUCT_IDS_SQL, {"run_id": str(run_id)}):
        status, rate = bound_term(terms, product["product_id"], "retrocession")
        if status != NOT_APPLICABLE and rate != 0:
            return True
    return False


__all__ = [
    "CONFLICT", "HASH_MISMATCH", "KIND_LABELS", "MESSAGES", "MISSING", "MISSING_BY_KIND", "NOT_APPLICABLE",
    "PRODUCT_EVIDENCE_DOMAIN", "PRODUCT_EVIDENCE_EVALUATOR", "PRODUCT_EVIDENCE_KINDS", "PRODUCT_EVIDENCE_SCHEMA",
    "DIMENSION_COLUMNS", "DIMENSION_DOMAIN", "DIMENSION_KINDS", "DIMENSION_SCHEMA", "LEGACY_SET",
    "PRODUCT_EVIDENCE_SCHEMA_LEGACY", "dimension_id_check_sql", "dimension_snapshot_hash", "dimension_snapshot_id",
    "dimension_snapshots", "negotiated_cost_defect",
    "PG_SNAPSHOT_BINDING_FUNCTION", "PG_SNAPSHOT_BINDING_TRIGGER", "SNAPSHOT_BINDING_SQL", "SNAPSHOT_UNBOUND_MESSAGE",
    "SQLITE_SNAPSHOT_BINDING_TRIGGER",
    "ProductEvidenceDefect", "RATE_KINDS", "REVOKED", "SHARE_CLASS_MISMATCH", "SQLITE_TENANT_TRIGGERS", "STALE", "STATUS_VERIFIED",
    "TENANT_MISMATCH_MESSAGE", "TENANT_MISMATCH_SQL",
    "IDENTITY_MISMATCH_MESSAGE", "PG_IDENTITY_FUNCTION", "PG_IDENTITY_TRIGGER", "SQLITE_IDENTITY_TRIGGERS",
    "identity_mismatch_sql", "PG_IDENTITY_MISMATCH_SQL", "SQLITE_IDENTITY_MISMATCH_SQL",
    "bound_rate_terms", "bound_term", "configure_synthetic_evidence", "evaluate_items", "evidence_identity", "identity_matches", "is_sha256", "is_synthetic",
    "item_binding", "item_sort_key", "item_terms", "lifecycle_fingerprint", "payload_defect_code",
    "product_identity", "rate_terms", "run_evidence_state", "stored_json_hash", "synthetic_evidence_allowed",
    "unresolved_retrocession",
]
