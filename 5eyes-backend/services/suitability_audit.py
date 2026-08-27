"""Sprint U-66 (2026-06-03): FIDLEG-Geeignetheitserklaerung Audit-Service.

Hintergrund
-----------
FIDLEG Art. 11-13 verlangt fuer Anlageberatung mit Einzelempfehlung
(Vollberatung) eine Geeignetheitspruefung VOR der Empfehlung. Pre-U-66
existierten die Modelle (SuitabilityCheck + AdvisoryLog.
suitability_check_id), aber kein Code-Pfad pruefte ob die Pflicht
eingehalten wurde -> ein Audit-Befund konnte erst bei manueller
Inspektion entstehen.

Diese Modul liefert einen read-only Audit-Service:
- audit_mandate_suitability(db, mandate) -> strukturierter Befund pro
  Mandat: alle relevanten AdvisoryLog-Eintraege + Verstoesse.

Designed als NON-BREAKING Audit-Layer (kein Pflicht-Check in
advisory_log_service.create_entry — das waere Breaking-Change und
sollte separat per Spec entschieden werden). Hier nur: Sichtbarkeit
schaffen, damit der Berater den Bestand abklopfen kann.

FIDLEG-Bezug
------------
- Art. 11: Pflicht Geeignetheitspruefung bei Vermoegensverwaltung +
  Anlageberatung mit Beruecksichtigung des Portfolios
- Art. 13: Pflicht ueber Empfehlung zu unterlassen, wenn ungeeignet
  (oder warnen + Auftrag dokumentieren)
- Art. 16: Dokumentationspflicht
- BVI/SBVg-Praxis: 12-Monats-Freshness als Industry-Standard
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

# Suitability-Check-Freshness in Tagen (12 Monate per Industry-Praxis).
SUITABILITY_FRESHNESS_MAX_DAYS = 365

# duty_type-Werte die (auf Log-Ebene) eine Geeignetheitspruefung VERLANGEN.
# Historisch (Per-Log-Design). Bleibt fuer Referenz/Rueckwaertskompat erhalten,
# ist aber NICHT mehr der Treiber des Audits (siehe unten, Art.-12-Umstellung).
DUTY_TYPES_REQUIRING_SUITABILITY = {
    "advisory_individual",  # Vollberatung mit Einzelempfehlung
    "advisory_portfolio",   # Vermoegensverwaltung
    "portfolio_management",
}

# Mandatstypen, die KEINE Eignungspruefung verlangen (reines Execution-only /
# blosse Auftragsuebermittlung -> FIDLEG Art. 13 "Ausnahme von der Pruefpflicht").
# Alles andere ist in 5eyes portfoliobezogene Anlageberatung bzw. Vermoegens-
# verwaltung und faellt damit unter die EIGNUNGSPRUEFUNG (Art. 12).
MANDATE_TYPES_EXEMPT_FROM_SUITABILITY = {
    "execution_only", "execution-only", "executiononly",
    "ausfuehrung", "ausführung", "auftragsuebermittlung", "no_advice",
}


def _mandate_requires_suitability(mandate: Any) -> bool:
    """FIDLEG Art. 10 (Pruefpflicht) + Art. 12 (Eignungspruefung): Wer
    portfoliobezogene Anlageberatung oder Vermoegensverwaltung erbringt, muss
    eine Eignungspruefung durchfuehren. 5eyes erbringt genau das (SAA-/Portfolio-
    Methodik), daher verlangt praktisch jedes Mandat eine Eignungspruefung —
    ausgenommen ausdrueckliches Execution-only (Art. 13)."""
    mtype = str(getattr(mandate, "mandate_type", "") or "").strip().lower()
    return mtype not in MANDATE_TYPES_EXEMPT_FROM_SUITABILITY


def _current_risk_assessment(db: Session, mandate_id: Any):
    """Aktuelles Risikoprofil (= 5eyes-Eignungspruefung nach Art. 12) fuer ein
    Mandat. Das RiskAssessment erfasst finanzielle Verhaeltnisse (Einkommen/
    Verpflichtungen/Ersparnis/Vermoegen), Anlageziel + Horizont und Risiko-
    bereitschaft — die von Art. 12 verlangten Elemente. None NUR wenn schlicht
    keins existiert. Ein Schema-/DB-Fehler wird NICHT verschluckt (er darf nicht
    als 'kein Profil' = non-compliant fehlgedeutet werden), sondern propagiert
    und wird im Audit als 'degraded' behandelt.

    FIDLEG-STATE-003 (Codex-Audit 2026-08-27): delegiert bewusst an den bereits
    vorhandenen, strengeren Kern-Resolver _current_risk_assessment_or_none()
    (services/portfolio_engine.py) statt eine eigene, schwaechere Query zu
    pflegen. Der Kern-Resolver filtert zusaetzlich deleted_at IS NULL — ohne
    diesen Filter konnte hier ein SOFT-DELETED RiskAssessment (is_current=1,
    aber geloescht) faelschlich als aktuelles/gueltiges Profil durchgehen und
    das Mandat als konform (is_compliant=True) auf Basis veralteter/geloeschter
    Daten ausweisen. Der Kern-Resolver wirft zudem ValueError bei mehreren
    mehrdeutigen 'aktuellen' Zeilen; das wird vom Caller (audit_mandate_
    suitability) bereits ueber den bestehenden 'except Exception' -> degraded-
    Pfad abgefangen (read-only Audit-Pfad, kein harter 409 wie bei den
    mutierenden Router-Aufrufern)."""
    from services.portfolio_engine import _current_risk_assessment_or_none
    return _current_risk_assessment_or_none(db, mandate_id)


def _parse_iso(value: Any) -> Optional[datetime]:
    """Best-Effort ISO-Parsing mit aware-UTC-Default."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Normalize Z -> +00:00 fuer fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def evaluate_suitability_freshness(
    check_dt: Optional[datetime],
    reference_dt: datetime,
    *,
    max_age_days: int = SUITABILITY_FRESHNESS_MAX_DAYS,
) -> dict[str, Any]:
    """Bewertet ob ein SuitabilityCheck zum Referenz-Zeitpunkt noch
    'frisch' ist (=binnen max_age_days vor reference_dt)."""
    if check_dt is None:
        return {"fresh": False, "reason": "missing_checked_at",
                "age_days": None}
    if check_dt > reference_dt:
        return {"fresh": False, "reason": "check_after_advisory",
                "age_days": None}
    age = (reference_dt - check_dt).days
    if age > max_age_days:
        return {"fresh": False, "reason": "stale",
                "age_days": age}
    return {"fresh": True, "reason": "ok", "age_days": age}


