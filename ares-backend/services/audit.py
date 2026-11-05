import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session
from models.review import AuditLog, AuditLogSequenceCounter
from models.users import User
import database
from database import new_uuid

logger = logging.getLogger(__name__)


def _claim_next_audit_sequence(db: Session) -> tuple[int, str]:
    """SEC-003 (Codex-Audit 2026-08-26): atomare Sequenzvergabe fuer die
    Hash-Chain. log() bestimmte den Vorgaenger bisher per
    `ORDER BY created_at DESC, id DESC` OHNE Lock -- zwei nahezu
    gleichzeitige Aufrufe konnten beide denselben "letzten" Eintrag lesen
    und dadurch zwei Zeilen mit identischem previous_hash erzeugen
    (Gabelung statt linearer Kette).

    UPDATE ... SET value = value + 1 auf die Singleton-Zaehlerzeile haelt
    den Schreib-Lock bis zum Commit der AUFRUFENDEN Transaktion (log()
    committet nie selbst) -- SQLite serialisiert damit ueber die ganze
    Datei (PRAGMA busy_timeout=5000 sorgt dafuer, dass ein blockierter
    zweiter Aufrufer wartet statt sofort zu scheitern), PostgreSQL ueber
    den Row-Lock. Konkurrierende log()-Aufrufe werden dadurch echt linear
    serialisiert, nicht nur "meistens" korrekt.

    Die Zaehlerzeile MUSS existieren (siehe database.py::
    ensure_audit_log_sequence_counter(), im Boot-Pfad vor jedem moeglichen
    log()-Aufruf). Existiert sie ausnahmsweise nicht (z.B. Testaufbau ohne
    vollen Boot-Pfad), legt log() sie defensiv selbst an.
    """
    # synchronize_session='fetch' (nicht False!): log() kann mehrfach in
    # derselben Session/Transaktion aufgerufen werden (manche Endpoints
    # loggen mehrere Aktionen pro Request). Ohne 'fetch' bliebe eine bereits
    # in der Identity-Map liegende Counter-Instanz aus dem ERSTEN Aufruf
    # stehen und der ZWEITE Aufruf saehe denselben (veralteten) Wert --
    # exakt das in dieser Session bereits gefundene REC-005-Stale-Fixture-
    # Muster (synchronize_session=False aktualisiert nur die DB-Zeile,
    # nicht bereits geladene Python-Objekte).
    updated_rows = (
        db.query(AuditLogSequenceCounter)
        .filter(AuditLogSequenceCounter.id == "singleton")
        .update({"value": AuditLogSequenceCounter.value + 1}, synchronize_session="fetch")
    )
    if updated_rows == 0:
        # Defensive: Zaehlerzeile fehlt (Test-/Skript-Kontext ohne vollen
        # Boot-Pfad, siehe database.py::ensure_audit_log_sequence_counter()).
        # Ein echter Doppel-Boot-Race auf eine bisher fehlende Zeile ist im
        # regulaeren Betrieb ausgeschlossen (die Zeile existiert vor dem
        # ersten moeglichen Request).
        db.add(AuditLogSequenceCounter(id="singleton", value=1))
        db.flush()
        new_sequence = 1
    else:
        counter = (
            db.query(AuditLogSequenceCounter)
            .filter(AuditLogSequenceCounter.id == "singleton")
            .first()
        )
        new_sequence = int(counter.value)
    if new_sequence <= 1:
        # Erster Eintrag des NEUEN Sequenz-Vertrags (Genesis) -- kein
        # numerischer Vorgaenger. Altdaten (sequence IS NULL) werden bewusst
        # nicht rueckwirkend verkettet, siehe models.review.AuditLog.sequence.
        return new_sequence, ""
    previous_entry = _pending_audit_entry(db, new_sequence - 1)
    if previous_entry is None:
        previous_entry = (
            db.query(AuditLog)
            .filter(AuditLog.sequence == new_sequence - 1)
            .first()
        )
    previous_hash = str(previous_entry.integrity_hash or "") if previous_entry else ""
    return new_sequence, previous_hash


