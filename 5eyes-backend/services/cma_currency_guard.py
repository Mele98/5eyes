"""CMA-CURRENCY-GUARD-001 (Variablen-Audit 2026-10, Abschnitt 1.13 Basiswaehrung).

Befund: Die Kapitalmarktannahmen (CMA) werden ausschliesslich nach
Jurisdiktion gewaehlt (``services.jurisdiction.resolve.
resolve_cma_for_jurisdiction``). ``Mandate.base_currency`` steuert nur die
FX-Umrechnung der Betraege. Ein CH-Mandat mit Basiswaehrung EUR/USD rechnet
deshalb mit CHF-Renditen und CHF-Volatilitaeten -- ohne Waehrungsrisiko,
ohne Hedge-Kosten, ohne Zinsdifferenz. Das Ergebnis sieht aus wie eine
fundierte Strategie, ist fuer die Referenzwaehrung des Kunden aber nicht
hergeleitet.

Es werden KEINE Waehrungs-CMA erfunden (Data-Owner-Entscheid, siehe
Owner-Entscheid unten). Stattdessen fail-closed:

- Die Strategie bleibt berechenbar (Berater soll sehen, was herauskommt),
  wird aber mit Reason-Code ``CMA_CURRENCY_MISMATCH`` als "nicht freigegeben"
  markiert (Reasoning + Feld ``cma_currency_guard`` in der AA-Antwort,
  Hinweis im Report).
- Finalisierung der Empfehlung und CMA-abhaengige Kundendokumente (PDF)
  werden mit 409 blockiert, bis
  (a) eine CMA in der Basiswaehrung vorliegt, oder
  (b) der Berater die Abweichung bewusst bestaetigt: dokumentierte
      Begruendung ``cmaCurrencyMismatchReason`` im Praeferenz-Snapshot der
      Soll-Allokation (gleiches Muster und gleiche Qualitaetspruefung wie
      ``bandDeviationReason``). Die Bestaetigung wird im Kundendokument
      ausgewiesen, nie verschwiegen.

Waehrungsbasis einer CMA-Zeile: das Modell hat keine eigene
Waehrungsspalte. Die Basis ist die Heimwaehrung ihrer Jurisdiktion
(``JurisdictionProfile.home_currency``; ``CapitalMarketAssumption.
jurisdiction`` NULL = "CH"). Fuer CH ist sie zusaetzlich durch die
Spaltensemantik belegt (``bonds_chf_ig_*``, ``equity_ch_*``,
``real_estate_ch_*``) und wird ohne Profilzeile als CHF gelesen. Fuer jede
andere Jurisdiktion ohne Profilzeile ist die Basis UNBEKANNT und wird wie ein
Mismatch behandelt (nie stillschweigend "passt").

Owner-Entscheid (offen, Data-Owner): CMA je Referenzwaehrung (inkl.
FX-Vola, Hedge-Kosten, Zinsdifferenz) bzw. eine explizite Waehrungsspalte
auf ``capital_market_assumptions``. Bis dahin gilt dieses Gate.
"""
from __future__ import annotations

from typing import Any

from services.preference_snapshot import ReasonCodedConflictError

CMA_CURRENCY_MISMATCH = "CMA_CURRENCY_MISMATCH"
ACK_PREFERENCE_KEY = "cmaCurrencyMismatchReason"

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_NOT_APPLICABLE = "not_applicable"

PDF_NOTICE_HEADING = "KAPITALMARKTANNAHMEN — WÄHRUNGSBASIS NICHT FREIGEGEBEN"


