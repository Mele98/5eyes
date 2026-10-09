"""CLI: bestehende ProductSuitability-Zeilen in ein initiales, approved
ProductEligibilityRuleSet migrieren (CERT-PRODUCT-ELIGIBILITY-001, Spec
Section 15).

Governance-Entscheidung des Users (2026-10-09): "migrate ProductSuitability
jetzt" -- dieses Skript setzt das um, bleibt aber bewusst zweistufig:

Workflow:
  1) Dry-Run (Default): python scripts/migrate_legacy_product_suitability.py --created-by <user_id> --approved-by <user_id>
  2) Apply:              python scripts/migrate_legacy_product_suitability.py --created-by <user_id> --approved-by <user_id> --apply

Nur eindeutige Zeilen (keine ueberlappenden Risikobaender fuer dasselbe
Produkt) werden migriert. Mehrdeutige/widersprueckliche Zeilen werden
gemeldet, nie automatisch aufgeloest -- siehe
services/product_eligibility_legacy_migration.py.

WICHTIG: Dieses Skript aendert nichts an Generate/Finalize/der produktiven
Empfehlungslogik. Es befuellt nur eine bisher ungenutzte, additive Tabelle.
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

    parser = argparse.ArgumentParser(description="Legacy ProductSuitability -> ProductEligibilityRuleSet.")
    parser.add_argument("--created-by", required=True, help="User-ID fuer created_by (Pflicht, reale Identitaet)")
    parser.add_argument("--approved-by", required=True, help="User-ID fuer approved_by (Pflicht, reale Identitaet)")
    parser.add_argument("--jurisdiction-fallback", default="CH", help="Jurisdiktion fuer Produkte ohne eigenes jurisdiction-Feld (Default: CH)")
    parser.add_argument("--apply", action="store_true", help="Aenderungen in DB schreiben (sonst Dry-Run)")
    args = parser.parse_args()

    # Imports nach _ensure_backend_on_path. Dieses Skript laeuft standalone
    # (nicht ueber uvicorn main:app), daher muessen alle Modelle, die per
    # relationship() querverweisen (Mandate <-> PortfolioHandoff etc.),
    # hier explizit importiert werden, bevor configure_mappers() laeuft --
    # sonst schlagen SQLAlchemy-Relationship-Aufloesungen fehl. Gleiches
    # Muster wie in tests/test_cert_product_eligibility_001_reproducers.py.
    from sqlalchemy.orm import configure_mappers  # type: ignore[import-not-found]
    from database import SessionLocal  # type: ignore[import-not-found]
    from models import (  # type: ignore[import-not-found]  # noqa: F401
        allocation, clients, client_login, fx_rate, mandates, profiling,
        protocol_bausteine, review, snapshots, tenant, users, wealth,
        portfolio_handoff, product_eligibility,
    )
    configure_mappers()
    from services.product_eligibility_legacy_migration import (  # type: ignore[import-not-found]
        classify_and_migrate_legacy_suitability,
    )

    db = SessionLocal()
    try:
        report = classify_and_migrate_legacy_suitability(
            db,
            created_by=args.created_by,
            approved_by=args.approved_by,
            jurisdiction_fallback=args.jurisdiction_fallback,
            dry_run=not args.apply,
        )
    finally:
        db.close()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Legacy-ProductSuitability-Migration {mode} ===")
    print(f"Migriert (verified_migrated_rule): {report.migrated_count}")
    print(f"Quarantaene (ambiguous/conflicting): {report.quarantined_count}")
    if report.rule_set_id:
        print(f"Neues RuleSet: {report.rule_set_id}")
    print()

    by_class: dict[str, list] = {}
    for item in report.items:
        by_class.setdefault(item.classification, []).append(item)

    for classification in ("legacy_conflicting", "legacy_ambiguous_scope", "verified_migrated_rule"):
        items = by_class.get(classification, [])
        if not items:
            continue
        print(f"--- {classification} ({len(items)}) ---")
        for item in items:
            rule_note = f" -> rule {item.new_rule_id}" if item.new_rule_id else ""
            print(f"  product={item.product_id} suitability={item.legacy_suitability_id}{rule_note}")
            print(f"    {item.reason}")
    print()
    if not args.apply:
        print("Hinweis: Dry-Run OK. Mit --apply ausfuehren zum Schreiben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
