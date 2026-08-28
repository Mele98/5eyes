import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from models.review import AuditLog, AuditLogSequenceCounter
from models.users import User
from database import new_uuid


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
    previous_entry = (
        db.query(AuditLog)
        .filter(AuditLog.sequence == new_sequence - 1)
        .first()
    )
    previous_hash = str(previous_entry.integrity_hash or "") if previous_entry else ""
    return new_sequence, previous_hash


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


def verify_audit_chain(db: Session) -> dict:
    """SEC-003 (Codex-Audit 2026-08-26): Runtime-Verifier fuer die seit dieser
    Migration gefuehrte Sequenz-Kette. Prueft ausschliesslich Zeilen mit
    sequence IS NOT NULL (Altdaten vor der Migration beanspruchen keine
    lineare Ketten-Garantie, siehe models.review.AuditLog.sequence).

    Prueft pro Zeile:
    - Sequenz ist lueckenlos 1..N (kein uebersprungener/doppelter Wert).
    - previous_hash der Zeile == integrity_hash der Zeile mit sequence-1
      (bzw. "" fuer die Genesis-Zeile sequence=1).
    - integrity_hash der Zeile ist konsistent mit einer Neuberechnung aus
      den gespeicherten Feldern (erkennt nachtraegliche Manipulation trotz
      Umgehung der DB-Trigger, z.B. direkter Dateizugriff).

    Gibt {'ok': bool, 'checked': int, 'errors': [...]} zurueck -- wirft
    nicht, damit ein Admin-Endpoint das Ergebnis direkt anzeigen kann.
    """
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.sequence.isnot(None))
        .order_by(AuditLog.sequence.asc())
        .all()
    )
    errors: list[str] = []
    expected_sequence = 1
    previous_row: AuditLog | None = None
    for row in rows:
        if row.sequence != expected_sequence:
            errors.append(
                f"Sequenzluecke/-duplikat: erwartet {expected_sequence}, gefunden {row.sequence} (id={row.id})"
            )
            expected_sequence = row.sequence
        expected_previous_hash = (
            str(previous_row.integrity_hash or "") if previous_row is not None else ""
        )
        if (row.previous_hash or "") != expected_previous_hash:
            errors.append(
                f"Kette gebrochen bei sequence={row.sequence} (id={row.id}): "
                f"previous_hash stimmt nicht mit dem Vorgaenger-Hash ueberein"
            )
        recomputed_payload = _audit_integrity_payload(
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
            previous_hash=row.previous_hash or "",
            ip_address=row.ip_address,
            tenant_id=row.tenant_id,
        )
        recomputed_hash = hashlib.sha256(recomputed_payload.encode("utf-8")).hexdigest()
        if recomputed_hash != row.integrity_hash:
            errors.append(
                f"integrity_hash stimmt nicht mit Neuberechnung ueberein bei sequence={row.sequence} (id={row.id})"
            )
        expected_sequence += 1
        previous_row = row
    return {"ok": len(errors) == 0, "checked": len(rows), "errors": errors}
