"""Weiterleitung ans Asset Management -- Snapshot-Berechnung.

Berechnet den zu einer Weiterleitung gehoerenden Handelslisten-Snapshot NICHT
neu (kein zweiter, unabhaengiger Engine-Pfad -- Drift-Risiko), sondern liest
ihn aus ``services.portfolio_engine.build_recommendation_payload_from_run()``,
demselben Aufruf, den ``routers/review.py::get_recommendation_payload*`` fuer
die Handelsliste-Anzeige im Review nutzt. Wendet exakt denselben 0.5%-der-
Gesamtsumme-Schwellenwert an wie ``openTradeList()`` in 5eyes_v2.html, damit
der Snapshot mit dem uebereinstimmt, was der Berater tatsaechlich gesehen hat.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.review import Product, RecommendationRun
from services.portfolio_engine import build_recommendation_payload_from_run

# Fields kept per trade in the immutable snapshot -- a curated subset of the
# live-rebalancing entry (see services/portfolio_engine_live_rebalancing.py),
# not the full internal engine record (which carries pricing-diagnostic
# fields irrelevant to an execution instruction).
_SNAPSHOT_TRADE_FIELDS = (
    "product_id",
    "product_name",
    "asset_class",
    "sub_asset_class",
    "product_currency",
    "rebalance_action",
    "rebalance_action_code",
    "current_market_value_rappen",
    "target_amount_rappen",
    "rebalance_amount_rappen",
    "current_weight_bps",
    "target_weight_bps",
)

# HANDOFF-INSTRUCTION-001: ausfuehrungsrelevante Felder (Instrument, Konto,
# Menge, Preis-/FX-Anker, Ordertyp). Sie werden uebernommen, wenn die Quelle
# sie liefert -- nie erfunden oder mit Defaults aufgefuellt.
_SNAPSHOT_INSTRUCTION_FIELDS = (
    "isin",
    "custody_account_id",
    "holding_depot_bank",
    "current_units_milli",
    "valuation_basis",
    "reference_price_rappen",
    "reference_price_date",
    "latest_price_rappen",
    "latest_price_date",
    "fx_rate",
    "order_type",
)

# Ohne diese Felder ist eine Zeile eine Rebalancing-Empfehlung, keine
# ausfuehrbare Handelsinstruktion -- pro Zeile ausgewiesen.
_REQUIRED_INSTRUCTION_FIELDS = ("isin", "custody_account_id", "current_units_milli", "reference_price_rappen")
INSTRUCTION_KIND_EXECUTABLE = "executable_instruction"
INSTRUCTION_KIND_RECOMMENDATION = "rebalancing_recommendation"

# Identisch zur Schwelle in openTradeList() (5eyes_v2.html) -- Trades unter
# 0.5% der Gesamtsumme werden dort ausgeblendet (Rauschen/Rundungsdrift), der
# Snapshot muss exakt dieselbe Liste abbilden.
_MIN_TRADE_SHARE = 0.005


class NoTradeListAvailableError(ValueError):
    """Kein Rebalancing-Bedarf oder keine Live-Rebalancing-Daten fuer diesen Run."""


class HoldingsValuationIncompleteError(ValueError):
    """HANDOFF-VALUATION-001: die Live-Bewertung ist nicht vollstaendig durch
    echte Bestaende, Preise und FX belegt -- kein ausfuehrungsnaher Snapshot."""


# HANDOFF-VALUATION-001: Coverage-Aggregate aus
# services/portfolio_engine_live_rebalancing.py::build_live_rebalancing_payload.
# Fehlt ein Aggregat, ist die Abdeckung nicht belegt (fail-closed).
_COVERAGE_BLOCKERS = (
    ("implied_positions_count", "Position(en) ohne erfassten Depotbestand (nur aus dem Zielbetrag abgeleitet)"),
    ("missing_prices_count", "Position(en) ohne aktuellen Marktpreis"),
    ("stale_positions_count", "Position(en) mit veraltetem Marktpreis"),
    ("fx_conversion_failed_count", "Position(en) mit fehlgeschlagener Waehrungsumrechnung"),
)


def assert_holdings_valuation_complete(live: dict) -> None:
    """Wirft ``HoldingsValuationIncompleteError``, wenn die Live-Bewertung
    nicht vollstaendig auf echten Bestaenden, frischen Preisen und
    erfolgreicher FX-Umrechnung beruht."""
    def _count(key: str):
        try:
            return int(live[key])
        except (KeyError, TypeError, ValueError):
            return None

    counts = {key: _count(key) for key in ("holding_positions_count",) + tuple(k for k, _ in _COVERAGE_BLOCKERS)}
    # Reihenfolge: zuerst der inhaltliche Befund (kein Bestand), dann fehlende
    # Nachweise -- die Meldung nennt den tatsaechlichen Grund.
    if counts["holding_positions_count"] is not None and counts["holding_positions_count"] <= 0:
        raise HoldingsValuationIncompleteError(
            "Kein erfasster Depotbestand: die Handelsliste beruht ausschliesslich "
            "auf aus dem Ziel abgeleiteten Positionen und ist keine Handelsinstruktion. "
            "Bitte die Depotbestaende erfassen."
        )
    if any(value is None for value in counts.values()):
        raise HoldingsValuationIncompleteError(
            "Die Bewertungsabdeckung der Live-Handelsliste ist nicht belegt "
            "(Bestands-/Preis-/FX-Nachweis fehlt). Keine Weiterleitung moeglich."
        )
    problems = [f"{counts[key]} {label}" for key, label in _COVERAGE_BLOCKERS if counts[key] > 0]
    if problems:
        raise HoldingsValuationIncompleteError(
            "Die Live-Bewertung ist nicht vollstaendig belegt: " + "; ".join(problems)
            + ". Bitte Bestaende und Preise aktualisieren, bevor die Handelsliste weitergeleitet wird."
        )


def snapshot_handoff_trades(db: Session, mandate: Mandate, run: RecommendationRun, user_id: str) -> tuple[list[dict], int]:
    """Liefert (trades, live_total_value_rappen) fuer eine neue Weiterleitung.

    Wirft ``ValueError`` (z.B. fehlendes Risikoprofil/Soll-Allokation, aus
    ``build_recommendation_payload_from_run``), ``NoTradeListAvailableError``
    (Live-Rebalancing lieferte keine Trades oberhalb der Anzeige-Schwelle) oder
    ``HoldingsValuationIncompleteError`` (Bewertung nicht durch echte
    Bestaende/Preise/FX belegt) -- alle sind vom Router als 409 zu behandeln.
    """
    payload = build_recommendation_payload_from_run(
        db=db, mandate=mandate, run=run, user_id=user_id, preferences=None,
    )
    live = payload.get("live_rebalancing") or {}
    drifts = live.get("position_drifts") or []
    total_value_rappen = int(live.get("live_total_value_rappen") or 0)
    if not drifts or total_value_rappen <= 0:
        raise NoTradeListAvailableError("Keine Live-Rebalancing-Daten fuer diesen Lauf verfuegbar.")
    assert_holdings_valuation_complete(live)

    threshold_rappen = round(total_value_rappen * _MIN_TRADE_SHARE)
    selected = [
        entry for entry in drifts
        if abs(int(entry.get("rebalance_amount_rappen") or 0)) >= threshold_rappen
    ]
    isin_by_product = _isin_by_product_id(db, [entry.get("product_id") for entry in selected])
    trades = [_snapshot_trade(entry, isin_by_product) for entry in selected]
    if not trades:
        raise NoTradeListAvailableError(
            "Live-Bewertung liegt aktuell innerhalb der strategischen Zielbandbreiten "
            "(keine Trades oberhalb der 0.5%-Anzeigeschwelle)."
        )
    trades.sort(key=lambda item: abs(int(item.get("rebalance_amount_rappen") or 0)), reverse=True)
    return trades, total_value_rappen


def _isin_by_product_id(db: Session, product_ids: list) -> dict:
    ids = sorted({str(pid) for pid in product_ids if pid})
    if not ids:
        return {}
    rows = db.query(Product.id, Product.isin).filter(Product.id.in_(ids)).all()
    return {row.id: str(row.isin).strip() for row in rows if row.isin and str(row.isin).strip()}


def _snapshot_trade(entry: dict, isin_by_product: dict) -> dict:
    """Kuratierte Tradezeile plus die vorhandenen Instruktionsfelder."""
    trade = {field: entry.get(field) for field in _SNAPSHOT_TRADE_FIELDS}
    source = dict(entry)
    # Quellfelder des Live-Rebalancings auf die Instruktionsnamen abbilden;
    # ein explizit geliefertes Feld hat Vorrang.
    if source.get("custody_account_id") is None and source.get("holding_custody_account_number"):
        source["custody_account_id"] = source.get("holding_custody_account_number")
    if source.get("isin") is None and isin_by_product.get(str(entry.get("product_id"))):
        source["isin"] = isin_by_product[str(entry.get("product_id"))]
    for field in _SNAPSHOT_INSTRUCTION_FIELDS:
        value = source.get(field)
        if value is not None and value != "":
            trade[field] = value
    missing = [field for field in _REQUIRED_INSTRUCTION_FIELDS if field not in trade]
    trade["instruction_kind"] = INSTRUCTION_KIND_RECOMMENDATION if missing else INSTRUCTION_KIND_EXECUTABLE
    trade["missing_instruction_fields"] = missing
    return trade
