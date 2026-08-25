"""CLI: CMA-Werte aus CSV in die DB importieren.

Workflow:
  1) User legt 'cma_q2_2026.csv' an (siehe docs/cma_import_workflow.md).
  2) Dry-Run:  python scripts/import_cma_from_csv.py cma_q2_2026.csv
  3) Apply:    python scripts/import_cma_from_csv.py cma_q2_2026.csv --apply

CSV-Format (Spaltennamen exakt wie unten):
  assumption_set_name,valid_from,source,bonds_chf_ig_return_bps,
  bonds_chf_ig_vol_bps,...,liquidity_vol_bps,notes

Werte:
  return_bps in [-5000, 5000]  (50% jaehrlich Min/Max)
  vol_bps    in [    0, 10000] (0% bis 100% jaehrlich)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    here = Path(__file__).resolve()
    backend = here.parent.parent / "5eyes-backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def main() -> int:
    _ensure_backend_on_path()

    parser = argparse.ArgumentParser(description="Import CMA-Werte aus CSV.")
    parser.add_argument("csv_path", help="Pfad zur CSV-Datei")
    parser.add_argument("--apply", action="store_true",
                        help="Aenderungen in DB schreiben (sonst Dry-Run)")
    parser.add_argument("--user-id", default=None,
                        help="User-ID fuer created_by (optional)")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"FEHLER: Datei nicht gefunden: {csv_path}", file=sys.stderr)
        return 2

    # Imports nach _ensure_backend_on_path
    from database import SessionLocal  # type: ignore[import-not-found]
    from services.cma_import import import_cma_csv  # type: ignore[import-not-found]

    db = SessionLocal()
    try:
        result = import_cma_csv(
            db=db,
            path=str(csv_path),
            user_id=args.user_id,
            dry_run=not args.apply,
        )
    finally:
        db.close()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== CMA-Import {mode} ===")
    print(f"Zeilen: {len(result.rows)}")
    error_count = sum(1 for r in result.rows if r.has_errors)
    print(f"Fehlerhafte Zeilen: {error_count}")
    print(f"Angewendet: {result.applied_count}")
    print()
    for row in result.rows:
        print(f"--- Zeile {row.row_index}: '{row.assumption_set_name}' ---")
        if row.issues:
            for issue in row.issues:
                col = f" [{issue.column}]" if issue.column else ""
                print(f"  {issue.severity.upper()}{col}: {issue.message}")
        if row.diff:
            print("  Aenderungen:")
            for col, (old, new) in sorted(row.diff.items()):
                print(f"    {col}: {old} -> {new}")
        else:
            if not row.has_errors:
                print("  (keine Aenderungen gegen aktuelles is_current=1 Set)")
        if row.applied:
            print("  -> APPLIED")
    print()
    if not args.apply and not result.has_errors:
        print("Hinweis: Dry-Run OK. Mit --apply ausfuehren zum Schreiben.")
    return 0 if not result.has_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
