"""SUITABILITY-LOSS-TOLERANCE-001: Verlusttoleranz-Pruefung (Vorbereitung, INAKTIV).

Gehoert zu Audit 2026-11, Entscheid AA-8, Luecke L16, Paket P11, Welle 0.
Auflagen aus der Pruefrunde #857 (N-857-3) sind hier schon festgeschrieben.

Frage 10 des Risikoprofils fragt, welche Wertschwankung der Kunde zu tragen
bereit ist (z. B. "Wertschwankung ca. -6 % bis +10 %"). Ares prueft diese
Antwort bisher nicht gegen die Strategie. Die Risky Fraction bleibt der harte
Plausibilitaets-Cap. Zusaetzlich gilt kuenftig:

    P10(1-Jahres-Rendite der SAA)  >=  Untergrenze der gewaehlten Antwort

P11 deckt nur die RisikoBEREITSCHAFT ab (ausdrueckliche Schwankungstoleranz).
Die Risikofaehigkeit bleibt ueber min(Faehigkeit, Bereitschaft) im Score.

Inhalt dieses Moduls, ausschliesslich reine Funktionen:

* ``LOSS_TOLERANCE_BANDS`` bildet die Punkte von Frage 10 auf die Unter- und
  Obergrenze der Wertschwankung ab. Die Werte werden aus den bestehenden
  Optionstexten (``risk_questionnaire_integrity.STANDARD_OPTIONS[10]``)
  gelesen, nicht abgetippt. Der Fragebogen selbst (Paragraf 2, Vorlage) wird
  nicht veraendert. Laesst sich eine Option nicht lesen, entsteht ein
  markierter Platzhalter ohne Untergrenze. Es wird nichts erfunden.
* Quantilquelle (N-857-3). Sperrgrundlage ist NUR
  - das P10 aus den MC-Pfaden auf Anlageklassenebene (``p10_from_paths``,
    Quelle ``SOURCE_MC_ASSET_PATHS``), oder
  - das P10 einer lognormalen 1-Jahres-Rendite aus Portfolio-mu/-sigma mit
    Schiefe 0 und Exzess-Kurtosis 0 (``lognormal_p10_return_bps``, Quelle
    ``SOURCE_LOGNORMAL_K0``).
  Liegen beide vor, gilt das Minimum (konservativ). Ein Momentenpfad mit
  Schiefe oder Kurtosis ungleich 0 ist als Sperrgrundlage gesperrt: bei
  fester Varianz rueckt Kurtosis das P10 nach innen, ein Portfolio-CF waere
  gemessen bis 2.2 pp zu mild. ``one_year_p10_return_bps`` (CF) bleibt nur
  als Ausweis-/Vergleichsfunktion.
* P5 und CVaR(10 %) werden nur ausgewiesen (``tail_disclosure_from_paths``),
  ohne Sperrwirkung.
* Konfliktbehandlung nach ``mandate_type``:
  - "Anlageberatung": Abraten plus dokumentierte Begruendung (Kundenentscheid).
  - "Vermoegensverwaltung" und jeder andere/unbekannte Typ (fail-closed):
    Block. Eine Begruendung genuegt nicht; Profil neu erheben oder Strategie
    anpassen.
* ``evaluate_loss_tolerance`` liefert ein ``LossToleranceCheck``.

NICHT VERDRAHTET. ``LOSS_TOLERANCE_CHECK_ENABLED`` ist ``False``, und
``evaluate_loss_tolerance_if_enabled`` gibt in diesem Zustand ``None`` zurueck.
Aktiviert wird P11 erst nach P2b (Netto-Simulation): AA-8 verlangt das Quantil
netto Kosten. Vor der Aktivierung muss Compliance die Punkte in
``COMPLIANCE_PLACEHOLDERS`` freigeben (Liste aus Dok. 86, Pruefrunde #857).
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from statistics import NormalDist
from typing import Mapping, Sequence

import numpy as np

from services.optimizer.distributions import (
    cornish_fisher_is_monotonic,
    standard_normal_to_log_return,
)
from services.risk_questionnaire_integrity import (
    POINT_FIELD_BY_QUESTION,
    STANDARD_OPTIONS,
    STANDARD_POINTS,
)

CHECK_VERSION = "loss_tolerance_p10_1y_v1_inactive"

# Flag: standardmaessig AUS. Aktivierung erst nach P2b (Netto-Simulation),
# per eigenem PR mit Verdrahtung (Kennzahlen + Finalize-Gate).
LOSS_TOLERANCE_CHECK_ENABLED = False

QUESTION_NUMBER = 10
POINT_FIELD = POINT_FIELD_BY_QUESTION[QUESTION_NUMBER]  # q_risk_preference_points
QUANTILE = 0.10
DISCLOSURE_QUANTILE = 0.05
HORIZON_YEARS = 1
INTERPRETATION_SOURCE = "AA-8"

RETURN_BASIS_GROSS = "gross"
RETURN_BASIS_NET = "net_of_costs"

SOURCE_MC_ASSET_PATHS = "mc_asset_level_paths"
SOURCE_LOGNORMAL_K0 = "lognormal_moments_k0"
ADMISSIBLE_SOURCES = (SOURCE_MC_ASSET_PATHS, SOURCE_LOGNORMAL_K0)

MANDATE_ADVISORY = "Anlageberatung"
MANDATE_DISCRETIONARY = "Vermögensverwaltung"
RESOLUTION_ADVISE_AGAINST = "advise_against_with_documented_justification"
RESOLUTION_BLOCK = "block_reassess_profile_or_adjust_strategy"

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
REASON_TAIL_MOMENTS_NOT_ADMISSIBLE = "LOSS_TOLERANCE_TAIL_MOMENTS_NOT_ADMISSIBLE"
REASON_SOURCE_NOT_ADMISSIBLE = "LOSS_TOLERANCE_SOURCE_NOT_ADMISSIBLE"

PLACEHOLDER_UNMAPPED = "PLACEHOLDER_UNMAPPED"

# Compliance-Platzhalter vor der Aktivierung (Dok. 86, Pruefrunde #857, 1-11).
# Jeder ist offen und wird mit jedem Ergebnis ausgewiesen; nichts davon ist
# hier entschieden.
COMPLIANCE_PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("CP01_INTERVAL_COVERAGE_P10",
     "Lesart 80-%-Intervall / P10 (Fragetext 10 nennt kein Konfidenzniveau; "
     "Lesart aus AA-8)."),
    ("CP02_HORIZON_ONE_YEAR",
     "Horizont 1 Jahr (Fragetext 10 nennt keinen Zeitraum; aus AA-8)."),
    ("CP03_NOMINAL_OR_REAL", "Pruefung nominal oder real."),
    ("CP04_NET_COST_BASIS",
     "Kostenbasis netto: TER, Honorar, Transaktionskosten, Behandlung von "
     "Retrozessionen (verfuegbar erst mit P2b)."),
    ("CP05_REFERENCE_PORTFOLIO",
     "Referenzportfolio: SAA oder umgesetztes Produktportfolio; "
     "Beratungsvermoegen oder Gesamtvermoegen."),
    ("CP06_QUANTILE_SOURCE_AND_STRESS",
     "Quantilquelle (MC-Pfade Anlageklassenebene / lognormal k=0) und "
     "Stress-/Krisenkorrelations-Einstellung (N-857-3)."),
    ("CP07_TOLERANCE_MARGIN_CA",
     "Toleranzmarge wegen 'ca.' im Optionstext (ja/nein)."),
    ("CP08_Q10_Q11_SCORE_CONTRADICTIONS",
     "Behandlung von Widerspruechen zwischen Frage 10, Frage 11 und Score "
     "(Frage 11 hat kein Toleranzband und wird nicht abgebildet)."),
    ("CP09_CONFLICT_TEXT_JUSTIFICATION_FOUR_EYES",
     "Konflikttext fuer Kundendokument und PDF, Begruendungsfeld, "
     "Mindestlaenge, Vier-Augen-Prinzip bei Vermoegensverwaltung."),
    ("CP10_REASON_CODE_CATALOG",
     "Aufnahme der Pruef-Codes in den Reason-Code-Katalog (mit Pin-Nachfuehrung)."),
    ("CP11_RECHECK_TRIGGERS",
     "Ausloeser fuer die erneute Pruefung (Aenderung von Profil, CMA, Strategie)."),
)
COMPLIANCE_PLACEHOLDER_KEYS: tuple[str, ...] = tuple(k for k, _ in COMPLIANCE_PLACEHOLDERS)

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


# ---------------------------------------------------------------------------
# Quantile
# ---------------------------------------------------------------------------

def lognormal_p10_return_bps(expected_return_bps: float, volatility_bps: float) -> float:
    """P10 der einfachen 1-Jahres-Rendite, lognormal (Schiefe 0, Kurtosis 0).

    Zulaessige Sperrgrundlage (``SOURCE_LOGNORMAL_K0``). Gleiche Momenten-
    Abbildung wie die MC (``standard_normal_to_log_return`` ohne Tail-Term).
    """
    gross = standard_normal_to_log_return(
        _Z_QUANTILE, float(expected_return_bps), float(volatility_bps),
    )
    return (float(gross) - 1.0) * 10000.0


def one_year_p10_return_bps(
    expected_return_bps: float,
    volatility_bps: float,
    *,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> float:
    """P10 mit Cornish-Fisher -- NUR Ausweis/Vergleich, keine Sperrgrundlage.

    Fuer eine EINZELNE Anlageklasse entspricht das der MC-Transformation. Auf
    Portfolioebene mit aggregierten Momenten ist es nicht konservativ
    (N-857-3). ``evaluate_loss_tolerance`` verwendet es nie.
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


