"""Sprint U-104 (2026-06-05): RecommendationRun-Lifecycle.

Loescht RecommendationRun-Zeilen (inkl. zugehoeriger RecommendationPositions)
deren created_at aelter ist als ein Schwellwert (default 90 Tage). Wird
als manueller Trigger ueber den Admin-Endpoint aufgerufen — KEIN
Auto-Cron (Anlagephilosophie: keine automatischen DB-Mutationen ohne
Berater-Trigger, ADR-003).

Sicherheits-Pattern:
  - dry_run-Default verfuegbar (Berater sieht zuerst was geloescht wuerde)
  - kein Soft-Delete: explizite physische Loeschung, da RecommendationRuns
    in AuditLog separat referenziert sind (Compliance-Trace bleibt)
  - Cascade ueber RecommendationPositions wird explizit gemacht (kein
    Vertrauen auf SQLAlchemy-relationship-cascade, da Model ohne
    cascade=delete-orphan definiert ist)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.clients import Client
from models.review import RecommendationPosition, RecommendationRun

if TYPE_CHECKING:
    from models.users import User


# Default-Schwelle (Tage). Berater-relevante Empfehlungen werden in
# Compliance-Workflows mindestens fuer dieses Fenster aufbewahrt.
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 30  # Sicherheitsschwelle gegen versehentliche Massenloeschung


@dataclass(frozen=True)
class CleanupResult:
    """Ergebnis eines Cleanup-Laufs.

    Attributes:
        dry_run: True wenn nichts wirklich geloescht wurde.
        cutoff_iso: ISO8601-Cutoff (alles aelter wurde geloescht).
        retention_days: Effektiv genutzter Schwellwert.
        deleted_runs: Anzahl der geloeschten RecommendationRun-Zeilen.
        deleted_positions: Anzahl der geloeschten RecommendationPosition-Zeilen.
        runs_remaining: Anzahl der RecommendationRuns nach dem Lauf.
        oldest_remaining_iso: created_at der aeltesten verbleibenden Zeile.
    """

    dry_run: bool
    cutoff_iso: str
    retention_days: int
    deleted_runs: int
    deleted_positions: int
    runs_remaining: int
    oldest_remaining_iso: str | None

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "cutoff_iso": self.cutoff_iso,
            "retention_days": self.retention_days,
            "deleted_runs": self.deleted_runs,
            "deleted_positions": self.deleted_positions,
            "runs_remaining": self.runs_remaining,
            "oldest_remaining_iso": self.oldest_remaining_iso,
        }


def _resolve_retention_days(retention_days: int | None) -> int:
    if retention_days is None:
        return DEFAULT_RETENTION_DAYS
    if retention_days < MIN_RETENTION_DAYS:
        raise ValueError(
            f"retention_days={retention_days} unterschreitet Mindest-Schwelle "
            f"{MIN_RETENTION_DAYS} Tage."
        )
    return int(retention_days)


def _cutoff_iso(retention_days: int, *, now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    cutoff = base - timedelta(days=retention_days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _tenant_scoped_client_ids(db: Session, current_user: "User | None") -> list[str] | None:
    """2026-07-24 (Security-Audit): liefert die Liste sichtbarer Client-IDs
    fuer den aufrufenden User, oder None wenn KEIN Filter angewendet werden
    soll (kein current_user uebergeben -- Backwards-Compat fuer bestehende
    Tests/interne Aufrufer; super_admin; oder tenant-loser Legacy-User,
    siehe services.auth._apply_tenant_filter_to_client_query fuer die exakt
    gespiegelte Konvention). None bedeutet 'kein Filter', NIE 'alles
    verstecken' -- eine leere Liste ([]) ist das korrekte Signal fuer
    'Tenant hat keine sichtbaren Clients', nicht None."""
    if current_user is None:
        return None
    if getattr(current_user, "role", None) == "super_admin":
        return None
    user_tid = getattr(current_user, "tenant_id", None)
    if not user_tid or not str(user_tid).strip():
        return None
    from services.auth import _apply_tenant_filter_to_client_query
    query = _apply_tenant_filter_to_client_query(db.query(Client.id), current_user)
    return [row[0] for row in query.all()]


def cleanup_recommendation_runs(
    db: Session,
    *,
    retention_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    current_user: "User | None" = None,
) -> CleanupResult:
    """Loescht (oder zaehlt nur, bei dry_run=True) RecommendationRuns
    aelter als retention_days.

    2026-07-24 (Security-Audit): `current_user` ist optional (Backwards-
    Compat fuer bestehende Aufrufer/Tests), aber der Endpoint MUSS ihn
    uebergeben -- ohne Tenant-Filter konnte ein tenant-gebundener (nicht
    super_admin) Admin RecommendationRun/-Position-Zeilen FREMDER Tenants
    physisch loeschen (kein Soft-Delete, kein Undo). Filter spiegelt exakt
    services.auth._apply_tenant_filter_to_client_query ueber client_id.

    Raises:
        ValueError: wenn retention_days < MIN_RETENTION_DAYS.
    """
    effective_days = _resolve_retention_days(retention_days)
    cutoff_iso = _cutoff_iso(effective_days, now=now)
    visible_client_ids = _tenant_scoped_client_ids(db, current_user)

    # 1) Eindeutige Run-IDs identifizieren — als String-Sort funktioniert
    #    ISO8601 lexikografisch (deshalb das feste Z-Suffix-Format).
    candidate_query = db.query(RecommendationRun.id).filter(
        RecommendationRun.created_at < cutoff_iso
    )
    if visible_client_ids is not None:
        candidate_query = candidate_query.filter(
            RecommendationRun.client_id.in_(visible_client_ids)
        )
    candidate_run_ids = [row[0] for row in candidate_query.all()]
    deleted_runs = len(candidate_run_ids)

    # 2) Zugehoerige Positions zaehlen (auch im dry_run, damit Berater
    #    sieht wie viele Detail-Rows mit weggehen).
    if candidate_run_ids:
        deleted_positions = (
            db.query(func.count(RecommendationPosition.id))
            .filter(RecommendationPosition.run_id.in_(candidate_run_ids))
            .scalar()
            or 0
        )
    else:
        deleted_positions = 0

    if not dry_run and candidate_run_ids:
        # Positions zuerst (FK-Constraint)
        (
            db.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id.in_(candidate_run_ids))
            .delete(synchronize_session=False)
        )
        (
            db.query(RecommendationRun)
            .filter(RecommendationRun.id.in_(candidate_run_ids))
            .delete(synchronize_session=False)
        )
        # commit wird vom Caller (Endpoint) gemacht — damit AuditLog-Write
        # in derselben Transaktion landet.

    # 2026-07-24 (Security-Audit): dieselbe Tenant-Scoping auch fuer die
    # reinen Report-Zahlen -- sonst saehe ein tenant-gebundener Admin ueber
    # 'runs_remaining'/'oldest_remaining_iso' die GESAMTZAHL/das aelteste
    # Datum quer durch ALLE Tenants (kleineres, aber reales Info-Leak).
    def _scope(query):
        if visible_client_ids is not None:
            return query.filter(RecommendationRun.client_id.in_(visible_client_ids))
        return query

    runs_remaining = (
        _scope(db.query(func.count(RecommendationRun.id)))
        .filter(RecommendationRun.created_at >= cutoff_iso)
        .scalar()
        if dry_run
        else _scope(db.query(func.count(RecommendationRun.id))).scalar()
    )
    runs_remaining = int(runs_remaining or 0)

    oldest_remaining_iso = (
        _scope(db.query(func.min(RecommendationRun.created_at)))
        .filter(RecommendationRun.created_at >= cutoff_iso)
        .scalar()
        if dry_run
        else _scope(db.query(func.min(RecommendationRun.created_at))).scalar()
    )

    return CleanupResult(
        dry_run=dry_run,
        cutoff_iso=cutoff_iso,
        retention_days=effective_days,
        deleted_runs=deleted_runs,
        deleted_positions=int(deleted_positions),
        runs_remaining=runs_remaining,
        oldest_remaining_iso=oldest_remaining_iso,
    )
