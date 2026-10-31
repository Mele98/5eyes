"""CMA_POLICY-Workflow: Lebenszyklus, Vier-Augen-Freigabe, Finalisierungs-Gate.

CMA-001 (Entscheidungsdokument 2026-10-27, Abschnitt 5, Paragraf 7.4).
Status des Dokuments: RECOMMENDED_PENDING_OWNER_LEGAL_AND_COMMITTEE_APPROVAL
-- dieses Modul liefert Schema, Workflow und Gate, KEINE fachliche Freigabe
und KEINE Werte.

Lebenszyklus
------------
``DRAFT -> VALIDATED -> APPROVED -> ACTIVE -> RETIRED`` bzw. ``REVOKED``
(Widerruf aus VALIDATED/APPROVED/ACTIVE).

* Inhalt und Komponenten sind nur im ``DRAFT`` aenderbar.
* ``validate`` prueft Vollstaendigkeit/Domaene und friert den Inhalt per
  ``content_hash`` ein.
* ``approve`` verlangt eine natuerliche Person, die weder Ersteller noch
  bereits Freigeber ist (kein Self-Approval); nach der zweiten
  unabhaengigen Freigabe ist die Version ``APPROVED``. Jede Freigabe
  speichert den Hash, den sie gesehen hat (append-only).
* ``activate`` prueft, dass Inhalt und alle Freigaben hashgleich sind und
  die Gueltigkeit den Aktivierungstag abdeckt; die bisher aktive Version
  derselben ``policy_id`` wird ``RETIRED``.
* Korrektur = neue Version (``supersedes_id``); Rollback = neue Version
  mit unveraendert uebernommenem Inhalt einer frueheren Version, die den
  vollen Zyklus inkl. zwei neuer Freigaben durchlaeuft. Eine einmal
  genehmigte Version wird nie ueberschrieben.

Aktivierung des Modells
-----------------------
Das Gate fuer neue Finalisierungen ist erst scharf, sobald irgendeine
Policy jemals aktiviert wurde (``activated_at`` gesetzt). Bis zur
Ausschussfreigabe existiert das Modell, blockiert aber nichts -- die
Aktivierung erfolgt ausschliesslich ueber den Policy-Status, nie ueber
eine Code-Konstante. Danach blockieren fehlende, abgelaufene, nicht
aktive oder hash-inkonsistente Policies jede neue Finalisierung;
abgeschlossene Beratungen bleiben ueber ``recommendation_runs.
cma_policy_row_id`` an ihre damalige Policy gebunden.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from core.evidence import evidence_hash
from database import new_uuid
from models.cma_policy import CmaPolicy, CmaPolicyApproval, CmaPolicyComponent

STATUS_DRAFT = "DRAFT"
STATUS_VALIDATED = "VALIDATED"
STATUS_APPROVED = "APPROVED"
STATUS_ACTIVE = "ACTIVE"
STATUS_RETIRED = "RETIRED"
STATUS_REVOKED = "REVOKED"
STATUSES = (
    STATUS_DRAFT, STATUS_VALIDATED, STATUS_APPROVED,
    STATUS_ACTIVE, STATUS_RETIRED, STATUS_REVOKED,
)

REQUIRED_APPROVALS = 2

#: Komponentenledger je Renditeannahme (Entscheidungsdokument, ADR-12a-Hold).
COMPONENTS = (
    "risk_free",
    "erp",
    "valuation_adjustment",
    "credit_carry",
    "default_loss",
    "fx",
    "fees",
)
RETURN_BASES = ("nominal", "real")
FEE_BASES = ("gross", "net")
SIGNS = ("positive", "negative", "either")
COMPONENT_UNITS = ("bps_pa",)

# Reason-Codes des Finalisierungs-Gates.
CMA_POLICY_MISSING = "CMA_POLICY_MISSING"
CMA_POLICY_NOT_ACTIVE = "CMA_POLICY_NOT_ACTIVE"
CMA_POLICY_EXPIRED = "CMA_POLICY_EXPIRED"
CMA_POLICY_INTEGRITY = "CMA_POLICY_INTEGRITY"

_CONTENT_FIELDS = (
    "policy_id",
    "version",
    "capital_market_assumptions_id",
    "correlation_policy_ref",
    "valid_from",
    "valid_until",
    "data_as_of",
    "base_currency",
    "return_basis",
    "fee_basis",
    "method_version",
    "sources_json",
    "rationale",
    "impact_report_ref",
    "supersedes_id",
    "expiry_rule",
    "exception_rule",
    "rollback_rule",
)
_COMPONENT_FIELDS = (
    "asset_key",
    "component",
    "value_bps",
    "unit",
    "horizon_years",
    "method",
    "source",
    "sign",
    "confidence",
    "range_min_bps",
    "range_max_bps",
)
_EDITABLE_FIELDS = tuple(
    f for f in _CONTENT_FIELDS if f not in ("policy_id", "version")
)
# Plausibilitaetsschranke wie services/cma_validation.py::RUNTIME_RETURN_MAX_BPS
# (Tippfehler-Schutz, kein Fachwert).
_COMPONENT_ABS_MAX_BPS = 10_000


class CmaPolicyError(ValueError):
    """Ungueltiger Inhalt (Router: 422)."""


class CmaPolicyConflict(Exception):
    """Unzulaessiger Zustandsuebergang oder Vier-Augen-Verstoss (Router: 409)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise CmaPolicyError(f"{field} ist kein ISO-Datum.") from exc


