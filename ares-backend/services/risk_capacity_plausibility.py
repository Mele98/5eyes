"""Plausibilitaetspruefung der Risikofaehigkeit gegen die erfassten Finanzdaten.

RISK-CAPACITY-PLAUSIBILITY-001 (Variablen-Audit 2026-10-18, P0).

Die Risikofaehigkeit stammt ausschliesslich aus dem Fragebogen (Fragen 3, 5,
6, 7 und 8; ``services/risk_scoring.py``). Sie wurde bisher nie gegen das
gehalten, was in der App strukturiert erfasst ist (Vermoegenspositionen,
Hypotheken/Verbindlichkeiten, Cashflows, Ziele). Ein Kunde konnte "hohe
Risikofaehigkeit" angeben, obwohl er laut erfassten Daten hohe Schulden, ein
negatives Budget oder grosse Nahziele hat.

Dieses Modul ist bewusst KEIN neuer Score:

* es aendert das Risikoprofil NIE (der Fragebogen bleibt nach §2 die einzige
  Quelle; Profil = MIN(Faehigkeit, Bereitschaft) bleibt unveraendert);
* es blockiert die Strategie NICHT;
* es meldet einen Widerspruch mit Reason-Code ``RISK_CAPACITY_INCONSISTENT``
  und konkreter Begruendung. Der Berater entscheidet: Fragebogen korrigieren
  oder das Profil per Override nach unten setzen (User-Regel: "immer den
  tieferen Wert").

Pruefrichtung: es wird ausschliesslich ein UEBERschaetzen der Risikofaehigkeit
gemeldet (Angabe guenstiger als die Daten). Eine guenstigere Datenlage als
angegeben ist konservativ und kein Befund.

Robustheit: Die erfassten Daten sind oft unvollstaendig (nicht jede Ausgabe
ist als Cashflow erfasst). Jede Regel ist darum so formuliert, dass fehlende
Daten den Befund abschwaechen statt ihn zu erfinden -- z.B. gilt das frei
verfuegbare Vermoegen als OBERGRENZE (alle nicht gebundenen Positionen), die
Sparquote als Obergrenze (Brutto- statt Nettoeinkommen). Wo eine Regel ohne
Daten nicht pruefbar ist, wird das explizit als "nicht pruefbar" ausgewiesen,
nie still als "konsistent".

Datenabdeckung je Regel (RISK-CAPACITY-COVERAGE-001, Codex-Review PR #647):
jede Pruefung braucht ihre eigene Datenbasis. Fehlen erfasste Ausgaben, sind
Frage 5 und Frage 7 "nicht pruefbar" -- eine fehlende Ausgabe ist keine
verifizierte Nullausgabe. Ist mindestens eine Regel nicht pruefbar und kein
Widerspruch gefunden, lautet der Gesamtstatus ``partial`` (nie
``consistent``). Ausgaben, die innerhalb des Vorausfensters
(``obligation_forward_window_months``) beginnen, zaehlen mit, weil Frage 5
auch kuenftig absehbare Verpflichtungen umfasst; massgebend ist die hoechste
monatliche Belastung im Fenster (Zeitprofil), nicht die Summe.
Einkommen wird im selben Fenster konservativ gewertet (CIO-Entscheid
2026-10-19): fuer Frage 3 und Frage 7 gilt das TIEFSTE monatliche Einkommen
im Fenster (ein heute aktives Einkommen, das im Fenster wegfaellt, zaehlt
nicht mehr; kuenftige neue Einkommen zaehlen nie). Die Sparquote wird je
Monatssegment aus Einkommen und Belastung DESSELBEN Monats gebildet;
massgebend ist der unguenstigste Monat.

Zeilenpraesenz ist keine Vollstaendigkeit (Codex-Closure-Review PR #653,
2026-10-20): erfasste Ausgabenzeilen sind ohne Berater-Bestaetigung nur eine
UNTERGRENZE (Coverage ``rows_unattested``). Ein niedriger Ausgabenwert belegt
Frage 5 und Frage 7 erst mit einer gueltigen FinancialCoverageAttestationV1
(``services/financial_coverage_attestation.py``: Haushalt, Kategorien,
unregelmaessige Ausgaben, Stichtag, Quelle, Actor, Policy, Cashflow-
Fingerprint). Ein bereits zu hoher Wert flaggt weiterhin einwegig.

``partial`` und ``not_evaluable`` sind kein stiller Zustand: Strategie-
Reasoning, Berater-PDF, Monolith-Banner und Audit zeigen sie als "noch nicht
verifiziert" (``VERIFICATION_CODE``) mit konkretem Aufloesungsauftrag
(``resolution_actions``).

Evidenz: Jedes nicht konsistente Ergebnis wird append-only im Audit-Log
festgehalten (Status, offene Pruefungen, Bestaetigungs-ID/-Hash,
``evaluation_hash`` = SHA-256 ueber Regelversion, Status, Befunde, Coverage
und Datengrundlage). Beim Speichern des Risikoprofils und bei der Generierung
wird zusaetzlich JEDE Bewertung als unveraenderliche, gehashte
``RiskCapacityPlausibilityEvaluationV1`` persistiert (Eingaben, Regelversion,
Ergebnis; services/risk_capacity_evaluation_snapshot.py) -- spaetere
Datenaenderungen deuten sie nicht um, sondern machen sie "neu zu pruefen".
Ein Aufloesungs-Workflow (Akzeptanz/Override einer offenen Coverage) waere
ein eigener Schritt.

Alle Schwellen sind CIO-Defaults, Compliance zu bestaetigen (siehe
``THRESHOLDS``); sie sind versioniert (``PLAUSIBILITY_RULES_VERSION``), damit
ein Audit-Eintrag nachvollziehbar bleibt, wenn die Schwellen spaeter geaendert
werden.
"""
from __future__ import annotations

import calendar
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from services.risk_scoring import (
    CAPACITY_BAND,
    HORIZON_YEARS,
    canonicalize_horizon_label,
)

logger = logging.getLogger(__name__)

REASON_CODE = "RISK_CAPACITY_INCONSISTENT"
# partial / not_evaluable: kein Widerspruch, aber noch nicht verifiziert.
VERIFICATION_CODE = "RISK_CAPACITY_NOT_VERIFIED"
# v3 (2026-10-20, PR #653 Restbefund A): Ausgaben-Coverage "recorded" nur mit
# gueltiger FinancialCoverageAttestationV1, sonst "rows_unattested".
PLAUSIBILITY_RULES_VERSION = "RCP-2026-10-20.v3"

STATUS_CONSISTENT = "consistent"
STATUS_INCONSISTENT = "inconsistent"
STATUS_NOT_EVALUABLE = "not_evaluable"
# Kein Widerspruch gefunden, aber mindestens eine Regel war mangels eigener
# Datenbasis (oder nicht zuordenbarer Antwort) nicht pruefbar.
STATUS_PARTIAL = "partial"

# Datenabdeckung je Regel (``result["coverage"]``).
COVERAGE_RECORDED = "recorded"          # erfasste Zeilen (Ausgaben: + gueltige Vollstaendigkeits-Bestaetigung)
COVERAGE_ROWS_UNATTESTED = "rows_unattested"  # Ausgabenzeilen ohne Bestaetigung (Untergrenze)
COVERAGE_DERIVED_ONLY = "derived_only"  # nur aus Positionen abgeleitet (Untergrenze)
COVERAGE_MISSING = "missing"            # keine Datenbasis
COVERAGE_ANSWER_UNMAPPED = "answer_unmapped"  # Antwort keiner Option zuzuordnen
COVERAGE_NOT_APPLICABLE = "not_applicable"    # Angabe kann nichts ueberschaetzen

# Pruef-IDs (stabil fuer UI/Audit/Tests).
CHECK_INCOME = "INCOME_ABOVE_RECORDED"
CHECK_OBLIGATIONS = "OBLIGATIONS_BELOW_RECORDED"
CHECK_FREE_WEALTH = "FREE_WEALTH_ABOVE_RECORDED"
CHECK_SAVINGS = "SAVINGS_RATE_ABOVE_RECORDED"
CHECK_LEVERAGE = "LEVERAGE_HIGH"
CHECK_NEAR_TERM_GOALS = "NEAR_TERM_GOALS_HIGH"