def _pending_audit_entry(db: Session, sequence: int) -> AuditLog | None:
    """N-862-1 (Pruefrunde #862): Vorgaenger aus den PENDING-Objekten der
    eigenen Session.

    Die Sessions laufen mit autoflush=False (database.SessionLocal). Ein in
    derselben Transaktion zuvor per log() angelegter, noch nicht geflushter
    Eintrag liegt nur in ``db.new`` -- die DB-Abfrage nach ``sequence - 1``
    findet ihn nicht, previous_hash wurde "" und verify_audit_chain meldete
    "Kette gebrochen" fuer JEDE Transaktion mit zwei oder mehr Eintraegen
    (z.B. Risikoprofil + Plausibilitaets-Befund, FX-Upsert mehrerer
    Waehrungen, Ziel-Reihenfolge).

    Bewusst KEIN db.flush() an dieser Stelle: log() wuerde sonst ALLE
    ausstehenden Objekte des Aufrufers vorzeitig schreiben. Ein Aufrufer
    darf ein Objekt nach db.add() noch vervollstaendigen; bei append-only-
    Tabellen (Unveraenderlichkeits-Trigger auf UPDATE) machte ein
    vorgezogener Flush daraus ein UPDATE, das der Trigger abweist, und
    Constraint-Fehler kaemen an einer Stelle, die der Aufrufer nicht
    abfaengt. Die Sequenz selbst ist davon
    unberuehrt: der Zaehler-UPDATE laeuft sofort gegen die DB und haelt den
    Schreib-Lock bis zum Commit (siehe _claim_next_audit_sequence).

    Ein Rollback (auch eines Savepoints) entfernt die pending Eintraege UND
    setzt den Zaehler zurueck -- beides bleibt konsistent.
    """
    for obj in db.new:
        if isinstance(obj, AuditLog) and obj.sequence == sequence:
            return obj
    return None


def _audit_integrity_payload(
    *,
    entry_id: str,
    user_id: str | None,
    user_name: str | None,
    table_name: str | None,
    record_id: str | None,
    action: str | None,
    field_name: str | None,
    old_value: str | None,
    new_value: str | None,
    mandate_id: str | None,
    client_id: str | None,
    created_at: str,
    previous_hash: str,
    ip_address: str | None = None,
    tenant_id: str | None = None,
) -> str:
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): ip_address wird ANS ENDE
    # angehaengt, nicht dazwischen eingefuegt -- so bleibt der Hash
    # historischer Eintraege (vor diesem Fix, ohne ip_address) unberuehrt;
    # nur NEUE Eintraege erhalten das erweiterte Format. Der Hash-Chain-
    # Mechanismus verkettet ueber previous_hash (ein reiner Hex-String),
    # nicht ueber ein festes Payload-Format, daher ist ein gemischter
    # Verlauf (alte + neue Formatversion) unproblematisch.
    # Roadmap #21 (2026-08-08): tenant_id wird -- wie schon ip_address (siehe
    # Kommentar oben) -- ANS ENDE angehaengt, damit der Hash historischer
    # Eintraege (vor dieser Migration, ohne tenant_id) unveraendert bleibt.
    #
    # Kontrollrunde 2026-09-24: der Delimiter war bisher ein einfaches '|'
    # -- ein normales, in Freitextfeldern (old_value/new_value/user_name,
    # z.B. DSG-Loeschgruende in routers/clients.py) plausibles Zeichen. Da
    # der Join nicht injektiv ist, konnten zwei UNTERSCHIEDLICHE Werte-Saetze
    # denselben Payload-String (und damit denselben Hash) erzeugen, sobald
    # ein '|' auf einer Feldgrenze landet (verifiziert: old_value='A|B',
    # new_value='C' hasht identisch zu old_value='A', new_value='B|C') --
    # das unterlaeuft die Manipulationserkennung genau fuer den Fall, den
    # die Hash-Chain eigentlich abdecken soll. services/advisory_log_
    # integrity.py hatte dieses Problem bereits korrekt geloest ('\x1f',
    # Unit-Separator -- praktisch nie in echten Textfeldern).
    #
    # ANDERS als bei advisory_log (REC-007-Migration, siehe database.py::
    # migrate_advisory_log_hash_scheme_cost_disclosure_snapshot) kann
    # audit_log NICHT rueckwirkend umgehasht werden: trg_audit_log_no_update
    # (database.py::ensure_audit_log_triggers) blockiert JEDES UPDATE auf
    # bestehenden Zeilen hart auf DB-Ebene -- genau die Massnahme, die
    # nachtraegliche Hash-Manipulation verhindern soll, verhindert hier auch
    # eine legitime Migration. Der Fix gilt daher nur fuer NEUE Zeilen ab
    # jetzt; verify_audit_chain() akzeptiert fuer Bestandszeilen weiterhin
    # zusaetzlich das alte '|'-Schema (siehe _audit_integrity_payload_
    # legacy_pipe_delimiter unten), damit deren Verifikation nicht durch
    # diesen Fix selbst als "manipuliert" gemeldet wird.
    return "\x1f".join(
        [
            str(entry_id or ""),
            str(user_id or ""),
            str(user_name or ""),
            str(table_name or ""),
            str(record_id or ""),
            str(action or ""),
            str(field_name or ""),
            str(old_value if old_value is not None else ""),
            str(new_value if new_value is not None else ""),
            str(mandate_id or ""),
            str(client_id or ""),
            str(created_at),
            str(previous_hash or ""),
            str(ip_address or ""),
            str(tenant_id or ""),
        ]
    )