def _normalize_currency(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def mandate_base_currency(mandate: Any) -> str:
    # Mandate.base_currency ist NOT NULL mit Default "CHF" (models/mandates.py).
    return _normalize_currency(getattr(mandate, "base_currency", None)) or "CHF"


def cma_currency_basis(db, cma: Any) -> str | None:
    """Waehrungsbasis einer CMA-Zeile (siehe Modul-Docstring) oder None."""
    if cma is None:
        return None
    jurisdiction = str(getattr(cma, "jurisdiction", None) or "CH").strip().upper() or "CH"
    home_currency = None
    if db is not None:
        from models.jurisdiction import JurisdictionProfile

        profile = (
            db.query(JurisdictionProfile)
            .filter(
                JurisdictionProfile.code == jurisdiction,
                JurisdictionProfile.deleted_at.is_(None),
            )
            .first()
        )
        home_currency = _normalize_currency(getattr(profile, "home_currency", None))
    if home_currency is None and jurisdiction == "CH":
        return "CHF"
    return home_currency


def _ack_reason(preferences: dict | None) -> str | None:
    raw = (preferences or {}).get(ACK_PREFERENCE_KEY) if isinstance(preferences, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def mismatch_message(base_currency: str, cma_currency: str | None) -> str:
    if cma_currency is None:
        return (
            "Kapitalmarktannahmen mit unbekannter Währungsbasis – für "
            f"Basiswährung {base_currency} nicht freigegeben."
        )
    return (
        f"Kapitalmarktannahmen in {cma_currency} – für Basiswährung "
        f"{base_currency} nicht freigegeben."
    )


def evaluate_cma_currency(
    db, mandate: Any, cma: Any, preferences: dict | None = None,
) -> dict[str, Any]:
    """Prueft Mandats-Basiswaehrung gegen die Waehrungsbasis der CMA.

    Rueckgabe (immer ein dict, auch im Gutfall -- maschinenlesbar):
    ``status`` ok|mismatch|acknowledged|not_applicable, ``reason_code`` (None bei ok),
    ``released`` (Finalisierung/Kundendokument erlaubt), ``message``,
    ``mandate_base_currency``, ``cma_currency``, ``acknowledgement_reason``
    (nur gesetzt, wenn sie die Qualitaetspruefung besteht) und
    ``acknowledgement_error`` (Grund, warum eine erfasste Begruendung nicht
    reicht).
    """
    base = mandate_base_currency(mandate)
    cma_currency = cma_currency_basis(db, cma)
    result: dict[str, Any] = {
        "status": STATUS_OK,
        "reason_code": None,
        "released": True,
        "message": None,
        "mandate_base_currency": base,
        "cma_currency": cma_currency,
        "acknowledgement_reason": None,
        "acknowledgement_error": None,
    }
    if cma is None:
        # Keine CMA verankert: nichts zu vergleichen. Fehlende CMA blockieren
        # die eigenen Gates (Finalisierung 422, PDF 409 "CMA-Snapshot fehlt").
        result["status"] = STATUS_NOT_APPLICABLE
        return result
    if cma_currency is not None and cma_currency == base:
        return result
    message = mismatch_message(base, cma_currency)
    result.update(status=STATUS_MISMATCH, reason_code=CMA_CURRENCY_MISMATCH, released=False, message=message)
    reason = _ack_reason(preferences)
    if reason is None:
        return result
    from services.override_reason_quality import (
        OverrideReasonQualityError,
        validate_override_reason_quality,
    )

    try:
        validate_override_reason_quality(reason)
    except OverrideReasonQualityError as exc:
        result["acknowledgement_error"] = str(exc)
        return result
    result.update(status=STATUS_ACKNOWLEDGED, released=True, acknowledgement_reason=reason)
    return result


def evaluate_for_allocation(db, mandate: Any, allocation: Any, fallback_cma: Any = None) -> dict[str, Any]:
    """Wie ``evaluate_cma_currency``, aber mit CMA und Bestaetigung aus der
    verankerten Soll-Allokation (CMA-Anker + Praeferenz-Snapshot)."""
    from models.allocation import CapitalMarketAssumption
    from services.portfolio_engine import _allocation_snapshot_preferences

    cma = fallback_cma
    cma_id = str(getattr(allocation, "capital_market_assumptions_id", "") or "").strip()
    if cma_id and db is not None:
        anchored = db.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == cma_id).first()
        if anchored is not None:
            cma = anchored
    try:
        preferences = _allocation_snapshot_preferences(allocation) if allocation is not None else None
    except ValueError:
        # Beschaedigter Snapshot: keine Bestaetigung lesbar -> fail-closed.
        preferences = None
    return evaluate_cma_currency(db, mandate, cma, preferences)


def evaluate_for_current_allocation(db, mandate: Any) -> dict[str, Any] | None:
    """Guard fuer die aktuelle Soll-Allokation des Mandats (Kundendokumente).

    None = keine aktuelle Soll-Allokation (die Dokument-Gates melden das
    selbst). CH-Mandat in CHF: DB-freier Kurzschluss (CH-CMA ist CHF), damit
    der CH-Bestand keinen Zusatz-Query bezahlt.
    """
    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH").strip().upper() or "CH"
    if jurisdiction == "CH" and mandate_base_currency(mandate) == "CHF":
        return None
    if db is None:
        return None
    from models.allocation import TargetAllocation

    allocation = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .first()
    )
    if allocation is None:
        return None
    return evaluate_for_allocation(db, mandate, allocation)


