"""Sprint U-10 (2026-05-30, Roadmap-Punkt 10): DSG-konformer Kunden-
Datenexport.

Gesetzliche Grundlage
---------------------
Schweizer Datenschutzgesetz (DSG, in Kraft seit 2023) Art. 25:
Recht auf Auskunft. Die betroffene Person kann von jeder Person, die
Daten ueber sie bearbeitet, Auskunft verlangen ueber ALLE Personen-
daten, die ueber sie bearbeitet werden. Format muss "in einem ueb-
lichen elektronischen Format" sein.

Was dieser Service liefert
--------------------------
Eine stabile JSON-Struktur mit allen Daten, die das 5eyes-System zu
einem Kunden gespeichert hat. Aufgeteilt in thematische Sektionen,
sodass der Berater dem Kunden den Export verstaendlich erklaeren kann.

Was bewusst NICHT geliefert wird
--------------------------------
- Berater-Stammdaten (anderes Datensubjekt)
- Produkt-Stammdaten / Marktdaten (kein Personenbezug)
- Capital-Market-Assumptions / House-Matrix (kein Personenbezug)
- Andere Mandate / andere Kunden (Mandantentrennung)

Aufbewahrungsfristen
--------------------
Werden im Export als Metadaten pro Tabelle dokumentiert (siehe
RETENTION_NOTES unten). Konkrete Loeschung folgt in einem eigenen
Sprint (Loeschanspruch, Art. 32 DSG).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models.clients import Client, ClientNationality, ClientOptHistory


SCHEMA_VERSION = 1

# DSG-konforme Aufbewahrungs-Hinweise pro Tabelle. Wird im Export
# mit-geliefert, damit der Kunde versteht, warum welcher Datensatz
# wie lange aufbewahrt wird.
RETENTION_NOTES: dict[str, str] = {
    "clients": (
        "Aufbewahrung waehrend der Kundenbeziehung plus 10 Jahre nach Ende "
        "(GwG Art. 7, OR Art. 962)."
    ),
    "mandates": "10 Jahre nach Ende des Mandats (OR Art. 962).",
    "risk_assessments": "10 Jahre nach Erfassung (FIDLEG Art. 11).",
    "risk_assessment_answers": "10 Jahre nach Erfassung (FIDLEG Art. 11).",
    "suitability_checks": "10 Jahre nach Pruefung (FIDLEG Art. 12, Art. 21).",
    "client_knowledge": "10 Jahre nach letzter Bestaetigung (FIDLEG Art. 6).",
    "advisory_log": "10 Jahre nach Beratungsgespraech (FIDLEG Art. 19).",
    "recommendation_runs": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "recommendation_positions": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "recommendation_holdings": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "target_allocations": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "strategy_snapshots": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "wealth_positions": "Kundenbeziehung + 10 Jahre (OR Art. 962).",
    "cashflows": "Kundenbeziehung + 10 Jahre (OR Art. 962).",
    "wealth_inflows": "Kundenbeziehung + 10 Jahre (OR Art. 962).",
    "goals": "Kundenbeziehung + 10 Jahre.",
    "planning_assumptions": "Kundenbeziehung + 10 Jahre.",
    "contract_documents": "10 Jahre nach Vertragsende (OR Art. 962).",
    "conflict_of_interest_disclosure": "10 Jahre nach Erfassung (FIDLEG Art. 9).",
    "mandate_report_notes": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
    "review_trigger": "10 Jahre nach Auflage (FIDLEG Art. 11).",
    "client_nationalities": "Kundenbeziehung + 10 Jahre (GwG Art. 7).",
    "client_opt_history": "10 Jahre nach Klassifikationswechsel (FIDLEG Art. 4).",
    "audit_log": (
        "10 Jahre nach Eintrag (interne Compliance + Beweissicherung)."
    ),
}


def export_client_data(db: Session, client_id: str) -> dict[str, Any]:
    """Liefert den vollstaendigen DSG-Export fuer einen Kunden.

    Parameter
    ---------
    db
        Aktive SQLAlchemy-Session.
    client_id
        Client.id des zu exportierenden Kunden.

    Returns
    -------
    Stabiles JSON-Schema:
    {
      "schema_version": 1,
      "exported_at": "2026-05-30T...Z",
      "client_id": "...",
      "client_number": "C-...",
      "legal_basis": {...},                    # DSG-Hinweise
      "retention_notes": {...},                # pro Tabelle
      "manifest": {                            # Zeilen-Counts pro Sektion
        "clients": 1, "mandates": 2, ...
      },
      "sections": {
        "client":              {...},          # Stammdaten
        "client_nationalities": [...],
        "client_opt_history":   [...],
        "client_knowledge":     [...],
        "mandates":             [...],
        "risk_assessments":     [...],
        "risk_assessment_answers": [...],
        "suitability_checks":   [...],
        "target_allocations":   [...],
        "recommendation_runs":  [...],
        "recommendation_positions": [...],
        "advisory_log":         [...],
        "wealth_positions":     [...],
        "cashflows":            [...],
        "wealth_inflows":       [...],
        "goals":                [...],
        "planning_assumptions": [...],
        "contract_documents":   [...],
        "conflict_of_interest_disclosure": [...],
        "mandate_report_notes": [...],
        "review_trigger":       [...],
        "strategy_snapshots":   [...],
        "audit_log":            [...]          # nur Eintraege zu diesem Kunden
      }
    }

    Wirft `ValueError` wenn der Kunde nicht existiert.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise ValueError(f"Client {client_id!r} nicht gefunden.")

    mandate_ids = _collect_mandate_ids(db, client_id)
    sections: dict[str, Any] = {
        "client": _serialize_one(client),
        "client_nationalities": _serialize_list(
            db.query(ClientNationality)
            .filter(ClientNationality.client_id == client_id)
            .all()
        ),
        "client_opt_history": _serialize_list(
            db.query(ClientOptHistory)
            .filter(ClientOptHistory.client_id == client_id)
            .all()
        ),
        "client_knowledge": _query_client_knowledge(db, client_id),
        "mandates": _query_mandates(db, client_id),
        "risk_assessments": _query_risk_assessments(db, mandate_ids),
        "risk_assessment_answers": _query_risk_assessment_answers(db, mandate_ids),
        "suitability_checks": _query_suitability_checks(db, mandate_ids),
        "target_allocations": _query_target_allocations(db, mandate_ids),
        "recommendation_runs": _query_recommendation_runs(db, mandate_ids),
        "recommendation_positions": _query_recommendation_positions(db, mandate_ids),
        "recommendation_holdings": _query_recommendation_holdings(db, mandate_ids),
        "advisory_log": _query_advisory_log(db, mandate_ids),
        "wealth_positions": _query_wealth_positions(db, client_id),
        "cashflows": _query_cashflows(db, client_id),
        "wealth_inflows": _query_wealth_inflows(db, client_id),
        "goals": _query_goals(db, mandate_ids),
        "planning_assumptions": _query_planning_assumptions(db, mandate_ids),
        "contract_documents": _query_contract_documents(db, mandate_ids),
        "conflict_of_interest_disclosure": _query_conflict_disclosures(db, mandate_ids),
        "mandate_report_notes": _query_mandate_report_notes(db, mandate_ids),
        "review_trigger": _query_review_trigger(db, mandate_ids),
        "strategy_snapshots": _query_strategy_snapshots(db, mandate_ids),
        "audit_log": _query_audit_log(db, client_id, mandate_ids),
    }

    manifest = {
        key: (1 if isinstance(value, dict) else len(value))
        for key, value in sections.items()
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "client_id": str(client.id),
        "client_number": str(client.client_number),
        "legal_basis": {
            "primary": "DSG Art. 25 (Recht auf Auskunft, Schweiz, in Kraft seit 2023)",
            "supplementary": [
                "FIDLEG Art. 11 (Dokumentationspflicht)",
                "GwG Art. 7 (Sorgfaltspflicht-Belege)",
                "OR Art. 962 (10-Jahres-Aufbewahrung)",
            ],
            "format": "Maschinenlesbares JSON, UTF-8.",
        },
        "retention_notes": RETENTION_NOTES,
        "manifest": manifest,
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Serialisierung
# ---------------------------------------------------------------------------

def _serialize_one(row: Any) -> dict[str, Any]:
    """Reflektive Serialisierung eines ORM-Objekts als JSON-faehiges dict.

    Nutzt sqlalchemy.inspect()-Spalten — kein hardcoded Field-Listing.
    Damit neue Spalten automatisch im Export landen.
    """
    if row is None:
        return {}
    from sqlalchemy import inspect

    mapper = inspect(row.__class__)
    out: dict[str, Any] = {}
    for column in mapper.columns:
        value = getattr(row, column.name, None)
        out[column.name] = _coerce_jsonable(value)
    return out


def _serialize_list(rows: list[Any]) -> list[dict[str, Any]]:
    return [_serialize_one(r) for r in rows]


def _coerce_jsonable(value: Any) -> Any:
    """Stellt sicher, dass nur JSON-faehige Primitives durchgehen."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    # Bytes, Decimal etc. -> str
    return str(value)


# ---------------------------------------------------------------------------
# Query-Helpers (lazy imports, defensive gegen fehlende Tabellen)
# ---------------------------------------------------------------------------

def _collect_mandate_ids(db: Session, client_id: str) -> list[str]:
    from models.mandates import Mandate
    return [
        str(m.id)
        for m in db.query(Mandate)
        .filter(Mandate.client_id == client_id)
        .all()
    ]


def _query_mandates(db: Session, client_id: str) -> list[dict[str, Any]]:
    from models.mandates import Mandate
    rows = (
        db.query(Mandate)
        .filter(Mandate.client_id == client_id)
        .all()
    )
    return _serialize_list(rows)


def _query_client_knowledge(db: Session, client_id: str) -> list[dict[str, Any]]:
    try:
        from models.profiling import ClientKnowledge
        rows = (
            db.query(ClientKnowledge)
            .filter(ClientKnowledge.client_id == client_id)
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_risk_assessments(db: Session, mandate_ids: list[str]) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.profiling import RiskAssessment
        rows = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_risk_assessment_answers(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.profiling import RiskAssessment, RiskAssessmentAnswer
        assessment_ids = [
            str(a.id)
            for a in db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id.in_(mandate_ids))
            .all()
        ]
        if not assessment_ids:
            return []
        rows = (
            db.query(RiskAssessmentAnswer)
            .filter(RiskAssessmentAnswer.assessment_id.in_(assessment_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_suitability_checks(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.profiling import SuitabilityCheck
        rows = (
            db.query(SuitabilityCheck)
            .filter(SuitabilityCheck.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_target_allocations(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.allocation import TargetAllocation
        rows = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_recommendation_runs(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import RecommendationRun
        rows = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_recommendation_positions(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import RecommendationPosition, RecommendationRun
        run_ids = [
            str(r.id)
            for r in db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id.in_(mandate_ids))
            .all()
        ]
        if not run_ids:
            return []
        rows = (
            db.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id.in_(run_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_recommendation_holdings(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import RecommendationHolding
        rows = (
            db.query(RecommendationHolding)
            .filter(RecommendationHolding.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_advisory_log(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import AdvisoryLog
        rows = (
            db.query(AdvisoryLog)
            .filter(AdvisoryLog.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_wealth_positions(db: Session, client_id: str) -> list[dict[str, Any]]:
    try:
        from models.wealth import WealthPosition
        rows = (
            db.query(WealthPosition)
            .filter(WealthPosition.client_id == client_id)
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_cashflows(db: Session, client_id: str) -> list[dict[str, Any]]:
    try:
        from models.wealth import Cashflow
        rows = (
            db.query(Cashflow)
            .filter(Cashflow.client_id == client_id)
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_wealth_inflows(db: Session, client_id: str) -> list[dict[str, Any]]:
    try:
        from models.wealth import WealthInflow
        rows = (
            db.query(WealthInflow)
            .filter(WealthInflow.client_id == client_id)
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_goals(db: Session, mandate_ids: list[str]) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.wealth import Goal
        rows = (
            db.query(Goal)
            .filter(Goal.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_planning_assumptions(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.wealth import PlanningAssumption
        rows = (
            db.query(PlanningAssumption)
            .filter(PlanningAssumption.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_contract_documents(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import ContractDocument
        rows = (
            db.query(ContractDocument)
            .filter(ContractDocument.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_conflict_disclosures(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import ConflictOfInterestDisclosure
        rows = (
            db.query(ConflictOfInterestDisclosure)
            .filter(ConflictOfInterestDisclosure.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_mandate_report_notes(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import MandateReportNotes
        rows = (
            db.query(MandateReportNotes)
            .filter(MandateReportNotes.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_review_trigger(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.review import ReviewTrigger
        rows = (
            db.query(ReviewTrigger)
            .filter(ReviewTrigger.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_strategy_snapshots(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    try:
        from models.snapshots import StrategySnapshot
        rows = (
            db.query(StrategySnapshot)
            .filter(StrategySnapshot.mandate_id.in_(mandate_ids))
            .all()
        )
        return _serialize_list(rows)
    except Exception:  # noqa: BLE001
        return []


def _query_audit_log(
    db: Session, client_id: str, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    """Audit-Eintraege die diesen Kunden oder seine Mandate betreffen."""
    try:
        from models.review import AuditLog
        from sqlalchemy import or_
        query = db.query(AuditLog).filter(
            or_(
                AuditLog.client_id == client_id,
                AuditLog.mandate_id.in_(mandate_ids) if mandate_ids else False,
            )
        )
        return _serialize_list(query.all())
    except Exception:  # noqa: BLE001
        return []