def components_of(db: Session, policy: CmaPolicy) -> list[CmaPolicyComponent]:
    return (
        db.query(CmaPolicyComponent)
        .filter(CmaPolicyComponent.policy_row_id == policy.id)
        .order_by(CmaPolicyComponent.asset_key, CmaPolicyComponent.component)
        .all()
    )


def approvals_of(db: Session, policy: CmaPolicy) -> list[CmaPolicyApproval]:
    return (
        db.query(CmaPolicyApproval)
        .filter(CmaPolicyApproval.policy_row_id == policy.id)
        .order_by(CmaPolicyApproval.approved_at)
        .all()
    )


def compute_content_hash(
    policy: CmaPolicy, components: Iterable[CmaPolicyComponent]
) -> str:
    payload = {
        "policy": {field: getattr(policy, field, None) for field in _CONTENT_FIELDS},
        "components": sorted(
            (
                {field: getattr(row, field, None) for field in _COMPONENT_FIELDS}
                for row in components
            ),
            key=lambda row: (row["asset_key"], row["component"]),
        ),
    }
    return evidence_hash(payload)


def _require_status(policy: CmaPolicy, *allowed: str) -> None:
    if policy.status not in allowed:
        raise CmaPolicyConflict(
            f"Policy {policy.policy_id} v{policy.version} ist {policy.status}; "
            f"erlaubt: {', '.join(allowed)}."
        )


def _validate_sources(raw: Any) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise CmaPolicyError("sources_json ist kein JSON.") from exc
    if not isinstance(raw, list) or not raw:
        raise CmaPolicyError("sources_json muss mindestens eine Quelle enthalten.")
    for entry in raw:
        if not isinstance(entry, dict) or not str(entry.get("source") or "").strip():
            raise CmaPolicyError("Jede Quelle braucht ein Feld 'source'.")
        if not str(entry.get("digest") or "").strip():
            raise CmaPolicyError(
                "Jede Quelle braucht einen Daten-/Datei-Digest ('digest')."
            )
    return json.dumps(raw, sort_keys=True, ensure_ascii=False)


