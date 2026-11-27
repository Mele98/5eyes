"""Synthetische Produktevidenz fuer Tests -- ueber den ECHTEN Pflegeweg (C-COMP-02).

Kein Gate-Bypass: Entwurf (``create_product_evidence_draft``), Vier-Augen-
Freigabe der gesehenen Menge (``approve_product_evidence_items``) und Bindung
(``snapshot_run_product_evidence``) sind die Produktfunktionen; alle Gates laufen
unveraendert. Das Modul liegt unter ``tests/`` und wird vom Produkt nie
importiert; es gibt keinen Umgebungsschalter.

Bestandstests, die NICHT die Produktevidenz pruefen, aber einen belegten
Produktlauf voraussetzen, stehen abschliessend in ``SYNTHETIC_EVIDENCE_MODULES``.
Nur fuer sie legt die conftest-Fixture die Nachweise an, bevor ein Lauf die
Kandidaten bewertet bzw. eine Position hinzugefuegt wird, und bindet direkt
eingefuegte Laeufe vor dem Commit. Jeder andere Test laeuft ohne Evidenz.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.product_evidence import PRODUCT_EVIDENCE_KINDS, product_identity
from core.reason_codes import DomainError
from database import new_uuid
from models.mandates import Mandate
from models.product_eligibility import ProductEvidenceItem
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from services.product_eligibility import (
    approve_product_evidence_items,
    close_product_evidence_item,
    create_product_evidence_draft,
    evidence_product_view,
    mandate_tenant_id,
    snapshot_run_product_evidence,
)

SOURCE_TYPE = "synthetic_test_fixture"
_CASH_TYPES = frozenset({"cash"})


def synthetic_values(product, kind: str, *, jurisdiction: str = "CH", today: str | None = None, **overrides) -> dict:
    """Erfassungswerte eines synthetischen Nachweises. ``costs`` folgt dem
    Stammdatenfeld; eine fehlende TER wird NIE zu 0 (dann kein Kostenwert)."""
    now = datetime.now(timezone.utc)
    today = today or now.date().isoformat()
    stable, share_class = product_identity(evidence_product_view(product))
    payload = {"classification": SOURCE_TYPE, "evidence_kind": kind, "status": "synthetic"}
    if kind == "kid":
        payload["status"] = "not_applicable"
    if kind == "costs":
        if product.ter_bps is not None:
            payload.update(value=int(product.ter_bps), unit="bps_per_year")
        elif str(product.product_type or "").strip().casefold() in _CASH_TYPES:
            payload["status"] = "not_applicable"
        else:
            payload["value"] = None
    if kind == "retrocession":
        if product.retrocession_bps is not None:
            payload.update(value=int(product.retrocession_bps), unit="bps_per_year")
        else:
            payload["status"] = "not_applicable"
    source = f"synthetic-test:{product.id}:{kind}"
    if kind == "retrocession" and getattr(product, "retrocession_source", None):
        source = str(product.retrocession_source)
    values = {
        "stable_instrument_id": stable, "share_class_id": share_class, "jurisdiction": jurisdiction,
        "evidence_kind": kind, "source_type": SOURCE_TYPE, "source_reference": source,
        "source_document_title": "Synthetischer Testnachweis", "source_document_version": "1",
        "source_document_date": today, "retrieved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_document_sha256": hashlib.sha256(source.encode()).hexdigest(), "payload": payload,
        "as_of": today, "valid_from": today, "valid_until": None, "note": None, "supersedes_id": None,
    }
    values.update(overrides)
    return values


def _approver(db, *, tenant_id: str) -> User:
    """Zweite Person; nach der Freigabe inaktiv, damit sie andere Vier-Augen-
    Regeln des Tests (Anzahl aktiver Freigeber) nicht veraendert."""
    now = datetime.now(timezone.utc).isoformat()
    uid = new_uuid()
    user = User(
        id=uid, tenant_id=tenant_id, username=f"evidence-approver-{uid}",
        password_hash="synthetic-test-only", full_name="Synthetische Zweitfreigabe",
        email=f"{uid}@example.invalid", role="compliance_reviewer", is_active=0,
        created_at=now, updated_at=now,
    )
    db.add(user)
    db.flush()
    return user


def add_synthetic_product_evidence(
    db, products, *, actor_id: str, tenant_id: str, jurisdiction: str = "CH", kinds=PRODUCT_EVIDENCE_KINDS,
    overrides: dict | None = None,
) -> list[ProductEvidenceItem]:
    """Entwurf + Vier-Augen-Freigabe je Produkt (ohne Commit)."""
    approver = _approver(db, tenant_id=tenant_id)
    approved: list[ProductEvidenceItem] = []
    for product in products:
        drafts = []
        for kind in kinds:
            values = synthetic_values(product, kind, jurisdiction=jurisdiction, **((overrides or {}).get(kind) or {}))
            if kind == "costs" and values["payload"].get("value") is None and (
                values["payload"].get("status") != "not_applicable"
            ):
                continue  # unbekannte TER bleibt unbelegt
            drafts.append(create_product_evidence_draft(
                db, product, values=values, tenant_id=tenant_id, actor_id=actor_id,
            ))
        db.flush()
        approved.extend(approve_product_evidence_items(
            db, product, seen=[(row.id, row.canonical_payload_hash) for row in drafts], tenant_id=tenant_id,
            actor_id=approver.id, is_same_person=lambda creator: str(creator) == str(approver.id),
            approver_ids=[approver.id], attestation=None, min_attestation_length=1,
        ))
    return approved


def bind_synthetic_run(db, run, mandate=None):
    """Nachweise der Positionen anlegen (falls noetig) und den Lauf binden."""
    mandate = mandate or db.get(Mandate, run.mandate_id)
    ids = [row[0] for row in db.query(RecommendationPosition.product_id).filter_by(run_id=run.id).all()]
    _provision(db, mandate, run.created_by, db.query(Product).filter(Product.id.in_(ids)).all())
    return snapshot_run_product_evidence(db, mandate, run)


def bind_run_with_synthetic_product(session_factory, run_id) -> None:
    """Wie ``add_evidenced_position``, mit eigener Session und Commit."""
    with session_factory() as db:
        add_evidenced_position(db, run_id)
        db.commit()


def add_evidenced_position(db, run_id) -> None:
    """Fixtures mit einem Lauf OHNE Position (gemockte Handelsliste): eine
    synthetische, belegte Position anlegen und den Lauf echt binden."""
    now = datetime.now(timezone.utc).isoformat()
    run = db.get(RecommendationRun, run_id)
    product = Product(
        id=f"evidence-{run_id}", product_name="Synthetisches belegtes Produkt", provider="Synthetisch",
        product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Welt", currency="CHF", ter_bps=20,
        retrocession_bps=0, retrocession_source="Testfixture: retrozessionsfrei", is_active=1,
        created_at=now, updated_at=now,
    )
    db.add(product)
    db.flush()
    db.add(RecommendationPosition(
        id=f"evidence-pos-{run_id}", run_id=run_id, product_id=product.id, target_weight_bps=10_000,
        target_amount_rappen=0, created_at=now, updated_at=now,
    ))
    db.flush()
    bind_synthetic_run(db, run)


def rebind_master_terms(session_factory, run_id) -> None:
    """Fixtures, die Kosten/Retrozession NACH der Bindung aendern: die Nachweise
    der Laufprodukte ueber den echten Ersatz-/Stilllegungsweg nachziehen und den
    Lauf neu binden. Unbekannt (NULL) bleibt unbelegt -- der Lauf ist dann ungebunden."""
    with session_factory() as db:
        run = db.get(RecommendationRun, run_id)
        ids = [row[0] for row in db.query(RecommendationPosition.product_id).filter_by(run_id=run_id).all()]
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        provision_products(db, db.get(Mandate, run.mandate_id), products)
        for product in products:
            known = {"costs": product.ter_bps is not None, "retrocession": product.retrocession_bps is not None}
            for row in db.query(ProductEvidenceItem).filter_by(product_id=product.id, status="approved").all():
                if row.evidence_kind not in known:
                    continue
                if not known[row.evidence_kind]:
                    close_product_evidence_item(db, row, status="retired", reason="TEST_UNKNOWN", actor_id="approver")
                    continue
                draft = create_product_evidence_draft(
                    db, product, values=synthetic_values(product, row.evidence_kind, supersedes_id=row.id),
                    tenant_id=row.tenant_id, actor_id=row.created_by)
                db.flush()
                approve_product_evidence_items(
                    db, product, seen=[(draft.id, draft.canonical_payload_hash)], tenant_id=row.tenant_id,
                    actor_id="approver", is_same_person=lambda _c: False, approver_ids=[], attestation=None,
                    min_attestation_length=1)
        run.product_evidence_snapshot_id = run.product_evidence_hash = run.product_evidence_status = None
        db.flush()
        try:
            with db.begin_nested():
                snapshot_run_product_evidence(db, db.get(Mandate, run.mandate_id), run)
        except DomainError:
            pass
        db.commit()


def provision_products(db, mandate, products) -> None:
    """Nachweise genau dieser Produkte anlegen, falls noch keine bestehen."""
    _provision(db, mandate, _actor(db, mandate), products)


def _provision(db, mandate, actor_id, products) -> None:
    tenant_id = mandate_tenant_id(mandate)
    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH")
    known = {row[0] for row in db.query(ProductEvidenceItem.product_id).filter(
        ProductEvidenceItem.tenant_id == tenant_id, ProductEvidenceItem.jurisdiction == jurisdiction,
    ).distinct().all()}
    missing = [
        p for p in products
        if p.id not in known and (p.tenant_id is None or str(p.tenant_id) == tenant_id)
    ]
    if missing:
        add_synthetic_product_evidence(
            db, missing, actor_id=actor_id, tenant_id=tenant_id, jurisdiction=jurisdiction,
        )


@contextmanager
def synthetic_evidence_for_existing_flows():
    """Nur fuer ``SYNTHETIC_EVIDENCE_MODULES`` (conftest). Legt die Nachweise vor
    der echten Pruefung an -- die Pruefung selbst bleibt unveraendert:

    * Generate: vor dem Bau des ``ProductEvidenceContext`` (Kandidatenwahl);
    * manuelle Position: vor ``assert_product_evidenced``;
    * direkt eingefuegte Laeufe (Fixtures ohne Generate): vor dem Commit
      Nachweise + echte Snapshot-Bindung."""
    import routers.review as review
    import services.product_eligibility as eligibility

    original_context, original_assert = eligibility.ProductEvidenceContext, review.assert_product_evidenced
    key, busy = "c_comp_02_touched_runs", "c_comp_02_busy"

    class ProvisioningContext(original_context):
        def __init__(self, db, mandate, products):
            if isinstance(mandate, Mandate):
                _provision(db, mandate, _actor(db, mandate), products)
            super().__init__(db, mandate, products)

    def provisioning_assert(db, mandate, product):
        _provision(db, mandate, _actor(db, mandate), [product])
        return original_assert(db, mandate, product)

    def after_flush(session, _ctx):
        for obj in session.new:
            if isinstance(obj, RecommendationRun):
                session.info.setdefault(key, set()).add(obj.id)
            elif isinstance(obj, RecommendationPosition):
                session.info.setdefault(key, set()).add(obj.run_id)

    def before_commit(session):
        if session.info.get(busy):
            return
        session.flush()
        runs = session.info.pop(key, set())
        session.info[busy] = True
        try:
            for run_id in sorted(r for r in runs if r):
                run = session.get(RecommendationRun, run_id)
                mandate = session.get(Mandate, run.mandate_id) if run is not None else None
                if mandate is None or run.product_evidence_status or not session.query(
                        RecommendationPosition.id).filter_by(run_id=run.id).first():
                    continue
                try:
                    with session.begin_nested():
                        bind_synthetic_run(session, run, mandate)
                except (DomainError, OperationalError):
                    pass  # Produkt absichtlich nicht belegbar / Teilschema: Lauf bleibt ungebunden
        finally:
            session.info[busy] = False

    eligibility.ProductEvidenceContext = ProvisioningContext
    review.assert_product_evidenced = provisioning_assert
    event.listen(Session, "after_flush", after_flush)
    event.listen(Session, "before_commit", before_commit)
    try:
        yield
    finally:
        eligibility.ProductEvidenceContext = original_context
        review.assert_product_evidenced = original_assert
        event.remove(Session, "after_flush", after_flush)
        event.remove(Session, "before_commit", before_commit)


def provision_database(db_path) -> None:
    """Livetests (eigener Serverprozess): Nachweise aller Katalogprodukte fuer
    jedes Mandat der Wegwerf-Datenbank -- gleicher Entwurfs-/Freigabeweg."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from services.portfolio_engine import ensure_default_products, ensure_hedged_product_variants

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 60})
    try:
        with sessionmaker(bind=engine)() as db:
            ensure_default_products(db, jurisdiction="CH")  # Entwicklungskatalog wie im Lauf
            ensure_hedged_product_variants(db)
            db.flush()
            products = db.query(Product).filter(Product.deleted_at.is_(None)).all()
            for mandate in db.query(Mandate).filter(Mandate.deleted_at.is_(None)).all():
                _provision(db, mandate, _actor(db, mandate), products)
            db.commit()
    finally:
        engine.dispose()


