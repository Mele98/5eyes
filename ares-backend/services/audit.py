import hashlib
import hmac
import json
import logging
import threading
from datetime import datetime, timezone
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session
from models.review import AuditChainVerificationStatus, AuditLog, AuditLogSequenceCounter
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
        return 1, ""
    # N-869-4: Spalten direkt aus der DB lesen (kein Entity-Load): eine in
    # der Identity-Map liegende Zaehler-Instanz koennte bei
    # expire_on_commit=False einen veralteten last_hash tragen.
    counter_value, counter_last_hash = db.execute(
        select(AuditLogSequenceCounter.value, AuditLogSequenceCounter.last_hash)
        .where(AuditLogSequenceCounter.id == "singleton")
    ).one()
    new_sequence = int(counter_value)
    if new_sequence <= 1:
        # Erster Eintrag des NEUEN Sequenz-Vertrags (Genesis) -- kein
        # numerischer Vorgaenger. Altdaten (sequence IS NULL) werden bewusst
        # nicht rueckwirkend verkettet, siehe models.review.AuditLog.sequence.
        return new_sequence, ""
    if counter_last_hash is not None:
        # N-869-4 (Pruefrunde #869): Vorgaenger-Hash von der Zaehlerzeile --
        # keine Lese-Abfrage auf audit_log. Unter PostgreSQL-RLS war der
        # Vorgaenger eines anderen Tenants (oder ohne tenant_id) unsichtbar,
        # previous_hash wurde '' und die Kette brach bei jedem Tenant-
        # Wechsel. Der Row-Lock aus dem UPDATE oben haelt value und
        # last_hash bis zum Commit konsistent.
        return new_sequence, str(counter_last_hash)
    # Bestand ohne last_hash (Zaehlerzeile vor N-869-4 und noch nicht per
    # ensure_runtime_columns/Alembic c8a2f4e6b0d9 nachgetragen): einmalig
    # wie bisher ueber pending objects bzw. audit_log. Ab dem naechsten
    # Eintrag fuehrt log() last_hash selbst.
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
    # N-869-4: Hash dieses Eintrags auf der Zaehlerzeile fortschreiben -- in
    # derselben Transaktion und unter demselben Row-Lock wie value. Der
    # naechste log() (auch in dieser Transaktion, auch eines anderen
    # Tenants) liest seinen Vorgaenger dort statt aus audit_log.
    db.query(AuditLogSequenceCounter).filter(AuditLogSequenceCounter.id == "singleton").update(
        {"last_hash": integrity_hash}, synchronize_session="fetch"
    )
    # Note: caller must db.commit() — we don't commit here


# H-865-2 (Pruefrunde #865): Obergrenze fuer aufgelistete Fundstellen je
# Kategorie im Pruefbericht. Die ANZAHL wird immer vollstaendig gemeldet; nur
# die Liste der Sequenznummern/IDs wird gekappt, damit ein massiv
# beschaedigter Bestand keinen riesigen Response erzeugt.
AUDIT_REPORT_MAX_LISTED = 100
# Grenze der SYNCHRONEN Startpruefung (Default von settings.
# audit_startup_check_max_rows). F6: darueber wird nicht mehr uebersprungen,
# sondern chunked im Hintergrund geprueft; das Siegel entsteht immer vorher.
AUDIT_STARTUP_CHECK_MAX_ROWS = 200_000
# Altzeilen (vor SEC-003, ohne sequence) speichern ihren previous_hash nicht.
# log() las den Vorgaenger damals per ORDER BY created_at DESC, id DESC ohne
# Lock -- bei nahezu gleichzeitigen Aufrufen konnte das ein frueherer Eintrag
# als der unmittelbare Vorgaenger sein (SEC-003-Gabelung). Darum werden neben
# dem unmittelbaren Vorgaenger noch so viele fruehere Zeilen als Kandidat
# geprueft.
_LEGACY_PREDECESSOR_WINDOW = 5


_MATCH = "match"
_AMBIGUOUS = "ambiguous"
_FIELD_SHIFT = "field_shift"
_PIPE_FIELD_COUNTS = {"pipe13": 13, "pipe14": 14, "pipe15": 15}

# N-869-2 (Pruefrunde #869): Fruehester created_at, ab dem ein Payload-Format
# ueberhaupt geschrieben worden sein kann (Autorendatum des einfuehrenden
# Commits minus einen Tag Sicherheitsabstand, UTC). Nur eine UNTERgrenze:
# alter Code kann nach einem Formatwechsel noch weiterlaufen (App nicht
# aktualisiert), ein neues Format aber nie vor seiner Einfuehrung entstehen.
_LEGACY_FORMAT_SINCE = {
    "pipe13": "2026-05-05T00:00:00",  # df3473b1 (erste gehashte Fassung)
    "pipe14": "2026-08-06T00:00:00",  # 09442a5d (+ ip_address)
    "pipe15": "2026-08-07T00:00:00",  # 3f1f68de (+ tenant_id)
    "us15": "2026-09-23T00:00:00",    # 8818bc19 (Unit-Separator)
}
# Bekannte Alt-BACKFILL-Zeilen ohne Hash (routers/system.py vor N-865-2,
# created_at per datetime.utcnow().isoformat() OHNE 'Z'). Nur diese Zeilen
# duerfen nach der ersten gehashten Zeile ohne Hash vorkommen.
_LEGACY_UNHASHED_BACKFILL_TABLES = frozenset({"asset_class_annual_returns", "asset_class_price_history"})