def create_draft(db: Session, actor_id: str, data: dict) -> CmaPolicy:
    """Neue Version (DRAFT) einer Policy. Version = bisheriges Maximum + 1."""
    from models.allocation import CapitalMarketAssumption

    policy_id = str(data.get("policy_id") or "").strip()
    if not policy_id:
        raise CmaPolicyError("policy_id fehlt.")
    cma_id = data.get("capital_market_assumptions_id")
    if not cma_id or db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == cma_id
    ).first() is None:
        raise CmaPolicyError("capital_market_assumptions_id verweist auf keine CMA.")
    supersedes_id = data.get("supersedes_id")
    if supersedes_id:
        previous = db.query(CmaPolicy).filter(CmaPolicy.id == supersedes_id).first()
        if previous is None or previous.policy_id != policy_id:
            raise CmaPolicyError(
                "supersedes_id muss eine Version derselben policy_id sein."
            )
    latest = (
        db.query(CmaPolicy.version)
        .filter(CmaPolicy.policy_id == policy_id)
        .order_by(CmaPolicy.version.desc())
        .first()
    )
    now = _now()
    policy = CmaPolicy(
        id=new_uuid(),
        policy_id=policy_id,
        version=(int(latest[0]) + 1) if latest else 1,
        status=STATUS_DRAFT,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    for field in _EDITABLE_FIELDS:
        if field in data:
            setattr(policy, field, data[field])
    if "sources_json" in data:
        policy.sources_json = _validate_sources(data["sources_json"])
    db.add(policy)
    db.flush()
    if "components" in data:
        replace_components(db, policy, data["components"])
    return policy


def replace_components(
    db: Session, policy: CmaPolicy, components: Iterable[dict]
) -> list[CmaPolicyComponent]:
    _require_status(policy, STATUS_DRAFT)
    rows = list(components or [])
    keys = [(str(c.get("asset_key")), str(c.get("component"))) for c in rows]
    if len(keys) != len(set(keys)):
        raise CmaPolicyError(
            "Jede Komponente darf je Anlage nur einmal vorkommen (keine Doppelanwendung)."
        )
    db.query(CmaPolicyComponent).filter(
        CmaPolicyComponent.policy_row_id == policy.id
    ).delete()
    now = _now()
    created = []
    for entry in rows:
        row = CmaPolicyComponent(
            id=new_uuid(), policy_row_id=policy.id, created_at=now,
            **{field: entry.get(field) for field in _COMPONENT_FIELDS},
        )
        db.add(row)
        created.append(row)
    policy.updated_at = now
    db.flush()
    return created


def _check_component(row: CmaPolicyComponent) -> None:
    label = f"{row.asset_key}/{row.component}"
    if not str(row.asset_key or "").strip():
        raise CmaPolicyError("Komponente ohne asset_key.")
    if row.component not in COMPONENTS:
        raise CmaPolicyError(f"{label}: unbekannte Komponente.")
    if row.unit not in COMPONENT_UNITS:
        raise CmaPolicyError(f"{label}: Einheit muss {COMPONENT_UNITS} sein.")
    if row.sign not in SIGNS:
        raise CmaPolicyError(f"{label}: Vorzeichen muss {SIGNS} sein.")
    for field in ("method", "source"):
        if not str(getattr(row, field) or "").strip():
            raise CmaPolicyError(f"{label}: {field} fehlt.")
    try:
        value = int(row.value_bps)
        low = int(row.range_min_bps)
        high = int(row.range_max_bps)
        horizon = int(row.horizon_years)
    except (TypeError, ValueError) as exc:
        raise CmaPolicyError(f"{label}: Wert/Bereich/Horizont fehlen.") from exc
    if horizon < 1:
        raise CmaPolicyError(f"{label}: horizon_years muss >= 1 sein.")
    if not low <= value <= high:
        raise CmaPolicyError(f"{label}: Wert liegt nicht im zulaessigen Bereich.")
    if max(abs(low), abs(high)) > _COMPONENT_ABS_MAX_BPS:
        raise CmaPolicyError(f"{label}: Bereich unplausibel (> {_COMPONENT_ABS_MAX_BPS} bps).")
    if row.sign == "positive" and value < 0 or row.sign == "negative" and value > 0:
        raise CmaPolicyError(f"{label}: Wert widerspricht dem Vorzeichen.")


def validate_policy(db: Session, policy: CmaPolicy, actor_id: str) -> CmaPolicy:
    _require_status(policy, STATUS_DRAFT)
    for field in (
        "valid_from", "data_as_of", "base_currency", "return_basis",
        "fee_basis", "method_version", "sources_json", "rationale",
    ):
        if not str(getattr(policy, field) or "").strip():
            raise CmaPolicyError(f"{field} fehlt.")
    if policy.return_basis not in RETURN_BASES:
        raise CmaPolicyError(f"return_basis muss {RETURN_BASES} sein.")
    if policy.fee_basis not in FEE_BASES:
        raise CmaPolicyError(f"fee_basis muss {FEE_BASES} sein.")
    valid_from = _parse_date(policy.valid_from, "valid_from")
    _parse_date(policy.data_as_of, "data_as_of")
    if policy.valid_until:
        if _parse_date(policy.valid_until, "valid_until") < valid_from:
            raise CmaPolicyError("valid_until liegt vor valid_from.")
    _validate_sources(policy.sources_json)
    components = components_of(db, policy)
    if not components:
        raise CmaPolicyError("Die Policy hat kein Komponentenledger.")
    for row in components:
        _check_component(row)
    policy.content_hash = compute_content_hash(policy, components)
    policy.status = STATUS_VALIDATED
    policy.validated_by = actor_id
    policy.validated_at = _now()
    policy.updated_at = policy.validated_at
    db.flush()
    return policy


def approve_policy(
    db: Session, policy: CmaPolicy, approver_id: str, rationale: str
) -> CmaPolicyApproval:
    _require_status(policy, STATUS_VALIDATED)
    if not str(rationale or "").strip():
        raise CmaPolicyError("Eine Freigabe braucht eine Begruendung.")
    if approver_id == policy.created_by:
        raise CmaPolicyConflict(
            "Vier-Augen-Prinzip: der Ersteller darf seine Policy nicht freigeben."
        )
    existing = approvals_of(db, policy)
    if any(row.approver_id == approver_id for row in existing):
        raise CmaPolicyConflict(
            "Vier-Augen-Prinzip: dieselbe Person kann nur einmal freigeben."
        )
    current_hash = compute_content_hash(policy, components_of(db, policy))
    if current_hash != policy.content_hash:
        raise CmaPolicyConflict("Inhalt weicht vom validierten Stand ab.")
    approval = CmaPolicyApproval(
        id=new_uuid(),
        policy_row_id=policy.id,
        approver_id=approver_id,
        approved_at=_now(),
        rationale=str(rationale).strip(),
        content_hash=current_hash,
    )
    db.add(approval)
    if len(existing) + 1 >= REQUIRED_APPROVALS:
        policy.status = STATUS_APPROVED
        policy.approved_at = approval.approved_at
    policy.updated_at = approval.approved_at
    db.flush()
    return approval


def integrity_errors(db: Session, policy: CmaPolicy) -> list[str]:
    """Leere Liste = Inhalt, Validierung und Freigaben sind hashgleich."""
    errors: list[str] = []
    current_hash = compute_content_hash(policy, components_of(db, policy))
    if not policy.content_hash or current_hash != policy.content_hash:
        errors.append("Inhalt weicht vom validierten Hash ab.")
    approvals = approvals_of(db, policy)
    approvers = {row.approver_id for row in approvals}
    if len(approvers) < REQUIRED_APPROVALS:
        errors.append("Weniger als zwei unabhaengige Freigaben.")
    if policy.created_by in approvers:
        errors.append("Self-Approval durch den Ersteller.")
    if any(row.content_hash != current_hash for row in approvals):
        errors.append("Eine Freigabe bezieht sich auf einen anderen Inhalt.")
    return errors


def _covers(policy: CmaPolicy, on: date) -> bool:
    if _parse_date(policy.valid_from, "valid_from") > on:
        return False
    if policy.valid_until and _parse_date(policy.valid_until, "valid_until") < on:
        return False
    return True


def activate_policy(
    db: Session, policy: CmaPolicy, actor_id: str, *, today: Optional[date] = None
) -> CmaPolicy:
    _require_status(policy, STATUS_APPROVED)
    errors = integrity_errors(db, policy)
    if errors:
        raise CmaPolicyConflict("; ".join(errors))
    today = today or date.today()
    if not _covers(policy, today):
        raise CmaPolicyConflict("Die Gueltigkeit deckt den Aktivierungstag nicht ab.")
    now = _now()
    previous = (
        db.query(CmaPolicy)
        .filter(
            CmaPolicy.policy_id == policy.policy_id,
            CmaPolicy.status == STATUS_ACTIVE,
            CmaPolicy.id != policy.id,
        )
        .with_for_update()
        .all()
    )
    for row in previous:
        row.status = STATUS_RETIRED
        row.retired_at = now
        row.updated_at = now
    policy.status = STATUS_ACTIVE
    policy.activated_by = actor_id
    policy.activated_at = now
    policy.updated_at = now
    db.flush()
    return policy


def retire_policy(db: Session, policy: CmaPolicy) -> CmaPolicy:
    _require_status(policy, STATUS_ACTIVE)
    policy.status = STATUS_RETIRED
    policy.retired_at = _now()
    policy.updated_at = policy.retired_at
    db.flush()
    return policy


def revoke_policy(
    db: Session, policy: CmaPolicy, actor_id: str, reason: str
) -> CmaPolicy:
    _require_status(policy, STATUS_VALIDATED, STATUS_APPROVED, STATUS_ACTIVE)
    if not str(reason or "").strip():
        raise CmaPolicyError("Ein Widerruf braucht eine Begruendung.")
    policy.status = STATUS_REVOKED
    policy.revoked_by = actor_id
    policy.revoked_at = _now()
    policy.revocation_reason = str(reason).strip()
    policy.updated_at = policy.revoked_at
    db.flush()
    return policy


# ---------------------------------------------------------------------------
# Finalisierungs-Gate
# ---------------------------------------------------------------------------


def policy_model_enforced(db: Session) -> bool:
    """Scharf, sobald je eine Policy aktiviert wurde (Status, keine Konstante)."""
    return (
        db.query(CmaPolicy.id).filter(CmaPolicy.activated_at.isnot(None)).first()
        is not None
    )


def finalization_policy_check(
    db: Session, cma_id: Optional[str], *, today: Optional[date] = None
) -> tuple[Optional[CmaPolicy], Optional[tuple[str, str]]]:
    """``(policy, None)`` = freigegeben; ``(None, (reason_code, message))`` =
    blockiert; ``(None, None)`` = Modell noch nicht aktiv geschaltet."""
    if not policy_model_enforced(db):
        return None, None
    today = today or date.today()
    rows = (
        db.query(CmaPolicy)
        .filter(CmaPolicy.capital_market_assumptions_id == cma_id)
        .all()
        if cma_id
        else []
    )
    if not rows:
        return None, (
            CMA_POLICY_MISSING,
            "Für die Kapitalmarktannahmen dieser Empfehlung existiert keine "
            "genehmigte CMA-Policy; neue Finalisierungen sind gesperrt.",
        )
    active = [row for row in rows if row.status == STATUS_ACTIVE]
    if not active:
        return None, (
            CMA_POLICY_NOT_ACTIVE,
            "Die CMA-Policy dieser Kapitalmarktannahmen ist nicht aktiv "
            "(Entwurf, nur validiert/genehmigt, abgelöst oder widerrufen).",
        )
    policy = active[0]
    if not _covers(policy, today):
        return None, (
            CMA_POLICY_EXPIRED,
            "Die aktive CMA-Policy ist abgelaufen oder noch nicht gültig.",
        )
    errors = integrity_errors(db, policy)
    if errors:
        return None, (
            CMA_POLICY_INTEGRITY,
            "Die aktive CMA-Policy ist nicht integer: " + "; ".join(errors),
        )
    return policy, None
