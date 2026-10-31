"""Versionierte Policy fuer Depot-Frische und Vermoegensabgleich (PORTFOLIO-DATA-001).

Die Schwellen (Frische in Bankarbeitstagen, Rundungsrest) sind Policy-Daten in
``config/portfolio_data_policy.json`` und keine Code-Konstanten. Die dort
hinterlegte Version hat den Status ``PROPOSED``: sie stammt aus der Empfehlung
vom 2026-10-27 (Abschnitt 6) und ist weder fachlich noch rechtlich freigegeben.

Aktiv (``is_active``) ist eine Policy nur mit Status ``APPROVED`` und einer
Freigabe je geforderter Rolle (Investment, Compliance, Operations) durch
verschiedene Personen mit Datum und Referenz. Nur eine aktive Policy darf
Finalisierung, PDF, Signatur oder Handoff blockieren. Jede andere Policy
liefert dieselbe Auswertung, aber nur als sichtbare Warnung
(``evaluate_portfolio_data_gate``: ``enforced`` False, ``would_block`` sichtbar).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from services.bank_calendar import BankCalendar, calendar_for_id

POLICY_SCHEMA = "ares.portfolio-data-policy/v1"

STATUS_DRAFT = "DRAFT"
STATUS_PROPOSED = "PROPOSED"
STATUS_APPROVED = "APPROVED"
STATUS_RETIRED = "RETIRED"
POLICY_STATUSES = (STATUS_DRAFT, STATUS_PROPOSED, STATUS_APPROVED, STATUS_RETIRED)

FRESHNESS_COMPONENTS = (
    "holdings_as_of",
    "cash_as_of",
    "price_as_of",
    "fx_as_of",
    "corporate_actions_checked_at",
)

ACTION_DRAFT = "draft"
FINAL_ACTIONS = ("finalize", "pdf", "signature", "handoff")
GATE_ACTIONS = (ACTION_DRAFT, *FINAL_ACTIONS)

_TOP_KEYS = {
    "schema", "policy_id", "version", "status", "status_note",
    "required_approver_roles", "approvals", "calendar", "freshness", "reconciliation",
}
_APPROVAL_KEYS = {"role", "approved_by", "approved_at", "reference"}


class PortfolioDataPolicyError(ValueError):
    """Policy-Datei fehlt, ist ungueltig oder widerspruechlich."""


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "portfolio_data_policy.json"


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _non_negative_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PortfolioDataPolicyError(f"{name} muss eine ganze Zahl >= 0 sein.")
    return value


def _non_empty_str(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioDataPolicyError(f"{name} fehlt.")
    return value.strip()


@dataclass(frozen=True)
class PortfolioDataPolicy:
    policy_id: str
    version: str
    status: str
    status_note: str
    required_approver_roles: tuple[str, ...]
    approvals: tuple[dict, ...]
    calendar_id: str
    timezone: str
    required_components: tuple[str, ...]
    final_max_business_days: int
    draft_max_business_days: int
    per_position_tolerance_minor_units: int
    aggregate_tolerance_major_units: int
    policy_hash: str

    @property
    def is_active(self) -> bool:
        if self.status != STATUS_APPROVED:
            return False
        approved_roles = {a["role"] for a in self.approvals}
        approvers = [a["approved_by"] for a in self.approvals]
        return (
            set(self.required_approver_roles) <= approved_roles
            and len(approvers) == len(set(approvers))
        )

    def calendar(self) -> BankCalendar:
        return calendar_for_id(self.calendar_id)

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def summary(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "status": self.status,
            "active": self.is_active,
            "policy_hash": self.policy_hash,
            "status_note": self.status_note,
        }


def parse_portfolio_data_policy(data) -> PortfolioDataPolicy:
    """Validiert ein Policy-Dokument streng; jeder Fehler -> ``PortfolioDataPolicyError``."""
    if not isinstance(data, dict):
        raise PortfolioDataPolicyError("Policy muss ein Objekt sein.")
    if set(data) != _TOP_KEYS:
        raise PortfolioDataPolicyError("Policy hat unerwartete oder fehlende Felder.")
    if data["schema"] != POLICY_SCHEMA:
        raise PortfolioDataPolicyError("Policy hat ein unbekanntes Schema.")
    status = data["status"]
    if status not in POLICY_STATUSES:
        raise PortfolioDataPolicyError(f"Unbekannter Policy-Status: {status!r}")

    roles = data["required_approver_roles"]
    if not isinstance(roles, list) or not roles or len(set(roles)) != len(roles):
        raise PortfolioDataPolicyError("required_approver_roles muss eine nicht leere Liste ohne Duplikate sein.")
    roles = tuple(_non_empty_str(r, "required_approver_roles[]") for r in roles)

    approvals = data["approvals"]
    if not isinstance(approvals, list):
        raise PortfolioDataPolicyError("approvals muss eine Liste sein.")
    parsed_approvals = []
    for entry in approvals:
        if not isinstance(entry, dict) or set(entry) != _APPROVAL_KEYS:
            raise PortfolioDataPolicyError("Freigabe braucht genau role, approved_by, approved_at, reference.")
        parsed = {key: _non_empty_str(entry[key], f"approvals[].{key}") for key in sorted(_APPROVAL_KEYS)}
        if parsed["role"] not in roles:
            raise PortfolioDataPolicyError(f"Freigabe fuer nicht geforderte Rolle {parsed['role']!r}.")
        parsed_approvals.append(parsed)
    if status != STATUS_APPROVED and parsed_approvals:
        raise PortfolioDataPolicyError("Freigaben sind nur bei Status APPROVED zulaessig.")

    calendar = data["calendar"]
    if not isinstance(calendar, dict) or set(calendar) != {"calendar_id", "timezone"}:
        raise PortfolioDataPolicyError("calendar braucht genau calendar_id und timezone.")
    calendar_id = _non_empty_str(calendar["calendar_id"], "calendar.calendar_id")
    timezone = _non_empty_str(calendar["timezone"], "calendar.timezone")
    try:
        calendar_for_id(calendar_id)
        ZoneInfo(timezone)
    except Exception as exc:  # noqa: BLE001 - jede Fehlkonfiguration ist ein Policy-Fehler
        raise PortfolioDataPolicyError(f"Kalender/Zeitzone ungueltig: {exc}") from exc

    freshness = data["freshness"]
    if not isinstance(freshness, dict) or set(freshness) != {
        "required_components", "final_max_business_days", "draft_max_business_days",
    }:
        raise PortfolioDataPolicyError("freshness hat unerwartete oder fehlende Felder.")
    components = freshness["required_components"]
    if (
        not isinstance(components, list)
        or not components
        or len(set(components)) != len(components)
        or not set(components) <= set(FRESHNESS_COMPONENTS)
    ):
        raise PortfolioDataPolicyError("freshness.required_components ist ungueltig.")
    final_max = _non_negative_int(freshness["final_max_business_days"], "final_max_business_days")
    draft_max = _non_negative_int(freshness["draft_max_business_days"], "draft_max_business_days")
    if draft_max < final_max:
        raise PortfolioDataPolicyError("draft_max_business_days darf nicht kleiner als final_max_business_days sein.")

    recon = data["reconciliation"]
    if not isinstance(recon, dict) or set(recon) != {
        "per_position_tolerance_minor_units", "aggregate_tolerance_major_units",
    }:
        raise PortfolioDataPolicyError("reconciliation hat unerwartete oder fehlende Felder.")

    return PortfolioDataPolicy(
        policy_id=_non_empty_str(data["policy_id"], "policy_id"),
        version=_non_empty_str(data["version"], "version"),
        status=status,
        status_note=_non_empty_str(data["status_note"], "status_note"),
        required_approver_roles=roles,
        approvals=tuple(parsed_approvals),
        calendar_id=calendar_id,
        timezone=timezone,
        required_components=tuple(components),
        final_max_business_days=final_max,
        draft_max_business_days=draft_max,
        per_position_tolerance_minor_units=_non_negative_int(
            recon["per_position_tolerance_minor_units"], "per_position_tolerance_minor_units",
        ),
        aggregate_tolerance_major_units=_non_negative_int(
            recon["aggregate_tolerance_major_units"], "aggregate_tolerance_major_units",
        ),
        policy_hash=hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest(),
    )


def load_portfolio_data_policy(path: Path | None = None) -> PortfolioDataPolicy:
    """Laedt die Policy-Datei; fehlend oder ungueltig -> ``PortfolioDataPolicyError``."""
    path = path or _default_policy_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PortfolioDataPolicyError(f"Policy-Datei nicht lesbar: {path.name}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PortfolioDataPolicyError("Policy-Datei ist kein gueltiges JSON.") from exc
    return parse_portfolio_data_policy(data)


_POLICY_NOT_ACTIVE_WARNING = (
    "Depot-Policy {version} hat Status {status} und ist nicht freigegeben: "
    "die Pruefung wird nur angezeigt und blockiert nichts."
)


def evaluate_portfolio_data_gate(
    policy: PortfolioDataPolicy | None,
    *,
    action: str,
    freshness: dict | None,
    reconciliation: dict | None,
    policy_error: str | None = None,
) -> dict:
    """Entscheid fuer eine Aktion (Entwurf oder Finalisierung/PDF/Signatur/Handoff).

    ``would_block`` ist die fachliche Auswertung, ``blocked`` die Wirkung:
    blockiert wird nur mit aktiver Policy. Ohne aktive Policy (PROPOSED,
    DRAFT, RETIRED, nicht ladbar) bleibt es bei sichtbaren Warnungen.
    """
    if action not in GATE_ACTIONS:
        raise ValueError(f"Unbekannte Aktion: {action!r}")
    reasons: list[str] = []
    final = action in FINAL_ACTIONS

    if freshness is None:
        reasons.append("freshness_not_evaluated")
    else:
        usability = freshness.get("usability")
        if usability == "blocked":
            reasons.append("freshness_blocked")
        elif final and usability != "final":
            reasons.append("freshness_draft_only")
    if final:
        if reconciliation is None:
            reasons.append("reconciliation_not_evaluated")
        elif reconciliation.get("status") != "reconciled":
            reasons.append("reconciliation_unexplained_difference")

    warnings: list[str] = []
    if policy is None:
        enforced = False
        warnings.append(
            "Depot-Policy nicht ladbar"
            + (f" ({policy_error})" if policy_error else "")
            + ": die Pruefung wird nur angezeigt und blockiert nichts."
        )
        policy_summary = None
    else:
        enforced = policy.is_active
        policy_summary = policy.summary()
        if not enforced:
            warnings.append(_POLICY_NOT_ACTIVE_WARNING.format(version=policy.version, status=policy.status))
    if freshness and freshness.get("usability") == "draft":
        warnings.append("Depotdaten veraltet: nur Entwurf/Szenario, keine Finalisierung oder Signatur.")
    for note in (freshness or {}).get("calendar_notes", []):
        warnings.append(note)

    would_block = bool(reasons)
    return {
        "action": action,
        "policy": policy_summary,
        "enforced": enforced,
        "would_block": would_block,
        "blocked": enforced and would_block,
        "reasons": reasons,
        "warnings": warnings,
    }