def _payload_fields(row: AuditLog, previous_hash: str) -> list[str]:
    return [
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


def _legacy_payload_variants(row: AuditLog, previous_hash: str) -> list[str]:
    """Alle Payload-Formate, mit denen eine Zeile gehasht worden sein kann --
    jeweils eingefroren aus der Git-Historie von log(). Nicht aendern.

    - 13 Felder, '|' (erste gehashte Fassung, bis CEO/CFO/CIO-Audit 2026-08-07)
    - 14 Felder, '|' (+ ip_address, bis Roadmap #21 2026-08-08)
    - 15 Felder, '|' (+ tenant_id, bis Delimiter-Fix 2026-09-24)
    - 15 Felder, Unit-Separator (heutiges Schema)
    """
    base = _payload_fields(row, previous_hash)
    ip = str(row.ip_address or "")
    tenant = str(row.tenant_id or "")
    return [
        "|".join(base),
        "|".join(base + [ip]),
        "|".join(base + [ip, tenant]),
        "\x1f".join(base + [ip, tenant]),
    ]


def _hash_status(row: AuditLog, previous_hash: str, *, formats: tuple[str, ...]) -> str | None:
    """N-869-2 (Pruefrunde #869): Neuberechnung ueber die zulaessigen Formate.

    Der '|'-Join ist nicht injektiv. Bisher galt eine Zeile als bestaetigt,
    sobald IRGENDEINE Variante passte -- eine 15-Felder-Zeile passte so auch
    zur 14-Felder-Variante, wenn ip_address='ip|tenant' und tenant_id=NULL
    gesetzt wurde (Tenant-Zuordnung entfernt, Pruefer meldete "verified").
    Eine Variante zaehlt jetzt nur, wenn
    1. die Felder, die das Format nicht kennt, leer sind (13: ip_address und
       tenant_id; 14: tenant_id),
    2. created_at nicht vor der Einfuehrung des Formats liegt, und
    3. bei '|'-Formaten kein Feldwert das Trennzeichen enthaelt.

    N-869-6 (Delta-Pruefung #869): Passt der Hash nur ueber ein '|'-Format
    mit '|' im Feldwert, folgt eine Gegenprobe ueber die Feldgrenzen: der
    gehashte Text wird an jedem '|' getrennt. Ergibt das genau die Feldzahl
    eines fuer created_at zulaessigen '|'-Formats, gibt es eine saubere
    Lesart des Textes ohne '|' in den Werten -- die gespeicherten Felder
    weichen davon ab, die Feldgrenzen wurden verschoben (z.B. tenant_id in
    ip_address geschoben): 'field_shift', Befund. Sonst stand das '|'
    schon beim Schreiben im Wert (echte Altzeile, etwa ein Loeschgrund):
    'ambiguous', nur Hinweis (WARNING) -- die Feldgrenzen sind nicht
    beweisbar, aber nichts deutet auf eine Verschiebung.

    Rueckgabe: 'match', 'field_shift', 'ambiguous' oder None (passt nicht).
    """
    base = _payload_fields(row, previous_hash)
    ip = str(row.ip_address or "")
    tenant = str(row.tenant_id or "")
    created_at = str(row.created_at or "")
    candidates = {
        "pipe13": ("|", base, not ip and not tenant),
        "pipe14": ("|", base + [ip], not tenant),
        "pipe15": ("|", base + [ip, tenant], True),
        "us15": ("\x1f", base + [ip, tenant], True),
    }
    clean_counts = {
        count for name, count in _PIPE_FIELD_COUNTS.items()
        if name in formats and created_at >= _LEGACY_FORMAT_SINCE[name]
    }
    ambiguous = False
    for name in formats:
        delimiter, fields, unknown_fields_empty = candidates[name]
        if not unknown_fields_empty or created_at < _LEGACY_FORMAT_SINCE[name]:
            continue
        joined = delimiter.join(fields)
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        if digest != row.integrity_hash:
            continue
        if delimiter == "|" and any("|" in value for value in fields):
            if len(joined.split("|")) in clean_counts:
                return _FIELD_SHIFT
            ambiguous = True
            continue
        return _MATCH
    return _AMBIGUOUS if ambiguous else None


def _chain_row_status(row: AuditLog, previous_hash: str) -> str | None:
    """Ketten-Zeile: aktuelles Schema, Fallback auf das 15-Felder-'|'-Schema
    (Kontrollrunde 2026-09-24: Zeilen aus der Zeit vor dem Delimiter-Fix
    koennen wegen trg_audit_log_no_update nicht umgehasht werden). Mit '|'
    im Feldwert: Gegenprobe ueber die Feldgrenzen wie bei den Altzeilen
    (N-869-2/N-869-6)."""
    return _hash_status(row, previous_hash, formats=("us15", "pipe15"))


def _row_hash_matches(row: AuditLog, previous_hash: str) -> bool:
    return _chain_row_status(row, previous_hash) in (_MATCH, _AMBIGUOUS)


_LEGACY_UNHASHED_PROTOCOL_TABLES = frozenset({"protocol_bausteine", "mandate_baustein_selections"})
# routers/protocol_bausteine.py schrieb bis zur Kontrollrunde 2026-09-24 ohne
# Hash (Fix 8818bc19/13ff5c74); danach entstehen dort keine solchen Zeilen.
_LEGACY_UNHASHED_PROTOCOL_UNTIL = "2026-09-25T00:00:00"


def _is_known_unhashed_legacy_writer(row: AuditLog) -> bool:
    """Zeilen ohne Hash aus den zwei bekannten Schreibern an log() vorbei
    (git-Historie: nur routers/system.py BACKFILL und routers/
    protocol_bausteine.py). Grenze: eine gefaelschte Zeile, die genau dieses
    Muster nachahmt, ist ohne Hash nicht von einer echten unterscheidbar."""
    created_at = str(row.created_at or "")
    if row.action == "BACKFILL" and row.table_name in _LEGACY_UNHASHED_BACKFILL_TABLES:
        return not created_at.endswith("Z")
    if row.table_name in _LEGACY_UNHASHED_PROTOCOL_TABLES:
        return created_at < _LEGACY_UNHASHED_PROTOCOL_UNTIL
    return False


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
    # N-880-03: Zaehler VOR dem Scan lesen (Snapshot des Ziel-Kopfs). Ein
    # waehrend des Scans committeter Eintrag liegt dann hinter dem Zielkopf
    # und wird mitgeprueft; frueher las der Pfad den Zaehler erst danach und
    # meldete in diesem Fenster faelschlich "Kettenende fehlt". Das
    # Kettenende wird ueber watch_sequence am Zaehlerstand geprueft (gleiches
    # Muster wie die Hintergrundpruefung).
    counter_value, counter_last_hash = _read_counter(db)
    scan = _ChainScan(watch_sequence=counter_value)
    for row in _iter_chain_rows(db):
        scan.feed(row)
    return scan.finish(counter_value, counter_last_hash)


# F6: Teilschrittgroesse beim Streamen der Kette (Keyset ueber sequence, id).
# Haelt den Speicher auch bei grossen Bestaenden klein; das Ergebnis ist
# identisch zum frueheren .all().
_CHAIN_SCAN_BATCH = 2_000


def _chain_rows_after(db: Session, after: tuple[int, str] | None, limit: int) -> list[AuditLog]:
    """Naechster Teilschritt der Kette nach (sequence, id), sortiert nach
    sequence, id. Keyset statt OFFSET: stabil, auch wenn waehrend der Pruefung
    neue Eintraege angehaengt werden; doppelte sequence-Werte (Befund) gehen
    nicht verloren."""
    query = db.query(AuditLog).filter(AuditLog.sequence.isnot(None))
    if after is not None:
        after_sequence, after_id = after
        query = query.filter(
            or_(
                AuditLog.sequence > after_sequence,
                and_(AuditLog.sequence == after_sequence, AuditLog.id > after_id),
            )
        )
    return query.order_by(AuditLog.sequence.asc(), AuditLog.id.asc()).limit(int(limit)).all()


def _iter_chain_rows(db: Session, batch: int = _CHAIN_SCAN_BATCH):
    after: tuple[int, str] | None = None
    while True:
        rows = _chain_rows_after(db, after, batch)
        if not rows:
            return
        yield from rows
        after = (int(rows[-1].sequence), str(rows[-1].id))


class _ChainScan:
    """Pruefung der Sequenz-Kette Zeile fuer Zeile (H-865-2, Regeln siehe
    _verify_audit_chain_detail). Zustand ueber Teilschritte hinweg, damit die
    synchrone Startpruefung und die chunked Hintergrundpruefung (F6) dieselbe
    Logik nutzen.

    ``watch_sequence``: Hash der Zeile mit dieser sequence festhalten (die
    Hintergrundpruefung liest den Zaehler VOR dem Durchlauf; haengen
    waehrenddessen neue Eintraege an, wird das Kettenende am Zaehlerstand
    geprueft, nicht an der letzten gelesenen Zeile).
    """

    def __init__(self, watch_sequence: int | None = None) -> None:
        self.errors: list[str] = []
        self.breaks: list[int] = []
        self.gaps: list[dict] = []
        self.duplicates: list[int] = []
        self.hash_mismatches: list[int] = []
        self.ambiguous: list[int] = []
        self.expected_sequence = 1
        self.previous_hash: str | None = None
        self.checked = 0
        self.last_sequence = 0
        self.last_hash: str | None = None
        self.watch_sequence = watch_sequence
        self.watched_hash: str | None = None

    def feed(self, row: AuditLog) -> None:
        if row.sequence != self.expected_sequence:
            self.errors.append(
                f"Sequenzluecke/-duplikat: erwartet {self.expected_sequence}, gefunden {row.sequence} (id={row.id})"
            )
            if row.sequence > self.expected_sequence:
                self.gaps.append({"from_sequence": self.expected_sequence, "to_sequence": int(row.sequence) - 1})
            else:
                self.duplicates.append(int(row.sequence))
            self.expected_sequence = row.sequence
        expected_previous_hash = self.previous_hash if self.previous_hash is not None else ""
        if (row.previous_hash or "") != expected_previous_hash:
            self.errors.append(
                f"Kette gebrochen bei sequence={row.sequence} (id={row.id}): "
                f"previous_hash stimmt nicht mit dem Vorgaenger-Hash ueberein"
            )
            self.breaks.append(int(row.sequence))
        row_status = _chain_row_status(row, row.previous_hash or "")
        if row_status == _AMBIGUOUS:
            # N-869-6: '|' im Feldwert einer '|'-Zeile, Gegenprobe ohne
            # Hinweis auf Verschiebung -> Hinweis, kein Fehler.
            self.ambiguous.append(int(row.sequence))
        elif row_status != _MATCH:
            self.errors.append(
                f"integrity_hash stimmt nicht mit Neuberechnung ueberein bei sequence={row.sequence} (id={row.id})"
            )
            self.hash_mismatches.append(int(row.sequence))
        self.expected_sequence += 1
        self.previous_hash = str(row.integrity_hash or "")
        self.checked += 1
        self.last_sequence = int(row.sequence)
        self.last_hash = row.integrity_hash
        if self.watch_sequence is not None and int(row.sequence) == int(self.watch_sequence):
            self.watched_hash = row.integrity_hash

    def finish(self, counter_value: int | None, counter_last_hash: str | None) -> dict:
        errors = list(self.errors)
        breaks = list(self.breaks)
        gaps = list(self.gaps)
        last_sequence = self.last_sequence
        if counter_value is not None and counter_value > last_sequence:
            errors.append(
                f"Kettenende fehlt: Sequenzzaehler steht bei {counter_value}, letzte Zeile hat sequence={last_sequence}"
            )
            gaps.append({"from_sequence": last_sequence + 1, "to_sequence": counter_value})
        elif self.checked and counter_last_hash is not None and counter_value is not None:
            if counter_value == last_sequence:
                head_hash = self.last_hash
            elif self.watch_sequence is not None and counter_value == int(self.watch_sequence):
                head_hash = self.watched_hash
            else:
                head_hash = counter_last_hash
            if counter_last_hash != head_hash:
                # N-869-4: der auf der Zaehlerzeile gefuehrte Hash muss zum
                # Eintrag mit sequence = Zaehlerstand passen -- sonst wurde
                # das Kettenende ersetzt.
                errors.append(
                    f"Kettenende passt nicht zum Sequenzzaehler: last_hash weicht vom Hash bei sequence={counter_value} ab"
                )
                breaks.append(int(counter_value))
        return {
            "ok": len(errors) == 0,
            "checked": self.checked,
            "errors": errors,
            "breaks": breaks,
            "gaps": gaps,
            "duplicates": list(self.duplicates),
            "hash_mismatches": list(self.hash_mismatches),
            "ambiguous": list(self.ambiguous),
            "counter_value": counter_value,
            "last_sequence": last_sequence,
        }


# ---------------------------------------------------------------------------
# Bestandssiegel (Delta-Pruefung #869, Entscheid Claude/Owner-Vertretung)
# ---------------------------------------------------------------------------
# Altzeilen ohne Hash (Live: 761, Maerz bis 9. August, Folge des frueheren
# Neuaufbau-Fehlers) lassen sich nachtraeglich nicht faelschungssicher
# machen -- ihr HEUTIGER Stand schon: ein einmaliger, verketteter Eintrag
# haelt Anzahl, ID-Bereich, Zeitraum und einen sha256 ueber die kanonisch
# serialisierten Altzeilen fest. Ab dann meldet der Verifier jede Aenderung,
# Loeschung oder Einfuegung im Altbestand.
#
# Bewusst ein Merkmal (field_name='LEGACY_SEAL') auf action='CREATE' und
# kein neuer action-Wert: ein neuer Wert im SQLite-CHECK erzwaenge den
# Tabellen-Neuaufbau auf jeder Installation (genau der Pfad aus H-865-1/
# N-869-1) und eine CHECK-Aenderung unter PostgreSQL.
#
# Versiegelt werden ALLE Altzeilen (sequence IS NULL), nicht nur die ohne
# Hash: das deckt die ungehashten ab und schliesst zusaetzlich die Luecke
# "letzte Altzeile geloescht" (#869, Abschnitt 4). Seit dem Ketten-Pflicht-
# Trigger (N-869-3) kann keine neue Zeile ohne sequence entstehen, der
# versiegelte Bestand ist also abgeschlossen.
LEGACY_SEAL_MARKER = "LEGACY_SEAL"
LEGACY_SEAL_SCHEME = "legacy-seal-v1"
_LEGACY_SEAL_TABLE = "audit_log"
_LEGACY_SEAL_RECORD = "legacy-seal"
_LEGACY_SEAL_COLUMNS = (
    "id", "user_id", "user_name", "table_name", "record_id", "action",
    "field_name", "old_value", "new_value", "mandate_id", "client_id",
    "integrity_hash", "ip_address", "created_at", "tenant_id", "sequence",
    "previous_hash",
)


def _legacy_seal_digest(db: Session) -> dict:
    """Kanonischer Stand des Altbestands: Zeilen nach id sortiert (in Python,
    unabhaengig von der DB-Collation), je Zeile ein JSON-Array der Spalten
    in fester Reihenfolge, zeilenweise in einen sha256 eingespeist."""
    rows = db.query(AuditLog).filter(AuditLog.sequence.is_(None)).all()
    rows.sort(key=lambda r: str(r.id))
    digest = hashlib.sha256()
    for row in rows:
        values = [getattr(row, column) for column in _LEGACY_SEAL_COLUMNS]
        digest.update(
            json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
    created = sorted(str(r.created_at or "") for r in rows)
    return {
        "scheme": LEGACY_SEAL_SCHEME,
        "count": len(rows),
        "unhashed": sum(1 for r in rows if not r.integrity_hash),
        "id_min": str(rows[0].id) if rows else None,
        "id_max": str(rows[-1].id) if rows else None,
        "created_at_min": created[0] if created else None,
        "created_at_max": created[-1] if created else None,
        "sha256": digest.hexdigest(),
    }


def _legacy_seals(db: Session) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.table_name == _LEGACY_SEAL_TABLE,
            AuditLog.field_name == LEGACY_SEAL_MARKER,
            AuditLog.sequence.isnot(None),
        )
        .order_by(AuditLog.sequence.asc())
        .all()
    )


