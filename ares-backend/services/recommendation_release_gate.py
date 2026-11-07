"""Zentrales Risk-Budget-Freigabe-Gate (RISK-BUDGET-FINALIZATION-001, Rest).

Vorher pruefte NUR die Finalisierung (routers/review.py::
_validate_recommendation_for_finalization) die Risikobudget-Treue der
verankerten Soll-Allokation -- und selbst dort war ein fehlender
Ist-Risikoanteil nur eine Warnung. Die staerkeren Freigabekanaele
(Advisory-Report-PDF, Signatur eines Empfehlungsdokuments, Weiterleitung
an das Asset Management) riefen die Pruefung gar nicht auf: eine
Allokation, die das Risikobudget des Kunden verletzt oder deren
Budget-Treue nicht belegbar ist, konnte damit als Kunden-PDF exportiert,
unterzeichnet oder zur Ausfuehrung weitergeleitet werden.

Diese Datei ist die EINE Quelle der Pruefung:

- ``risk_budget_release_findings(allocation)`` -- reine Pruefung der
  typisierten Spalten ``risk_budget_bps_at_generation`` und
  ``risky_fraction_bps_at_generation`` der verankerten Allokation. Die
  Finalisierung nutzt sie fuer ihre Fehlerliste (422 wie bisher).
- ``assert_recommendation_release_eligible(...)`` -- das Gate fuer die
  Freigabekanaele. Wirft ``DomainError`` (409) mit stabilem Reason-Code,
  BEVOR der Kanal irgendeine Wirkung hat (kein PDF, keine Signatur, kein
  Handoff).

Fail-closed: fehlt der Nachweis (Budget oder Ist-Risikoanteil fehlt bzw.
ist nicht lesbar), wird blockiert -- "nicht belegbar" ist nicht
"eingehalten". Heilmittel ist immer dasselbe: Allokation neu generieren
(liefert den Nachweis) bzw. Risikoprofil/Bausteine anpassen (bei
Verletzung).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session

from core.reason_codes import DomainError

RISK_BUDGET_EVIDENCE_MISSING = "RISK_BUDGET_EVIDENCE_MISSING"
RISK_BUDGET_VIOLATED = "RISK_BUDGET_VIOLATED"
RELEASE_ALLOCATION_MISSING = "RELEASE_ALLOCATION_MISSING"

CHANNEL_ADVISORY_PDF = "advisory_pdf"
CHANNEL_SIGNATURE = "signature"
CHANNEL_HANDOFF = "handoff"
# H8: Finalisierung als eigener Kanal des Kundeninformations-/KYC-Gates.
CHANNEL_FINALIZATION = "finalization"

_CHANNEL_LABELS = {
    CHANNEL_ADVISORY_PDF: "Der Advisory-Report kann nicht exportiert werden",
    CHANNEL_SIGNATURE: "Das Dokument kann nicht unterzeichnet werden",
    CHANNEL_HANDOFF: "Die Handelsliste kann nicht weitergeleitet werden",
    CHANNEL_FINALIZATION: "Die Empfehlung kann nicht finalisiert werden",
}

# Dokumenttypen, die die Anlageempfehlung/Soll-Allokation verkoerpern. Ein
# Beratungsvertrag, eine Risikoprofilierung oder "Sonstiges" haengen nicht
# an der Allokation und bleiben unabhaengig vom Risikobudget signierbar.
RECOMMENDATION_DOCUMENT_TYPES = frozenset({
    "Anlagestrategie",
    "Anlagerezept",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
})

_EVIDENCE_MISSING_MESSAGE = (
    "Die Einhaltung des Risikobudgets ist für die aktuelle Soll-Allokation "
    "nicht nachgewiesen (Risikobudget oder Ist-Risikoanteil fehlt bzw. ist "
    "nicht lesbar). Bitte die Allokation neu generieren, damit der Nachweis "
    "vorliegt."
)


def risk_budget_release_findings(allocation: Any) -> list[tuple[str, str]]:
    """``[(reason_code, message)]`` fuer die Risikobudget-Treue der Allokation.

    Leere Liste = Nachweis vorhanden und Budget eingehalten.
    """
    budget = getattr(allocation, "risk_budget_bps_at_generation", None)
    realized = getattr(allocation, "risky_fraction_bps_at_generation", None)
    if budget is None or realized is None:
        return [(RISK_BUDGET_EVIDENCE_MISSING, _EVIDENCE_MISSING_MESSAGE)]
    try:
        budget_int = int(budget)
        realized_int = int(realized)
    except (TypeError, ValueError):
        return [(RISK_BUDGET_EVIDENCE_MISSING, _EVIDENCE_MISSING_MESSAGE)]
    if realized_int > budget_int:
        # Zahlen in die Meldung: der Berater muss sehen, WIE weit er
        # darueber liegt, um Risikoprofil oder Bausteine als Stellschraube
        # zu waehlen.
        return [(
            RISK_BUDGET_VIOLATED,
            "Die Soll-Allokation verletzt das Risikobudget des "
            f"Risikoprofils: Ist-Risikoanteil {realized_int / 100:.2f} % "
            f"gegen Budget {budget_int / 100:.2f} %. Risikoprofil oder "
            "Bausteine anpassen und die Allokation neu generieren.",
        )]
    return []


def risk_budget_release_errors(allocation: Any) -> list[str]:
    """Nur die Meldungen -- fuer die Fehlerliste der Finalisierung."""
    return [message for _code, message in risk_budget_release_findings(allocation)]


def _current_allocation(db: Session, mandate: Any) -> Any:
    from models.allocation import TargetAllocation

    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )


def _run_allocation(db: Session, mandate: Any, run: Any) -> Any:
    from models.allocation import TargetAllocation

    if not getattr(run, "target_allocation_id", None):
        return None
    return (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.id == run.target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )


def assert_recommendation_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    run: Optional[Any] = None,
) -> None:
    """Zentrales Freigabe-Gate fuer PDF, Signatur und Handoff.

    Bezug:
    - mit ``run`` (Handoff): die im Run verankerte Allokation. Ein Run ohne
      gueltige Allokation ist nicht freigebbar (409).
    - ohne ``run`` (Advisory-PDF, Signatur): die aktuelle Soll-Allokation
      des Mandats -- genau die, die der Advisory-Report publiziert
      (services/advisory_report.py::_cached_current_ta). Existiert keine,
      wird keine Strategie publiziert und es gibt kein Risikobudget zu
      belegen.

    Wirft ``DomainError`` (409, detail={reason_code, message, channel, ...});
    neben dem Risikobudget auch ``CMA_ADR12A_HOLD`` (KGV-aktive CMA).
    """
    if run is not None:
        allocation = _run_allocation(db, mandate, run)
        if allocation is None:
            raise DomainError(
                RELEASE_ALLOCATION_MISSING,
                (
                    f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: "
                    "die Empfehlung ist keiner gültigen Soll-Allokation "
                    "zugeordnet. Bitte die Allokation neu generieren."
                ),
                http_status=409,
                extra={"channel": channel},
            )
    else:
        allocation = _current_allocation(db, mandate)
        if allocation is None:
            return
    # CMA-001 / ADR-12a-Release-Hold: keine Freigabe, solange die CMA der
    # Allokation eine ungeklaerte KGV-Bewertungsanpassung traegt
    # (services/cma_valuation_hold.py).
    from services.cma_valuation_hold import assert_allocation_cma_without_adr12a_hold

    assert_allocation_cma_without_adr12a_hold(
        db,
        allocation,
        channel=channel,
        channel_label=_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich"),
    )
    findings = risk_budget_release_findings(allocation)
    if not findings:
        return
    reason_code, message = findings[0]
    raise DomainError(
        reason_code,
        (
            f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}. "
            f"{message}"
        ),
        http_status=409,
        extra={
            "channel": channel,
            "target_allocation_id": getattr(allocation, "id", None),
        },
    )


# ---------------------------------------------------------------------------
# Risikoprofil-Signoff (CIO-Entscheid 2026-10-24)
# ---------------------------------------------------------------------------
#
# Ein Signoff im Zustand ``integrity_mismatch`` (Zeile oder fachliche Bindung
# passt nicht mehr zum Assessment, services/risk_profile_signoff.py::
# verify_signoff_binding) wurde in Kundendokumenten bisher nur als "nicht
# gueltig" ausgewiesen. Jetzt sperren dieselben Freigabekanaele fail-closed.
# Legacy-Zustaende (unsigniert, Altsignatur ohne Signoff, "neue Signatur
# erforderlich") bleiben wie bisher -- sie behaupten keine gueltige Signatur.
# Der interne Advisory-Report zeigt den Zustand weiter an; die
# Kundenportal-Sicht desselben Reports ist gesperrt (neutrale Meldung).

RISK_PROFILE_SIGNOFF_MISMATCH = "RISK_PROFILE_SIGNOFF_MISMATCH"

CHANNEL_CLIENT_PDF = "client_pdf"
_CHANNEL_LABELS[CHANNEL_CLIENT_PDF] = "Das Kundendokument kann nicht erstellt werden"
CHANNEL_CLIENT_PORTAL = "client_portal"
_CHANNEL_LABELS[CHANNEL_CLIENT_PORTAL] = "Der Kundenportal-Bericht kann nicht angezeigt werden"

# Neutrale Kundenmeldung (Kundenportal): keine internen Details, der
# Reason-Code steht nur in Log und Audit.
CLIENT_PORTAL_UNAVAILABLE_MESSAGE = (
    "Ihr Bericht wird derzeit aktualisiert – bitte wenden Sie sich an Ihre "
    "Beraterin oder Ihren Berater."
)

# Kundenrelevante bzw. kundensignierbare Dokumenttypen, die das Risikoprofil
# des Kunden tragen und deshalb eine gueltige Signoff-Bindung voraussetzen.
SIGNOFF_BOUND_DOCUMENT_TYPES = frozenset({
    "Anlagestrategie",
    "Risikoprofilierung",
    "Beratungsprotokoll",
    "Eignungsprüfung",
    "Override-Zustimmung",
    "Kostenausweis",
    "Anlagerezept",
})

_SIGNOFF_MISMATCH_MESSAGE = (
    "Die Risikoprofil-Signatur passt nicht mehr zum gespeicherten Profil – "
    "Profil prüfen und neu signieren."
)


def assert_risk_signoff_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
) -> None:
    """409, wenn der Signoff des aktuellen Risikoprofils ``integrity_mismatch``
    ist -- dieselbe Pruefung wie API/PDF-Anzeige (``signoff_state`` +
    ``resolve_signoff_binding``), VOR jeder Wirkung des Kanals.

    Ohne aktuelles Risikoprofil oder ohne gebundene Signatur passiert nichts
    (unveraendertes Verhalten; andere Gates sind dafuer zustaendig)."""
    from services.portfolio_engine import _current_risk_assessment_or_none
    from services.risk_profile_signoff import (
        STATUS_SIGNED,
        resolve_signoff_binding,
        signoff_state,
    )

    try:
        assessment = _current_risk_assessment_or_none(db, mandate.id)
    except ValueError:
        # Mehrdeutiger Anker: eigener Fehlerpfad der Kanaele, hier nichts
        # zusaetzlich zu belegen.
        return
    if assessment is None or signoff_state(assessment) != STATUS_SIGNED:
        return
    binding = resolve_signoff_binding(db, assessment)
    if binding is not None and binding.verified:
        return
    mismatches = list(binding.mismatches) if binding is not None else ["signoff_missing"]
    if binding is not None and not binding.row_verified and "signoff_row" not in mismatches:
        mismatches.append("signoff_row")
    raise DomainError(
        RISK_PROFILE_SIGNOFF_MISMATCH,
        (
            f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}. "
            f"{_SIGNOFF_MISMATCH_MESSAGE}"
        ),
        http_status=409,
        extra={
            "channel": channel,
            "risk_assessment_id": getattr(assessment, "id", None),
            "signoff_id": getattr(assessment, "signoff_id", None),
            "integrity_mismatches": mismatches,
        },
    )


def assert_current_allocation_without_adr12a_hold(
    db: Session,
    mandate: Any,
    *,
    channel: str,
) -> None:
    """CMA-001 / ADR-12a-Release-Hold fuer Kundenkanaele ohne Risikobudget-
    Gate (Kunden-PDFs mit Strategie/Positionen, Kundenportal): 409
    ``CMA_ADR12A_HOLD``, wenn die CMA der aktuellen Soll-Allokation eine
    ungeklaerte KGV-Bewertungsanpassung traegt. Ohne aktuelle Allokation
    wird keine Strategie publiziert -- nichts zu sperren."""
    from services.cma_valuation_hold import assert_allocation_cma_without_adr12a_hold

    allocation = _current_allocation(db, mandate)
    if allocation is None:
        return
    assert_allocation_cma_without_adr12a_hold(
        db,
        allocation,
        channel=channel,
        channel_label=_CHANNEL_LABELS.get(channel, "Freigabe nicht möglich"),
    )


# ---------------------------------------------------------------------------
# H8 C-2 (Compliance-Audit 2026-11-07, Luecke 2):
# Kundeninformation nach Art. 8/9 FIDLEG als Gate vor Finalisierung und
# Vertragsunterzeichnung.
# ---------------------------------------------------------------------------
#
# Fail-closed, ohne Override:
# - Rechtliche Angaben der Firma (models/tenant.py::TenantLegalProfile) fehlen
#   oder sind unvollstaendig -> Sperre mit Liste der fehlenden Angaben. Ares
#   belegt keinen Wert vor (keine Firma, Adresse, Ombudsstelle, Aufsicht).
# - Sitz ausserhalb der abgebildeten Regime (heute nur Schweiz = FIDLEG) ->
#   Sperre statt stiller Freigabe.
# - Kein gueltiger Abgabenachweis der Kundeninformation (archiviertes PDF,
#   Byte-Hash stimmt) oder Abgabe erst NACH dem Vertragsabschluss -> Sperre.
#
# Gelesen wird per SQL (Muster H7 N-884-04 oben): dieses Modul ist das eine
# Freigabe-Gate der Kanaele und bekommt dafuer keine neuen Modulkanten.

CLIENT_ONBOARDING_INCOMPLETE = "CLIENT_ONBOARDING_INCOMPLETE"
CLIENT_INFORMATION_TENANT_DATA_MISSING = "CLIENT_INFORMATION_TENANT_DATA_MISSING"
CLIENT_INFORMATION_REGIME_UNSUPPORTED = "CLIENT_INFORMATION_REGIME_UNSUPPORTED"
CLIENT_INFORMATION_NOT_DELIVERED = "CLIENT_INFORMATION_NOT_DELIVERED"
CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT = "CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT"


CLIENT_INFORMATION_DOCUMENT_TYPE = "Kundeninformation"
CLIENT_INFORMATION_TEMPLATE_VERSION = "ARES-KI-FIDLEG-1"
# Dokumenttypen, deren Unterzeichnung den Vertragsabschluss markiert. Die
# Kundeninformation muss VOR der ersten Unterschrift auf einem davon liegen.
CONTRACT_CONCLUSION_DOCUMENT_TYPES = frozenset({
    "Beratungsvertrag",
    "Anlagestrategie",
    "Anlagerezept",
})
# Sitzlaender, fuer die Ares ein Informationsregime abbildet (Art. 8/9 FIDLEG).
CLIENT_INFORMATION_SEAT_REGIMES = {"CH": "FIDLEG"}

CLIENT_INFORMATION_DELIVERY_CHANNELS = (
    "persoenlich_papier",
    "post",
    "email",
    "kundenportal",
)

# (Feld, Bezeichnung fuer den Owner-Hinweis) -- Reihenfolge = Anzeige.
LEGAL_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("legal_name", "Firma (vollstaendiger Name)"),
    ("address_street", "Adresse: Strasse und Nummer"),
    ("address_postal_code", "Adresse: PLZ"),
    ("address_city", "Adresse: Ort"),
    ("address_country", "Adresse: Land (Sitz, ISO-Code)"),
    ("business_activity", "Taetigkeitsfeld"),
    ("supervision_type", "Aufsichtsstatus"),
    ("supervisory_authority", "Aufsichtsbehoerde"),
    ("supervisory_organisation", "Aufsichtsorganisation (AO)"),
    ("license_reference", "Bewilligungs- bzw. Registerangabe"),
    ("ombudsman_name", "Ombudsstelle: Name"),
    ("ombudsman_address", "Ombudsstelle: Adresse"),
    ("contact_phone", "Kontakt: Telefon"),
    ("contact_email", "Kontakt: E-Mail"),
    ("contact_website", "Kontakt: Website"),
)
_LEGAL_PROFILE_LABELS = dict(LEGAL_PROFILE_FIELDS)
_BASE_REQUIRED = (
    "legal_name", "address_street", "address_postal_code", "address_city",
    "address_country", "business_activity", "supervision_type",
    "ombudsman_name", "ombudsman_address",
)
# Aufsichtsstatus -> zusaetzlich verlangte Angaben (Werte aus models/tenant.py).
SUPERVISION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "vermoegensverwalter_finig": ("supervisory_authority", "supervisory_organisation"),
    "andere_finma_bewilligung": ("supervisory_authority",),
    "anlageberater_ohne_prudenzielle_aufsicht": ("license_reference",),
}
SUPERVISION_LABELS: dict[str, str] = {
    "vermoegensverwalter_finig": "Vermoegensverwalter mit Bewilligung der FINMA (FINIG)",
    "andere_finma_bewilligung": "Finanzinstitut mit anderer Bewilligung der FINMA",
    "anlageberater_ohne_prudenzielle_aufsicht": (
        "Kundenberater ohne prudenzielle Aufsicht (Eintrag in einem Beraterregister)"
    ),
}
_OWNER_PROFILE_ACTION = (
    "Ein Firmen-Admin ergaenzt unter Administration > Rechtliche Angaben "
    "(Kundeninformation FIDLEG): "
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def legal_profile_missing_fields(profile: Optional[dict]) -> list[str]:
    """Fehlende Pflichtangaben (Feldnamen) der rechtlichen Angaben."""
    profile = profile or {}
    missing = [name for name in _BASE_REQUIRED if not _clean(profile.get(name))]
    supervision = _clean(profile.get("supervision_type"))
    if supervision and supervision not in SUPERVISION_REQUIREMENTS:
        missing.append("supervision_type")
    for name in SUPERVISION_REQUIREMENTS.get(supervision, ()):
        if not _clean(profile.get(name)):
            missing.append(name)
    if not (_clean(profile.get("contact_phone")) or _clean(profile.get("contact_email"))):
        missing.append("contact_phone")
    seen: set[str] = set()
    return [name for name in missing if not (name in seen or seen.add(name))]


def legal_profile_hash(profile: Optional[dict]) -> str:
    """SHA-256 ueber die kanonischen Inhaltsfelder (ohne Metadaten)."""
    payload = {name: _clean((profile or {}).get(name)) for name, _label in LEGAL_PROFILE_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_tenant_legal_profile(db: Session, tenant_id: Optional[str]) -> Optional[dict]:
    if not tenant_id:
        return None
    row = db.execute(
        _sql_text("SELECT * FROM tenant_legal_profiles WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).mappings().first()
    return dict(row) if row is not None else None


# Gleicher Wert wie models/tenant.py::DEFAULT_TENANT_ID (Test
# test_h8_c2_client_information prueft die Gleichheit); hier als Literal,
# damit das Freigabe-Gate keine neue Modulkante bekommt.
_DEFAULT_TENANT_ID = "main"


def mandate_tenant_id(db: Session, mandate: Any) -> str:
    """Mandant des Mandats: eigene Spalte, sonst die des Kunden, sonst der
    Standard-Mandant -- dieselbe Semantik wie routers/mandates.py (Anlage)
    und services/auth.py::_resolve_tenant_id_for_user (NULL = 'main', Tier 1)."""
    tenant_id = getattr(mandate, "tenant_id", None)
    if tenant_id:
        return str(tenant_id)
    row = db.execute(
        _sql_text("SELECT tenant_id FROM clients WHERE id = :cid"),
        {"cid": str(getattr(mandate, "client_id", "") or "")},
    ).first()
    return str(row[0]) if row is not None and row[0] else _DEFAULT_TENANT_ID


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _finding(reason_code: str, message: str, owner_action: str, scope: str, **extra: Any) -> dict:
    return {"reason_code": reason_code, "message": message,
            "owner_action": owner_action, "scope": scope, **extra}


def contract_concluded_at(db: Session, mandate_id: str) -> Optional[str]:
    """Fruehester Signaturzeitpunkt eines Vertragsdokuments (Vertragsabschluss)."""
    placeholders = ", ".join(f":t{i}" for i in range(len(CONTRACT_CONCLUSION_DOCUMENT_TYPES)))
    params = {f"t{i}": value for i, value in enumerate(sorted(CONTRACT_CONCLUSION_DOCUMENT_TYPES))}
    params["mid"] = str(mandate_id)
    row = db.execute(
        _sql_text(
            "SELECT MIN(signed_at) FROM contract_documents WHERE mandate_id = :mid "
            "AND deleted_at IS NULL AND signed_at IS NOT NULL "
            f"AND document_type IN ({placeholders})"
        ),
        params,
    ).first()
    return str(row[0]) if row is not None and row[0] else None


def client_information_deliveries(db: Session, mandate_id: str) -> list[dict]:
    """Abgabenachweise des Mandats mit Integritaetspruefung gegen das Archiv."""
    rows = db.execute(
        _sql_text(
            "SELECT d.*, c.checksum_sha256 AS archived_sha256, c.document_type AS archived_type, "
            "c.mandate_id AS archived_mandate_id, c.deleted_at AS archived_deleted_at "
            "FROM client_information_deliveries d "
            "LEFT JOIN contract_documents c ON c.id = d.contract_document_id "
            "WHERE d.mandate_id = :mid ORDER BY d.delivered_at, d.recorded_at"
        ),
        {"mid": str(mandate_id)},
    ).mappings().all()
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        item["archive_verified"] = bool(
            item.get("archived_sha256")
            and item.get("archived_sha256") == item.get("pdf_sha256")
            and item.get("archived_type") == CLIENT_INFORMATION_DOCUMENT_TYPE
            and str(item.get("archived_mandate_id") or "") == str(mandate_id)
            and not item.get("archived_deleted_at")
        )
        for key in ("archived_sha256", "archived_type", "archived_mandate_id", "archived_deleted_at"):
            item.pop(key, None)
        out.append(item)
    return out


def client_onboarding_findings(
    db: Session,
    mandate: Any,
    *,
    reference_time: Optional[str] = None,
) -> list[dict]:
    """Alle offenen Punkte vor Vertragsabschluss/Finalisierung (leer = frei)."""
    findings: list[dict] = []
    now = reference_time or _utc_now_iso()
    profile = load_tenant_legal_profile(db, mandate_tenant_id(db, mandate))
    missing = legal_profile_missing_fields(profile)
    if missing:
        labels = [_LEGAL_PROFILE_LABELS.get(name, name) for name in missing]
        if "contact_phone" in missing:
            labels = [
                "Kontakt: Telefon oder E-Mail" if label == _LEGAL_PROFILE_LABELS["contact_phone"] else label
                for label in labels
            ]
        findings.append(_finding(
            CLIENT_INFORMATION_TENANT_DATA_MISSING,
            "Die Kundeninformation nach Art. 8 FIDLEG kann nicht erstellt werden: "
            "Pflichtangaben der Firma fehlen (" + ", ".join(labels) + ").",
            _OWNER_PROFILE_ACTION + ", ".join(labels) + ".",
            "tenant",
            missing_fields=missing,
            missing_labels=labels,
        ))
    elif _clean(profile.get("address_country")).upper() not in CLIENT_INFORMATION_SEAT_REGIMES:
        findings.append(_finding(
            CLIENT_INFORMATION_REGIME_UNSUPPORTED,
            "Fuer den Sitz der Firma ("
            f"{_clean(profile.get('address_country')) or 'unbekannt'}) bildet Ares "
            "kein Informationsregime ab (heute nur Schweiz/FIDLEG).",
            "Owner/Compliance: Informationspflichten ausserhalb von Ares regeln; "
            "Ares gibt die Kundeninformation fuer diesen Sitz nicht frei.",
            "tenant",
        ))
    mandate_id = str(getattr(mandate, "id", "") or "")
    deliveries = [d for d in client_information_deliveries(db, mandate_id) if d["archive_verified"]]
    concluded = contract_concluded_at(db, mandate_id)
    cutoff = min(concluded, now) if concluded else now
    if not deliveries:
        findings.append(_finding(
            CLIENT_INFORMATION_NOT_DELIVERED,
            "Fuer dieses Mandat ist keine Abgabe der Kundeninformation (Art. 8/9 "
            "FIDLEG) mit archivierter Fassung nachgewiesen.",
            "Berater: Kundeninformation als PDF erstellen, dem Kunden vor "
            "Vertragsabschluss uebergeben und die Uebergabe erfassen.",
            "mandate",
        ))
    elif not any(str(d.get("delivered_at") or "") <= cutoff for d in deliveries):
        findings.append(_finding(
            CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT,
            "Die Kundeninformation wurde erst nach dem Vertragsabschluss "
            f"({cutoff}) uebergeben (Art. 9 FIDLEG: vor Vertragsabschluss).",
            "Owner/Compliance: Vorgang pruefen; der Vertrag ist neu abzuschliessen, "
            "nachdem die Kundeninformation uebergeben wurde.",
            "mandate",
            contract_concluded_at=concluded,
        ))
    return findings


def client_onboarding_status(db: Session, mandate: Any) -> dict:
    """Anzeige-Status fuer die Maske (gleiche Quelle wie das Gate)."""
    tenant_id = mandate_tenant_id(db, mandate)
    profile = load_tenant_legal_profile(db, tenant_id)
    findings = client_onboarding_findings(db, mandate)
    deliveries = client_information_deliveries(db, str(mandate.id))
    current_hash = legal_profile_hash(profile) if profile else None
    for delivery in deliveries:
        delivery["legal_profile_current"] = bool(
            current_hash and delivery.get("legal_profile_hash") == current_hash
        )
    latest = db.execute(
        _sql_text(
            "SELECT id, version, checksum_sha256, content_json, created_at FROM contract_documents "
            "WHERE mandate_id = :mid AND document_type = :dtype AND deleted_at IS NULL "
            "ORDER BY version DESC LIMIT 1"
        ),
        {"mid": str(mandate.id), "dtype": CLIENT_INFORMATION_DOCUMENT_TYPE},
    ).mappings().first()
    latest_document = None
    if latest is not None:
        try:
            meta = json.loads(latest["content_json"] or "{}")
        except (TypeError, ValueError):
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
        latest_document = {
            "id": latest["id"],
            "version": latest["version"],
            "checksum_sha256": latest["checksum_sha256"],
            "created_at": latest["created_at"],
            "template_version": meta.get("template_version"),
            "legal_profile_revision": meta.get("legal_profile_revision"),
            "current": bool(
                current_hash
                and meta.get("legal_profile_hash") == current_hash
                and meta.get("template_version") == CLIENT_INFORMATION_TEMPLATE_VERSION
            ),
        }
    return {
        "mandate_id": str(mandate.id),
        "client_id": str(mandate.client_id),
        "release_ready": not findings,
        "findings": findings,
        "legal_profile": {
            "present": profile is not None,
            "revision": int((profile or {}).get("revision") or 0),
            "profile_hash": current_hash,
            "missing_fields": legal_profile_missing_fields(profile),
        },
        "contract_concluded_at": contract_concluded_at(db, str(mandate.id)),
        "deliveries": deliveries,
        "template_version": CLIENT_INFORMATION_TEMPLATE_VERSION,
        "latest_document": latest_document,
    }


def assert_client_onboarding_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    http_status: int = 409,
) -> None:
    """Sperrt Finalisierung bzw. Vertragsunterzeichnung, solange Kunden-
    information (Art. 8/9 FIDLEG) fehlt. Wirft
    ``DomainError`` mit ``reason_code`` CLIENT_ONBOARDING_INCOMPLETE und der
    Liste ``findings`` (je eigener Reason-Code + Owner-Hinweis), BEVOR der
    Kanal irgendeine Wirkung hat."""
    findings = client_onboarding_findings(db, mandate)
    if not findings:
        return
    raise DomainError(
        CLIENT_ONBOARDING_INCOMPLETE,
        (
            f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: "
            + " ".join(f["message"] for f in findings)
        ),
        http_status=http_status,
        extra={
            "channel": channel,
            "findings": findings,
            "finding_codes": [f["reason_code"] for f in findings],
        },
    )