CHECK_SHORT_LABELS = {
    CHECK_INCOME: "Frage 3 Einkommen",
    CHECK_OBLIGATIONS: "Frage 5 Verpflichtungen",
    CHECK_FREE_WEALTH: "Frage 6 freies Vermögen",
    CHECK_SAVINGS: "Frage 7 Sparquote",
    CHECK_LEVERAGE: "Verschuldung",
    CHECK_NEAR_TERM_GOALS: "Nahziele",
}

# ---------------------------------------------------------------------------
# Antwort-Baender des Fragebogens (§2, 1:1 aus ares.html, CHF).
# (untere Grenze, obere Grenze | None = offen). Index = Antwortposition.
# ---------------------------------------------------------------------------
INCOME_BANDS_CHF_MONTH: tuple[tuple[int, int | None], ...] = (
    (0, 6_000), (6_000, 9_000), (9_000, 12_000), (12_000, 20_000), (20_000, None),
)
OBLIGATION_BANDS_CHF_MONTH: tuple[tuple[int, int | None], ...] = (
    (0, 3_000), (3_000, 5_000), (5_000, 8_000), (8_000, 12_000), (12_000, None),
)
FREE_WEALTH_BANDS_CHF: tuple[tuple[int, int | None], ...] = (
    (0, 100_000), (100_000, 250_000), (250_000, 1_000_000),
    (1_000_000, 2_000_000), (2_000_000, None),
)
SAVINGS_RATE_BANDS_PCT: tuple[tuple[int, int | None], ...] = (
    (0, 0), (1, 10), (10, 25), (25, 50), (50, None),
)
# Punkte je Antwortposition (identisch zu RISK_*_POINTS im Monolithen).
INCOME_POINTS = (0, 1, 2, 3, 4)
OBLIGATION_POINTS = (4, 3, 2, 1, 0)
WEALTH_POINTS = (0, 3, 6, 9, 12)
SAVINGS_POINTS = (0, 3, 6, 9, 12)

# ---------------------------------------------------------------------------
# Schwellen -- CIO-Default, Compliance zu bestaetigen.
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, Any] = {
    # Toleranz fuer Brutto/Netto, Rundung und Erfassungszeitpunkt: gemeldet
    # wird erst, wenn der erfasste Wert die Bandgrenze um mehr als 10 % verfehlt.
    "income_tolerance_ratio": 0.10,
    "obligation_tolerance_ratio": 0.10,
    "free_wealth_tolerance_ratio": 0.10,
    # Sparquote: Toleranz in Prozentpunkten; ein negatives Budget bei einer
    # angegebenen Sparquote > 0 % ist immer ein Befund.
    "savings_rate_tolerance_pp": 5.0,
    # Verschuldungsgrad = Verbindlichkeiten / Brutto-Vermoegen. 2/3 entspricht
    # der ueblichen Belehnungsgrenze der 1. Hypothek: darueber ist ein
    # wesentlicher Teil des Vermoegens fremdfinanziert.
    "leverage_ratio_max": 2 / 3,
    # Nahziele: Kapitalbedarf aus Zielen, die innerhalb von 3 Jahren faellig
    # werden, im Verhaeltnis zum liquiden Vermoegen.
    "near_term_goal_years": 3,
    "near_term_goal_share_max": 0.50,
    # Frage 5 umfasst "aktuelle und kuenftig absehbare" Verpflichtungen:
    # erfasste Ausgaben, die innerhalb dieses Vorausfensters beginnen, zaehlen
    # mit (hoechste monatliche Belastung im Fenster). CIO-Default 12 Monate,
    # Compliance zu bestaetigen.
    "obligation_forward_window_months": 12,
    # Strukturregeln (Verschuldung, Nahziele) melden nur, wenn der Fragebogen
    # mindestens eine mittlere Risikofaehigkeit (Band "Ausgewogen" = 3 von 5)
    # bzw. einen langen Horizont (>= 6 Jahre) ausweist -- sonst steht die
    # Angabe nicht im Widerspruch zur Datenlage.
    "structural_min_capacity_band": 3,
    "structural_min_horizon_years": 6,
}

_FREQUENCY_PER_YEAR = {
    "monatlich": 12,
    "quartalsweise": 4,
    "halbjährlich": 2,
    "jährlich": 1,
}


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeclaredCapacity:
    """Die fuer die Pruefung relevanten Fragebogen-Angaben."""

    income_band: int | None
    obligations_band: int | None
    free_wealth_band: int | None
    savings_band: int | None
    capacity_band: int | None
    horizon_years: int | None
    capacity_score_x10: int | None = None
    willingness_score_x10: int | None = None
    final_score_x10: int | None = None
    is_overridden: bool = False
    override_score_x10: int | None = None


@dataclass(frozen=True)
class RecordedFinancials:
    """Erfasste Finanzdaten, alle Betraege in CHF-Rappen."""

    gross_income_monthly_rappen: int = 0
    recurring_expense_monthly_rappen: int = 0
    liquid_assets_rappen: int = 0
    gross_assets_rappen: int = 0
    direct_property_rappen: int = 0
    mortgage_liabilities_rappen: int = 0
    other_liabilities_rappen: int = 0
    near_term_goal_need_rappen: int = 0
    position_count: int = 0
    # nur vom Berater erfasste (nicht aus Positionen abgeleitete) Cashflows
    income_cashflow_count: int = 0
    expense_cashflow_count: int = 0
    near_term_goal_labels: tuple[str, ...] = field(default_factory=tuple)
    # Zeitprofil der Ausgaben: ``recurring_expense_monthly_rappen`` ist die
    # hoechste monatliche Belastung im Vorausfenster; ``current_...`` die am
    # Stichtag. None = nicht aus der DB geladen (reine Regeltests).
    current_expense_monthly_rappen: int | None = None
    peak_expense_from: str | None = None
    outside_window_expense_count: int = 0
    # Einkommens-Zeitprofil: ``gross_income_monthly_rappen`` ist das TIEFSTE
    # monatliche Einkommen im Fenster, ``current_...`` das am Stichtag.
    current_income_monthly_rappen: int | None = None
    income_min_from: str | None = None
    # Ungunstigster Monat fuer die Sparquote (Einkommen und Belastung
    # desselben Monatssegments). None = Fallback auf die Aggregatwerte.
    savings_worst_income_monthly_rappen: int | None = None
    savings_worst_expense_monthly_rappen: int | None = None
    savings_worst_from: str | None = None
    # Restbefund A (PR #653): erfasste Ausgabenzeilen belegen nur mit einer
    # gueltigen FinancialCoverageAttestationV1 Vollstaendigkeit.
    # ``coverage_attestation_status`` ist der Status der Bestaetigung
    # (services/financial_coverage_attestation.py), nur fuer die Wortwahl.
    expense_coverage_attested: bool = False
    coverage_attestation_status: str | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _band_from_points(points: Any, mapping: tuple[int, ...]) -> int | None:
    """Antwortposition aus Punkten; None wenn die Punkte keiner Antwort entsprechen.

    Die API akzeptiert z.B. fuer Frage 6 jede Ganzzahl 0..12; nur die Werte
    der Antwortoptionen sind eindeutig einer Bandbreite zuzuordnen. Alles
    andere ist "nicht pruefbar", nie eine geratene Bandbreite.
    """
    if isinstance(points, bool) or not isinstance(points, int):
        return None
    try:
        return mapping.index(points)
    except ValueError:
        return None


def _chf(rappen: int | float) -> str:
    amount = int(round(float(rappen) / 100.0))
    sign = "-" if amount < 0 else ""
    return f"CHF {sign}{abs(amount):,}".replace(",", "'")


def _band_label_chf(band: tuple[int, int | None], suffix: str = "") -> str:
    low, high = band
    if high is None:
        return f"über {_chf(low * 100)}{suffix}"
    if low == 0:
        return f"bis {_chf(high * 100)}{suffix}"
    return f"{_chf(low * 100)} bis {_chf(high * 100)}{suffix}"