def ensure_legacy_seal(db: Session) -> dict | None:
    """Schreibt genau einmal den Bestandssiegel-Eintrag, wenn Altzeilen
    (sequence IS NULL) existieren und noch kein Siegel vorhanden ist. Idempotent; der
    Aufrufer committet. Rueckgabe: der versiegelte Stand oder None."""
    if _legacy_seals(db):
        return None
    # N-869-9 (Delta 2 #869): zwei gleichzeitige Starts durften beide "kein
    # Siegel" sehen und je eines schreiben. Jetzt: die Zaehlerzeile sperren
    # -- dieselbe Sperre, die log() bis zum Commit des Aufrufers haelt -- und
    # unter der Sperre erneut pruefen. Der zweite Start wartet, sieht danach
    # (neues Statement: SQLite haelt nach einem SELECT keinen Lese-Snapshot,
    # PG READ COMMITTED) das committete Siegel und schreibt keins. Bewusst
    # KEIN Rollback davor: unter PG naehme er den Operator-Bypass (set_config
    # in derselben Transaktion) mit zurueck. Zweite Verteidigungslinie: der
    # partielle Unique-Index ux_audit_log_legacy_seal (SQLite:
    # database.py::ensure_audit_log_indexes, PG: Alembic d3b7f1a5c9e2).
    db.query(AuditLogSequenceCounter).filter(AuditLogSequenceCounter.id == "singleton").update(
        {"value": AuditLogSequenceCounter.value}, synchronize_session=False
    )
    if _legacy_seals(db):
        return None
    # N-869-8 (Delta 2 #869): versiegelt wird, sobald Altzeilen existieren --
    # auch wenn alle einen Hash tragen (Schutz gegen Loeschen der letzten
    # Altzeile und gegen eingefuegte Zeilen gilt fuer den ganzen Altbestand).
    has_legacy = (
        db.query(AuditLog.id).filter(AuditLog.sequence.is_(None)).first() is not None
    )
    if not has_legacy:
        return None
    sealed = _legacy_seal_digest(db)
    log(
        db,
        user_id="system",
        user_name="System (Bestandssiegel)",
        table_name=_LEGACY_SEAL_TABLE,
        record_id=_LEGACY_SEAL_RECORD,
        action="CREATE",
        field_name=LEGACY_SEAL_MARKER,
        new_value=json.dumps(sealed, sort_keys=True, separators=(",", ":")),
        tenant_id=None,
    )
    return sealed


