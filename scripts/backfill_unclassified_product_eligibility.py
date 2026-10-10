"""CLI: Produkte ohne JEDE Suitability-Historie (weder ProductSuitability
noch governed ProductEligibilityRule) sicher nachklassifizieren
(CERT-PRODUCT-ELIGIBILITY-001, Befund C: Custom-/Tenant-Produkte und
Nicht-CH-Jurisdiktionen, die nie durch ensure_default_products() oder die
Legacy-Migration liefen).

Governance-Entscheidung des Users (2026-10-09, Befund C: "Beides
(migrieren + Pflichtfeld bauen)") -- dieses Skript deckt den "migrieren"-
Teil ab; der "Pflichtfeld"-Teil ist bereits in routers/review.py::
create_product() (ProductCreate.suitability_*) umgesetzt, gilt aber nur fuer
NEU erfasste Produkte ab jetzt. Dieses Skript holt die VORHER erfassten
nach.

Nur sicher klassifizierbare Produkte (einfache Aktien/Obligationen/
Immobilien-Instrumente plus eine kleine, namentlich bekannte Alternative-/
Liquiditaets-Liste) werden automatisch eingestuft -- mit demselben
Risikoband, das der Firmen-Default-Katalog schon immer verwendet. Alles
andere (strukturiert/derivativ/gehebelt, unbekannte Alternative-/
Liquiditaets-Kategorien) wird in Quarantaene gemeldet, nie automatisch
geraten -- siehe services/product_eligibility_unclassified_backfill.py.

Workflow:
  1) Dry-Run (Default): python scripts/backfill_unclassified_product_eligibility.py --authored-by <user_id>
  2) Apply:              python scripts/backfill_unclassified_product_eligibility.py --authored-by <user_id> --apply
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

    parser = argparse.ArgumentParser(
        description="Unclassified products -> safe ProductEligibilityRule backfill."
    )
    parser.add_argument("--authored-by", required=True, help="User-ID fuer created_by/approved_by (Pflicht, reale Identitaet)")
    parser.add_argument("--jurisdiction-fallback", default="CH", help="Jurisdiktion fuer Produkte ohne eigenes jurisdiction-Feld (Default: CH)")
    parser.add_argument("--apply", action="store_true", help="Aenderungen in DB schreiben (sonst Dry-Run)")
    args = parser.parse_args()

    from sqlalchemy.orm import configure_mappers  # type: ignore[import-not-found]
    from database import SessionLocal  # type: ignore[import-not-found]
    from models import (  # type: ignore[import-not-found]  # noqa: F401
        allocation, clients, client_login, fx_rate, mandates, profiling,
        protocol_bausteine, review, snapshots, tenant, users, wealth,
        portfolio_handoff, product_eligibility,
    )
    configure_mappers()
    from services.product_eligibility_unclassified_backfill import (  # type: ignore[import-not-found]
        classify_and_backfill_unclassified_products,
    )

    db = SessionLocal()
    try:
        report = classify_and_backfill_unclassified_products(
            db,
            jurisdiction_fallback=args.jurisdiction_fallback,
            authored_by=args.authored_by,
            dry_run=not args.apply,
        )
        if args.apply:
            db.commit()
    finally:
        db.close()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Unclassified-Product-Backfill {mode} ===")
    print(f"Automatisch klassifiziert: {report.classified_count}")
    print(f"Quarantaene (braucht manuelle Klassifizierung): {report.quarantined_count}")
    print()

    by_class: dict[str, list] = {}
    for item in report.items:
        by_class.setdefault(item.classification, []).append(item)

    for classification in ("quarantined_complex", "quarantined_unrecognized_category", "auto_classified"):
        items = by_class.get(classification, [])
        if not items:
            continue
        print(f"--- {classification} ({len(items)}) ---")
        for item in items:
            rule_note = f" -> rule {item.new_rule_id}" if item.new_rule_id else ""
            print(f"  product={item.product_id}{rule_note}")
            print(f"    {item.reason}")
    print()
    if not args.apply:
        print("Hinweis: Dry-Run OK. Mit --apply ausfuehren zum Schreiben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