def _audit_integrity_payload_legacy_pipe_delimiter(
    *,
    entry_id: str,
    user_id: str | None,
    user_name: str | None,
    table_name: str | None,
    record_id: str | None,
    action: str | None,
    field_name: str | None,
    old_value: str | None,
    new_value: str | None,
    mandate_id: str | None,
    client_id: str | None,
    created_at: str,
    previous_hash: str,
    ip_address: str | None = None,
    tenant_id: str | None = None,
) -> str:
    """Frozen copy of the pre-2026-09-24 '|'-delimited payload, kept ONLY
    so verify_audit_chain() can still verify rows written before the
    delimiter fix (see _audit_integrity_payload's docstring -- audit_log's
    immutability trigger makes retroactive rehashing impossible). Never
    used for new writes; do not change."""
    return "|".join(
        [
            str(entry_id or ""),
            str(user_id or ""),
            str(user_name or ""),
            str(table_name or ""),
            str(record_id or ""),
            str(action or ""),
            str(field_name or ""),
            str(old_value if old_value is not None else ""),
            str(new_value if new_value is not None else ""),
            str(mandate_id or ""),
            str(client_id or ""),
            str(created_at),
            str(previous_hash or ""),
            str(ip_address or ""),
            str(tenant_id or ""),
        ]
    )


