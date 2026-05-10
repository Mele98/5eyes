"""CMA-Import aus CSV (P10 Multi-Source Data Aggregator).

Wofuer: BlackRock, JP Morgan, Vanguard publizieren quartalsweise PDFs mit
ihren Capital Market Assumptions (erwartete Renditen/Vols pro Bucket).
User extrahiert die Werte manuell in eine CSV (Excel-Template) und ruft
dieses Skript, das:
  1) CSV parst
  2) jede Zeile validiert (Pflichtfelder, Plausibilitaet)
  3) optional Diff gegen aktuelles is_current=1 Set zeigt (dry-run)
  4) im Apply-Modus: vorheriges Set superseded (is_current=0) +
     neue Zeile mit is_current=1 + version+1 anlegt

CSV-Format (breit, eine Zeile = ein CMA-Set):
  assumption_set_name,valid_from,source,bonds_chf_ig_return_bps,
  bonds_chf_ig_vol_bps,...,liquidity_vol_bps,notes

Beispiel:
  'BlackRock Q2-2026',2026-04-01,'BlackRock LTCMA Q2 2026 PDF',
  220,350,...

Plausibilitaets-Grenzen (konservativ, Memory feedback_conservative_values):
  return_bps in [-5000, 5000]   (-50% bis +50% jaehrlich)
  vol_bps    in [   0, 10000]   (0% bis 100% jaehrlich)
"""
from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# Pflichtspalten und Wertebereich.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "assumption_set_name",
    "valid_from",
)

OPTIONAL_TEXT_COLUMNS: tuple[str, ...] = (
    "source",
    "notes",
    "valid_until",
)

# CMA-Felder Map: column-name in CSV == column-name in DB.
CMA_NUMERIC_COLUMNS: tuple[str, ...] = (
    "bonds_chf_ig_return_bps", "bonds_chf_ig_vol_bps",
    "bonds_fx_hedged_return_bps", "bonds_fx_hedged_vol_bps",
    "bonds_hy_return_bps", "bonds_hy_vol_bps",
    "equity_ch_return_bps", "equity_ch_vol_bps",
    "equity_intl_return_bps", "equity_intl_vol_bps",
    "equity_em_return_bps", "equity_em_vol_bps",
    "real_estate_ch_return_bps", "real_estate_ch_vol_bps",
    "alternatives_gold_return_bps", "alternatives_gold_vol_bps",
    "liquidity_return_bps", "liquidity_vol_bps",
)

# Plausibilitaets-Grenzen (bps).
RETURN_MIN_BPS, RETURN_MAX_BPS = -5000, 5000
VOL_MIN_BPS, VOL_MAX_BPS = 0, 10000


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #
@dataclass
class ImportIssue:
    """Validation- oder Apply-Problem bei einer Zeile."""
    row_index: int
    column: str | None
    message: str
    severity: str = "error"  # 'error' | 'warning'


@dataclass
class ImportRowResult:
    row_index: int
    assumption_set_name: str
    issues: list[ImportIssue] = field(default_factory=list)
    diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # column -> (old, new)
    applied: bool = False

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


@dataclass
class ImportResult:
    rows: list[ImportRowResult] = field(default_factory=list)
    dry_run: bool = True

    @property
    def has_errors(self) -> bool:
        return any(r.has_errors for r in self.rows)

    @property
    def applied_count(self) -> int:
        return sum(1 for r in self.rows if r.applied)


# --------------------------------------------------------------------------- #
# CSV-Reader
# --------------------------------------------------------------------------- #
def read_cma_csv(path: str) -> list[dict]:
    """Liest eine CSV. Whitespace wird getrimmt. Leere Zellen -> None.

    Raises FileNotFoundError / csv.Error wenn die Datei kaputt ist.
    """
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cleaned = {
                (k or "").strip(): ((v or "").strip() or None)
                for k, v in row.items() if k is not None
            }
            if not any(v for v in cleaned.values()):
                continue  # leere Zeile ueberspringen
            rows.append(cleaned)
    return rows


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_cma_row(row: dict, row_index: int) -> list[ImportIssue]:
    """Pruefe Pflichtspalten + Wertebereich. Liefert Issue-Liste."""
    issues: list[ImportIssue] = []
    for col in REQUIRED_COLUMNS:
        v = row.get(col)
        if v is None or not str(v).strip():
            issues.append(ImportIssue(row_index, col, f"Pflichtspalte '{col}' fehlt"))
    # valid_from sollte ISO sein
    if row.get("valid_from"):
        try:
            from datetime import date as Date
            Date.fromisoformat(row["valid_from"])
        except (ValueError, TypeError):
            issues.append(ImportIssue(row_index, "valid_from",
                                      f"valid_from '{row['valid_from']}' ist kein ISO-Datum"))
    # Numerische Felder: bei vorhanden -> int parsen + Range
    for col in CMA_NUMERIC_COLUMNS:
        raw = row.get(col)
        if raw is None or raw == "":
            continue
        try:
            value = int(raw)
        except (ValueError, TypeError):
            issues.append(ImportIssue(row_index, col, f"{col}='{raw}' ist kein Integer"))
            continue
        if col.endswith("_return_bps"):
            if not (RETURN_MIN_BPS <= value <= RETURN_MAX_BPS):
                issues.append(ImportIssue(
                    row_index, col,
                    f"{col}={value} ausserhalb [{RETURN_MIN_BPS},{RETURN_MAX_BPS}]",
                ))
        elif col.endswith("_vol_bps"):
            if not (VOL_MIN_BPS <= value <= VOL_MAX_BPS):
                issues.append(ImportIssue(
                    row_index, col,
                    f"{col}={value} ausserhalb [{VOL_MIN_BPS},{VOL_MAX_BPS}]",
                ))
    return issues


