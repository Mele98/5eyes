"""CCX-P3-FX (N-909-13): Druckpruefung der FX-Basis fuer Kundendokumente.

Alle 12 Kunden-PDFs und der Ex-ante-Kostenausweis (JSON) zeigen Betraege eines
Laufs, der mit dem damals belegten Kurs gerechnet wurde. Solange dieser Lauf
nicht versiegelt ist (kein SEALED-Envelope mit gebundenem Bewertungs-Snapshot
und FX-Basis), gibt es keine gebundene Kursevidenz, auf die sich "eingefroren"
berufen koennte. Deshalb gilt dieselbe Linie wie beim gespeicherten
Depot-Check (N-909-02): beim Druck muss jede Waehrung der Betragsquellen des
Mandats heute strikt konvertierbar sein (belegt, frisch nach Tenant-Frist,
kein Ersatzkurs) -- sonst ``CCX_FX_BASIS_*``.

CCX P5 (Codex N-909-22, Vertrag §8.3): die fruehere Ausnahme fuer einen
versiegelten, FRESHen Lauf ist entfallen. Jedes Live-Neurendern prueft die
heutige strikte FX-Basis; eine Ausnahme gilt nur fuer die Wiedergabe des
gespeicherten, hashgebundenen P5-Artefakts (Archiv/Signatur).

H12 (N-909-20, Codex: route-spezifisches FX-Quelleninventar): welche Route
welche FX-abhaengigen Betraege druckt und welche Pruefung deshalb gilt, steht
in ``ROUTE_FX_SOURCES`` (Waechter ``tests/test_h12_ccx_hygiene.py``).

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


# Klassen des FX-Quelleninventars.
FX_RUN_AMOUNTS = "run_amounts"
FX_ADVISORY_POSITIONS_LIVE = "advisory_positions_live"
FX_LIVE_STRICT_BUILDER = "live_strict_builder"

# H12: je Kunden-PDF-Route (Funktion in routers/pdf_reports.py) die gedruckten
# FX-abhaengigen Betraege und die daraus folgende Pruefung.
#   FX_RUN_AMOUNTS: eingefrorene Betraege eines Laufs (Engine rechnet mit allen
#     Betragsquellen: Vermoegen, einbezogene Cashflows, Zufluesse) -> Druck-
#     pruefung ``assert_print_fx_basis_current`` ueber alle Quellen, Ausnahme
#     nur fuer einen SEALED+FRESH-Lauf mit Bewertungsbindung.
#   FX_ADVISORY_POSITIONS_LIVE: nur das Beratungsvermoegen aus der Vermoegens-
#     erfassung, live und strikt umgerechnet (``_advisory_wealth_from_capture``)
#     -> genau die gedruckten Positionen werden geprueft; keine Ausnahme (live).
#     Ohne Fremdwaehrungs-Position keine Kursabfrage, keine Sperre (N-909-20).
#   FX_LIVE_STRICT_BUILDER: der Daten-Builder rechnet live mit der strikten
#     Basis (``load_fx_basis``/``from_db_strict_for_model``) und sperrt dort.
ROUTE_FX_SOURCES: dict[str, tuple[str, str]] = {
    "get_risikoprofil_pdf": (FX_ADVISORY_POSITIONS_LIVE, "Beratungsvermoegen (Kopfzeile)"),
    "get_vertrag_pdf": (FX_ADVISORY_POSITIONS_LIVE, "Beratungsvermoegen (Vertragsgegenstand)"),
    "get_portfolio_pdf": (FX_RUN_AMOUNTS, "Beratungsvermoegen und Bucket-Betraege der Soll-Allokation"),
    "get_protokoll_pdf": (FX_RUN_AMOUNTS, "Beratungsvermoegen der Soll-Allokation, Strategiebetraege"),
    "get_backtest_pdf": (FX_RUN_AMOUNTS, "Startwert und Pfadbetraege"),
    "get_cost_disclosure_pdf": (FX_RUN_AMOUNTS, "Anlagebasis und Kostenbetraege"),
    "get_kundeninformation_pdf": (FX_RUN_AMOUNTS, "Ex-ante-Kostenzeilen (Anlagebasis des Laufs)"),
    "get_anlagestrategie_pdf": (FX_LIVE_STRICT_BUILDER, "Positionen/Strategiebetraege live strikt"),
    "get_assetallocation_pdf": (FX_LIVE_STRICT_BUILDER, "IST-Positionen live strikt"),
    "get_contract_signoff_pdf": (FX_LIVE_STRICT_BUILDER, "Strategiebetraege live strikt"),
    "get_depotcheck_pdf": (FX_LIVE_STRICT_BUILDER, "Depotpositionen live strikt"),
    "get_advisory_report_pdf": (FX_LIVE_STRICT_BUILDER, "Bericht live strikt"),
}


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
    """Ist ``run_id`` der Lauf des aktuellen SEALED-Envelopes, der FRESH ist
    (P2: eine Invalidierung laesst ``status`` SEALED und setzt nur
    ``freshness_status``), mit gebundenem Bewertungs-Snapshot (FX-Basis)?"""
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
    if envelope is None or envelope.freshness_status != "FRESH":
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
    Betragsquellen heute nicht strikt konvertierbar ist. Ohne Fremdwaehrung:
    keine Kursabfrage.

    CCX P5 (Vertrag §8.3, N-909-22): die fruehere Ausnahme fuer einen
    SEALED+FRESH-Lauf entfaellt. Eine Ausnahme gilt nur fuer die Wiedergabe des
    exakten, hashgebundenen P5-Artefakts; jedes Live-Neurendern -- auch
    desselben versiegelten Laufs -- prueft die heutige strikte FX-Basis.
    ``run_id`` bleibt fuer Aufrufer erhalten (keine Wirkung mehr)."""
    del run_id
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
    "FX_ADVISORY_POSITIONS_LIVE",
    "FX_LIVE_STRICT_BUILDER",
    "FX_RUN_AMOUNTS",
    "ROUTE_FX_SOURCES",
    "current_run_id",
    "load_fx_basis",
    "mandate_amount_currencies",
    "run_is_sealed",
]
