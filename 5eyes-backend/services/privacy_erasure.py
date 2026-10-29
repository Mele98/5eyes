"""PRIVACY-001: Loeschgesuch mit Dispositionen, Sperrarchiv und
Aufbewahrungsmatrix.

Ablauf
------
1. ``open_erasure_case`` durchsucht das Loeschinventar
   (services/privacy_erasure_inventory.py) fuer den Kunden und legt je
   Tabelle und Datenkategorie eine Dispositionszeile an (Zaehlung + Digest
   der Zeilen-IDs, keine Inhalte).
2. Jede Zeile wird entschieden: ein aktiver Legal Hold, der die Nachweisart
   umfasst, ergibt ``LEGAL_HOLD``; sonst gilt die genehmigte Policy der
   Aufbewahrungsmatrix. Fehlt sie (nur ``PROPOSED`` oder gar nichts), bleibt
   die Zeile ``DECISION_PENDING`` -- weder automatische Loeschung noch stille
   unbegrenzte Aufbewahrung. ``RETAIN_RESTRICTED`` braucht Rechtsgrundlage,
   Fristausloeser und Monate; fehlt das Ausloesedatum, bleibt die Zeile offen.
3. ``execute_erasure_case`` verweigert die Ausfuehrung, solange eine Zeile
   offen ist. Sonst: sperrende Dispositionen werden angewendet (Sperrvermerk),
   loeschende ueber die vorhandenen Methoden (Tier-A-Redaktion,
   Crypto-Shredding). Wo keine Methode existiert oder eine Methode
   gesperrte Evidenz mitzerstoeren wuerde, scheitert die Zeile sichtbar
   (``FAILED`` mit Code), der Vorgang ist dann ``PARTIALLY_EXECUTED``.
4. Der Loeschbeleg enthaelt Vorgangs-ID, Kategorien, Zaehlungen und Digests.
   Ein Ledger-Eintrag neben der DB-Datei (Suppression-Ledger, gleiche Datei
   wie PRIV-005) stellt Vorgang und Sperrvermerke nach einem Backup-Restore
   wieder her, bevor die DB operativ freigegeben wird.
5. ``process_retention_expiry`` markiert abgelaufene Sperren als
   ``DISPOSAL_DUE`` und vernichtet den Kundenschluessel, sobald keine
   versiegelte Evidenz des Kunden mehr gesperrt aufbewahrt werden muss.

``restricted_evidence_types`` ist die Abfrage fuer Lesepfade: gesperrte
Nachweisarten sind fuer Beratung, Analytics und Export nicht mehr lesbar.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func, inspect as sa_inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from database import Base, new_uuid
from models.privacy import (
    PrivacyErasureCase,
    PrivacyErasureDisposition,
    PrivacyLegalHold,
    PrivacyRetentionPolicy,
    PrivacyRoleDesignation,
)
from services import privacy_erasure_inventory as inv

RECEIPT_SCHEMA = "PrivacyErasureReceiptV1"
LEDGER_KIND_CASE = "privacy_case"
LEDGER_KIND_DISPOSAL = "privacy_disposal"

PRIVACY_ROLES = ("LEGAL", "PRIVACY")
RETENTION_TRIGGERS = ("ERASURE_REQUEST", "RELATIONSHIP_END", "LATEST_RECORD")
POLICY_DISPOSITIONS = (inv.DELETE, inv.ANONYMIZE, inv.PARTIAL_DELETE_MINIMIZE, inv.RETAIN_RESTRICTED)

# Pflichtangaben jeder Matrixzeile (PRIVACY-001 "Erforderliche
# Aufbewahrungsmatrix"). Die Werte liefert Legal/Privacy, nie der Code.
REQUIRED_MATRIX_KEYS = (
    "controller",            # Datenverantwortlicher
    "purpose",               # Zweck
    "provider_role",         # betroffene Anbieterrolle
    "processor_role",        # Verantwortlicher/Auftragsbearbeiter
    "mandate_instruction",   # Mandantenweisung
    "information_path",      # Informationsweg
    "allowed_roles",         # erlaubte Nutzer/Rollen
    "legal_hold_rule",       # Legal-Hold-Regel
    "method",                # Minimierungs-/Anonymisierungs-/Loeschmethode
    "replicas",              # Verhalten in Replikaten
    "search_index",          # Verhalten in Suchindizes
    "exports",               # Verhalten in Exporten
    "backups",               # Verhalten in Backups
)
ANONYMIZE_EVIDENCE_KEY = "anonymization_irreversibility"

OPEN_CASE_STATUSES = ("DECISION_PENDING", "READY")
RESTRICTING_LINE_STATUSES = ("APPLIED", "DISPOSAL_DUE")

PRIVACY_TABLES = (
    PrivacyRetentionPolicy.__table__,
    PrivacyRoleDesignation.__table__,
    PrivacyLegalHold.__table__,
    PrivacyErasureCase.__table__,
    PrivacyErasureDisposition.__table__,
)


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def _utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _parse_date(value: str | None, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise _error(422, "PRIVACY_INVALID_DATE", f"{field} ist kein ISO-Datum") from exc


def _add_months(start: date, months: int) -> date:
    year, month_index = divmod(start.month - 1 + months, 12)
    year += start.year
    month = month_index + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _same_tenant(column, tenant_id: str | None):
    return column.is_(None) if tenant_id is None else column == tenant_id


def _client_row(db: Session, client_id: str):
    return db.execute(
        text("SELECT id, tenant_id, erased_at FROM clients WHERE id = :id"), {"id": client_id},
    ).first()


def ensure_privacy_tables(db: Session) -> None:
    """Legt fehlende Privacy-Tabellen an (Restore einer Sicherung, die
    aelter als diese Tabellen ist). Idempotent."""
    bind = db.get_bind()
    for table in PRIVACY_TABLES:
        table.create(bind=bind, checkfirst=True)


# --------------------------------------------------------------------------
# Rollen Legal/Privacy
# --------------------------------------------------------------------------

def active_privacy_roles(db: Session, *, tenant_id: str | None, user_id: str) -> set[str]:
    rows = (
        db.query(PrivacyRoleDesignation.privacy_role)
        .filter(
            _same_tenant(PrivacyRoleDesignation.tenant_id, tenant_id),
            PrivacyRoleDesignation.user_id == user_id,
            PrivacyRoleDesignation.revoked_at.is_(None),
        )
        .all()
    )
    return {str(row[0]) for row in rows}


def _require_privacy_officer(db: Session, *, tenant_id: str | None, user_id: str, action: str) -> None:
    if not user_id or not active_privacy_roles(db, tenant_id=tenant_id, user_id=user_id):
        raise _error(
            403, "PRIVACY_ROLE_REQUIRED",
            f"{action} ist nur fuer im Mandanten benannte Legal-/Privacy-Personen zulaessig",
        )


def grant_privacy_role(
    db: Session, *, tenant_id: str | None, user_id: str, privacy_role: str, granted_by: str,
    now: datetime | None = None,
) -> PrivacyRoleDesignation:
    if privacy_role not in PRIVACY_ROLES:
        raise _error(422, "PRIVACY_ROLE_INVALID", f"Rolle muss eine von {PRIVACY_ROLES} sein")
    user = db.execute(
        text("SELECT tenant_id FROM users WHERE id = :id AND deleted_at IS NULL"), {"id": user_id},
    ).first()
    if user is None or user[0] != tenant_id:
        raise _error(404, "PRIVACY_USER_NOT_IN_TENANT", "Benutzer gehoert nicht zu diesem Mandanten")
    if privacy_role in active_privacy_roles(db, tenant_id=tenant_id, user_id=user_id):
        raise _error(409, "PRIVACY_ROLE_ALREADY_GRANTED", "Rolle ist bereits vergeben")
    designation = PrivacyRoleDesignation(
        id=new_uuid(), tenant_id=tenant_id, user_id=user_id, privacy_role=privacy_role,
        granted_by=granted_by, granted_at=_iso(_utc(now)),
    )
    db.add(designation)
    db.flush()
    return designation


def revoke_privacy_role(
    db: Session, *, designation_id: str, revoked_by: str, now: datetime | None = None,
) -> PrivacyRoleDesignation:
    designation = db.get(PrivacyRoleDesignation, designation_id)
    if designation is None or designation.revoked_at is not None:
        raise _error(404, "PRIVACY_ROLE_NOT_FOUND", "Aktive Rollenbenennung nicht gefunden")
    designation.revoked_at = _iso(_utc(now))
    designation.revoked_by = revoked_by
    db.flush()
    return designation


# --------------------------------------------------------------------------
# Aufbewahrungsmatrix (Policy-Daten)
# --------------------------------------------------------------------------

def _policy_content(policy: PrivacyRetentionPolicy) -> dict[str, Any]:
    return {
        "tenant_id": policy.tenant_id,
        "evidence_type": policy.evidence_type,
        "data_category": policy.data_category,
        "version": policy.version,
        "disposition": policy.disposition,
        "legal_basis": policy.legal_basis,
        "retention_trigger": policy.retention_trigger,
        "retention_months": policy.retention_months,
        "matrix": json.loads(policy.matrix_json),
    }


def propose_policy(
    db: Session,
    *,
    tenant_id: str | None,
    evidence_type: str,
    data_category: str,
    disposition: str,
    matrix: dict[str, Any],
    proposed_by: str,
    legal_basis: str | None = None,
    retention_trigger: str | None = None,
    retention_months: int | None = None,
    now: datetime | None = None,
) -> PrivacyRetentionPolicy:
    """Legt eine neue Version als ``PROPOSED`` an. Ohne Wirkung, bis sie
    von einer benannten Legal-/Privacy-Person genehmigt ist."""
    if evidence_type not in inv.EVIDENCE_TYPES:
        raise _error(422, "PRIVACY_EVIDENCE_TYPE_UNKNOWN", f"Unbekannte Nachweisart {evidence_type!r}")
    if data_category != "*" and data_category not in inv.DATA_CATEGORIES:
        raise _error(422, "PRIVACY_CATEGORY_UNKNOWN", f"Unbekannte Datenkategorie {data_category!r}")
    if disposition not in POLICY_DISPOSITIONS:
        raise _error(
            422, "PRIVACY_DISPOSITION_INVALID",
            "Policy-Disposition muss DELETE, ANONYMIZE, PARTIAL_DELETE_MINIMIZE oder "
            "RETAIN_RESTRICTED sein; LEGAL_HOLD entsteht nur ueber einen Legal Hold",
        )
    if retention_trigger is not None and retention_trigger not in RETENTION_TRIGGERS:
        raise _error(422, "PRIVACY_TRIGGER_INVALID", f"Fristausloeser muss einer von {RETENTION_TRIGGERS} sein")
    if not isinstance(matrix, dict):
        raise _error(422, "PRIVACY_MATRIX_INVALID", "Matrix-Angaben muessen ein Objekt sein")
    latest = (
        db.query(func.max(PrivacyRetentionPolicy.version))
        .filter(
            _same_tenant(PrivacyRetentionPolicy.tenant_id, tenant_id),
            PrivacyRetentionPolicy.evidence_type == evidence_type,
            PrivacyRetentionPolicy.data_category == data_category,
        )
        .scalar()
    )
    policy = PrivacyRetentionPolicy(
        id=new_uuid(), tenant_id=tenant_id, evidence_type=evidence_type, data_category=data_category,
        version=int(latest or 0) + 1, status="PROPOSED", disposition=disposition,
        legal_basis=legal_basis, retention_trigger=retention_trigger, retention_months=retention_months,
        matrix_json=_canonical(matrix), policy_hash="", proposed_by=proposed_by,
        proposed_at=_iso(_utc(now)),
    )
    policy.policy_hash = _sha256(_canonical(_policy_content(policy)))
    db.add(policy)
    db.flush()
    return policy


def policy_approval_problems(policy: PrivacyRetentionPolicy) -> list[str]:
    """Was einer Genehmigung entgegensteht (leer = genehmigungsfaehig)."""
    problems: list[str] = []
    matrix = json.loads(policy.matrix_json or "{}")
    for key in REQUIRED_MATRIX_KEYS:
        value = matrix.get(key)
        if value in (None, "", [], {}):
            problems.append(f"Matrixangabe fehlt: {key}")
    if not (policy.legal_basis or "").strip():
        problems.append("Rechtsgrundlage fehlt")
    if policy.disposition == inv.RETAIN_RESTRICTED:
        if policy.retention_trigger not in RETENTION_TRIGGERS:
            problems.append("RETAIN_RESTRICTED braucht einen pruefbaren Fristausloeser")
        if not isinstance(policy.retention_months, int) or policy.retention_months <= 0:
            problems.append("RETAIN_RESTRICTED braucht eine Frist in Monaten (> 0)")
    if policy.disposition == inv.ANONYMIZE and not matrix.get(ANONYMIZE_EVIDENCE_KEY):
        problems.append("ANONYMIZE braucht den Nachweis der irreversiblen Anonymisierung")
    return problems


def approve_policy(
    db: Session, *, policy_id: str, approved_by: str, now: datetime | None = None,
) -> PrivacyRetentionPolicy:
    policy = db.get(PrivacyRetentionPolicy, policy_id)
    if policy is None:
        raise _error(404, "PRIVACY_POLICY_NOT_FOUND", "Policy nicht gefunden")
    if policy.status != "PROPOSED":
        raise _error(409, "PRIVACY_POLICY_NOT_PROPOSED", "Nur vorgeschlagene Policies sind genehmigungsfaehig")
    _require_privacy_officer(db, tenant_id=policy.tenant_id, user_id=approved_by, action="Policy-Genehmigung")
    if approved_by == policy.proposed_by:
        raise _error(409, "PRIVACY_FOUR_EYES", "Vorschlag und Genehmigung muessen von verschiedenen Personen stammen")
    problems = policy_approval_problems(policy)
    if problems:
        raise _error(422, "PRIVACY_POLICY_INCOMPLETE", "; ".join(problems))
    stamp = _iso(_utc(now))
    previous = (
        db.query(PrivacyRetentionPolicy)
        .filter(
            _same_tenant(PrivacyRetentionPolicy.tenant_id, policy.tenant_id),
            PrivacyRetentionPolicy.evidence_type == policy.evidence_type,
            PrivacyRetentionPolicy.data_category == policy.data_category,
            PrivacyRetentionPolicy.status == "APPROVED",
        )
        .all()
    )
    for row in previous:
        row.status = "RETIRED"
        row.retired_at = stamp
    policy.status = "APPROVED"
    policy.approved_by = approved_by
    policy.approved_at = stamp
    db.flush()
    return policy


def approved_policy(
    db: Session, *, tenant_id: str | None, evidence_type: str, data_category: str,
) -> PrivacyRetentionPolicy | None:
    for category in (data_category, "*"):
        row = (
            db.query(PrivacyRetentionPolicy)
            .filter(
                _same_tenant(PrivacyRetentionPolicy.tenant_id, tenant_id),
                PrivacyRetentionPolicy.evidence_type == evidence_type,
                PrivacyRetentionPolicy.data_category == category,
                PrivacyRetentionPolicy.status == "APPROVED",
            )
            .order_by(PrivacyRetentionPolicy.version.desc())
            .first()
        )
        if row is not None:
            return row
    return None


# --------------------------------------------------------------------------
# Legal Hold
# --------------------------------------------------------------------------

def _validated_scope(scope: Iterable[str]) -> list[str]:
    values = sorted({str(item) for item in (scope or [])})
    if not values:
        raise _error(422, "PRIVACY_HOLD_SCOPE_EMPTY", "Legal Hold braucht einen Umfang (Nachweisarten)")
    unknown = [item for item in values if item not in inv.EVIDENCE_TYPES]
    if unknown:
        raise _error(422, "PRIVACY_EVIDENCE_TYPE_UNKNOWN", f"Unbekannte Nachweisarten: {unknown}")
    return values


def create_legal_hold(
    db: Session,
    *,
    client_id: str,
    case_reference: str,
    legal_reason: str,
    scope: Iterable[str],
    review_date: str,
    set_by: str,
    expires_at: str | None = None,
    now: datetime | None = None,
) -> PrivacyLegalHold:
    """Legt einen Legal Hold als ``PROPOSED`` an. Er wirkt erst, wenn eine
    zweite benannte Legal-/Privacy-Person ihn genehmigt."""
    client = _client_row(db, client_id)
    if client is None:
        raise _error(404, "PRIVACY_CLIENT_NOT_FOUND", "Kunde nicht gefunden")
    tenant_id = client[1]
    if not (case_reference or "").strip() or not (legal_reason or "").strip():
        raise _error(422, "PRIVACY_HOLD_INCOMPLETE", "Fall-ID und Rechtsgrund sind Pflicht")
    review = _parse_date(review_date, "review_date")
    if review is None:
        raise _error(422, "PRIVACY_HOLD_INCOMPLETE", "Review-Datum ist Pflicht")
    expiry = _parse_date(expires_at, "expires_at")
    scope_values = _validated_scope(scope)
    _require_privacy_officer(db, tenant_id=tenant_id, user_id=set_by, action="Legal Hold")
    stamp = _iso(_utc(now))
    hold = PrivacyLegalHold(
        id=new_uuid(), tenant_id=tenant_id, client_id=client_id, case_reference=case_reference.strip(),
        legal_reason=legal_reason.strip(), scope_json=_canonical(scope_values), set_by=set_by,
        review_date=review.isoformat(), expires_at=expiry.isoformat() if expiry else None,
        status="PROPOSED", extension_count=0, created_at=stamp, updated_at=stamp,
    )
    db.add(hold)
    db.flush()
    return hold


def approve_legal_hold(
    db: Session, *, hold_id: str, approved_by: str, now: datetime | None = None,
) -> PrivacyLegalHold:
    hold = db.get(PrivacyLegalHold, hold_id)
    if hold is None or hold.status != "PROPOSED":
        raise _error(404, "PRIVACY_HOLD_NOT_FOUND", "Vorgeschlagener Legal Hold nicht gefunden")
    _require_privacy_officer(db, tenant_id=hold.tenant_id, user_id=approved_by, action="Legal-Hold-Genehmigung")
    if approved_by == hold.set_by:
        raise _error(409, "PRIVACY_FOUR_EYES", "Setzer und Genehmiger muessen verschiedene Personen sein")
    stamp = _iso(_utc(now))
    hold.status = "ACTIVE"
    hold.approved_by = approved_by
    hold.approved_at = stamp
    hold.updated_at = stamp
    db.flush()
    return hold


def extend_legal_hold(
    db: Session, *, hold_id: str, review_date: str, actor: str,
    expires_at: str | None = None, now: datetime | None = None,
) -> PrivacyLegalHold:
    hold = db.get(PrivacyLegalHold, hold_id)
    if hold is None or hold.status != "ACTIVE":
        raise _error(404, "PRIVACY_HOLD_NOT_FOUND", "Aktiver Legal Hold nicht gefunden")
    review = _parse_date(review_date, "review_date")
    if review is None:
        raise _error(422, "PRIVACY_HOLD_INCOMPLETE", "Review-Datum ist Pflicht")
    expiry = _parse_date(expires_at, "expires_at")
    _require_privacy_officer(db, tenant_id=hold.tenant_id, user_id=actor, action="Legal-Hold-Verlaengerung")
    hold.review_date = review.isoformat()
    hold.expires_at = expiry.isoformat() if expiry else None
    hold.extension_count = int(hold.extension_count or 0) + 1
    hold.updated_at = _iso(_utc(now))
    db.flush()
    return hold


def release_legal_hold(
    db: Session, *, hold_id: str, actor: str, now: datetime | None = None,
) -> PrivacyLegalHold:
    hold = db.get(PrivacyLegalHold, hold_id)
    if hold is None or hold.status not in ("PROPOSED", "ACTIVE"):
        raise _error(404, "PRIVACY_HOLD_NOT_FOUND", "Offener Legal Hold nicht gefunden")
    _require_privacy_officer(db, tenant_id=hold.tenant_id, user_id=actor, action="Legal-Hold-Aufhebung")
    stamp = _iso(_utc(now))
    hold.status = "RELEASED"
    hold.released_by = actor
    hold.released_at = stamp
    hold.updated_at = stamp
    db.flush()
    return hold


def _hold_is_active(hold: PrivacyLegalHold, today: date) -> bool:
    if hold.status != "ACTIVE":
        return False
    expiry = _parse_date(hold.expires_at, "expires_at")
    return expiry is None or expiry > today


def active_legal_holds(
    db: Session, *, tenant_id: str | None, client_id: str, now: datetime | None = None,
) -> list[PrivacyLegalHold]:
    today = _utc(now).date()
    rows = (
        db.query(PrivacyLegalHold)
        .filter(
            _same_tenant(PrivacyLegalHold.tenant_id, tenant_id),
            PrivacyLegalHold.client_id == client_id,
            PrivacyLegalHold.status == "ACTIVE",
        )
        .order_by(PrivacyLegalHold.created_at)
        .all()
    )
    return [hold for hold in rows if _hold_is_active(hold, today)]


def _hold_for(holds: list[PrivacyLegalHold], evidence_type: str) -> PrivacyLegalHold | None:
    for hold in holds:
        if evidence_type in json.loads(hold.scope_json):
            return hold
    return None


# --------------------------------------------------------------------------
# Inventarsuche
# --------------------------------------------------------------------------

def _primary_key_column(table: str) -> str | None:
    meta = Base.metadata.tables.get(table)
    if meta is None:
        return None
    columns = [column.name for column in meta.primary_key.columns]
    return columns[0] if len(columns) == 1 else None


def _table_columns(db: Session, table: str) -> set[str]:
    inspector = sa_inspect(db.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


class _ClientScope:
    """Findet die Zeilen-IDs jeder Inventartabelle fuer einen Kunden."""

    def __init__(self, db: Session, client_id: str):
        self.db = db
        self.client_id = client_id
        self._ids: dict[str, list[str]] = {}
        self._columns: dict[str, set[str]] = {}
        self.mandate_ids = self._select("SELECT id FROM mandates WHERE client_id = :v", client_id)
        self.login_user_ids = (
            self._select("SELECT user_id FROM client_logins WHERE client_id = :v", client_id)
            if self.columns("client_logins") else []
        )

    def _select(self, sql: str, value: str) -> list[str]:
        return [str(row[0]) for row in self.db.execute(text(sql), {"v": value}).all() if row[0] is not None]

    def columns(self, table: str) -> set[str]:
        if table not in self._columns:
            self._columns[table] = _table_columns(self.db, table)
        return self._columns[table]

    def _scope_values(self, scope: str) -> list[str]:
        if scope == "client":
            return [self.client_id]
        if scope == "mandate":
            return self.mandate_ids
        if scope == "client_login_user":
            return self.login_user_ids
        return self.row_ids(scope)

    def row_ids(self, table: str) -> list[str]:
        if table in self._ids:
            return self._ids[table]
        entry = inv.PERSONAL_DATA_INVENTORY[table]
        route_column, scope = entry.route
        pk = _primary_key_column(table)
        columns = self.columns(table)
        values = self._scope_values(scope)
        ids: list[str] = []
        if values and pk and route_column in columns and pk in columns:
            params = {f"v{i}": value for i, value in enumerate(values)}
            placeholders = ", ".join(f":{key}" for key in params)
            rows = self.db.execute(
                text(f'SELECT "{pk}" FROM "{table}" WHERE "{route_column}" IN ({placeholders})'),
                params,
            ).all()
            ids = sorted(str(row[0]) for row in rows)
        self._ids[table] = ids
        return ids

    def latest_created(self, table: str) -> date | None:
        ids = self.row_ids(table)
        pk = _primary_key_column(table)
        if not ids or not pk or "created_at" not in self.columns(table):
            return None
        params = {f"v{i}": value for i, value in enumerate(ids)}
        placeholders = ", ".join(f":{key}" for key in params)
        value = self.db.execute(
            text(f'SELECT MAX(created_at) FROM "{table}" WHERE "{pk}" IN ({placeholders})'), params,
        ).scalar()
        return _parse_date(value, "created_at") if value else None


def _rows_digest(table: str, ids: list[str]) -> str | None:
    if not ids:
        return None
    return _sha256(_canonical({"table": table, "ids": ids}))


# --------------------------------------------------------------------------
# Vorgang
# --------------------------------------------------------------------------

def _case_lines(db: Session, case_id: str) -> list[PrivacyErasureDisposition]:
    return (
        db.query(PrivacyErasureDisposition)
        .filter(PrivacyErasureDisposition.case_id == case_id)
        .order_by(PrivacyErasureDisposition.table_name, PrivacyErasureDisposition.data_category)
        .all()
    )


def _retention_base(case: PrivacyErasureCase, line: PrivacyErasureDisposition, trigger: str | None,
                    scope: _ClientScope | None) -> date | None:
    if trigger == "ERASURE_REQUEST":
        return _parse_date(case.opened_at, "opened_at")
    if trigger == "RELATIONSHIP_END":
        return _parse_date(case.relationship_end_date, "relationship_end_date")
    if trigger == "LATEST_RECORD" and scope is not None:
        return scope.latest_created(line.table_name)
    return None


def _decide_line(
    line: PrivacyErasureDisposition,
    case: PrivacyErasureCase,
    db: Session,
    holds: list[PrivacyLegalHold],
    scope: _ClientScope | None,
    stamp: str,
) -> None:
    line.disposition = None
    line.policy_id = None
    line.legal_hold_id = None
    line.legal_basis = None
    line.retention_trigger = None
    line.retain_until = None
    line.failure_code = None
    line.updated_at = stamp
    if not line.row_count:
        line.decision_status = "NO_DATA"
        return
    hold = _hold_for(holds, line.evidence_type)
    if hold is not None:
        line.decision_status = "DECIDED"
        line.disposition = inv.LEGAL_HOLD
        line.legal_hold_id = hold.id
        line.retain_until = hold.expires_at
        return
    policy = approved_policy(
        db, tenant_id=case.tenant_id, evidence_type=line.evidence_type, data_category=line.data_category,
    )
    if policy is None:
        line.decision_status = "DECISION_PENDING"
        line.failure_code = "NO_APPROVED_POLICY"
        return
    line.policy_id = policy.id
    line.legal_basis = policy.legal_basis
    line.disposition = policy.disposition
    if policy.disposition == inv.RETAIN_RESTRICTED:
        line.retention_trigger = policy.retention_trigger
        base = _retention_base(case, line, policy.retention_trigger, scope)
        if base is None:
            line.decision_status = "DECISION_PENDING"
            line.failure_code = "RETENTION_TRIGGER_DATE_MISSING"
            return
        line.retain_until = _add_months(base, int(policy.retention_months)).isoformat()
    line.decision_status = "DECIDED"


def _refresh_status(case: PrivacyErasureCase, lines: list[PrivacyErasureDisposition]) -> None:
    if case.status in ("EXECUTED", "PARTIALLY_EXECUTED"):
        return
    pending = any(line.decision_status == "DECISION_PENDING" for line in lines)
    case.status = "DECISION_PENDING" if pending else "READY"


def open_erasure_case(
    db: Session,
    *,
    client_id: str,
    opened_by: str,
    relationship_end_date: str | None = None,
    now: datetime | None = None,
) -> PrivacyErasureCase:
    """Legt den Vorgang an, inventarisiert und entscheidet jede Kategorie."""
    client = _client_row(db, client_id)
    if client is None:
        raise _error(404, "PRIVACY_CLIENT_NOT_FOUND", "Kunde nicht gefunden")
    tenant_id = client[1]
    end_date = _parse_date(relationship_end_date, "relationship_end_date")
    existing = (
        db.query(PrivacyErasureCase)
        .filter(PrivacyErasureCase.client_id == client_id, PrivacyErasureCase.status.in_(OPEN_CASE_STATUSES))
        .first()
    )
    if existing is not None:
        raise _error(409, "PRIVACY_CASE_ALREADY_OPEN", "Fuer diesen Kunden ist bereits ein Loeschvorgang offen")
    stamp = _iso(_utc(now))
    case = PrivacyErasureCase(
        id=new_uuid(), tenant_id=tenant_id, client_id=client_id, status="DECISION_PENDING",
        inventory_version=inv.INVENTORY_VERSION,
        relationship_end_date=end_date.isoformat() if end_date else None,
        opened_by=opened_by, opened_at=stamp, updated_at=stamp,
    )
    db.add(case)
    scope = _ClientScope(db, client_id)
    holds = active_legal_holds(db, tenant_id=tenant_id, client_id=client_id, now=now)
    lines: list[PrivacyErasureDisposition] = []
    for table in sorted(inv.PERSONAL_DATA_INVENTORY):
        ids = scope.row_ids(table)
        for category in inv.categories_for(table):
            line = PrivacyErasureDisposition(
                id=new_uuid(), case_id=case.id, tenant_id=tenant_id, client_id=client_id,
                table_name=table, data_category=category.name, evidence_type=category.evidence_type,
                method=category.method, row_count=len(ids), rows_digest=_rows_digest(table, ids),
                decision_status="DECISION_PENDING", created_at=stamp, updated_at=stamp,
            )
            _decide_line(line, case, db, holds, scope, stamp)
            db.add(line)
            lines.append(line)
    _refresh_status(case, lines)
    db.flush()
    return case


def refresh_erasure_case(db: Session, *, case_id: str, now: datetime | None = None) -> PrivacyErasureCase:
    """Entscheidet offene Zeilen neu (z.B. nach Genehmigung einer Policy
    oder nach Setzen eines Legal Holds). Angewendete Zeilen bleiben."""
    case = db.get(PrivacyErasureCase, case_id)
    if case is None:
        raise _error(404, "PRIVACY_CASE_NOT_FOUND", "Loeschvorgang nicht gefunden")
    stamp = _iso(_utc(now))
    scope = _ClientScope(db, case.client_id)
    holds = active_legal_holds(db, tenant_id=case.tenant_id, client_id=case.client_id, now=now)
    lines = _case_lines(db, case.id)
    redecide = ("DECISION_PENDING", "DECIDED", "FAILED") if case.status == "PARTIALLY_EXECUTED" else (
        "DECISION_PENDING", "DECIDED",
    )
    for line in lines:
        if line.decision_status in redecide:
            _decide_line(line, case, db, holds, scope, stamp)
    _refresh_status(case, lines)
    case.updated_at = stamp
    db.flush()
    return case


def _keys_already_shredded(db: Session, client_id: str) -> bool:
    if "client_pii_keys" not in set(sa_inspect(db.get_bind()).get_table_names()):
        return False
    row = db.execute(
        text("SELECT shredded_at FROM client_pii_keys WHERE client_id = :id"), {"id": client_id},
    ).first()
    return bool(row and row[0])


def _receipt(case: PrivacyErasureCase, lines: list[PrivacyErasureDisposition]) -> dict[str, Any]:
    totals: dict[str, int] = {}
    for line in lines:
        key = f"{line.decision_status}:{line.disposition or '-'}"
        totals[key] = totals.get(key, 0) + 1
    return {
        "schema": RECEIPT_SCHEMA,
        "case_id": case.id,
        "inventory_version": case.inventory_version,
        "opened_at": case.opened_at,
        "executed_at": case.executed_at,
        "status": case.status,
        "lines": [
            {
                "table": line.table_name,
                "data_category": line.data_category,
                "evidence_type": line.evidence_type,
                "decision_status": line.decision_status,
                "disposition": line.disposition,
                "row_count": int(line.row_count or 0),
                "rows_digest": line.rows_digest,
                "retention_trigger": line.retention_trigger,
                "retain_until": line.retain_until,
                "policy_id": line.policy_id,
                "legal_hold_id": line.legal_hold_id,
                "failure_code": line.failure_code,
            }
            for line in lines
        ],
        "totals": dict(sorted(totals.items())),
    }


_CASE_LEDGER_FIELDS = (
    "id", "tenant_id", "client_id", "status", "inventory_version", "relationship_end_date",
    "opened_by", "opened_at", "executed_by", "executed_at", "receipt_json", "receipt_sha256", "updated_at",
)
_LINE_LEDGER_FIELDS = tuple(column.name for column in PrivacyErasureDisposition.__table__.columns)


def _write_ledger(db: Session, entry: dict[str, Any]) -> None:
    from services.client_erasure import _append_ledger_entry, _ledger_path

    try:
        _append_ledger_entry(_ledger_path(db), entry)
    except OSError as exc:
        raise _error(
            503, "PRIVACY_LEDGER_UNAVAILABLE",
            "Suppression-Ledger nicht schreibbar; Vorgang nicht ausgefuehrt",
        ) from exc


def execute_erasure_case(
    db: Session, *, case_id: str, executed_by: str, now: datetime | None = None,
) -> PrivacyErasureCase:
    """Wendet die entschiedenen Dispositionen an (fail-closed bei offenen
    Entscheiden). Der Aufrufer committet; bei einer Ausnahme rollt er
    zurueck, und nichts ist angewendet."""
    case = db.get(PrivacyErasureCase, case_id)
    if case is None:
        raise _error(404, "PRIVACY_CASE_NOT_FOUND", "Loeschvorgang nicht gefunden")
    if case.status == "EXECUTED":
        raise _error(409, "PRIVACY_CASE_ALREADY_EXECUTED", "Loeschvorgang ist bereits ausgefuehrt")
    refresh_erasure_case(db, case_id=case_id, now=now)
    lines = _case_lines(db, case.id)
    pending = [line for line in lines if line.decision_status == "DECISION_PENDING"]
    if pending:
        raise _error(
            409, "PRIVACY_DECISION_PENDING",
            f"Entscheid ausstehend fuer {len(pending)} Kategorie(n); keine Loeschung und keine Sperre ausgefuehrt",
        )
    stamp = _iso(_utc(now))
    todo = [line for line in lines if line.decision_status == "DECIDED"]

    def _relevant(method: str) -> list[PrivacyErasureDisposition]:
        return [line for line in lines if line.method == method and line.row_count
                and line.decision_status in ("DECIDED", "APPLIED", "DISPOSAL_DUE")]

    tier_a_lines = _relevant(inv.TIER_A_REDACTION)
    crypto_lines = _relevant(inv.CRYPTO_SHRED)
    tier_a_ok = bool(tier_a_lines) and all(
        line.disposition in inv.ERASING_DISPOSITIONS for line in tier_a_lines
    )
    crypto_ok = bool(crypto_lines) and all(
        line.disposition in inv.ERASING_DISPOSITIONS for line in crypto_lines
    )
    keys_were_shredded = _keys_already_shredded(db, case.client_id)
    run_tier_a = tier_a_ok and any(line in todo for line in tier_a_lines)
    run_shred = crypto_ok and any(line in todo for line in crypto_lines) and not keys_were_shredded

    client = _client_row(db, case.client_id)
    if run_tier_a and client is not None and not client[2]:
        from services.client_erasure import erase_client_personal_data

        erase_client_personal_data(
            db, case.client_id, reason=f"PRIVACY-001 Loeschvorgang {case.id}", shred_pii_keys=run_shred,
        )
    elif run_shred:
        from services.pii_vault import shred_client_keys

        shred_client_keys(db, case.client_id)

    for line in todo:
        failure: str | None = None
        if line.disposition in inv.RESTRICTING_DISPOSITIONS:
            if line.method == inv.CRYPTO_SHRED and keys_were_shredded:
                failure = "KEY_ALREADY_SHREDDED"
        elif line.method is None:
            failure = "METHOD_NOT_IMPLEMENTED"
        elif line.method == inv.TIER_A_REDACTION and not tier_a_ok:
            failure = "TIER_A_NOT_SEPARABLE"
        elif line.method == inv.CRYPTO_SHRED and not crypto_ok:
            failure = "SHARED_KEY_RETAINED"
        line.updated_at = stamp
        if failure:
            line.decision_status = "FAILED"
            line.failure_code = failure
        else:
            line.decision_status = "APPLIED"
            line.applied_at = stamp
    failed = any(line.decision_status == "FAILED" for line in lines)
    case.status = "PARTIALLY_EXECUTED" if failed else "EXECUTED"
    case.executed_by = executed_by
    case.executed_at = stamp
    case.updated_at = stamp
    receipt = _receipt(case, lines)
    case.receipt_json = _canonical(receipt)
    case.receipt_sha256 = _sha256(case.receipt_json)
    db.flush()
    _write_ledger(db, {
        "kind": LEDGER_KIND_CASE,
        "case": {field: getattr(case, field) for field in _CASE_LEDGER_FIELDS},
        "lines": [{field: getattr(line, field) for field in _LINE_LEDGER_FIELDS} for line in lines],
        "keys_shredded": bool(run_shred or keys_were_shredded),
        "recorded_at": stamp,
    })
    return case


# --------------------------------------------------------------------------
# Fristablauf
# --------------------------------------------------------------------------

def process_retention_expiry(
    db: Session, *, now: datetime | None = None, tenant_id: str | None = None, all_tenants: bool = False,
) -> dict[str, Any]:
    """Abgelaufene Sperren werden ``DISPOSAL_DUE``; ein aufgehobener oder
    abgelaufener Legal Hold ebenso. Ist fuer einen Kunden keine versiegelte
    Evidenz mehr gesperrt, wird sein Schluessel vernichtet und die
    faelligen Crypto-Zeilen sind ``DISPOSED`` (nicht wiederherstellbar).
    Andere faellige Zeilen bleiben sichtbar ``DISPOSAL_DUE``, bis eine
    Entsorgungsmethode existiert."""
    moment = _utc(now)
    today = moment.date()
    stamp = _iso(moment)
    query = db.query(PrivacyErasureDisposition).filter(
        PrivacyErasureDisposition.decision_status.in_(RESTRICTING_LINE_STATUSES),
        PrivacyErasureDisposition.disposition.in_(sorted(inv.RESTRICTING_DISPOSITIONS)),
    )
    if not all_tenants:
        query = query.filter(_same_tenant(PrivacyErasureDisposition.tenant_id, tenant_id))
    lines = query.all()
    holds_by_client: dict[str, list[PrivacyLegalHold]] = {}
    newly_due = 0
    for line in lines:
        if line.decision_status != "APPLIED":
            continue
        key = f"{line.tenant_id}|{line.client_id}"
        if key not in holds_by_client:
            holds_by_client[key] = active_legal_holds(
                db, tenant_id=line.tenant_id, client_id=line.client_id, now=moment,
            )
        holds = holds_by_client[key]
        if line.disposition == inv.LEGAL_HOLD:
            hold = db.get(PrivacyLegalHold, line.legal_hold_id) if line.legal_hold_id else None
            due = hold is None or not _hold_is_active(hold, today)
        else:
            until = _parse_date(line.retain_until, "retain_until")
            due = until is not None and until <= today and _hold_for(holds, line.evidence_type) is None
        if due:
            line.decision_status = "DISPOSAL_DUE"
            line.updated_at = stamp
            newly_due += 1

    disposed = 0
    shredded_clients: list[str] = []
    clients = sorted({(line.tenant_id, line.client_id) for line in lines})
    for line_tenant, client_id in clients:
        crypto_lines = [line for line in lines if line.client_id == client_id
                        and line.tenant_id == line_tenant and line.method == inv.CRYPTO_SHRED]
        if not crypto_lines or any(line.decision_status == "APPLIED" for line in crypto_lines):
            continue
        if not _keys_already_shredded(db, client_id):
            from services.pii_vault import shred_client_keys

            shred_client_keys(db, client_id)
            shredded_clients.append(client_id)
        for line in crypto_lines:
            if line.decision_status == "DISPOSAL_DUE":
                line.decision_status = "DISPOSED"
                line.disposed_at = stamp
                line.updated_at = stamp
                disposed += 1
    db.flush()
    if shredded_clients:
        _write_ledger(db, {
            "kind": LEDGER_KIND_DISPOSAL,
            "subject_client_ids": shredded_clients,
            "disposed_line_ids": sorted(
                line.id for line in lines if line.decision_status == "DISPOSED" and line.disposed_at == stamp
            ),
            "disposed_at": stamp,
        })
    return {"disposal_due": newly_due, "disposed": disposed, "keys_shredded_clients": shredded_clients}


# --------------------------------------------------------------------------
# Lese-Gate (Sperrarchiv)
# --------------------------------------------------------------------------

def restricted_evidence_types(
    db: Session, *, client_id: str | None = None, mandate_id: str | None = None,
) -> frozenset[str]:
    """Nachweisarten, die fuer diesen Kunden gesperrt sind (angewendete
    ``RETAIN_RESTRICTED``-/``LEGAL_HOLD``-Disposition, noch nicht entsorgt).
    Lesepfade fuer Beratung, Analytics und Export muessen sie ausblenden.

    Genau eine Abfrage (Lesepfade haben Query-Budgets). Eine SQLite-DB ohne
    Privacy-Tabellen (aelterer Schemastand) hat keine Sperren."""
    if client_id is None and mandate_id is None:
        return frozenset()
    statuses = ", ".join(f"'{value}'" for value in RESTRICTING_LINE_STATUSES)
    dispositions = ", ".join(f"'{value}'" for value in sorted(inv.RESTRICTING_DISPOSITIONS))
    if client_id is not None:
        scope, params = "d.client_id = :value", {"value": client_id}
    else:
        scope = "d.client_id = (SELECT m.client_id FROM mandates m WHERE m.id = :value)"
        params = {"value": mandate_id}
    sql = text(
        "SELECT DISTINCT d.evidence_type FROM privacy_erasure_dispositions d "
        f"WHERE {scope} AND d.decision_status IN ({statuses}) AND d.disposition IN ({dispositions})"
    )
    try:
        rows = db.execute(sql, params).all()
    except OperationalError:
        if db.get_bind().dialect.name != "sqlite":
            raise
        return frozenset()
    return frozenset(str(row[0]) for row in rows)


# --------------------------------------------------------------------------
# Wiederanwendung nach Backup-Restore
# --------------------------------------------------------------------------

def reapply_ledger_entries(db: Session, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Stellt Vorgaenge, Sperrvermerke und Schluesselvernichtungen aus dem
    Suppression-Ledger in einer frisch wiederhergestellten DB her. Idempotent:
    bereits vorhandene ausgefuehrte Vorgaenge bleiben unveraendert."""
    summary: dict[str, Any] = {"cases_restored": [], "cases_present": [], "keys_shredded": []}
    relevant = [entry for entry in entries if entry.get("kind") in (LEDGER_KIND_CASE, LEDGER_KIND_DISPOSAL)]
    if not relevant:
        return summary
    ensure_privacy_tables(db)
    from services.pii_vault import shred_client_keys

    def _shred(client_id: str) -> None:
        if _client_row(db, client_id) is None or _keys_already_shredded(db, client_id):
            return
        shred_client_keys(db, client_id)
        summary["keys_shredded"].append(client_id)

    for entry in relevant:
        if entry["kind"] == LEDGER_KIND_CASE:
            data = entry.get("case") or {}
            case_id = data.get("id")
            if not case_id:
                continue
            case = db.get(PrivacyErasureCase, case_id)
            if case is not None and case.status in ("EXECUTED", "PARTIALLY_EXECUTED") \
                    and case.receipt_sha256 == data.get("receipt_sha256"):
                summary["cases_present"].append(case_id)
            else:
                if case is None:
                    case = PrivacyErasureCase(id=case_id)
                    db.add(case)
                for field in _CASE_LEDGER_FIELDS:
                    setattr(case, field, data.get(field))
                for line_data in entry.get("lines") or []:
                    line = db.get(PrivacyErasureDisposition, line_data.get("id"))
                    if line is None:
                        line = PrivacyErasureDisposition(id=line_data.get("id"))
                        db.add(line)
                    for field in _LINE_LEDGER_FIELDS:
                        setattr(line, field, line_data.get(field))
                summary["cases_restored"].append(case_id)
            if entry.get("keys_shredded") and data.get("client_id"):
                _shred(str(data["client_id"]))
        else:
            for line_id in entry.get("disposed_line_ids") or []:
                line = db.get(PrivacyErasureDisposition, line_id)
                if line is not None and line.decision_status != "DISPOSED":
                    line.decision_status = "DISPOSED"
                    line.disposed_at = entry.get("disposed_at")
                    line.updated_at = entry.get("disposed_at")
            for client_id in entry.get("subject_client_ids") or []:
                _shred(str(client_id))
        db.flush()
    return summary


def assert_evidence_readable(
    db: Session, *, evidence_types: Iterable[str], client_id: str | None = None, mandate_id: str | None = None,
) -> None:
    """Lese-Gate fuer Beratungs-/Analytics-Pfade: 423, wenn eine der
    Nachweisarten fuer diesen Kunden gesperrt ist (Sperrarchiv)."""
    blocked = sorted(
        set(evidence_types) & restricted_evidence_types(db, client_id=client_id, mandate_id=mandate_id)
    )
    if blocked:
        raise _error(
            423, "PRIVACY_EVIDENCE_RESTRICTED",
            "Nachweis ist nach einem Loeschgesuch gesperrt und nur fuer den festgelegten "
            f"Rechts-/Revisionszweck verfuegbar ({', '.join(blocked)})",
        )


def evidence_types_for_table(table: str) -> frozenset[str]:
    return frozenset(category.evidence_type for category in inv.categories_for(table))