def _band_label_pct(band: tuple[int, int | None]) -> str:
    low, high = band
    if high is None:
        return f"über {low} %"
    if low == high:
        return f"{low} %"
    return f"{low} bis {high} %"


def declared_capacity_from_assessment(assessment: Any) -> DeclaredCapacity:
    """Fragebogen-Angaben aus einer RiskAssessment-Zeile (ORM oder Double)."""
    horizon_label = canonicalize_horizon_label(
        getattr(assessment, "investment_horizon_label", "") or ""
    )
    horizon_years = HORIZON_YEARS.get(horizon_label)
    cap_profile = str(getattr(assessment, "risk_capacity_profile", "") or "").strip()

    def _opt_int(name: str) -> int | None:
        value = getattr(assessment, name, None)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    return DeclaredCapacity(
        income_band=_band_from_points(getattr(assessment, "q_income_points", None), INCOME_POINTS),
        obligations_band=_band_from_points(
            getattr(assessment, "q_obligations_points", None), OBLIGATION_POINTS
        ),
        free_wealth_band=_band_from_points(getattr(assessment, "q_wealth_points", None), WEALTH_POINTS),
        savings_band=_band_from_points(getattr(assessment, "q_savings_points", None), SAVINGS_POINTS),
        capacity_band=CAPACITY_BAND.get(cap_profile),
        horizon_years=horizon_years,
        capacity_score_x10=_opt_int("risk_capacity_score_x10"),
        willingness_score_x10=_opt_int("risk_willingness_score_x10"),
        final_score_x10=_opt_int("final_score_x10"),
        is_overridden=bool(getattr(assessment, "is_overridden", 0) or 0),
        override_score_x10=_opt_int("override_score_x10"),
    )


# ---------------------------------------------------------------------------
# Kern: reine Regelpruefung (ohne DB)
# ---------------------------------------------------------------------------