# --------------------------------------------------------------------------- #
# Diff
# --------------------------------------------------------------------------- #
def diff_against_current(db: Any, row: dict) -> dict[str, tuple[Any, Any]]:
    """Vergleicht row gegen aktuelles is_current=1 Set (selber Name).

    Liefert Map column -> (old_value, new_value). Wenn kein altes Set,
    liefert leer.
    """
    from models.allocation import CapitalMarketAssumption  # lazy
    name = (row.get("assumption_set_name") or "").strip()
    if not name:
        return {}
    current = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.assumption_set_name == name,
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .order_by(CapitalMarketAssumption.version.desc())
        .first()
    )
    if current is None:
        return {}
    diff: dict[str, tuple[Any, Any]] = {}
    for col in CMA_NUMERIC_COLUMNS:
        old_val = getattr(current, col, None)
        new_raw = row.get(col)
        new_val = int(new_raw) if new_raw not in (None, "") else None
        if old_val != new_val:
            diff[col] = (old_val, new_val)
    return diff


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def apply_cma_row(db: Any, row: dict, user_id: str | None) -> Any:
    """Schreibt eine neue CapitalMarketAssumption-Zeile mit is_current=1.

    Versioniert: vorheriges is_current=1 (selber Name) wird auf is_current=0
    gesetzt. version += 1.
    """
    from datetime import datetime, timezone
    from models.allocation import CapitalMarketAssumption  # lazy

    name = (row.get("assumption_set_name") or "").strip()
    if not name:
        raise ValueError("assumption_set_name darf nicht leer sein")

    prev = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.assumption_set_name == name,
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .order_by(CapitalMarketAssumption.version.desc())
        .first()
    )
    new_version = (int(prev.version) + 1) if prev is not None else 1
    if prev is not None:
        prev.is_current = 0

    def _opt_int(v: Any) -> int | None:
        return int(v) if v not in (None, "") else None

    now_iso = datetime.now(timezone.utc).isoformat()
    entry_kwargs: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "assumption_set_name": name,
        "version": new_version,
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "is_current": 1,
        "source": row.get("source") or "csv-import",
        "notes": row.get("notes"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    if user_id:
        entry_kwargs["created_by"] = user_id
    for col in CMA_NUMERIC_COLUMNS:
        entry_kwargs[col] = _opt_int(row.get(col))

    entry = CapitalMarketAssumption(**entry_kwargs)
    db.add(entry)
    return entry


# --------------------------------------------------------------------------- #
# Top-Level Importer
# --------------------------------------------------------------------------- #
def import_cma_csv(
    db: Any,
    path: str,
    user_id: str | None = None,
    dry_run: bool = True,
) -> ImportResult:
    """End-to-End: CSV lesen -> validieren -> diff -> (apply wenn nicht dry-run).

    Bei Validation-Errors in einer Zeile wird sie NICHT applied (auch wenn
    dry_run=False). Andere Zeilen werden trotzdem applied (best-effort).
    """
    result = ImportResult(dry_run=dry_run)
    rows = read_cma_csv(path)
    for idx, row in enumerate(rows, start=1):
        row_result = ImportRowResult(
            row_index=idx,
            assumption_set_name=(row.get("assumption_set_name") or "").strip(),
        )
        # Validation
        row_result.issues = validate_cma_row(row, idx)
        # Diff (auch bei dry_run)
        try:
            row_result.diff = diff_against_current(db, row)
        except Exception as exc:  # noqa: BLE001
            row_result.issues.append(ImportIssue(idx, None, f"diff failed: {exc}", "warning"))
        # Apply
        if not row_result.has_errors and not dry_run:
            try:
                apply_cma_row(db, row, user_id)
                row_result.applied = True
            except Exception as exc:  # noqa: BLE001
                row_result.issues.append(ImportIssue(idx, None, f"apply failed: {exc}"))
        result.rows.append(row_result)
    if not dry_run:
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("import_cma_csv: commit failed (%s)", exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return result
