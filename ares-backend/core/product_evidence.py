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
PRODUCT_EVIDENCE_SCHEMA = "ares-product-evidence/v1"
PRODUCT_EVIDENCE_EVALUATOR = "ares-product-evidence/1"
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


def evaluate_items(
    product: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, tenant_id: str, jurisdiction: str, today: str,
) -> tuple[list[ProductEvidenceDefect], list[Mapping[str, Any]]]:
    """Alle Pflichtarten eines Produkts; ``(Befunde, wirksame Nachweise)``."""
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


# -- Gebundener Satz eines Laufs ---------------------------------------------

# Lauf, Mandat, Snapshot und Positionsprodukte in EINER Abfrage (Query-Budgets).
RUN_STATE_SQL = (
    "SELECT r.id AS run_id, r.product_evidence_hash AS run_hash, "
    "r.product_evidence_status, r.mandate_id AS run_mandate_id, m.tenant_id AS mandate_tenant_id, "
    "m.jurisdiction AS mandate_jurisdiction, s.id AS snapshot_id, s.tenant_id, s.mandate_id, "
    "s.recommendation_run_id, s.product_ids_json, s.item_ids_json, s.item_hashes_json, s.status, "
    "s.canonical_payload_json, s.product_evidence_hash, "
    "rp.product_id, p.id, p.isin, p.internal_product_id, p.figi, p.share_class_figi "
    "FROM recommendation_runs r JOIN mandates m ON m.id = r.mandate_id "
    "LEFT JOIN product_evidence_snapshots s ON s.id = r.product_evidence_snapshot_id "
    "LEFT JOIN recommendation_positions rp ON rp.run_id = r.id "
    "LEFT JOIN products p ON p.id = rp.product_id WHERE r.id = :run_id"
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
        )
    except (KeyError, TypeError, ValueError):
        return None
    return payload if consistent else None


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
    if row["mandate_jurisdiction"] != payload["mandate_jurisdiction"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    product_rows = [r for r in rows if r["product_id"] is not None]
    for product in product_rows:
        if product["id"] is None:
            return ProductEvidenceDefect(MISSING, str(product["product_id"]), "instrument_identity"), payload, []
    products = {str(p["id"]): p for p in product_rows}
    if sorted(products) != payload["product_ids"]:
        return ProductEvidenceDefect(STALE, None, "snapshot"), payload, []
    items = list(query(RUN_ITEMS_SQL, {"run_id": str(run_id)}))
    effective: list[Mapping[str, Any]] = []
    for product_id in payload["product_ids"]:
        defects, selected = evaluate_items(
            products[product_id], items, tenant_id=payload["tenant_id"],
            jurisdiction=payload["jurisdiction"], today=today,
        )
        if defects:
            return defects[0], payload, []
        effective.extend(selected)
    effective.sort(key=item_sort_key)
    if [item_binding(item) for item in effective] != payload["items"]:
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
    "ProductEvidenceDefect", "RATE_KINDS", "REVOKED", "SHARE_CLASS_MISMATCH", "SQLITE_TENANT_TRIGGERS", "STALE", "STATUS_VERIFIED",
    "TENANT_MISMATCH_MESSAGE", "TENANT_MISMATCH_SQL",
    "bound_rate_terms", "bound_term", "configure_synthetic_evidence", "evaluate_items", "evidence_identity", "identity_matches", "is_sha256", "is_synthetic",
    "item_binding", "item_sort_key", "item_terms", "lifecycle_fingerprint", "payload_defect_code",
    "product_identity", "rate_terms", "run_evidence_state", "stored_json_hash", "synthetic_evidence_allowed",
    "unresolved_retrocession",
]
