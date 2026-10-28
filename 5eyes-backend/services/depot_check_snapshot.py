"""DepotCheckAnalysisSnapshot (DEPOT-E2E-SNAPSHOT-001, CIO-Entscheid).

Das Depot-Check-Ergebnis wird an genau einen DepotSnapshotV1
(services/depot_snapshot.py) gebunden -- ``snapshot_id`` + ``snapshot_hash`` --
und mit Analyse-Version und Ergebnis-Hash append-only gespeichert. Der
JSON-Endpunkt (``GET /depot-check?analysis_snapshot_id=``) und das
Depot-Check-PDF lesen denselben gespeicherten Snapshot; ein neuer Stand
erzeugt einen neuen Snapshot, nie eine stille Nachberechnung.

IST: ``compute_depot_check(..., holdings_snapshot=...)`` -- genau der Bestand
des Depot-Snapshots. SOLL-Vergleich: Zielbetraege des gueltigen Laufs und die
aktuelle TargetAllocation; beide IDs werden im Snapshot festgehalten.

``result_hash`` = SHA-256 ueber das Ergebnis, ``analysis_hash`` = SHA-256 ueber
den gesamten Inhalt, ``analysis_snapshot_id`` leitet sich daraus ab (gleicher
Inhalt = gleiche ID). Der Verifier prueft nur aus dem gespeicherten Inhalt.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation
from models.mandates import Mandate
from services.depot_check import _select_latest_run, compute_depot_check
from services.depot_snapshot import (
    DepotSnapshotIntegrityError,
    _canonical,
    _sha256,
    verify_depot_snapshot,
    verify_persisted_depot_snapshot,
)

DEPOT_CHECK_ANALYSIS_VERSION = "DepotCheckAnalysisV1"

_BODY_KEYS = (
    "analysis_version", "mandate_id", "snapshot_id", "snapshot_hash", "as_of",
    "holdings_as_of", "currency", "target_allocation_id", "recommendation_run_id",
    "result", "result_hash",
)
_IDENTITY_KEYS = (
    "analysis_snapshot_id", "analysis_version", "snapshot_id", "snapshot_hash",
    "as_of", "result_hash", "target_allocation_id", "recommendation_run_id",
)

NO_ANALYSIS_MESSAGE = (
    "Depot-Check-PDF nicht moeglich: zum erfassten Depotbestand gibt es keinen "
    "gespeicherten Depot-Check (Depot-Snapshot). Ein Berater muss den Depot-Check "
    "einmal erzeugen."
)


class DepotCheckAnalysisIntegrityError(DepotSnapshotIntegrityError):
    """Gespeicherter Depot-Check-Snapshot ist unvollstaendig, manipuliert oder
    nicht an seinen Depot-Snapshot gebunden."""


def _current_target_allocation_id(db: Session, mandate: Mandate) -> str | None:
    # Dieselbe Auswahl wie compute_depot_check (Bucket-Drift gegen Soll).
    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    return str(ta.id) if ta is not None else None


def build_depot_check_analysis(db: Session, mandate: Mandate, snapshot: dict) -> dict:
    """Depot-Check auf dem Bestand eines verifizierten Depot-Snapshots (nicht persistiert)."""
    from services.house_matrix_benchmark import resolve_depotcheck_benchmark

    verify_depot_snapshot(snapshot)
    if snapshot["mandate_id"] != str(getattr(mandate, "id", "") or ""):
        raise DepotCheckAnalysisIntegrityError("Depot-Snapshot gehoert nicht zu diesem Mandat.")
    result = compute_depot_check(db, mandate, holdings_snapshot=snapshot)
    # Wie GET /depot-check: Status der HouseMatrix-Referenz gehoert zum Ergebnis.
    result["house_matrix_benchmark"] = resolve_depotcheck_benchmark(db, mandate).public()
    result = json.loads(_canonical(result))
    run = _select_latest_run(db, mandate)
    body = {
        "analysis_version": DEPOT_CHECK_ANALYSIS_VERSION,
        "mandate_id": snapshot["mandate_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "as_of": snapshot["as_of"],
        "holdings_as_of": snapshot["holdings_as_of"],
        "currency": snapshot["currency"],
        "target_allocation_id": _current_target_allocation_id(db, mandate),
        "recommendation_run_id": str(run.id) if run is not None else None,
        "result": result,
        "result_hash": _sha256(result),
    }
    analysis_hash = _sha256(body)
    return {**body, "analysis_hash": analysis_hash, "analysis_snapshot_id": f"dca-{analysis_hash[:24]}"}


def verify_depot_check_analysis(analysis) -> dict:
    """Prueft Version, Vollstaendigkeit, Ergebnis-Hash, Inhalts-Hash und ID."""
    if not isinstance(analysis, dict):
        raise DepotCheckAnalysisIntegrityError("Depot-Check-Snapshot muss ein Objekt sein.")
    if analysis.get("analysis_version") != DEPOT_CHECK_ANALYSIS_VERSION:
        raise DepotCheckAnalysisIntegrityError("Depot-Check-Snapshot hat eine unbekannte Version.")
    if set(analysis) != set(_BODY_KEYS) | {"analysis_hash", "analysis_snapshot_id"}:
        raise DepotCheckAnalysisIntegrityError("Depot-Check-Snapshot hat unerwartete oder fehlende Felder.")
    if analysis["result_hash"] != _sha256(analysis["result"]):
        raise DepotCheckAnalysisIntegrityError("Depot-Check-Ergebnis stimmt nicht mit seinem Hash ueberein.")
    expected = _sha256({key: analysis[key] for key in _BODY_KEYS})
    if analysis["analysis_hash"] != expected or analysis["analysis_snapshot_id"] != f"dca-{expected[:24]}":
        raise DepotCheckAnalysisIntegrityError("Depot-Check-Snapshot-Hash stimmt nicht mit dem Inhalt ueberein.")
    return analysis


def public_depot_check_payload(analysis: dict) -> dict:
    """JSON-Antwort: gespeichertes Ergebnis plus Snapshot-Identitaet."""
    return {**analysis["result"], **{key: analysis[key] for key in _IDENTITY_KEYS}}


# --- Persistenz (append-only Tabelle depot_check_analysis_snapshots) --------

def persist_depot_check_analysis(db: Session, analysis: dict, *, mandate: Mandate, created_by: str, created_at: str):
    """Speichert den Snapshot (idempotent: gleicher Inhalt = gleiche ID)."""
    from models.snapshots import DepotCheckAnalysisSnapshot

    verify_depot_check_analysis(analysis)
    existing = (
        db.query(DepotCheckAnalysisSnapshot)
        .filter(DepotCheckAnalysisSnapshot.id == analysis["analysis_snapshot_id"])
        .first()
    )
    if existing is not None:
        _verify_row(existing, mandate_id=analysis["mandate_id"])
        return existing, False
    row = DepotCheckAnalysisSnapshot(
        id=analysis["analysis_snapshot_id"],
        schema_version=DEPOT_CHECK_ANALYSIS_VERSION,
        mandate_id=analysis["mandate_id"],
        client_id=str(getattr(mandate, "client_id", "") or ""),
        depot_snapshot_id=analysis["snapshot_id"],
        depot_snapshot_hash=analysis["snapshot_hash"],
        as_of_date=analysis["as_of"],
        analysis_json=_canonical(analysis),
        analysis_hash=analysis["analysis_hash"],
        result_hash=analysis["result_hash"],
        created_by=created_by,
        created_at=created_at,
    )
    db.add(row)
    return row, True


def _verify_row(row, *, mandate_id: str) -> dict:
    try:
        analysis = json.loads(getattr(row, "analysis_json", None) or "")
    except (TypeError, ValueError) as exc:
        raise DepotCheckAnalysisIntegrityError("Gespeicherter Depot-Check ist kein gueltiges JSON.") from exc
    verify_depot_check_analysis(analysis)
    header = (
        row.id, row.analysis_hash, row.result_hash, row.mandate_id, row.depot_snapshot_id,
        row.depot_snapshot_hash, row.as_of_date, row.schema_version,
    )
    content = (
        analysis["analysis_snapshot_id"], analysis["analysis_hash"], analysis["result_hash"],
        analysis["mandate_id"], analysis["snapshot_id"], analysis["snapshot_hash"],
        analysis["as_of"], DEPOT_CHECK_ANALYSIS_VERSION,
    )
    if header != content or analysis["mandate_id"] != mandate_id:
        raise DepotCheckAnalysisIntegrityError(
            "Gespeicherter Depot-Check widerspricht seinen Kopfdaten oder dem Mandat."
        )
    return analysis


def load_depot_check_analysis(db: Session, mandate: Mandate, analysis_id: str | None = None) -> dict | None:
    """Laedt und verifiziert einen gespeicherten Depot-Check samt Bindung an
    seinen Depot-Snapshot. Ohne ``analysis_id`` der juengste des Mandats
    (``None``, wenn keiner existiert); unbekannte ID -> ``LookupError``."""
    from models.snapshots import DepotCheckAnalysisSnapshot, DepotSnapshot

    query = db.query(DepotCheckAnalysisSnapshot).filter(
        DepotCheckAnalysisSnapshot.mandate_id == mandate.id,
    )
    if analysis_id is not None:
        row = query.filter(DepotCheckAnalysisSnapshot.id == analysis_id).first()
        if row is None:
            raise LookupError("Depot-Check-Snapshot nicht gefunden.")
    else:
        row = query.order_by(
            DepotCheckAnalysisSnapshot.created_at.desc(), DepotCheckAnalysisSnapshot.id.desc(),
        ).first()
        if row is None:
            return None
    analysis = _verify_row(row, mandate_id=mandate.id)
    depot_row = (
        db.query(DepotSnapshot)
        .filter(DepotSnapshot.id == analysis["snapshot_id"], DepotSnapshot.mandate_id == mandate.id)
        .first()
    )
    if depot_row is None:
        raise DepotCheckAnalysisIntegrityError("Der gebundene Depot-Snapshot fehlt.")
    snapshot = verify_persisted_depot_snapshot(depot_row, mandate_id=mandate.id)
    if snapshot["snapshot_hash"] != analysis["snapshot_hash"]:
        raise DepotCheckAnalysisIntegrityError("Depot-Check ist nicht an diesen Depot-Snapshot gebunden.")
    return analysis


def assert_analysis_matches_current_allocation(db: Session, mandate: Mandate, analysis: dict) -> None:
    """Das PDF kombiniert den gespeicherten Depot-Check mit der aktuellen
    Strategie: nur zulaessig, wenn beide auf derselben Soll-Allokation beruhen."""
    if analysis.get("target_allocation_id") != _current_target_allocation_id(db, mandate):
        raise ValueError(
            "Depot-Check kann nicht erstellt werden: die Soll-Allokation hat sich seit "
            "dem gespeicherten Depot-Check geaendert. Bitte den Depot-Check zum "
            "Depot-Snapshot neu speichern."
        )


def mandate_has_recorded_holdings(db: Session, mandate: Mandate) -> bool:
    """True, sobald fuer das Mandat ein Depotbestand erfasst ist (neueste
    Holding je Produkt mit Stueckzahl oder Marktwert > 0) -- derselbe Filter
    wie die Bestandsbewertung des Depot-Snapshots. Nur bei ``False`` ist ein
    Depot-Check-PDF ohne Snapshot-Bindung (reine SOLL-Analyse) zulaessig."""
    from services.portfolio_engine_live_rebalancing import _latest_holdings_by_product_for_mandate

    return any(
        int(row.units_milli or 0) > 0 or int(row.market_value_rappen or 0) > 0
        for row in _latest_holdings_by_product_for_mandate(db, mandate.id).values()
    )


def ensure_current_depot_check_analysis(
    db: Session, mandate: Mandate, *, as_of, created_by: str, created_at: str, fx_source=None,
) -> tuple[dict, list[tuple[str, str, str]]]:
    """Ein-Klick-PDF: Depot-Snapshot des aktuellen Bestands und Depot-Check dazu
    speichern (beides idempotent: gleicher Inhalt = bestehende Zeile).

    Unvollstaendige Bewertung -> ``ValueError`` mit Grund (kein Snapshot).
    Returns ``(analysis, created)`` mit ``(tabelle, id, hash)`` je neuer Zeile.
    """
    from services.depot_snapshot import build_depot_snapshot, persist_depot_snapshot

    snapshot = build_depot_snapshot(db, mandate, as_of=as_of, fx_source=fx_source)
    snapshot_row, snapshot_created = persist_depot_snapshot(
        db, snapshot, mandate=mandate, created_by=created_by, created_at=created_at,
    )
    analysis = build_depot_check_analysis(db, mandate, snapshot)
    row, created = persist_depot_check_analysis(
        db, analysis, mandate=mandate, created_by=created_by, created_at=created_at,
    )
    new_rows = []
    if snapshot_created:
        new_rows.append(("depot_snapshots", snapshot_row.id, snapshot["snapshot_hash"]))
    if created:
        new_rows.append(("depot_check_analysis_snapshots", row.id, analysis["analysis_hash"]))
    return analysis, new_rows