def log(
    db: Session,
    *,
    user_id: str,
    user_name: str,
    table_name: str,
    record_id: str,
    action: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    mandate_id: str | None = None,
    client_id: str | None = None,
    ip_address: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Write an immutable audit log entry. Call after every mutating operation.

    Roadmap #21 (2026-08-08): tenant_id wird, wenn nicht explizit uebergeben,
    aus user_id hergeleitet (Lookup gegen users.tenant_id). Callers muessen
    dafuer NICHT angepasst werden -- user_id ist an jedem bestehenden
    Call-Site bereits ein Pflichtparameter. Bleibt None fuer Aktionen ohne
    echten users-Eintrag (z.B. Client-Portal-Logins) -- unveraendert zum
    bisherigen Verhalten, keine Regression.
    """
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    sequence, previous_hash = _claim_next_audit_sequence(db)
    entry_id = new_uuid()
    stored_old_value = str(old_value) if old_value is not None else None
    stored_new_value = str(new_value) if new_value is not None else None
    stored_ip_address = str(ip_address) if ip_address else None
    resolved_tenant_id = tenant_id
    if resolved_tenant_id is None:
        actor = db.query(User).filter(User.id == user_id).first()
        resolved_tenant_id = getattr(actor, "tenant_id", None) if actor is not None else None
    stored_tenant_id = str(resolved_tenant_id) if resolved_tenant_id else None
    payload = _audit_integrity_payload(
        entry_id=entry_id,
        user_id=user_id,
        user_name=user_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        field_name=field_name,
        old_value=stored_old_value,
        new_value=stored_new_value,
        mandate_id=mandate_id,
        client_id=client_id,
        created_at=created_at,
        previous_hash=previous_hash,
        ip_address=stored_ip_address,
        tenant_id=stored_tenant_id,
    )
    integrity_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    entry = AuditLog(
        id=entry_id,
        user_id=user_id,
        user_name=user_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        field_name=field_name,
        old_value=stored_old_value,
        new_value=stored_new_value,
        mandate_id=mandate_id,
        client_id=client_id,
        integrity_hash=integrity_hash,
        ip_address=stored_ip_address,
        tenant_id=stored_tenant_id,
        created_at=created_at,
        sequence=sequence,
        previous_hash=previous_hash,
    )
    db.add(entry)
    # Note: caller must db.commit() — we don't commit here


# H-865-2 (Pruefrunde #865): Obergrenze fuer aufgelistete Fundstellen je
# Kategorie im Pruefbericht. Die ANZAHL wird immer vollstaendig gemeldet; nur
# die Liste der Sequenznummern/IDs wird gekappt, damit ein massiv
# beschaedigter Bestand keinen riesigen Response erzeugt.
AUDIT_REPORT_MAX_LISTED = 100
# Leichte Startpruefung: oberhalb dieser Zeilenzahl wird sie uebersprungen
# (Hinweis im Log, Pruefung dann ueber den Admin-Endpoint). Die Pruefung ist
# O(n) und laedt alle Zeilen; bei ~1000 Zeilen dauert sie Millisekunden.
AUDIT_STARTUP_CHECK_MAX_ROWS = 200_000
# Altzeilen (vor SEC-003, ohne sequence) speichern ihren previous_hash nicht.
# log() las den Vorgaenger damals per ORDER BY created_at DESC, id DESC ohne
# Lock -- bei nahezu gleichzeitigen Aufrufen konnte das ein frueherer Eintrag
# als der unmittelbare Vorgaenger sein (SEC-003-Gabelung). Darum werden neben
# dem unmittelbaren Vorgaenger noch so viele fruehere Zeilen als Kandidat
# geprueft.
_LEGACY_PREDECESSOR_WINDOW = 5


def _row_hash_matches(row: AuditLog, previous_hash: str) -> bool:
    """Neuberechnung nach aktuellem Schema, Fallback auf das '|'-Schema
    (Kontrollrunde 2026-09-24: Zeilen aus der Zeit vor dem Delimiter-Fix
    koennen wegen trg_audit_log_no_update nicht umgehasht werden)."""
    common = dict(
        entry_id=row.id,
        user_id=row.user_id,
        user_name=row.user_name,
        table_name=row.table_name,
        record_id=row.record_id,
        action=row.action,
        field_name=row.field_name,
        old_value=row.old_value,
        new_value=row.new_value,
        mandate_id=row.mandate_id,
        client_id=row.client_id,
        created_at=row.created_at,
        previous_hash=previous_hash,
        ip_address=row.ip_address,
        tenant_id=row.tenant_id,
    )
    for builder in (_audit_integrity_payload, _audit_integrity_payload_legacy_pipe_delimiter):
        if hashlib.sha256(builder(**common).encode("utf-8")).hexdigest() == row.integrity_hash:
            return True
    return False


def _legacy_payload_variants(row: AuditLog, previous_hash: str) -> list[str]:
    """Alle Payload-Formate, mit denen eine Altzeile (sequence IS NULL)
    gehasht worden sein kann -- jeweils eingefroren aus der Git-Historie von
    log(). Nicht aendern.

    - 13 Felder, '|' (erste gehashte Fassung, bis CEO/CFO/CIO-Audit 2026-08-07)
    - 14 Felder, '|' (+ ip_address, bis Roadmap #21 2026-08-08)
    - 15 Felder, '|' (+ tenant_id, bis Delimiter-Fix 2026-09-24)
    - 15 Felder, Unit-Separator (heutiges Schema, der Vollstaendigkeit halber)
    """
    base = [
        str(row.id or ""),
        str(row.user_id or ""),
        str(row.user_name or ""),
        str(row.table_name or ""),
        str(row.record_id or ""),
        str(row.action or ""),
        str(row.field_name or ""),
        str(row.old_value if row.old_value is not None else ""),
        str(row.new_value if row.new_value is not None else ""),
        str(row.mandate_id or ""),
        str(row.client_id or ""),
        str(row.created_at),
        str(previous_hash or ""),
    ]
    ip = str(row.ip_address or "")
    tenant = str(row.tenant_id or "")
    return [
        "|".join(base),
        "|".join(base + [ip]),
        "|".join(base + [ip, tenant]),
        "\x1f".join(base + [ip, tenant]),
    ]


def _legacy_row_matches(row: AuditLog, previous_hash: str) -> bool:
    return any(
        hashlib.sha256(variant.encode("utf-8")).hexdigest() == row.integrity_hash
        for variant in _legacy_payload_variants(row, previous_hash)
    )


def _capped(values: list) -> list:
    return values[:AUDIT_REPORT_MAX_LISTED]


def verify_audit_chain(db: Session) -> dict:
    """SEC-003: oeffentlicher Vertrag {'ok', 'checked', 'errors'} --
    unveraendert, damit bestehende Aufrufer/Tests stabil bleiben. Die
    strukturierten Fundstellen (H-865-2) liefert _verify_audit_chain_detail().
    """
    detail = _verify_audit_chain_detail(db)
    return {"ok": detail["ok"], "checked": detail["checked"], "errors": detail["errors"]}


def _verify_audit_chain_detail(db: Session) -> dict:
    """SEC-003 (Codex-Audit 2026-08-26): Runtime-Verifier fuer die seit dieser
    Migration gefuehrte Sequenz-Kette. Prueft ausschliesslich Zeilen mit
    sequence IS NOT NULL (Altdaten vor der Migration beanspruchen keine
    lineare Ketten-Garantie, siehe models.review.AuditLog.sequence; deren
    Pruefung pro Zeile: verify_audit_legacy_rows()).

    Prueft pro Zeile:
    - Sequenz ist lueckenlos 1..N (kein uebersprungener/doppelter Wert).
    - previous_hash der Zeile == integrity_hash der Zeile mit sequence-1
      (bzw. "" fuer die Genesis-Zeile sequence=1).
    - integrity_hash der Zeile ist konsistent mit einer Neuberechnung aus
      den gespeicherten Feldern (erkennt nachtraegliche Manipulation trotz
      Umgehung der DB-Trigger, z.B. direkter Dateizugriff).
    - H-865-2: der Sequenzzaehler steht nicht hoeher als die letzte
      vorhandene Zeile -- sonst fehlen Eintraege am ENDE der Kette (die
      Pruefung zwischen Zeilen allein erkennt ein abgeschnittenes Ende
      nicht). Zaehler und Eintrag entstehen in derselben Transaktion (log()
      committet nie selbst, ein Rollback setzt beides zurueck).

    Gibt {'ok', 'checked', 'errors', 'breaks', 'gaps', 'duplicates',
    'hash_mismatches', 'counter_value', 'last_sequence'} zurueck -- wirft
    nicht. Die strukturierten Felder enthalten nur Sequenznummern, keine
    Inhalte (Admin-Endpoint, H-865-2); 'errors' bleibt als lesbare Liste
    fuer Logs und Tests.
    """
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.sequence.isnot(None))
        .order_by(AuditLog.sequence.asc())
        .all()
    )
    errors: list[str] = []
    breaks: list[int] = []
    gaps: list[dict] = []
    duplicates: list[int] = []
    hash_mismatches: list[int] = []
    expected_sequence = 1
    previous_row: AuditLog | None = None
    for row in rows:
        if row.sequence != expected_sequence:
            errors.append(
                f"Sequenzluecke/-duplikat: erwartet {expected_sequence}, gefunden {row.sequence} (id={row.id})"
            )
            if row.sequence > expected_sequence:
                gaps.append({"from_sequence": expected_sequence, "to_sequence": int(row.sequence) - 1})
            else:
                duplicates.append(int(row.sequence))
            expected_sequence = row.sequence
        expected_previous_hash = (
            str(previous_row.integrity_hash or "") if previous_row is not None else ""
        )
        if (row.previous_hash or "") != expected_previous_hash:
            errors.append(
                f"Kette gebrochen bei sequence={row.sequence} (id={row.id}): "
                f"previous_hash stimmt nicht mit dem Vorgaenger-Hash ueberein"
            )
            breaks.append(int(row.sequence))
        if not _row_hash_matches(row, row.previous_hash or ""):
            errors.append(
                f"integrity_hash stimmt nicht mit Neuberechnung ueberein bei sequence={row.sequence} (id={row.id})"
            )
            hash_mismatches.append(int(row.sequence))
        expected_sequence += 1
        previous_row = row

    last_sequence = int(rows[-1].sequence) if rows else 0
    counter = (
        db.query(AuditLogSequenceCounter)
        .filter(AuditLogSequenceCounter.id == "singleton")
        .first()
    )
    counter_value = int(counter.value) if counter is not None and counter.value is not None else None
    if counter_value is not None and counter_value > last_sequence:
        errors.append(
            f"Kettenende fehlt: Sequenzzaehler steht bei {counter_value}, letzte Zeile hat sequence={last_sequence}"
        )
        gaps.append({"from_sequence": last_sequence + 1, "to_sequence": counter_value})
    return {
        "ok": len(errors) == 0,
        "checked": len(rows),
        "errors": errors,
        "breaks": breaks,
        "gaps": gaps,
        "duplicates": duplicates,
        "hash_mismatches": hash_mismatches,
        "counter_value": counter_value,
        "last_sequence": last_sequence,
    }


def verify_audit_legacy_rows(db: Session) -> dict:
    """H-865-2 (Pruefrunde #865): Pruefung pro Zeile fuer Altzeilen ohne
    sequence. verify_audit_chain() schliesst sie aus; fuer den Modell-
    kommentar ("Altdaten bleiben ueber integrity_hash weiterhin
    manipulationssicher pro Zeile") gab es bisher keinen Pruefer.

    Altzeilen speichern ihren previous_hash nicht (die Spalte kam erst mit
    SEC-003). Rekonstruiert wird er so, wie log() ihn damals bestimmte: als
    integrity_hash der zeitlich vorangehenden Zeile (created_at, id).
    Ergebnis je gehashter Altzeile:

    - verified: Hash passt mit dem unmittelbaren Vorgaenger (Inhalt UND
      Verkettung bestaetigt).
    - link_unconfirmed: Hash passt nur mit einem frueheren Vorgaenger
      (Fenster _LEGACY_PREDECESSOR_WINDOW) oder mit leerem Vorgaenger. Der
      Inhalt ist bestaetigt, die Verkettung nicht -- typische Ursache ist
      die SEC-003-Gabelung (zwei gleichzeitige Schreiber lasen denselben
      Vorgaenger). Hinweis, kein Integritaetsfehler.
    - mismatch: Hash passt mit keinem Kandidaten -> Inhalt veraendert ODER
      der unmittelbare Vorgaenger wurde entfernt (dessen Hash steckt in der
      Payload und ist dann nicht mehr verfuegbar). Beides ist ein
      Integritaetsfehler.

    Zeilen ohne integrity_hash (vor Einfuehrung des Hashes sowie BACKFILL-
    Zeilen vor N-865-2) werden nur gezaehlt; sie sind nicht pruefbar.
    """
    rows = db.query(AuditLog).filter(AuditLog.sequence.is_(None)).all()
    rows.sort(key=lambda r: (str(r.created_at or ""), str(r.id or "")))
    unhashed = 0
    verified = 0
    link_unconfirmed_ids: list[str] = []
    mismatch_ids: list[str] = []
    for index, row in enumerate(rows):
        if not row.integrity_hash:
            unhashed += 1
            continue
        direct_previous = str(rows[index - 1].integrity_hash or "") if index > 0 else ""
        if _legacy_row_matches(row, direct_previous):
            verified += 1
            continue
        candidates = [""] + [
            str(rows[j].integrity_hash or "")
            for j in range(max(0, index - 1 - _LEGACY_PREDECESSOR_WINDOW), index - 1)
        ]
        if any(_legacy_row_matches(row, candidate) for candidate in candidates):
            link_unconfirmed_ids.append(str(row.id))
        else:
            mismatch_ids.append(str(row.id))
    return {
        "ok": not mismatch_ids,
        "total": len(rows),
        "hashed": len(rows) - unhashed,
        "unhashed": unhashed,
        "verified": verified,
        "link_unconfirmed": len(link_unconfirmed_ids),
        "link_unconfirmed_ids": _capped(link_unconfirmed_ids),
        "mismatches": len(mismatch_ids),
        "mismatch_ids": _capped(mismatch_ids),
    }


def audit_log_integrity_report(db: Session) -> dict:
    """H-865-2: Gesamtbericht fuer Admin-Endpoint und Startpruefung.

    Liefert nur Zaehler, Sequenznummern und Zeilen-IDs, keine Inhalte
    (Namen, Werte, IPs). Es gibt EINE globale Kette ueber alle Tenants
    (Singleton-Zaehler); tenant_id steckt nur in der Hash-Payload.
    """
    chain = _verify_audit_chain_detail(db)
    legacy = verify_audit_legacy_rows(db)
    return {
        "ok": bool(chain["ok"] and legacy["ok"]),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": {
            "ok": chain["ok"],
            "checked": chain["checked"],
            "last_sequence": chain["last_sequence"],
            "counter_value": chain["counter_value"],
            "break_count": len(chain["breaks"]),
            "breaks": _capped(chain["breaks"]),
            "gap_count": len(chain["gaps"]),
            "gaps": _capped(chain["gaps"]),
            "duplicate_count": len(chain["duplicates"]),
            "duplicates": _capped(chain["duplicates"]),
            "hash_mismatch_count": len(chain["hash_mismatches"]),
            "hash_mismatches": _capped(chain["hash_mismatches"]),
        },
        "legacy": legacy,
    }


def run_startup_audit_chain_check(
    session_factory: Callable[[], Session] | None = None,
    *,
    max_rows: int = AUDIT_STARTUP_CHECK_MAX_ROWS,
) -> dict | None:
    """H-865-2: leichte Startpruefung. Blockiert den Start NIE.

    Begruendung (Verfuegbarkeit): Ein Bruch der Kette ist ein Befund ueber
    die Vergangenheit. Ein Startabbruch repariert ihn nicht (die Zeilen sind
    unveraenderlich), wuerde aber die laufende Beratung und auch den Zugriff
    fuer die Aufarbeitung blockieren. Deshalb: CRITICAL ins Log bei
    verletzter Integritaet, WARNING bei nicht bestaetigter Verkettung von
    Altzeilen oder wenn die Pruefung selbst scheitert. Der Start laeuft
    weiter, die Details liefert GET /admin/system/audit-log/verify.
    """
    factory = session_factory or database.SessionLocal
    try:
        with factory() as db:
            total = int(db.query(func.count(AuditLog.id)).scalar() or 0)
            if total > max_rows:
                logger.warning(
                    "Audit-Kettenpruefung beim Start uebersprungen: %s Eintraege > Grenze %s "
                    "(Pruefung ueber GET /admin/system/audit-log/verify)",
                    total, max_rows,
                )
                return None
            report = audit_log_integrity_report(db)
    except Exception as exc:  # noqa: BLE001 -- die Startpruefung darf den Boot nie stoppen
        logger.warning("Audit-Kettenpruefung beim Start nicht durchfuehrbar: %s", type(exc).__name__)
        return None
    chain = report["chain"]
    legacy = report["legacy"]
    if not report["ok"]:
        logger.critical(
            "AUDIT-LOG-INTEGRITAET VERLETZT: Kette ok=%s (geprueft=%s, Brueche=%s, Luecken=%s, "
            "Duplikate=%s, Hash-Abweichungen=%s); Altzeilen ok=%s (Hash-Abweichungen=%s). "
            "Details: GET /admin/system/audit-log/verify",
            chain["ok"], chain["checked"], chain["break_count"], chain["gap_count"],
            chain["duplicate_count"], chain["hash_mismatch_count"],
            legacy["ok"], legacy["mismatches"],
        )
    elif legacy["link_unconfirmed"]:
        logger.warning(
            "Audit-Log-Kette ok (%s Eintraege); %s Altzeilen nur inhaltlich bestaetigt, "
            "Verkettung nicht rekonstruierbar",
            chain["checked"], legacy["link_unconfirmed"],
        )
    else:
        logger.info(
            "Audit-Log-Kette ok: %s verkettete Eintraege, %s von %s gehashten Altzeilen bestaetigt",
            chain["checked"], legacy["verified"], legacy["hashed"],
        )
    return report
