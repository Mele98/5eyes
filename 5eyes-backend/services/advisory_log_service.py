"""Sprint U-FINMA-2.1 — Service-Layer fuer AdvisoryLog.

Zentralisiert:
- JSON-Serialisierung der List-Felder (participants, topics, risk_warnings, …)
- Integrity-Hash-Berechnung beim Persist
- retain_until-Berechnung (= entry_datetime + 10 Jahre)
- Versions-Geschichte: Update legt neue Zeile an, alte wird superseded
- Response-Serialisierung (DB-Strings -> Python-Listen)
- Read-Audit (last_read_at / last_read_by)

So bleiben die Router-Endpoints dünn und die FINMA-Logik an einer Stelle
testbar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from database import new_uuid
from models.review import AdvisoryLog
from models.users import User
from services.advisory_log_integrity import (
    compute_integrity_hash,
    compute_retain_until,
    verify_integrity_hash,
)


_LIST_FIELDS = (
    ("participants", "participants_json"),
    ("topics", "topics_json"),
    ("risk_warnings_given", "risk_warnings_given_json"),
    ("conflict_disclosure_ids", "conflict_disclosure_ids_json"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        # Bereits JSON? Pass-through nur wenn parsebar.
        try:
            json.loads(value)
            return value
        except (TypeError, ValueError):
            return json.dumps([value])
    # Pydantic-Model-Liste -> dict-Liste serialisierbar machen
    serialized = []
    for item in value:
        if hasattr(item, "model_dump"):
            serialized.append(item.model_dump())
        else:
            serialized.append(item)
    return json.dumps(serialized, ensure_ascii=False)


def _load_json(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _load_json_object(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def build_hash_payload(entry: AdvisoryLog) -> dict:
    """Snapshot der hash-relevanten Felder für `compute_integrity_hash`."""
    return {
        "mandate_id": entry.mandate_id,
        "advisor_id": entry.advisor_id,
        "entry_type": entry.entry_type,
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": entry.location,
        "title": entry.title,
        "description": entry.description,
        "decision": entry.decision,
        "status": entry.status,
        "participants_json": entry.participants_json,
        "topics_json": entry.topics_json,
        "risk_warnings_given_json": entry.risk_warnings_given_json,
        "cost_disclosure_given": entry.cost_disclosure_given,
        "cost_disclosure_snapshot_json": entry.cost_disclosure_snapshot_json,
        "conflict_disclosure_ids_json": entry.conflict_disclosure_ids_json,
        "suitability_check_id": entry.suitability_check_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "version": entry.version,
    }


ADVISORY_LOG_COST_SNAPSHOT_SCHEMA_VERSION = 2


def _build_cost_disclosure_snapshot(
    db: Session, mandate, *, recommendation_run_id: str | None = None,
) -> str | None:
    """Nachweis der Kostenzahlen, die in dieser Beratung gezeigt wurden.

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): `cost_disclosure_given` war ein
    reines Selbst-Attest-Flag ohne Nachweis, WELCHE Zahlen gezeigt wurden.

    COST-EVIDENCE-001 (CERT-COST-CONFLICT-001, 2026-10-13): die erste
    Fassung dieses Nachweises war zu duenn und an den falschen Lauf
    gebunden. Zwei Maengel, beide behoben:

    1. Sie rief `build_cost_disclosure(db, mandate)` -- den MANDATSWEITEN
       Bauer -- und ignorierte die `recommendation_run_id` des
       Protokolleintrags. Der Eintrag dokumentiert aber ein Gespraech ueber
       EINEN bestimmten Lauf; der Nachweis muss an denselben haengen. Vorher
       konnte das Protokoll die Zahlen eines anderen Laufs festhalten als
       den, auf den es sich beruft.
    2. Sie speicherte sechs reduzierte Summenfelder. Ohne Posten,
       Warnungen und Hash ist das kein nachrechenbarer Nachweis: man sieht
       eine Zahl, aber nicht, woraus sie entstand.

    Jetzt: der vollstaendige Payload, gebunden an die Lauf-ID und ihren
    Status, mit Inhalts-Hash. Liegt der bei der Finalisierung eingefrorene
    Nachweis des Laufs vor (COST-CONTEXT-001b), ist ER die Quelle -- also
    genau die Zahlen, die der Kunde erhalten hat, und nicht eine
    Neuberechnung von heute.

    Fail-soft bleibt: schlaegt die Berechnung fehl (keine Empfehlung,
    kaputtes Gebuehrenmodell), wird kein Snapshot gespeichert und das Flag
    bleibt gueltig -- der Berater hat das Gespraech dokumentiert, auch wenn
    die Engine gerade keine Zahlen liefern konnte. Den Protokolleintrag
    daran scheitern zu lassen waere eine Blockade, die dieser Befund nicht
    verlangt.
    """
    if mandate is None:
        return None
    try:
        from services.cost_disclosure import (
            build_cost_disclosure,
            build_cost_disclosure_for_run,
            cost_disclosure_content_hash,
            load_frozen_cost_disclosure,
        )

        run = None
        if recommendation_run_id:
            from models.review import RecommendationRun
            run = (
                db.query(RecommendationRun)
                .filter(
                    RecommendationRun.id == recommendation_run_id,
                    # An das Mandat gebunden: ein Lauf eines ANDEREN Mandats
                    # darf nicht zum Nachweis dieses Protokolls werden
                    # (gleiche Haertung wie COST-BASIS-001).
                    RecommendationRun.mandate_id == getattr(mandate, "id", None),
                )
                .first()
            )

        if run is not None:
            frozen, _reason = load_frozen_cost_disclosure(run)
            payload = frozen if frozen is not None else build_cost_disclosure_for_run(
                db, mandate, run,
            )
            bound_run_id = str(getattr(run, "id", "") or "")
            bound_status = str(getattr(run, "result_status", "") or "")
        else:
            # Kein (oder kein zugehoeriger) Lauf genannt: wie bisher der
            # mandatsweite Bauer. Die Bindung bleibt dann ausdruecklich
            # leer, statt einen Lauf zu behaupten.
            payload = build_cost_disclosure(db, mandate)
            bound_run_id = str(payload.get("source_run_id") or "") or None
            bound_status = str(payload.get("source_run_status") or "") or None
    except Exception:  # noqa: BLE001 -- siehe Docstring: fail-soft
        return None

    totals = payload.get("totals") or {}
    snapshot = {
        "schema_version": ADVISORY_LOG_COST_SNAPSHOT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "recommendation_run_id": bound_run_id,
        "status": bound_status,
        "currency": payload.get("currency"),
        "advisory_wealth_rappen": payload.get("advisory_wealth_rappen"),
        "invested_amount_rappen": payload.get("invested_amount_rappen"),
        "one_time_rappen": totals.get("one_time_rappen"),
        "annual_rappen": totals.get("annual_rappen"),
        "first_year_rappen": totals.get("first_year_rappen"),
        "totals": totals,
        "cost_items": payload.get("cost_items") or [],
        "warnings": payload.get("warnings") or [],
        "is_complete": payload.get("is_complete"),
        "data_pending": payload.get("data_pending"),
        # Ob der Nachweis aus dem eingefrorenen Snapshot des Laufs stammt --
        # ohne das Feld waere "die Zahlen des Kunden" von "heute neu
        # gerechnet" nicht zu unterscheiden.
        "evidence_frozen": bool(payload.get("evidence_frozen")),
        "source_content_hash": payload.get("content_hash"),
    }
    # Hash ueber den Nachweis selbst, nach demselben Verfahren wie im
    # Kostenausweis. `generated_at` ist Teil des Inhalts: zwei Protokolle
    # ueber dieselben Zahlen sind zwei verschiedene Nachweise.
    snapshot["content_hash"] = cost_disclosure_content_hash(snapshot)
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


def create_advisory_log(
    db: Session,
    *,
    mandate_id: str,
    advisor: User,
    payload,
    mandate=None,
) -> AdvisoryLog:
    """Persist einen neuen AdvisoryLog-Eintrag mit Hash + retain_until.

    `payload` ist eine `AdvisoryLogCreate`-Instanz. `mandate` (optional) wird
    fuer den Kosten-Offenlegungs-Snapshot benoetigt, wenn
    payload.cost_disclosure_given=True -- ohne Mandate-Objekt wird das Flag
    weiterhin gespeichert, aber ohne Zahlen-Snapshot.
    """
    now = _now_iso()
    entry_datetime = payload.entry_datetime
    entry_date = payload.entry_date or entry_datetime[:10]
    cost_disclosure_snapshot_json = (
        _build_cost_disclosure_snapshot(
            db, mandate,
            # COST-EVIDENCE-001: an den Lauf binden, auf den sich DIESER
            # Eintrag beruft -- nicht an den, den der mandatsweite Bauer
            # gerade waehlen wuerde.
            recommendation_run_id=getattr(payload, "recommendation_run_id", None),
        )
        if payload.cost_disclosure_given
        else None
    )

    entry = AdvisoryLog(
        id=new_uuid(),
        mandate_id=mandate_id,
        advisor_id=advisor.id,
        entry_type=payload.entry_type,
        title=payload.title,
        description=payload.description,
        decision=payload.decision,
        trigger_id=payload.trigger_id,
        recommendation_run_id=payload.recommendation_run_id,
        status=payload.status or "Empfohlen",
        client_signed=1 if payload.client_signed else 0,
        client_signed_at=payload.client_signed_at,
        document_id=payload.document_id,
        entry_date=entry_date,
        # FINMA-Erweiterung
        entry_datetime=entry_datetime,
        duration_minutes=payload.duration_minutes,
        communication_channel=payload.communication_channel,
        language=payload.language,
        location=payload.location,
        participants_json=_dump_json(payload.participants),
        topics_json=_dump_json(payload.topics),
        risk_warnings_given_json=_dump_json(payload.risk_warnings_given),
        cost_disclosure_given=1 if payload.cost_disclosure_given else 0,
        cost_disclosure_snapshot_json=cost_disclosure_snapshot_json,
        conflict_disclosure_ids_json=_dump_json(payload.conflict_disclosure_ids),
        suitability_check_id=payload.suitability_check_id,
        retain_until=compute_retain_until(entry_datetime),
        version=1,
        created_at=now,
        updated_at=now,
    )
    entry.integrity_hash = compute_integrity_hash(payload=build_hash_payload(entry))
    db.add(entry)
    return entry


def supersede_advisory_log(
    db: Session,
    *,
    previous: AdvisoryLog,
    advisor: User,
    update,
) -> AdvisoryLog:
    """Erzeugt eine neue Version mit den geänderten Feldern; markiert den
    Vorgänger als superseded. FINMA-Pflicht: keine destructive Updates.

    `update` ist eine `AdvisoryLogUpdate`-Instanz.
    """
    now = _now_iso()

    new = AdvisoryLog(
        id=new_uuid(),
        mandate_id=previous.mandate_id,
        advisor_id=advisor.id,
        entry_type=previous.entry_type,
        title=previous.title,
        description=update.description if update.description is not None else previous.description,
        decision=update.decision if update.decision is not None else previous.decision,
        trigger_id=previous.trigger_id,
        recommendation_run_id=(
            update.recommendation_run_id
            if update.recommendation_run_id is not None
            else previous.recommendation_run_id
        ),
        status=update.status or previous.status,
        client_signed=(
            (1 if update.client_signed else 0)
            if update.client_signed is not None
            else previous.client_signed
        ),
        client_signed_at=(
            update.client_signed_at
            if update.client_signed_at is not None
            else previous.client_signed_at
        ),
        document_id=previous.document_id,
        entry_date=previous.entry_date,
        # FINMA-Felder bleiben weitestgehend aus previous (außer revisierte)
        entry_datetime=previous.entry_datetime,
        duration_minutes=previous.duration_minutes,
        communication_channel=previous.communication_channel,
        language=previous.language,
        location=previous.location,
        participants_json=previous.participants_json,
        topics_json=(
            _dump_json(update.topics) if update.topics is not None else previous.topics_json
        ),
        risk_warnings_given_json=(
            _dump_json(update.risk_warnings_given)
            if update.risk_warnings_given is not None
            else previous.risk_warnings_given_json
        ),
        cost_disclosure_given=previous.cost_disclosure_given,
        cost_disclosure_snapshot_json=previous.cost_disclosure_snapshot_json,
        conflict_disclosure_ids_json=previous.conflict_disclosure_ids_json,
        suitability_check_id=previous.suitability_check_id,
        retain_until=previous.retain_until,
        version=previous.version + 1,
        supersedes_id=previous.id,
        created_at=now,
        updated_at=now,
    )
    new.integrity_hash = compute_integrity_hash(payload=build_hash_payload(new))
    db.add(new)
    db.flush()

    # Vorgänger als superseded markieren
    previous.superseded_by_id = new.id
    previous.updated_at = now

    return new


def mark_read(db: Session, *, entry: AdvisoryLog, reader: User) -> None:
    """FINMA-Pflicht: Access-Tracking bei sensiblen Daten."""
    entry.last_read_at = _now_iso()
    entry.last_read_by = reader.id


# ---------------------------------------------------------------------------
# Sprint U-FINMA-2.2 — Detection + Aggregator-Helpers
# ---------------------------------------------------------------------------

def get_latest_active_entry(
    db: Session, *, mandate_id: str
) -> AdvisoryLog | None:
    """Letzter aktiver (non-superseded) Eintrag eines Mandats nach entry_date.

    Wird vom Aggregator konsumiert um „letzter Termin" anzuzeigen.
    """
    return (
        db.query(AdvisoryLog)
        .filter(
            AdvisoryLog.mandate_id == mandate_id,
            AdvisoryLog.superseded_by_id.is_(None),
            # RISK-PROFILE-SIGNOFF-001: System-Ereignisse (z.B. Portal-
            # Signoff des Risikoprofils) sind kein Beratungstermin.
            AdvisoryLog.system_event.is_(None),
        )
        .order_by(
            AdvisoryLog.entry_datetime.desc().nullslast(),
            AdvisoryLog.entry_date.desc(),
            AdvisoryLog.created_at.desc(),
        )
        .first()
    )


def count_active_entries(db: Session, *, mandate_id: str) -> int:
    """Anzahl aktiver (non-superseded) AdvisoryLog-Köpfe."""
    return (
        db.query(AdvisoryLog)
        .filter(
            AdvisoryLog.mandate_id == mandate_id,
            AdvisoryLog.superseded_by_id.is_(None),
        )
        .count()
    )


def detect_suitability_mismatches(db: Session, mandate) -> list[str]:
    """Liefert eine Liste menschenlesbarer Warnings, wenn die aktuelle
    Empfehlung das Risikoprofil-Budget oder die Toleranzbänder verlässt --
    oder wenn die HouseMatrix-Cap-Pruefung nicht moeglich ist.

    FINMA-relevant: jeder Mismatch sollte im nächsten Beratungsprotokoll
    als gegebener Risikohinweis dokumentiert werden.

    Beispiele:
    - „Risky-Fraction 47 % überschreitet HouseMatrix-Cap 45 % (Defensiv)"
    - „Aktien-Anteil 28 % verlässt Toleranzband 15-25 %"
    - „HouseMatrix-Cap nicht pruefbar (SCORE_BUCKET_MISSING): ..."
    """
    return evaluate_suitability_mismatches(db, mandate)["warnings"]


def evaluate_suitability_mismatches(db: Session, mandate) -> dict:
    """Wie ``detect_suitability_mismatches``, plus strukturierter Status der
    HouseMatrix-Cap-Pruefung (``services.suitability_cap_check``).

    Rueckgabe: ``{"warnings": list[str], "cap_check": SuitabilityCapCheck}``.
    """
    from models.allocation import TargetAllocation
    from models.profiling import RiskAssessment
    from services.suitability_cap_check import (
        evaluate_house_matrix_cap,
        not_applicable,
    )

    warnings: list[str] = []

    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    if ta is None:
        # kein aktiver Allokations-Stand → kein Mismatch erfassbar
        return {"warnings": warnings, "cap_check": not_applicable()}

    ra = (
        db.query(RiskAssessment)
        .filter(
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.is_current == 1,
            RiskAssessment.deleted_at.is_(None),
        )
        .first()
    )

    raw_risky_fraction = getattr(ta, "risky_fraction_bps", None)
    risky_fraction = _safe_int(raw_risky_fraction)
    risk_budget = _safe_int(getattr(ta, "risk_budget_bps_at_generation", 0))
    # Wenn risk_budget verfuegbar → direkter Check (war zum Generate-Zeitpunkt aktiv)
    if risky_fraction and risk_budget and risky_fraction > risk_budget:
        warnings.append(
            f"Risiko-Anteil {risky_fraction / 100:.1f} % überschreitet "
            f"Risikobudget {risk_budget / 100:.1f} % zum Zeitpunkt der "
            "Empfehlungs-Generierung."
        )

    # Plus: vergleich mit aktueller HouseMatrix (kann sich nach Generate geaendert haben)
    # Kontrollrunde 2026-09-20: override-bewusst (score_bucket_from_assessment
    # nutzt bei aktivem Override override_score_x10).
    # SUITABILITY-DETECTOR-SCALE-001 (2026-10-14): 0..100 -> 1..10-Bucket.
    # SUITABILITY-DETECTOR-AVAILABILITY-001 (2026-10-21): fehlende Policy,
    # fehlender/mehrdeutiger Score-Bucket, fehlendes Risikoprofil oder
    # fehlender Risiko-Anteil wurden vorher still uebersprungen (leere Liste
    # = "geeignet", fail-open). Jetzt expliziter Status ``unavailable`` mit
    # Reason-Code und Berater-Hinweis (fail-closed).
    cap_check = evaluate_house_matrix_cap(
        db,
        assessment=ra,
        risky_fraction_bps=(
            None if raw_risky_fraction is None else risky_fraction
        ),
    )
    if cap_check.requires_advisor_attention and cap_check.message:
        warnings.append(cap_check.message)

    # Buckets gegen Bänder pruefen
    for bucket_key in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        target = _safe_int(getattr(ta, f"target_{bucket_key}_bps", 0))
        band_min = _safe_int(getattr(ta, f"band_{bucket_key}_min_bps", 0))
        band_max = _safe_int(getattr(ta, f"band_{bucket_key}_max_bps", 0))
        if target and band_max and band_max > 0:
            if target < band_min or target > band_max:
                bucket_label = bucket_key.replace("_", " ").title()
                warnings.append(
                    f"{bucket_label}-Anteil {target / 100:.1f} % verlässt "
                    f"Toleranzband {band_min / 100:.1f}-{band_max / 100:.1f} %."
                )

    return {"warnings": warnings, "cap_check": cap_check}


def build_auto_log_payload(
    db: Session,
    *,
    mandate,
    advisor: User,
    entry_datetime: str,
    duration_minutes: int = 60,
    communication_channel: str = "schriftlich",
    extra_topics: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict:
    """Pre-filled AdvisoryLogCreate-Payload als dict.

    Berater nutzt das als Vorlage und ergaenzt nur description / Status /
    decision. Hash + retain_until werden vom create_advisory_log berechnet.

    - Topics: aus existierenden AdvisoryLog-Themen + extra_topics
    - Risk-Warnings: aus detect_suitability_mismatches + extra_warnings
    """
    topics_set = set(extra_topics or [])
    topics_set.update([
        "Strategieueberblick", "Risikoprofil", "Asset Allocation",
    ])
    mismatches = detect_suitability_mismatches(db, mandate)
    risk_warnings = list(mismatches)
    if extra_warnings:
        risk_warnings.extend(extra_warnings)
    if not risk_warnings:
        # Mindestens ein generischer Hinweis fuer FIDLEG-Compliance
        risk_warnings = [
            "Allgemeines Marktrisiko: Wertpapiere koennen an Wert verlieren.",
        ]

    return {
        "entry_type": "Jahresreview",
        "title": f"Beratungsprotokoll {entry_datetime[:10]}",
        "description": (
            f"Auto-generiertes Beratungsprotokoll auf Basis des Advisory-"
            f"Reports vom {entry_datetime[:10]}. Bitte vom Berater "
            "individuell ergaenzen / korrigieren (Mindestlaenge 30 Zeichen)."
        ),
        "decision": None,
        "entry_datetime": entry_datetime,
        "duration_minutes": duration_minutes,
        "communication_channel": communication_channel,
        "language": "de",
        "location": None,
        "participants": [],
        "topics": sorted(topics_set),
        "risk_warnings_given": risk_warnings,
        "cost_disclosure_given": False,
        "status": "Empfohlen",
    }


def _safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def verify_entry_integrity(entry: AdvisoryLog) -> bool | None:
    """Prueft den gespeicherten integrity_hash gegen die aktuellen Feldwerte.

    Mega-Audit (2026-08-04): `verify_integrity_hash()` wurde seit U-FINMA-2.1
    berechnet und persistiert, aber NIRGENDS beim Lesen tatsaechlich
    aufgerufen (nur in Tests) -- der Manipulationsschutz existierte nur auf
    dem Papier. Wird jetzt bei jeder Serialisierung mitgeliefert.

    Returns
    -------
    None
        Kein Hash vorhanden (Legacy-Eintrag vor U-FINMA-2.1) -- nichts zu
        verifizieren, KEIN Manipulationsverdacht.
    True/False
        Hash vorhanden und stimmt/stimmt nicht mit dem aktuellen Inhalt
        ueberein.
    """
    if not entry.integrity_hash:
        return None
    return verify_integrity_hash(
        payload=build_hash_payload(entry), expected_hash=entry.integrity_hash,
    )


def serialize_response(entry: AdvisoryLog) -> dict:
    """Wandelt AdvisoryLog-Row in API-Response-Dict (JSON-Felder → Listen)."""
    return {
        "id": entry.id,
        "mandate_id": entry.mandate_id,
        "entry_type": entry.entry_type,
        "title": entry.title,
        "description": entry.description,
        "decision": entry.decision,
        "trigger_id": entry.trigger_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "status": entry.status,
        "advisor_id": entry.advisor_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "document_id": entry.document_id,
        "entry_date": entry.entry_date,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        # FINMA-Erweiterung
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": entry.location,
        "participants": _load_json(entry.participants_json),
        "topics": _load_json(entry.topics_json),
        "risk_warnings_given": _load_json(entry.risk_warnings_given_json),
        "cost_disclosure_given": entry.cost_disclosure_given,
        "cost_disclosure_snapshot": _load_json_object(entry.cost_disclosure_snapshot_json),
        "conflict_disclosure_ids": _load_json(entry.conflict_disclosure_ids_json),
        "suitability_check_id": entry.suitability_check_id,
        "integrity_hash": entry.integrity_hash,
        "integrity_verified": verify_entry_integrity(entry),
        "retain_until": entry.retain_until,
        "version": entry.version,
        "supersedes_id": entry.supersedes_id,
        "superseded_by_id": entry.superseded_by_id,
        "last_read_at": entry.last_read_at,
        "last_read_by": entry.last_read_by,
    }
