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

CLASS-01-Fix (2026-10-07, Rubrik-1-Stammdaten-Audit, FIDLEG Art. 13 Abs. 3):
Vorher war `Client.client_classification` eine reine Audit-Trail-Groesse
("write-only") -- keine Suitability-/Advisory-Logik las sie je. Art. 13
Abs. 3 FIDLEG saezt zwei konkrete, eindeutige Rechtsfolgen:
1. Bei INSTITUTIONELLEN Kunden wird generelle Eignung fuer das angebotene
   Service vermutet -- die Eignungspruefungspflicht entfaellt vollstaendig,
   analog zu Execution-only (siehe `_mandate_requires_suitability()`).
2. Bei PROFESSIONELLEN Kunden (client_classification ODER
   is_professional_opt_out) wird NUR vermutet, dass Kenntnisse/Erfahrung und
   die finanzielle Risikofaehigkeit vorhanden sind -- die Anlageziele
   (Risikobereitschaft/Praeferenzen) bleiben individuell zu erheben, weil
   Eignung sich final immer an den TATSAECHLICHEN Zielen des Kunden misst,
   nicht an dessen Erfahrung. 5eyes' knowledge_services_json/
   knowledge_instruments_json-Felder sind ohnehin bereits optional (fliessen
   NIE in compute_scores()/final_score_x10 ein, siehe services/risk_scoring.py
   -- rein dokumentarisch) und die Risikokapazitaets-Punkte (q_income/
   q_obligations/q_savings/q_wealth) werden bewusst NICHT automatisch
   hochgesetzt: die Art.-13-Vermutung befreit von der DOKUMENTATIONSPFLICHT,
   sie darf NICHT die tatsaechliche, CAPM-relevante Risikokapazitaets-
   Bemessung verzerren (ein professioneller Kunde mit realem Einkommen X
   bleibt bei Einkommen X fuer die Portfoliokonstruktion massgeblich, auch
   wenn die rechtliche Pruefpflicht entfaellt). Die Maskenseite
   (Risikoprofil-UI-Anpassung fuer professionelle/institutionelle Kunden)
   wird separat im Frontend umgesetzt.
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
    ausgenommen ausdrueckliches Execution-only (Art. 13) ODER einen
    Institutionellen Kunden (CLASS-01-Fix, 2026-10-07, siehe Modul-Docstring
    "FIDLEG Art. 13 Abs. 3"-Nachtrag unten: bei institutionellen Kunden wird
    Eignung generell vermutet, die Pruefpflicht entfaellt vollstaendig)."""
    mtype = str(getattr(mandate, "mandate_type", "") or "").strip().lower()
    if mtype in MANDATE_TYPES_EXEMPT_FROM_SUITABILITY:
        return False
    client = getattr(mandate, "client", None)
    classification = str(getattr(client, "client_classification", "") or "").strip()
    if classification == "Institutioneller Kunde":
        return False
    return True


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
      'suitability_basis': 'risk_assessment' | 'execution_only_exempt'
                            | 'institutional_client_exempt' | None,
      'risk_assessment_id': str|None,
      'risk_assessment_version': int|None,
      'risk_assessment_date': str|None,
      'risk_assessment_profile': str|None,
      'risk_assessment_age_days': int|None,
      'risk_assessment_signed_at': str|None,      # Kunden-Signatur (Doku, s.u.)
      'risk_assessment_signed_method': str|None,  # 'portal' | 'advisor_recorded'
      'allocation_issues': [ {target_allocation_id, based_on_assessment_id, reason}, ... ],
      'override_reason_issues': [ {risk_assessment_id, reason_code, detail}, ... ],
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
        "allocation_issues": [],
        "override_reason_issues": [],
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

    # Execution-only (Art. 13) oder institutioneller Kunde (Art. 13 Abs. 3):
    # keine Eignungspruefung noetig -> konform. Die beiden Ausnahmegruende
    # werden unterschieden, damit Reporting/PDF den richtigen FIDLEG-Verweis
    # zitieren (CLASS-01-Fix, 2026-10-07).
    if not _mandate_requires_suitability(mandate):
        client = getattr(mandate, "client", None)
        classification = str(getattr(client, "client_classification", "") or "").strip()
        if classification == "Institutioneller Kunde":
            base["suitability_basis"] = "institutional_client_exempt"
            base["fidleg_basis"] = "Art. 13 Abs. 3 FIDLEG"
        else:
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

    # Kontrollrunde 2026-09-21 (Override-Begruendungs-Audit): ein Berater-
    # Override (is_overridden=1) verlangt eine FIDLEG-Art.-13-taugliche
    # Begruendung (services.override_reason_quality). Diese wird beim
    # SCHREIBEN via Pydantic erzwungen (schemas/profiling.py) und beim
    # LIVE-ENGINE-Lauf erneut geprueft (services.risk_assessment_semantics.
    # validate_risk_assessment_model_input, aufgerufen aus portfolio_engine
    # /risk_matrix/advisory_log_service) -- ABER dieser Audit-Report las
    # is_overridden/override_reason bisher gar nicht. Ein Altbestand-Override
    # (vor der Qualitaets-Pruefung von Sprint U-28/U-29 am 2026-06-03
    # angelegt) oder ein Override, dessen zugehoeriger RiskAssessment nie
    # wieder einen Live-Engine-Lauf durchlaeuft, ging damit unentdeckt durch
    # diesen Audit als "konform" -- weder hier noch in der PDF-Compliance-
    # Sektion (services.advisory_report._build_suitability_compliance
    # spiegelt diesen Audit 1:1) erschien ein Hinweis.
    if int(getattr(ra, "is_overridden", 0) or 0) == 1:
        from services.override_reason_quality import (
            OverrideReasonQualityError,
            validate_override_reason_quality,
        )
        try:
            validate_override_reason_quality(
                getattr(ra, "override_reason", None)
            )
        except OverrideReasonQualityError as exc:
            base["override_reason_issues"].append({
                "risk_assessment_id": base["risk_assessment_id"],
                "reason_code": exc.reason_code,
                "detail": str(exc),
            })
            base["is_compliant"] = False

    # Kontrollrunde 2026-09-20 (Risikoprofil-Audit): ein FRISCHES Risikoprofil
    # allein sagt nichts darueber aus, ob die AKTUELLE Soll-Allokation auch
    # unter DIESEM Profil erstellt wurde. Ohne diesen Check konnte ein Mandat
    # nach einer Risikoprofil-Herabstufung (z.B. Wachstumsorientiert ->
    # Defensiv) weiterhin eine alte, zu aggressive Allokation halten, und
    # dieser Audit meldete trotzdem is_compliant=True (nur Existenz+Alter des
    # Profils geprueft, nie ob es zur tatsaechlich verwendeten Allokation
    # passt) -- die IST/SOLL-Band-Pruefung in services/depot_check.py liest
    # die Baender zudem direkt von der persistierten TargetAllocation, nicht
    # neu aus dem aktuellen Profil abgeleitet, haette den Widerspruch also
    # ebenfalls nicht gefangen. Derselbe Identitaets-Check existiert bereits
    # in services/portfolio_engine.py::build_target_payload_from_allocation
    # (dort als harte Exception fuer den Live-Strategiepfad) -- hier als
    # nicht-blockierender Compliance-Befund fuer den Audit-Report gespiegelt.
    # Nur fuer "modern_context"-Allokationen geprueft (identisches Gate wie
    # im Live-Pfad) -- Alt-Allokationen ohne based_on_assessment_id bleiben
    # aus Rueckwaertskompat-Gruenden unangetastet.
    try:
        from services.portfolio_engine import _current_target_allocation_or_none
        ta = _current_target_allocation_or_none(db, mandate.id)
    except Exception:  # noqa: BLE001 — degraded statt fehlgedeutet, wie oben
        ta = None
        base["audit_degraded"] = True
        base["is_compliant"] = None
    if ta is not None:
        from services.risk_assessment_semantics import (
            target_allocation_predates_current_assessment,
        )
        if target_allocation_predates_current_assessment(ta, base["risk_assessment_id"]):
            base["allocation_issues"].append({
                "target_allocation_id": getattr(ta, "id", None),
                "based_on_assessment_id": str(
                    getattr(ta, "based_on_assessment_id", "") or ""
                ),
                "reason": "allocation_predates_current_risk_assessment",
            })
            base["is_compliant"] = False

    return base
