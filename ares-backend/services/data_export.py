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
    "protocol_baustein_selections": "10 Jahre nach Erstellung (FIDLEG Art. 11).",
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
      "complete": true,                        # False sobald IRGENDEINE
                                                # Sektion fehlgeschlagen ist
                                                # (PRIV-002, siehe unten)
      "section_status": {                      # "ok" | "error" pro Sektion,
        "risk_assessments": "ok", ...          # die frueher einen Fehler
      },                                        # lautlos verschluckt haette
      "section_errors": {                      # nur befuellt fuer Sektionen
        # "wealth_positions": "Sektion konnte nicht geladen werden ..."
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
        "protocol_baustein_selections": [...],
        "audit_log":            [...]          # nur Eintraege zu diesem Kunden
      }
    }

    Wirft `ValueError` wenn der Kunde nicht existiert.

    Fehlersichtbarkeit (PRIV-002, Codex-Audit 2026-08/09)
    ------------------------------------------------------
    Fast alle Sektionen (ausser "client", "client_nationalities",
    "client_opt_history" und "mandates", die schon vorher ungefangene
    Fehler nach oben durchgereicht haben) wurden frueher von einem
    breiten `except Exception: return []` in der jeweiligen
    `_query_*`-Funktion abgefangen. Ein DB-/Schema-Fehler in EINER
    Sektion fuehrte damit lautlos zu einer leeren Liste -- der
    Gesamt-Export sah trotzdem vollstaendig erfolgreich aus, obwohl er
    unvollstaendig war. Fuer einen DSG-Art.-25-Auskunftsexport ist das
    inakzeptabel.

    Die Resilienz bleibt erhalten (ein Sektionsfehler crasht weiterhin
    NICHT den gesamten Export), aber jetzt sichtbar ueber die drei
    zusaetzlichen Top-Level-Felder `complete`, `section_status` und
    `section_errors` (siehe Schema oben). Die Rohdaten in `sections`
    und die Zeilen-Counts in `manifest` bleiben bei einem erfolgreichen
    Export unveraendert -- rein additiv.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise ValueError(f"Client {client_id!r} nicht gefunden.")

    mandate_ids = _collect_mandate_ids(db, client_id)
    section_status: dict[str, str] = {}
    section_errors: dict[str, str] = {}

    def _s(name: str, builder) -> Any:
        return _run_section(section_status, section_errors, name, builder)

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
        "client_knowledge": _s("client_knowledge", lambda: _query_client_knowledge(db, client_id)),
        "mandates": _query_mandates(db, client_id),
        "risk_assessments": _s("risk_assessments", lambda: _query_risk_assessments(db, mandate_ids)),
        "risk_assessment_answers": _s(
            "risk_assessment_answers", lambda: _query_risk_assessment_answers(db, mandate_ids)
        ),
        "suitability_checks": _s("suitability_checks", lambda: _query_suitability_checks(db, mandate_ids)),
        "target_allocations": _s("target_allocations", lambda: _query_target_allocations(db, mandate_ids)),
        "recommendation_runs": _s("recommendation_runs", lambda: _query_recommendation_runs(db, mandate_ids)),
        "recommendation_positions": _s(
            "recommendation_positions", lambda: _query_recommendation_positions(db, mandate_ids)
        ),
        "recommendation_holdings": _s(
            "recommendation_holdings", lambda: _query_recommendation_holdings(db, mandate_ids)
        ),
        "advisory_log": _s("advisory_log", lambda: _query_advisory_log(db, mandate_ids)),
        "wealth_positions": _s("wealth_positions", lambda: _query_wealth_positions(db, client_id)),
        "cashflows": _s("cashflows", lambda: _query_cashflows(db, client_id)),
        "wealth_inflows": _s("wealth_inflows", lambda: _query_wealth_inflows(db, client_id)),
        "goals": _s("goals", lambda: _query_goals(db, mandate_ids)),
        "planning_assumptions": _s(
            "planning_assumptions", lambda: _query_planning_assumptions(db, mandate_ids)
        ),
        "contract_documents": _s(
            "contract_documents", lambda: _query_contract_documents(db, mandate_ids)
        ),
        "conflict_of_interest_disclosure": _s(
            "conflict_of_interest_disclosure", lambda: _query_conflict_disclosures(db, mandate_ids)
        ),
        "mandate_report_notes": _s(
            "mandate_report_notes", lambda: _query_mandate_report_notes(db, mandate_ids)
        ),
        "review_trigger": _s("review_trigger", lambda: _query_review_trigger(db, mandate_ids)),
        "strategy_snapshots": _s(
            "strategy_snapshots", lambda: _query_strategy_snapshots(db, mandate_ids)
        ),
        "protocol_baustein_selections": _s(
            "protocol_baustein_selections",
            lambda: _query_protocol_baustein_selections(db, mandate_ids),
        ),
        "audit_log": _s("audit_log", lambda: _query_audit_log(db, client_id, mandate_ids)),
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
        "complete": all(status == "ok" for status in section_status.values()),
        "section_status": section_status,
        "section_errors": section_errors,
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
# Sektions-Ausfuehrung mit sichtbarem Fehler-Reporting (PRIV-002)
# ---------------------------------------------------------------------------