def reasoning_line(guard: dict | None) -> str | None:
    if not guard or guard.get("status") in (STATUS_OK, STATUS_NOT_APPLICABLE):
        return None
    if guard.get("status") == STATUS_ACKNOWLEDGED:
        return (
            f"{guard['message']} Vom Berater bewusst bestätigt: "
            f"{guard['acknowledgement_reason']} [{CMA_CURRENCY_MISMATCH}]"
        )
    hint = (
        " Die Strategie ist berechnet, aber NICHT freigegeben: Finalisierung "
        "und Kundendokumente sind blockiert, bis Kapitalmarktannahmen in der "
        "Basiswährung vorliegen oder der Berater die Abweichung mit "
        "dokumentierter Begründung bestätigt."
    )
    if guard.get("acknowledgement_error"):
        hint += f" Erfasste Begründung genügt nicht: {guard['acknowledgement_error']}"
    return f"{guard['message']}{hint} [{CMA_CURRENCY_MISMATCH}]"


def attach_to_strategy_payload(db, mandate: Any, payload: dict) -> dict:
    """Haengt ``cma_currency_guard`` an eine Strategie-Antwort und setzt den
    Hinweis an die Spitze des Reasonings (UI zeigt nur die ersten Punkte)."""
    allocation = payload.get("target_allocation")
    guard = evaluate_for_allocation(db, mandate, allocation, payload.get("capital_market_assumptions"))
    payload["cma_currency_guard"] = guard
    line = reasoning_line(guard)
    if line:
        reasoning = [item for item in list(payload.get("reasoning") or []) if item != line]
        payload["reasoning"] = [line] + reasoning
    return payload


class CmaCurrencyMismatchError(ReasonCodedConflictError):
    reason_code = CMA_CURRENCY_MISMATCH

    def __init__(self, guard: dict, *, context: str):
        self.guard = dict(guard)
        action = "Die Empfehlung kann nicht finalisiert werden" if context == "finalization" else (
            "Das Kundendokument kann nicht erstellt werden"
        )
        self.message = (
            f"{guard.get('message')} {action}, bis Kapitalmarktannahmen in der "
            "Basiswährung vorliegen oder der Berater die Abweichung mit "
            "dokumentierter Begründung bestätigt (Strategie mit Begründung neu "
            "berechnen)."
        )
        if guard.get("acknowledgement_error"):
            self.message += f" Erfasste Begründung genügt nicht: {guard['acknowledgement_error']}"
        super().__init__(f"{CMA_CURRENCY_MISMATCH}: {self.message}")

    def http_detail(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "mandate_base_currency": self.guard.get("mandate_base_currency"),
            "cma_currency": self.guard.get("cma_currency"),
        }


def enforce_release(guard: dict, *, context: str) -> dict:
    if not guard.get("released"):
        raise CmaCurrencyMismatchError(guard, context=context)
    return guard


def pdf_notice(guard: dict | None) -> dict | None:
    """Banner-Dict fuer Kundendokumente bei bestaetigter Abweichung."""
    if not guard or guard.get("status") in (STATUS_OK, STATUS_NOT_APPLICABLE):
        return None
    message = str(guard.get("message") or "")
    if guard.get("acknowledgement_reason"):
        message += f" Bewusste Bestätigung des Beraters: {guard['acknowledgement_reason']}"
    return {
        "heading": PDF_NOTICE_HEADING,
        "reason_code": CMA_CURRENCY_MISMATCH,
        "mandate_base_currency": guard.get("mandate_base_currency"),
        "cma_currency": guard.get("cma_currency"),
        "acknowledged": guard.get("status") == STATUS_ACKNOWLEDGED,
        "message": message,
    }


def merge_notices(provisional: dict | None, currency: dict | None) -> dict | None:
    """Ein Banner pro Dokument: Provisorik zuerst, Waehrungshinweis angehaengt."""
    if currency is None:
        return provisional
    if provisional is None:
        return currency
    merged = dict(provisional)
    merged["message"] = f"{provisional.get('message') or ''} {currency['message']}".strip()
    merged["cma_currency_guard"] = currency
    return merged
