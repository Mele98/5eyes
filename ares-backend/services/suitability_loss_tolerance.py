"""SUITABILITY-LOSS-TOLERANCE-001: Verlusttoleranz-Pruefung (Vorbereitung, INAKTIV).

Gehoert zu Audit 2026-11, Entscheid AA-8, Luecke L16, Paket P11, Welle 0.

Frage 10 des Risikoprofils fragt, welche Wertschwankung der Kunde zu tragen
bereit ist (z. B. "Wertschwankung ca. -6 % bis +10 %"). Ares prueft diese
Antwort bisher nicht gegen die Strategie. Die Risky Fraction bleibt der harte
Plausibilitaets-Cap. Zusaetzlich gilt kuenftig:

    P10(1-Jahres-Rendite der SAA)  >=  Untergrenze der gewaehlten Antwort

Ist die Bedingung verletzt, liegt ein Eignungskonflikt vor. Die Freigabe
bleibt dann gesperrt, bis eine Begruendung erfasst ist, wie beim
Hausband-Override. Diese Sperre wird erst bei der Aktivierung verdrahtet.

Inhalt dieses Moduls, ausschliesslich reine Funktionen:

* ``LOSS_TOLERANCE_BANDS`` bildet die Punkte von Frage 10 auf die Unter- und
  Obergrenze der Wertschwankung ab. Die Werte werden aus den bestehenden
  Optionstexten (``risk_questionnaire_integrity.STANDARD_OPTIONS[10]``)
  gelesen, nicht abgetippt. Der Fragebogen selbst (Paragraf 2, Vorlage) wird
  nicht veraendert. Laesst sich eine Option nicht lesen, entsteht ein
  markierter Platzhalter ohne Untergrenze. Es wird nichts erfunden.
* ``one_year_p10_return_bps`` berechnet das 10-%-Quantil der einfachen
  1-Jahres-Rendite. Verwendet wird dieselbe Log-/Cornish-Fisher-Abbildung wie
  in der Monte-Carlo-Simulation
  (``optimizer.distributions.standard_normal_to_log_return``).
* ``evaluate_loss_tolerance`` liefert ein ``LossToleranceCheck`` (Status,
  Reason-Code, Konfliktobjekt).

NICHT VERDRAHTET. ``LOSS_TOLERANCE_CHECK_ENABLED`` ist ``False``, und
``evaluate_loss_tolerance_if_enabled`` gibt in diesem Zustand ``None`` zurueck.
Aktiviert wird P11 erst nach P2b (Netto-Simulation): AA-8 verlangt das Quantil
netto Kosten. Bis dahin waere jede Allokations- oder Kennzahlenrechnung brutto,
und die Pruefung fiele zu milde aus.

Offene Platzhalter (``OPEN_PLACEHOLDERS``) werden mit jedem Ergebnis
ausgewiesen:

* Der Ares-Fragetext zu Frage 10 nennt weder ein Konfidenzniveau noch einen
  Zeitraum. Die Lesart "rund 80 % der Faelle, je 10 % darunter und darueber"
  (also P10) und der Horizont von 1 Jahr stammen aus Entscheid AA-8, der sich
  auf die Vorlage stuetzt, nicht aus dem Ares-Text. Die Bestaetigung durch
  Compliance steht aus.
* Netto-Rendite: erst mit P2b verfuegbar.
* Frage 11 (Reaktion auf -20 % Verlust) ist eine Verhaltensfrage ohne
  Toleranzband. Sie wird bewusst nicht auf eine Untergrenze abgebildet.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from statistics import NormalDist
from typing import Mapping

from services.optimizer.distributions import (
    cornish_fisher_is_monotonic,
    standard_normal_to_log_return,
)
from services.risk_questionnaire_integrity import (
    POINT_FIELD_BY_QUESTION,
    STANDARD_OPTIONS,
    STANDARD_POINTS,
)

CHECK_VERSION = "loss_tolerance_p10_1y_v0_inactive"

# Flag: standardmaessig AUS. Aktivierung erst nach P2b (Netto-Simulation),
# per eigenem PR mit Verdrahtung (Kennzahlen + Finalize-Gate).
LOSS_TOLERANCE_CHECK_ENABLED = False

QUESTION_NUMBER = 10
POINT_FIELD = POINT_FIELD_BY_QUESTION[QUESTION_NUMBER]  # q_risk_preference_points
QUANTILE = 0.10
HORIZON_YEARS = 1
INTERPRETATION_SOURCE = "AA-8"

RETURN_BASIS_GROSS = "gross"
RETURN_BASIS_NET = "net_of_costs"

# Pruef-Codes (``check_code``) sind bewusst KEINE Reason-Codes im Sinn von
# ``core/reason_codes.py``: das inaktive Modul erzeugt nichts fuer API, PDF
# oder Audit. Mit der Aktivierung (P11, nach P2b) werden sie als Reason-Codes
# in den Katalog aufgenommen (Blatt-Pin-Nachfuehrung im Aktivierungs-PR) und
# das Feld in ``reason_code`` umbenannt.
STATUS_OK = "ok"
STATUS_CONFLICT = "conflict"
STATUS_NOT_EVALUABLE = "not_evaluable"

REASON_CONFLICT = "LOSS_TOLERANCE_CONFLICT"
REASON_ANSWER_MISSING = "LOSS_TOLERANCE_ANSWER_MISSING"
REASON_ANSWER_UNMAPPED = "LOSS_TOLERANCE_ANSWER_UNMAPPED"
REASON_DISTRIBUTION_MISSING = "LOSS_TOLERANCE_DISTRIBUTION_MISSING"
REASON_CF_NOT_MONOTONIC = "LOSS_TOLERANCE_CORNISH_FISHER_NOT_MONOTONIC"

PLACEHOLDER_UNMAPPED = "PLACEHOLDER_UNMAPPED"
PLACEHOLDER_Q10_COVERAGE = "Q10_INTERVAL_COVERAGE_FROM_AA8_NOT_IN_QUESTION_TEXT"
PLACEHOLDER_Q10_HORIZON = "Q10_HORIZON_FROM_AA8_NOT_IN_QUESTION_TEXT"
PLACEHOLDER_NET_BASIS = "RETURN_BASIS_NET_PENDING_P2B"
PLACEHOLDER_Q11 = "Q11_BEHAVIOUR_NOT_MAPPED"

OPEN_PLACEHOLDERS: dict[str, str] = {
    PLACEHOLDER_Q10_COVERAGE: (
        "Fragetext 10 nennt kein Konfidenzniveau; 80-%-Intervall (P10 als "
        "Untergrenze) aus Entscheid AA-8 (Vorlage), Compliance-Bestaetigung offen."
    ),
    PLACEHOLDER_Q10_HORIZON: (
        "Fragetext 10 nennt keinen Zeitraum; 1 Jahr aus Entscheid AA-8, "
        "Compliance-Bestaetigung offen."
    ),
    PLACEHOLDER_NET_BASIS: (
        "AA-8 verlangt die Rendite netto Kosten; verfuegbar erst mit P2b "
        "(Netto-Simulation). Bis dahin nicht aktivierbar."
    ),
    PLACEHOLDER_Q11: (
        "Frage 11 (Reaktion auf -20 % Verlust) ist eine Verhaltensfrage ohne "
        "Toleranzband und wird nicht auf eine Untergrenze abgebildet."
    ),
}

_Z_QUANTILE = NormalDist().inv_cdf(QUANTILE)
_FLUCTUATION = re.compile(
    r"Wertschwankung\s+ca\.\s*[−–\-]\s*(?P<low>\d+(?:[.,]\d+)?)\s*%\s*bis\s*"
    r"\+\s*(?P<high>\d+(?:[.,]\d+)?)\s*%"
)


@dataclass(frozen=True)
class LossToleranceBand:
    """Antwort auf Frage 10 -> Schwankungsband (bps, einfache Rendite)."""

    points: int
    option_index: int
    option_text: str
    floor_bps: int | None
    upper_bps: int | None
    placeholder: str | None = None

    @property
    def is_mapped(self) -> bool:
        return self.floor_bps is not None and self.placeholder is None


def _percent_to_bps(text: str) -> int:
    return int(round(float(text.replace(",", ".")) * 100.0))


def parse_fluctuation_band(option_text: str) -> tuple[int, int] | None:
    """``(-low_bps, +high_bps)`` aus "Wertschwankung ca. -X % bis +Y %", sonst None."""
    match = _FLUCTUATION.search(str(option_text or ""))
    if match is None:
        return None
    return -_percent_to_bps(match.group("low")), _percent_to_bps(match.group("high"))


def build_loss_tolerance_bands(
    options: tuple[str, ...] = STANDARD_OPTIONS[QUESTION_NUMBER],
    points: tuple[int, ...] = STANDARD_POINTS[QUESTION_NUMBER],
) -> dict[int, LossToleranceBand]:
    """Punkte -> Band aus den Optionstexten. Nicht lesbar = Platzhalter."""
    if len(options) != len(points):
        raise ValueError("Frage 10: Optionen und Punkte passen nicht zusammen.")
    bands: dict[int, LossToleranceBand] = {}
    for index, (text, pts) in enumerate(zip(options, points)):
        parsed = parse_fluctuation_band(text)
        if parsed is None:
            bands[int(pts)] = LossToleranceBand(
                points=int(pts), option_index=index, option_text=text,
                floor_bps=None, upper_bps=None, placeholder=PLACEHOLDER_UNMAPPED,
            )
            continue
        floor_bps, upper_bps = parsed
        bands[int(pts)] = LossToleranceBand(
            points=int(pts), option_index=index, option_text=text,
            floor_bps=floor_bps, upper_bps=upper_bps,
        )
    return bands


LOSS_TOLERANCE_BANDS: dict[int, LossToleranceBand] = build_loss_tolerance_bands()


def one_year_p10_return_bps(
    expected_return_bps: float,
    volatility_bps: float,
    *,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> float:
    """10-%-Quantil der einfachen 1-Jahres-Rendite in bps.

    Arithmetische Momente -> Log-Rendite wie im MC
    (``standard_normal_to_log_return``), mit Cornish-Fisher fuer Schiefe und
    Exzess-Kurtosis. Die Transformation ist monoton (geprueft), daher ist
    ``R(z_0.10) - 1`` das 10-%-Quantil. Wirft ``ValueError``, wenn sie es
    nicht ist.
    """
    if not cornish_fisher_is_monotonic(float(skew), float(excess_kurtosis)):
        raise ValueError(REASON_CF_NOT_MONOTONIC)
    gross = standard_normal_to_log_return(
        _Z_QUANTILE,
        float(expected_return_bps),
        float(volatility_bps),
        skew=float(skew),
        excess_kurt=float(excess_kurtosis),
    )
    return (float(gross) - 1.0) * 10000.0


@dataclass(frozen=True)
class LossToleranceCheck:
    status: str
    check_code: str | None
    message: str
    answer_points: int | None = None
    answer_text: str | None = None
    floor_bps: int | None = None
    upper_bps: int | None = None
    p10_return_bps: float | None = None
    shortfall_bps: float | None = None
    requires_justification: bool = False
    quantile: float = QUANTILE
    horizon_years: int = HORIZON_YEARS
    return_basis: str = RETURN_BASIS_GROSS
    interpretation_source: str = INTERPRETATION_SOURCE
    check_version: str = CHECK_VERSION
    placeholders: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_conflict(self) -> bool:
        return self.status == STATUS_CONFLICT

    def to_dict(self) -> dict:
        data = asdict(self)
        data["placeholders"] = list(self.placeholders)
        return data


def _placeholders(return_basis: str, band: LossToleranceBand | None) -> tuple[str, ...]:
    items = [PLACEHOLDER_Q10_COVERAGE, PLACEHOLDER_Q10_HORIZON]
    if return_basis != RETURN_BASIS_NET:
        items.append(PLACEHOLDER_NET_BASIS)
    if band is not None and band.placeholder:
        items.append(band.placeholder)
    return tuple(items)


def answer_points_from_assessment(assessment) -> int | None:
    """Punkte von Frage 10 aus einem Risikoprofil (Objekt oder Mapping), nur lesen."""
    if assessment is None:
        return None
    if isinstance(assessment, Mapping):
        value = assessment.get(POINT_FIELD)
    else:
        value = getattr(assessment, POINT_FIELD, None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def evaluate_loss_tolerance(
    answer_points: int | None,
    *,
    p10_return_bps: float | None = None,
    expected_return_bps: float | None = None,
    volatility_bps: float | None = None,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    return_basis: str = RETURN_BASIS_GROSS,
) -> LossToleranceCheck:
    """Prueft P10 (1 Jahr) der SAA gegen die Untergrenze der Antwort zu Frage 10.

    Entweder ``p10_return_bps`` direkt (z. B. aus MC-Pfaden) oder
    ``expected_return_bps`` + ``volatility_bps`` (+ Schiefe/Kurtosis). Fail-
    closed: fehlende/unbekannte Antwort oder Verteilung -> ``not_evaluable``,
    nie ``ok``. Konflikt genau dann, wenn ``P10 < Untergrenze``.
    """
    if isinstance(answer_points, bool) or not isinstance(answer_points, int):
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_ANSWER_MISSING,
            message="Verlusttoleranz nicht pruefbar: Antwort zu Frage 10 fehlt.",
            return_basis=return_basis,
            placeholders=_placeholders(return_basis, None),
        )
    band = LOSS_TOLERANCE_BANDS.get(int(answer_points))
    if band is None or not band.is_mapped:
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_ANSWER_UNMAPPED,
            message=(
                "Verlusttoleranz nicht pruefbar: fuer die Antwort zu Frage 10 "
                "ist keine Wertschwankungs-Untergrenze hinterlegt (Platzhalter)."
            ),
            answer_points=int(answer_points),
            answer_text=band.option_text if band else None,
            return_basis=return_basis,
            placeholders=_placeholders(return_basis, band)
            + (() if band else (PLACEHOLDER_UNMAPPED,)),
        )
    common = dict(
        answer_points=band.points,
        answer_text=band.option_text,
        floor_bps=band.floor_bps,
        upper_bps=band.upper_bps,
        return_basis=return_basis,
        placeholders=_placeholders(return_basis, band),
    )
    if p10_return_bps is None:
        if expected_return_bps is None or volatility_bps is None:
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_DISTRIBUTION_MISSING,
                message=(
                    "Verlusttoleranz nicht pruefbar: Renditeverteilung der "
                    "Strategie fehlt."
                ),
                **common,
            )
        try:
            p10_return_bps = one_year_p10_return_bps(
                expected_return_bps, volatility_bps,
                skew=skew, excess_kurtosis=excess_kurtosis,
            )
        except ValueError:
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_CF_NOT_MONOTONIC,
                message=(
                    "Verlusttoleranz nicht pruefbar: Cornish-Fisher-Abbildung "
                    "fuer diese Schiefe/Kurtosis nicht monoton."
                ),
                **common,
            )
    p10 = float(p10_return_bps)
    if not math.isfinite(p10):
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_DISTRIBUTION_MISSING,
            message="Verlusttoleranz nicht pruefbar: P10 ist keine endliche Zahl.",
            **common,
        )
    p10 = round(p10, 2)
    floor = int(band.floor_bps)
    if p10 < floor:
        shortfall = round(floor - p10, 2)
        return LossToleranceCheck(
            status=STATUS_CONFLICT,
            check_code=REASON_CONFLICT,
            message=(
                "Eignungskonflikt Verlusttoleranz: Im unguenstigen Jahr (10-%-"
                f"Quantil, 1 Jahr) liegt die Rendite der Strategie bei "
                f"{p10 / 100.0:.2f} % und damit {shortfall / 100.0:.2f} pp unter "
                f"der vom Kunden genannten Wertschwankung von "
                f"{floor / 100.0:.0f} %. Freigabe nur mit Begruendung."
            ),
            p10_return_bps=p10,
            shortfall_bps=shortfall,
            requires_justification=True,
            **common,
        )
    return LossToleranceCheck(
        status=STATUS_OK,
        check_code=None,
        message=(
            f"Verlusttoleranz eingehalten: 10-%-Quantil (1 Jahr) "
            f"{p10 / 100.0:.2f} % >= Untergrenze {floor / 100.0:.0f} %."
        ),
        p10_return_bps=p10,
        **common,
    )


def evaluate_loss_tolerance_if_enabled(
    answer_points: int | None,
    *,
    enabled: bool | None = None,
    **kwargs,
) -> LossToleranceCheck | None:
    """Einziger vorgesehener Einstiegspunkt fuer die spaetere Verdrahtung.

    ``None``, solange das Flag aus ist (Default). Keine Seiteneffekte.
    """
    active = LOSS_TOLERANCE_CHECK_ENABLED if enabled is None else bool(enabled)
    if not active:
        return None
    return evaluate_loss_tolerance(answer_points, **kwargs)
