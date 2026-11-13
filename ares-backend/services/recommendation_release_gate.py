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

import json
from datetime import date as _date, datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, evidence_hash
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
# H8 C-2 / C-5 (Compliance-Audit 2026-11-07, Luecken 2 und 5):
# Kundeninformation nach Art. 8/9 FIDLEG und GwG-Bestaetigung als Gate vor
# Finalisierung und Vertragsunterzeichnung.
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
# - GwG: Frage "handelt auf eigene Rechnung" unbeantwortet, keine KYC-
#   Bestaetigung, fehlende Vier-Augen-Freigabe bei PEP/erhoehtem Risiko,
#   ueberfaellige Aktualisierung, PEP-Widerspruch -> Sperre.
#
# Gelesen wird per SQL (Muster H7 N-884-04 oben): dieses Modul ist das eine
# Freigabe-Gate der Kanaele und bekommt dafuer keine neuen Modulkanten.

CLIENT_ONBOARDING_INCOMPLETE = "CLIENT_ONBOARDING_INCOMPLETE"
CLIENT_INFORMATION_TENANT_DATA_MISSING = "CLIENT_INFORMATION_TENANT_DATA_MISSING"
CLIENT_INFORMATION_REGIME_UNSUPPORTED = "CLIENT_INFORMATION_REGIME_UNSUPPORTED"
CLIENT_INFORMATION_NOT_DELIVERED = "CLIENT_INFORMATION_NOT_DELIVERED"
CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT = "CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT"
KYC_BENEFICIAL_OWNER_UNANSWERED = "KYC_BENEFICIAL_OWNER_UNANSWERED"
KYC_CONFIRMATION_MISSING = "KYC_CONFIRMATION_MISSING"
KYC_SECOND_APPROVAL_MISSING = "KYC_SECOND_APPROVAL_MISSING"
KYC_CONFIRMATION_REVIEW_OVERDUE = "KYC_CONFIRMATION_REVIEW_OVERDUE"
KYC_PEP_INCONSISTENT = "KYC_PEP_INCONSISTENT"
KYC_CONFIRMATION_SEAL_INVALID = "KYC_CONFIRMATION_SEAL_INVALID"
# C-890-01 Nachtrag 2: Zweitfreigabe begruendet abgelehnt -> nie wirksam.
KYC_CONFIRMATION_REJECTED = "KYC_CONFIRMATION_REJECTED"
# Wer als zweite Person freigeben darf; gleiche Liste wie
# services/auth.py::COMPLIANCE_APPROVER_ROLES (Test prueft die Gleichheit).
KYC_APPROVER_ROLES: tuple[str, ...] = ("admin", "super_admin", "compliance_reviewer")


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
    """SHA-256 (core.evidence, SCHEME_V1) ueber die Inhaltsfelder (ohne Metadaten)."""
    payload = {name: _clean((profile or {}).get(name)) for name, _label in LEGAL_PROFILE_FIELDS}
    return evidence_hash(payload, scheme=SCHEME_V1)


def row_seal(row: dict, seal_column: str) -> str:
    """N-890-10: Siegel einer append-only Nachweiszeile = core.evidence-Hash
    (SCHEME_V1) ueber ALLE Spalten der Tabelle ausser der Siegelspalte. Die
    Router bilden es beim Schreiben aus dem ORM-Objekt, das Gate rechnet es
    aus der gelesenen Zeile nach (Abweichung = Nachweis ungueltig)."""
    return evidence_hash(
        {key: value for key, value in row.items() if key != seal_column}, scheme=SCHEME_V1,
    )