def assess_plausibility(
    declared: DeclaredCapacity,
    recorded: RecordedFinancials,
) -> dict:
    """Vergleicht Fragebogen-Angaben mit erfassten Daten. Aendert nichts."""
    findings: list[dict] = []
    not_evaluable: list[dict] = []
    t = THRESHOLDS

    coverage: dict[str, str] = {}
    evaluated: set[str] = set()

    def skip(check: str, question: int | None, reason: str, cov: str = COVERAGE_MISSING) -> None:
        not_evaluable.append({"check": check, "question_number": question, "reason": reason})
        coverage[check] = cov

    income_coverage = (
        COVERAGE_RECORDED if recorded.income_cashflow_count > 0
        else COVERAGE_DERIVED_ONLY if recorded.gross_income_monthly_rappen > 0
        else COVERAGE_MISSING
    )
    expense_coverage = (
        (COVERAGE_RECORDED if recorded.expense_coverage_attested else COVERAGE_ROWS_UNATTESTED)
        if recorded.expense_cashflow_count > 0
        else COVERAGE_DERIVED_ONLY if recorded.recurring_expense_monthly_rappen > 0
        else COVERAGE_MISSING
    )
    expense_complete = expense_coverage == COVERAGE_RECORDED
    forward_months = int(t["obligation_forward_window_months"])

    # R1 -- Frage 3: regelmaessiges Bruttoeinkommen pro Monat (tiefster
    # Monat im Vorausfenster, siehe Modul-Docstring).
    income = int(recorded.gross_income_monthly_rappen)
    income_drops = (
        recorded.current_income_monthly_rappen is not None
        and recorded.income_min_from is not None
        and income < int(recorded.current_income_monthly_rappen)
    )
    if declared.income_band is None:
        skip(CHECK_INCOME, 3, "Antwort zu Frage 3 ist keiner Antwortoption zuzuordnen.",
             COVERAGE_ANSWER_UNMAPPED)
    elif declared.income_band == 0:
        coverage[CHECK_INCOME] = COVERAGE_NOT_APPLICABLE
    else:
        band = INCOME_BANDS_CHF_MONTH[declared.income_band]
        if recorded.income_cashflow_count <= 0 or (income <= 0 and not income_drops):
            skip(CHECK_INCOME, 3, "Keine laufenden Einnahmen als Cashflow erfasst.", income_coverage)
        else:
            coverage[CHECK_INCOME] = income_coverage
            evaluated.add(CHECK_INCOME)
            limit = band[0] * 100 * (1 - t["income_tolerance_ratio"])
            if income < limit:
                findings.append({
                    "check": CHECK_INCOME,
                    "question_number": 3,
                    "declared": _band_label_chf(band, " pro Monat"),
                    "recorded": f"{_chf(income)} pro Monat",
                    "message": (
                        f"Frage 3 (Einkommen): angegeben {_band_label_chf(band, ' pro Monat')}, "
                        + (
                            f"erfasste laufende Einnahmen heute "
                            f"{_chf(recorded.current_income_monthly_rappen)} pro Monat; ab "
                            f"{_month_label(recorded.income_min_from)} sinkt das erfasste "
                            f"Einkommen auf {_chf(income)} pro Monat."
                            if income_drops
                            else f"erfasste laufende Einnahmen {_chf(income)} pro Monat."
                        )
                    ),
                })

    # R2 -- Frage 5: finanzielle Verpflichtungen pro Monat (invers bewertet).
    expense = int(recorded.recurring_expense_monthly_rappen)
    if declared.obligations_band is None:
        skip(CHECK_OBLIGATIONS, 5, "Antwort zu Frage 5 ist keiner Antwortoption zuzuordnen.",
             COVERAGE_ANSWER_UNMAPPED)
    else:
        band = OBLIGATION_BANDS_CHF_MONTH[declared.obligations_band]
        if band[1] is None:
            coverage[CHECK_OBLIGATIONS] = COVERAGE_NOT_APPLICABLE
        else:
            limit = band[1] * 100 * (1 + t["obligation_tolerance_ratio"])
            # Einweg-Logik: die erfassten (auch nur abgeleiteten) Ausgaben sind
            # eine UNTERGRENZE der Verpflichtungen. Liegt schon sie ueber der
            # Bandgrenze, ist das ein Befund. Liegt sie darunter, belegt das
            # nur dann Konsistenz, wenn die Ausgaben als vollstaendig bestaetigt
            # sind (Zeilenpraesenz allein genuegt nicht).
            if expense > limit:
                coverage[CHECK_OBLIGATIONS] = expense_coverage
                evaluated.add(CHECK_OBLIGATIONS)
                findings.append({
                    "check": CHECK_OBLIGATIONS,
                    "question_number": 5,
                    "declared": _band_label_chf(band, " pro Monat"),
                    "recorded": f"{_chf(expense)} pro Monat",
                    "message": (
                        f"Frage 5 (Verpflichtungen): angegeben {_band_label_chf(band, ' pro Monat')}, "
                        + _expense_phrase(recorded, forward_months)
                        + f" {_chf(expense)} pro Monat."
                    ),
                })
            elif expense_coverage == COVERAGE_ROWS_UNATTESTED:
                skip(
                    CHECK_OBLIGATIONS, 5,
                    "Ausgaben erfasst, aber ihre Vollständigkeit ist nicht bestätigt"
                    + _attestation_suffix(recorded)
                    + "; die erfassten Ausgaben sind nur eine Untergrenze.",
                    expense_coverage,
                )
            elif not expense_complete:
                skip(
                    CHECK_OBLIGATIONS, 5,
                    "Keine Ausgaben als Cashflow erfasst"
                    + (" (nur aus Positionen abgeleitete Kosten)"
                       if expense_coverage == COVERAGE_DERIVED_ONLY else "")
                    + "; fehlende Ausgaben sind keine Nullausgaben.",
                    expense_coverage,
                )
            else:
                coverage[CHECK_OBLIGATIONS] = expense_coverage
                evaluated.add(CHECK_OBLIGATIONS)

    # R3 -- Frage 6: frei verfuegbares Vermoegen (Obergrenze aus den Daten).
    free_wealth_upper = (
        int(recorded.liquid_assets_rappen)
        - int(recorded.other_liabilities_rappen)
        - max(0, int(recorded.mortgage_liabilities_rappen) - int(recorded.direct_property_rappen))
        - int(recorded.near_term_goal_need_rappen)
    )
    if declared.free_wealth_band is None:
        skip(CHECK_FREE_WEALTH, 6, "Antwort zu Frage 6 ist keiner Antwortoption zuzuordnen.",
             COVERAGE_ANSWER_UNMAPPED)
    elif declared.free_wealth_band == 0:
        coverage[CHECK_FREE_WEALTH] = COVERAGE_NOT_APPLICABLE
    else:
        band = FREE_WEALTH_BANDS_CHF[declared.free_wealth_band]
        if recorded.position_count <= 0:
            skip(CHECK_FREE_WEALTH, 6, "Keine Vermögenspositionen erfasst.")
        else:
            coverage[CHECK_FREE_WEALTH] = COVERAGE_RECORDED
            evaluated.add(CHECK_FREE_WEALTH)
            limit = band[0] * 100 * (1 - t["free_wealth_tolerance_ratio"])
            if free_wealth_upper < limit:
                findings.append({
                    "check": CHECK_FREE_WEALTH,
                    "question_number": 6,
                    "declared": _band_label_chf(band),
                    "recorded": _chf(free_wealth_upper),
                    "message": (
                        f"Frage 6 (frei verfügbares Vermögen): angegeben {_band_label_chf(band)}, "
                        f"aus den erfassten Daten höchstens {_chf(free_wealth_upper)} "
                        "(liquide Positionen abzüglich Schulden und Ziele der nächsten "
                        f"{t['near_term_goal_years']} Jahre; Vorsorge und Immobilien nicht frei verfügbar)."
                    ),
                })

    # R4 -- Frage 7: Sparquote (Obergrenze: Brutto-Einnahmen minus Ausgaben).
    if declared.savings_band is None:
        skip(CHECK_SAVINGS, 7, "Antwort zu Frage 7 ist keiner Antwortoption zuzuordnen.",
             COVERAGE_ANSWER_UNMAPPED)
    elif declared.savings_band == 0:
        coverage[CHECK_SAVINGS] = COVERAGE_NOT_APPLICABLE
    else:
        band = SAVINGS_RATE_BANDS_PCT[declared.savings_band]
        sav_income = (
            int(recorded.savings_worst_income_monthly_rappen)
            if recorded.savings_worst_income_monthly_rappen is not None else income
        )
        sav_expense = (
            int(recorded.savings_worst_expense_monthly_rappen)
            if recorded.savings_worst_expense_monthly_rappen is not None else expense
        )
        if recorded.income_cashflow_count <= 0 or (sav_income <= 0 and not income_drops):
            skip(CHECK_SAVINGS, 7, "Keine laufenden Einnahmen als Cashflow erfasst.", income_coverage)
        else:
            # Obergrenze: Brutto-Einnahmen minus (Untergrenze der) Ausgaben,
            # im unguenstigsten Monatssegment des Vorausfensters.
            rate_pct = _savings_rate_pct(sav_income, sav_expense)
            limit_pct = max(0.0, band[0] - t["savings_rate_tolerance_pp"])
            if rate_pct >= limit_pct and not expense_complete:
                # Ohne (vollstaendig bestaetigte) Ausgaben waere die Sparquote
                # eine Scheingewissheit (bis 100 %). Nur ein bereits
                # widersprechender Wert zaehlt.
                skip(
                    CHECK_SAVINGS, 7,
                    (
                        "Ausgaben erfasst, aber ihre Vollständigkeit ist nicht bestätigt"
                        + _attestation_suffix(recorded)
                        + "; die Sparquote ist damit nur eine Obergrenze."
                    )
                    if expense_coverage == COVERAGE_ROWS_UNATTESTED
                    else (
                        "Keine Ausgaben als Cashflow erfasst; die Sparquote ist ohne "
                        "Ausgaben nicht belegbar."
                    ),
                    expense_coverage,
                )
            else:
                coverage[CHECK_SAVINGS] = (
                    COVERAGE_RECORDED
                    if income_coverage == COVERAGE_RECORDED and expense_complete
                    else COVERAGE_ROWS_UNATTESTED
                    if expense_coverage == COVERAGE_ROWS_UNATTESTED
                    else COVERAGE_DERIVED_ONLY
                )
                evaluated.add(CHECK_SAVINGS)
            if rate_pct < limit_pct:
                findings.append({
                    "check": CHECK_SAVINGS,
                    "question_number": 7,
                    "declared": _band_label_pct(band),
                    "recorded": f"{rate_pct:.0f} %",
                    "message": (
                        f"Frage 7 (Sparquote): angegeben {_band_label_pct(band)}, "
                        f"aus den erfassten laufenden Cashflows höchstens {rate_pct:.0f} % "
                        f"(Einnahmen {_chf(sav_income)}, Ausgaben {_chf(sav_expense)} pro Monat"
                        + _savings_suffix(recorded)
                        + ")."
                    ),
                })

    structural = (
        (declared.capacity_band is not None
         and declared.capacity_band >= t["structural_min_capacity_band"])
        or (declared.horizon_years is not None
            and declared.horizon_years >= t["structural_min_horizon_years"])
    )
    capacity_label = _capacity_label(declared)

    # R5 -- Verschuldungsgrad.
    liabilities = int(recorded.mortgage_liabilities_rappen) + int(recorded.other_liabilities_rappen)
    gross_assets = int(recorded.gross_assets_rappen)
    if structural and recorded.position_count > 0:
        evaluated.add(CHECK_LEVERAGE)
    if liabilities > 0 and structural:
        ratio = (liabilities / gross_assets) if gross_assets > 0 else float("inf")
        if ratio > t["leverage_ratio_max"]:
            ratio_text = "über 100 %" if ratio == float("inf") else f"{ratio * 100:.0f} %"
            findings.append({
                "check": CHECK_LEVERAGE,
                "question_number": None,
                "declared": capacity_label,
                "recorded": ratio_text,
                "message": (
                    f"Verschuldung: Verbindlichkeiten {_chf(liabilities)} entsprechen "
                    f"{ratio_text} des erfassten Brutto-Vermögens ({_chf(gross_assets)}); "
                    f"der Fragebogen weist {capacity_label} aus."
                ),
            })

    # R6 -- Nahziele im Verhaeltnis zum liquiden Vermoegen.
    need = int(recorded.near_term_goal_need_rappen)
    liquid = int(recorded.liquid_assets_rappen)
    if need > 0 and structural:
        evaluated.add(CHECK_NEAR_TERM_GOALS)
        share = (need / liquid) if liquid > 0 else float("inf")
        if share >= t["near_term_goal_share_max"]:
            share_text = "über 100 %" if share == float("inf") else f"{share * 100:.0f} %"
            labels = ", ".join(f"«{label}»" for label in recorded.near_term_goal_labels[:3])
            findings.append({
                "check": CHECK_NEAR_TERM_GOALS,
                "question_number": 8,
                "declared": capacity_label,
                "recorded": share_text,
                "message": (
                    f"Nahziele: in den nächsten {t['near_term_goal_years']} Jahren werden "
                    f"{_chf(need)} benötigt ({share_text} des liquiden Vermögens"
                    + (f"; {labels}" if labels else "")
                    + f"); der Fragebogen weist {capacity_label} aus."
                ),
            })

    if findings:
        status = STATUS_INCONSISTENT
    elif not_evaluable and (not evaluated or _nothing_evaluable(not_evaluable)):
        status = STATUS_NOT_EVALUABLE
    elif not_evaluable:
        status = STATUS_PARTIAL
    else:
        status = STATUS_CONSISTENT
    result = {
        "version": PLAUSIBILITY_RULES_VERSION,
        "status": status,
        "reason_code": REASON_CODE if findings else None,
        "findings": findings,
        "not_evaluable": not_evaluable,
        "coverage": coverage,
        "capacity_binding": _capacity_binding(declared),
        "override_down": _override_down(declared),
        "thresholds": dict(THRESHOLDS),
        "data_basis": {
            "currency": "CHF",
            "gross_income_monthly_rappen": income,
            "recurring_expense_monthly_rappen": expense,
            "current_expense_monthly_rappen": recorded.current_expense_monthly_rappen,
            "current_income_monthly_rappen": recorded.current_income_monthly_rappen,
            "income_min_from": recorded.income_min_from,
            "savings_worst_income_monthly_rappen": recorded.savings_worst_income_monthly_rappen,
            "savings_worst_expense_monthly_rappen": recorded.savings_worst_expense_monthly_rappen,
            "savings_worst_from": recorded.savings_worst_from,
            "peak_expense_from": recorded.peak_expense_from,
            "obligation_forward_window_months": forward_months,
            "outside_window_expense_count": int(recorded.outside_window_expense_count),
            "income_cashflow_count": int(recorded.income_cashflow_count),
            "expense_cashflow_count": int(recorded.expense_cashflow_count),
            "expense_coverage_attested": bool(recorded.expense_coverage_attested),
            "liquid_assets_rappen": liquid,
            "gross_assets_rappen": gross_assets,
            "liabilities_rappen": liabilities,
            "free_wealth_upper_bound_rappen": free_wealth_upper,
            "near_term_goal_need_rappen": need,
        },
    }
    _finalize(result, recorded.coverage_attestation_status)
    return result


