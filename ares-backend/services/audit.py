import hashlib
import json
import logging
from datetime import datetime, timezone
from contextlib import AbstractContextManager, nullcontext
from typing import Callable

from sqlalchemy import func, select
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
    ambiguous: list[int] = []
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
        row_status = _chain_row_status(row, row.previous_hash or "")
        if row_status == _AMBIGUOUS:
            # N-869-6: '|' im Feldwert einer '|'-Zeile, Gegenprobe ohne
            # Hinweis auf Verschiebung -> Hinweis, kein Fehler.
            ambiguous.append(int(row.sequence))
        elif row_status != _MATCH:
            errors.append(
                f"integrity_hash stimmt nicht mit Neuberechnung ueberein bei sequence={row.sequence} (id={row.id})"
            )
            hash_mismatches.append(int(row.sequence))
        expected_sequence += 1
        previous_row = row

    last_sequence = int(rows[-1].sequence) if rows else 0
    counter = db.execute(
        select(AuditLogSequenceCounter.value, AuditLogSequenceCounter.last_hash)
        .where(AuditLogSequenceCounter.id == "singleton")
    ).first()
    counter_value = int(counter[0]) if counter is not None and counter[0] is not None else None
    counter_last_hash = counter[1] if counter is not None else None
    if counter_value is not None and counter_value > last_sequence:
        errors.append(
            f"Kettenende fehlt: Sequenzzaehler steht bei {counter_value}, letzte Zeile hat sequence={last_sequence}"
        )
        gaps.append({"from_sequence": last_sequence + 1, "to_sequence": counter_value})
    elif (
        rows and counter_last_hash is not None and counter_value == last_sequence
        and counter_last_hash != rows[-1].integrity_hash
    ):
        # N-869-4: der auf der Zaehlerzeile gefuehrte Hash muss zum letzten
        # Eintrag passen -- sonst wurde das Kettenende ersetzt.
        errors.append(
            f"Kettenende passt nicht zum Sequenzzaehler: last_hash weicht vom Hash bei sequence={last_sequence} ab"
        )
        breaks.append(last_sequence)
    return {
        "ok": len(errors) == 0,
        "checked": len(rows),
        "errors": errors,
        "breaks": breaks,
        "gaps": gaps,
        "duplicates": duplicates,
        "hash_mismatches": hash_mismatches,
        "ambiguous": ambiguous,
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
            "ambiguous_count": len(chain["ambiguous"]),
            "ambiguous": _capped(chain["ambiguous"]),
        },
        "legacy": legacy,
    }


def run_startup_audit_chain_check(
    session_factory: Callable[[], Session] | None = None,
    *,
    max_rows: int = AUDIT_STARTUP_CHECK_MAX_ROWS,
    read_scope: Callable[[Session], AbstractContextManager] | None = None,
) -> dict | None:
    """H-865-2: leichte Startpruefung. Blockiert den Start NIE.

    Begruendung (Verfuegbarkeit): Ein Bruch der Kette ist ein Befund ueber
    die Vergangenheit. Ein Startabbruch repariert ihn nicht (die Zeilen sind
    unveraenderlich), wuerde aber die laufende Beratung und auch den Zugriff
    fuer die Aufarbeitung blockieren. Deshalb: CRITICAL ins Log bei
    verletzter Integritaet, WARNING bei nicht bestaetigter Verkettung von
    Altzeilen oder wenn die Pruefung selbst scheitert. Der Start laeuft
    weiter, die Details liefert GET /admin/system/audit-log/verify.

    N-869-4: ``read_scope`` ist der Lese-Kontext fuer ALLE audit_log-Zeilen
    (unter PostgreSQL der explizite Operator-Bypass, siehe routers/system.py::
    run_startup_audit_chain_check). Ohne ihn saehe eine Session ohne Tenant-
    Kontext unter RLS 0 Zeilen und meldete wegen des Zaehlers einen falschen
    CRITICAL "Kettenende fehlt".
    """
    factory = session_factory or database.SessionLocal

    def _scope(db):
        return read_scope(db) if read_scope is not None else nullcontext()

    try:
        with factory() as db, _scope(db):
            total = int(db.query(func.count(AuditLog.id)).scalar() or 0)
        if total > max_rows:
            logger.warning(
                "Audit-Kettenpruefung beim Start uebersprungen: %s Eintraege > Grenze %s "
                "(Pruefung ueber GET /admin/system/audit-log/verify)",
                total, max_rows,
            )
            return None
        # Bestandssiegel: genau einmal, verkettet, vor der Pruefung (die es
        # dann gleich mitprueft). Eigene Session: ein Rollback hier wuerde
        # unter PostgreSQL auch den Operator-Bypass (set_config in derselben
        # Transaktion) zuruecknehmen. Ein Fehler stoppt weder Start noch
        # Pruefung.
        try:
            with factory() as db, _scope(db):
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
        with factory() as db, _scope(db):
            report = audit_log_integrity_report(db)
    except Exception as exc:  # noqa: BLE001 -- die Startpruefung darf den Boot nie stoppen
        logger.warning("Audit-Kettenpruefung beim Start nicht durchfuehrbar: %s", type(exc).__name__)
        return None
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
    def _on_block(reason_code: str, run_id: str | None = None) -> None:
        restore_tenant_after_rollback(db, set_tenant_context)
        log(db, user_id=user.id, user_name=user.full_name,
            table_name="recommendation_runs" if run_id else "mandates",
            record_id=run_id or mandate_id, action="UPDATE",
            field_name=field_name, new_value=reason_code,
            mandate_id=mandate_id, ip_address=ip_address)
        db.commit()
    return _on_block