def _finite_returns(one_year_returns_bps: Sequence[float]) -> np.ndarray:
    values = np.asarray(one_year_returns_bps, dtype=np.float64).reshape(-1)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError(REASON_DISTRIBUTION_MISSING)
    return values


def p10_from_paths(one_year_returns_bps: Sequence[float]) -> float:
    """P10 aus den 1-Jahres-Portfoliorenditen der MC-Pfade (bps).

    Die Pfade muessen auf Anlageklassenebene simuliert und erst danach
    gewichtet sein (wie in der Produktions-MC). Quelle ``SOURCE_MC_ASSET_PATHS``.
    """
    return float(np.quantile(_finite_returns(one_year_returns_bps), QUANTILE))


def tail_disclosure_from_paths(one_year_returns_bps: Sequence[float]) -> dict[str, float]:
    """P5 und CVaR(10 %) aus MC-Pfaden -- nur Ausweis, ohne Sperrwirkung."""
    values = _finite_returns(one_year_returns_bps)
    p10 = float(np.quantile(values, QUANTILE))
    tail = values[values <= p10]
    return {
        "p5_return_bps": round(float(np.quantile(values, DISCLOSURE_QUANTILE)), 2),
        "cvar10_return_bps": round(float(tail.mean()), 2),
    }