def _attestation_suffix(recorded: RecordedFinancials) -> str:
    from services.financial_coverage_attestation import STATUS_MISSING, STATUS_REASONS

    status = recorded.coverage_attestation_status
    if not status or status == STATUS_MISSING or status not in STATUS_REASONS:
        return ""
    return " (" + STATUS_REASONS[status].rstrip(".") + ")"


def _resolution_actions(result: dict, attestation_status: str | None) -> list[str]:
    """Konkrete naechste Schritte fuer jede offene Pruefung (dedupliziert)."""
    from services.financial_coverage_attestation import STATUS_MISSING

    coverage = result.get("coverage") or {}
    actions: list[str] = []

    def add(text: str) -> None:
        if text not in actions:
            actions.append(text)

    for row in result.get("not_evaluable") or []:
        check = row.get("check")
        cov = coverage.get(check)
        if check == "ALL":
            add(str(row.get("reason") or "Datengrundlage prüfen").rstrip(".")
                + ": Risikoprofil und erfasste Finanzdaten prüfen und die Prüfung wiederholen.")
        elif cov == COVERAGE_ANSWER_UNMAPPED:
            add(f"Antwort zu Frage {row.get('question_number')} im Fragebogen eindeutig erfassen.")
        elif check in (CHECK_OBLIGATIONS, CHECK_SAVINGS) and cov == COVERAGE_ROWS_UNATTESTED:
            if attestation_status and attestation_status != STATUS_MISSING:
                add("Ausgaben und Verpflichtungen prüfen und die Vollständigkeit erneut bestätigen "
                    "(bisherige Bestätigung nicht mehr gültig).")
            else:
                add("Ausgaben und Verpflichtungen auf Vollständigkeit prüfen und die "
                    "Vollständigkeit der Finanzdaten bestätigen.")
        elif check in (CHECK_OBLIGATIONS, CHECK_SAVINGS) and cov in (
            COVERAGE_MISSING, COVERAGE_DERIVED_ONLY,
        ) and not (check == CHECK_SAVINGS and str(row.get("reason", "")).startswith("Keine laufenden Einnahmen")):
            add("Ausgaben vollständig als Cashflow erfassen und die Vollständigkeit bestätigen.")
        elif check in (CHECK_INCOME, CHECK_SAVINGS):
            add("Laufende Einnahmen als Cashflow erfassen.")
        elif check == CHECK_FREE_WEALTH:
            add("Vermögenspositionen erfassen.")
        else:
            add(str(row.get("reason") or "Datengrundlage ergänzen."))
    return actions


