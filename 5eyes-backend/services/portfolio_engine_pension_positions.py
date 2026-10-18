"""Vorsorgevermoegen im Gesamtvermoegen (VORSORGE-PROJECTION-001, 2026-10-18).

Fachentscheid des Users (2026-10-18): Vorsorgegelder (BVG, Saeule 3a,
Freizuegigkeit, Policen) werden von uns NICHT verwaltet, sondern wie in der
klassischen Finanzplanung deterministisch fortgeschrieben -- kein Raten einer
Anlageklassen-Aufteilung, keine geschaetzte Aktienexposure.

Vorher (develop d3c9a67) bekam jede Vorsorge-Position pauschal 45 % Aktien /
45 % Obligationen / 10 % Liquiditaet. Ein Saeule-3a-Konto zaehlte damit zu
45 % als Aktien und loeste im Exposure-Tilt eine Aktienreduktion im
Beratungsvermoegen aus; im Gesamtvermoegens-Pfad wuchs es mit CMA-Renditen.

Jetzt, fuer jede aktive EXTERNE Vorsorge-Position ("Anderes Vermoegen"):

1. Sie ist eigene Kategorie "Vorsorge (gebunden)" -- nicht auf Anlageklassen
   verteilt und ausserhalb der Exposure-Tilts. Ausnahme: erfasst der Berater
   bewusst eine vollstaendige Aufteilung (alloc_*_bps = 10000), zaehlt diese
   im Exposure-Tilt mit; fortgeschrieben wird die Position trotzdem
   deterministisch (wir verwalten sie nicht).
2. Fortschreibung NOMINAL mit dem erfassten Satz (pension_interest_rate_bps),
   sonst mit dem Default je Anlageform (benannte, versionierte Konstanten,
   User-Entscheid). Police: Rueckkaufswert heute -> vertraglicher Ablaufwert
   bei Faelligkeit (geometrisch interpoliert).
3. Bezug: 3a, Freizuegigkeit und Policen werden beim Bezug GENAU EINMAL
   freies Vermoegen (Zufluss im Cashflow-Pfad, nach Kapitalbezugssteuer: pro
   Position erfasst -- CHF-Betrag vor Satz, aus dem kantonalen Steuerrechner --,
   sonst defensiv 10 % fuer 3a/FZ/BVG-Kapital, 3b-Policen 0 %; das pauschale
   Steuermodul des Mandats wird dafuer NICHT verwendet). Davor zaehlen sie nicht als verfuegbar (PENSION-AVAILABILITY-001
   bleibt). BVG: nur Fortschreibung, kein automatischer Bezug (Kapitalbezug
   als verknuepften Vermoegenszufluss erfassen; Rentenmodellierung siehe
   docs/planning/2026-10-18-vorsorge-benefit-reconciliation.md).
4. Ein vom Berater erfasster WealthInflow mit linked_position_id auf die
   Position IST der Bezug: der automatische Bezug entfaellt, die Position
   wird ab dem Jahr dieses Zuflusses ausgebucht (keine Doppelzaehlung).
   Nicht verknuepfte Zufluesse, die nach einem Vorsorgebezug aussehen und im
   selben Jahr wie ein automatischer Bezug liegen, werden als moeglicher
   Doppelbezug gemeldet.

Index-Konvention (wie _simulate_bucket_path): Serie[t] = Wert nach t Jahren
(t=0 heute); cashflow[k] (Kalenderjahr start_year+k) wirkt auf Serie[k+1].
Ein Bezug im Offset k entnimmt den Wert, den die Position in Serie[k+1]
haette; die Position ist ab Index k+1 null.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")

# ---------------------------------------------------------------------------
# Versionierte Annahmen (User-Entscheid 2026-10-18). Saetze NOMINAL p.a.
# ---------------------------------------------------------------------------
PENSION_PROJECTION_ASSUMPTIONS_VERSION = "vorsorge-projektion-2026-10-18"

PENSION_VEHICLES = ("Konto", "Wertschriften", "Police")

# Default-Satz je Anlageform, wenn pro Position nichts erfasst ist.
PENSION_DEFAULT_RATE_BPS_BY_VEHICLE: dict[str, int] = {
    "Konto": 0,            # 3a-/Freizuegigkeitskonto: 0 % p.a.
    "Wertschriften": 300,  # 3a-/Freizuegigkeitsdepot: 3 % p.a. (wie Finanzplaner)
    "Police": 0,           # Police ohne Ablaufwert: konservativ 0 % p.a.
}
# BVG/Pensionskasse: Fortschreibung mit erfasstem Zins, Default 0 % p.a.
PENSION_BVG_DEFAULT_RATE_BPS = 0

# Anlageform, wenn keine erfasst ist (konservativ: Konto = 0 %).
PENSION_DEFAULT_VEHICLE_BY_TYPE: dict[str, str] = {
    "saeule 3a": "Konto",
    "freizuegigkeit": "Konto",
    "saeule 3b": "Police",
    "lebensversicherung": "Police",
}

# Vorsorgearten mit automatischem Kapitalbezug in diesem Modell.
PENSION_AUTO_PAYOUT_TYPES = frozenset({"saeule 3a", "freizuegigkeit", "saeule 3b", "lebensversicherung"})
# Vorsorgearten, deren Kapitalbezug der Kapitalleistungssteuer unterliegt
# (3b-/Lebensversicherungs-Policen: in der Regel steuerfrei -> Default 0).
PENSION_LUMPSUM_TAXED_TYPES = frozenset({"saeule 3a", "freizuegigkeit", "bvg"})
# Kapitalbezugssteuer, wenn pro Position weder Betrag noch Satz erfasst ist:
# defensiv 10 % (User-Entscheid 2026-10-18, Version siehe oben). Der Berater
# erfasst den Wert aus dem Steuerrechner des Kantons
# (pension_lumpsum_tax_rappen hat Vorrang vor pension_lumpsum_tax_bps).
PENSION_LUMPSUM_TAX_DEFAULT_BPS = 1000

# Bisheriger gemischter Default -- gilt NUR noch fuer Vorsorge-Positionen im
# BERATUNGSvermoegen (vom Berater bewusst als verwaltet erfasst) ohne
# Aufteilung. Externe Vorsorge wird nie mehr auf Anlageklassen geraten.
PENSION_ADVISORY_LEGACY_WEIGHTS_BPS: dict[str, int] = {
    "equities": 4500, "bonds": 4500, "real_estate": 0, "alternatives": 0, "liquidity": 1000,
}

PENSION_BOUND_LABEL = "Vorsorge (gebunden)"

_TYPE_LABELS = {
    "bvg": "BVG",
    "saeule 3a": "Säule 3a",
    "freizuegigkeit": "Freizügigkeit",
    "saeule 3b": "Säule 3b",
    "lebensversicherung": "Lebensversicherung",
}

_NON_PENSION_DEFAULT_WEIGHTS_BPS: dict[str, dict[str, int]] = {
    "Depot": {"equities": 6000, "bonds": 2500, "real_estate": 0, "alternatives": 500, "liquidity": 1000},
    "Liquiditaet": {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 10000},
    "Immobilien": {"equities": 0, "bonds": 0, "real_estate": 10000, "alternatives": 0, "liquidity": 0},
    "Alternative": {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 10000, "liquidity": 0},
    "Hypothek": {key: 0 for key in BUCKETS},
    "Custom": {"equities": 5000, "bonds": 2000, "real_estate": 1000, "alternatives": 500, "liquidity": 1500},
}

_PAYOUT_KEYWORDS = re.compile(
    r"(3a|3b|s(ae|ä)ule|pension|bvg|\bpk\b|vorsorge|freiz(ue|ü)gigkeit|police|versicherung|kapitalbezug)",
    re.IGNORECASE,
)


def _norm(value) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        text = text.replace(src, dst)
    return text


def normalized_pension_type(value) -> str:
    return " ".join(_norm(value).casefold().split())


def recorded_split(position) -> dict[str, int] | None:
    split = {
        "equities": int(getattr(position, "alloc_equities_bps", 0) or 0),
        "bonds": int(getattr(position, "alloc_bonds_bps", 0) or 0),
        "real_estate": int(getattr(position, "alloc_real_estate_bps", 0) or 0),
        "alternatives": int(getattr(position, "alloc_alternatives_bps", 0) or 0),
        "liquidity": int(getattr(position, "alloc_liquidity_bps", 0) or 0),
    }
    return split if sum(split.values()) == 10000 else None


def is_pension_position(position) -> bool:
    from services.wealth_position_semantics import canonical_position_type

    return _norm(canonical_position_type(getattr(position, "position_type", ""))) == "Vorsorge"


def is_external_pension_position(position) -> bool:
    """Aktive Vorsorge-Position im "Anderen Vermoegen" (nicht verwaltet)."""
    from services.wealth_position_semantics import is_external_wealth_assignment

    if getattr(position, "deleted_at", None):
        return False
    if int(getattr(position, "is_active", 1) or 0) != 1:
        return False
    return is_pension_position(position) and is_external_wealth_assignment(
        getattr(position, "assignment", "")
    )


def position_bucket_weights(position) -> dict[str, int]:
    """Bucket-Gewichte einer Position, die auf Anlageklassen verteilt wird.

    Externe Vorsorge laeuft NICHT hierueber (siehe _summarize_positions);
    fuer eine Vorsorge-Position im Beratungsvermoegen gilt die erfasste
    Aufteilung bzw. der bisherige gemischte Default."""
    from services.wealth_position_semantics import (
        canonical_position_type,
        is_direct_real_estate_position,
    )

    canonical_type = _norm(canonical_position_type(getattr(position, "position_type", "")))
    if canonical_type in ("Depot", "Vorsorge"):
        split = recorded_split(position)
        if split is not None:
            return split
        if canonical_type == "Vorsorge":
            return dict(PENSION_ADVISORY_LEGACY_WEIGHTS_BPS)
    if is_direct_real_estate_position(getattr(position, "position_type", "")):
        return dict(_NON_PENSION_DEFAULT_WEIGHTS_BPS["Immobilien"])
    return dict(
        _NON_PENSION_DEFAULT_WEIGHTS_BPS.get(canonical_type, _NON_PENSION_DEFAULT_WEIGHTS_BPS["Custom"])
    )


def pension_vehicle(position) -> str | None:
    raw = str(getattr(position, "pension_vehicle", "") or "").strip()
    if raw in PENSION_VEHICLES:
        return raw
    return PENSION_DEFAULT_VEHICLE_BY_TYPE.get(
        normalized_pension_type(getattr(position, "pension_type", None))
    )


def pension_rate_bps(position) -> tuple[int, bool]:
    """(nominaler Satz p.a. in bps, True wenn Default statt erfasst)."""
    recorded = getattr(position, "pension_interest_rate_bps", None)
    if recorded is not None and not isinstance(recorded, bool):
        return int(recorded), False
    vehicle = pension_vehicle(position)
    if vehicle is None:
        return PENSION_BVG_DEFAULT_RATE_BPS, True
    return PENSION_DEFAULT_RATE_BPS_BY_VEHICLE[vehicle], True


def _year_of(iso_value) -> int | None:
    text = str(iso_value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def resolve_payout_year(position, *, birth_year: int | None, retirement_year: int | None) -> tuple[int | None, str]:
    """Bezugsjahr + Quelle. Police: Faelligkeit; sonst 'Verfuegbar ab',
    Geburtsjahr + Rentenalter der Position, Pensionierungsjahr des Mandats."""
    if pension_vehicle(position) == "Police":
        maturity_year = _year_of(getattr(position, "pension_maturity_date", None))
        if maturity_year is not None:
            return maturity_year, "Fälligkeit"
    available_year = _year_of(getattr(position, "liquidity_available_from", None))
    if available_year is not None:
        return available_year, "Verfügbar ab"
    age = getattr(position, "pension_retirement_age", None)
    if birth_year and age:
        return int(birth_year) + int(age), "Rentenalter"
    if retirement_year:
        return int(retirement_year), "Pensionierungsjahr Mandat"
    return None, ""


def _chf(rappen: int) -> str:
    return "CHF " + f"{int(round(rappen / 100)):,}".replace(",", "'")


def pension_lumpsum_tax_default_bps(position) -> int:
    """Default-Satz ohne Erfassung: 10 % fuer steuerbare Arten, sonst 0."""
    type_key = normalized_pension_type(getattr(position, "pension_type", None))
    return PENSION_LUMPSUM_TAX_DEFAULT_BPS if type_key in PENSION_LUMPSUM_TAXED_TYPES else 0


def pension_lumpsum_tax(position, gross_rappen: int) -> tuple[int, str]:
    """(Kapitalbezugssteuer in Rappen, Reasoning-Text) fuer einen Bezug."""
    gross = max(0, int(gross_rappen))
    amount = getattr(position, "pension_lumpsum_tax_rappen", None)
    rate = getattr(position, "pension_lumpsum_tax_bps", None)
    if amount is not None:
        tax = min(gross, max(0, int(amount)))
        return tax, f"Kapitalbezugssteuer {_chf(tax)} (erfasst)"
    if rate is not None:
        tax = min(gross, max(0, int(round(gross * int(rate) / 10000))))
        return tax, f"Kapitalbezugssteuer {_chf(tax)} (erfasst {int(rate) / 100:.2f} %)"
    default_bps = pension_lumpsum_tax_default_bps(position)
    if default_bps <= 0:
        return 0, ""
    tax = min(gross, int(round(gross * default_bps / 10000)))
    return tax, f"Kapitalbezugssteuer {_chf(tax)} (Default {default_bps / 100:g} %, defensiv)"


@dataclass
class PensionProjection:
    series_rappen: list[int]
    payout_series_rappen: list[int]
    notes: list[str] = field(default_factory=list)


def _value_path(position, value: int, horizon: int, start_year: int) -> list[float]:
    """Nominaler Wertpfad Serie[0..H] (ohne Bezug)."""
    if pension_vehicle(position) == "Police":
        maturity_value = getattr(position, "pension_maturity_value_rappen", None)
        maturity_year = _year_of(getattr(position, "pension_maturity_date", None))
        if maturity_value and maturity_year is not None and value > 0:
            steps = max(1, maturity_year - int(start_year) + 1)
            factor = (float(maturity_value) / float(value)) ** (1.0 / steps)
            path = []
            for t in range(horizon + 1):
                if t >= steps:
                    path.append(float(maturity_value))
                else:
                    path.append(value * factor ** t)
            return path
    rate, _default = pension_rate_bps(position)
    return [value * (1.0 + rate / 10000.0) ** t for t in range(horizon + 1)]


def build_pension_projection(
    positions,
    wealth_inflows,
    *,
    start_year: int,
    horizon_years: int,
    value_of: Callable[[object], int],
    birth_year: int | None = None,
    retirement_year: int | None = None,
) -> PensionProjection | None:
    """Deterministische Projektion aller externen Vorsorge-Positionen.

    ``None``, wenn es keine gibt (Foundation-Vertrag bleibt dann
    byte-identisch). Kapitalbezugssteuer: siehe pension_lumpsum_tax.
    """
    horizon = max(0, int(horizon_years or 0))
    start_year = int(start_year)
    linked: dict[str, list] = {}
    unlinked: list = []
    for inflow in wealth_inflows or []:
        if int(getattr(inflow, "is_active", 1) or 0) != 1:
            continue
        linked_id = getattr(inflow, "linked_position_id", None)
        if linked_id:
            linked.setdefault(str(linked_id), []).append(inflow)
        else:
            unlinked.append(inflow)

    series = [0] * (horizon + 1)
    payouts = [0] * horizon
    notes: list[str] = []
    auto_payout_years: dict[int, list[str]] = {}
    found = False
    for position in positions or []:
        if not is_external_pension_position(position):
            continue
        value = int(value_of(position))
        if value <= 0:
            continue
        found = True
        type_key = normalized_pension_type(getattr(position, "pension_type", None))
        label = str(getattr(position, "label", "") or _TYPE_LABELS.get(type_key, "Vorsorge"))
        path = _value_path(position, value, horizon, start_year)
        rate, rate_is_default = pension_rate_bps(position)
        vehicle = pension_vehicle(position)
        if vehicle == "Police" and getattr(position, "pension_maturity_value_rappen", None):
            growth_text = "Rückkaufswert heute, vertraglicher Ablaufwert bei Fälligkeit"
        else:
            growth_text = (
                f"nominal {rate / 100:.2f} % p.a."
                + (" (Default)" if rate_is_default else "")
            )
        exit_offset: int | None = None
        payout_text = ""

        own_inflows = linked.get(str(getattr(position, "id", "") or ""), [])
        linked_offsets = [
            int(getattr(i, "expected_year", 0) or 0) - start_year for i in own_inflows
        ]
        linked_offsets = [k for k in linked_offsets if 0 <= k < horizon]
        if linked_offsets:
            exit_offset = min(linked_offsets)
            payout_text = (
                f"Bezug über erfassten Vermögenszufluss {start_year + exit_offset} "
                "(automatischer Bezug entfällt)"
            )
        elif type_key in PENSION_AUTO_PAYOUT_TYPES:
            year, source = resolve_payout_year(
                position, birth_year=birth_year, retirement_year=retirement_year,
            )
            if year is None:
                payout_text = (
                    "kein Bezugsjahr ermittelbar (Verfügbar ab, Rentenalter mit "
                    "Geburtsjahr oder Pensionierungsjahr fehlt) – bleibt gebunden"
                )
            else:
                offset = max(0, year - start_year)
                if offset >= horizon:
                    payout_text = f"Bezug {year} liegt ausserhalb des Horizonts – bleibt gebunden"
                else:
                    exit_offset = offset
                    gross = int(round(path[offset + 1]))
                    tax, tax_text = pension_lumpsum_tax(position, gross)
                    payouts[offset] += gross - tax
                    auto_payout_years.setdefault(start_year + offset, []).append(label)
                    payout_text = (
                        f"Kapitalbezug {start_year + offset} ({source}) {_chf(gross)}"
                        + (f", {tax_text}" if tax_text else "")
                        + f" -> {_chf(gross - tax)} freies Vermögen"
                    )
        else:
            payout_text = (
                "nur Fortschreibung, kein automatischer Bezug (Kapitalbezug als "
                "verknüpften Vermögenszufluss erfassen; BVG-Rente noch nicht modelliert)"
            )

        last = horizon if exit_offset is None else exit_offset
        for t in range(0, last + 1):
            series[t] += int(round(path[t]))
        notes.append(
            f"Vorsorge '{label}' ({_TYPE_LABELS.get(type_key, 'ohne Typ')}"
            + (f", {vehicle}" if vehicle else "")
            + f"): gebunden, {growth_text}; {payout_text}."
        )

    if not found:
        return None
    for inflow in unlinked:
        year = getattr(inflow, "expected_year", None)
        text = f"{getattr(inflow, 'label', '')} {getattr(inflow, 'source_type', '')}"
        if year in auto_payout_years and (
            str(getattr(inflow, "source_type", "")) == "Saeule3b" or _PAYOUT_KEYWORDS.search(text)
        ):
            notes.append(
                f"Möglicher Doppelbezug: Vermögenszufluss '{getattr(inflow, 'label', '')}' "
                f"({year}) ist mit keiner Vorsorge-Position verknüpft, während "
                f"{', '.join(auto_payout_years[year])} im selben Jahr automatisch "
                "bezogen wird. Bitte den Zufluss mit der Position verknüpfen oder entfernen."
            )
    notes.append(
        "Vorsorgevermögen wird nicht verwaltet, sondern deterministisch fortgeschrieben "
        f"(Annahmen-Version {PENSION_PROJECTION_ASSUMPTIONS_VERSION}); es zählt erst ab "
        "dem Bezug als verfügbares Vermögen."
    )
    return PensionProjection(series_rappen=series, payout_series_rappen=payouts, notes=notes)




def external_pension_projection(
    positions,
    wealth_inflows,
    *,
    start_year,
    horizon_years: int,
    fx_source=None,
    target_currency: str = "CHF",
    mandate=None,
) -> PensionProjection | None:
    """Engine-Einstieg: Projektion mit Waehrungsumrechnung, Mandats-
    Geburts-/Pensionierungsjahr und Kapitalbezugssteuer des Mandats."""
    from datetime import date

    from services.portfolio_engine import _convert_position_amount_to_target_currency

    return build_pension_projection(
        positions,
        wealth_inflows,
        start_year=int(start_year if start_year is not None else date.today().year),
        horizon_years=horizon_years,
        value_of=lambda pos: max(0, _convert_position_amount_to_target_currency(
            pos, fx_source, target_currency,
        )),
        birth_year=int(getattr(mandate, "client_birth_year", 0) or 0) or None,
        retirement_year=int(getattr(mandate, "retirement_year", 0) or 0) or None,
    )


def with_pension_payouts(inflow_series_rappen: list[int], external_foundation_projection: dict) -> list[int]:
    """Automatische Vorsorgebezuege sind Zufluesse ins freie Vermoegen
    (genau einmal, im Bezugsjahr)."""
    payouts = (external_foundation_projection or {}).get("pension_payout_series_rappen")
    if not payouts:
        return inflow_series_rappen
    if len(payouts) != len(inflow_series_rappen):
        raise ValueError("Vorsorge-Bezugsserie passt nicht zum Projektionshorizont.")
    return [int(a) + int(b) for a, b in zip(inflow_series_rappen, payouts)]


# ---------------------------------------------------------------------------
# Engine-Einstiege (aus portfolio_engine.py ausgelagert, Zeilenbudget)
# ---------------------------------------------------------------------------


def summarize_positions(positions, fx_source=None, target_currency: str = "CHF"):
    """Ersetzt portfolio_engine._summarize_positions (re-exportiert).

    Externe Vorsorge ist eigene Kategorie: in total_rappen, nicht in
    amounts_rappen; nur eine bewusst erfasste Aufteilung landet in
    pension_exposure_amounts_rappen (Exposure-Tilt)."""
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        PortfolioSummary,
        _convert_position_amount_to_target_currency,
    )

    amounts = {key: 0 for key in BUCKET_FIELDS}
    total_rappen = 0
    pension_bound_rappen = 0
    pension_exposure = {key: 0 for key in BUCKET_FIELDS}
    for pos in positions:
        value_rappen = _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        if value_rappen <= 0:
            continue
        total_rappen += value_rappen
        if is_external_pension_position(pos):
            pension_bound_rappen += value_rappen
            split = recorded_split(pos)
            if split is not None:
                for key in BUCKET_FIELDS:
                    pension_exposure[key] += int(round(value_rappen * split[key] / 10000))
            continue
        weights = position_bucket_weights(pos)
        for key in BUCKET_FIELDS:
            amounts[key] += int(round(value_rappen * weights[key] / 10000))
    return PortfolioSummary(
        amounts_rappen=amounts,
        total_rappen=total_rappen,
        pension_bound_rappen=pension_bound_rappen,
        pension_exposure_amounts_rappen=(
            pension_exposure if any(pension_exposure.values()) else None
        ),
    )


def pension_foundation_keys(
    positions,
    wealth_inflows,
    *,
    start_year,
    horizon_years: int,
    fx_source=None,
    target_currency: str = "CHF",
    mandate=None,
) -> dict[str, list[int]]:
    """Zusatz-Keys fuer _build_external_foundation_projection: deterministische
    Vorsorge-Serie (H+1) und Netto-Bezuege (H, vom Loader in den Cashflow-Pfad
    addiert). Ohne externe Vorsorge ``{}`` -> Vertrag byte-identisch."""
    pension = external_pension_projection(
        positions,
        wealth_inflows,
        start_year=start_year,
        horizon_years=horizon_years,
        fx_source=fx_source,
        target_currency=target_currency,
        mandate=mandate,
    )
    if pension is None:
        return {}
    return {
        "pension_series_rappen": list(pension.series_rappen),
        "pension_payout_series_rappen": list(pension.payout_series_rappen),
    }


def pension_series_for_horizon(external_foundation_projection: dict, required_length: int) -> list[int]:
    """Vorsorge-Serie fuer die Optimizer-Funding-Serie: externe Vorsorge laeuft
    mit ihrer eigenen deterministischen Serie statt in der CPI-Basis."""
    series = list(
        (external_foundation_projection or {}).get("pension_series_rappen")
        or [0] * required_length
    )
    if len(series) != required_length:
        from services.optimizer.constraints import OptimizerInputError

        raise OptimizerInputError(
            "Die Vorsorge-Serie deckt den Optimizer-Horizont nicht "
            "vollstaendig ab."
        )
    return [max(0, int(value)) for value in series]


def with_pension_notes(
    total_summary,
    positions,
    wealth_inflows,
    *,
    start_year,
    horizon_years: int,
    fx_source=None,
    target_currency: str = "CHF",
    mandate=None,
):
    """total_summary mit den Reasoning-Saetzen zur Vorsorge-Fortschreibung
    (ausgegeben ueber _apply_external_exposure_tilts)."""
    from dataclasses import replace

    pension = external_pension_projection(
        positions,
        wealth_inflows,
        start_year=start_year,
        horizon_years=horizon_years,
        fx_source=fx_source,
        target_currency=target_currency,
        mandate=mandate,
    )
    if pension is None:
        return total_summary
    return replace(total_summary, assumption_notes=tuple(pension.notes))