# ---------------------------------------------------------------------------
# Ergebnisobjekt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LossToleranceCheck:
    status: str
    check_code: str | None
    message: str
    mandate_type: str | None = None
    answer_points: int | None = None
    answer_text: str | None = None
    floor_bps: int | None = None
    upper_bps: int | None = None
    p10_return_bps: float | None = None
    p10_source: str | None = None
    p10_candidates_bps: dict = field(default_factory=dict)
    shortfall_bps: float | None = None
    conflict_resolution: str | None = None
    blocks_release: bool = False
    justification_sufficient: bool = False
    requires_justification: bool = False
    requires_advise_against: bool = False
    p5_return_bps: float | None = None
    cvar10_return_bps: float | None = None
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


def _placeholders(band: LossToleranceBand | None, *, unmapped: bool = False) -> tuple[str, ...]:
    items = list(COMPLIANCE_PLACEHOLDER_KEYS)
    if unmapped or (band is not None and band.placeholder):
        items.append(PLACEHOLDER_UNMAPPED)
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


def conflict_resolution_for(mandate_type: str | None) -> dict:
    """Konfliktbehandlung je Mandatstyp (fail-closed: unbekannt = Block)."""
    if str(mandate_type or "") == MANDATE_ADVISORY:
        return {
            "conflict_resolution": RESOLUTION_ADVISE_AGAINST,
            "blocks_release": True,
            "justification_sufficient": True,
            "requires_justification": True,
            "requires_advise_against": True,
        }
    return {
        "conflict_resolution": RESOLUTION_BLOCK,
        "blocks_release": True,
        "justification_sufficient": False,
        "requires_justification": False,
        "requires_advise_against": False,
    }


