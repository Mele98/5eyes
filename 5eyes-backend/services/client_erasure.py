"""Sprint 2026-08-15 (DSG Art. 32 -- Recht auf Loeschung / Erasure).

Gesetzlicher Hintergrund
-------------------------
Das Schweizer Datenschutzgesetz (DSG, in Kraft seit 2023) Art. 32 gibt
einer betroffenen Person das Recht, von jedem Verantwortlichen die
Loeschung ihrer Personendaten zu verlangen. Dieses Recht ist -- wie das
strukturell verwandte "Recht auf Vergessenwerden" der DSGVO (Art. 17) --
NICHT absolut: es steht zurueck, wo eine gesetzliche Aufbewahrungspflicht
entgegensteht. Fuer 5eyes als Vermoegensverwaltungs-/Beratungs-Software
sind das insbesondere:

- FIDLEG Art. 11/12/16/19/21 (Dokumentationspflicht Beratung, Eignungs-
  pruefung, Kostenoffenlegung) -- i.d.R. 10 Jahre.
- GwG Art. 7 (Sorgfaltspflicht-Belege) -- i.d.R. 10 Jahre.
- OR Art. 962 (kaufmaennische Buchfuehrung/Aufbewahrung) -- 10 Jahre.

Die bestehende, bereits vor diesem Sprint gepflegte Aufstellung in
``services/data_export.py::RETENTION_NOTES`` dokumentiert diese Fristen
pro Tabelle und wird hier als Single Source of Truth fuer "was ist
retention-geschuetzt" wiederverwendet (nicht dupliziert).

Design-Entscheidung: Zwei-Stufen-Modell statt Alles-oder-Nichts
-----------------------------------------------------------------
Ein voller Hard-Delete des gesamten Kunden-Fussabdrucks wuerde die oben
genannten 10-Jahres-Pflichten verletzen, solange die Frist laeuft
(genau das ist die "Retention-Abwaegung FIDLEG 10 Jahre vs. OR 962", die
in docs/planning/2026-08-03-launch-readiness-update.md als offener
Punkt gelistet ist). Ein reiner Soft-Delete (nur ``deleted_at`` setzen,
wie der bestehende ``DELETE /clients/{id}``) loescht dagegen faktisch
GAR NICHTS -- das ist im Mega-Audit vom 2026-08-04 explizit als
Compliance-Luecke benannt ("der DELETE-Endpoint taeuscht eine Loeschung
vor, die er nicht ausfuehrt").

Dieser Service waehlt einen dritten Weg, der beide Pflichten so weit wie
technisch moeglich gleichzeitig erfuellt:

TIER A -- irreversible Anonymisierung (JETZT, bei jedem Aufruf):
    Direkt identifizierende Felder (Name, Geburtsdatum, Partnerdaten,
    Adresse, Bankverbindungs-/Depotnummern, freie Notizfelder,
    Signatur-Bildartefakte, Login-E-Mail) werden auf einen fixen
    Redaction-Marker gesetzt. Diese Felder sind selbst NICHT der
    gesetzlich vorgeschriebene "Beleg" (das ist die Beratungsleistung,
    der Entscheid, der Betrag, das Datum) -- sie sind Metadaten UEBER
    die Person, die den Beleg betrifft. Nach dieser Stufe ist die
    natuerliche Person aus den verbleibenden Datensaetzen praktisch
    nicht mehr identifizierbar, obwohl die Datensaetze selbst (Betraege,
    Allokationen, Entscheide, Datum) fuer die Aufbewahrungsfrist
    bestehen bleiben.

TIER B -- unveraendert belassen (bewusst NICHT Teil dieses Services):
    FIDLEG-Pflichtdokumentationen mit eigenem Integritaets-/Versions-
    Vertrag (``advisory_log`` -- Beratungsprotokoll, eigener
    ``integrity_hash`` + ``retain_until``; ``portfolio_handoffs`` --
    laut Docstring "UNVERAENDERLICHER Snapshot"; ``risk_assessments``/
    ``suitability_checks``/``conflict_of_interest_disclosures``/
    ``recommendation_runs``/``target_allocations``/``strategy_snapshots``/
    ``mandate_report_notes``/``mandate_baustein_selections``) werden NICHT
    angefasst. Diese Tabellen sind laut RETENTION_NOTES durchgehend
    10-Jahre-pflichtig und enthalten primaer strukturierte Compliance-
    Entscheide, keine primaeren Identitaetsmerkmale -- die betroffene
    Person bleibt darin nur ueber die (jetzt anonymisierte) client_id/
    mandate_id-Verkettung referenziert, nicht mehr über Klartextnamen.
    Bekannter Restrisiko-Punkt (siehe docs/planning/2026-08-15-dsg-
    art32-erasure-workflow.md): einzelne freie Textfelder in diesen
    Tabellen (z.B. AdvisoryLog.description/participants_json,
    ConflictOfInterestDisclosure.description) KOENNEN Namen enthalten.
    Eine feldweise Redaktion dieser Tabellen wuerde ihre eigenen
    Integritaets-/Versionsvertraege brechen und ist eine Rechtsfrage
    (Aufbewahrungspflicht vs. Loeschungsanspruch), keine rein
    technische -- ausdruecklich zur menschlichen/juristischen
    Pruefung vermerkt, nicht autonom entschieden.

``audit_log`` (Tabelle) wird ebenfalls NICHT angefasst -- und zwar nicht
nur aus Rechtsgruenden, sondern weil es technisch gar nicht geht: die
Tabelle traegt harte SQLite-Trigger (``trg_audit_log_no_update``,
``trg_audit_log_no_delete``, siehe database.py::ensure_audit_log_triggers),
die JEDES UPDATE/DELETE mit ``RAISE(ABORT, 'audit_log is immutable')``
verwerfen. Dieser Trigger war selbst Gegenstand eines kritischen
Bugfixes (2026-08-07 CEO/CFO/CIO-Audit: ging bei jeder Neuinstallation
verloren) -- ihn fuer die Erasure zu umgehen wuerde exakt die
Sicherheits-Eigenschaft aufweichen, die dort gerade repariert wurde.
Die Erasure-Aktion selbst wird stattdessen als GANZ NORMALER, neuer
Audit-Log-Eintrag geschrieben (siehe routers/clients.py::erase_client)
-- foerdert die Nachvollziehbarkeit ("wer hat wann wen aus welchem
Grund geloescht"), statt sie zu untergraben.

Was dieser Service NICHT tut
------------------------------
- Kein Hard-Delete von Zeilen (ausser es gibt in Zukunft einen
  separaten, retention-Ablauf-gesteuerten Purge-Job -- out of scope
  hier, siehe Doku).
- Keine Dateisystem-Bereinigung: ``ContractDocument.pdf_path`` ist ein
  definiertes, aber nirgends beschriebenes Legacy-Feld (PDFs werden
  serverseitig on-demand gerendert und nie auf Platte persistiert,
  siehe routers/pdf_reports.py) -- es gibt keine Binärdatei zu loeschen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


# Fixer, wiedererkennbarer Redaction-Marker -- bewusst ASCII-only (keine
# Mojibake-Risiken in Exporten/Logs, siehe frueherer Test-Fixture-Bugfix).
REDACTION_MARKER = "[ERASED-DSG-ART-32]"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    ).first()
    return row is not None


def _columns(db: Session, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {str(row[1]) for row in db.execute(text(f"PRAGMA table_info({_quote_ident(table)})")).all()}


def _quote_ident(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return '"' + identifier + '"'


def _in_params(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    params = {f"{prefix}_{i}": value for i, value in enumerate(values)}
    return ", ".join(f":{key}" for key in params), params


def _redact(
    db: Session,
    table: str,
    filter_column: str,
    values: list[str],
    *,
    marker_columns: Iterable[str] = (),
    null_columns: Iterable[str] = (),
) -> int:
    """UPDATEs directly-identifying columns to a fixed marker (strings) or
    NULL (numeric/typed columns), scoped to rows matching filter_column IN
    values. Defensive against schema drift (missing table/column -> no-op,
    same pattern as services/foundation_purge.py). Returns affected rowcount.
    """
    if not values:
        return 0
    cols = _columns(db, table)
    if filter_column not in cols:
        return 0
    set_parts: list[str] = []
    params: dict[str, Any] = {}
    for i, col in enumerate(marker_columns):
        if col in cols:
            key = f"marker_{i}"
            set_parts.append(f"{_quote_ident(col)} = :{key}")
            params[key] = REDACTION_MARKER
    for col in null_columns:
        if col in cols:
            set_parts.append(f"{_quote_ident(col)} = NULL")
    if not set_parts:
        return 0
    clause, id_params = _in_params(filter_column, values)
    params.update(id_params)
    sql = (
        f"UPDATE {_quote_ident(table)} SET {', '.join(set_parts)} "
        f"WHERE {_quote_ident(filter_column)} IN ({clause})"
    )
    result = db.execute(text(sql), params)
    return int(result.rowcount or 0)


def erase_client_personal_data(db: Session, client_id: str, *, reason: str) -> dict[str, Any]:
    """Irreversibly anonymizes Tier-A personal-data fields for one client.

    Raises HTTPException(404) if the client does not exist, and
    HTTPException(409) if the client was already DSG-erased (idempotency
    guard -- re-running is harmless but almost always signals a caller bug
    or a duplicate request, so we surface it rather than silently no-op).
    """
    client_row = db.execute(
        text("SELECT id, erased_at FROM clients WHERE id = :id"),
        {"id": client_id},
    ).first()
    if client_row is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    if client_row[1]:
        raise HTTPException(
            status_code=409,
            detail="Kunde wurde bereits nach DSG Art. 32 geloescht (anonymisiert)",
        )

    now = _now()
    mandate_rows = db.execute(
        text("SELECT id FROM mandates WHERE client_id = :client_id"),
        {"client_id": client_id},
    ).all()
    mandate_ids = [str(r[0]) for r in mandate_rows]

    redacted: dict[str, int] = {}

    def _apply(table: str, filter_column: str, values: list[str], **kwargs: Any) -> None:
        n = _redact(db, table, filter_column, values, **kwargs)
        if n:
            redacted[table] = redacted.get(table, 0) + n

    # --- Kernidentitaet des Kunden ---
    _apply(
        "clients", "id", [client_id],
        marker_columns=[
            "salutation", "first_name", "last_name", "date_of_birth", "canton",
            "civil_status", "profession", "employer", "partner_salutation",
            "partner_first_name", "partner_last_name", "partner_date_of_birth",
            "partner_profession", "notes",
        ],
    )
    _apply("client_opt_history", "client_id", [client_id], marker_columns=["notes"])

    # --- Mandat: redundante PII-Kopien + Bankverbindung ---
    if mandate_ids:
        _apply(
            "mandates", "id", mandate_ids,
            marker_columns=["depot_bank", "depot_account_number", "client_sex"],
            null_columns=["client_birth_year"],
        )

    # --- Vermoegen/Cashflow: Adressen, Kontonummern, freie Notizen ---
    _apply(
        "wealth_positions", "client_id", [client_id],
        marker_columns=[
            "property_address", "property_zip_city", "depot_bank",
            "depot_account_number", "mortgage_bank", "notes",
        ],
    )
    _apply("cashflows", "client_id", [client_id], marker_columns=["notes"])
    _apply("wealth_inflows", "client_id", [client_id], marker_columns=["notes"])
    if mandate_ids:
        _apply("goals", "mandate_id", mandate_ids, marker_columns=["notes"])
        _apply("planning_assumptions", "mandate_id", mandate_ids, marker_columns=["notes"])

    # --- Vertragsdokumente: Signatur-Artefakte + gerenderter Inhalt ---
    if mandate_ids:
        _apply(
            "contract_documents", "mandate_id", mandate_ids,
            marker_columns=[
                "title", "content_json", "pdf_path", "checksum_sha256",
                "signature_advisor_image", "signature_advisor_signer_name",
                "signature_advisor_ip",
                "signature_client_image", "signature_client_signer_name",
                "signature_client_ip",
            ],
        )

    # --- Kundenportal-Login (falls vorhanden): eigenes User-Konto des Kunden ---
    login_row = db.execute(
        text("SELECT user_id FROM client_logins WHERE client_id = :client_id"),
        {"client_id": client_id},
    ).first()
    if login_row is not None:
        user_id = str(login_row[0])
        _apply(
            "users", "id", [user_id],
            marker_columns=["full_name", "email"],
            null_columns=[
                "totp_secret", "reset_token_hash", "reset_token_expires_at",
                "invite_token_hash", "invite_expires_at",
            ],
        )
        if "is_active" in _columns(db, "users"):
            db.execute(
                text("UPDATE users SET is_active = 0 WHERE id = :id"),
                {"id": user_id},
            )
        if _table_exists(db, "client_logins"):
            db.execute(
                text("UPDATE client_logins SET is_active = 0 WHERE client_id = :client_id"),
                {"client_id": client_id},
            )
        if _table_exists(db, "refresh_tokens"):
            db.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = :now "
                    "WHERE user_id = :user_id AND revoked_at IS NULL"
                ),
                {"now": now, "user_id": user_id},
            )

    # --- Client-Zeile final markieren (unabhaengig vom gewoehnlichen Soft-Delete) ---
    db.execute(
        text(
            "UPDATE clients SET deleted_at = COALESCE(deleted_at, :now), "
            "erased_at = :now, erasure_reason = :reason, updated_at = :now "
            "WHERE id = :id"
        ),
        {"now": now, "reason": reason, "id": client_id},
    )
    db.flush()

    return {
        "status": "erased",
        "client_id": client_id,
        "mandate_ids": mandate_ids,
        "redacted": redacted,
        "erased_at": now,
    }
