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

PRIV-003 (Codex-Audit 2026-09-07): die Kandidaten-Auswahl filterte bisher
NUR nach created_at/Tenant -- ein `Final`-Lauf (der bereits einem Kunden
vorgelegt/vertraglich relevant sein kann) wurde nach 90 Tagen genauso
geloescht wie ein `Draft`/`Superseded`-Lauf, und zwar UNABHAENGIG davon, ob
ein AdvisoryLog-Eintrag (FINMA/FIDLEG-Beratungsprotokoll, 10 Jahre
Aufbewahrung, siehe models/review.py::AdvisoryLog-Docstring) per
recommendation_run_id noch auf genau diesen Lauf zeigt. Das widerspricht der
in services/data_export.py::RETENTION_NOTES dokumentierten 10-Jahres-Frist
fuer `recommendation_runs`. Zwei zusaetzliche Ausschluss-Kriterien:
  1) result_status == 'Final' (kanonischer Wert lt. Schema-CHECK-Constraint
     in 5eyes_schema_v4.0_FINAL.sql: 'Draft'|'Final'|'Rejected'|'Superseded')
     wird NIE geloescht, unabhaengig vom Alter.
  2) Laeufe, auf die noch ein AdvisoryLog per recommendation_run_id zeigt,
     werden ebenfalls ausgenommen -- dieses Feld ist Teil des per
     advisory_log_integrity.compute_integrity_hash() hash-geschuetzten
     Beratungsprotokoll-Eintrags und damit ein aktiver Verweis, kein reines
     Nice-to-have (im Unterschied zu PortfolioHandoff.recommendation_run_id,
     das laut eigenem Modell-Docstring bewusst verwaisen darf -- siehe
     models/portfolio_handoff.py -- dessen FK wird daher vor der Loeschung
     explizit auf NULL gesetzt statt den Lauf zu schuetzen, damit dieselbe
     Absicht auch unter PRAGMA foreign_keys=ON, wie sie
     database.py::attach_sqlite_pragmas fuer die echte Tier-1-DB setzt,
     nicht zu einem IntegrityError beim Bulk-DELETE fuehrt).
  Draft/Superseded/Rejected-Laeufe ohne AdvisoryLog-Verweis werden weiterhin
  exakt wie vorher rein nach Alter geloescht (Tier-1-Normalfall unveraendert).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.clients import Client
from models.review import AdvisoryLog, RecommendationPosition, RecommendationRun

if TYPE_CHECKING:
    from models.users import User


# Default-Schwelle (Tage). Berater-relevante Empfehlungen werden in
# Compliance-Workflows mindestens fuer dieses Fenster aufbewahrt.
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 30  # Sicherheitsschwelle gegen versehentliche Massenloeschung

# PRIV-003: kanonischer Terminal-Status lt. Schema-CHECK-Constraint
# (5eyes_schema_v4.0_FINAL.sql: 'Draft'|'Final'|'Rejected'|'Superseded').
# Ein Final-Lauf wird von der altersbasierten Loeschung IMMER ausgenommen,
# unabhaengig davon ob er zusaetzlich referenziert ist.
PROTECTED_RESULT_STATUS = "Final"


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
    #
    # PRIV-003: zusaetzlich zu Alter+Tenant ausgeschlossen:
    #   - result_status == 'Final' (nie loeschbar allein durch Alter)
    #   - jeder Lauf, auf den noch ein AdvisoryLog-Eintrag per
    #     recommendation_run_id zeigt (aktiver, hash-geschuetzter Verweis
    #     im FINMA-Beratungsprotokoll -- siehe Modul-Docstring oben).
    referenced_run_ids_subquery = (
        db.query(AdvisoryLog.recommendation_run_id)
        .filter(AdvisoryLog.recommendation_run_id.isnot(None))
    )
    candidate_query = db.query(RecommendationRun.id).filter(
        RecommendationRun.created_at < cutoff_iso,
        RecommendationRun.result_status != PROTECTED_RESULT_STATUS,
        ~RecommendationRun.id.in_(referenced_run_ids_subquery),
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
        # PRIV-003: PortfolioHandoff.recommendation_run_id ist laut eigenem
        # Modell-Docstring (models/portfolio_handoff.py) ABSICHTLICH nullable
        # und darf diese Bereinigung nicht blockieren -- der Handoff traegt
        # seinen eigenen unveraenderlichen Trade-Snapshot und verliert beim
        # Cleanup nur die Provenienz-Referenz. Ohne dieses explizite
        # Vorab-Nullen wuerde der nachfolgende Bulk-DELETE unter
        # PRAGMA foreign_keys=ON (siehe database.py::attach_sqlite_pragmas,
        # in der echten Tier-1-DB aktiv) mit einem IntegrityError abbrechen,
        # sobald irgendein Handoff auf einen Loesch-Kandidaten zeigt.
        from models.portfolio_handoff import PortfolioHandoff

        (
            db.query(PortfolioHandoff)
            .filter(PortfolioHandoff.recommendation_run_id.in_(candidate_run_ids))
            .update({"recommendation_run_id": None}, synchronize_session=False)
        )
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

    # PRIV-003: vorher wurde "verbleibend" ueber `created_at >= cutoff_iso`
    # angenaehert -- das war aequivalent zu "nicht geloescht", SOLANGE jeder
    # Kandidat unterhalb des Cutoffs tatsaechlich geloescht wurde. Seit
    # Final-Status/AdvisoryLog-Referenzen Kandidaten von der Loeschung
    # ausnehmen koennen, bleiben auch manche Laeufe UNTER dem Cutoff
    # bestehen -- die Altersgrenze allein zaehlt sie im dry_run also
    # faelschlich nicht als "verbleibend". Stattdessen direkt ueber
    # candidate_run_ids ausschliessen: im dry_run (noch nicht geloescht)
    # liefert das die korrekte Vorschau; im echten Lauf sind die Kandidaten
    # ohnehin schon aus der Tabelle verschwunden, der Filter ist dann ein
    # No-op und aendert nichts am Ergebnis.
    def _remaining(query):
        scoped = _scope(query)
        if candidate_run_ids:
            scoped = scoped.filter(~RecommendationRun.id.in_(candidate_run_ids))
        return scoped

    runs_remaining = int(_remaining(db.query(func.count(RecommendationRun.id))).scalar() or 0)
    oldest_remaining_iso = _remaining(db.query(func.min(RecommendationRun.created_at))).scalar()

    return CleanupResult(
        dry_run=dry_run,
        cutoff_iso=cutoff_iso,
        retention_days=effective_days,
        deleted_runs=deleted_runs,
        deleted_positions=int(deleted_positions),
        runs_remaining=runs_remaining,
        oldest_remaining_iso=oldest_remaining_iso,
    )