def generate_with_evidence(api, db_path, mandate_id, body=None):
    """``POST .../recommendations/generate`` im Livetest: ohne Nachweise sperrt
    das Gate (409), danach mit synthetischer Evidenz derselbe Aufruf."""
    path = f"/mandates/{mandate_id}/recommendations/generate"
    status, response = api("POST", path, body or {})
    if status == 409 and "PRODUCT_EVIDENCE_" in str(response):
        provision_database(db_path)
        status, response = api("POST", path, body or {})
    return status, response


def _actor(db, mandate) -> str:
    actor = getattr(mandate, "advisor_id", None) or db.query(User.id).order_by(User.id).limit(1).scalar()
    return str(actor)


SYNTHETIC_EVIDENCE_MODULES: frozenset[str] = frozenset({
    "test_advisory_report.py",
    "test_allocation_editor_stale_state_contract.py",
    "test_allocation_input_staleness_surfaces.py",
    "test_asset_allocation_reference_integrity_edges.py",
    "test_audit_2026_11_fondsuniversum_fixes.py",
    "test_audit_n856_5_po04_golden_shift_exact.py",
    "test_audit_po04_implementation_metrics.py",
    "test_audit_po06_hedged_currency_exposure.py",
    "test_audit_po13_product_tie_break.py",
    "test_audit_po16_finalize_saa_reconciliation.py",
    "test_c860_eligibility_timestamp_formats.py",
    "test_c_comp_02_channels.py",
    "test_c_comp_02_v2_product_evidence_envelope.py",
    "test_ccx_p2_invalidation.py",
    "test_ccx_p3_n2_pdf_sweep.py",
    "test_ccx_p3_strict_fx_channels.py",
    "test_ccx_p4_allocation_publish.py",
    "test_ccx_p5_channel_envelope.py",
    "test_cert_cost_publication_001_reproducers.py",
    "test_cert_handoff_execution_001_reproducers.py",
    "test_cma_adr12a_release_hold.py",
    "test_cma_correlation_provenance_engine_wiring.py",
    "test_cost_disclosure_endpoint.py",
    "test_cost_disclosure_run_resolver.py",
    "test_de_onboarding_integration.py",
    "test_depot_check_bound_inputs.py",
    "test_depot_check_pdf_warnings_merge.py",
    "test_depot_e2e_snapshot_identity.py",
    "test_depotcheck_stale_run_fallback_regression.py",
    "test_dynamic_retirement_phase.py",
    "test_e2e_thierry_goessi_walkthrough.py",
    "test_engine_de_jurisdiction_wiring.py",
    "test_esg_manual_final_missingness.py",
    "test_esg_premium_criteria.py",
    "test_esg_theme_exclusion_effective.py",
    "test_g7_currency_matrix.py",
    "test_golden_snapshot_ch_regression.py",
    "test_h179_contract_layer.py",
    "test_h7_c4_retro_finalization_gate.py",
    "test_h7_n884_07_release_block_audit.py",
    "test_h8_c2_client_information.py",
    "test_handoff_new_product_zero_holding.py",
    "test_handoff_preview_parity_and_cash.py",
    "test_k1_pe_s_missing_ter_rank.py",
    "test_k3_run_context.py",
    "test_kn3_b_restart_freshness.py",
    "test_manual_allocation_save_contract.py",
    "test_manual_save_requires_basis.py",
    "test_pdf_recommendation_run_resolver.py",
    "test_portfolio_data_001_gate_wiring.py",
    "test_portfolio_generate_after_saa_recalc.py",
    "test_portfolio_handoff.py",
    "test_pref_context_snapshot.py",
    "test_provisional_pdf_gate.py",
    "test_provisional_pdf_gate_extended.py",
    "test_provisional_warning_json_and_client_portal.py",
    "test_rec001_cross_tenant_product_visibility.py",
    "test_rec002_rec004_recommendation_position_integrity.py",
    "test_recommendation_generate_accepts_unfinalizable_cma_less_allocation.py",
    "test_regenerate_unchanged_inputs_is_idempotent.py",
    "test_rev_e2_890982d7_greenwashing.py",
    "test_risk_budget_release_gate_channels.py",
    "test_risk_override_allocation_staleness.py",
    "test_runtime_contracts.py",
    "test_saa_resampled_stability.py",
    "test_service_domain_error_parity.py",
    "test_stage8_foundation_smoketest.py",
    "test_stale_allocation_hide_soll_exposures.py",
    "test_stale_allocation_hide_targets.py",
    "test_suitability_gate_all_paths.py",
    "test_sustainability_e2a_contract.py",
    "test_sustainability_e2b_n1_product_enforcement.py",
    "test_sustainability_e2b_n2_live_evidence.py",
    "test_sustainability_e2b_offer_and_floor.py",
    "test_x2b_run_context_readers.py",
    "test_zero_strategy_base_n858_11.py",
})
