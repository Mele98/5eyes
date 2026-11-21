"""HANDOFF-CASH-BASIS-001: Liquiditaet des Beratungsvermoegens in der Handoff-Basis.

CIO-Entscheid: Bewertete Liquiditaetspositionen (``WealthPosition`` vom Typ
Liquiditaet, Zuordnung Beratungsvermoegen) zaehlen als Cash-IST in der Basis
einer Weiterleitung, wenn ein Depot erfasst ist. Cash ausserhalb der
erfassten Depotpositionen darf nicht still aus der Basis verschwinden.

Jede solche Position wird eine eigene Zeile mit IST = bewerteter Betrag
(in Mandatswaehrung) und SOLL = 0: das SOLL ist vollstaendig ueber die
Produkte des Laufs abgebildet, das Delta zeigt, wie viel Liquiditaet fuer die
Kaeufe eingesetzt wird. Ohne Stichtag oder Waehrung, oder ohne gueltigen
FX-Kurs, ist die Position nicht belegt -- fail-closed wie die Depotbewertung.
Ein Hoechstalter des Stichtags ist nicht festgelegt (Owner-Entscheid); es wird
nur das Vorhandensein geprueft.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from core import external_holdings_rule as external_rule

from models.mandates import Mandate
from models.wealth import WealthPosition
from services.currency.fx_rates import FXRateSource
from services.portfolio_engine import _convert_position_value_to_target_currency
from services.portfolio_engine_live_rebalancing import _rebalancing_action_meta

HOLDING_ORIGIN_ADVISORY_CASH = "advisory_cash"
VALUATION_BASIS_WEALTH_POSITION = "wealth_position_value"
_LIQUIDITY_POSITION_TYPES = ("Liquidität", "Liquiditaet")
_ADVISORY_ASSIGNMENTS = ("Beratungsvermögen", "Beratungsvermoegen")


# Wertemenge von WealthPosition.liquidity_instrument (schemas/wealth.py).
_LIQUIDITY_INSTRUMENTS = ("Kontoguthaben", "Sparkonto", "Festgeld", "Kassenobligation", "Geldmarktfonds")


def _generic_cash_name(instrument: str | None, currency: str) -> str:
    kind = str(instrument or "").strip()
    parts = ["Liquiditaet", kind if kind in _LIQUIDITY_INSTRUMENTS else "", currency]
    return " ".join(part for part in parts if part)


class AdvisoryCashValuationError(ValueError):
    """Eine Liquiditaetsposition des Beratungsvermoegens ist nicht belegt."""


def advisory_cash_entries(db: Session, mandate: Mandate) -> list[dict]:
    """Bewertete Liquiditaetspositionen des Beratungsvermoegens als
    Live-Rebalancing-Eintraege (IST = Wert in Mandatswaehrung, SOLL = 0)."""
    rows = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.position_type.in_(_LIQUIDITY_POSITION_TYPES),
    ).order_by(WealthPosition.id.asc()).all()
    target_currency = str(getattr(mandate, "base_currency", "") or "CHF").upper().strip()
    fx_source = None
    entries = []
    for pos in rows:
        if pos.is_active == 0 or str(pos.assignment or "").strip() not in _ADVISORY_ASSIGNMENTS:
            continue
        value = int(pos.current_value_rappen or 0)
        if value <= 0:
            continue
        label = str(pos.label or "").strip() or pos.id
        as_of = str(pos.valuation_date or "").strip()
        currency = str(pos.currency or "").upper().strip()
        if not as_of or not currency:
            raise AdvisoryCashValuationError(
                f"Die Liquiditaetsposition '{label}' im Beratungsvermoegen hat keinen "
                "Bewertungsstichtag oder keine Waehrung. Ohne belegte Bewertung kann sie "
                "nicht in die Basis der Handelsliste einfliessen; bitte Stichtag und "
                "Waehrung erfassen."
            )
        if currency != target_currency and fx_source is None:
            # Dieselbe FX-Basis wie die Allokation (build_recommendation_payload).
            fx_source = FXRateSource.from_db_strict_for_model(db, tenant_id=getattr(mandate, "tenant_id", None))  # CCX-P3-FX N-909-01
        try:
            value_target = _convert_position_value_to_target_currency(value, pos, fx_source, target_currency)
        except ValueError as exc:
            raise AdvisoryCashValuationError(
                f"Die Liquiditaetsposition '{label}' laesst sich nicht in die "
                f"Mandatswaehrung umrechnen: {exc}"
            ) from exc
        entries.append({
            "id": f"cash-{pos.id}",
            "wealth_position_id": pos.id,
            "product_id": None,
            # Red-Team 2026-10-28 Befund 3: keine Freitext-Bezeichnung im
            # unveraenderlichen Snapshot, nur Instrumenttyp + Waehrung.
            "product_name": _generic_cash_name(pos.liquidity_instrument, currency),
            "asset_class": "Liquiditaet",
            "sub_asset_class": str(pos.liquidity_instrument or "").strip() or None,
            "product_currency": currency,
            "target_weight_bps": 0,
            "target_amount_rappen": 0,
            "latest_price_rappen": None,
            "reference_price_rappen": None,
            "holding_present": True,
            "holding_as_of_date": as_of,
            "holding_depot_bank": str(pos.depot_bank or "").strip() or None,
            "holding_custody_account_number": str(pos.depot_account_number or "").strip() or None,
            "valuation_basis": VALUATION_BASIS_WEALTH_POSITION,
            "current_market_value_rappen": value_target,
            "holding_origin": HOLDING_ORIGIN_ADVISORY_CASH,
        })
    return entries


def with_cash_actions(drifts: list[dict]) -> list[dict]:
    """Liquiditaet hat keinen Marktpreis, ihr Wert ist nominal: die Aktion
    folgt dem Delta statt ``MISSING_PRICE``."""
    result = []
    for entry in drifts:
        if entry.get("holding_origin") == HOLDING_ORIGIN_ADVISORY_CASH:
            code, label = _rebalancing_action_meta(
                int(entry["delta_weight_bps"]), int(entry["rebalance_amount_rappen"]), True,
            )
            entry = {**entry, "rebalance_action_code": code, "rebalance_action": label, "rebalance_action_label": label}
        result.append(entry)
    return result


# K3 / N-915-06: Titel ausserhalb der Empfehlung (core/external_holdings_rule.py).
def external_handoff_entries(db: Session, mandate: Mandate, exclude_isins=()) -> list[dict]:
    """Bewerteter Fremdbestand als Live-Rebalancing-Eintraege (IST = Wert in
    Mandatswaehrung, SOLL = 0) -- dieselbe Regel wie Depotcheck und
    Depot-Snapshot. Nicht bewertbar -> ``AdvisoryCashValuationError``
    (fail-closed, kein Ersatzwert)."""
    rows = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.position_type == "Depot",
    ).order_by(WealthPosition.id.asc()).all()
    depots = [(row.id, row.external_holdings_json) for row in rows
              if external_rule.is_advisory_depot(row) and row.external_holdings_json]
    if not depots:
        return []
    target_currency = str(getattr(mandate, "base_currency", "") or "CHF").upper().strip()
    # Dieselbe strikte FX-Basis wie die Liquiditaet (lazy: nur bei Fremdwaehrung).
    fx: dict = {}

    def convert(amount: int, currency: str) -> int:
        if currency != target_currency and "source" not in fx:
            fx["source"] = FXRateSource.from_db_strict_for_model(db, tenant_id=getattr(mandate, "tenant_id", None))
        return external_rule.strict_converter(fx.get("source"), target_currency)(amount, currency)

    valuation = external_rule.evaluate(depots, convert=convert, exclude_isins=exclude_isins, today=date.today().isoformat())
    if valuation["unvalued_count"]:
        raise AdvisoryCashValuationError(external_rule.unvalued_message(valuation["items"]))
    return [{
        "id": item["id"],
        "wealth_position_id": item["wealth_position_id"],
        "product_id": None,
        "product_name": item["label"],
        "isin": item["isin"],
        "asset_class": item["asset_class"],
        "sub_asset_class": None,
        "product_currency": item["currency"],
        "target_weight_bps": 0,
        "target_amount_rappen": 0,
        "latest_price_rappen": None,
        "reference_price_rappen": None,
        "holding_present": True,
        "holding_as_of_date": item["valuation_date"],
        "valuation_basis": external_rule.VALUATION_BASIS_EXTERNAL,
        "current_market_value_rappen": int(item["amount_base_rappen"]),
        "holding_origin": external_rule.ORIGIN_EXTERNAL,
    } for item in valuation["items"]]


def with_external_actions(drifts: list[dict]) -> list[dict]:
    """Fremdtitel: nie ein Verkaufsauftrag. Die Aktion ist ein gekennzeichneter
    Vorschlag (``REVIEW``); Verkauf oder Halten entscheidet der Kunde."""
    result = []
    for entry in drifts:
        if entry.get("holding_origin") == external_rule.ORIGIN_EXTERNAL:
            label = external_rule.ACTION_REVIEW_LABEL
            entry = {**entry, "rebalance_action_code": external_rule.ACTION_REVIEW, "rebalance_action": label,
                     "rebalance_action_label": label}
        result.append(entry)
    return result
