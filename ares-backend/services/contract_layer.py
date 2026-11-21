"""L2/L3-Gate: Vertragsvorlage, Datenschutzabschnitt, Zuwendungen der
Depotbank, Gruende der Empfehlung (Art. 15 FIDLEG) und W033-Restinhalte
(H-179; Dok. 112 Kap. 4.1 und 7.1; Dok. 113 E-113-4/5).

Ein Einstieg (``contract_layer_findings``) fuer Finalisierung, Berater-
Signatur, Vor-Ort-Signatur, Vertrags-PDF und Statusanzeige. Ares erfindet
keinen Text und keinen Wert: fehlt ein freigegebener Owner-Inhalt, entsteht
ein Finding mit eigenem Reason-Code und einer Handlungsanweisung; das Gate
wirft dann ``CONTRACT_LAYER_INCOMPLETE`` mit der Liste.

Bewusst NICHT in Publikation und Portfolio-Generierung (KW47-Kernkette): die
Sperre greift an den kundenwirksamen Schritten Vertrag, Signatur,
Finalisierung und Kundendokument.

Schnittstelle P5 (Kanal-Envelope): ``contract_template_binding`` liefert die
hashbare Bindung der wirksamen Vertragsvorlage eines Mandats.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable, Optional

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, evidence_hash
from core.reason_codes import DomainError, ReasonCode
from services import owner_content as oc
from services.recommendation_release_gate import (
    CHANNEL_FINALIZATION,
    CHANNEL_SIGNATURE,
    CONTRACT_CONCLUSION_DOCUMENT_TYPES,
    _CHANNEL_LABELS,
    _call_on_block,
    mandate_tenant_id,
)
from core.presentation_rounding import format_bps_as_pct

CONTRACT_DOCUMENT_TYPE = "Beratungsvertrag"
CONTRACT_BINDING_KIND = "contract_template"
# Mandatstypen mit Eignungspruefung (W033).
SUITABILITY_MANDATE_TYPES = ("Vermögensverwaltung", "Anlageberatung")
# Ohne erfasste Depotbank fehlt die Zuwendungsangabe nur bei der Vermoegens-
# verwaltung (Verwaltungsvollmacht der Depotbank mit Zuwendungsklausel, Dok. 112
# Kap. 3.2/5). Ist eine Depotbank erfasst, ist die Angabe fuer jeden Typ Pflicht.
DEPOT_BANK_REQUIRED_MANDATE_TYPES = ("Vermögensverwaltung",)
# P-1: Gruende der Empfehlung sind fuer die Anlageberatung Pflicht (Dok. 112 7.1).
RATIONALE_MANDATE_TYPES = ("Anlageberatung",)

_ADMIN_ACTION = (
    "Firmen-Admin: unter Administration > Compliance > Vertragsschicht den Text "
    "bzw. Wert der Firma erfassen; eine zweite Person gibt ihn frei."
)


def _finding(reason_code: str, message: str, owner_action: str, scope: str, **extra: Any) -> dict:
    return {"reason_code": str(reason_code), "message": message,
            "owner_action": owner_action, "scope": scope, **extra}


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# V-1: Vertragsvorlage je Mandatstyp
# ---------------------------------------------------------------------------


def contract_template_state(db: Session, mandate: Any) -> dict:
    """Klauseln der Vertragsvorlage des Mandatstyps mit Status und Text.

    ``template_hash`` nur, wenn jede Pflichtklausel einen freigegebenen Text
    hat (typspezifisch vor gemeinsam)."""
    mandate_type = str(getattr(mandate, "mandate_type", "") or "")
    slug = oc.CONTRACT_MANDATE_TYPES.get(mandate_type)
    tenant_id = mandate_tenant_id(db, mandate)
    state: dict[str, Any] = {
        "catalog_version": oc.CATALOG_VERSION, "mandate_type": mandate_type, "supported": slug is not None,
        "tenant_id": tenant_id, "clauses": [], "missing": [], "invalid": [], "template_hash": None,
    }
    if slug is None:
        return state
    for clause in oc.CONTRACT_CLAUSE_KEYS:
        specific = oc.resolve_owner_content(db, tenant_id, oc.contract_clause_key(slug, clause))
        chosen = specific
        if specific["status"] != oc.STATUS_APPROVED:
            shared = oc.resolve_owner_content(
                db, tenant_id, oc.contract_clause_key(oc.CONTRACT_SHARED_SLUG, clause),
            )
            if shared["status"] == oc.STATUS_APPROVED or specific["status"] == oc.STATUS_MISSING:
                chosen = shared
        entry = {
            "clause": clause, "label": oc.CONTRACT_CLAUSE_LABELS[clause], "status": chosen["status"],
            "key": chosen["key"], "text": oc.approved_text(chosen),
            "binding": oc.binding_of(chosen) if chosen["status"] == oc.STATUS_APPROVED else None,
            "placeholder": next(c[3] for c in oc.CONTRACT_CLAUSES if c[0] == clause),
        }
        state["clauses"].append(entry)
        if chosen["status"] == oc.STATUS_INVALID or specific["status"] == oc.STATUS_INVALID:
            state["invalid"].append(clause)
        elif chosen["status"] != oc.STATUS_APPROVED:
            state["missing"].append(clause)
    if not state["missing"] and not state["invalid"]:
        state["template_hash"] = evidence_hash({
            "kind": CONTRACT_BINDING_KIND,
            "catalog_version": oc.CATALOG_VERSION,
            "mandate_type": mandate_type,
            "tenant_id": tenant_id,
            "clauses": [{"clause": c["clause"], **c["binding"]} for c in state["clauses"]],
        }, scheme=SCHEME_V1)
    return state


def contract_template_binding(db: Session, mandate: Any) -> Optional[dict]:
    """P5-Schnittstelle: Bindung der wirksamen Vertragsvorlage oder ``None``
    (nicht freigegeben -> P5 darf nicht siegeln, das Gate sperrt ohnehin)."""
    state = contract_template_state(db, mandate)
    if not state["template_hash"]:
        return None
    return {
        "kind": CONTRACT_BINDING_KIND,
        "catalog_version": state["catalog_version"],
        "mandate_type": state["mandate_type"],
        "template_hash": state["template_hash"],
        "clauses": [{"clause": c["clause"], **c["binding"]} for c in state["clauses"]],
    }


def _template_findings(state: dict) -> list[dict]:
    if not state["supported"]:
        return [_finding(
            ReasonCode.CONTRACT_TEMPLATE_UNAPPROVED,
            f"Für den Mandatstyp «{state['mandate_type'] or 'unbekannt'}» ist keine "
            "Vertragsvorlage vorgesehen.",
            "Owner/Compliance: Mandatstyp prüfen; Ares bildet Vertragsvorlagen nur für "
            "Vermögensverwaltung, Anlageberatung und Finanzplanung ab.",
            "tenant",
        )]
    labels_invalid = [oc.CONTRACT_CLAUSE_LABELS[c] for c in state["invalid"]]
    labels_missing = [oc.CONTRACT_CLAUSE_LABELS[c] for c in state["missing"]]
    if labels_invalid or len(labels_missing) == len(oc.CONTRACT_CLAUSE_KEYS):
        return [_finding(
            ReasonCode.CONTRACT_TEMPLATE_UNAPPROVED,
            f"Die Vertragsvorlage für «{state['mandate_type']}» ist nicht freigegeben"
            + (f" (Freigabekette ungültig: {', '.join(labels_invalid)})." if labels_invalid else "."),
            _ADMIN_ACTION, "tenant",
            missing_clauses=state["missing"], invalid_clauses=state["invalid"],
        )]
    if labels_missing:
        return [_finding(
            ReasonCode.CONTRACT_TEMPLATE_CLAUSE_MISSING,
            f"In der Vertragsvorlage für «{state['mandate_type']}» fehlen freigegebene "
            "Pflichtklauseln: " + ", ".join(labels_missing) + ".",
            _ADMIN_ACTION, "tenant", missing_clauses=state["missing"],
        )]
    return []


def contract_document_place(content_json: Any) -> str:
    try:
        parsed = json.loads(content_json) if content_json else {}
    except (TypeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("ort_unterzeichnung") or parsed.get("ort") or parsed.get("place") or "").strip()


def contract_document_binding(content_json: Any) -> Optional[str]:
    try:
        parsed = json.loads(content_json) if content_json else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    binding = parsed.get("contract_template")
    return str(binding.get("template_hash")) if isinstance(binding, dict) and binding.get("template_hash") else None


def _contract_document_findings(state: dict, document: Any) -> list[dict]:
    findings: list[dict] = []
    if not contract_document_place(getattr(document, "content_json", None)):
        findings.append(_finding(
            ReasonCode.CONTRACT_PLACE_MISSING,
            "Im Vertrag fehlt der Ort der Unterzeichnung (Pflichtfeld, kein Vorgabewert).",
            "Berater: Ort der Unterzeichnung im Vertrag erfassen und das Vertrags-PDF neu erstellen.",
            "document", document_id=getattr(document, "id", None),
        ))
    bound = contract_document_binding(getattr(document, "content_json", None))
    if state["template_hash"] and bound != state["template_hash"]:
        findings.append(_finding(
            ReasonCode.CONTRACT_TEMPLATE_OUTDATED,
            "Der Vertrag beruht nicht auf der aktuell freigegebenen Vertragsvorlage.",
            "Berater: Vertrags-PDF neu erstellen; der neue Vertrag trägt die aktuelle Vorlage.",
            "document", document_id=getattr(document, "id", None),
            document_template_hash=bound, current_template_hash=state["template_hash"],
        ))
    return findings


# ---------------------------------------------------------------------------
# D-1: Datenbearbeitung in der Kundeninformation (DSG Art. 19)
# ---------------------------------------------------------------------------


def privacy_section_state(db: Session, tenant_id: Optional[str]) -> dict:
    lines: list[tuple[str, str]] = []
    missing: list[str] = []
    bindings: list[dict] = []
    for section, label, _input, _placeholder in oc.PRIVACY_SECTIONS:
        resolution = oc.resolve_owner_content(db, tenant_id, oc.PRIVACY_KEY_PREFIX + section)
        text = oc.approved_text(resolution)
        if text is None:
            missing.append(section)
            continue
        lines.append((label, text))
        bindings.append(oc.binding_of(resolution))
    return {
        "lines": tuple(lines), "missing": missing,
        "hash": evidence_hash({"privacy": bindings}, scheme=SCHEME_V1) if not missing else None,
    }


def _privacy_findings(state: dict) -> list[dict]:
    if not state["missing"]:
        return []
    labels = [label for key, label, _i, _p in oc.PRIVACY_SECTIONS if key in state["missing"]]
    return [_finding(
        ReasonCode.CLIENT_INFORMATION_PRIVACY_MISSING,
        "Der Abschnitt Datenbearbeitung der Kundeninformation (Art. 19 DSG) ist nicht "
        "vollständig freigegeben: " + ", ".join(labels) + ".",
        _ADMIN_ACTION, "tenant", missing_sections=state["missing"],
    )]


# ---------------------------------------------------------------------------
# R-1: Zuwendungen der Depotbank
# ---------------------------------------------------------------------------


def depot_bank_inducement_state(db: Session, mandate: Any, today: Optional[str] = None) -> dict:
    """Wirksame Angabe zur Depotbank des Mandats: ``status`` ok | no_bank |
    missing | expired | not_yet_valid; ``line`` = Klartext fuer Kundendokumente."""
    today = today or _today()
    bank = str(getattr(mandate, "depot_bank", "") or "").strip()
    key = oc.depot_bank_key(bank)
    result: dict[str, Any] = {"depot_bank": bank or None, "key": key, "status": "no_bank",
                              "value": None, "line": None, "binding": None}
    if not key:
        return result
    resolution = oc.resolve_owner_content(db, mandate_tenant_id(db, mandate), key)
    value = oc.approved_value(resolution)
    if not isinstance(value, dict):
        result["status"] = "missing"
        return result
    result.update(value=value, binding=oc.binding_of(resolution))
    if str(value.get("valid_from") or "") > today:
        result["status"] = "not_yet_valid"
        return result
    if value.get("valid_until") and str(value["valid_until"]) < today:
        result["status"] = "expired"
        return result
    result["status"] = "ok"
    result["line"] = depot_bank_inducement_line(value)
    return result


def depot_bank_inducement_line(value: dict) -> str:
    """Sachliche Wiedergabe der strukturierten Owner-Angabe (kein Rechtstext)."""
    bank = str(value.get("depot_bank") or "")
    evidence = str(value.get("evidence_reference") or "")
    status = value.get("status")
    if status == "keine":
        core = "keine Zuwendungen der Depotbank an den Finanzdienstleister"
    elif status == "satz":
        core = (f"Zuwendung der Depotbank an den Finanzdienstleister: "
                f"{format_bps_as_pct(value.get('rate_bps'), decimals=2)} auf {value.get('basis')}")
    else:
        core = ("Zuwendungen der Depotbank: Verzicht des Kunden, Bandbreite "
                f"{format_bps_as_pct(value.get('range_min_bps'), decimals=2)} bis "
                f"{format_bps_as_pct(value.get('range_max_bps'), decimals=2)}")
    validity = f"gültig ab {value.get('valid_from')}"
    if value.get("valid_until"):
        validity += f" bis {value.get('valid_until')}"
    return f"Depotbank {bank}: {core} ({validity}; Beleg {evidence})."


def _depot_bank_findings(state: dict, mandate_type: str) -> list[dict]:
    status = state["status"]
    if status == "ok":
        return []
    if status == "no_bank":
        if mandate_type not in DEPOT_BANK_REQUIRED_MANDATE_TYPES:
            return []
        return [_finding(
            ReasonCode.DEPOT_BANK_INDUCEMENT_MISSING,
            "Für das Mandat ist keine Depotbank erfasst; die Angabe zu Zuwendungen der "
            "Depotbank fehlt deshalb.",
            "Berater: Depotbank im Mandat erfassen; Firmen-Admin: Zuwendungen dieser "
            "Depotbank erfassen und freigeben lassen.",
            "mandate",
        )]
    if status == "missing":
        return [_finding(
            ReasonCode.DEPOT_BANK_INDUCEMENT_MISSING,
            f"Zu Zuwendungen der Depotbank «{state['depot_bank']}» liegt keine freigegebene "
            "Angabe der Firma vor (keine / Satz und Basis / Verzicht mit Bandbreite).",
            _ADMIN_ACTION, "tenant", depot_bank=state["depot_bank"], content_key=state["key"],
        )]
    return [_finding(
        ReasonCode.DEPOT_BANK_INDUCEMENT_EXPIRED,
        f"Die freigegebene Angabe zu Zuwendungen der Depotbank «{state['depot_bank']}» ist "
        + ("abgelaufen." if status == "expired" else "noch nicht gültig."),
        _ADMIN_ACTION, "tenant", depot_bank=state["depot_bank"], content_key=state["key"],
    )]


# ---------------------------------------------------------------------------
# P-1: Gruende der Empfehlung (Art. 15 FIDLEG)
# ---------------------------------------------------------------------------


def latest_advice_rationale(db: Session, mandate_id: str, run_id: Optional[str]) -> Optional[dict]:
    if not run_id:
        return None
    row = db.execute(_sql_text(
        "SELECT * FROM advice_rationales WHERE mandate_id = :mid AND recommendation_run_id = :rid "
        "ORDER BY recorded_at DESC, id DESC LIMIT 1"
    ), {"mid": str(mandate_id), "rid": str(run_id)}).mappings().first()
    return dict(row) if row is not None else None


def _rationale_findings(db: Session, mandate: Any, run_id: Optional[str]) -> list[dict]:
    if str(getattr(mandate, "mandate_type", "") or "") not in RATIONALE_MANDATE_TYPES or not run_id:
        return []
    row = latest_advice_rationale(db, str(mandate.id), run_id)
    if row and str(row.get("client_needs") or "").strip() and str(row.get("recommendation_reasons") or "").strip():
        return []
    return [_finding(
        ReasonCode.ADVICE_RATIONALE_MISSING,
        "Für diese Empfehlung sind die Kundenbedürfnisse und die Gründe der Empfehlung "
        "nicht dokumentiert (Art. 15 FIDLEG).",
        "Berater: Bedürfnisse und Gründe der Empfehlung zur Empfehlung erfassen.",
        "mandate", recommendation_run_id=str(run_id),
    )]


# ---------------------------------------------------------------------------
# E-1: W033-Restinhalte
# ---------------------------------------------------------------------------


def current_risk_assessment(db: Session, mandate_id: str) -> Optional[dict]:
    row = db.execute(_sql_text(
        "SELECT id, investment_horizon_years FROM risk_assessments "
        "WHERE mandate_id = :mid AND is_current = 1 AND deleted_at IS NULL"
    ), {"mid": str(mandate_id)}).mappings().first()
    return dict(row) if row is not None else None


def w033_declarations(db: Session, mandate_id: str, assessment_id: str) -> list[dict]:
    return [dict(r) for r in db.execute(_sql_text(
        "SELECT * FROM w033_client_declarations WHERE mandate_id = :mid AND risk_assessment_id = :aid "
        "ORDER BY recorded_at"
    ), {"mid": str(mandate_id), "aid": str(assessment_id)}).mappings().all()]


def w033_state(db: Session, mandate: Any) -> dict:
    tenant_id = mandate_tenant_id(db, mandate)
    assessment = current_risk_assessment(db, str(mandate.id))
    declaration = oc.resolve_owner_content(db, tenant_id, oc.W033_DECLARATION_KEY)
    advice = oc.resolve_owner_content(db, tenant_id, oc.W033_HORIZON_ADVICE_KEY)
    minimum = oc.resolve_owner_content(db, tenant_id, oc.W033_MIN_HORIZON_KEY)
    distribution = oc.resolve_owner_content(db, tenant_id, oc.W033_DISTRIBUTION_KEY)
    min_value = oc.approved_value(minimum)
    min_years = int(min_value["value"]) if isinstance(min_value, dict) and isinstance(min_value.get("value"), int) else None
    state: dict[str, Any] = {
        "assessment_id": assessment["id"] if assessment else None,
        "horizon_years": (int(assessment["investment_horizon_years"])
                          if assessment and assessment.get("investment_horizon_years") is not None else None),
        "min_horizon_years": min_years,
        "declaration_text": oc.approved_text(declaration),
        "declaration_binding": oc.binding_of(declaration) if declaration["status"] == oc.STATUS_APPROVED else None,
        "advice_text": oc.approved_text(advice),
        "advice_binding": oc.binding_of(advice) if advice["status"] == oc.STATUS_APPROVED else None,
        "distribution_text": oc.approved_text(distribution),
        "declaration_confirmed": False,
        "advice_required": None,
        "advice_confirmed": False,
    }
    if assessment is None:
        return state
    rows = w033_declarations(db, str(mandate.id), str(assessment["id"]))

    def confirmed(kind: str, binding: Optional[dict]) -> bool:
        return bool(binding) and any(
            r["declaration_kind"] == kind and r["content_hash"] == binding["content_hash"] for r in rows
        )

    state["declaration_confirmed"] = confirmed("angaben_wahr_meldepflicht", state["declaration_binding"])
    if min_years is not None and state["horizon_years"] is not None:
        state["advice_required"] = state["horizon_years"] < min_years
    state["advice_confirmed"] = confirmed("horizont_abraten", state["advice_binding"])
    return state


def _w033_findings(state: dict, mandate_type: str) -> list[dict]:
    if mandate_type not in SUITABILITY_MANDATE_TYPES or state["assessment_id"] is None:
        return []
    findings: list[dict] = []
    if not state["declaration_confirmed"]:
        findings.append(_finding(
            ReasonCode.W033_DECLARATION_MISSING,
            "Die Kundenerklärung «Angaben wahr, wesentliche Änderungen werden gemeldet» zum "
            "aktuellen Risikoprofil fehlt"
            + (" (Text der Firma nicht freigegeben)." if state["declaration_binding"] is None else "."),
            (_ADMIN_ACTION if state["declaration_binding"] is None
             else "Berater: Bestätigung des Kunden zum aktuellen Risikoprofil erfassen."),
            "tenant" if state["declaration_binding"] is None else "mandate",
        ))
    if state["min_horizon_years"] is None:
        findings.append(_finding(
            ReasonCode.W033_MIN_HORIZON_UNAPPROVED,
            "Der Mindestanlagehorizont der Firma ist nicht freigegeben; Ares setzt keinen "
            "eigenen Wert.",
            _ADMIN_ACTION, "tenant",
        ))
    elif state["advice_required"] and not state["advice_confirmed"]:
        findings.append(_finding(
            ReasonCode.W033_HORIZON_ADVICE_UNCONFIRMED,
            f"Der Anlagehorizont ({state['horizon_years']} Jahre) liegt unter dem Mindesthorizont "
            f"der Firma ({state['min_horizon_years']} Jahre). Der Abraten-Hinweis und die "
            "Bestätigung des Kunden fehlen"
            + (" (Text der Firma nicht freigegeben)." if state["advice_binding"] is None else "."),
            (_ADMIN_ACTION if state["advice_binding"] is None
             else "Berater: Abraten-Hinweis abgeben und die Bestätigung des Kunden erfassen."),
            "tenant" if state["advice_binding"] is None else "mandate",
        ))
    return findings


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def contract_layer_findings(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    run_id: Optional[str] = None,
    document: Any = None,
    today: Optional[str] = None,
) -> list[dict]:
    """Alle offenen L2/L3-Punkte fuer ``channel`` (leer = frei)."""
    mandate_type = str(getattr(mandate, "mandate_type", "") or "")
    template = contract_template_state(db, mandate)
    findings = _template_findings(template)
    findings += _privacy_findings(privacy_section_state(db, mandate_tenant_id(db, mandate)))
    findings += _depot_bank_findings(depot_bank_inducement_state(db, mandate, today), mandate_type)
    findings += _w033_findings(w033_state(db, mandate), mandate_type)
    if channel == CHANNEL_FINALIZATION:
        findings += _rationale_findings(db, mandate, run_id)
    if document is not None and str(getattr(document, "document_type", "") or "") == CONTRACT_DOCUMENT_TYPE:
        findings += _contract_document_findings(template, document)
    return findings


def assert_contract_layer_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    run_id: Optional[str] = None,
    document: Any = None,
    http_status: int = 409,
    on_block: Optional[Callable[..., None]] = None,
) -> None:
    """Fail-closed: wirft ``CONTRACT_LAYER_INCOMPLETE`` (Liste ``findings``),
    BEVOR der Kanal eine Wirkung hat. Fuer die Signatur nur bei Dokumenten,
    deren Unterzeichnung den Vertragsabschluss markiert."""
    if channel == CHANNEL_SIGNATURE and document is not None and (
        str(getattr(document, "document_type", "") or "") not in CONTRACT_CONCLUSION_DOCUMENT_TYPES
    ):
        return
    findings = contract_layer_findings(db, mandate, channel=channel, run_id=run_id, document=document)
    if not findings:
        return
    if on_block is not None:
        _call_on_block(on_block, ReasonCode.CONTRACT_LAYER_INCOMPLETE.value, findings)
    raise DomainError(
        ReasonCode.CONTRACT_LAYER_INCOMPLETE,
        f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: "
        + " ".join(f["message"] for f in findings),
        http_status=http_status,
        extra={
            "channel": channel,
            "findings": findings,
            "finding_codes": [f["reason_code"] for f in findings],
        },
    )


def contract_layer_status(db: Session, mandate: Any) -> dict:
    """Anzeige fuer die Maske (gleiche Quelle wie das Gate)."""
    template = contract_template_state(db, mandate)
    w033 = w033_state(db, mandate)
    latest_run = db.execute(_sql_text(
        "SELECT id FROM recommendation_runs WHERE mandate_id = :mid ORDER BY created_at DESC, id DESC LIMIT 1"
    ), {"mid": str(mandate.id)}).first()
    return {
        "mandate_id": str(mandate.id),
        "latest_run_id": str(latest_run[0]) if latest_run is not None else None,
        "catalog_version": oc.CATALOG_VERSION,
        "contract_template": {
            "mandate_type": template["mandate_type"], "supported": template["supported"],
            "template_hash": template["template_hash"],
            "clauses": [{k: c[k] for k in ("clause", "label", "status", "key", "placeholder")}
                        for c in template["clauses"]],
        },
        "depot_bank_inducement": {
            k: v for k, v in depot_bank_inducement_state(db, mandate).items() if k != "binding"
        },
        "w033": {
            **{k: v for k, v in w033.items() if not k.endswith("_binding")},
            "declaration_content_hash": (w033["declaration_binding"] or {}).get("content_hash"),
            "advice_content_hash": (w033["advice_binding"] or {}).get("content_hash"),
        },
        "findings": contract_layer_findings(db, mandate, channel=CHANNEL_SIGNATURE),
    }