# Generische, unbedenkliche Fehlerbeschreibung fuer den Export -- absichtlich
# OHNE Exception-Text/Stacktrace, da der Export einem Kunden (DSG Art. 25)
# oder Berater ausgehaendigt werden kann und keine internen Details (Tabellen-
# namen, Query-Strukturen, Stacktraces) preisgeben soll.
_SECTION_ERROR_MESSAGE = (
    "Sektion konnte nicht geladen werden (interner Fehler bei der "
    "Datenabfrage). Der Export ist dadurch unvollstaendig -- bitte "
    "Support kontaktieren und Export erneut anfordern."
)


def _run_section(
    section_status: dict[str, str],
    section_errors: dict[str, str],
    name: str,
    builder: Any,
) -> Any:
    """Fuehrt eine Sektions-Builder-Funktion aus und protokolliert Erfolg/
    Fehler sichtbar, statt ihn wie vorher lautlos zu verschlucken.

    Die Resilienz bleibt erhalten: ein Fehler in dieser einen Sektion
    crasht weiterhin nicht den gesamten Export (`except Exception` faengt
    ihn weiterhin ab). Neu ist nur, dass der Fehler jetzt im Rueckgabewert
    von `export_client_data` sichtbar wird (`section_status`,
    `section_errors`, `complete`), statt spurlos zu einer leeren Liste zu
    werden, die wie ein vollstaendiger Export aussieht.
    """
    try:
        result = builder()
    except Exception:  # noqa: BLE001 -- bewusst breit, siehe Docstring
        section_status[name] = "error"
        section_errors[name] = _SECTION_ERROR_MESSAGE
        return []
    section_status[name] = "ok"
    return result


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
    from models.profiling import ClientKnowledge
    rows = (
        db.query(ClientKnowledge)
        .filter(ClientKnowledge.client_id == client_id)
        .all()
    )
    return _serialize_list(rows)


