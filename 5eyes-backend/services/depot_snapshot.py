"""DepotSnapshotV1 und IST-Stress (DEPOT-E2E-STRESS-001 Option 2, DEPOT-E2E-SNAPSHOT-001).

Der bestehende Stress-Replay rechnet auf der SOLL-Gewichtung der
TargetAllocation (Scope ``approved_target_allocation``, PR #751). Dieser
Service ergaenzt den Scope ``current_holdings_snapshot``: dieselben
historischen Szenarien (``services.backtest_stress``), aber auf den
IST-Gewichten eines unveraenderlichen, hash-gebundenen Depot-Snapshots.

Bestand (CIO-Entscheid 2026-10-26): der GESAMTE erfasste Depotbestand des
Mandats -- neueste Holding je Produkt, auch ausserhalb der Positionen des
aktuellen Laufs --, bewertet mit den Regeln der Handelsliste
(``portfolio_engine_live_rebalancing.value_mandate_holdings``) und geprueft
mit derselben Abdeckungspruefung ``assert_holdings_valuation_complete``
(services/portfolio_handoff.py). Nicht verwendet werden der
``current_amount_rappen`` eines Laufs (Kopie), Zielbetraege und Vermoegens-
positionen ohne Bewertung; Vorsorge (3a/FZ/Police) ist eine
Vermoegensposition und erreicht diese Quelle nicht. Laufpositionen ohne
Bestand sind fuer den IST irrelevant (IST misst, was gehalten wird).

Waehrung: jede Position ist Stueckzahl x letzter Marktpreis; der Preis ist
in ``product.currency`` notiert und wird mit
``_convert_price_rappen_to_target_currency`` auf die Basiswaehrung des
Mandats umgerechnet. Ein nur als Marktwert erfasster Bestand ist laut
Docstring dieser Funktion eine CHF-Eingabe unabhaengig von der
Produktwaehrung -- seine Waehrung ist nicht belegt, darum fail-closed.

DepotSnapshotV1 haelt fest: Stichtag, Bestandsdatum, Basiswaehrung,
FX-Evidenz (``FXRateSource.canonical_model_signature``) und jede Position
(nach ID sortiert) mit Stueckzahl, Preis, Preisdatum, Produktwaehrung, Wert
in Basiswaehrung und Anlageklassen-Zuordnung. ``snapshot_hash`` ist SHA-256
ueber den kanonischen Inhalt, ``snapshot_id`` leitet sich daraus ab; der
Verifier prueft nur aus dem gespeicherten Inhalt.

Fail-closed: unvollstaendige Bewertung -> kein Snapshot. Position ohne
eindeutige Anlageklasse -> Snapshot mit Ausweis, aber keine Szenariozahlen
(kein Default-Bucket). Szenario-Parameter werden nicht veraendert.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.review import Product
from services.backtest_stress import compute_stress_for_weights, stress_catalog_hash
from services.depot_check import PRODUCT_ASSET_CLASS_ALIASES
from services.portfolio_engine_live_rebalancing import value_mandate_holdings
from services.portfolio_handoff import (
    HoldingsValuationIncompleteError,
    assert_holdings_valuation_complete,
)

DEPOT_SNAPSHOT_VERSION = "DepotSnapshotV1"
IST_STRESS_SCOPE = "current_holdings_snapshot"
IST_STRESS_SCOPE_LABEL = (
    "Stress-Replay des IST-Depots (Bestand gemaess Depot-Snapshot)"
)

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")

SOURCE_MANDATE_HOLDINGS = "mandate_holdings_valuation"

STATUS_OK = "ok"
STATUS_UNCLASSIFIED = "unclassified_positions"
STATUS_NO_HOLDINGS = "no_holdings"

REASON_UNKNOWN_ASSET_CLASS = "unknown_asset_class"

_BODY_KEYS = (
    "snapshot_version", "mandate_id", "as_of", "holdings_as_of", "currency",
    "fx_evidence", "source", "positions",
)


class DepotSnapshotIntegrityError(ValueError):
    """Gespeicherter Depot-Snapshot ist unvollstaendig oder manipuliert."""


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(payload) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _product_bucket_weights(product: Product) -> tuple[dict | None, str | None]:
    raw = str(getattr(product, "asset_class", "") or "").strip().lower()
    bucket = PRODUCT_ASSET_CLASS_ALIASES.get(raw)
    if bucket is None:
        return None, REASON_UNKNOWN_ASSET_CLASS
    return {bucket: 10000}, None


def _complete_holdings_valuation(db: Session, mandate: Mandate, fx_source, target: str) -> dict:
    """Bewertung des gesamten Bestands; jede Luecke -> ``HoldingsValuationIncompleteError``."""
    valuation = value_mandate_holdings(db, mandate.id, fx_source=fx_source, target_currency=target)
    if not valuation["holding_positions_count"]:
        raise HoldingsValuationIncompleteError(
            "Kein erfasster Depotbestand: es gibt keinen IST-Bestand fuer einen Stress-Replay."
        )
    # Fehlender/veralteter Preis, FX-Fehler (Regeln der Handelsliste).
    assert_holdings_valuation_complete(valuation)
    if valuation["missing_product_count"]:
        raise HoldingsValuationIncompleteError(
            f"{valuation['missing_product_count']} Depotposition(en) ohne Produktstammdaten."
        )
    if valuation["missing_units_count"]:
        raise HoldingsValuationIncompleteError(
            f"{valuation['missing_units_count']} Depotposition(en) ohne erfasste Stueckzahl: "
            "Wert und Waehrung sind nicht durch Stueckzahl x Marktpreis belegt."
        )
    if any(p["current_market_value_rappen"] is None for p in valuation["positions"]):
        raise HoldingsValuationIncompleteError("Mindestens eine Depotposition ist nicht bewertet.")
    return valuation


def build_depot_snapshot(db: Session, mandate: Mandate, *, as_of: date, fx_source=None) -> dict:
    """Erzeugt den DepotSnapshotV1 des bewerteten IST-Bestands (nicht persistiert).

    ``HoldingsValuationIncompleteError``/``ValueError`` werden nicht
    abgefangen: ohne vollstaendige Bewertung kein Snapshot.
    """
    from services.currency.fx_rates import FXRateSource

    target = str(getattr(mandate, "base_currency", None) or "CHF").upper().strip() or "CHF"
    if fx_source is None:
        fx_source = FXRateSource.from_db_for_model(db)
    valuation = _complete_holdings_valuation(db, mandate, fx_source, target)
    product_ids = sorted({p["product_id"] for p in valuation["positions"]})
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}
    positions, currencies = [], set()
    for entry in valuation["positions"]:
        product = products[entry["product_id"]]
        weights, reason = _product_bucket_weights(product)
        if entry["product_currency"]:
            currencies.add(entry["product_currency"])
        positions.append({
            "position_id": str(entry["holding_id"]),
            "product_id": str(entry["product_id"]),
            "isin": str(getattr(product, "isin", "") or "") or None,
            "asset_class": str(getattr(product, "asset_class", "") or "") or None,
            "holding_as_of_date": entry["holding_as_of_date"],
            "units_milli": int(entry["units_milli"]),
            "price_rappen": int(entry["latest_price_rappen"]),
            "price_date": entry["latest_price_date"],
            "product_currency": entry["product_currency"],
            "fx_converted": bool(entry["fx_converted"]),
            "valuation_basis": entry["valuation_basis"],
            "amount_base_rappen": int(entry["current_market_value_rappen"]),
            "bucket_weights_bps": weights,
            "unclassified_reason": reason,
        })
    body = {
        "snapshot_version": DEPOT_SNAPSHOT_VERSION,
        "mandate_id": str(getattr(mandate, "id", "") or ""),
        "as_of": as_of.isoformat(),
        "holdings_as_of": valuation["as_of_date"],
        "currency": target,
        "fx_evidence": fx_source.canonical_model_signature(
            sorted(currencies | {target}), target_currency=target,
        ),
        "source": SOURCE_MANDATE_HOLDINGS,
        "positions": sorted(positions, key=lambda item: item["position_id"]),
    }
    snapshot_hash = _sha256(body)
    return {**body, "snapshot_hash": snapshot_hash, "snapshot_id": f"dps-{snapshot_hash[:24]}"}


def verify_depot_snapshot(snapshot) -> dict:
    """Prueft Version, Vollstaendigkeit, Hash und ID aus dem Inhalt selbst."""
    if not isinstance(snapshot, dict):
        raise DepotSnapshotIntegrityError("Depot-Snapshot muss ein Objekt sein.")
    if snapshot.get("snapshot_version") != DEPOT_SNAPSHOT_VERSION:
        raise DepotSnapshotIntegrityError("Depot-Snapshot hat eine unbekannte Version.")
    expected_keys = set(_BODY_KEYS) | {"snapshot_hash", "snapshot_id"}
    if set(snapshot) != expected_keys:
        raise DepotSnapshotIntegrityError("Depot-Snapshot hat unerwartete oder fehlende Felder.")
    body = {key: snapshot[key] for key in _BODY_KEYS}
    expected_hash = _sha256(body)
    if snapshot["snapshot_hash"] != expected_hash or snapshot["snapshot_id"] != f"dps-{expected_hash[:24]}":
        raise DepotSnapshotIntegrityError("Depot-Snapshot-Hash stimmt nicht mit dem Inhalt ueberein.")
    positions = body["positions"]
    if not isinstance(positions, list) or [p.get("position_id") for p in positions] != sorted(
        p.get("position_id") for p in positions
    ):
        raise DepotSnapshotIntegrityError("Depot-Snapshot: Positionen sind nicht kanonisch sortiert.")
    return snapshot


def ist_weights_from_snapshot(snapshot: dict) -> tuple[dict | None, str, list[dict]]:
    """IST-Bucket-Gewichte (bps) eines verifizierten Snapshots.

    Returns ``(weights_bps | None, status, unclassified_positions)``.
    """
    positions = snapshot.get("positions") or []
    unclassified = [
        {"position_id": p["position_id"], "reason": p["unclassified_reason"]}
        for p in positions
        if p.get("bucket_weights_bps") is None
    ]
    if unclassified:
        return None, STATUS_UNCLASSIFIED, unclassified
    total = sum(_int(p.get("amount_base_rappen")) for p in positions)
    if total <= 0:
        return None, STATUS_NO_HOLDINGS, []
    amounts = {bucket: 0.0 for bucket in BUCKETS}
    for p in positions:
        base = _int(p.get("amount_base_rappen"))
        for bucket, weight in (p.get("bucket_weights_bps") or {}).items():
            amounts[bucket] += base * _int(weight) / 10000.0
    return {bucket: int(round(amounts[bucket] / total * 10000)) for bucket in BUCKETS}, STATUS_OK, []


_STATUS_WARNINGS = {
    STATUS_UNCLASSIFIED: (
        "IST-Stress nicht berechnet: mindestens eine Depotposition hat keine "
        "eindeutige Anlageklassen-Zuordnung. Zuordnung erfassen und einen "
        "neuen Depot-Snapshot erstellen."
    ),
    STATUS_NO_HOLDINGS: (
        "IST-Stress nicht berechnet: im Depot-Snapshot ist kein bewerteter "
        "IST-Bestand erfasst."
    ),
}


def compute_ist_stress(snapshot: dict) -> dict:
    """Stress-Replay (bestehende Szenarien) auf den IST-Gewichten des Snapshots."""
    verify_depot_snapshot(snapshot)
    weights, status, unclassified = ist_weights_from_snapshot(snapshot)
    scenarios = compute_stress_for_weights(weights) if weights is not None else []
    catalog_hash = stress_catalog_hash()
    result = {
        "scope": IST_STRESS_SCOPE,
        "scope_label": IST_STRESS_SCOPE_LABEL,
        "status": status,
        "mandate_id": snapshot["mandate_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "as_of": snapshot["as_of"],
        "currency": snapshot["currency"],
        "source": snapshot["source"],
        "weights_bps": weights or {},
        "scenarios": scenarios,
        "unclassified_positions": unclassified,
        "stress_catalog_hash": catalog_hash,
    }
    if status in _STATUS_WARNINGS:
        result["warning"] = _STATUS_WARNINGS[status]
    result["result_hash"] = _sha256({
        "snapshot_hash": snapshot["snapshot_hash"],
        "stress_catalog_hash": catalog_hash,
        "status": status,
        "weights_bps": result["weights_bps"],
        "scenarios": scenarios,
    })
    return result


# --- Persistenz (append-only Tabelle depot_snapshots) -----------------------

def persist_depot_snapshot(db: Session, snapshot: dict, *, mandate: Mandate, created_by: str, created_at: str):
    """Speichert den Snapshot (idempotent: gleicher Inhalt = gleiche ID)."""
    from models.snapshots import DepotSnapshot

    verify_depot_snapshot(snapshot)
    existing = db.query(DepotSnapshot).filter(DepotSnapshot.id == snapshot["snapshot_id"]).first()
    if existing is not None:
        verify_persisted_depot_snapshot(existing, mandate_id=snapshot["mandate_id"])
        return existing, False
    row = DepotSnapshot(
        id=snapshot["snapshot_id"],
        schema_version=DEPOT_SNAPSHOT_VERSION,
        mandate_id=snapshot["mandate_id"],
        client_id=str(getattr(mandate, "client_id", "") or ""),
        as_of_date=snapshot["as_of"],
        currency=snapshot["currency"],
        source=snapshot["source"],
        snapshot_json=_canonical(snapshot),
        snapshot_hash=snapshot["snapshot_hash"],
        created_by=created_by,
        created_at=created_at,
    )
    db.add(row)
    return row, True


def verify_persisted_depot_snapshot(row, *, mandate_id: str) -> dict:
    """Gespeicherte Zeile -> verifizierter Snapshot; jede Abweichung zwischen
    JSON, Hash-Spalte, ID und Kopfspalten ist ein Integritaetsfehler."""
    try:
        snapshot = json.loads(getattr(row, "snapshot_json", None) or "")
    except (TypeError, ValueError) as exc:
        raise DepotSnapshotIntegrityError("Gespeicherter Depot-Snapshot ist kein gueltiges JSON.") from exc
    verify_depot_snapshot(snapshot)
    header = (
        row.id, row.snapshot_hash, row.mandate_id, row.as_of_date, row.currency,
        row.source, row.schema_version,
    )
    content = (
        snapshot["snapshot_id"], snapshot["snapshot_hash"], snapshot["mandate_id"],
        snapshot["as_of"], snapshot["currency"], snapshot["source"], DEPOT_SNAPSHOT_VERSION,
    )
    if header != content or snapshot["mandate_id"] != mandate_id:
        raise DepotSnapshotIntegrityError(
            "Gespeicherter Depot-Snapshot widerspricht seinen Kopfdaten oder dem Mandat."
        )
    return snapshot