def _evaluation_hash(result: dict) -> str:
    import hashlib

    bound = {
        key: result.get(key)
        for key in (
            "version", "status", "reason_code", "findings", "not_evaluable",
            "coverage", "capacity_binding", "override_down", "thresholds",
            "data_basis", "coverage_attestation", "risk_assessment_id",
        )
    }
    canonical = json.dumps(bound, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finalize(result: dict, attestation_status: str | None = None) -> dict:
    """Leitet Verifikationscode, Aufloesungsauftraege, Text und Hash ab."""
    from services.financial_coverage_attestation import STATUS_VALID

    open_status = result.get("status") in (STATUS_PARTIAL, STATUS_NOT_EVALUABLE)
    result["verification_code"] = VERIFICATION_CODE if open_status else None
    result["resolution_actions"] = _resolution_actions(result, attestation_status)
    coverage = result.get("coverage") or {}
    result["coverage_attestation_required"] = bool(
        attestation_status != STATUS_VALID
        and any(
            coverage.get(check) in (COVERAGE_ROWS_UNATTESTED, COVERAGE_MISSING, COVERAGE_DERIVED_ONLY)
            for check in (CHECK_OBLIGATIONS, CHECK_SAVINGS)
        )
    )
    result["advisor_text"] = advisor_summary_text(result)
    result["evaluation_hash"] = _evaluation_hash(result)
    return result


def _peak_is_future(recorded: RecordedFinancials) -> bool:
    current = recorded.current_expense_monthly_rappen
    return (
        current is not None
        and recorded.peak_expense_from is not None
        and int(recorded.recurring_expense_monthly_rappen) > int(current)
    )


def _month_label(iso: str | None) -> str:
    parsed = _parse_iso_date(iso)
    return f"{parsed.month:02d}.{parsed.year}" if parsed else ""


def _expense_phrase(recorded: RecordedFinancials, forward_months: int) -> str:
    if _peak_is_future(recorded):
        return (
            "erfasste laufende und innerhalb von "
            f"{forward_months} Monaten beginnende Ausgaben inkl. Hypothekarzins und "
            f"Amortisation (höchste Monatsbelastung ab {_month_label(recorded.peak_expense_from)})"
        )
    return "erfasste laufende Ausgaben inkl. Hypothekarzins und Amortisation"


def _savings_rate_pct(income: int, expense: int) -> float:
    if income > 0:
        return (income - expense) / income * 100.0
    # Kein Einkommen im Monat: keine Sparquote moeglich; mit Ausgaben negativ.
    return -100.0 if expense > 0 else 0.0


def _savings_suffix(recorded: RecordedFinancials) -> str:
    worst = recorded.savings_worst_from
    current_income = recorded.current_income_monthly_rappen
    current_expense = recorded.current_expense_monthly_rappen
    if (
        worst is None
        or current_income is None
        or current_expense is None
        or (
            recorded.savings_worst_income_monthly_rappen == current_income
            and recorded.savings_worst_expense_monthly_rappen == current_expense
        )
    ):
        return ""
    return f", ungünstigster Monat ab {_month_label(worst)}"


def _nothing_evaluable(not_evaluable: list[dict]) -> bool:
    checks = {row["check"] for row in not_evaluable}
    return {CHECK_INCOME, CHECK_FREE_WEALTH, CHECK_SAVINGS} <= checks


def _capacity_label(declared: DeclaredCapacity) -> str:
    for name, band in CAPACITY_BAND.items():
        if band == declared.capacity_band:
            return f"die Risikofähigkeit «{name}»"
    return "eine nicht dokumentierte Risikofähigkeit"


def _capacity_binding(declared: DeclaredCapacity) -> bool | None:
    if declared.capacity_score_x10 is None or declared.willingness_score_x10 is None:
        return None
    return declared.capacity_score_x10 <= declared.willingness_score_x10


def _override_down(declared: DeclaredCapacity) -> bool:
    return bool(
        declared.is_overridden
        and declared.override_score_x10 is not None
        and declared.final_score_x10 is not None
        and declared.override_score_x10 < declared.final_score_x10
    )


def _open_topics(result: dict) -> str:
    labels: list[str] = []
    for row in result.get("not_evaluable") or []:
        check = str(row.get("check"))
        if check == "ALL":
            continue
        label = CHECK_SHORT_LABELS.get(check, check)
        if label not in labels:
            labels.append(label)
    return ", ".join(labels)


def not_verified_text(result: dict) -> str:
    """Berater-Satz fuer partial/not_evaluable: noch nicht verifiziert + Auftrag."""
    if result.get("status") not in (STATUS_PARTIAL, STATUS_NOT_EVALUABLE):
        return ""
    topics = _open_topics(result)
    actions = result.get("resolution_actions") or []
    text = (
        f"Plausibilitätsprüfung Risikofähigkeit ({VERIFICATION_CODE}): "
        "Die Angaben zur Risikofähigkeit sind noch nicht verifiziert"
        + (f" – nicht prüfbar: {topics}." if topics else ".")
    )
    if actions:
        text += " Offen: " + " ".join(actions)
    text += " Das Risikoprofil wurde nicht automatisch geändert."
    return text


def advisor_summary_text(result: dict) -> str:
    """Neutraler Berater-Satz (UI, Strategie-Reasoning)."""
    findings = result.get("findings") or []
    if not findings:
        return not_verified_text(result)
    count = len(findings)
    topics = "; ".join(
        CHECK_SHORT_LABELS.get(str(f.get("check")), str(f.get("check"))) for f in findings
    )
    text = (
        f"Plausibilitätsprüfung Risikofähigkeit ({REASON_CODE}): "
        f"{count} Fragebogen-Angabe{'n' if count != 1 else ''} "
        f"{'weichen' if count != 1 else 'weicht'} von den erfassten Finanzdaten ab "
        f"({topics}). Das Risikoprofil wurde nicht automatisch geändert."
    )
    if result.get("override_down"):
        text += " Ein Override nach unten ist dokumentiert."
    else:
        text += (
            " Bitte den Fragebogen korrigieren oder das Profil per Override "
            "nach unten dokumentieren."
        )
    if result.get("capacity_binding") is False:
        text += (
            " Hinweis: derzeit ist die Risikobereitschaft bindend; der "
            "Widerspruch verändert das berechnete Profil nicht."
        )
    return text


def strategy_reasoning_lines(result: dict | None) -> list[str]:
    """Reasoning-Zeilen fuer die Strategie (leer nur bei ``consistent``).

    ``partial``/``not_evaluable`` erscheinen als "noch nicht verifiziert" mit
    Aufloesungsauftrag (Restbefund B, PR #653) -- nie still.
    """
    if not result:
        return []
    if result.get("status") in (STATUS_PARTIAL, STATUS_NOT_EVALUABLE):
        line = not_verified_text(result)
        return [line] if line else []
    if result.get("status") != STATUS_INCONSISTENT:
        return []
    lines = [result.get("advisor_text") or advisor_summary_text(result)]
    lines.extend(str(f.get("message") or "") for f in result.get("findings") or [])
    return [line for line in lines if line]


def attach_to_strategy_payload(payload: dict, result: dict | None) -> dict:
    """Haengt das Pruefergebnis an eine Strategie-Antwort (Reasoning + Feld)."""
    payload["risk_capacity_plausibility"] = result
    lines = strategy_reasoning_lines(result)
    if lines:
        reasoning = [
            line for line in list(payload.get("reasoning") or []) if line not in lines
        ]
        # Zusammenfassung zuoberst (UI zeigt nur die ersten Reasoning-Punkte),
        # Einzelbefunde am Ende.
        payload["reasoning"] = [lines[0]] + reasoning + lines[1:]
    return payload


# PDF Risikoprofil (Berater-Teil): bewusst ein einziger neutraler Satz ohne
# Betraege und ohne Aussage ueber die Verlusttragfaehigkeit des Kunden.
PDF_ADVISOR_NOTE = (
    "Plausibilitätsprüfung (Beraterhinweis): Einzelne Angaben zur "
    "Risikofähigkeit weichen von den in der Beratung erfassten Finanzdaten ab. "
    "Das Risikoprofil wurde dadurch nicht automatisch verändert."
)


def pdf_advisor_note(result: dict | None) -> str:
    """Berater-Teil des Risikoprofil-PDF (ohne Betraege).

    inconsistent -> fester neutraler Satz; partial/not_evaluable -> "noch nicht
    verifiziert" mit offenen Pruefungen und naechstem Schritt; consistent -> "".
    """
    if not result:
        return ""
    status = result.get("status")
    if status == STATUS_INCONSISTENT:
        return PDF_ADVISOR_NOTE
    if status not in (STATUS_PARTIAL, STATUS_NOT_EVALUABLE):
        return ""
    topics = _open_topics(result)
    actions = result.get("resolution_actions") or []
    note = (
        "Plausibilitätsprüfung (Beraterhinweis): Die Angaben zur Risikofähigkeit "
        "sind noch nicht vollständig gegen die erfassten Finanzdaten verifiziert"
        + (f" ({topics})." if topics else ".")
    )
    if actions:
        note += " Offener Schritt: " + " ".join(actions)
    note += " Das Risikoprofil wurde dadurch nicht automatisch verändert."
    return note


# ---------------------------------------------------------------------------
# Datenbasis aus der DB
# ---------------------------------------------------------------------------

def _parse_iso_date(value: Any) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _add_years(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year + years)
    except ValueError:  # 29. Februar
        return anchor.replace(year=anchor.year + years, day=28)


def _months_between(start: date, end: date) -> int:
    if end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _fx_to_chf(amount_rappen: int, currency: Any, fx_source) -> int:
    amount = int(amount_rappen or 0)
    cur = str(currency or "CHF").upper().strip() or "CHF"
    if amount == 0 or cur == "CHF":
        return amount
    rate = float(fx_source.cross_rate(cur, "CHF"))
    if not rate > 0:
        raise ValueError(f"Ungueltige FX-Rate {cur}->CHF.")
    return int(round(amount * rate))


def _included(row: Any) -> bool:
    # CASHFLOW-GOAL-INCLUDE-TOGGLE-001: is_included=0 fliesst in keine Berechnung ein.
    value = getattr(row, "is_included", 1)
    return value is None or int(value) == 1


def _add_months(anchor: date, months: int) -> date:
    total = anchor.month - 1 + months
    year, month = anchor.year + total // 12, total % 12 + 1
    return anchor.replace(year=year, month=month,
                          day=min(anchor.day, calendar.monthrange(year, month)[1]))


def _forward_segments(today: date, window_end: date) -> list[tuple[date, date]]:
    """Monatssegmente [today..Monatsende], [1. Folgemonat..], ... bis window_end."""
    segments: list[tuple[date, date]] = []
    start = today
    while start <= window_end:
        month_end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        segments.append((start, min(month_end, window_end)))
        start = _add_months(start.replace(day=1), 1)
    return segments


def _overlaps(cf: Any, seg_start: date, seg_end: date) -> bool:
    # valid_until ist INKLUSIV (Cashflow-Konvention).
    start = _parse_iso_date(getattr(cf, "valid_from", None))
    end = _parse_iso_date(getattr(cf, "valid_until", None))
    if start and start > seg_end:
        return False
    if end and end < seg_start:
        return False
    return True


def _active_today(cf: Any, today: date) -> bool:
    start = _parse_iso_date(getattr(cf, "valid_from", None))
    end = _parse_iso_date(getattr(cf, "valid_until", None))
    if start and start > today:
        return False
    if end and end < today:
        return False
    return True


def _goal_need_within_window(goal: Any, today: date, window_end: date) -> int:
    """Kapitalbedarf eines Ausgaben-Ziels im Fenster [heute, window_end] (Basiswaehrung)."""
    from services.cashflow_timeline import normalize_frequency

    goal_type = str(getattr(goal, "goal_type", "") or "").strip().lower()
    goal_type = goal_type.replace("ä", "ae").replace(" ", "_")
    amount = int(getattr(goal, "target_amount_rappen", 0) or 0)
    if amount <= 0:
        return 0
    start = _parse_iso_date(getattr(goal, "start_date", None))
    target = _parse_iso_date(getattr(goal, "target_date", None))
    horizon = getattr(goal, "horizon_years", None)
    if goal_type == "einmalige_ausgabe":
        due = target
        if due is None and isinstance(horizon, int) and not isinstance(horizon, bool):
            due = _add_years(start or today, horizon)
        if due is None:
            return 0
        # Ueberfaellige, noch aktive Ziele gelten als sofort faellig.
        return amount if due <= window_end else 0
    if goal_type in {"wiederkehrende_ausgabe", "pensionsausgabe"}:
        per_year = _FREQUENCY_PER_YEAR.get(normalize_frequency(getattr(goal, "frequency", None)))
        if not per_year:
            return 0
        stream_start = start
        if stream_start is None and isinstance(horizon, int) and not isinstance(horizon, bool):
            stream_start = _add_years(today, horizon)
        stream_start = max(stream_start or today, today)
        stream_end = target if (target and not int(getattr(goal, "is_ongoing", 0) or 0)) else None
        effective_end = min(stream_end or window_end, window_end)
        months = _months_between(stream_start, effective_end)
        return int(round(amount * per_year * months / 12.0))
    return 0


# RISK-CAPACITY-REPORT-001: ein Aufrufer mit bereits geladenen Zeilen (der
# Advisory-Report-Aggregator, Call-Cache U-18) kann sie hier fuer GENAU dieses
# Mandat hinterlegen, damit die Pruefung keine zusaetzlichen Cashflow-/Ziel-
# Queries ausloest. Erwartet wird eine Obermenge der aktiven, eingeschlossenen
# Zeilen; is_active/is_included/deleted_at werden unten identisch nachgefiltert.
PRELOADED_ROWS_KEY = "_risk_capacity_preloaded_rows"


def _preloaded_rows(db, mandate) -> dict | None:
    info = getattr(db, "info", None)
    entry = info.get(PRELOADED_ROWS_KEY) if isinstance(info, dict) else None
    if not isinstance(entry, dict):
        return None
    if (
        entry.get("mandate_id") != getattr(mandate, "id", None)
        or entry.get("client_id") != getattr(mandate, "client_id", None)
    ):
        return None
    return entry


def load_recorded_financials(db, mandate, *, today: date | None = None) -> RecordedFinancials:
    """Liest die erfassten Daten des Mandats (read-only) und rechnet in CHF.

    Wirft ValueError, wenn die Daten nicht eindeutig umrechenbar sind (z.B.
    fehlende FX-Rate) -- der Aufrufer weist das als "nicht pruefbar" aus.
    """
    from models.wealth import Cashflow, Goal, WealthPosition
    from services.currency.fx_rates import FXRateSource
    from services.wealth_cashflows import derive_wealth_cashflows
    from services.wealth_position_semantics import (
        canonical_position_type,
        is_direct_real_estate_position,
        is_liability_assignment,
        is_mortgage_position,
    )
    from services.cashflow_timeline import normalize_frequency, normalize_nature

    today = today or date.today()
    fx_source = FXRateSource.from_db_for_model(db)
    base_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF")

    positions = [
        pos for pos in db.query(WealthPosition).filter(
            WealthPosition.client_id == mandate.client_id,
            WealthPosition.deleted_at.is_(None),
        ).all()
        if int(getattr(pos, "is_active", 1) or 0) == 1
    ]
    liquid = gross = prop = mortgages = other_liab = 0
    for pos in positions:
        value = abs(_fx_to_chf(getattr(pos, "current_value_rappen", 0), pos.currency, fx_source))
        ptype = getattr(pos, "position_type", "")
        if is_mortgage_position(ptype):
            mortgages += value
        elif is_liability_assignment(getattr(pos, "assignment", "")):
            other_liab += value
        else:
            gross += value
            if is_direct_real_estate_position(ptype):
                prop += value
            elif canonical_position_type(ptype) != "Vorsorge":
                liquid += value

    preloaded = _preloaded_rows(db, mandate)
    cashflow_rows = (
        [cf for cf in preloaded["cashflows"] if getattr(cf, "deleted_at", None) is None]
        if preloaded is not None
        else db.query(Cashflow).filter(
            Cashflow.client_id == mandate.client_id,
            Cashflow.deleted_at.is_(None),
        ).all()
    )
    cashflows = [
        cf for cf in cashflow_rows
        if int(getattr(cf, "is_active", 1) or 0) == 1
        and _included(cf)
    ]
    cashflows = list(cashflows) + list(derive_wealth_cashflows(positions))
    window_end_obl = _add_months(today, int(THRESHOLDS["obligation_forward_window_months"]))
    segments = _forward_segments(today, window_end_obl)
    segment_expense = [0.0] * len(segments)
    segment_income = [0.0] * len(segments)
    income_monthly = 0.0
    income_count = expense_count = outside_window = 0
    for cf in cashflows:
        frequency = normalize_frequency(getattr(cf, "frequency", None))
        if normalize_nature(getattr(cf, "nature", None), frequency) == "einmalig":
            continue
        per_year = _FREQUENCY_PER_YEAR.get(frequency)
        if not per_year:
            continue
        cf_type = str(getattr(cf, "cashflow_type", "") or "")
        amount = int(getattr(cf, "amount_rappen", 0) or 0)
        # Aus Positionen abgeleitete Posten (Zins, Miete, Hypothekarzins)
        # zaehlen zum Betrag, belegen aber nicht, dass das Einkommen erfasst ist.
        derived = int(getattr(cf, "is_derived", 0) or 0) == 1
        if cf_type == "Income":
            # Einweg-Logik: nur am Stichtag aktives Einkommen; kuenftiges
            # Einkommen entlastet die Pruefung nicht.
            if not _active_today(cf, today):
                continue
            gross_amount = getattr(cf, "gross_amount_rappen", None)
            if isinstance(gross_amount, int) and not isinstance(gross_amount, bool):
                amount = max(amount, gross_amount)
            monthly_income = _fx_to_chf(amount, cf.currency, fx_source) * per_year / 12.0
            income_monthly += monthly_income
            income_count += 0 if derived else 1
            # Konservativ: ein Einkommen zaehlt in einem Monatssegment nur,
            # wenn es das ganze Segment abdeckt (valid_until inklusiv).
            end = _parse_iso_date(getattr(cf, "valid_until", None))
            for i, (_s0, s1) in enumerate(segments):
                if end is None or end >= s1:
                    segment_income[i] += monthly_income
        elif cf_type == "Expense":
            # Frage 5: aktuelle UND innerhalb des Vorausfensters beginnende
            # Verpflichtungen; Zeitprofil je Monatssegment.
            hits = [i for i, (s0, s1) in enumerate(segments) if _overlaps(cf, s0, s1)]
            if not hits:
                start = _parse_iso_date(getattr(cf, "valid_from", None))
                if start and start > window_end_obl and not derived:
                    outside_window += 1
                continue
            monthly = _fx_to_chf(amount, cf.currency, fx_source) * per_year / 12.0
            for i in hits:
                segment_expense[i] += monthly
            expense_count += 0 if derived else 1

    peak_index = (
        max(range(len(segment_expense)), key=lambda i: segment_expense[i]) if segments else None
    )
    expense_monthly = segment_expense[peak_index] if peak_index is not None else 0.0
    current_expense = segment_expense[0] if segments else 0.0
    income_min_index = (
        min(range(len(segment_income)), key=lambda i: segment_income[i]) if segments else None
    )
    income_min = segment_income[income_min_index] if income_min_index is not None else 0.0
    worst_index = (
        min(
            range(len(segments)),
            key=lambda i: _savings_rate_pct(
                int(round(segment_income[i])), int(round(segment_expense[i]))
            ),
        )
        if segments else None
    )

    window_end = _add_years(today, int(THRESHOLDS["near_term_goal_years"]))
    need = 0
    labels: list[str] = []
    goal_rows = (
        sorted(
            (g for g in preloaded["goals"] if getattr(g, "deleted_at", None) is None),
            key=lambda g: int(getattr(g, "rank", 0) or 0),
        )
        if preloaded is not None
        else db.query(Goal).filter(
            Goal.mandate_id == mandate.id,
            Goal.deleted_at.is_(None),
        ).order_by(Goal.rank.asc()).all()
    )
    for goal in goal_rows:
        if int(getattr(goal, "is_active", 1) or 0) != 1:
            continue
        if not _included(goal):
            continue
        goal_need = _goal_need_within_window(goal, today, window_end)
        if goal_need > 0:
            need += _fx_to_chf(goal_need, base_currency, fx_source)
            labels.append(str(getattr(goal, "label", "") or "Ziel"))

    return RecordedFinancials(
        gross_income_monthly_rappen=int(round(income_min)),
        recurring_expense_monthly_rappen=int(round(expense_monthly)),
        liquid_assets_rappen=liquid,
        gross_assets_rappen=gross,
        direct_property_rappen=prop,
        mortgage_liabilities_rappen=mortgages,
        other_liabilities_rappen=other_liab,
        near_term_goal_need_rappen=need,
        position_count=len(positions),
        income_cashflow_count=income_count,
        expense_cashflow_count=expense_count,
        near_term_goal_labels=tuple(labels),
        current_expense_monthly_rappen=int(round(current_expense)),
        peak_expense_from=segments[peak_index][0].isoformat() if peak_index is not None else None,
        outside_window_expense_count=outside_window,
        current_income_monthly_rappen=int(round(income_monthly)),
        income_min_from=(
            segments[income_min_index][0].isoformat() if income_min_index is not None else None
        ),
        savings_worst_income_monthly_rappen=(
            int(round(segment_income[worst_index])) if worst_index is not None else None
        ),
        savings_worst_expense_monthly_rappen=(
            int(round(segment_expense[worst_index])) if worst_index is not None else None
        ),
        savings_worst_from=segments[worst_index][0].isoformat() if worst_index is not None else None,
    )


def evaluate_mandate(
    db, mandate, assessment, *, today: date | None = None, capture: dict | None = None,
) -> dict:
    """Pruefung fuer ein Mandat. Fehler in der Datenbasis -> "nicht pruefbar".

    ``capture`` (optional, RiskCapacityPlausibilityEvaluationV1): bei
    vollstaendiger Auswertung werden die tatsaechlich verwendeten Eingaben
    (``declared``, ``recorded``, ``coverage_attestation``, ``as_of_date``)
    eingetragen, damit genau diese Bewertung als Evidenz persistiert werden
    kann (services/risk_capacity_evaluation_snapshot.py). Das Ergebnis
    selbst bleibt unveraendert.
    """
    if assessment is None:
        return _not_evaluable_result("Kein aktuelles Risikoprofil vorhanden.")
    from dataclasses import replace

    from services.financial_coverage_attestation import STATUS_VALID, resolve_attestation

    declared = declared_capacity_from_assessment(assessment)
    try:
        recorded = load_recorded_financials(db, mandate, today=today)
    except ValueError as exc:
        return _not_evaluable_result(f"Erfasste Daten nicht auswertbar: {exc}")
    attestation = resolve_attestation(db, mandate, today=today)
    recorded = replace(
        recorded,
        expense_coverage_attested=attestation["status"] == STATUS_VALID,
        coverage_attestation_status=attestation["status"],
    )
    result = assess_plausibility(declared, recorded)
    result["risk_assessment_id"] = getattr(assessment, "id", None)
    result["coverage_attestation"] = attestation
    _finalize(result, attestation["status"])
    if capture is not None:
        capture.update(
            declared=declared,
            recorded=recorded,
            coverage_attestation=attestation,
            as_of_date=(today or date.today()).isoformat(),
        )
    return result


def evaluate_mandate_safely(
    db, mandate, assessment, *, today: date | None = None, capture: dict | None = None,
) -> dict:
    """Wie evaluate_mandate, faengt aber jeden Fehler ab.

    Die Pruefung ist ein Hinweis-Layer: ein Programmfehler darf weder das
    Speichern des Risikoprofils noch die Strategie verhindern. Er wird
    geloggt und als "nicht pruefbar" sichtbar gemacht, nie als "konsistent".
    """
    try:
        return evaluate_mandate(db, mandate, assessment, today=today, capture=capture)
    except Exception as exc:  # noqa: BLE001 -- Hinweis-Layer, siehe Docstring
        logger.exception(
            "Risk-capacity plausibility failed for mandate %s",
            getattr(mandate, "id", "?"),
        )
        return _not_evaluable_result(f"Prüfung fehlgeschlagen: {type(exc).__name__}")


def _not_evaluable_result(reason: str) -> dict:
    return _finalize({
        "version": PLAUSIBILITY_RULES_VERSION,
        "status": STATUS_NOT_EVALUABLE,
        "reason_code": None,
        "findings": [],
        "not_evaluable": [{"check": "ALL", "question_number": None, "reason": reason}],
        "coverage": {},
        "capacity_binding": None,
        "override_down": False,
        "thresholds": dict(THRESHOLDS),
        "data_basis": {},
        "advisor_text": "",
    })


def audit_payload(result: dict) -> str:
    """Kompakter Audit-Wert ohne Betraege: Version, Status, Codes, Pruef-IDs,
    offene Pruefungen, Bestaetigungs-Referenz und Evaluation-Hash."""
    attestation = result.get("coverage_attestation") or {}
    return json.dumps(
        {
            "version": result.get("version"),
            "status": result.get("status"),
            "reason_code": result.get("reason_code"),
            "verification_code": result.get("verification_code"),
            "checks": [f.get("check") for f in result.get("findings") or []],
            "not_evaluable": [r.get("check") for r in result.get("not_evaluable") or []],
            "override_down": bool(result.get("override_down")),
            "coverage_attestation": {
                "status": attestation.get("status"),
                "attestation_id": attestation.get("attestation_id"),
                "attestation_hash": attestation.get("attestation_hash"),
            },
            "evaluation_hash": result.get("evaluation_hash"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def audit_plausibility_outcome(
    db,
    result: dict,
    *,
    user,
    table_name: str,
    record_id: str,
    mandate,
    ip_address: str | None = None,
) -> bool:
    """Schreibt einen Audit-Log-Eintrag fuer jedes NICHT konsistente Ergebnis.

    inconsistent, partial und not_evaluable werden append-only festgehalten
    (Restbefund B, PR #653): der spaetere Audit sieht, dass eine Empfehlung
    mit unverifizierter Risikofaehigkeit erstellt wurde.
    """
    if not result or result.get("status") not in (
        STATUS_INCONSISTENT, STATUS_PARTIAL, STATUS_NOT_EVALUABLE,
    ):
        return False
    from services.audit import log

    log(
        db,
        user_id=user.id,
        user_name=user.full_name,
        table_name=table_name,
        record_id=record_id,
        action="CREATE",
        field_name="risk_capacity_plausibility",
        new_value=audit_payload(result),
        mandate_id=getattr(mandate, "id", None),
        client_id=getattr(mandate, "client_id", None),
        ip_address=ip_address,
    )
    return True


# Historischer Name (routers/profiling.py); auditiert seit PR #653 jedes nicht
# konsistente Ergebnis, nicht nur Widersprueche.
audit_if_inconsistent = audit_plausibility_outcome


__all__ = [
    "REASON_CODE",
    "VERIFICATION_CODE",
    "COVERAGE_ROWS_UNATTESTED",
    "PLAUSIBILITY_RULES_VERSION",
    "THRESHOLDS",
    "STATUS_PARTIAL",
    "DeclaredCapacity",
    "RecordedFinancials",
    "assess_plausibility",
    "declared_capacity_from_assessment",
    "load_recorded_financials",
    "evaluate_mandate",
    "evaluate_mandate_safely",
    "strategy_reasoning_lines",
    "attach_to_strategy_payload",
    "pdf_advisor_note",
    "audit_if_inconsistent",
    "audit_plausibility_outcome",
    "not_verified_text",
]