def _query_risk_assessments(db: Session, mandate_ids: list[str]) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.profiling import RiskAssessment
    rows = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_risk_assessment_answers(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
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


def _query_suitability_checks(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.profiling import SuitabilityCheck
    rows = (
        db.query(SuitabilityCheck)
        .filter(SuitabilityCheck.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_target_allocations(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.allocation import TargetAllocation
    rows = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_recommendation_runs(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import RecommendationRun
    rows = (
        db.query(RecommendationRun)
        .filter(RecommendationRun.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_recommendation_positions(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
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


def _query_recommendation_holdings(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    """2026-09 (PRIV-002-Nachfund): `RecommendationHolding` hat KEINE
    `mandate_id`-Spalte (nur `run_id` -> `RecommendationRun.mandate_id`).
    Die vorherige Filterung auf `RecommendationHolding.mandate_id` warf
    daher IMMER einen `AttributeError`, der vom alten breiten
    `except Exception: return []` lautlos verschluckt wurde -- diese
    Sektion war im DSG-Export faktisch seit jeher immer leer, fuer jeden
    Kunden mit Recommendation-Holdings. Fix: gleiches Join-Muster wie
    `_query_recommendation_positions` (ueber `run_id`)."""
    if not mandate_ids:
        return []
    from models.review import RecommendationHolding, RecommendationRun
    run_ids = [
        str(r.id)
        for r in db.query(RecommendationRun)
        .filter(RecommendationRun.mandate_id.in_(mandate_ids))
        .all()
    ]
    if not run_ids:
        return []
    rows = (
        db.query(RecommendationHolding)
        .filter(RecommendationHolding.run_id.in_(run_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_advisory_log(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import AdvisoryLog
    rows = (
        db.query(AdvisoryLog)
        .filter(AdvisoryLog.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_wealth_positions(db: Session, client_id: str) -> list[dict[str, Any]]:
    from models.wealth import WealthPosition
    rows = (
        db.query(WealthPosition)
        .filter(WealthPosition.client_id == client_id)
        .all()
    )
    return _serialize_list(rows)


def _query_cashflows(db: Session, client_id: str) -> list[dict[str, Any]]:
    from models.wealth import Cashflow
    rows = (
        db.query(Cashflow)
        .filter(Cashflow.client_id == client_id)
        .all()
    )
    return _serialize_list(rows)


def _query_wealth_inflows(db: Session, client_id: str) -> list[dict[str, Any]]:
    from models.wealth import WealthInflow
    rows = (
        db.query(WealthInflow)
        .filter(WealthInflow.client_id == client_id)
        .all()
    )
    return _serialize_list(rows)


def _query_goals(db: Session, mandate_ids: list[str]) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.wealth import Goal
    rows = (
        db.query(Goal)
        .filter(Goal.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_planning_assumptions(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.wealth import PlanningAssumption
    rows = (
        db.query(PlanningAssumption)
        .filter(PlanningAssumption.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_contract_documents(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import ContractDocument
    rows = (
        db.query(ContractDocument)
        .filter(ContractDocument.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_conflict_disclosures(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import ConflictOfInterestDisclosure
    rows = (
        db.query(ConflictOfInterestDisclosure)
        .filter(ConflictOfInterestDisclosure.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_mandate_report_notes(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import MandateReportNotes
    rows = (
        db.query(MandateReportNotes)
        .filter(MandateReportNotes.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_review_trigger(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.review import ReviewTrigger
    rows = (
        db.query(ReviewTrigger)
        .filter(ReviewTrigger.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_protocol_baustein_selections(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    """2026-07-25 (Generalaudit, Wave-10 DSG-Fork): custom_override_md ist laut
    Modell-Docstring explizit fuer "Klienten-spezifische Erlaeuterung" gedacht --
    fehlte bisher im Auskunfts-Export (DSG Art. 25)."""
    if not mandate_ids:
        return []
    from models.protocol_bausteine import MandateBausteinSelection
    rows = (
        db.query(MandateBausteinSelection)
        .filter(MandateBausteinSelection.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_strategy_snapshots(
    db: Session, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    if not mandate_ids:
        return []
    from models.snapshots import StrategySnapshot
    rows = (
        db.query(StrategySnapshot)
        .filter(StrategySnapshot.mandate_id.in_(mandate_ids))
        .all()
    )
    return _serialize_list(rows)


def _query_audit_log(
    db: Session, client_id: str, mandate_ids: list[str]
) -> list[dict[str, Any]]:
    """Audit-Eintraege die diesen Kunden oder seine Mandate betreffen."""
    from models.review import AuditLog
    from sqlalchemy import or_
    query = db.query(AuditLog).filter(
        or_(
            AuditLog.client_id == client_id,
            AuditLog.mandate_id.in_(mandate_ids) if mandate_ids else False,
        )
    )
    return _serialize_list(query.all())
