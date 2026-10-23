"""Abgleich SAA-Anlageklassen <-> dokumentierte Kenntnisse/Erfahrungen.

KNOWLEDGE-GAP-ASSET-CLASS-001 (Variablen-Audit 2026-10-21).

Ausgangslage: Die Kenntnisse & Erfahrungen des Kunden
(``RiskAssessment.knowledge_instruments_json`` / ``knowledge_services_json``)
fliessen NIE in den Risikoscore (``services/risk_scoring.py``) und wirken
hoechstens auf Produktebene (``services/product_eligibility.py``,
Wissenskategorien je Produkt). Die strategische Allokation (SAA) konnte
deshalb Anlageklassen enthalten -- z.B. Private Equity oder Immobilienfonds --
zu denen fuer den Kunden weder Kenntnisse noch eine Aufklaerung dokumentiert
sind, ohne dass das irgendwo sichtbar wurde.

Dieses Modul ist bewusst ein reiner Hinweis-Layer:

* es aendert die Allokation NIE (keine Gewichtsverschiebung, kein Ausschluss);
* es blockiert weder Generierung noch Speichern;
* es meldet jede Luecke mit Reason-Code ``KNOWLEDGE_GAP_ASSET_CLASS`` und
  dem Handlungssatz "Kunde ueber <Klasse> informieren und dokumentieren".

Offene Compliance-Frage (Owner-Entscheid, NICHT hier entschieden): Soll eine
Luecke die Strategie blockieren (fail-closed wie die Produkt-Eignung) oder
bleibt sie ein dokumentationspflichtiger Hinweis? Bis zum Entscheid gilt
"Hinweis" -- siehe ``COMPLIANCE_OPEN_QUESTION``.

Mapping SAA -> Fragebogen-Zeile
-------------------------------
Abgeleitet aus dem bestehenden Code, nicht erfunden:

* Fragebogen-Zeilen (``knowledge_instruments_json``-Schluessel) =
  ``data-row`` der Kenntnis-Tabelle im Monolithen
  (``5eyes_v2.html``, Tabelle "Finanzinstrumente"): Anlagefonds, Aktien,
  Obligationen, Geldmarktprodukte, Immobilien, Infrastruktur, Edelmetalle.
* SAA-Anlageklassen-Labels = ``_ASSET_CLASS_LABEL_TO_BUCKET`` in
  ``services/portfolio_engine.py`` (Aktien, Obligationen, Immobilien,
  Alternative, Liquiditaet); Sub-Klassen = ``_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS``
  bzw. die Splits in ``services/portfolio_engine_house_matrix.py``.
* Aktien/Obligationen/Immobilien tragen in SAA und Fragebogen denselben Namen.
  Immobilien in der SAA sind Fonds/REITs (Direkt-only ist nicht umsetzbar,
  ``portfolio_engine_house_matrix``); die Produktebene ordnet Immobilienfonds
  bewusst NICHT der Kategorie ``funds_etf`` zu (``map_product_to_knowledge_
  categories``) -- folglich deckt "Anlagefonds" Immobilien hier ebenfalls
  nicht ab.
* "Gold / Rohstoffe" -> Edelmetalle; Geldmarktfonds/Festgeld ->
  Geldmarktprodukte; Kontoguthaben ist kein Finanzinstrument (keine Zeile
  noetig).
* Liquid Alternatives, Hedge Funds, Private Equity, Krypto: der Fragebogen
  hat dafuer KEINE Zeile -- Kenntnis ist im heutigen Fragebogen nicht
  dokumentierbar, die Luecke wird darum immer gemeldet (Fragebogen bleibt
  bewusst unveraendert; Erweiterung = Owner-Entscheid).
* Unbekannte Sub-Klassen (z.B. andere Jurisdiktion) fallen auf das Mapping
  ihrer Anlageklasse zurueck; unbekannte Alternative-Sub-Klassen gelten
  konservativ als "keine Zeile".

"Dokumentiert" heisst: Zeile mit ``known`` ODER ``informed`` (bzw. Legacy
``has_experience``/bool) -- identische Semantik wie
``routers/pdf_reports._knowledge_map_from_json``. Eine erhaltene Aufklaerung
gilt als dokumentierte Information.

Professionelle/institutionelle Kunden: Art. 13 Abs. 3 FIDLEG -- Kenntnisse
und Erfahrung werden vermutet (gleiche Lesart wie
``services/suitability_audit.py``); Status ``presumed``, keine Luecke.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

REASON_CODE = "KNOWLEDGE_GAP_ASSET_CLASS"
CHECK_VERSION = "knowledge-asset-class-v1"

STATUS_OK = "ok"
STATUS_GAP = "gap"
STATUS_PRESUMED = "presumed"
STATUS_NOT_EVALUABLE = "not_evaluable"

COMPLIANCE_OPEN_QUESTION = (
    "Owner-Entscheid offen: Soll eine Kenntnisluecke zu einer SAA-Anlageklasse "
    "die Strategie blockieren oder (wie heute) nur als dokumentationspflichtiger "
    "Hinweis erscheinen?"
)

# Fragebogen-Zeilen (Monolith, Tabelle Finanzinstrumente, data-row).
QUESTIONNAIRE_INSTRUMENT_ROWS: tuple[str, ...] = (
    "Anlagefonds", "Aktien", "Obligationen", "Geldmarktprodukte",
    "Immobilien", "Infrastruktur", "Edelmetalle",
)

# Sentinel: fuer diese Klasse existiert keine Fragebogen-Zeile.
NO_QUESTIONNAIRE_ROW: tuple[str, ...] = ()

_ASSET_CLASS_ALIASES = {
    "liquidität": "Liquiditaet",
    "liquiditat": "Liquiditaet",
    "liquiditaet": "Liquiditaet",
    "aktien": "Aktien",
    "obligationen": "Obligationen",
    "immobilien": "Immobilien",
    "alternative": "Alternative",
    "alternativen": "Alternative",
}

# Anlageklasse -> erforderliche Fragebogen-Zeile(n) (Fallback je Klasse).
ASSET_CLASS_TO_ROWS: dict[str, tuple[str, ...] | None] = {
    "Aktien": ("Aktien",),
    "Obligationen": ("Obligationen",),
    "Immobilien": ("Immobilien",),
    "Alternative": NO_QUESTIONNAIRE_ROW,
    "Liquiditaet": ("Geldmarktprodukte",),
}

# Sub-Klasse -> Zeile(n); None = kein Kenntnisbedarf (kein Finanzinstrument).
SUB_CLASS_TO_ROWS: dict[str, tuple[str, ...] | None] = {
    "Gold / Rohstoffe": ("Edelmetalle",),
    "Liquid Alternatives": NO_QUESTIONNAIRE_ROW,
    "Hedge Funds": NO_QUESTIONNAIRE_ROW,
    "Private Equity": NO_QUESTIONNAIRE_ROW,
    "Krypto": NO_QUESTIONNAIRE_ROW,
    "Geldmarktfonds": ("Geldmarktprodukte",),
    "Festgeld": ("Geldmarktprodukte",),
    "Kontoguthaben": None,
}

_BUCKET_FIELDS = (
    ("Aktien", "target_equities_bps"),
    ("Obligationen", "target_bonds_bps"),
    ("Immobilien", "target_real_estate_bps"),
    ("Alternative", "target_alternatives_bps"),
    ("Liquiditaet", "target_liquidity_bps"),
)

_PROFESSIONAL_CLASSIFICATIONS = {"Professioneller Kunde", "Institutioneller Kunde"}


def _canonical_asset_class(raw: Any) -> str:
    text = str(raw or "").strip()
    return _ASSET_CLASS_ALIASES.get(text.lower(), text)


def documented_instrument_rows(raw: Any) -> set[str]:
    """Fragebogen-Zeilen mit dokumentierter Kenntnis ODER Aufklaerung."""
    if isinstance(raw, Mapping):
        parsed: Any = raw
    else:
        if not raw:
            return set()
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return set()
    if not isinstance(parsed, Mapping):
        return set()
    covered: set[str] = set()
    for key, value in parsed.items():
        if isinstance(value, Mapping):
            ok = bool(value.get("known") or value.get("informed") or value.get("has_experience"))
        else:
            ok = bool(value)
        if ok:
            covered.add(str(key).strip())
    return covered


def required_rows_for(asset_class: str, sub_asset_class: str | None) -> tuple[str, ...] | None:
    """Erforderliche Fragebogen-Zeilen; None = kein Kenntnisbedarf,
    ``()`` = Klasse ist im Fragebogen nicht dokumentierbar."""
    sub = str(sub_asset_class or "").strip()
    if sub in SUB_CLASS_TO_ROWS:
        return SUB_CLASS_TO_ROWS[sub]
    canonical = _canonical_asset_class(asset_class)
    if canonical in ASSET_CLASS_TO_ROWS:
        return ASSET_CLASS_TO_ROWS[canonical]
    # Unbekannte Anlageklasse: konservativ als nicht dokumentierbar melden.
    return NO_QUESTIONNAIRE_ROW


def _fmt_pct(bps: int) -> str:
    return f"{bps / 100:.1f}".replace(".", ",") + " %"


def _finding_message(label: str, weight_bps: int, rows: tuple[str, ...]) -> str:
    if rows:
        row_text = ", ".join(f"«{r}»" for r in rows)
        basis = (
            f"für die weder Kenntnisse noch eine Aufklärung dokumentiert sind "
            f"(Fragebogen-Zeile {row_text})"
        )
    else:
        basis = (
            "für die weder Kenntnisse noch eine Aufklärung dokumentiert sind "
            "(der Kenntnis-Fragebogen enthält dafür keine eigene Zeile)"
        )
    return (
        f"Kenntnislücke [{REASON_CODE}]: Die SAA enthält {label} "
        f"({_fmt_pct(weight_bps)}), {basis}. "
        f"Kunde über {label} informieren und dokumentieren."
    )


def evaluate_knowledge_gaps(
    sub_allocations: Iterable[Mapping[str, Any]] | None,
    knowledge_instruments: Any,
    *,
    client_classification: str | None = None,
    is_professional_opt_out: Any = 0,
) -> dict:
    """Reine Funktion: SAA-Sleeves gegen dokumentierte Kenntnisse pruefen.

    Gruppierung: Sleeves mit derselben Fragebogen-Zeile werden zu EINEM
    Befund zusammengefasst (Label = Zeile, z.B. "Aktien"); Sleeves ohne
    Fragebogen-Zeile erscheinen einzeln mit ihrem Sub-Klassen-Label
    (z.B. "Private Equity").
    """
    classification = str(client_classification or "").strip()
    base = {
        "version": CHECK_VERSION,
        "reason_code": None,
        "findings": [],
        "advisory_only": True,
        "compliance_open_question": COMPLIANCE_OPEN_QUESTION,
    }
    if classification in _PROFESSIONAL_CLASSIFICATIONS or bool(int(is_professional_opt_out or 0)):
        base["status"] = STATUS_PRESUMED
        base["basis"] = "Art. 13 Abs. 3 FIDLEG (Kenntnisse/Erfahrung vermutet)"
        return base

    covered = documented_instrument_rows(knowledge_instruments)
    groups: dict[str, dict[str, Any]] = {}
    for sleeve in sub_allocations or []:
        if not isinstance(sleeve, Mapping):
            continue
        weight = int(sleeve.get("target_weight_bps") or 0)
        if weight <= 0:
            continue
        asset_class = _canonical_asset_class(sleeve.get("asset_class"))
        sub = str(sleeve.get("sub_asset_class") or "").strip()
        rows = required_rows_for(asset_class, sub)
        if rows is None:
            continue
        if rows and any(r in covered for r in rows):
            continue
        label = rows[0] if rows else (sub or asset_class)
        key = f"row:{rows[0]}" if rows else f"sub:{asset_class}:{label}"
        group = groups.setdefault(key, {
            "reason_code": REASON_CODE,
            "label": label,
            "asset_class": asset_class,
            "sub_asset_classes": [],
            "required_questionnaire_rows": list(rows),
            "questionnaire_row_available": bool(rows),
            "target_weight_bps": 0,
        })
        if sub and sub not in group["sub_asset_classes"]:
            group["sub_asset_classes"].append(sub)
        group["target_weight_bps"] += weight

    findings = sorted(groups.values(), key=lambda g: (-g["target_weight_bps"], g["label"]))
    for finding in findings:
        finding["action"] = f"Kunde über {finding['label']} informieren und dokumentieren."
        finding["message"] = _finding_message(
            finding["label"], finding["target_weight_bps"],
            tuple(finding["required_questionnaire_rows"]),
        )
    base["findings"] = findings
    base["status"] = STATUS_GAP if findings else STATUS_OK
    base["reason_code"] = REASON_CODE if findings else None
    return base


def sub_allocations_from_target_allocation(allocation: Any) -> list[dict]:
    """Persistierte Sleeves einer TargetAllocation; Fallback auf die Buckets."""
    raw = getattr(allocation, "sub_allocations_json", None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [s for s in parsed if isinstance(s, Mapping)]
        except (TypeError, ValueError):
            pass
    return [
        {"asset_class": label, "sub_asset_class": None,
         "target_weight_bps": int(getattr(allocation, field, 0) or 0)}
        for label, field in _BUCKET_FIELDS
    ]


def evaluate_for_payload(payload: Mapping[str, Any], mandate: Any, assessment: Any) -> dict:
    client = getattr(mandate, "client", None)
    return evaluate_knowledge_gaps(
        payload.get("sub_allocations") or [],
        getattr(assessment, "knowledge_instruments_json", None),
        client_classification=getattr(client, "client_classification", None),
        is_professional_opt_out=getattr(client, "is_professional_opt_out", 0),
    )


def _not_evaluable(reason: str) -> dict:
    return {
        "version": CHECK_VERSION,
        "status": STATUS_NOT_EVALUABLE,
        "reason_code": None,
        "findings": [],
        "advisory_only": True,
        "compliance_open_question": COMPLIANCE_OPEN_QUESTION,
        "not_evaluable_reason": reason,
    }


def reasoning_lines(result: Mapping[str, Any] | None) -> list[str]:
    if not result or result.get("status") != STATUS_GAP:
        return []
    return [str(f.get("message") or "") for f in result.get("findings") or [] if f.get("message")]


def attach_to_strategy_payload(payload: dict, mandate: Any, assessment: Any) -> dict:
    """Haengt den Abgleich an eine Strategie-Antwort (Feld + Reasoning).

    Aendert keine Gewichte. Fehler im Hinweis-Layer duerfen die Strategie nie
    verhindern; sie werden als ``not_evaluable`` sichtbar, nie als ``ok``.
    """
    try:
        result = evaluate_for_payload(payload, mandate, assessment)
    except Exception as exc:  # noqa: BLE001 -- Hinweis-Layer
        logger.exception("Knowledge gap check failed for mandate %s", getattr(mandate, "id", "?"))
        result = _not_evaluable(f"Prüfung fehlgeschlagen: {type(exc).__name__}")
    payload["knowledge_asset_class_check"] = result
    lines = reasoning_lines(result)
    if lines:
        existing = [line for line in list(payload.get("reasoning") or []) if line not in lines]
        payload["reasoning"] = existing + lines
    return payload


def protocol_hints_for_mandate(db: Any, mandate: Any, allocation: Any) -> list[str]:
    """Saetze fuer das Beratungsprotokoll-PDF (leer ohne Luecke)."""
    if allocation is None:
        return []
    from services.portfolio_engine import _current_risk_assessment_or_none

    assessment = _current_risk_assessment_or_none(db, mandate.id)
    if assessment is None:
        return []
    client = getattr(mandate, "client", None)
    result = evaluate_knowledge_gaps(
        sub_allocations_from_target_allocation(allocation),
        getattr(assessment, "knowledge_instruments_json", None),
        client_classification=getattr(client, "client_classification", None),
        is_professional_opt_out=getattr(client, "is_professional_opt_out", 0),
    )
    return reasoning_lines(result)


__all__ = [
    "REASON_CODE",
    "COMPLIANCE_OPEN_QUESTION",
    "QUESTIONNAIRE_INSTRUMENT_ROWS",
    "evaluate_knowledge_gaps",
    "documented_instrument_rows",
    "required_rows_for",
    "attach_to_strategy_payload",
    "sub_allocations_from_target_allocation",
    "protocol_hints_for_mandate",
    "reasoning_lines",
]