def evaluate_loss_tolerance(
    answer_points: int | None,
    *,
    mandate_type: str | None,
    mc_p10_return_bps: float | None = None,
    expected_return_bps: float | None = None,
    volatility_bps: float | None = None,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    p5_return_bps: float | None = None,
    cvar10_return_bps: float | None = None,
    return_basis: str = RETURN_BASIS_GROSS,
) -> LossToleranceCheck:
    """Prueft P10 (1 Jahr) der SAA gegen die Untergrenze der Antwort zu Frage 10.

    Sperrgrundlage: ``mc_p10_return_bps`` (MC-Pfade, Anlageklassenebene) und/
    oder lognormales P10 aus ``expected_return_bps``/``volatility_bps``; bei
    beiden das Minimum. Ein Momentenpfad mit ``skew`` oder ``excess_kurtosis``
    ungleich 0 wird abgelehnt (``not_evaluable``). ``p5``/``cvar10`` sind nur
    Ausweis. Fail-closed: fehlende/unbekannte Antwort oder Verteilung ->
    ``not_evaluable``, nie ``ok``. Konflikt genau dann, wenn ``P10 < Untergrenze``.
    """
    base = dict(
        mandate_type=mandate_type,
        return_basis=return_basis,
        p5_return_bps=None if p5_return_bps is None else round(float(p5_return_bps), 2),
        cvar10_return_bps=(
            None if cvar10_return_bps is None else round(float(cvar10_return_bps), 2)
        ),
    )
    if isinstance(answer_points, bool) or not isinstance(answer_points, int):
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_ANSWER_MISSING,
            message="Verlusttoleranz nicht pruefbar: Antwort zu Frage 10 fehlt.",
            placeholders=_placeholders(None),
            **base,
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
            placeholders=_placeholders(band, unmapped=True),
            **base,
        )
    common = dict(
        answer_points=band.points,
        answer_text=band.option_text,
        floor_bps=band.floor_bps,
        upper_bps=band.upper_bps,
        placeholders=_placeholders(band),
        **base,
    )
    candidates: dict[str, float] = {}
    if mc_p10_return_bps is not None:
        value = float(mc_p10_return_bps)
        if not math.isfinite(value):
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_DISTRIBUTION_MISSING,
                message="Verlusttoleranz nicht pruefbar: MC-P10 ist keine endliche Zahl.",
                **common,
            )
        candidates[SOURCE_MC_ASSET_PATHS] = round(value, 2)
    if expected_return_bps is not None or volatility_bps is not None:
        if expected_return_bps is None or volatility_bps is None:
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_DISTRIBUTION_MISSING,
                message=(
                    "Verlusttoleranz nicht pruefbar: erwartete Rendite und "
                    "Volatilitaet muessen beide vorliegen."
                ),
                **common,
            )
        # N-857-3: Tail-Momente sind keine zulaessige Sperrgrundlage.
        if float(skew) != 0.0 or float(excess_kurtosis) != 0.0:
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_TAIL_MOMENTS_NOT_ADMISSIBLE,
                message=(
                    "Verlusttoleranz nicht pruefbar: ein Momentenpfad mit "
                    "Schiefe oder Kurtosis ist keine zulaessige Sperrgrundlage "
                    "(MC-Pfade auf Anlageklassenebene oder lognormal mit k=0)."
                ),
                **common,
            )
        lognormal = lognormal_p10_return_bps(expected_return_bps, volatility_bps)
        if not math.isfinite(lognormal):
            return LossToleranceCheck(
                status=STATUS_NOT_EVALUABLE,
                check_code=REASON_DISTRIBUTION_MISSING,
                message="Verlusttoleranz nicht pruefbar: P10 ist keine endliche Zahl.",
                **common,
            )
        candidates[SOURCE_LOGNORMAL_K0] = round(lognormal, 2)
    if not candidates:
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_DISTRIBUTION_MISSING,
            message="Verlusttoleranz nicht pruefbar: Renditeverteilung der Strategie fehlt.",
            **common,
        )
    source = min(candidates, key=lambda key: (candidates[key], key))
    if source not in ADMISSIBLE_SOURCES:  # Schutz gegen kuenftige Quellen
        return LossToleranceCheck(
            status=STATUS_NOT_EVALUABLE,
            check_code=REASON_SOURCE_NOT_ADMISSIBLE,
            message="Verlusttoleranz nicht pruefbar: Quantilquelle nicht zulaessig.",
            **common,
        )
    p10 = candidates[source]
    floor = int(band.floor_bps)
    evaluated = dict(p10_return_bps=p10, p10_source=source, p10_candidates_bps=dict(candidates))
    if p10 < floor:
        shortfall = round(floor - p10, 2)
        resolution = conflict_resolution_for(mandate_type)
        action = (
            "Abraten und Begruendung dokumentieren (Kundenentscheid)."
            if resolution["justification_sufficient"]
            else "Freigabe gesperrt: Profil neu erheben oder Strategie anpassen; "
                 "eine Begruendung genuegt nicht."
        )
        return LossToleranceCheck(
            status=STATUS_CONFLICT,
            check_code=REASON_CONFLICT,
            message=(
                "Eignungskonflikt Verlusttoleranz: Im unguenstigen Jahr (10-%-"
                f"Quantil, 1 Jahr) liegt die Rendite der Strategie bei "
                f"{p10 / 100.0:.2f} % und damit {shortfall / 100.0:.2f} pp unter "
                f"der vom Kunden genannten Wertschwankung von "
                f"{floor / 100.0:.0f} %. {action}"
            ),
            shortfall_bps=shortfall,
            **resolution,
            **evaluated,
            **common,
        )
    return LossToleranceCheck(
        status=STATUS_OK,
        check_code=None,
        message=(
            f"Verlusttoleranz eingehalten: 10-%-Quantil (1 Jahr) "
            f"{p10 / 100.0:.2f} % >= Untergrenze {floor / 100.0:.0f} %."
        ),
        **evaluated,
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