def load_tenant_legal_profile(db: Session, tenant_id: Optional[str]) -> Optional[dict]:
    if not tenant_id:
        return None
    row = db.execute(
        _sql_text("SELECT * FROM tenant_legal_profiles WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    # N-890-04: Retro-Grundsatz liegt auf der Firma (tenants), nicht in den
    # rechtlichen Angaben -- fuer die Kundeninformation mitlesen.
    tenant = db.execute(
        _sql_text("SELECT default_retrocession_reimbursement FROM tenants WHERE id = :tid"),
        {"tid": str(tenant_id)},
    ).first()
    profile["tenant_default_retrocession_reimbursement"] = (
        int(tenant[0] or 0) if tenant is not None else None
    )
    return profile


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
    """Fruehester Signaturzeitpunkt eines Vertragsdokuments (Vertragsabschluss):
    Berater-/Papier-Signatur (contract_documents.signed_at) ODER Vor-Ort-
    Signatur des Kunden (onsite_signature_evidence.signed_at, N-890-01)."""
    placeholders = ", ".join(f":t{i}" for i in range(len(CONTRACT_CONCLUSION_DOCUMENT_TYPES)))
    params = {f"t{i}": value for i, value in enumerate(sorted(CONTRACT_CONCLUSION_DOCUMENT_TYPES))}
    params["mid"] = str(mandate_id)
    candidates: list[str] = []
    for sql in (
        "SELECT MIN(signed_at) FROM contract_documents WHERE mandate_id = :mid "
        "AND deleted_at IS NULL AND signed_at IS NOT NULL "
        f"AND document_type IN ({placeholders})",
        "SELECT MIN(signed_at) FROM onsite_signature_evidence WHERE mandate_id = :mid "
        f"AND signed_at IS NOT NULL AND document_type IN ({placeholders})",
    ):
        row = db.execute(_sql_text(sql), params).first()
        if row is not None and row[0]:
            candidates.append(str(row[0]))
    return min(candidates) if candidates else None


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
        archived_keys = ("archived_sha256", "archived_type", "archived_mandate_id", "archived_deleted_at")
        own = {key: value for key, value in item.items() if key not in archived_keys}
        item["seal_verified"] = bool(item.get("delivery_hash")) and (
            row_seal(own, "delivery_hash") == item.get("delivery_hash")
        )
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


def latest_kyc_confirmation(db: Session, client_id: str, mandate_id: Optional[str]) -> Optional[dict]:
    """Juengste Bestaetigung samt Freigabe; ``seal_verified`` bzw.
    ``approval_by`` nur, wenn das jeweilige Siegel nachgerechnet stimmt."""
    row = db.execute(
        _sql_text(
            "SELECT * FROM kyc_confirmations "
            "WHERE client_id = :cid AND (mandate_id IS NULL OR mandate_id = :mid) "
            "ORDER BY recorded_at DESC, id DESC LIMIT 1"
        ),
        {"cid": str(client_id), "mid": str(mandate_id or "")},
    ).mappings().first()
    if row is None:
        return None
    confirmation = dict(row)
    # C-890-01: eine Bestandsbestaetigung (vor der Policy-Bindung erfasst) hat
    # die Bindungsspalten NULL; ihr Siegel deckt nur die damaligen Spalten.
    # Sie bleibt nachpruefbar, gilt aber als "policy_binding_missing".
    seal_input = dict(row)
    if all(seal_input.get(column) is None for column in KYC_REVIEW_BINDING_COLUMNS):
        for column in KYC_REVIEW_BINDING_COLUMNS:
            seal_input.pop(column, None)
    confirmation["seal_verified"] = row_seal(seal_input, "confirmation_hash") == row["confirmation_hash"]
    approval = db.execute(
        _sql_text("SELECT * FROM kyc_confirmation_approvals WHERE confirmation_id = :id"),
        {"id": str(row["id"])},
    ).mappings().first()
    # C-890-01 Nachtrag 2: eine Freigabe zaehlt nur mit gueltigem Siegel, von
    # einer freigabeberechtigten Rolle (admin oder compliance_reviewer) und
    # nicht von derselben Person (gleiche ID oder E-Mail wie der Erfasser).
    approval_ok = approval is not None and (
        row_seal(dict(approval), "approval_hash") == approval["approval_hash"]
    ) and kyc_second_person_valid(db, approval["approved_by"], row["recorded_by"])
    rejection = db.execute(
        _sql_text("SELECT * FROM kyc_confirmation_rejections WHERE confirmation_id = :id"),
        {"id": str(row["id"])},
    ).mappings().first()
    # Eine Ablehnung gilt auch bei defektem Siegel als "nicht freigegeben";
    # fail-closed bleibt die Bestaetigung damit in jedem Fall unwirksam.
    confirmation["rejected"] = rejection is not None
    confirmation["rejection_id"] = rejection["id"] if rejection is not None else None
    confirmation["approval_id"] = approval["id"] if approval_ok else None
    confirmation["approval_by"] = approval["approved_by"] if approval_ok else None
    confirmation["approval_at"] = approval["approved_at"] if approval_ok else None
    return confirmation


def _email_identity(value: Any) -> str:
    """Gleiche Regel wie services/auth.py::normalize_email_identity (Test):
    Gross-/Kleinschreibung, Leerzeichen und ``+alias`` zaehlen nicht."""
    raw = _clean(value).lower()
    if "@" not in raw:
        return raw
    local, _, domain = raw.rpartition("@")
    return local.split("+", 1)[0] + "@" + domain


def kyc_reviewer_account_ready(row: Any) -> bool:
    """N-897-02: Konto der Rolle compliance_reviewer zaehlt nur, wenn es per
    Einladung aktiviert wurde und Passwort sowie 2FA zuletzt von der Person
    selbst gesetzt wurden (nie von einem Admin)."""
    return bool(
        row["invited_at"] and row["activated_at"]
        and str(row["credentials_set_by"] or "") == "self"
        and int(row["totp_enabled"] or 0)
        and str(row["totp_set_by"] or "") == "self"
    )


def kyc_second_person_valid(db: Session, approver_id: Any, recorder_id: Any) -> bool:
    """Vier-Augen nachgerechnet (KYC-Zweitfreigabe UND Policy-Aktivierung):
    Freigeber existiert mit einer Freigaberolle (``KYC_APPROVER_ROLES``), ist
    nicht der Erfasser -- weder gleiche ID noch gleiche normalisierte E-Mail
    (zweites Konto, ``+alias``) -- und ist, falls externe Compliance-Person,
    ein selbst aktiviertes Konto mit selbst gesetzter 2FA (N-897-02)."""
    if not approver_id or str(approver_id) == str(recorder_id or ""):
        return False
    rows = {
        str(r["id"]): r for r in db.execute(
            _sql_text(
                "SELECT id, role, email, invited_at, activated_at, credentials_set_by, "
                "totp_enabled, totp_set_by FROM users WHERE id IN (:a, :b)"
            ),
            {"a": str(approver_id), "b": str(recorder_id or "")},
        ).mappings().all()
    }
    approver = rows.get(str(approver_id))
    if approver is None or str(approver["role"] or "") not in KYC_APPROVER_ROLES:
        return False
    if str(approver["role"]) == "compliance_reviewer" and not kyc_reviewer_account_ready(approver):
        return False
    recorder = rows.get(str(recorder_id or ""))
    a_mail = _email_identity(approver["email"])
    r_mail = _email_identity(recorder["email"]) if recorder is not None else ""
    return not (a_mail and a_mail == r_mail)


def kyc_approver_account(db: Session, user_id: Any) -> Optional[dict]:
    """Freigabenachweis (N-897-02): Herkunft des Freigeberkontos -- Rolle,
    Identitaet der externen Person, wer es wann eingeladen hat, wann es
    aktiviert wurde und wer Passwort/2FA zuletzt gesetzt hat."""
    if not user_id:
        return None
    row = db.execute(
        _sql_text(
            "SELECT id, full_name, role, invited_by, invited_at, activated_at, credentials_set_by, "
            "totp_enabled, totp_set_by, reviewer_organisation, reviewer_reference "
            "FROM users WHERE id = :id"
        ),
        {"id": str(user_id)},
    ).mappings().first()
    if row is None:
        return None
    inviter = None
    if row["invited_by"]:
        found = db.execute(_sql_text("SELECT full_name FROM users WHERE id = :id"),
                           {"id": str(row["invited_by"])}).first()
        inviter = found[0] if found is not None else None
    return {
        "user_id": row["id"], "name": row["full_name"], "role": row["role"],
        "organisation": row["reviewer_organisation"], "reference": row["reviewer_reference"],
        "invited_by": row["invited_by"], "invited_by_name": inviter, "invited_at": row["invited_at"],
        "activated_at": row["activated_at"],
        "credentials_set_by": ("selbst" if row["credentials_set_by"] == "self"
                               else ("Admin" if row["credentials_set_by"] else "unbekannt")),
        "totp_enabled": bool(int(row["totp_enabled"] or 0)),
        "totp_set_by": ("selbst" if row["totp_set_by"] == "self"
                        else ("Admin" if row["totp_set_by"] else "unbekannt")),
    }


def kyc_requires_second_approval(confirmation: dict) -> bool:
    """Bei der Erfassung festgehalten (N-890-03): PEP, erhoehtes Risiko ODER
    Herabstufung gegenueber dem zuletzt wirksamen Stand."""
    return bool(int(confirmation.get("requires_second_approval") or 0))


# ---------------------------------------------------------------------------
# C-890-01: Wiedervorlage-Policy der KYC-Bestaetigung (Maximalabstand)
# ---------------------------------------------------------------------------
#
# Ares erfindet keine Frist. Wie weit ``next_review_due`` hoechstens nach dem
# Abschluss der GwG-Abklaerung (``form_completed_on``) liegen darf, steht
# ausschliesslich in einer vom Owner erfassten, von einer zweiten Person
# (Admin) freigegebenen und hashgesicherten Policy je Tenant/Jurisdiktion
# (``kyc_review_policies`` + ``kyc_review_policy_activations``, append-only).
# Fehlt sie, ist sie noch nicht wirksam, abgelaufen, mehrdeutig, ohne
# Vier-Augen-Freigabe oder hashungueltig, blockieren Erfassung (API) und jede
# Kundenfreigabe (Finalisierung, Berater-/Vor-Ort-Signatur, Handoff,
# Kunden-PDF) mit demselben Reason-Code -- es gibt keinen Default.
#
# Jurisdiktion = Sitzland der Firma aus den rechtlichen Angaben (gleiche
# Quelle wie das Informationsregime oben, kein Mandats-Fallback).
#
# Kalendervertrag (``add_months_clamped``): Obergrenze = Abschlussdatum plus
# N Kalendermonate. Gibt es den Tag im Zielmonat nicht (31. -> 30. April,
# 29. Februar -> 28. Februar im Nicht-Schaltjahr), gilt der LETZTE Tag des
# Zielmonats -- nie ein Ueberlauf in den Folgemonat (die strengere Lesart).
# Die exakte Obergrenze ist zulaessig: form_completed_on < next_review_due
# <= Obergrenze.

KYC_REVIEW_POLICY_MISSING = "KYC_REVIEW_POLICY_MISSING"
KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN = "KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN"
KYC_REVIEW_POLICY_UNAPPROVED = "KYC_REVIEW_POLICY_UNAPPROVED"
KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE = "KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE"
KYC_REVIEW_POLICY_EXPIRED = "KYC_REVIEW_POLICY_EXPIRED"
KYC_REVIEW_POLICY_AMBIGUOUS = "KYC_REVIEW_POLICY_AMBIGUOUS"
KYC_REVIEW_POLICY_INVALID = "KYC_REVIEW_POLICY_INVALID"
KYC_REVIEW_POLICY_BINDING_MISSING = "KYC_REVIEW_POLICY_BINDING_MISSING"
KYC_REVIEW_POLICY_BINDING_INVALID = "KYC_REVIEW_POLICY_BINDING_INVALID"
KYC_REVIEW_POLICY_SHORTENED = "KYC_REVIEW_POLICY_SHORTENED"
KYC_REVIEW_DUE_EXCEEDS_POLICY = "KYC_REVIEW_DUE_EXCEEDS_POLICY"

# Stabile Status (API, Status-Maske, Fehlerdetail aller Kanaele).
KYC_REVIEW_STATUS_EFFECTIVE = "effective"
KYC_REVIEW_STATUS_OK = "ok"
KYC_REVIEW_STATUS_BY_CODE: dict[str, str] = {
    KYC_REVIEW_POLICY_MISSING: "policy_missing",
    KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN: "jurisdiction_unknown",
    KYC_REVIEW_POLICY_UNAPPROVED: "policy_unapproved",
    KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE: "policy_not_yet_effective",
    KYC_REVIEW_POLICY_EXPIRED: "policy_expired",
    KYC_REVIEW_POLICY_AMBIGUOUS: "policy_ambiguous",
    KYC_REVIEW_POLICY_INVALID: "policy_invalid",
    KYC_REVIEW_POLICY_BINDING_MISSING: "policy_binding_missing",
    KYC_REVIEW_POLICY_BINDING_INVALID: "policy_binding_invalid",
    KYC_REVIEW_POLICY_SHORTENED: "due_under_shortened_policy",
    KYC_REVIEW_DUE_EXCEEDS_POLICY: "due_exceeds_policy",
    KYC_CONFIRMATION_REVIEW_OVERDUE: "review_overdue",
}

KYC_REVIEW_RISK_NORMAL = "normal"
KYC_REVIEW_RISK_ELEVATED = "erhoeht"
# Gleicher Wert wie models/tenant.py::KYC_REVIEW_GENESIS (Test prueft die
# Gleichheit; Literal, damit das Gate keine neue Modulkante bekommt).
KYC_REVIEW_GENESIS = "GENESIS"
# Gleiche Liste wie database.py::KYC_CONFIRMATION_REVIEW_BINDING_COLUMNS.
KYC_REVIEW_BINDING_COLUMNS: tuple[str, ...] = (
    "review_policy_row_id", "review_policy_activation_id", "review_policy_id",
    "review_policy_version", "review_policy_hash", "review_risk_class",
    "review_interval_months", "review_max_due",
)

_REVIEW_OWNER_POLICY_ACTION = (
    "Owner/Compliance: die freigegebene Wiedervorlage-Frist der Firma als neue "
    "Policy-Version erfassen (POST /compliance/kyc-review-policies); eine zweite "
    "Person mit Admin-Rolle gibt sie mit der Freigabereferenz frei."
)
_REVIEW_MESSAGES: dict[str, tuple[str, str]] = {
    KYC_REVIEW_POLICY_MISSING: (
        "Fuer diese Firma und Jurisdiktion ist keine Wiedervorlage-Policy "
        "(maximaler Abstand bis zur naechsten KYC-Aktualisierung) erfasst; Ares "
        "setzt keine eigene Frist.",
        _REVIEW_OWNER_POLICY_ACTION,
    ),
    KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN: (
        "Die Jurisdiktion der Wiedervorlage-Policy ist unbekannt: das Sitzland "
        "der Firma fehlt in den rechtlichen Angaben.",
        "Ein Firmen-Admin ergaenzt unter Administration > Rechtliche Angaben das "
        "Sitzland der Firma.",
    ),
    KYC_REVIEW_POLICY_UNAPPROVED: (
        "Die Wiedervorlage-Policy ist nicht durch eine zweite Person freigegeben "
        "und deshalb nicht wirksam.",
        "Eine zweite Person mit Admin-Rolle gibt die erfasste Policy-Version mit "
        "Freigabereferenz frei.",
    ),
    KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE: (
        "Die freigegebene Wiedervorlage-Policy ist noch nicht wirksam "
        "(Gueltigkeitsbeginn liegt in der Zukunft).",
        "Bis zum Gueltigkeitsbeginn warten oder eine ab heute gueltige Version "
        "erfassen und freigeben lassen.",
    ),
    KYC_REVIEW_POLICY_EXPIRED: (
        "Die Wiedervorlage-Policy ist abgelaufen (Gueltigkeitsende ueberschritten).",
        _REVIEW_OWNER_POLICY_ACTION,
    ),
    KYC_REVIEW_POLICY_AMBIGUOUS: (
        "Die Wiedervorlage-Policy ist mehrdeutig (keine eindeutige Kette der "
        "freigegebenen Versionen); keine Version gilt.",
        "Owner/Compliance: Vorgang pruefen lassen; danach eine neue Version "
        "erfassen und freigeben.",
    ),
    KYC_REVIEW_POLICY_INVALID: (
        "Die Wiedervorlage-Policy ist ungueltig (Siegel bzw. Freigabe-Hash "
        "stimmt nicht oder der Inhalt verletzt die Regeln); keine Version gilt.",
        "Owner/Compliance: Vorgang pruefen lassen; danach eine neue Version "
        "erfassen und freigeben.",
    ),
    KYC_REVIEW_POLICY_BINDING_MISSING: (
        "Die KYC-Bestaetigung ist an keine freigegebene Wiedervorlage-Policy "
        "gebunden (erfasst vor Einfuehrung der Policy).",
        "Berater: nach Freigabe der Policy eine neue KYC-Bestaetigung erfassen.",
    ),
    KYC_REVIEW_POLICY_BINDING_INVALID: (
        "Die Policy-Bindung der KYC-Bestaetigung ist ungueltig (Policy, Version, "
        "Hash, Mandant, Zeitpunkt oder berechnete Obergrenze stimmen nicht).",
        "Berater: neue KYC-Bestaetigung erfassen; Owner/Compliance: Vorgang pruefen.",
    ),
    KYC_REVIEW_POLICY_SHORTENED: (
        "Die heute wirksame Wiedervorlage-Policy ist strenger als die bei der "
        "Erfassung gebundene: der erfasste Termin liegt nach der neuen "
        "Obergrenze, die Aktualisierung ist sofort faellig.",
        "Berater: Aktualisierung im SRO-/Fremdprozess durchfuehren und eine neue "
        "KYC-Bestaetigung erfassen.",
    ),
    KYC_REVIEW_DUE_EXCEEDS_POLICY: (
        "Die naechste Aktualisierung liegt nach der Obergrenze der wirksamen "
        "Wiedervorlage-Policy.",
        "Berater: einen Termin bis zur angegebenen Obergrenze erfassen.",
    ),
}


def kyc_review_message(reason_code: str) -> tuple[str, str]:
    """(Meldung, Owner-Hinweis) eines Wiedervorlage-Reason-Codes."""
    return _REVIEW_MESSAGES[reason_code]


def _iso_day(value: Any) -> str:
    return str(value or "")[:10]


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (_date(year, month + 1, 1) - _date(year, month, 1)).days


def add_months_clamped(day: Any, months: int) -> str:
    """Kalendersichere Obergrenze (Vertrag siehe Abschnittskopf): ``day``
    (ISO-Datum) plus ``months`` Kalendermonate; fehlt der Tag im Zielmonat,
    gilt der letzte Tag des Zielmonats. Beispiele: 2024-02-29 + 12 ->
    2025-02-28; 2024-02-29 + 48 -> 2028-02-29; 2026-01-31 + 1 -> 2026-02-28;
    2026-08-31 + 1 -> 2026-09-30."""
    if int(months) <= 0:
        raise ValueError("Abstand muss positiv sein")
    start = _date.fromisoformat(_iso_day(day))
    index = start.year * 12 + (start.month - 1) + int(months)
    year, month = divmod(index, 12)
    month += 1
    return _date(year, month, min(start.day, _days_in_month(year, month))).isoformat()


def kyc_review_risk_class(risk_category: Any, is_pep: Any) -> str:
    """PEP ODER erhoehtes Risiko -> Klasse ``erhoeht`` (strengere Frist)."""
    if bool(int(is_pep or 0)) or str(risk_category or "") != KYC_REVIEW_RISK_NORMAL:
        return KYC_REVIEW_RISK_ELEVATED
    return KYC_REVIEW_RISK_NORMAL


def kyc_review_policy_defect(policy: dict) -> Optional[str]:
    """Inhaltliche Regeln einer Policy (bei Erfassung, Aktivierung und im Gate
    geprueft): Abstand > 0; eine eigene PEP-/Hochrisiko-Frist darf nie
    lockerer sein als die Normalfrist; Gueltigkeitsende nicht vor dem Beginn.
    None = in Ordnung, sonst Kennung der Regel."""
    try:
        normal = int(policy.get("normal_max_months"))
    except (TypeError, ValueError):
        return "normal_max_months"
    if normal <= 0:
        return "normal_max_months"
    elevated = policy.get("elevated_max_months")
    if elevated is not None:
        try:
            elevated = int(elevated)
        except (TypeError, ValueError):
            return "elevated_max_months"
        if elevated <= 0:
            return "elevated_max_months"
        if elevated > normal:
            return "elevated_looser_than_normal"
    valid_from = _iso_day(policy.get("valid_from"))
    valid_until = _iso_day(policy.get("valid_until")) if policy.get("valid_until") else ""
    if not valid_from:
        return "valid_from"
    if valid_until and valid_until < valid_from:
        return "valid_until"
    return None


def kyc_review_interval_months(policy: dict, risk_class: str) -> int:
    if risk_class == KYC_REVIEW_RISK_ELEVATED and policy.get("elevated_max_months") is not None:
        return int(policy["elevated_max_months"])
    return int(policy["normal_max_months"])


def kyc_review_jurisdiction(db: Session, tenant_id: Optional[str]) -> Optional[str]:
    """Sitzland der Firma (rechtliche Angaben), gross geschrieben; None wenn
    nicht erfasst."""
    if not tenant_id:
        return None
    row = db.execute(
        _sql_text("SELECT address_country FROM tenant_legal_profiles WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    ).first()
    country = _clean(row[0] if row is not None else None).upper()
    return country or None


def kyc_review_effective_from(policy: dict, activation: dict) -> str:
    """Wirksam ab Gueltigkeitsbeginn, fruehestens ab dem Tag der Freigabe
    (eine rueckdatierte Policy wirkt nie vor ihrer Freigabe)."""
    return max(_iso_day(policy.get("valid_from")), _iso_day(activation.get("approved_at")))


def kyc_review_public_policy(policy: dict, activation: Optional[dict]) -> dict:
    return {
        "id": policy.get("id"),
        "tenant_id": policy.get("tenant_id"),
        "jurisdiction": policy.get("jurisdiction"),
        "policy_id": policy.get("policy_id"),
        "version": policy.get("version"),
        "normal_max_months": policy.get("normal_max_months"),
        "elevated_max_months": policy.get("elevated_max_months"),
        "valid_from": policy.get("valid_from"),
        "valid_until": policy.get("valid_until"),
        "source_reference": policy.get("source_reference"),
        "created_by": policy.get("created_by"),
        "created_at": policy.get("created_at"),
        "policy_hash": policy.get("policy_hash"),
        "activation_id": (activation or {}).get("id"),
        "approved_by": (activation or {}).get("approved_by"),
        "approved_at": (activation or {}).get("approved_at"),
        "approval_reference": (activation or {}).get("approval_reference"),
        "effective_from": (
            kyc_review_effective_from(policy, activation) if activation is not None else None
        ),
    }


def _review_resolution(code: Optional[str], tenant_id: Any, jurisdiction: Any,
                       policy: Optional[dict] = None, activation: Optional[dict] = None,
                       **extra: Any) -> dict:
    return {
        "status": KYC_REVIEW_STATUS_BY_CODE[code] if code else KYC_REVIEW_STATUS_EFFECTIVE,
        "reason_code": code,
        "tenant_id": tenant_id,
        "jurisdiction": jurisdiction,
        "policy": kyc_review_public_policy(policy, activation) if policy is not None else None,
        "policy_row": policy,
        "activation_row": activation,
        **extra,
    }


def kyc_review_policy_chain(db: Session, tenant_id: str, jurisdiction: str) -> tuple[dict, list[dict]]:
    """Alle Policy-Versionen (nach id) und Aktivierungen eines Tenants/einer
    Jurisdiktion, roh gelesen (per SQL, Muster H7 N-884-04)."""
    params = {"tid": str(tenant_id), "jur": str(jurisdiction)}
    policies = {
        str(row["id"]): dict(row)
        for row in db.execute(
            _sql_text("SELECT * FROM kyc_review_policies WHERE tenant_id = :tid AND jurisdiction = :jur"),
            params,
        ).mappings().all()
    }
    activations = [
        dict(row)
        for row in db.execute(
            _sql_text(
                "SELECT * FROM kyc_review_policy_activations "
                "WHERE tenant_id = :tid AND jurisdiction = :jur ORDER BY approved_at, id"
            ),
            params,
        ).mappings().all()
    ]
    return policies, activations


def resolve_kyc_review_policy(
    db: Session,
    tenant_id: Optional[str],
    jurisdiction: Optional[str],
    on_date: str,
    *,
    as_of: Optional[str] = None,
) -> dict:
    """Die am Tag ``on_date`` wirksame Policy-Version (fail-closed). Mit
    ``as_of`` (Zeitstempel) zaehlen nur Freigaben bis zu diesem Zeitpunkt --
    so rechnet das Gate die Bindung einer frueheren Erfassung nach.

    Ergebnis: ``status`` (``effective`` oder ein Sperrstatus), ``reason_code``
    (None nur bei ``effective``) und die oeffentliche Sicht ``policy``.

    Wirksam ist von der juengsten Aktivierung der Kette rueckwaerts die erste
    Version, deren Wirksamkeitsbeginn (Gueltigkeitsbeginn, fruehestens Tag der
    Freigabe) erreicht ist; ist deren Gueltigkeitsende ueberschritten, gilt
    keine Version (``expired``). Jede Aktivierung muss ihr Siegel, den
    gesehenen Policy-Hash und die Vier-Augen-Regel erfuellen; die Kette muss
    linear sein und die Versionen streng steigen -- sonst gilt keine Version."""
    on_date = _iso_day(on_date)
    if not jurisdiction:
        return _review_resolution(KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN, tenant_id, jurisdiction)
    policies, activations = kyc_review_policy_chain(db, str(tenant_id), str(jurisdiction))
    if as_of is not None:
        activations = [a for a in activations if str(a.get("approved_at") or "") <= str(as_of)]
    if not policies and not activations:
        return _review_resolution(KYC_REVIEW_POLICY_MISSING, tenant_id, jurisdiction)
    for activation in activations:
        policy = policies.get(str(activation.get("policy_row_id")))
        if (
            policy is None
            or row_seal(policy, "policy_hash") != policy.get("policy_hash")
            or row_seal(activation, "activation_hash") != activation.get("activation_hash")
            or activation.get("policy_hash") != policy.get("policy_hash")
            or kyc_review_policy_defect(policy) is not None
        ):
            return _review_resolution(KYC_REVIEW_POLICY_INVALID, tenant_id, jurisdiction, policy, activation)
        if not kyc_second_person_valid(db, activation.get("approved_by"), policy.get("created_by")):
            # N-897-04: Vier-Augen per Person wie bei der KYC-Zweitfreigabe
            # (ID, normalisierte E-Mail, Freigaberolle, Konto-Herkunft).
            return _review_resolution(KYC_REVIEW_POLICY_UNAPPROVED, tenant_id, jurisdiction, policy, activation)
    if not activations:
        newest = max(policies.values(), key=lambda p: int(p.get("version") or 0))
        return _review_resolution(KYC_REVIEW_POLICY_UNAPPROVED, tenant_id, jurisdiction, newest)
    by_predecessor: dict[str, list[dict]] = {}
    for activation in activations:
        by_predecessor.setdefault(str(activation.get("predecessor_activation_id")), []).append(activation)
    if any(len(items) > 1 for items in by_predecessor.values()):
        return _review_resolution(KYC_REVIEW_POLICY_AMBIGUOUS, tenant_id, jurisdiction)
    chain: list[dict] = []
    seen: set[str] = set()
    cursor = KYC_REVIEW_GENESIS
    while cursor in by_predecessor:
        activation = by_predecessor[cursor][0]
        if str(activation["id"]) in seen:
            return _review_resolution(KYC_REVIEW_POLICY_AMBIGUOUS, tenant_id, jurisdiction)
        chain.append(activation)
        seen.add(str(activation["id"]))
        cursor = str(activation["id"])
    versions = [int(policies[str(a["policy_row_id"])].get("version") or 0) for a in chain]
    if len(chain) != len(activations) or any(b <= a for a, b in zip(versions, versions[1:])):
        return _review_resolution(KYC_REVIEW_POLICY_AMBIGUOUS, tenant_id, jurisdiction)
    chain_pairs = [(policies[str(a["policy_row_id"])], a) for a in chain]
    for activation in reversed(chain):
        policy = policies[str(activation["policy_row_id"])]
        if kyc_review_effective_from(policy, activation) <= on_date:
            valid_until = _iso_day(policy.get("valid_until")) if policy.get("valid_until") else ""
            if valid_until and on_date > valid_until:
                return _review_resolution(KYC_REVIEW_POLICY_EXPIRED, tenant_id, jurisdiction, policy, activation,
                                          chain=chain_pairs)
            return _review_resolution(None, tenant_id, jurisdiction, policy, activation, chain=chain_pairs)
    head = chain[-1]
    return _review_resolution(
        KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE, tenant_id, jurisdiction,
        policies[str(head["policy_row_id"])], head, chain=chain_pairs,
    )


def kyc_review_entry_binding(
    db: Session,
    *,
    tenant_id: str,
    form_completed_on: str,
    risk_category: str,
    is_pep: Any,
    at: str,
) -> dict:
    """Bindung einer NEUEN KYC-Bestaetigung (API): die zum Erfassungszeitpunkt
    ``at`` wirksame Policy, Risikoklasse, Abstand und serverseitig berechnete
    Obergrenze. ``reason_code`` gesetzt = Erfassung gesperrt."""
    jurisdiction = kyc_review_jurisdiction(db, tenant_id)
    resolution = resolve_kyc_review_policy(db, tenant_id, jurisdiction, _iso_day(at), as_of=at)
    if resolution["reason_code"]:
        return resolution
    policy = resolution["policy_row"]
    activation = resolution["activation_row"]
    risk_class = kyc_review_risk_class(risk_category, is_pep)
    interval = kyc_review_interval_months(policy, risk_class)
    max_due = add_months_clamped(form_completed_on, interval)
    return {
        **resolution,
        "form_completed_on": _iso_day(form_completed_on),
        "risk_class": risk_class,
        "interval_months": interval,
        "max_due": max_due,
        "binding": {
            "review_policy_row_id": policy["id"],
            "review_policy_activation_id": activation["id"],
            "review_policy_id": policy["policy_id"],
            "review_policy_version": int(policy["version"]),
            "review_policy_hash": policy["policy_hash"],
            "review_risk_class": risk_class,
            "review_interval_months": interval,
            "review_max_due": max_due,
        },
    }


def kyc_review_binding_defect(db: Session, confirmation: dict, tenant_id: str,
                              jurisdiction: Optional[str]) -> Optional[str]:
    """Rechnet die im Siegel gebundene Policy nach (Hash-, Mandanten-,
    Versions- und Zeitmanipulation). None = Bindung gueltig; sonst Kennung der
    Abweichung. ``missing`` = Bestandsbestaetigung ohne Bindung."""
    values = {column: confirmation.get(column) for column in KYC_REVIEW_BINDING_COLUMNS}
    if all(value is None for value in values.values()):
        return "missing"
    if any(value is None for value in values.values()):
        return "partial"
    policy_row = db.execute(
        _sql_text("SELECT * FROM kyc_review_policies WHERE id = :id"),
        {"id": str(values["review_policy_row_id"])},
    ).mappings().first()
    activation_row = db.execute(
        _sql_text("SELECT * FROM kyc_review_policy_activations WHERE id = :id"),
        {"id": str(values["review_policy_activation_id"])},
    ).mappings().first()
    if policy_row is None or activation_row is None:
        return "policy_row"
    policy, activation = dict(policy_row), dict(activation_row)
    if str(activation.get("policy_row_id")) != str(policy.get("id")):
        return "activation"
    if row_seal(policy, "policy_hash") != policy.get("policy_hash") or (
        row_seal(activation, "activation_hash") != activation.get("activation_hash")
    ):
        return "policy_seal"
    if not (policy.get("policy_hash") == activation.get("policy_hash") == values["review_policy_hash"]):
        return "policy_hash"
    confirmation_tenant = str(confirmation.get("tenant_id") or _DEFAULT_TENANT_ID)
    if not (str(policy.get("tenant_id")) == str(tenant_id) == confirmation_tenant):
        return "tenant"
    if str(policy.get("jurisdiction")) != str(jurisdiction or ""):
        return "jurisdiction"
    if str(policy.get("policy_id")) != str(values["review_policy_id"]) or (
        int(policy.get("version") or 0) != int(values["review_policy_version"])
    ):
        return "version"
    recorded_at = str(confirmation.get("recorded_at") or "")
    at_recording = resolve_kyc_review_policy(
        db, policy.get("tenant_id"), policy.get("jurisdiction"), _iso_day(recorded_at), as_of=recorded_at,
    )
    if at_recording["reason_code"] or (
        str((at_recording["activation_row"] or {}).get("id")) != str(activation.get("id"))
    ):
        return "time"
    risk_class = kyc_review_risk_class(confirmation.get("risk_category"), confirmation.get("is_pep"))
    if risk_class != values["review_risk_class"]:
        return "risk_class"
    interval = kyc_review_interval_months(policy, risk_class)
    if interval != int(values["review_interval_months"]):
        return "interval"
    completed = _iso_day(confirmation.get("form_completed_on"))
    try:
        max_due = add_months_clamped(completed, interval)
    except ValueError:
        return "max_due"
    if max_due != _iso_day(values["review_max_due"]):
        return "max_due"
    due = _iso_day(confirmation.get("next_review_due"))
    if not (completed < due <= max_due):
        return "next_review_due"
    return None


def _review_finding(reason_code: str, scope: str, resolution: Optional[dict] = None, **extra: Any) -> dict:
    message, owner_action = _REVIEW_MESSAGES[reason_code]
    policy = (resolution or {}).get("policy") or {}
    return _finding(
        reason_code, message, owner_action, scope,
        kyc_review_status=KYC_REVIEW_STATUS_BY_CODE.get(reason_code),
        policy_ref={
            "policy_row_id": policy.get("id"),
            "policy_id": policy.get("policy_id"),
            "version": policy.get("version"),
            "jurisdiction": (resolution or {}).get("jurisdiction"),
            "tenant_id": (resolution or {}).get("tenant_id"),
        },
        **extra,
    )


def kyc_review_findings(
    db: Session,
    mandate: Any,
    today: str,
    *,
    confirmation: Optional[dict],
    include_without_confirmation: bool = True,
) -> list[dict]:
    """Die EINE Wiedervorlage-Pruefung aller Kanaele (API-Status,
    Finalisierung, Berater-/Vor-Ort-Signatur, Handoff, Kunden-PDF).

    Reihenfolge: Bindung der juengsten Bestaetigung (fehlend/ungueltig), dann
    die heute wirksame Policy (fehlend/unfreigegeben/... -> deren Code), dann
    "Policy verkuerzt" (der gebundene Termin liegt nach der Obergrenze der
    heute wirksamen Policy -> sofort faellig). Eine spaetere, laengere Policy
    verlaengert einen gebundenen Termin nie: massgebend bleibt der gebundene
    ``next_review_due`` (Ablauf: KYC_CONFIRMATION_REVIEW_OVERDUE)."""
    today = _iso_day(today)
    tenant_id = mandate_tenant_id(db, mandate)
    jurisdiction = kyc_review_jurisdiction(db, tenant_id)
    current = resolve_kyc_review_policy(db, tenant_id, jurisdiction, today)
    findings: list[dict] = []
    if confirmation is None:
        if include_without_confirmation and current["reason_code"]:
            findings.append(_review_finding(current["reason_code"], "tenant", current))
        return findings
    defect = kyc_review_binding_defect(db, confirmation, tenant_id, jurisdiction)
    if defect == "missing":
        findings.append(_review_finding(
            KYC_REVIEW_POLICY_BINDING_MISSING, "client", current, confirmation_id=confirmation.get("id"),
        ))
    elif defect is not None:
        findings.append(_review_finding(
            KYC_REVIEW_POLICY_BINDING_INVALID, "client", current,
            confirmation_id=confirmation.get("id"), binding_defect=defect,
        ))
    if current["reason_code"]:
        findings.append(_review_finding(current["reason_code"], "tenant", current))
    elif defect is None:
        # N-897-05 (Entscheid konservativ): massgebend ist die STRENGSTE
        # Obergrenze aller Versionen, die seit der Erfassung wirksam waren --
        # eine einmal durch Verkuerzung faellig gewordene Bestaetigung wird
        # durch eine spaetere Verlaengerung nicht wieder gruen (Heilung nur
        # durch eine neue KYC-Bestaetigung).
        risk_class = kyc_review_risk_class(confirmation.get("risk_category"), confirmation.get("is_pep"))
        recorded = _iso_day(confirmation.get("recorded_at"))
        bound_version = int(confirmation.get("review_policy_version") or 0)
        strictest = None
        for policy, activation in current.get("chain") or []:
            if int(policy.get("version") or 0) < bound_version:
                continue
            if kyc_review_effective_from(policy, activation) > today:
                continue
            if policy.get("valid_until") and _iso_day(policy.get("valid_until")) < recorded:
                continue
            candidate = add_months_clamped(
                confirmation.get("form_completed_on"), kyc_review_interval_months(policy, risk_class),
            )
            if strictest is None or candidate < strictest[0]:
                strictest = (candidate, policy)
        if strictest is not None and _iso_day(confirmation.get("next_review_due")) > strictest[0]:
            findings.append(_review_finding(
                KYC_REVIEW_POLICY_SHORTENED, "client", current,
                confirmation_id=confirmation.get("id"),
                bound_next_review_due=_iso_day(confirmation.get("next_review_due")),
                current_max_due=strictest[0],
                shortened_by_policy_version=int(strictest[1].get("version") or 0),
            ))
    return findings


def kyc_review_status(db: Session, mandate: Any, confirmation: Optional[dict],
                      today: Optional[str] = None) -> dict:
    """Anzeige-Status der Wiedervorlage-Policy (gleiche Quelle wie das Gate)."""
    today = _iso_day(today or _utc_now_iso())
    tenant_id = mandate_tenant_id(db, mandate)
    jurisdiction = kyc_review_jurisdiction(db, tenant_id)
    current = resolve_kyc_review_policy(db, tenant_id, jurisdiction, today)
    codes = [f["reason_code"] for f in kyc_review_findings(db, mandate, today, confirmation=confirmation)]
    if confirmation is not None and _iso_day(confirmation.get("next_review_due")) < today:
        codes.append(KYC_CONFIRMATION_REVIEW_OVERDUE)
    first = codes[0] if codes else None
    return {
        "status": KYC_REVIEW_STATUS_BY_CODE[first] if first else KYC_REVIEW_STATUS_OK,
        "reason_code": first,
        "finding_codes": codes,
        "policy_status": current["status"],
        "policy_reason_code": current["reason_code"],
        "tenant_id": tenant_id,
        "jurisdiction": jurisdiction,
        "policy": current["policy"],
        "binding": (
            {column: confirmation.get(column) for column in KYC_REVIEW_BINDING_COLUMNS}
            if confirmation is not None else None
        ),
    }


def kyc_review_release_findings(db: Session, mandate: Any, today: Optional[str] = None) -> list[dict]:
    """Kunden-PDF-Kanal: dieselbe Wiedervorlage-Pruefung, sobald eine
    KYC-Bestaetigung vorliegt (Bindung, Policy, Verkuerzung, Ablauf). Ohne
    Bestaetigung bleibt das PDF ein Entwurf vor Vertragsabschluss; den
    Abschluss sperren Finalisierung/Signatur (KYC_CONFIRMATION_MISSING)."""
    today = _iso_day(today or _utc_now_iso())
    confirmation = latest_kyc_confirmation(db, str(getattr(mandate, "client_id", "") or ""),
                                           getattr(mandate, "id", None))
    if confirmation is None:
        return []
    findings = kyc_review_findings(db, mandate, today, confirmation=confirmation)
    if _iso_day(confirmation.get("next_review_due")) < today:
        findings.append(_finding(
            KYC_CONFIRMATION_REVIEW_OVERDUE,
            "Die KYC-Bestaetigung ist ueberfaellig (naechste Aktualisierung am "
            f"{confirmation.get('next_review_due')}).",
            "Berater: Aktualisierung im SRO-/Fremdprozess durchfuehren und eine neue "
            "KYC-Bestaetigung erfassen.",
            "client",
            confirmation_id=confirmation.get("id"),
            kyc_review_status=KYC_REVIEW_STATUS_BY_CODE[KYC_CONFIRMATION_REVIEW_OVERDUE],
        ))
    return findings


# N-897-01: ausdrueckliche, zentrale Klassifikation ALLER PDF-/Berichtsrouten.
# "kundenwirksam" = Inhalt geht an den Kunden bzw. dokumentiert Empfehlung/
# Vertrag -> Wiedervorlage-Gate (assert_kyc_review_release_eligible) VOR jeder
# Wirkung. tests/test_c890_01_report_route_classification.py liest die echte
# App-Routentabelle: jede PDF-/Berichtsroute muss hier stehen, jede
# kundenwirksame muss bei faelliger/ungebundener KYC-Bestaetigung sperren.
REPORT_CLIENT_FACING = "kundenwirksam"
REPORT_INTERNAL = "intern"
REPORT_ROUTE_CLASSIFICATION: dict[str, tuple[str, str]] = {
    "GET /mandates/{mandate_id}/reports/anlagestrategie.pdf": (REPORT_CLIENT_FACING, "Anlagestrategie fuer den Kunden"),
    "GET /mandates/{mandate_id}/reports/assetallocation.pdf": (REPORT_CLIENT_FACING, "Asset-Allocation-Ausdruck fuer das Kundengespraech"),
    "GET /mandates/{mandate_id}/reports/risikoprofil.pdf": (REPORT_CLIENT_FACING, "Risikoprofil zur Unterschrift des Kunden"),
    "GET /mandates/{mandate_id}/reports/portfolio.pdf": (REPORT_CLIENT_FACING, "Anlagerezept/Portfolio fuer den Kunden"),
    "GET /mandates/{mandate_id}/reports/vertrag.pdf": (REPORT_CLIENT_FACING, "Vertragsdokumente"),
    "GET /mandates/{mandate_id}/reports/contract-signoff.pdf": (REPORT_CLIENT_FACING, "Kunden-Sign-off"),
    "GET /mandates/{mandate_id}/reports/protokoll.pdf": (REPORT_CLIENT_FACING, "Beratungsprotokoll (Kundenexemplar)"),
    "GET /mandates/{mandate_id}/reports/depotcheck.pdf": (REPORT_CLIENT_FACING, "Depotcheck-Analyse fuer den Kunden"),
    "GET /mandates/{mandate_id}/reports/backtest.pdf": (REPORT_CLIENT_FACING, "Backtest-Ausdruck fuer den Kunden"),
    "GET /mandates/{mandate_id}/reports/advisory-report.pdf": (REPORT_CLIENT_FACING, "Beratungsbericht (client-ready, Attachment)"),
    "GET /mandates/{mandate_id}/reports/cost-disclosure.pdf": (REPORT_CLIENT_FACING, "Ex-ante-Kostenausweis (FIDLEG)"),
    "GET /mandates/{mandate_id}/advisory-report": (REPORT_CLIENT_FACING, "React-Beratungsbericht (gleicher Inhalt wie das PDF)"),
    "GET /client-portal/mandates/{mandate_id}/report": (REPORT_CLIENT_FACING, "Bericht im Kundenportal"),
    "GET /mandates/{mandate_id}/reports/kundeninformation.pdf": (REPORT_INTERNAL, (
        "Kundeninformation Art. 8/9 FIDLEG: muss VOR Vertragsabschluss und vor der KYC-Bestaetigung "
        "abgegeben werden koennen; eigenes Gate (rechtliche Angaben)")),
    "GET /mandates/{mandate_id}/documents/{doc_id}/pdf": (REPORT_INTERNAL, (
        "Archivabruf bereits erzeugter, gesiegelter Dokumente als Nachweis; erzeugt keinen neuen Inhalt")),
    "GET /clients/{client_id}/data-export": (REPORT_INTERNAL, (
        "Datenauskunft nach DSG (gesetzlicher Anspruch der betroffenen Person), keine Empfehlung")),
    "GET /mandates/{mandate_id}/report-notes": (REPORT_INTERNAL, "interne Beraternotizen zum Bericht"),
    "PUT /mandates/{mandate_id}/report-notes": (REPORT_INTERNAL, "interne Beraternotizen zum Bericht"),
    "POST /mandates/{mandate_id}/advisory-log/from-report-generation": (REPORT_INTERNAL, "interner Beratungsprotokoll-Eintrag"),
    "GET /products/sustainability/attributes/export": (REPORT_INTERNAL, "Produkt-Referenzdaten, kein Kundenbezug"),
}


def is_report_route(path: str) -> bool:
    """Erkennung einer PDF-/Berichtsroute aus der Routentabelle."""
    last = path.rstrip("/").split("/")[-1].lower()
    return (path.endswith(".pdf") or path.endswith("/pdf") or "/reports/" in path
            or "report" in last or "export" in last)


def _call_on_block(on_block: Callable, reason_code: str, findings: list[dict]) -> None:
    # Ein Callback aus services.audit.release_block_audit protokolliert die
    # Policy-Bezuege der Wiedervorlage-Sperren zusaetzlich (ohne Freitext).
    if getattr(on_block, "accepts_findings", False):
        on_block(reason_code, None, findings=findings)
    else:
        on_block(reason_code, None)


def assert_kyc_review_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    http_status: int = 409,
    on_block: Optional[Callable[..., None]] = None,
) -> None:
    """Kunden-PDF-Gate der Wiedervorlage-Policy (gleiche Hülle wie
    ``assert_client_onboarding_release_eligible``)."""
    findings = kyc_review_release_findings(db, mandate)
    if not findings:
        return
    if on_block is not None:
        _call_on_block(on_block, CLIENT_ONBOARDING_INCOMPLETE, findings)
    raise DomainError(
        CLIENT_ONBOARDING_INCOMPLETE,
        f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: "
        + " ".join(f["message"] for f in findings),
        http_status=http_status,
        extra={
            "channel": channel,
            "findings": findings,
            "finding_codes": [f["reason_code"] for f in findings],
        },
    )


def _kyc_findings(db: Session, mandate: Any, today: str) -> list[dict]:
    client_id = str(getattr(mandate, "client_id", "") or "")
    findings: list[dict] = []
    dd = db.execute(
        _sql_text(
            "SELECT pep_status, acting_for_own_account, acting_for_own_account_answered "
            "FROM client_due_diligence WHERE client_id = :cid"
        ),
        {"cid": client_id},
    ).mappings().first()
    if dd is None or not int(dd.get("acting_for_own_account_answered") or 0):
        findings.append(_finding(
            KYC_BENEFICIAL_OWNER_UNANSWERED,
            "Die Frage, ob der Kunde auf eigene Rechnung handelt (wirtschaftlich "
            "Berechtigter, GwG Art. 4), ist nicht ausdruecklich beantwortet.",
            "Berater: Sorgfaltspflicht-Erfassung des Kunden oeffnen und die Frage "
            "'handelt auf eigene Rechnung' ausdruecklich beantworten.",
            "client",
        ))
    confirmation = latest_kyc_confirmation(db, client_id, getattr(mandate, "id", None))
    if confirmation is None:
        findings.extend(kyc_review_findings(db, mandate, today, confirmation=None))
        findings.append(_finding(
            KYC_CONFIRMATION_MISSING,
            "Bestaetigung fehlt: Fuer diesen Kunden ist nicht erfasst, dass die "
            "GwG-Abklaerung (Identifizierung der Vertragspartei nach GwG Art. 3, "
            "wirtschaftlich Berechtigter mit Formular A/K/S/T nach GwG Art. 4, "
            "Risikokategorie, PEP) im SRO- bzw. "
            "Fremdprozess erfolgt ist.",
            "Berater: KYC-Bestaetigung erfassen (Formular, Datum, Referenz, "
            "Risikokategorie, PEP, naechste Aktualisierung).",
            "client",
        ))
        return findings
    if not confirmation.get("seal_verified"):
        findings.append(_finding(
            KYC_CONFIRMATION_SEAL_INVALID,
            "Das Siegel der KYC-Bestaetigung stimmt nicht mit dem gespeicherten "
            "Inhalt ueberein; die Bestaetigung gilt nicht.",
            "Berater: neue KYC-Bestaetigung erfassen; Owner/Compliance: Vorgang pruefen.",
            "client",
            confirmation_id=confirmation.get("id"),
        ))
    # C-890-01: Bindung an die freigegebene Wiedervorlage-Policy und deren
    # heutige Wirksamkeit (dieselbe Pruefung wie API-Status und Kunden-PDF).
    findings.extend(kyc_review_findings(db, mandate, today, confirmation=confirmation))
    if kyc_requires_second_approval(confirmation) and confirmation.get("rejected"):
        findings.append(_finding(
            KYC_CONFIRMATION_REJECTED,
            "Die Zweitfreigabe dieser KYC-Bestaetigung wurde begruendet abgelehnt; "
            "die Bestaetigung wird nie wirksam.",
            "Berater: Sachverhalt klaeren und eine neue KYC-Bestaetigung erfassen, "
            "die erneut durch eine zweite Person freigegeben wird.",
            "client",
            confirmation_id=confirmation.get("id"),
        ))
    elif kyc_requires_second_approval(confirmation):
        approver = str(confirmation.get("approval_by") or "")
        if not approver or approver == str(confirmation.get("recorded_by") or ""):
            findings.append(_finding(
                KYC_SECOND_APPROVAL_MISSING,
                "PEP, erhoehtes Risiko oder Herabstufung gegenueber der zuletzt "
                "wirksamen Bestaetigung: die KYC-Bestaetigung ist noch nicht "
                "durch eine zweite Person freigegeben.",
                "Eine zweite Person (Admin oder externe Compliance-Freigabe) "
                "gibt die KYC-Bestaetigung frei.",
                "client",
                confirmation_id=confirmation.get("id"),
            ))
    if str(confirmation.get("next_review_due") or "") < today:
        findings.append(_finding(
            KYC_CONFIRMATION_REVIEW_OVERDUE,
            "Die KYC-Bestaetigung ist ueberfaellig (naechste Aktualisierung am "
            f"{confirmation.get('next_review_due')}).",
            "Berater: Aktualisierung im SRO-/Fremdprozess durchfuehren und eine neue "
            "KYC-Bestaetigung erfassen.",
            "client",
            confirmation_id=confirmation.get("id"),
            kyc_review_status=KYC_REVIEW_STATUS_BY_CODE[KYC_CONFIRMATION_REVIEW_OVERDUE],
        ))
    dd_pep = int(dd.get("pep_status") or 0) if dd is not None else None
    conf_pep = int(confirmation.get("is_pep") or 0)
    if dd_pep is not None and dd_pep != conf_pep:
        findings.append(_finding(
            KYC_PEP_INCONSISTENT,
            "Widerspruch: Sorgfaltspflicht-Erfassung und KYC-Bestaetigung fuehren "
            "den PEP-Status unterschiedlich"
            + (" (PEP in der Erfassung zurueckgenommen)." if conf_pep else "."),
            "Berater: PEP-Status klaeren und eine neue KYC-Bestaetigung erfassen; "
            "eine Herabstufung braucht die Freigabe einer zweiten Person.",
            "client",
            confirmation_id=confirmation.get("id"),
        ))
    return findings


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
    deliveries = [
        d for d in client_information_deliveries(db, mandate_id)
        if d["archive_verified"] and d["seal_verified"]
    ]
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
    elif not any(
        # N-890-02: massgebend sind Uebergabe UND Erfassung (Serverzeit) vor dem
        # Vertragsabschluss -- ein nachtraeglich erfasster Beleg zaehlt nie als
        # vorvertragliche Abgabe.
        str(d.get("delivered_at") or "") <= cutoff and str(d.get("recorded_at") or "") <= cutoff
        for d in deliveries
    ):
        findings.append(_finding(
            CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT,
            "Die Kundeninformation wurde nachtraeglich uebergeben bzw. erfasst "
            f"(Vertragsabschluss {cutoff}); Art. 9 FIDLEG verlangt die Abgabe vor "
            "Vertragsabschluss.",
            "Owner/Compliance: Vorgang pruefen; der Vertrag ist neu abzuschliessen, "
            "nachdem die Kundeninformation uebergeben wurde.",
            "mandate",
            contract_concluded_at=concluded,
        ))
    findings.extend(_kyc_findings(db, mandate, now[:10]))
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
    confirmation = latest_kyc_confirmation(db, str(mandate.client_id), str(mandate.id))
    latest = db.execute(
        _sql_text(
            "SELECT id, version, checksum_sha256, content_json, created_at FROM contract_documents "
            "WHERE mandate_id = :mid AND document_type = :dtype AND deleted_at IS NULL "
            "ORDER BY version DESC LIMIT 1"
        ),
        {"mid": str(mandate.id), "dtype": CLIENT_INFORMATION_DOCUMENT_TYPE},
    ).mappings().first()
    dd = db.execute(
        _sql_text(
            "SELECT pep_status, acting_for_own_account, acting_for_own_account_answered, "
            "beneficial_owner_name FROM client_due_diligence WHERE client_id = :cid"
        ),
        {"cid": str(mandate.client_id)},
    ).mappings().first()
    due_diligence = None
    if dd is not None:
        answered = bool(int(dd["acting_for_own_account_answered"] or 0))
        due_diligence = {
            "acting_for_own_account_answered": answered,
            "acting_for_own_account": (bool(int(dd["acting_for_own_account"] or 0)) if answered else None),
            "beneficial_owner_name": dd["beneficial_owner_name"],
            "pep_status": bool(int(dd["pep_status"] or 0)),
        }
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
        "kyc_confirmation": confirmation,
        "kyc_requires_second_approval": (
            kyc_requires_second_approval(confirmation) if confirmation else None
        ),
        # C-890-01: Wiedervorlage-Policy (Status, wirksame Version, Bindung).
        "kyc_review_policy": kyc_review_status(db, mandate, confirmation),
        "template_version": CLIENT_INFORMATION_TEMPLATE_VERSION,
        "latest_document": latest_document,
        "due_diligence": due_diligence,
    }


def assert_client_onboarding_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    http_status: int = 409,
    on_block: Optional[Callable[[str, Optional[str]], None]] = None,
) -> None:
    """Sperrt Finalisierung bzw. Vertragsunterzeichnung, solange Kunden-
    information (Art. 8/9 FIDLEG) oder GwG-Bestaetigung fehlen. Wirft
    ``DomainError`` mit ``reason_code`` CLIENT_ONBOARDING_INCOMPLETE und der
    Liste ``findings`` (je eigener Reason-Code + Owner-Hinweis), BEVOR der
    Kanal irgendeine Wirkung hat."""
    findings = client_onboarding_findings(db, mandate)
    if not findings:
        return
    if on_block is not None:
        # N-890-07: Audit-Eintrag (H7 release_block_audit) vor dem Raise;
        # C-890-01: Policy-Bezug der Wiedervorlage-Sperren mitprotokolliert.
        _call_on_block(on_block, CLIENT_ONBOARDING_INCOMPLETE, findings)
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


# ---------------------------------------------------------------------------
# H7 N-884-04: Retro-Gate auch fuer bereits finale Laeufe (Handoff, Signatur)
# ---------------------------------------------------------------------------
#
# Die Finalisierung sperrt seit H7 C-4 unvollstaendige Retrozessions-Ausweise
# (services/cost_disclosure.py::retrocession_finalization_block). Laeufe, die
# VOR diesem Gate final wurden, koennten sonst weiterhin weitergeleitet oder
# unterzeichnet werden. Gelesen wird das bei der Finalisierung EINGEFRORENE
# L1-Urteil (``product_retrocessions.complete``, ``requires_resolution`` der
# Kostenzeilen) -- keine Neuberechnung, keine zweite Retro-Logik. Fehlt der
# Snapshot oder ist er unlesbar und traegt der Lauf Produkte mit unbekannter
# oder positiver Retrozession, gilt das als nicht nachgewiesen (fail-closed).
# Reason-Codes wie bei der Finalisierung (Art. 26 FIDLEG; Art. 400 OR;
# BGE 137 III 393).

RETRO_RELEASE_INCOMPLETE = "RETROCESSION_DISCLOSURE_INCOMPLETE"
RETRO_RELEASE_UNAVAILABLE = "RETROCESSION_EVIDENCE_UNAVAILABLE"
_RETRO_HEAL = (
    "Retrozession im Fondsuniversum erfassen bzw. Verzicht (Beleg) oder "
    "Rückerstattung im Mandat dokumentieren und die Empfehlung neu finalisieren "
    "(Art. 26 FIDLEG; Art. 400 OR; BGE 137 III 393)."
)


def _release_run_row(db: Session, mandate: Any, run: Optional[Any]):
    if run is not None:
        return (
            str(run.id),
            str(getattr(run, "result_status", "") or ""),
            getattr(run, "cost_disclosure_snapshot_json", None),
        )
    return db.execute(
        _sql_text(
            "SELECT id, result_status, cost_disclosure_snapshot_json FROM recommendation_runs "
            "WHERE mandate_id = :mid AND result_status = 'Final' "
            "ORDER BY updated_at DESC, created_at DESC LIMIT 1"
        ),
        {"mid": str(mandate.id)},
    ).first()


def _run_has_retro_relevant_products(db: Session, run_id: str) -> bool:
    rates = db.execute(
        _sql_text(
            "SELECT p.retrocession_bps FROM recommendation_positions rp "
            "JOIN products p ON p.id = rp.product_id WHERE rp.run_id = :run_id"
        ),
        {"run_id": run_id},
    ).all()
    return any(rate is None or int(rate) > 0 for (rate,) in rates)


def retrocession_release_finding(
    db: Session, mandate: Any, run: Optional[Any] = None,
) -> Optional[tuple[str, str, Optional[str]]]:
    """(reason_code, message, run_id) fuer einen finalen Lauf mit nicht
    geklaerter Retrozession, sonst None. Ohne ``run``: der aktuelle finale
    Lauf des Mandats (Signatur). Nicht finale Laeufe prueft die Finalisierung."""
    row = _release_run_row(db, mandate, run)
    if row is None:
        return None
    run_id, status, snapshot_json = row[0], row[1], row[2]
    if status != "Final":
        return None
    payload = None
    if snapshot_json:
        try:
            payload = (json.loads(snapshot_json) or {}).get("payload")
        except (TypeError, ValueError, AttributeError):
            payload = None
    if not isinstance(payload, dict):
        if not _run_has_retro_relevant_products(db, str(run_id)):
            return None
        return (
            RETRO_RELEASE_UNAVAILABLE,
            "Für die finale Empfehlung liegt kein lesbarer, eingefrorener "
            "Retrozessions-Nachweis vor, und sie enthält Produkte mit unbekannter "
            "oder vorhandener Retrozession. " + _RETRO_HEAL,
            str(run_id),
        )
    summary = payload.get("product_retrocessions") or None
    retro_ok = summary is None or bool(summary.get("complete"))
    unresolved_items = any(
        bool(item.get("requires_resolution")) for item in (payload.get("cost_items") or [])
        if isinstance(item, dict)
    )
    if retro_ok and not unresolved_items:
        return None
    return (
        RETRO_RELEASE_INCOMPLETE,
        "Der eingefrorene Retrozessions-Ausweis der finalen Empfehlung ist "
        "unvollständig (unbekannte oder ungeregelte Vergütung von Dritten). "
        + _RETRO_HEAL,
        str(run_id),
    )


def assert_retrocession_release_eligible(
    db: Session,
    mandate: Any,
    *,
    channel: str,
    run: Optional[Any] = None,
    on_block: Optional[Callable[[str, Optional[str]], None]] = None,
) -> None:
    """Fail-closed-Gate fuer Handoff und Signatur (409). ``on_block`` (z.B.
    Audit-Eintrag des Routers) wird vor dem Raise mit (reason_code, run_id)
    aufgerufen."""
    finding = retrocession_release_finding(db, mandate, run)
    if finding is None:
        return
    reason_code, message, run_id = finding
    if on_block is not None:
        on_block(reason_code, run_id)
    raise DomainError(
        reason_code,
        f"{_CHANNEL_LABELS.get(channel, 'Freigabe nicht möglich')}: {message}",
        http_status=409,
        extra={"channel": channel, "recommendation_run_id": run_id},
    )
