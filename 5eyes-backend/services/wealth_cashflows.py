"""Vermögensgetriebene Cashflows (2026-06-14).

Leitet aus Vermögenspositionen die periodischen Cashflows ab, die sonst nur
'im Hintergrund' existierten — damit Hypothekarzins, Amortisation, Miet- und
Zinserträge SICHTBAR im Cashflow auftauchen und in Summe/Projektion zählen.

Fachlogik (verifiziert gegen models/wealth.py + schemas/wealth.py):
  • Hypothek (position_type='Hypothek', assignment='Verbindlichkeit'):
        current_value_rappen = Schuld; mortgage_interest_rate_bps = Zinssatz.
        -> Hypothekarzins/Jahr (AUSGABE) = |Schuld| * rate_bps / 10000
        -> Amortisation/Jahr (AUSGABE)   = mortgage_amortization_rappen
  • Immobilien:
        -> Mieteinnahmen/Jahr (EINNAHME) = property_rental_income_rappen
  • Liquidität:
        -> Liquiditätszins/Jahr (EINNAHME) = current_value * liquidity_rate_bps / 10000

BEWUSST NICHT abgeleitet: reine Wertsteigerung von Depot/Alternative
(asset_expected_return_bps) — das ist Vermögenswachstum, steckt bereits in der
Verzehr-Projektion; als Cashflow wäre es Doppelzählung.

Die erzeugten Objekte sind READ-ONLY (kein DB-Eintrag) und tragen die Attribute,
die cashflow_timeline.totals_for_year/contribution_for_year via getattr liest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

from services.wealth_position_semantics import (
    is_direct_real_estate_position,
    is_liquidity_position,
    is_mortgage_position,
)


@dataclass
class DerivedCashflow:
    """Abgeleiteter, schreibgeschützter Cashflow aus einer Vermögensposition.

    Attribute spiegeln die von cashflow_timeline gelesenen Cashflow-Felder +
    Herkunfts-Marker (is_derived/source/origin_position_id) für die UI."""
    id: str
    client_id: str
    cashflow_type: str            # 'Income' | 'Expense'
    label: str
    amount_rappen: int
    currency: str = "CHF"
    frequency: str = "jährlich"
    nature: str = "wiederkehrend"
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_inflation_linked: int = 0
    notes: Optional[str] = None
    is_active: int = 1
    # Herkunft (für UI-Kennzeichnung 'automatisch aus Vermögen')
    is_derived: int = 1
    source: str = "wealth_position"
    origin_position_id: Optional[str] = None
    origin_position_type: Optional[str] = None
    # Vermögens-Topf der Quellposition ("Beratungsvermögen" / "Anderes Vermögen").
    # Macht sichtbar, dass z.B. Mieterträge aus 'Anderem Vermögen' stammen, das in
    # der Beratungs-/Allokationsansicht NICHT auftaucht — sonst wirkt eine Einnahme
    # ohne sichtbare Quelle.
    origin_assignment: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _rate_amount(value_rappen: int | None, rate_bps: int | None) -> int:
    """Periodenbetrag aus Kapital * Satz (bps). Vorzeichen-neutral (abs)."""
    v = abs(int(value_rappen or 0))
    r = int(rate_bps or 0)
    if v == 0 or r == 0:
        return 0
    return int(round(v * r / 10000.0))


REFINANCE_RATE_BPS = 300        # nach Ablauf/SARON-Frist mit 3% rechnen (User-Vorgabe 2026-06-14)
SARON_FIXED_YEARS = 5           # SARON: aktueller Satz 5 Jahre, danach 3%


def _is_direct_amortization(amortization_type) -> bool:
    # ACHTUNG: "indirekt" enthält den Substring "direkt" — daher zuerst ausschliessen.
    t = str(amortization_type or "").strip().lower()
    if "indirekt" in t or "indirect" in t:
        return False
    return "direkt" in t or "direct" in t


def _is_saron(mortgage_type) -> bool:
    t = str(mortgage_type or "").strip().lower()
    return "saron" in t or "variabel" in t or "variable" in t


def _year_of(date_str) -> int | None:
    s = str(date_str or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def _convert_position_rappen(
    amount_rappen: int,
    position,
    fx_source,
    target_currency: str,
) -> int:
    amount = int(amount_rappen or 0)
    if amount == 0:
        return amount
    source_currency = str(
        getattr(position, "currency", "") or "CHF"
    ).upper().strip()
    target = str(target_currency or "CHF").upper().strip()
    if source_currency == target:
        return amount
    if fx_source is None:
        raise ValueError(
            f"Keine FX-Quelle fuer Hypothekenpfad "
            f"{source_currency}->{target}; eine stille 1:1-Konvertierung "
            "ist nicht zulaessig."
        )
    try:
        rate = float(fx_source.cross_rate(source_currency, target))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Fehlender FX-Kurs {source_currency}/{target} für Hypothekenpfad."
        ) from exc
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError(
            f"Ungueltiger FX-Kurs {source_currency}/{target} fuer "
            f"Hypothekenpfad: {rate}."
        )
    return int(round(amount * rate))


def mortgage_interest_schedule(
    *,
    debt_rappen: int,
    rate_bps: int,
    amortization_rappen: int = 0,
    amortization_type=None,
    mortgage_type=None,
    maturity_date=None,
    horizon_years: int,
    start_year: int,
    refinance_rate_bps: int = REFINANCE_RATE_BPS,
    saron_fixed_years: int = SARON_FIXED_YEARS,
) -> list[int]:
    """Jahres-Hypothekarzins (Rappen) über ``horizon_years`` ab ``start_year``.

    Fachlogik (User-Entscheid 2026-06-14):
      • Direkte Amortisation reduziert die Schuld jährlich (Floor 0) → sinkender
        Zins. Indirekte Amortisation lässt die Schuld unverändert (fliesst in 3a).
      • Zinssatz: aktueller ``rate_bps`` bis zum Ablauf (Fix-Hypothek: bis
        ``maturity_date``; SARON/variabel: ``saron_fixed_years`` Jahre), danach
        ``refinance_rate_bps`` (3%). Ohne maturity_date bei Fix: aktueller Satz
        bleibt (kein Cutover).

    Reine Funktion (keine DB/Seiteneffekte) — Fundament für die Projektions-
    Integration (Schritt B). Index i = Jahr ``start_year + i``.
    """
    debt0 = abs(int(debt_rappen or 0))
    base_rate = int(rate_bps or 0)
    amort = abs(int(amortization_rappen or 0)) if _is_direct_amortization(amortization_type) else 0
    n = max(0, int(horizon_years or 0))
    saron = _is_saron(mortgage_type)
    maturity_year = _year_of(maturity_date)

    schedule: list[int] = []
    for i in range(n):
        year = int(start_year) + i
        # Schuld zu Jahresbeginn (direkte Amortisation reduziert linear, Floor 0).
        debt_i = max(0, debt0 - amort * i)
        # Zinssatz dieses Jahres.
        if saron:
            rate_i = base_rate if i < int(saron_fixed_years) else int(refinance_rate_bps)
        elif maturity_year is not None:
            rate_i = base_rate if year <= maturity_year else int(refinance_rate_bps)
        else:
            rate_i = base_rate  # Fix ohne Ablaufdatum: aktueller Satz bleibt
        schedule.append(int(round(debt_i * rate_i / 10000.0)))
    return schedule


def mortgage_interest_adjustment_series(
    positions: list,
    horizon_years: int,
    start_year: int,
    *,
    fx_source=None,
    target_currency: str = "CHF",
) -> list[int]:
    """Jahres-Anpassung der Zinslast für die PROJEKTION (Rappen, additiv auf das
    Netto-Cashflow-Series). Pro Jahr i: Summe über Hypotheken von
    (Zins_heute − Zins_Jahr_i). Positiv = weniger Zinslast (direkte Amortisation
    baut Schuld ab), negativ = mehr (Refinanzierung auf 3% nach Ablauf/SARON-Frist).

    Der statische 'heutige' Hypothekarzins (= schedule[0]) steckt bereits im
    Cashflow-Series; diese Serie korrigiert ihn jahresabhängig, ohne die
    heutige Cashflow-Ansicht/Summe zu verändern."""
    n = max(0, int(horizon_years or 0))
    adj = [0] * n
    if n == 0:
        return adj
    for pos in positions or []:
        if getattr(pos, "deleted_at", None):
            continue
        if int(getattr(pos, "is_active", 1) or 0) != 1:
            continue
        if str(getattr(pos, "position_type", "") or "") != "Hypothek":
            continue
        s = mortgage_interest_schedule(
            debt_rappen=getattr(pos, "current_value_rappen", 0),
            rate_bps=getattr(pos, "mortgage_interest_rate_bps", 0),
            amortization_rappen=getattr(pos, "mortgage_amortization_rappen", 0),
            amortization_type=getattr(pos, "mortgage_amortization_type", None),
            mortgage_type=getattr(pos, "mortgage_type", None),
            maturity_date=getattr(pos, "mortgage_maturity_date", None),
            horizon_years=n, start_year=start_year,
        )
        if not s:
            continue
        base = s[0]  # entspricht dem statischen 'heutigen' Hypothekarzins
        for i in range(n):
            adj[i] += _convert_position_rappen(
                base - s[i],
                pos,
                fx_source,
                target_currency,
            )
    return adj


def mortgage_amortization_adjustment_series(
    positions: list,
    horizon_years: int,
    *,
    fx_source=None,
    target_currency: str = "CHF",
) -> list[int]:
    """Correct the recurring direct-amortization cashflow after payoff.

    ``derive_wealth_cashflows`` exposes the entered annual amount so the
    current cashflow view stays transparent.  A direct mortgage can, however,
    pay at most its remaining principal.  This series is added to the negative
    base cashflow and therefore contains the positive overstatement to reverse.
    Indirect amortization remains a recurring transfer into the pledged-asset
    series and is deliberately not capped here.
    """
    n = max(0, int(horizon_years or 0))
    adjustment = [0] * n
    for pos in positions or []:
        if getattr(pos, "deleted_at", None):
            continue
        if int(getattr(pos, "is_active", 1) or 0) != 1:
            continue
        if str(getattr(pos, "position_type", "") or "") != "Hypothek":
            continue
        if not _is_direct_amortization(
            getattr(pos, "mortgage_amortization_type", None)
        ):
            continue
        debt = abs(int(getattr(pos, "current_value_rappen", 0) or 0))
        annual = abs(
            int(getattr(pos, "mortgage_amortization_rappen", 0) or 0)
        )
        if annual <= 0:
            continue
        remaining = debt
        for index in range(n):
            actual_payment = min(annual, remaining)
            adjustment[index] += _convert_position_rappen(
                annual - actual_payment,
                pos,
                fx_source,
                target_currency,
            )
            remaining -= actual_payment
    return adjustment


def derive_wealth_cashflows(positions: list) -> list[DerivedCashflow]:
    """Erzeugt die abgeleiteten Cashflows für eine Liste von Vermögenspositionen.

    Nur aktive (is_active==1, deleted_at is None) Positionen. Nur Posten mit
    echtem Betrag > 0 werden erzeugt (kein Rauschen)."""
    out: list[DerivedCashflow] = []
    for pos in positions or []:
        if getattr(pos, "deleted_at", None):
            continue
        if int(getattr(pos, "is_active", 1) or 0) != 1:
            continue
        ptype = str(getattr(pos, "position_type", "") or "")
        pid = str(getattr(pos, "id", "") or "")
        cid = str(getattr(pos, "client_id", "") or "")
        label = str(getattr(pos, "label", "") or "").strip() or ptype or "Position"
        currency = str(getattr(pos, "currency", "") or "CHF")
        vfrom = getattr(pos, "valuation_date", None)
        value = int(getattr(pos, "current_value_rappen", 0) or 0)
        assignment = str(getattr(pos, "assignment", "") or "").strip() or None

        def _mk(suffix: str, cf_type: str, amount: int, text: str, inflation_linked: int = 0) -> None:
            if amount <= 0:
                return
            out.append(DerivedCashflow(
                id=f"derived:{suffix}:{pid}",
                client_id=cid,
                cashflow_type=cf_type,
                label=text,
                amount_rappen=amount,
                currency=currency,
                valid_from=vfrom,
                is_inflation_linked=1 if inflation_linked else 0,
                origin_position_id=pid,
                origin_position_type=ptype,
                origin_assignment=assignment,
            ))

        if is_mortgage_position(ptype):
            _mk("mortgage_interest", "Expense",
                _rate_amount(value, getattr(pos, "mortgage_interest_rate_bps", 0)),
                f"Hypothekarzins: {label}")
            _mk("mortgage_amortization", "Expense",
                abs(int(getattr(pos, "mortgage_amortization_rappen", 0) or 0)),
                f"Amortisation: {label}")
        elif is_direct_real_estate_position(ptype):
            # Mieteinnahme nur ableiten, wenn die Liegenschaft auch einen Wert > 0 hat.
            # Sonst entstünde Einkommen ohne Substanz (Wert 0 + Miete = Dateneingabe-
            # Fehler / Inkonsistenz): die IST-Cashflow-Projektion zeigte Mieterträge,
            # während Gesamt-/Beratungsvermögen die Liegenschaft mit 0 führen.
            if value > 0:
                _mk("rental_income", "Income",
                    abs(int(getattr(pos, "property_rental_income_rappen", 0) or 0)),
                    f"Mieteinnahmen: {label}",
                    inflation_linked=int(getattr(pos, "property_rental_inflation_linked", 0) or 0))
        elif is_liquidity_position(ptype):
            interest = _rate_amount(value, getattr(pos, "liquidity_interest_rate_bps", 0))
            if interest >= 0:
                _mk("liquidity_interest", "Income", interest,
                    f"Zinsertrag: {label}")
            else:
                # Negativzins / Verwahrungsentgelt (wie 2015-2022 bei CH-Banken auf
                # Bar-/Depotguthaben): ein negativer Satz ist eine Ausgabe, kein Ertrag.
                # Ohne diese Verzweigung wuerde _mk() den negativen Betrag als
                # "Rauschen" (amount <= 0) verwerfen -> Negativzins wuerde nie berechnet.
                _mk("liquidity_interest", "Expense", abs(interest),
                    f"Negativzins: {label}")

    return out


def derive_tax_cashflow(mandate, total_wealth_rappen: int) -> list[DerivedCashflow]:
    """Roadmap #39 (Standpunkt 2026-08-07): geschaetzte Vermoegenssteuer als
    optionale, abgeleitete jaehrliche Ausgabe in der deterministischen
    Cashflow-Projektion/Reserve-Berechnung.

    Opt-in ueber mandate.tax_estimate_in_cashflow_enabled (Default 0 =
    Backwards-Compat, kein Verhalten fuer Bestandsmandate).

    Nutzt DENSELBEN Tax-Regime-Resolver wie der steuer-bewusste Optimizer-
    Solver-Pfad (services.portfolio_engine_optimizer_integration.
    _build_tax_solver_kwargs) -- Kanton-Override (tax_jurisdiction='CH-GE')
    und manuelle tax_overrides_json wirken hier identisch, statt eine
    zweite, potenziell abweichende Resolution-Logik zu bauen.

    Scope bewusst NUR Vermoegenssteuer, NICHT Erwerbseinkommensteuer: das
    CH-Tax-Modul (services/tax/regimes/ch.py) bildet explizit "Pauschal-
    Mittelwerte fuer Asset-Allocation-Wirkung" ab, keine progressive
    Einkommenssteuer-Tabelle -- eine "geschaetzte Einkommensteuer" waere ohne
    echte Tarif-Stufen/Abzuege irrefuehrend genauer als sie tatsaechlich ist.

    Liefert eine leere Liste wenn: Flag aus, kein Vermoegen, keine
    tax_jurisdiction gesetzt oder das explizit konfigurierte Regime keine
    Vermoegenssteuer unterstuetzt. Eine konfigurierte, aber nicht aufloesbare
    Steuerbasis ist dagegen ein Domainfehler und wird bewusst nicht als
    steuerfreier Cashflow verschluckt (identisch zum Solver-Pfad)."""
    if not int(getattr(mandate, "tax_estimate_in_cashflow_enabled", 0) or 0):
        return []
    # Resolve the activated tax basis before wealth-dependent early returns.
    # Zero wealth must not hide a persisted, unusable opt-in configuration.
    from services.portfolio_engine_optimizer_integration import _build_tax_solver_kwargs

    tax_kwargs = _build_tax_solver_kwargs(mandate)
    wealth = int(total_wealth_rappen or 0)
    if wealth <= 0:
        return []
    regime = tax_kwargs.get("tax_regime")
    if regime is None or not getattr(regime, "supports_wealth_tax", False):
        return []
    from services.tax.base import TaxContext

    ctx = TaxContext(
        year_index=0,
        calendar_year=int(tax_kwargs.get("base_calendar_year", 0)) or 2026,
        wealth_rappen=float(wealth),
        age=None,
    )
    result = regime.annual_wealth_tax(ctx)
    amount = int(round(result.amount_rappen))
    if amount <= 0:
        return []
    mandate_id = str(getattr(mandate, "id", "") or "")
    return [DerivedCashflow(
        id=f"derived:wealth_tax:{mandate_id}",
        client_id=str(getattr(mandate, "client_id", "") or ""),
        cashflow_type="Expense",
        label=f"Vermögenssteuer (geschätzt, {getattr(regime, 'display_name', 'Pauschal')})",
        amount_rappen=amount,
        currency=str(getattr(mandate, "base_currency", "") or "CHF"),
        source="tax_estimate",
        origin_position_id=None,
        origin_position_type="TaxEstimate",
        notes=(
            "Pauschale Schaetzung auf Basis des aktuellen Gesamtvermoegens "
            "(kein progressiver Tarif, keine Erwerbseinkommensteuer). "
            "Kann von der tatsaechlichen Steuerrechnung abweichen."
        ),
    )]