def audit_mandate_suitability(
    db: Session, mandate: Any,
) -> dict[str, Any]:
    """FIDLEG-Eignungspruefungs-Audit auf MANDATSEBENE
    (Art. 10 Pruefpflicht + Art. 12 Eignungspruefung).

    Umstellung 2026-07-19 (Option A): Frueher wurde pro AdvisoryLog-Eintrag ein
    'duty_type' + 'suitability_check_id' geprueft — beide Spalten existieren auf
    AdvisoryLog gar nicht, weshalb der Audit IMMER 'compliant' meldete (blind).

    Rechtlich korrekt ist die Eignungspruefung ohnehin eine mandats-/beziehungs-
    bezogene, REGELMAESSIG zu aktualisierende Pflicht (Art. 12): Wer portfolio-
    bezogene Anlageberatung oder Vermoegensverwaltung erbringt — 5eyes tut das —
    muss finanzielle Verhaeltnisse, Anlageziele und Kenntnisse/Erfahrung erheben
    und aktuell halten. In 5eyes IST diese Eignungspruefung das aktuelle
    RiskAssessment (Risikoprofil). Der Audit prueft daher: existiert ein
    AKTUELLES (<= SUITABILITY_FRESHNESS_MAX_DAYS Tage) Risikoprofil? Fehlt es
    oder ist es veraltet -> nicht konform.

    Schema-Output (rueckwaertskompatibel + neue risk_assessment_* Felder fuer die
    Zusammenfassung "wann/welches Profil"):
    {
      'total_advisory_logs': N,          # informativ (Beratungsprotokoll-Eintraege)
      'logs_requiring_suitability': 0|1, # 1 wenn das Mandat eine Eignungspr. verlangt
      'logs_with_suitability': 0|1,      # 1 wenn ein aktuelles/frisches Profil vorliegt
      'logs_without_suitability': [ {reason, detail}, ... ],
      'freshness_issues': [ {risk_assessment_id, reason, age_days}, ... ],
      'result_issues': [],
      'requires_suitability': bool,
      'suitability_basis': 'risk_assessment' | 'execution_only_exempt' | None,
      'risk_assessment_id': str|None,
      'risk_assessment_version': int|None,
      'risk_assessment_date': str|None,
      'risk_assessment_profile': str|None,
      'risk_assessment_age_days': int|None,
      'risk_assessment_signed_at': str|None,      # Kunden-Signatur (Doku, s.u.)
      'risk_assessment_signed_method': str|None,  # 'portal' | 'advisor_recorded'
      'is_compliant': bool,
      'fidleg_basis': 'Art. 10 / Art. 12 FIDLEG',
    }
    """
    now = datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "total_advisory_logs": 0,
        "logs_requiring_suitability": 0,
        "logs_with_suitability": 0,
        "logs_without_suitability": [],
        "freshness_issues": [],
        "result_issues": [],
        "requires_suitability": False,
        "suitability_basis": None,
        "risk_assessment_id": None,
        "risk_assessment_version": None,
        "risk_assessment_date": None,
        "risk_assessment_profile": None,
        "risk_assessment_age_days": None,
        # FIDLEG-Kunden-Signatur des Risikoprofils (reine Dokumentation, aendert
        # is_compliant NICHT). None solange kein aktuelles Profil geladen/signiert.
        "risk_assessment_signed_at": None,
        "risk_assessment_signed_method": None,
        "audit_degraded": False,
        "is_compliant": True,
        "fidleg_basis": "Art. 10 / Art. 12 FIDLEG",
    }

    # Anzahl Beratungsprotokoll-Eintraege (nur informativ fuer die Anzeige).
    try:
        from models.review import AdvisoryLog
        base["total_advisory_logs"] = (
            db.query(AdvisoryLog)
            .filter(AdvisoryLog.mandate_id == mandate.id)
            .count()
        )
    except Exception:  # noqa: BLE001 — robust gegen Schema-Mismatch
        base["total_advisory_logs"] = 0

    # Execution-only (Art. 13): keine Eignungspruefung noetig -> konform.
    if not _mandate_requires_suitability(mandate):
        base["suitability_basis"] = "execution_only_exempt"
        base["is_compliant"] = True
        return base

    base["requires_suitability"] = True
    base["logs_requiring_suitability"] = 1
    base["suitability_basis"] = "risk_assessment"

    # Infra-/Schema-Fehler beim Laden des Risikoprofils NICHT als 'kein Profil'
    # (= non-compliant) fehldeuten -> fail-closed 'degraded' (is_compliant=None,
    # audit_degraded=True), konsistent zum Renderer (zeigt 'Pruefung nicht moeglich').
    try:
        ra = _current_risk_assessment(db, mandate.id)
    except Exception:  # noqa: BLE001
        base["suitability_basis"] = "degraded"
        base["audit_degraded"] = True
        base["is_compliant"] = None
        return base

    if ra is None:
        base["logs_without_suitability"].append({
            "reason": "no_current_risk_assessment",
            "detail": ("Keine aktuelle Eignungspruefung (Risikoprofil) fuer das "
                       "Mandat erfasst — FIDLEG Art. 12 verlangt sie vor "
                       "portfoliobezogener Anlageberatung."),
        })
        base["is_compliant"] = False
        return base

    base["risk_assessment_id"] = getattr(ra, "id", None)
    base["risk_assessment_version"] = getattr(ra, "version", None)
    base["risk_assessment_date"] = (
        getattr(ra, "assessed_at", None) or getattr(ra, "valid_from", None)
    )
    base["risk_assessment_profile"] = getattr(ra, "final_profile", None)
    base["risk_assessment_signed_at"] = getattr(ra, "client_signed_at", None)
    base["risk_assessment_signed_method"] = getattr(ra, "client_signed_method", None)

    ra_dt = (_parse_iso(getattr(ra, "assessed_at", None))
             or _parse_iso(getattr(ra, "valid_from", None)))
    freshness = evaluate_suitability_freshness(ra_dt, now)
    base["risk_assessment_age_days"] = freshness["age_days"]
    if freshness["fresh"]:
        base["logs_with_suitability"] = 1
        base["is_compliant"] = True
    else:
        base["freshness_issues"].append({
            "risk_assessment_id": base["risk_assessment_id"],
            "reason": freshness["reason"],
            "age_days": freshness["age_days"],
        })
        base["is_compliant"] = False

    return base
