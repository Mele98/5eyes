"""K1 / CK-01: Kundensummen des Vermoegens ueber die strikte P3-FX-Basis.

Vorher summierte ``v_client_wealth_summary`` die Positionsbetraege nominal ueber
alle Waehrungen (CHF 400'000 + USD 100'000 = "500'000" unter ``*_chf``). Die
Summen entstehen jetzt im Python-Pfad: jede aktive Position wird zeilenweise
mit EINER gebundenen, strikten FX-Basis (``services.fx_basis``, dieselbe Quelle
wie Cashflow-Summary, Allokation und PDF) in die Zielwaehrung konvertiert und
erst danach addiert. Die View bleibt unveraendert bestehen (keine
Schemaaenderung); sie wird fuer Betraege nicht mehr gelesen.

Zielwaehrung (nie still CHF, nie geraten):

1. ``mandate_id`` -> Mandatswaehrung (Mandat muss zum Kunden gehoeren);
2. ``target_currency`` -> diese Waehrung;
3. alle aktiven Positionen in derselben belegten Waehrung -> diese Waehrung,
   ohne Umrechnung (Einwaehrungsfall unveraendert);
4. gemischte Waehrungen -> Kunden-Basiswaehrung = die eindeutige
   Basiswaehrung der (aktiven) Mandate des Kunden;
5. sonst ``CCX_FX_BASIS_MISMATCH`` (Mandatskontext/Zielwaehrung noetig).

Fehlt ein belegter Kurs, ist er abgelaufen oder ein Ersatzkurs (Quelle
``Default``), endet der Aufruf typisiert (``CCX_FX_BASIS_MISSING|STALE``). Ein
Nominalwert gemischter Waehrungen wird nie ausgegeben.

Klassifikation identisch zur bisherigen View: Verbindlichkeit genau bei
``assignment = 'Verbindlichkeit'``, Beratungsvermoegen genau bei
``assignment = 'Beratungsvermögen'``, Brutto = alle uebrigen Positionen mit
gesetzter Zuordnung.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from core.reason_codes import DomainError, ReasonCode
from services.fx_basis import FxBasis, load_fx_basis, normalize_currency

LIABILITY_ASSIGNMENT = "Verbindlichkeit"
ADVISORY_ASSIGNMENT = "Beratungsvermögen"
ACTIVE_MANDATE_STATUS = "Aktiv"


@dataclass(frozen=True)
class WealthTotals:
    gross_wealth_rappen: int
    liabilities_rappen: int
    advisory_wealth_rappen: int
    amount_currency: str | None
    fx_basis_hash: str
    valuation_as_of: str

    @property
    def net_worth_rappen(self) -> int:
        return self.gross_wealth_rappen - self.liabilities_rappen


def active_position_currencies(positions: Iterable[Any]) -> set[str]:
    return {normalize_currency(getattr(p, "currency", None)) for p in positions}


def client_base_currency(mandates: Iterable[Any]) -> str:
    """Eindeutige Basiswaehrung der Mandate eines Kunden (aktive bevorzugt).

    Kein Mandat oder mehrere Basiswaehrungen -> ``CCX_FX_BASIS_MISMATCH``: die
    Summe braucht dann einen ausdruecklichen Mandatskontext."""
    rows = [m for m in mandates if not getattr(m, "deleted_at", None)]
    active = [m for m in rows if str(getattr(m, "status", "") or "") == ACTIVE_MANDATE_STATUS]
    pool = active or rows
    currencies = {normalize_currency(getattr(m, "base_currency", None)) for m in pool} - {""}
    if len(currencies) != 1:
        raise DomainError(
            ReasonCode.CCX_FX_BASIS_MISMATCH,
            "Die Vermoegenspositionen liegen in verschiedenen Waehrungen vor und der Kunde hat "
            "keine eindeutige Mandatswaehrung; fuer eine Summe ist ein Mandatskontext "
            "(mandate_id) oder eine Zielwaehrung (target_currency) erforderlich.",
            extra={"currencies": sorted(currencies)},
        )
    return next(iter(currencies))


def resolve_summary_currency(
    positions: list[Any],
    mandates: Iterable[Any],
    *,
    mandate_currency: str | None = None,
    target_currency: str | None = None,
) -> str:
    """Zielwaehrung nach der Rangfolge im Modul-Docstring."""
    if mandate_currency:
        return normalize_currency(mandate_currency)
    if target_currency:
        return normalize_currency(target_currency)
    currencies = active_position_currencies(positions)
    if len(currencies) <= 1 and "" not in currencies:
        if currencies:
            return next(iter(currencies))
        return client_base_currency_or_none(mandates) or "CHF"
    return client_base_currency(mandates)


def client_base_currency_or_none(mandates: Iterable[Any]) -> str | None:
    try:
        return client_base_currency(mandates)
    except DomainError:
        return None


def summarize_positions(positions: Iterable[Any], basis: FxBasis) -> WealthTotals:
    """Zeilenweise konvertieren, erst danach summieren (fail-closed)."""
    gross = liabilities = advisory = 0
    for position in positions:
        assignment = getattr(position, "assignment", None)
        if assignment is None:
            continue  # wie die View: NULL-Zuordnung zaehlt nirgends
        amount = basis.convert(
            int(getattr(position, "current_value_rappen", 0) or 0),
            getattr(position, "currency", None),
        ).converted_amount_minor
        if assignment == LIABILITY_ASSIGNMENT:
            liabilities += amount
        else:
            gross += amount
            if assignment == ADVISORY_ASSIGNMENT:
                advisory += amount
    return WealthTotals(
        gross_wealth_rappen=gross,
        liabilities_rappen=liabilities,
        advisory_wealth_rappen=advisory,
        amount_currency=basis.target_currency,
        fx_basis_hash=basis.fx_basis_hash,
        valuation_as_of=basis.as_of,
    )


def compute_wealth_totals(
    db: Any,
    positions: list[Any],
    mandates: Iterable[Any],
    *,
    mandate_currency: str | None = None,
    target_currency: str | None = None,
    tenant_id: Any = None,
) -> WealthTotals:
    """Kundensummen in der aufgeloesten Zielwaehrung (typisierter Block bei
    fehlender/abgelaufener/ersetzter FX-Basis)."""
    mandates = list(mandates)
    summary_currency = resolve_summary_currency(
        positions, mandates, mandate_currency=mandate_currency, target_currency=target_currency,
    )
    currencies = active_position_currencies(positions)
    basis = load_fx_basis(db, summary_currency, currencies - {""}, tenant_id=tenant_id)
    basis.require_convertible(currencies)
    totals = summarize_positions(positions, basis)
    if not positions and not mandate_currency and not target_currency:
        # Ohne Positionen gibt es keine Betragswaehrung (wie bisher: Anzeige "—").
        return WealthTotals(0, 0, 0, None, totals.fx_basis_hash, totals.valuation_as_of)
    return totals


__all__ = [
    "WealthTotals",
    "client_base_currency",
    "compute_wealth_totals",
    "resolve_summary_currency",
    "summarize_positions",
]
