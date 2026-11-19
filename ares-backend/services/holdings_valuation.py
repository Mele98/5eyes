"""CCX-P3 Markt- und Depot-Wahrheit: verlustfreie Bewertung eines Mandats.

Vertrag 2026-11-13 §6 (inkl. Nachtrag P3-FX). Ein Bewertungs-Snapshot haelt
zu einem Stichtag fest:

* jede aktive Vermoegensposition des Kunden (inkl. Verbindlichkeit, Vorsorge,
  Immobilie) und jede Depotposition des massgebenden Laufs als eigene Zeile --
  nichts faellt weg. Nicht uebernommene Altbestaende frueherer Laeufe
  erscheinen als ``NOT_CARRIED_OVER``;
* je Zeile Originalbetrag und -waehrung, Kurs (Verhaeltnis + ppm), Kursquelle,
  Beobachtungszeitpunkte (Bewertung/Preis und Kurs) und den in die
  Mandatswaehrung konvertierten Wert -- unbekannt bleibt ``None``, nie 0;
* genau eine FX-Basis (``fx_basis_hash``) fuer Positionen, Cashflows und
  Vermoegenszufluesse;
* ``coverage_status``: COMPLETE nur, wenn jede Zeile sauber bewertet ist und
  jede Waehrung der Aussage einen belegten, frischen Kurs hat; bekannte Werte
  mit Befund (Doppelerfassung eines Depots) PARTIAL; sonst UNKNOWN.

Leerer Bestand ist nur mit ausdruecklicher Bestaetigung "kein Bestand /
Neugeld" zulaessig, und auch dann nur, wenn Cashflows oder Zufluesse
erfasst sind (Mindestregel). Kein Depot-/Markt-Claim ohne COMPLETE: nur ein
COMPLETE-Snapshot traegt Gesamt- und Beratungsvermoegen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.advisory_envelope_codec import child_hash, utc_now
from core.reason_codes import DomainError, ReasonCode
from database import new_uuid
from models.review import PriceHistory, Product, RecommendationPosition
from models.snapshots import (
    HOLDINGS_VALUATION_SCHEMA_VERSION,
    HoldingsValuationRow,
    HoldingsValuationSnapshot,
)
from models.wealth import Cashflow, WealthInflow, WealthPosition
from services.fx_basis import (
    MARKET_DATA_STALE_AFTER_DAYS,
    STATUS_MISMATCH,
    STATUS_OK,
    STATUS_STALE,
    FxBasis,
    FxBasisError,
    load_fx_basis,
    normalize_currency,
    resolve_as_of,
)
from services.portfolio_engine_live_rebalancing import (
    _latest_holdings_by_product_for_mandate,
    current_run_holdings,
    holdings_not_carried_over,
)
from services.recommendation_position_ledger import decide_positions, ledger_child_hash, missing_decisions
from services.valuation_completeness import COMPLETE, PARTIAL, UNKNOWN, coverage_from_qualities

SNAPSHOT_KIND = "holdings-valuation"
ROW_KIND = "holdings-valuation-row"
SOURCE_MANUAL = "manual_valuation"
SOURCE_MARKET = "market_data"
BASIS_RECORDED = "recorded"
BASIS_CONFIRMED_EMPTY = "confirmed_no_holdings"

ADVISORY_ASSIGNMENT = "Beratungsvermögen"
LIABILITY_ASSIGNMENT = "Verbindlichkeit"

Q_OK = "OK"
Q_MISSING_VALUATION_DATE = "MISSING_VALUATION_DATE"
Q_FUTURE_VALUATION_DATE = "FUTURE_VALUATION_DATE"
Q_MISSING_CURRENCY = "MISSING_CURRENCY"
Q_MISSING_FX = "MISSING_FX"
Q_STALE_FX = "STALE_FX"
Q_FX_MISMATCH = "FX_MISMATCH"
Q_MISSING_PRICE = "MISSING_PRICE"
Q_STALE_PRICE = "STALE_PRICE"
Q_MISSING_QUANTITY = "MISSING_QUANTITY"
Q_MISSING_INSTRUMENT = "MISSING_INSTRUMENT"
Q_DUPLICATE_DEPOT = "DUPLICATE_DEPOT"
Q_NOT_CARRIED_OVER = "NOT_CARRIED_OVER"
Q_STALE_VALUATION = "STALE_VALUATION"

# Qualitaeten mit bekanntem Wert (nur Befund, Wert bleibt sichtbar).
_VALUE_KNOWN = frozenset({Q_OK, Q_DUPLICATE_DEPOT})

# Vorrang des primaeren Blocker-Codes.
_CODE_ORDER = (
    ReasonCode.CCX_VALUATION_MISSING,
    ReasonCode.CCX_FX_BASIS_MISSING,
    ReasonCode.CCX_VALUATION_INCOMPLETE,
    ReasonCode.CCX_FX_BASIS_MISMATCH,
    ReasonCode.CCX_FX_BASIS_STALE,
    ReasonCode.CCX_VALUATION_STALE,
)


class ValuationError(DomainError):
    """Bewertung nicht publizierbar (``CCX_VALUATION_*`` / ``CCX_FX_BASIS_*``)."""

    channel = "holdings_valuation"


def quality_reason(quality: str) -> ReasonCode:
    """Katalogisierter Code einer Zeilenqualitaet (statisch aufloesbar)."""
    if quality in (Q_MISSING_CURRENCY, Q_MISSING_FX):
        return ReasonCode.CCX_FX_BASIS_MISSING
    if quality == Q_STALE_FX:
        return ReasonCode.CCX_FX_BASIS_STALE
    if quality == Q_FX_MISMATCH:
        return ReasonCode.CCX_FX_BASIS_MISMATCH
    if quality in (Q_STALE_PRICE, Q_STALE_VALUATION):
        return ReasonCode.CCX_VALUATION_STALE
    return ReasonCode.CCX_VALUATION_INCOMPLETE


def primary_reason(codes: Iterable[str]) -> ReasonCode:
    """Primaerer Blocker in fester Vorrangfolge (``_CODE_ORDER``)."""
    present = set(codes)
    if ReasonCode.CCX_VALUATION_MISSING.value in present:
        return ReasonCode.CCX_VALUATION_MISSING
    if ReasonCode.CCX_FX_BASIS_MISSING.value in present:
        return ReasonCode.CCX_FX_BASIS_MISSING
    if ReasonCode.CCX_VALUATION_INCOMPLETE.value in present:
        return ReasonCode.CCX_VALUATION_INCOMPLETE
    if ReasonCode.CCX_FX_BASIS_MISMATCH.value in present:
        return ReasonCode.CCX_FX_BASIS_MISMATCH
    if ReasonCode.CCX_FX_BASIS_STALE.value in present:
        return ReasonCode.CCX_FX_BASIS_STALE
    if ReasonCode.CCX_VALUATION_STALE.value in present:
        return ReasonCode.CCX_VALUATION_STALE
    if ReasonCode.CCX_VALUATION_ATTESTATION_REQUIRED.value in present:
        return ReasonCode.CCX_VALUATION_ATTESTATION_REQUIRED
    return ReasonCode.CCX_VALUATION_INCOMPLETE


def _fx_quality(status: str) -> str:
    if status == STATUS_STALE:
        return Q_STALE_FX
    if status == STATUS_MISMATCH:
        return Q_FX_MISMATCH
    return Q_MISSING_FX


def _canonical(body: Any) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _date(value: Any) -> date | None:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw[:10]) if len(raw) >= 10 else None
    except ValueError:
        return None


def _half_up_div(numerator: int, denominator: int) -> int:
    negative = numerator < 0
    q, r = divmod(abs(numerator), denominator)
    if 2 * r >= denominator:
        q += 1
    return -q if negative and q else q


def _quantity_text(units_milli: int) -> str:
    whole, frac = divmod(int(units_milli), 1000)
    return f"{whole}.{frac:03d}".rstrip("0").rstrip(".") if frac else str(whole)


def _norm_assignment(value: Any) -> str:
    text = str(value or "").strip()
    return ADVISORY_ASSIGNMENT if text == "Beratungsvermoegen" else text


@dataclass
class ValuationRowData:
    position_id: str
    source_kind: str
    instrument_id: str | None
    assignment: str | None
    quantity_decimal_string: str | None
    price_minor: int | None
    price_currency: str | None
    source_amount_minor: int | None
    fx_rate_ppm: int | None
    fx_rate_ratio: str | None
    fx_source: str | None
    fx_observed_at: str | None
    base_value_minor: int | None
    price_observed_at: str | None
    data_quality: str
    included_in_total: int
    label: str | None = None
    row_hash: str = ""

    def hash_body(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "source_kind": self.source_kind,
            "instrument_id": self.instrument_id,
            "assignment": self.assignment,
            "quantity_decimal_string": self.quantity_decimal_string,
            "price_minor": self.price_minor,
            "price_currency": self.price_currency,
            "source_amount_minor": self.source_amount_minor,
            "fx_rate_ppm": self.fx_rate_ppm,
            "fx_rate_ratio": self.fx_rate_ratio,
            "fx_source": self.fx_source,
            "fx_observed_at": self.fx_observed_at,
            "base_value_minor": self.base_value_minor,
            "price_observed_at": self.price_observed_at,
            "data_quality": self.data_quality,
            "included_in_total": self.included_in_total,
        }

    def seal(self) -> None:
        self.row_hash = child_hash(ROW_KIND, _canonical(self.hash_body()))

    def view(self) -> dict[str, Any]:
        return {**self.hash_body(), "label": self.label, "row_hash": self.row_hash}


@dataclass
class ValuationProjection:
    tenant_id: str | None
    mandate_id: str
    as_of: str
    base_currency: str
    fx_basis: FxBasis
    rows: list[ValuationRowData]
    coverage_status: str
    holdings_basis: str
    blocker_codes: list[str]
    flow_blockers: list[dict[str, Any]] = field(default_factory=list)
    source_system: str = SOURCE_MANUAL
    source_observed_at: str | None = None
    total_base_minor: int | None = None
    advisory_base_minor: int | None = None
    manual_valuation_attested: bool = False
    manual_valuation_max_age_days: int | None = None
    snapshot_hash: str = ""

    @property
    def fx_basis_hash(self) -> str:
        return self.fx_basis.fx_basis_hash

    @property
    def position_count(self) -> int:
        return len(self.rows)

    @property
    def publishable(self) -> bool:
        return self.coverage_status == COMPLETE and not self.blocker_codes

    def hash_body(self) -> dict[str, Any]:
        return {
            "schema_version": HOLDINGS_VALUATION_SCHEMA_VERSION,
            "tenant_id": self.tenant_id,
            "mandate_id": self.mandate_id,
            "as_of": self.as_of,
            "source_observed_at": self.source_observed_at,
            "source_system": self.source_system,
            "base_currency": self.base_currency,
            "fx_basis_hash": self.fx_basis_hash,
            "coverage_status": self.coverage_status,
            "holdings_basis": self.holdings_basis,
            "position_count": self.position_count,
            "total_base_minor": self.total_base_minor,
            "advisory_base_minor": self.advisory_base_minor,
            "blocker_codes": sorted(self.blocker_codes),
            "manual_valuation_attested": bool(self.manual_valuation_attested),
            "manual_valuation_max_age_days": self.manual_valuation_max_age_days,
            "rows": [r.row_hash for r in sorted(self.rows, key=lambda r: (r.source_kind, r.position_id))],
        }

    def view(self) -> dict[str, Any]:
        return {
            "schema_version": HOLDINGS_VALUATION_SCHEMA_VERSION,
            "mandate_id": self.mandate_id,
            "as_of": self.as_of,
            "source_observed_at": self.source_observed_at,
            "source_system": self.source_system,
            "base_currency": self.base_currency,
            "coverage_status": self.coverage_status,
            "holdings_basis": self.holdings_basis,
            "position_count": self.position_count,
            "total_base_minor": self.total_base_minor,
            "advisory_base_minor": self.advisory_base_minor,
            "blocker_codes": sorted(self.blocker_codes),
            "reason_code": str(primary_reason(self.blocker_codes)) if self.blocker_codes else None,
            "flow_blockers": list(self.flow_blockers),
            "manual_valuation_attested": bool(self.manual_valuation_attested),
            "manual_valuation_max_age_days": self.manual_valuation_max_age_days,
            "fx_basis_hash": self.fx_basis_hash,
            "fx_basis": self.fx_basis.as_dict(),
            "snapshot_hash": self.snapshot_hash,
            "rows": [r.view() for r in sorted(self.rows, key=lambda r: (r.source_kind, r.position_id))],
        }


# ── Laden ────────────────────────────────────────────────────────────────────


def _wealth_positions(db: Session, client_id: str) -> list[Any]:
    return (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == client_id,
            WealthPosition.is_active == 1,
            WealthPosition.deleted_at.is_(None),
        )
        .order_by(WealthPosition.id.asc())
        .all()
    )


def _flows(db: Session, mandate: Any) -> tuple[list[Any], list[Any]]:
    """Cashflows (aktiv, eingeschlossen) und alle erfassten Zufluesse des
    Mandats -- auch unsichere: ein erfasster Betrag ohne Waehrung ist nie
    gueltig."""
    client_id = str(getattr(mandate, "client_id", "") or "")
    cashflows = (
        db.query(Cashflow)
        .filter(Cashflow.client_id == client_id, Cashflow.is_active == 1, Cashflow.is_included == 1,
                Cashflow.deleted_at.is_(None))
        .all()
    )
    inflows = (
        db.query(WealthInflow)
        .filter(WealthInflow.client_id == client_id, WealthInflow.is_active == 1,
                WealthInflow.deleted_at.is_(None))
        .all()
    )
    inflows = [
        inflow for inflow in inflows
        if not getattr(inflow, "mandate_id", None) or str(inflow.mandate_id) == str(mandate.id)
    ]
    return [cf for cf in cashflows if int(getattr(cf, "amount_rappen", 0) or 0) != 0], inflows


def mandate_has_recorded_depot_holdings(db: Session, mandate_id: str) -> bool:
    """True, sobald fuer das Mandat ein Depotbestand erfasst ist (neueste
    Holding je Produkt mit Stueckzahl oder Marktwert > 0)."""
    return any(
        int(row.units_milli or 0) > 0 or int(row.market_value_rappen or 0) > 0
        for row in _latest_holdings_by_product_for_mandate(db, mandate_id).values()
    )


def tenant_manual_valuation_max_age_days(db: Session, tenant_id: Any) -> int | None:
    """N-909-07: Owner-Frist fuer manuelle Bewertungen; ohne Wert ``None``
    (kein erfundener Default -> Bestaetigungspflicht des Beraters)."""
    if not tenant_id:
        return None
    try:
        value = db.execute(
            text("SELECT manual_valuation_max_age_days FROM tenants WHERE id = :t"), {"t": str(tenant_id)},
        ).scalar()
    except Exception:  # noqa: BLE001 - Altschema ohne Spalte: keine Frist
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def _depot_holdings(db: Session, mandate_id: str) -> tuple[Any, list[Any], list[dict[str, Any]]]:
    run, holdings = current_run_holdings(db, mandate_id)
    held = [h for h in holdings if int(h.units_milli or 0) > 0 or int(h.market_value_rappen or 0) > 0]
    return run, held, holdings_not_carried_over(db, mandate_id)


def _prices_as_of(db: Session, product_ids: list[str], as_of: date) -> dict[str, Any]:
    """Juengster Preis je Produkt mit Preisdatum <= Stichtag (Stichtagsgrenze)."""
    if not product_ids:
        return {}
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id.in_(product_ids), PriceHistory.price_date <= as_of.isoformat())
        .order_by(PriceHistory.product_id.asc(), PriceHistory.price_date.desc(), PriceHistory.fetched_at.desc())
        .all()
    )
    latest: dict[str, Any] = {}
    for row in rows:
        latest.setdefault(row.product_id, row)
    return latest


# ── Projektion ───────────────────────────────────────────────────────────────


def _convert_row(row: ValuationRowData, basis: FxBasis, amount: int, currency: str) -> None:
    """Konvertiert den Originalbetrag; ein unbrauchbarer Kurs macht die Zeile
    unbekannt (Wert None), nie 0."""
    status = basis.status(currency)
    if status != STATUS_OK or (
        currency != basis.target_currency and basis.target_currency != "CHF"
        and basis.statuses.get(basis.target_currency, STATUS_OK) != STATUS_OK
    ):
        bad = status if status != STATUS_OK else basis.statuses.get(basis.target_currency, STATUS_OK)
        row.data_quality = _fx_quality(bad)
        row.base_value_minor = None
        return
    line = basis.convert(amount, currency)
    sign = -1 if row.assignment == LIABILITY_ASSIGNMENT else 1
    row.base_value_minor = sign * line.converted_amount_minor
    row.fx_rate_ppm = line.fx_rate_ppm
    row.fx_rate_ratio = line.fx_rate_ratio
    row.fx_source = line.fx_source
    row.fx_observed_at = line.source_observed_at


def project_holdings_valuation(
    db: Session,
    mandate: Any,
    *,
    as_of: Any = None,
    confirm_no_holdings: bool = False,
    attest_manual_valuations: bool = False,
) -> ValuationProjection:
    """Bewertet den gesamten Bestand des Mandats verlustfrei (ohne Persistenz).

    N-909-07: manuelle Bewertungen (Vermoegenspositionen) folgen der Owner-Frist
    ``tenants.manual_valuation_max_age_days`` (aelter -> STALE_VALUATION). Ohne
    Owner-Frist ist die Bestaetigung "Bewertung aktuell" des Beraters Pflicht
    (``attest_manual_valuations``), sonst ``CCX_VALUATION_ATTESTATION_REQUIRED``."""
    as_of_date = resolve_as_of(as_of)
    base_currency = normalize_currency(getattr(mandate, "base_currency", None))
    client_id = str(getattr(mandate, "client_id", "") or "")
    positions = _wealth_positions(db, client_id)
    cashflows, inflows = _flows(db, mandate)
    run, holdings, not_carried = _depot_holdings(db, str(mandate.id))
    product_ids = sorted({h.product_id for h in holdings if h.product_id})
    products = {
        p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}
    prices = _prices_as_of(db, product_ids, as_of_date)

    currencies = {normalize_currency(getattr(p, "currency", None)) for p in positions}
    currencies |= {normalize_currency(getattr(p, "currency", None)) for p in products.values()}
    currencies |= {normalize_currency(getattr(cf, "currency", None)) for cf in cashflows}
    currencies |= {normalize_currency(getattr(i, "currency", None)) for i in inflows}
    try:
        basis = load_fx_basis(db, base_currency, currencies - {""}, as_of=as_of_date,
                              tenant_id=getattr(mandate, "tenant_id", None))
    except FxBasisError:
        # Mehrdeutige aktive Kurse: keine Basis -> alles Fremde unbekannt.
        basis = load_fx_basis(db, base_currency, set(), as_of=as_of_date)
        basis = FxBasis(base_currency, basis.as_of, (), basis.fx_basis_hash,
                        {c: STATUS_MISMATCH for c in currencies - {"", base_currency}})

    rows: list[ValuationRowData] = []
    observed: list[str] = []
    depot_keys: dict[tuple[str, str], list[ValuationRowData]] = {}
    for pos in positions:
        assignment = _norm_assignment(getattr(pos, "assignment", None))
        currency = normalize_currency(getattr(pos, "currency", None))
        amount = int(getattr(pos, "current_value_rappen", 0) or 0)
        # Stichtagspolitik manuelle Bewertung (Tier 1, Live-Feeds aus): Beleg ist
        # der erfasste Bewertungsstichtag, sonst der Erfassungs-/Aenderungs-
        # zeitpunkt der Position (der Berater hat den Wert dann erfasst bzw.
        # bestaetigt). Ein Wert nach dem Stichtag ist zeitlich inkonsistent.
        valuation_date = _date(getattr(pos, "valuation_date", None)) or _date(getattr(pos, "updated_at", None))
        row = ValuationRowData(
            position_id=str(pos.id), source_kind="wealth_position", instrument_id=None,
            assignment=assignment or None, quantity_decimal_string=None, price_minor=amount,
            price_currency=currency or None, source_amount_minor=amount, fx_rate_ppm=None,
            fx_rate_ratio=None, fx_source=None, fx_observed_at=None, base_value_minor=None,
            price_observed_at=valuation_date.isoformat() if valuation_date else None,
            data_quality=Q_OK, included_in_total=1, label=str(getattr(pos, "label", "") or "") or None,
        )
        if not currency:
            row.data_quality = Q_MISSING_CURRENCY
        elif valuation_date is None:
            row.data_quality = Q_MISSING_VALUATION_DATE
        elif valuation_date > as_of_date:
            row.data_quality = Q_FUTURE_VALUATION_DATE
        else:
            _convert_row(row, basis, amount, currency)
            observed.append(valuation_date.isoformat())
        bank = str(getattr(pos, "depot_bank", "") or "").strip().casefold()
        account = str(getattr(pos, "depot_account_number", "") or "").replace(" ", "").casefold()
        if bank and account:
            depot_keys.setdefault((bank, account), []).append(row)
        rows.append(row)
    manual_max_age = tenant_manual_valuation_max_age_days(db, getattr(mandate, "tenant_id", None)) \
        if positions else None
    if manual_max_age is not None:
        manual_limit = as_of_date - timedelta(days=manual_max_age)
        for row in rows:
            observed_row = _date(row.price_observed_at)
            if row.data_quality == Q_OK and observed_row is not None and observed_row < manual_limit:
                row.data_quality = Q_STALE_VALUATION
    for duplicates in depot_keys.values():
        if len(duplicates) > 1:
            for row in duplicates:
                if row.data_quality == Q_OK:
                    row.data_quality = Q_DUPLICATE_DEPOT

    stale_limit = as_of_date - timedelta(days=MARKET_DATA_STALE_AFTER_DAYS)
    for holding in holdings:
        product = products.get(holding.product_id)
        units = int(holding.units_milli or 0)
        price = prices.get(holding.product_id)
        price_currency = normalize_currency(getattr(product, "currency", None)) if product else ""
        price_date = _date(getattr(price, "price_date", None)) if price is not None else None
        price_minor = int(price.price_rappen) if price is not None and price.price_rappen else None
        row = ValuationRowData(
            position_id=str(holding.id), source_kind="depot_holding",
            instrument_id=str(holding.product_id) if holding.product_id else None,
            assignment=ADVISORY_ASSIGNMENT, quantity_decimal_string=_quantity_text(units) if units > 0 else None,
            price_minor=price_minor, price_currency=price_currency or None, source_amount_minor=None,
            fx_rate_ppm=None, fx_rate_ratio=None, fx_source=None, fx_observed_at=None, base_value_minor=None,
            price_observed_at=price_date.isoformat() if price_date else None, data_quality=Q_OK,
            included_in_total=0, label=str(getattr(product, "product_name", "") or "") or None,
        )
        if product is None:
            row.data_quality = Q_MISSING_INSTRUMENT
        elif units <= 0:
            # Nur Marktwert ohne Stueckzahl: Waehrung nicht belegt -> unbekannt.
            row.data_quality = Q_MISSING_QUANTITY
        elif price_minor is None or price_date is None:
            row.data_quality = Q_MISSING_PRICE
        elif not holding.as_of_date:
            row.data_quality = Q_MISSING_VALUATION_DATE
        elif price_date < stale_limit:
            row.data_quality = Q_STALE_PRICE
        elif not price_currency:
            row.data_quality = Q_MISSING_CURRENCY
        else:
            source_amount = _half_up_div(units * price_minor, 1000)
            row.source_amount_minor = source_amount
            _convert_row(row, basis, source_amount, price_currency)
            if row.data_quality == Q_OK:
                observed.append(price_date.isoformat())
        rows.append(row)
    for item in not_carried:
        rows.append(ValuationRowData(
            position_id=str(item["holding_id"]), source_kind="depot_holding",
            instrument_id=str(item["product_id"]), assignment=ADVISORY_ASSIGNMENT,
            quantity_decimal_string=None, price_minor=None, price_currency=None, source_amount_minor=None,
            fx_rate_ppm=None, fx_rate_ratio=None, fx_source=None, fx_observed_at=None, base_value_minor=None,
            price_observed_at=None, data_quality=Q_NOT_CARRIED_OVER, included_in_total=0,
            label=item.get("product_name"),
        ))

    for row in rows:
        if row.data_quality not in _VALUE_KNOWN:
            row.base_value_minor = None
        row.seal()

    blockers = {str(quality_reason(r.data_quality)) for r in rows if r.data_quality != Q_OK}
    flow_blockers: list[dict[str, Any]] = []
    for kind, items in (("cashflow", cashflows), ("wealth_inflow", inflows)):
        for item in items:
            currency = normalize_currency(getattr(item, "currency", None))
            status = basis.status(currency) if currency else "MISSING"
            if currency and status == STATUS_OK and (
                currency == base_currency or base_currency == "CHF"
                or basis.statuses.get(base_currency, STATUS_OK) == STATUS_OK
            ):
                continue
            quality = Q_MISSING_CURRENCY if not currency else _fx_quality(status)
            flow_blockers.append({"kind": kind, "id": str(item.id), "currency": currency or None,
                                  "data_quality": quality})
            blockers.add(str(quality_reason(quality)))

    if positions and manual_max_age is None and not attest_manual_valuations:
        blockers.add(str(ReasonCode.CCX_VALUATION_ATTESTATION_REQUIRED))
    holdings_basis = BASIS_RECORDED
    if not rows:
        if confirm_no_holdings and (cashflows or inflows):
            holdings_basis = BASIS_CONFIRMED_EMPTY
        else:
            blockers.add(str(ReasonCode.CCX_VALUATION_MISSING))

    coverage = coverage_from_qualities(
        [r.data_quality for r in rows], value_unknown=[r.base_value_minor is None for r in rows],
    )
    if blockers and coverage == COMPLETE:
        coverage = UNKNOWN if any(
            code in blockers for code in (str(ReasonCode.CCX_VALUATION_MISSING), str(ReasonCode.CCX_FX_BASIS_MISSING))
        ) else PARTIAL
    total = advisory = None
    if coverage == COMPLETE:
        included = [r for r in rows if r.included_in_total]
        total = sum(int(r.base_value_minor) for r in included)
        advisory = sum(int(r.base_value_minor) for r in included if r.assignment == ADVISORY_ASSIGNMENT)
    systems = {SOURCE_MANUAL if r.source_kind == "wealth_position" else SOURCE_MARKET for r in rows}
    fx_observed = [q.observed_at[:10] for q in basis.quotes]
    projection = ValuationProjection(
        tenant_id=str(getattr(mandate, "tenant_id", "") or "") or None,
        mandate_id=str(mandate.id),
        as_of=as_of_date.isoformat(),
        base_currency=base_currency,
        fx_basis=basis,
        rows=rows,
        coverage_status=coverage,
        holdings_basis=holdings_basis,
        blocker_codes=sorted(blockers),
        flow_blockers=flow_blockers,
        source_system="+".join(sorted(systems)) if systems else SOURCE_MANUAL,
        source_observed_at=min(observed + fx_observed) if (observed or fx_observed) else None,
        total_base_minor=total,
        advisory_base_minor=advisory,
        manual_valuation_attested=bool(attest_manual_valuations),
        manual_valuation_max_age_days=manual_max_age,
    )
    projection.snapshot_hash = child_hash(SNAPSHOT_KIND, _canonical(projection.hash_body()))
    return projection


def assert_valuation_publishable(projection: ValuationProjection) -> None:
    """Kein Depot-/Markt-Claim ohne COMPLETE (typisierter Blocker)."""
    if projection.publishable:
        return
    code = primary_reason(projection.blocker_codes)
    raise ValuationError(
        code,
        "Die Bewertung des Bestands ist nicht vollstaendig belegt "
        f"({projection.coverage_status}); kundenwirksame Schritte sind gesperrt.",
        extra={
            "coverage_status": projection.coverage_status,
            "blocker_codes": sorted(projection.blocker_codes),
            "snapshot_hash": projection.snapshot_hash,
            "fx_basis_hash": projection.fx_basis_hash,
        },
    )


# ── Persistenz ───────────────────────────────────────────────────────────────


def persist_valuation_snapshot(db: Session, projection: ValuationProjection, *, user_id: str) -> HoldingsValuationSnapshot:
    """Schreibt Snapshot und Zeilen append-only; gleicher Inhalt (Hash) wird
    wiederverwendet statt dupliziert."""
    if not projection.tenant_id:
        raise ValuationError(
            ReasonCode.CCX_VALUATION_MISSING,
            "Die Bewertung kann nicht festgehalten werden: das Mandat ist keiner Firma zugeordnet.",
        )
    existing = db.query(HoldingsValuationSnapshot).filter(
        HoldingsValuationSnapshot.tenant_id == projection.tenant_id,
        HoldingsValuationSnapshot.mandate_id == projection.mandate_id,
        HoldingsValuationSnapshot.snapshot_hash == projection.snapshot_hash,
    ).first()
    if existing is not None:
        return existing
    snapshot = HoldingsValuationSnapshot(
        id=new_uuid(), tenant_id=projection.tenant_id, mandate_id=projection.mandate_id,
        schema_version=HOLDINGS_VALUATION_SCHEMA_VERSION, as_of=projection.as_of,
        source_observed_at=projection.source_observed_at, source_system=projection.source_system,
        base_currency=projection.base_currency, fx_basis_hash=projection.fx_basis_hash,
        fx_basis_json=_canonical(projection.fx_basis.as_dict()).decode("utf-8"),
        coverage_status=projection.coverage_status, holdings_basis=projection.holdings_basis,
        position_count=projection.position_count, total_base_minor=projection.total_base_minor,
        advisory_base_minor=projection.advisory_base_minor,
        blocker_codes_json=json.dumps(sorted(projection.blocker_codes), separators=(",", ":")),
        manual_valuation_attested=1 if projection.manual_valuation_attested else 0,
        manual_valuation_max_age_days=projection.manual_valuation_max_age_days,
        snapshot_hash=projection.snapshot_hash, created_at=utc_now(), created_by=user_id,
    )
    db.add(snapshot)
    db.flush()
    for row in projection.rows:
        db.add(HoldingsValuationRow(
            id=new_uuid(), tenant_id=projection.tenant_id, snapshot_id=snapshot.id, row_hash=row.row_hash,
            **row.hash_body(),
        ))
    db.flush()
    return snapshot


def verify_valuation_snapshot(db: Session, snapshot: HoldingsValuationSnapshot) -> str | None:
    """Prueft gespeicherte Zeilen gegen den Snapshot-Hash; ``None`` = integer."""
    rows = db.query(HoldingsValuationRow).filter(
        HoldingsValuationRow.tenant_id == snapshot.tenant_id,
        HoldingsValuationRow.snapshot_id == snapshot.id,
    ).all()
    if len(rows) != int(snapshot.position_count):
        return "row_count"
    for row in rows:
        data = ValuationRowData(**{
            name: getattr(row, name) for name in ValuationRowData.__dataclass_fields__
            if name not in ("label", "row_hash")
        })
        data.seal()
        if data.row_hash != row.row_hash:
            return "row_hash"
    body = {
        "schema_version": snapshot.schema_version,
        "tenant_id": snapshot.tenant_id,
        "mandate_id": snapshot.mandate_id,
        "as_of": snapshot.as_of,
        "source_observed_at": snapshot.source_observed_at,
        "source_system": snapshot.source_system,
        "base_currency": snapshot.base_currency,
        "fx_basis_hash": snapshot.fx_basis_hash,
        "coverage_status": snapshot.coverage_status,
        "holdings_basis": snapshot.holdings_basis,
        "position_count": int(snapshot.position_count),
        "total_base_minor": snapshot.total_base_minor,
        "advisory_base_minor": snapshot.advisory_base_minor,
        "blocker_codes": sorted(json.loads(snapshot.blocker_codes_json)),
        "manual_valuation_attested": bool(snapshot.manual_valuation_attested),
        "manual_valuation_max_age_days": snapshot.manual_valuation_max_age_days,
        "rows": [r.row_hash for r in sorted(rows, key=lambda r: (r.source_kind, r.position_id))],
    }
    if child_hash(SNAPSHOT_KIND, _canonical(body)) != snapshot.snapshot_hash:
        return "snapshot_hash"
    return None


@dataclass
class ValuationBinding:
    """CCX-P3-Bindung fuer das P1-Siegel ("Daten uebergeben"): der Envelope
    erhaelt Projektion, Ledger und Fence, ohne selbst zu bewerten."""

    projection: ValuationProjection
    ledger_entries: list[dict[str, Any]]
    ledger_hash: str
    confirm_no_holdings: bool
    attest_manual_valuations: bool = False

    @property
    def publishable(self) -> bool:
        return self.projection.publishable

    @property
    def primary_code(self) -> str:
        return str(primary_reason(self.projection.blocker_codes))

    @property
    def depot_position_ids(self) -> list[str]:
        return [r.position_id for r in self.projection.rows if r.source_kind == "depot_holding"]

    def missing_decisions(self) -> list[str]:
        return missing_decisions(self.depot_position_ids, self.ledger_entries)

    def persist(self, db: Session, *, user_id: str) -> HoldingsValuationSnapshot:
        return persist_valuation_snapshot(db, self.projection, user_id=user_id)

    def unchanged(self, db: Session, mandate: Any) -> bool:
        """Fence: Bestand/Preise/Kurse zum selben Stichtag unveraendert?"""
        try:
            again = project_holdings_valuation(
                db, mandate, as_of=self.projection.as_of, confirm_no_holdings=self.confirm_no_holdings,
                attest_manual_valuations=self.attest_manual_valuations,
            )
        except Exception:  # noqa: BLE001 - unbekannt -> nie konsistent
            return False
        return again.snapshot_hash == self.projection.snapshot_hash


def prepare_valuation_binding(
    db: Session, mandate: Any, run: Any, *, confirm_no_holdings: bool = False,
    attest_manual_valuations: bool = False,
) -> ValuationBinding:
    """Bewertung + Entscheid je verwalteter Depotposition (gegen die Zielgewichte
    des Laufs). N-909-09: manuelle, nicht verwaltete Positionen (Vorsorge,
    Immobilie, Police, Konten) bleiben sichtbar und bewertet, erhalten aber nie
    KEEP/SELL -- nicht verwaltet, nie auf Anlageklassen geschaetzt."""
    projection = project_holdings_valuation(
        db, mandate, confirm_no_holdings=confirm_no_holdings,
        attest_manual_valuations=attest_manual_valuations,
    )
    weights: dict[str, int] = {}
    for position in db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == str(getattr(run, "id", "") or ""),
    ).all():
        key = str(position.product_id)
        weights[key] = weights.get(key, 0) + int(position.target_weight_bps or 0)
    depot_rows = [
        {"position_id": r.position_id, "instrument_id": r.instrument_id, "data_quality": r.data_quality}
        for r in projection.rows if r.source_kind == "depot_holding"
    ]
    entries = decide_positions(depot_rows, weights)
    return ValuationBinding(
        projection=projection,
        ledger_entries=entries,
        ledger_hash=ledger_child_hash(entries, projection.snapshot_hash),
        confirm_no_holdings=confirm_no_holdings,
        attest_manual_valuations=attest_manual_valuations,
    )


def assert_fx_evidence_current(db: Session, mandate: Any, fx_evidence: Any) -> None:
    """N-909-02: die gespeicherte Kursevidenz eines Snapshots (Depot-Snapshot)
    muss heute noch belegt sein -- jede Fremdwaehrung mit belegtem, frischem
    Kurs (kein Ersatzkurs) und mit genau dem gespeicherten Kurs. Ein Alt- oder
    Ersatzkurs wird nie gedruckt (``CCX_FX_BASIS_*``)."""
    evidence = fx_evidence if isinstance(fx_evidence, dict) else {}
    target = normalize_currency(evidence.get("target_currency") or getattr(mandate, "base_currency", None))
    rates = evidence.get("effective_rates_x1e8") or []
    currencies = {normalize_currency(item[0]) for item in rates if isinstance(item, (list, tuple)) and item}
    foreign = currencies - {target, ""}
    if not foreign:
        return
    basis = load_fx_basis(db, target, foreign, tenant_id=getattr(mandate, "tenant_id", None))
    for item in rates:
        currency, stored = normalize_currency(item[0]), int(item[1])
        if currency in ("", target):
            continue
        line = basis.convert(0, currency)  # wirft bei fehlendem/abgelaufenem/Ersatzkurs
        numerator, denominator = (int(part) for part in line.fx_rate_ratio.split("/"))
        # Gleiche Darstellung wie FXRateSource.canonical_model_signature.
        current = int(round(((numerator / 10_000) / (denominator / 10_000)) * 100_000_000))
        if current != stored:
            raise ValuationError(
                ReasonCode.CCX_FX_BASIS_MISMATCH,
                f"Der gespeicherte Kurs {currency}/{target} entspricht nicht dem heute belegten Kurs; "
                "bitte den Depot-Check neu speichern.",
                extra={"currencies": [currency], "fx_basis_hash": basis.fx_basis_hash},
            )


__all__ = [
    "ValuationBinding",
    "mandate_has_recorded_depot_holdings",
    "prepare_valuation_binding",
    "ValuationError",
    "ValuationProjection",
    "assert_valuation_publishable",
    "persist_valuation_snapshot",
    "primary_reason",
    "project_holdings_valuation",
    "verify_valuation_snapshot",
]
