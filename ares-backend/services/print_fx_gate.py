"""CCX-P3-FX (N-909-13): Druckpruefung der FX-Basis fuer Kundendokumente.

Alle 12 Kunden-PDFs und der Ex-ante-Kostenausweis (JSON) zeigen Betraege eines
Laufs, der mit dem damals belegten Kurs gerechnet wurde. Solange dieser Lauf
nicht versiegelt ist (kein SEALED-Envelope mit gebundenem Bewertungs-Snapshot
und FX-Basis), gibt es keine gebundene Kursevidenz, auf die sich "eingefroren"
berufen koennte. Deshalb gilt dieselbe Linie wie beim gespeicherten
Depot-Check (N-909-02): beim Druck muss jede Waehrung der Betragsquellen des
Mandats heute strikt konvertierbar sein (belegt, frisch nach Tenant-Frist,
kein Ersatzkurs) -- sonst ``CCX_FX_BASIS_*``.

Ein versiegelter Lauf traegt seine FX-Basis im Envelope (Bewertungs-Snapshot
mit ``fx_basis_hash``); er wird hier nicht erneut gegen heute geprueft.

Das Modul ist zugleich die Druck-Fassade der Router fuer die strikte FX-Basis
(``load_fx_basis``) und den Kostenausweis (``build_client_cost_disclosure``).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from models.review import RecommendationRun
from models.snapshots import AdvisoryDecisionEnvelope, AdvisoryEnvelopeBinding
from models.wealth import Cashflow, WealthInflow, WealthPosition
from services.advisory_decision_envelope import VALUATION_BINDING_KIND, mandate_tenant
from services.cost_disclosure import build_cost_disclosure
from services.fx_basis import load_fx_basis, normalize_currency


def mandate_amount_currencies(db: Session, mandate: Any) -> set[str]:
    """Waehrungen aller aktiven Betragsquellen des Mandats (Vermoegen,
    einbezogene Cashflows, Zufluesse) -- dieselben Quellen wie die Engine."""
    client_id = getattr(mandate, "client_id", None)
    currencies: set[str] = set()
    for row in db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id, WealthPosition.deleted_at.is_(None),
    ).all():
        if int(getattr(row, "is_active", 1) or 0) == 1:
            currencies.add(normalize_currency(row.currency))
    for row in db.query(Cashflow).filter(
        Cashflow.client_id == client_id, Cashflow.deleted_at.is_(None),
    ).all():
        if int(getattr(row, "is_active", 1) or 0) == 1 and int(getattr(row, "is_included", 1) or 0) == 1:
            currencies.add(normalize_currency(getattr(row, "currency", None)))
    for row in db.query(WealthInflow).filter(
        WealthInflow.client_id == client_id, WealthInflow.deleted_at.is_(None),
    ).all():
        currencies.add(normalize_currency(getattr(row, "currency", None)))
    return currencies


def current_run_id(db: Session, mandate_id: str) -> str | None:
    """Aktueller Lauf wie ``portfolio_engine._current_recommendation_run``:
    juengster Final-Lauf, sonst juengster Lauf."""
    for only_final in (True, False):
        query = db.query(RecommendationRun).filter(RecommendationRun.mandate_id == str(mandate_id))
        if only_final:
            query = query.filter(RecommendationRun.result_status == "Final")
        run = query.order_by(RecommendationRun.created_at.desc()).first()
        if run is not None:
            return str(run.id)
    return None


def run_is_sealed(db: Session, mandate: Any, run_id: str | None) -> bool:
    """Ist ``run_id`` der Lauf des aktuellen SEALED-Envelopes mit gebundenem
    Bewertungs-Snapshot (FX-Basis)?"""
    if not run_id:
        return False
    tenant_id = mandate_tenant(mandate)
    if not tenant_id:
        return False
    envelope = db.query(AdvisoryDecisionEnvelope).filter(
        AdvisoryDecisionEnvelope.tenant_id == tenant_id,
        AdvisoryDecisionEnvelope.mandate_id == str(mandate.id),
        AdvisoryDecisionEnvelope.status == "SEALED",
    ).first()
    if envelope is None:
        return False
    kinds = {
        (b.binding_kind, str(b.object_id))
        for b in db.query(AdvisoryEnvelopeBinding).filter(
            AdvisoryEnvelopeBinding.tenant_id == tenant_id,
            AdvisoryEnvelopeBinding.envelope_id == envelope.id,
        ).all()
    }
    has_run = ("recommendation_run", str(run_id)) in kinds
    has_valuation = any(kind == VALUATION_BINDING_KIND for kind, _ in kinds)
    return has_run and has_valuation


def assert_print_fx_basis_current(db: Session, mandate: Any, *, run_id: str | None = None) -> None:
    """Sperrt typisiert (``CCX_FX_BASIS_*``), wenn eine Waehrung der
    Betragsquellen heute nicht strikt konvertierbar ist und der Lauf nicht
    versiegelt ist. Ohne Fremdwaehrung: keine Kursabfrage."""
    if run_id is None:
        run_id = current_run_id(db, str(mandate.id))
    if run_is_sealed(db, mandate, run_id):
        return
    target = normalize_currency(getattr(mandate, "base_currency", None))
    currencies = mandate_amount_currencies(db, mandate)
    if not currencies - {target}:
        return
    basis = load_fx_basis(db, target, currencies, tenant_id=getattr(mandate, "tenant_id", None))
    basis.require_convertible(currencies)


def build_client_cost_disclosure(db: Session, mandate: Any) -> dict:
    """Ex-ante-Kostenausweis fuer den Kunden: erst die Druckpruefung, dann
    derselbe ``build_cost_disclosure`` (Single-Source-of-Truth)."""
    assert_print_fx_basis_current(db, mandate)
    return build_cost_disclosure(db, mandate)


__all__ = [
    "assert_print_fx_basis_current",
    "build_client_cost_disclosure",
    "current_run_id",
    "load_fx_basis",
    "mandate_amount_currencies",
    "run_is_sealed",
]