def _verify_legacy_seal(db: Session) -> dict:
    """Prueft jeden vorhandenen Siegel-Eintrag gegen den heutigen Altbestand.
    Abweichung = Befund. Ohne Siegel: seal_ok None (nichts zu pruefen)."""
    seals = _legacy_seals(db)
    if not seals:
        # N-869-8: Altzeilen ohne Siegel -> Hinweis seal_missing (kein Befund;
        # die naechste Startpruefung schreibt das Siegel).
        has_legacy = db.query(AuditLog.id).filter(AuditLog.sequence.is_(None)).first() is not None
        return {
            "seal_present": False, "seal_ok": None, "seal_sequence": None, "seal_count": None,
            "seal_missing": has_legacy,
        }
    current = _legacy_seal_digest(db)
    ok = True
    first: dict | None = None
    for seal in seals:
        try:
            sealed = json.loads(seal.new_value or "")
        except ValueError:
            ok = False
            continue
        if first is None:
            first = sealed
        if sealed.get("scheme") != LEGACY_SEAL_SCHEME or any(
            sealed.get(key) != current[key] for key in current
        ):
            ok = False
    return {
        "seal_present": True,
        "seal_ok": ok,
        "seal_sequence": int(seals[0].sequence),
        "seal_count": int(first["count"]) if first and isinstance(first.get("count"), int) else None,
        "seal_missing": False,
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
      (Fenster _LEGACY_PREDECESSOR_WINDOW) oder mit leerem Vorgaenger --
      typisch fuer die SEC-003-Gabelung. Hinweis, kein Integritaetsfehler.
    - field_shift (N-869-6): Hash passt nur ueber ein '|'-Format mit '|' im
      Feldwert, und die Gegenprobe ueber die Feldgrenzen findet eine saubere
      Lesart mit anderen Feldwerten (z.B. Tenant-Zuordnung per
      Feldverschiebung entfernt). Befund.
    - ambiguous (N-869-2/N-869-6): wie oben, aber ohne saubere Lesart -- das
      '|' stand schon beim Schreiben im Wert. Hinweis (WARNING), kein
      Befund.
    - mismatch: Hash passt mit keinem zulaessigen Format/Kandidaten ->
      Inhalt veraendert ODER der unmittelbare Vorgaenger wurde entfernt.
      Befund.

    Zeilen ohne integrity_hash: vor der ersten gehashten Zeile (Zeit vor dem
    Hash) und aus den zwei bekannten Alt-Schreibern an log() vorbei
    (_is_known_unhashed_legacy_writer) werden nur gezaehlt. Jede andere
    Zeile ohne Hash NACH der ersten gehashten Zeile ist ein Befund
    (unexpected_unhashed, N-869-2): eine eingefuegte Fremdzeile darf nicht
    als blosser Hinweis durchgehen.
    """
    rows = db.query(AuditLog).filter(AuditLog.sequence.is_(None)).all()
    rows.sort(key=lambda r: (str(r.created_at or ""), str(r.id or "")))
    formats = ("pipe13", "pipe14", "pipe15", "us15")
    unhashed = 0
    verified = 0
    seen_hashed = False
    link_unconfirmed_ids: list[str] = []
    ambiguous_ids: list[str] = []
    mismatch_ids: list[str] = []
    field_shift_ids: list[str] = []
    unexpected_unhashed_ids: list[str] = []
    for index, row in enumerate(rows):
        if not row.integrity_hash:
            unhashed += 1
            if seen_hashed and not _is_known_unhashed_legacy_writer(row):
                unexpected_unhashed_ids.append(str(row.id))
            continue
        seen_hashed = True
        direct_previous = str(rows[index - 1].integrity_hash or "") if index > 0 else ""
        status = _hash_status(row, direct_previous, formats=formats)
        if status == _MATCH:
            verified += 1
            continue
        if status == _FIELD_SHIFT:
            field_shift_ids.append(str(row.id))
            continue
        if status == _AMBIGUOUS:
            ambiguous_ids.append(str(row.id))
            continue
        candidates = [""] + [
            str(rows[j].integrity_hash or "")
            for j in range(max(0, index - 1 - _LEGACY_PREDECESSOR_WINDOW), index - 1)
        ]
        statuses = {status} | {_hash_status(row, c, formats=formats) for c in candidates}
        if _MATCH in statuses:
            link_unconfirmed_ids.append(str(row.id))
        elif _FIELD_SHIFT in statuses:
            field_shift_ids.append(str(row.id))
        elif _AMBIGUOUS in statuses:
            ambiguous_ids.append(str(row.id))
        else:
            mismatch_ids.append(str(row.id))
    seal = _verify_legacy_seal(db)
    return {
        # N-869-6: ambiguous ist nur ein Hinweis; Befunde sind mismatch,
        # field_shift, unexpected_unhashed und ein nicht mehr passendes
        # Bestandssiegel.
        "ok": not (mismatch_ids or field_shift_ids or unexpected_unhashed_ids) and seal["seal_ok"] is not False,
        "total": len(rows),
        "hashed": len(rows) - unhashed,
        "unhashed": unhashed,
        "verified": verified,
        "link_unconfirmed": len(link_unconfirmed_ids),
        "link_unconfirmed_ids": _capped(link_unconfirmed_ids),
        "mismatches": len(mismatch_ids),
        "mismatch_ids": _capped(mismatch_ids),
        "ambiguous": len(ambiguous_ids),
        "ambiguous_ids": _capped(ambiguous_ids),
        "field_shift": len(field_shift_ids),
        "field_shift_ids": _capped(field_shift_ids),
        "unexpected_unhashed": len(unexpected_unhashed_ids),
        "unexpected_unhashed_ids": _capped(unexpected_unhashed_ids),
        **seal,
    }


def audit_log_integrity_report(db: Session) -> dict:
    """H-865-2: Gesamtbericht fuer Admin-Endpoint und Startpruefung.

    Liefert nur Zaehler, Sequenznummern und Zeilen-IDs, keine Inhalte
    (Namen, Werte, IPs). Es gibt EINE globale Kette ueber alle Tenants
    (Singleton-Zaehler); tenant_id steckt nur in der Hash-Payload.
    """
    chain = _verify_audit_chain_detail(db)
    legacy = verify_audit_legacy_rows(db)
    return _report_from_parts(chain, legacy)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report_from_parts(chain: dict, legacy: dict) -> dict:
    return {
        "ok": bool(chain["ok"] and legacy["ok"]),
        "checked_at": _utc_now(),
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
            "ambiguous_count": len(chain["ambiguous"]),
            "ambiguous": _capped(chain["ambiguous"]),
        },
        "legacy": legacy,
    }


# ---------------------------------------------------------------------------
# F6 (Codex-Entscheid Runde 3, 2026-11-07): Startgrenze nur fuer die SYNCHRONE
# Vollpruefung. Siegel immer vor dem Return; darueber Vollpruefung chunked im
# Hintergrund mit persistiertem, sichtbarem Status.
# ---------------------------------------------------------------------------
AUDIT_VERIFICATION_STATES = ("pending", "running", "ok", "broken", "error")
_STATUS_ID = "singleton"


def _finding_counts(report: dict) -> dict:
    chain = report["chain"]
    legacy = report["legacy"]
    return {
        "break_count": int(chain["break_count"]),
        "gap_count": int(chain["gap_count"]),
        "duplicate_count": int(chain["duplicate_count"]),
        "hash_mismatch_count": int(chain["hash_mismatch_count"]),
        "legacy_mismatches": int(legacy["mismatches"]),
        "legacy_field_shift": int(legacy["field_shift"]),
        "legacy_unexpected_unhashed": int(legacy["unexpected_unhashed"]),
        "legacy_seal_ok": legacy["seal_ok"],
    }


def _finding_total(counts: dict) -> int:
    total = sum(
        int(counts[key]) for key in (
            "break_count", "gap_count", "duplicate_count", "hash_mismatch_count",
            "legacy_mismatches", "legacy_field_shift", "legacy_unexpected_unhashed",
        )
    )
    return total + (1 if counts.get("legacy_seal_ok") is False else 0)


def _write_verification_status(factory: Callable[[], Session], **fields) -> bool:
    """Persistiert den Pruefstatus (Singleton). Best effort: ein Fehler hier
    darf weder Start noch Pruefung stoppen; er wird geloggt, der Befund bleibt
    ueber das Log (CRITICAL) sichtbar."""
    try:
        with factory() as db:
            status = db.get(AuditChainVerificationStatus, _STATUS_ID)
            if status is None:
                status = AuditChainVerificationStatus(id=_STATUS_ID, state="pending", mode="sync")
                db.add(status)
            for key, value in fields.items():
                if key == "detail":
                    status.detail_json = json.dumps(value, sort_keys=True, separators=(",", ":"))
                else:
                    setattr(status, key, value)
            status.updated_at = _utc_now()
            db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 -- Status ist Anzeige, kein Startkriterium
        logger.warning("Audit-Pruefstatus nicht gespeichert: %s", type(exc).__name__)
        return False


def get_audit_verification_status(db: Session) -> dict:
    """Sichtbarer Integritaetsstatus (F6). ``integrity_confirmed`` ist nur bei
    state='ok' wahr -- solange die Hintergrundpruefung aussteht, laeuft oder
    gescheitert ist, gilt die Integritaet als NICHT bestaetigt (fail-closed in
    der Anzeige). Ohne gespeicherten Status: state='unknown'. Nur Zaehler,
    Sequenznummern, Ketten-Hash und Zeitpunkte, keine Inhalte."""
    status = db.get(AuditChainVerificationStatus, _STATUS_ID)
    if status is None:
        return {
            "state": "unknown", "mode": None, "integrity_confirmed": False,
            "total_rows": None, "threshold": None, "target_sequence": None,
            "verified_through_sequence": None, "checked": None, "finding_count": None,
            "findings": None, "last_ok_sequence": None, "last_ok_hash": None, "last_ok_at": None,
            "started_at": None, "updated_at": None, "finished_at": None, "error": None,
        }
    try:
        detail = json.loads(status.detail_json) if status.detail_json else {}
    except ValueError:
        detail = {}
    return {
        "state": status.state,
        "mode": status.mode,
        "integrity_confirmed": status.state == "ok",
        "total_rows": status.total_rows,
        "threshold": status.threshold,
        "target_sequence": status.target_sequence,
        "verified_through_sequence": status.verified_through_sequence,
        "checked": status.checked,
        "finding_count": status.finding_count,
        "findings": detail.get("findings"),
        "last_ok_sequence": status.last_ok_sequence,
        "last_ok_hash": status.last_ok_hash,
        "last_ok_at": status.last_ok_at,
        "started_at": status.started_at,
        "updated_at": status.updated_at,
        "finished_at": status.finished_at,
        "error": detail.get("error"),
    }


def _record_final_status(
    factory: Callable[[], Session], report: dict, *, mode: str, head_hash: str | None
) -> None:
    counts = _finding_counts(report)
    finished = _utc_now()
    fields = {
        "state": "ok" if report["ok"] else "broken",
        "mode": mode,
        "checked": int(report["chain"]["checked"]),
        "verified_through_sequence": int(report["chain"]["last_sequence"]),
        "finding_count": _finding_total(counts),
        "finished_at": finished,
        "detail": {"findings": counts},
    }
    if report["ok"]:
        fields.update(
            last_ok_sequence=int(report["chain"]["last_sequence"]),
            last_ok_hash=head_hash,
            last_ok_at=finished,
        )
    _write_verification_status(factory, **fields)


def _log_report(report: dict) -> None:
    chain = report["chain"]
    legacy = report["legacy"]
    if not report["ok"]:
        logger.critical(
            "AUDIT-LOG-INTEGRITAET VERLETZT: Kette ok=%s (geprueft=%s, Brueche=%s, Luecken=%s, "
            "Duplikate=%s, Hash-Abweichungen=%s); Altzeilen ok=%s (Hash-Abweichungen=%s, "
            "Feldverschiebung=%s, unerwartet ohne Hash=%s, Bestandssiegel ok=%s). "
            "Details: GET /admin/system/audit-log/verify",
            chain["ok"], chain["checked"], chain["break_count"], chain["gap_count"],
            chain["duplicate_count"], chain["hash_mismatch_count"],
            legacy["ok"], legacy["mismatches"], legacy["field_shift"], legacy["unexpected_unhashed"],
            legacy["seal_ok"],
        )
    elif (
        legacy["link_unconfirmed"] or legacy["ambiguous"] or chain["ambiguous_count"]
        or legacy["seal_missing"]
    ):
        # N-869-6: '|' im Wert ohne Hinweis auf Verschiebung ist nur ein
        # Hinweis -- eine echte Altzeile darf nicht bei jedem Start CRITICAL
        # ausloesen.
        logger.warning(
            "Audit-Log-Kette ok (%s Eintraege); Hinweise: %s Altzeilen nur inhaltlich bestaetigt "
            "(Verkettung nicht rekonstruierbar), %s Altzeilen und %s Ketten-Zeilen mit '|' im "
            "Feldwert (Feldgrenzen nicht beweisbar, keine Verschiebung erkennbar); "
            "Altzeilen ohne Bestandssiegel: %s",
            chain["checked"], legacy["link_unconfirmed"], legacy["ambiguous"], chain["ambiguous_count"],
            legacy["seal_missing"],
        )
    else:
        logger.info(
            "Audit-Log-Kette ok: %s verkettete Eintraege, %s von %s gehashten Altzeilen bestaetigt",
            chain["checked"], legacy["verified"], legacy["hashed"],
        )


def _write_seal_if_needed(factory: Callable[[], Session], scope) -> None:
    """Bestandssiegel: genau einmal, verkettet. Eigene Session: ein Rollback
    hier wuerde unter PostgreSQL auch den Operator-Bypass (set_config in
    derselben Transaktion) zuruecknehmen. Ein Fehler stoppt weder Start noch
    Pruefung.

    F6: Das Siegel setzt KEINE vorherige Vollpruefung voraus. Es haelt den
    heutigen Stand des abgeschlossenen Altbestands (sequence IS NULL) fest
    und wird ueber log() an den Zaehler-Kopf (last_hash) gehaengt -- beides
    ohne Lesen der Kette. Ob Altzeilen VOR dem Siegel veraendert wurden,
    beantwortet unabhaengig davon die Pruefung pro Altzeile; ob die Kette
    intakt ist, die Kettenpruefung (synchron oder im Hintergrund). Schon der
    synchrone Pfad siegelt vor der Pruefung. Ein Aufschub bis nach der
    Vollpruefung oeffnete dagegen genau das Fenster, in dem Aenderungen am
    Altbestand unerkannt blieben.
    """
    try:
        with factory() as db, scope(db):
            sealed = ensure_legacy_seal(db)
            if sealed is not None:
                db.commit()
        if sealed is not None:
            logger.info(
                "Bestandssiegel fuer %s Altzeilen geschrieben (davon %s ohne Hash)",
                sealed["count"], sealed["unhashed"],
            )
    except Exception as exc:  # noqa: BLE001 -- Siegel darf den Boot nie stoppen
        logger.warning("Bestandssiegel nicht geschrieben: %s", type(exc).__name__)


def _start_daemon_thread(job: Callable[[], object]) -> None:
    threading.Thread(target=job, name="ares-audit-chain-verify", daemon=True).start()


def _read_counter(db: Session) -> tuple[int | None, str | None]:
    counter = db.execute(
        select(AuditLogSequenceCounter.value, AuditLogSequenceCounter.last_hash)
        .where(AuditLogSequenceCounter.id == "singleton")
    ).first()
    value = int(counter[0]) if counter is not None and counter[0] is not None else None
    return value, (counter[1] if counter is not None else None)


def run_chunked_audit_verification(
    session_factory: Callable[[], Session] | None = None,
    *,
    read_scope: Callable[[Session], AbstractContextManager] | None = None,
    chunk_size: int | None = None,
) -> dict | None:
    """F6: Vollpruefung der Audit-Kette in Teilschritten (Hintergrund).

    Jeder Teilschritt laeuft in einer eigenen kurzen Session (keine lange
    Lesetransaktion, Speicher begrenzt). Nach jedem Teilschritt werden
    Fortschritt (verified_through_sequence, checked) und die Zahl bisheriger
    Befunde persistiert. Der Zaehlerstand wird VOR dem Durchlauf gelesen
    (Ziel-Kopf); waehrenddessen angehaengte Eintraege werden mitgeprueft.

    Ergebnis wie der synchrone Pfad: CRITICAL bei Befund und Status 'broken'
    mit Befundzahl; sonst Status 'ok' mit dem letzten erfolgreich geprueften
    Kopf. Wirft nie; ein Fehler ergibt Status 'error' (Integritaet bleibt
    unbestaetigt) und eine WARNING.
    """
    factory = session_factory or database.SessionLocal
    size = int(chunk_size or database.settings.audit_verify_chunk_size)

    def _scope(db):
        return read_scope(db) if read_scope is not None else nullcontext()

    try:
        with factory() as db, _scope(db):
            counter_value, counter_last_hash = _read_counter(db)
        _write_verification_status(
            factory, state="running", mode="background", target_sequence=counter_value,
            verified_through_sequence=0, checked=0, finding_count=0, started_at=_utc_now(),
            finished_at=None, detail={"findings": None},
        )
        scan = _ChainScan(watch_sequence=counter_value)
        after: tuple[int, str] | None = None
        while True:
            with factory() as db, _scope(db):
                rows = _chain_rows_after(db, after, size)
                for row in rows:
                    scan.feed(row)
            if not rows:
                break
            after = (int(rows[-1].sequence), str(rows[-1].id))
            _write_verification_status(
                factory, verified_through_sequence=scan.last_sequence, checked=scan.checked,
                finding_count=len(scan.errors),
            )
        chain = scan.finish(counter_value, counter_last_hash)
        with factory() as db, _scope(db):
            legacy = verify_audit_legacy_rows(db)
        report = _report_from_parts(chain, legacy)
    except Exception as exc:  # noqa: BLE001 -- Hintergrundpruefung darf nie crashen
        logger.warning("Audit-Kettenpruefung im Hintergrund nicht durchfuehrbar: %s", type(exc).__name__)
        _write_verification_status(
            factory, state="error", mode="background", finished_at=_utc_now(),
            detail={"findings": None, "error": type(exc).__name__},
        )
        return None
    _record_final_status(factory, report, mode="background", head_hash=scan.last_hash)
    _log_report(report)
    return report


def restore_tenant_after_rollback(
    db: Session, set_tenant_context: Callable[[Session, str | None], None] | None,
) -> None:
    """Rollback, danach den Tenant-Kontext der Session wieder setzen
    (N-884-09; ohne ``set_tenant_context`` nur Rollback wie bisher)."""
    tenant_id = db.info.get("tenant_id")
    db.rollback()
    if set_tenant_context is not None and tenant_id:
        set_tenant_context(db, tenant_id)


def release_block_audit(
    db: Session,
    *,
    user,
    ip_address: str | None,
    mandate_id: str,
    field_name: str,
    set_tenant_context: Callable[[Session, str | None], None] | None = None,
) -> Callable[[str, str | None], None]:
    """H7 N-884-04/07: Audit-Eintrag fuer eine Freigabe-Sperre (Handoff,
    Signatur, Vor-Ort-Signatur). Rueckgabe ist der ``on_block``-Callback
    ``(reason_code, run_id)``: verwirft offene Aenderungen, schreibt den
    Eintrag (``field_name`` z.B. ``signature_blocked``, ``new_value`` =
    Reason-Code) und committet ihn, BEVOR der Aufrufer den Fehler wirft.

    N-884-09: unter PostgreSQL macht ``db.rollback()`` den in derselben
    Transaktion gesetzten Tenant-Kontext (``set_config(..., false)``)
    rueckgaengig; der Audit-Insert liefe dann ohne ``app.tenant_id`` und
    scheiterte an RLS WITH CHECK. Deshalb wird der Kontext der Session
    (``session.info["tenant_id"]``) nach dem Rollback mit
    ``set_tenant_context`` (services.tenant_context, von den Routern ueber
    services.auth uebergeben) wieder gesetzt."""
    def _on_block(reason_code: str, run_id: str | None = None, *, findings=None) -> None:
        restore_tenant_after_rollback(db, set_tenant_context)
        log(db, user_id=user.id, user_name=user.full_name,
            table_name="recommendation_runs" if run_id else "mandates",
            record_id=run_id or mandate_id, action="UPDATE",
            field_name=field_name, new_value=reason_code,
            mandate_id=mandate_id, ip_address=ip_address)
        # C-890-01: jede Sperre durch die KYC-Wiedervorlage-Policy bekommt einen
        # eigenen, tenantgebundenen Beleg mit Reason-Code, Kanal und
        # Policybezug -- nur strukturierte Kennungen, keine Freitexte.
        for finding in findings or ():
            ref = finding.get("policy_ref") if isinstance(finding, dict) else None
            if not isinstance(ref, dict):
                continue
            log(db, user_id=user.id, user_name=user.full_name,
                table_name="kyc_review_policies",
                record_id=str(ref.get("policy_row_id") or "-"), action="UPDATE",
                field_name=KYC_REVIEW_BLOCK_AUDIT_FIELD,
                new_value=kyc_review_block_audit_value(finding.get("reason_code"), field_name, ref),
                mandate_id=mandate_id, ip_address=ip_address,
                tenant_id=ref.get("tenant_id"))
        db.commit()
    _on_block.accepts_findings = True
    return _on_block


def run_startup_audit_chain_check(
    session_factory: Callable[[], Session] | None = None,
    *,
    max_rows: int | None = None,
    read_scope: Callable[[Session], AbstractContextManager] | None = None,
    background_runner: Callable[[Callable[[], object]], None] | None = None,
) -> dict | None:
    """H-865-2: Startpruefung. Blockiert den Start NIE.

    Begruendung (Verfuegbarkeit): Ein Bruch der Kette ist ein Befund ueber
    die Vergangenheit. Ein Startabbruch repariert ihn nicht (die Zeilen sind
    unveraenderlich), wuerde aber die laufende Beratung und auch den Zugriff
    fuer die Aufarbeitung blockieren. Deshalb: CRITICAL ins Log bei
    verletzter Integritaet, WARNING bei nicht bestaetigter Verkettung von
    Altzeilen oder wenn die Pruefung selbst scheitert. Der Start laeuft
    weiter, die Details liefert GET /admin/system/audit-log/verify, den
    Status GET /admin/system/audit-log/verification-status.

    F6 (Codex-Entscheid Runde 3): ``max_rows`` (Default
    settings.audit_startup_check_max_rows) begrenzt nur die SYNCHRONE
    Vollpruefung. Das Bestandssiegel wird unabhaengig von der Zeilenzahl vor
    dem Return gebildet. Ueber der Grenze: Status 'pending', danach
    Vollpruefung chunked ueber ``background_runner`` (Default: Daemon-
    Thread); Rueckgabe dann None, der Bericht entsteht im Hintergrund.

    N-869-4: ``read_scope`` ist der Lese-Kontext fuer ALLE audit_log-Zeilen
    (unter PostgreSQL der explizite Operator-Bypass, siehe routers/system.py::
    run_startup_audit_chain_check). Ohne ihn saehe eine Session ohne Tenant-
    Kontext unter RLS 0 Zeilen und meldete wegen des Zaehlers einen falschen
    CRITICAL "Kettenende fehlt".
    """
    factory = session_factory or database.SessionLocal
    limit = int(max_rows if max_rows is not None else database.settings.audit_startup_check_max_rows)
    runner = background_runner or _start_daemon_thread

    def _scope(db):
        return read_scope(db) if read_scope is not None else nullcontext()

    try:
        with factory() as db, _scope(db):
            total = int(db.query(func.count(AuditLog.id)).scalar() or 0)
        # F6: Siegel immer zuerst, unabhaengig von der Zeilenzahl.
        _write_seal_if_needed(factory, _scope)
        if total > limit:
            logger.warning(
                "Audit-Kettenpruefung beim Start nicht synchron (uebersprungen): %s Eintraege > "
                "Grenze %s; Bestandssiegel gebildet, Vollpruefung laeuft im Hintergrund "
                "(Status: GET /admin/system/audit-log/verification-status)",
                total, limit,
            )
            _write_verification_status(
                factory, state="pending", mode="background", total_rows=total, threshold=limit,
                target_sequence=None, verified_through_sequence=0, checked=0, finding_count=None,
                started_at=None, finished_at=None, detail={"findings": None},
            )
            runner(lambda: run_chunked_audit_verification(factory, read_scope=read_scope))
            return None
        _write_verification_status(
            factory, state="running", mode="sync", total_rows=total, threshold=limit,
            target_sequence=None, verified_through_sequence=0, checked=0, finding_count=None,
            started_at=_utc_now(), finished_at=None, detail={"findings": None},
        )
        with factory() as db, _scope(db):
            chain = _verify_audit_chain_detail(db)
            legacy = verify_audit_legacy_rows(db)
            head_hash = _hash_at_sequence(db, int(chain["last_sequence"] or 0))
        report = _report_from_parts(chain, legacy)
    except Exception as exc:  # noqa: BLE001 -- die Startpruefung darf den Boot nie stoppen
        logger.warning("Audit-Kettenpruefung beim Start nicht durchfuehrbar: %s", type(exc).__name__)
        _write_verification_status(
            factory, state="error", mode="sync", finished_at=_utc_now(),
            detail={"findings": None, "error": type(exc).__name__},
        )
        return None
    _record_final_status(factory, report, mode="sync", head_hash=head_hash)
    _log_report(report)
    return report


def _hash_at_sequence(db: Session, sequence: int) -> str | None:
    if sequence <= 0:
        return None
    row = (
        db.query(AuditLog.integrity_hash)
        .filter(AuditLog.sequence == sequence)
        .order_by(AuditLog.id.desc())
        .first()
    )
    return row[0] if row is not None else None

# ---------------------------------------------------------------------------
# F4 (Codex-Entscheid Runde 3, 2026-11-07): externer Anker fuer die Audit-Kette
# ---------------------------------------------------------------------------
# Die Audit-Kette ist ein ungeschluesselter SHA-256-Verbund. Wer Schreibzugriff
# auf die Datenbankdatei hat, kann das Kettenende abschneiden (Zeilen loeschen
# und den Zaehler zuruecksetzen) oder die Kette vollstaendig neu berechnen; die
# Kette allein erkennt das nicht (Pruefrunde #869, Abschnitt 4). Erkennbar wird
# es erst gegen einen Stand, der AUSSERHALB des veraenderbaren Speichers liegt.
#
# Ein Anker haelt fest:
#
# - den Kettenkopf (``chain_sequence`` + ``chain_head_hash``),
# - das Bestandssiegel (Sequenz und Hash des Siegel-Eintrags, Digest und Anzahl
#   des versiegelten Altbestands).
#
# Er enthaelt keine Kundendaten, keine Namen, Pfade oder Benutzerkennungen --
# nur Sequenznummern, Hashes, eine Anzahl und Zeitpunkte. Das Textformat ist zum
# Ausdrucken bzw. Ablegen in einer getrennten append-only/WORM- oder
# Treuhand-Ablage gedacht (Owner-Schritt, Runbook). Ein Fingerabdruck (sha256
# der kanonischen Felder) erkennt Abschreibfehler; ist ``backup_hmac_key``
# konfiguriert, traegt der Anker zusaetzlich eine HMAC-SHA256-Signatur (gleiche
# Schluesselverwaltung wie die Backup-Signatur, SEC-007).
#
# Zwei Quellen:
#
# - ``export_audit_anchor``: aus der laufenden Datenbank, NUR nach erfolgreicher
#   Vollpruefung (Kette + Altbestand + Siegel); sonst fail-closed
#   ``AuditAnchorNotVerified``. Feld ``verified: yes``.
# - ``backup_snapshot_anchor`` auf einer Backup-Kopie (``services/backup.py``):
#   der Stand des Snapshots im signierten Backup-Manifest. Feld ``verified: no``
#   (nicht vollgeprueft; ein Restore-Abgleich prueft ihn mit
#   ``verify_audit_anchor`` gegen die wiederhergestellte Datenbank).
#
# ``verify_audit_anchor`` prueft, ob die heutige Kette den Anker-Stand
# unveraendert enthaelt: Kette 1..N lueckenlos und hash-gleich, Kopf N mit dem
# Anker-Hash, Siegel-Eintrag und versiegelter Altbestand unveraendert.
#
# Ort: hier in services.audit (Kette, Siegel, Pruefung); die Backup-Engine
# bekommt den Snapshot-Anker als Funktion uebergeben (backup_snapshot_anchor),
# damit sie frei von App-Importen bleibt (Architektur-Ratsche).

ANCHOR_SCHEME = "ares-audit-anchor-v1"
ANCHOR_PRODUCT = "Ares"

# Feste Reihenfolge der signierten Felder (Textformat und Kanonisierung).
ANCHOR_FIELDS: tuple[str, ...] = (
    "scheme",
    "product",
    "created_at",
    "source",
    "verified",
    "chain_sequence",
    "chain_head_hash",
    "legacy_seal_sequence",
    "legacy_seal_entry_hash",
    "legacy_seal_digest",
    "legacy_seal_count",
)
_INT_FIELDS = frozenset({"chain_sequence", "legacy_seal_sequence", "legacy_seal_count"})
_NONE = "none"
_SIG_PREFIX = "hmac-sha256:"
_HEX64 = frozenset("0123456789abcdef")

Fetch = Callable[[str], list]


class AuditAnchorError(ValueError):
    """Anker nicht bildbar oder nicht lesbar (fail-closed)."""


def _anchor_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


# ---------------------------------------------------------------------------
# Zustand lesen (Live-Session oder Backup-Kopie ueber dasselbe Roh-SQL)
# ---------------------------------------------------------------------------

def read_anchor_state(fetch: Fetch) -> dict:
    """Kettenkopf und Bestandssiegel aus der Datenbank (Roh-SQL, damit
    dieselbe Funktion auf der Live-Session und auf einer Backup-Kopie per
    sqlite3/sqlcipher3 laeuft). Fail-closed: ein inkonsistenter Kopf
    (Zaehler-Hash passt nicht zur Zeile) oder ein unlesbares Siegel ergibt
    ``AuditAnchorError``."""
    counter = fetch("SELECT value, last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'")
    sequence = int(counter[0][0]) if counter and counter[0][0] is not None else 0
    counter_last_hash = counter[0][1] if counter else None
    if sequence > 0:
        rows = fetch(
            "SELECT integrity_hash FROM audit_log WHERE sequence = "
            f"{int(sequence)} ORDER BY id"
        )
        if len(rows) != 1 or not _is_hex64(rows[0][0]):
            raise AuditAnchorError("Kettenkopf fehlt oder ist nicht eindeutig")
        head_hash = str(rows[0][0])
        if counter_last_hash is not None and counter_last_hash != head_hash:
            raise AuditAnchorError("Kettenkopf passt nicht zum Sequenzzaehler")
    else:
        head_hash = _NONE
    seals = fetch(
        "SELECT sequence, integrity_hash, new_value FROM audit_log "
        "WHERE table_name = 'audit_log' AND field_name = 'LEGACY_SEAL' "
        "AND sequence IS NOT NULL ORDER BY sequence"
    )
    if len(seals) > 1:
        raise AuditAnchorError("Mehr als ein Bestandssiegel")
    seal_fields: dict[str, Any] = {
        "legacy_seal_sequence": _NONE,
        "legacy_seal_entry_hash": _NONE,
        "legacy_seal_digest": _NONE,
        "legacy_seal_count": _NONE,
    }
    if seals:
        seal_sequence, seal_hash, seal_value = seals[0]
        try:
            sealed = json.loads(seal_value or "")
        except ValueError as exc:
            raise AuditAnchorError("Bestandssiegel nicht lesbar") from exc
        if (
            sealed.get("scheme") != LEGACY_SEAL_SCHEME
            or not _is_hex64(sealed.get("sha256"))
            or not isinstance(sealed.get("count"), int)
            or not _is_hex64(seal_hash)
        ):
            raise AuditAnchorError("Bestandssiegel nicht lesbar")
        seal_fields = {
            "legacy_seal_sequence": int(seal_sequence),
            "legacy_seal_entry_hash": str(seal_hash),
            "legacy_seal_digest": str(sealed["sha256"]),
            "legacy_seal_count": int(sealed["count"]),
        }
    return {"chain_sequence": sequence, "chain_head_hash": head_hash, **seal_fields}


def _canonical(fields: dict) -> bytes:
    return json.dumps(
        {key: fields[key] for key in ANCHOR_FIELDS}, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def anchor_fingerprint(fields: dict) -> str:
    return hashlib.sha256(_canonical(fields)).hexdigest()


def _signature(fields: dict, key: str) -> str:
    return _SIG_PREFIX + hmac.new(key.encode("utf-8"), _canonical(fields), hashlib.sha256).hexdigest()


def build_anchor(state: dict, *, source: str, verified: bool, key: str | None, created_at: str | None = None) -> dict:
    fields = {
        "scheme": ANCHOR_SCHEME,
        "product": ANCHOR_PRODUCT,
        "created_at": created_at or _anchor_utc_now(),
        "source": source,
        "verified": "yes" if verified else "no",
        **{k: state[k] for k in (
            "chain_sequence", "chain_head_hash", "legacy_seal_sequence",
            "legacy_seal_entry_hash", "legacy_seal_digest", "legacy_seal_count",
        )},
    }
    anchor = dict(fields)
    anchor["fingerprint"] = anchor_fingerprint(fields)
    signing_key = (key or "").strip()
    anchor["signature"] = _signature(fields, signing_key) if signing_key else _NONE
    return anchor


class AuditAnchorNotVerified(AuditAnchorError):
    """Export verweigert: die Vollpruefung der Kette ist nicht ok."""

    def __init__(self, message: str, report: dict | None = None) -> None:
        super().__init__(message)
        self.report = report


def session_fetch(db: Session) -> Fetch:
    """Roh-SQL-Zugriff fuer read_anchor_state auf der Live-Session."""
    return lambda sql: db.execute(text(sql)).fetchall()


def format_anchor_text(anchor: dict) -> str:
    """Quittung zum Ausdrucken/Ablegen. LF-Zeilenenden, nur ASCII."""
    lines = [
        "# Ares Audit-Anker",
        "# Ablage: getrennt vom Rechner und von den Backups, unveraenderlich",
        "# (append-only/WORM-Ablage oder Treuhand). Enthaelt keine Kundendaten.",
        "# Pruefen: scripts/audit_anchor.py verify <Datei> bzw.",
        "# POST /admin/system/audit-log/anchor/verify",
    ]
    for key in (*ANCHOR_FIELDS, "fingerprint", "signature"):
        lines.append(f"{key}: {anchor[key]}")
    return "\n".join(lines) + "\n"


def parse_anchor_text(payload: str) -> dict:
    """Liest eine Quittung. Fail-closed: fehlende, doppelte oder unbekannte
    Felder und ungueltige Werte ergeben ``AuditAnchorError``."""
    known = (*ANCHOR_FIELDS, "fingerprint", "signature")
    values: dict[str, Any] = {}
    for raw in (payload or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in known:
            raise AuditAnchorError("Anker enthaelt eine unbekannte Zeile")
        if key in values:
            raise AuditAnchorError(f"Anker-Feld doppelt: {key}")
        values[key] = value.strip()
    missing = [key for key in known if key not in values]
    if missing:
        raise AuditAnchorError(f"Anker unvollstaendig: {', '.join(missing)}")
    for key in _INT_FIELDS:
        if values[key] != _NONE:
            if not values[key].isdigit():
                raise AuditAnchorError(f"Anker-Feld ungueltig: {key}")
            values[key] = int(values[key])
    if values["scheme"] != ANCHOR_SCHEME:
        raise AuditAnchorError("Anker-Format unbekannt")
    return values


# ---------------------------------------------------------------------------
# Export und Pruefung
# ---------------------------------------------------------------------------

def export_audit_anchor(db: Session, *, key: str | None) -> dict:
    """Anker aus der laufenden Datenbank -- nur nach erfolgreicher
    Vollpruefung (fail-closed). Der Aufrufer stellt unter PostgreSQL den
    Operator-Bypass bereit (alle Tenants, eine Kette)."""
    state = read_anchor_state(session_fetch(db))
    report = audit_log_integrity_report(db)
    if not report["ok"]:
        raise AuditAnchorNotVerified("Audit-Kette nicht intakt; kein Anker ausgestellt", report)
    if report["legacy"]["seal_missing"]:
        raise AuditAnchorNotVerified("Altbestand ohne Bestandssiegel; kein Anker ausgestellt", report)
    # Der Kopf muss in der eben geprueften Kette liegen (Zeilen sind
    # unveraenderlich; neue Eintraege haengen nur an).
    if int(report["chain"]["last_sequence"]) < int(state["chain_sequence"]):
        raise AuditAnchorNotVerified("Kettenkopf nicht in der geprueften Kette", report)
    return build_anchor(state, source="live", verified=True, key=key)


def _check_signature(anchor: dict, key: str | None) -> str:
    signature = str(anchor.get("signature") or _NONE)
    signing_key = (key or "").strip()
    if signature == _NONE:
        # N-880-02: mit konfiguriertem Schluessel ist ein unsignierter Anker
        # (auch eine auf 'none' gesetzte Signaturzeile -- der Fingerabdruck
        # deckt die Signatur nicht ab) nicht ok, wie verify_backup_manifest.
        return "missing" if signing_key else "none"
    if not signature.startswith(_SIG_PREFIX):
        return "invalid"
    if not signing_key:
        return "key_missing"
    return "valid" if hmac.compare_digest(signature, _signature(anchor, signing_key)) else "invalid"


def verify_audit_anchor(
    db: Session, payload: str | dict, *, key: str | None, allow_unsigned: bool = False
) -> dict:
    """Prueft, ob die heutige Kette den Anker-Stand unveraendert enthaelt.

    ``ok`` nur wenn: Fingerabdruck stimmt, Signatur gueltig, Kette 1..N ohne
    Befund und Kopf N hash-gleich, Siegel-Eintrag und versiegelter Altbestand
    unveraendert. Unsigniert ist nur ok, solange kein Schluessel konfiguriert
    ist, oder mit ``allow_unsigned`` (bewusst unsignierter Altanker, z.B. vor
    Einfuehrung von BACKUP_HMAC_KEY; das Ergebnis weist es aus). Gibt nur
    Zaehler, Sequenznummern und Gruende zurueck."""
    reasons: list[str] = []
    anchor = parse_anchor_text(payload) if isinstance(payload, str) else dict(payload)
    fingerprint_ok = hmac.compare_digest(str(anchor.get("fingerprint") or ""), anchor_fingerprint(anchor))
    if not fingerprint_ok:
        reasons.append("fingerprint_mismatch")
    signature = _check_signature(anchor, key)
    if signature in ("invalid", "key_missing") or (signature == "missing" and not allow_unsigned):
        reasons.append(f"signature_{signature}")

    anchor_sequence = int(anchor["chain_sequence"]) if anchor["chain_sequence"] != _NONE else 0
    scan = _ChainScan(watch_sequence=anchor_sequence or None)
    for row in _iter_chain_rows(db):
        if int(row.sequence) > anchor_sequence:
            break
        scan.feed(row)
    prefix_ok = not scan.errors and scan.last_sequence == anchor_sequence
    if not prefix_ok:
        reasons.append("chain_prefix_changed")
    head_match = (
        anchor_sequence == 0 and anchor["chain_head_hash"] == _NONE
    ) or (anchor_sequence > 0 and scan.watched_hash == anchor["chain_head_hash"])
    if not head_match:
        reasons.append("chain_head_mismatch")

    current = read_anchor_state(session_fetch(db))
    seal_match = all(
        current[k] == anchor[k]
        for k in ("legacy_seal_sequence", "legacy_seal_entry_hash", "legacy_seal_digest", "legacy_seal_count")
    )
    if not seal_match:
        reasons.append("legacy_seal_mismatch")
    legacy_seal_ok = _verify_legacy_seal(db)["seal_ok"]
    if anchor["legacy_seal_sequence"] != _NONE and legacy_seal_ok is not True:
        reasons.append("legacy_rows_changed")

    report = audit_log_integrity_report(db)
    return {
        "ok": not reasons,
        "reasons": reasons,
        "anchor_sequence": anchor_sequence,
        "anchor_created_at": str(anchor.get("created_at")),
        "anchor_fingerprint": str(anchor.get("fingerprint")),
        "anchor_verified_at_export": anchor.get("verified") == "yes",
        "signature": signature,
        "unsigned_accepted": signature == "missing" and allow_unsigned,
        "fingerprint_ok": fingerprint_ok,
        "chain_prefix_ok": prefix_ok,
        "head_match": head_match,
        "legacy_seal_match": seal_match,
        "legacy_seal_ok": legacy_seal_ok,
        "current_sequence": int(current["chain_sequence"]),
        "full_chain_ok": bool(report["ok"]),
    }


# N-880-08: Nachweis eines Anker-Abgleichs (GeBueV-Nachvollziehbarkeit der
# Restore-Abgleiche). action='CREATE' mit Merkmal field_name, kein neuer
# action-Wert (sonst Tabellen-Neuaufbau, siehe LEGACY_SEAL). Nur Ergebnis,
# Fingerabdruck, Sequenzen und Gruende -- keine Inhalte.
ANCHOR_VERIFY_TABLE = "audit_anchor"
ANCHOR_VERIFY_MARKER = "ANCHOR_VERIFY"
STATUS_READ_MARKER = "VERIFICATION_STATUS_READ"


def log_anchor_verification(
    db: Session, result: dict, *, user_id: str, user_name: str | None, ip_address: str | None = None,
    target: str = "live",
) -> None:
    """Auditeintrag fuer eine Anker-Pruefung (Endpoint und CLI). Der Aufrufer
    committet (unter PG im Operator-Bypass)."""
    log(
        db,
        user_id=user_id,
        user_name=user_name,
        table_name=ANCHOR_VERIFY_TABLE,
        record_id=str(result.get("anchor_fingerprint") or "unbekannt"),
        action="CREATE",
        field_name=ANCHOR_VERIFY_MARKER,
        new_value=json.dumps({
            "ok": bool(result.get("ok")),
            "target": target,
            "anchor_sequence": result.get("anchor_sequence"),
            "current_sequence": result.get("current_sequence"),
            "signature": result.get("signature"),
            "reasons": list(result.get("reasons") or []),
        }, sort_keys=True, separators=(",", ":")),
        ip_address=ip_address,
    )


def backup_snapshot_anchor(fetch: Fetch, key: str | None) -> dict:
    """Anker-Stand einer Backup-Kopie fuer das Backup-Manifest
    (services.backup.backup_database(snapshot_anchor=...)). Nicht
    vollgeprueft: ``verified: no``; der Restore-Abgleich prueft ihn mit
    verify_audit_anchor gegen die wiederhergestellte Datenbank."""
    return build_anchor(read_anchor_state(fetch), source="backup-snapshot", verified=False, key=key)


KYC_REVIEW_BLOCK_AUDIT_FIELD = "kyc_review_policy_blocked"


def kyc_review_block_audit_value(code, channel_field: str | None, ref: dict) -> str:
    """Strukturierter Auditwert einer Wiedervorlage-Sperre (C-890-01):
    ``<Reason-Code>;kanal=<feld>;policy=<id>@v<version>;jurisdiktion=<land>``."""
    policy = f"{ref.get('policy_id') or '-'}@v{ref.get('version') or '-'}"
    return (
        f"{code};kanal={channel_field or '-'};policy={policy};"
        f"jurisdiktion={ref.get('jurisdiction') or '-'}"
    )


def gate_block_audit(
    db: Session,
    *,
    user,
    mandate,
    ip_address: str | None,
    table_name: str,
    field_name: str,
) -> Callable[[str, dict], None]:
    """Router-Callback fuer fail-closed Gates (z. B. Untergrenze der
    Nachhaltigkeitspraeferenz, N-888-01): schreibt den Block in den
    Audit-Trail und committet VOR dem Fehler, damit die Spur die Ablehnung
    (Rollback des Requests) ueberlebt. ``payload`` ist kanonisches JSON."""

    def _audit(payload: str, result: dict) -> None:
        # N-888-13: der Request scheitert ohnehin; offene fachliche
        # Aenderungen (neu/geaendert/geloescht, auch bereits geflusht) werden
        # VERWORFEN, damit der Commit ausschliesslich den Audit-Eintrag
        # enthaelt. Erst danach schreiben und committen.
        user_id = user.id
        user_name = getattr(user, "full_name", None) or getattr(user, "username", "")
        mandate_id = getattr(mandate, "id", None)
        client_id = getattr(mandate, "client_id", None)
        db.rollback()
        log(
            db,
            user_id=user_id,
            user_name=user_name,
            table_name=table_name,
            record_id=str((result or {}).get("decision_id") or mandate_id or ""),
            action="CREATE",
            field_name=field_name,
            new_value=payload,
            mandate_id=mandate_id,
            client_id=client_id,
            ip_address=ip_address,
        )
        db.commit()

    return _audit
