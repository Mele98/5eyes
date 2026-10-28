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

import hashlib
import json

from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.review import Product, RecommendationRun
from models.wealth import WealthPosition
from services.portfolio_engine import build_recommendation_payload_from_run
from services.portfolio_engine_live_rebalancing import _build_live_position_drifts

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
    "holding_origin",
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


# HANDOFF-NEW-PRODUCT-001: Herkunft des IST je Tradezeile und Bestandsbasis
# der ganzen Weiterleitung (persistiert in portfolio_handoffs.holdings_basis,
# Wertemenge models/portfolio_handoff.py::HANDOFF_HOLDINGS_BASES).
HOLDING_ORIGIN_HELD = "held"
HOLDING_ORIGIN_NOT_HELD = "not_held"
HOLDINGS_BASIS_RECORDED_DEPOT = "recorded_depot"
HOLDINGS_BASIS_CONFIRMED_NO_HOLDINGS = "confirmed_no_holdings"


class NoTradeListAvailableError(ValueError):
    """Kein Rebalancing-Bedarf oder keine Live-Rebalancing-Daten fuer diesen Run."""


class HoldingsValuationIncompleteError(ValueError):
    """HANDOFF-VALUATION-001: die Live-Bewertung ist nicht vollstaendig durch
    echte Bestaende, Preise und FX belegt -- kein ausfuehrungsnaher Snapshot."""


# HANDOFF-VALUATION-001: Coverage-Aggregate aus
# services/portfolio_engine_live_rebalancing.py::build_live_rebalancing_payload.
# Fehlt ein Aggregat, ist die Abdeckung nicht belegt (fail-closed).
_PRICE_BLOCKERS = (
    ("missing_prices_count", "Position(en) ohne aktuellen Marktpreis"),
    ("stale_positions_count", "Position(en) mit veraltetem Marktpreis"),
    ("fx_conversion_failed_count", "Position(en) mit fehlgeschlagener Waehrungsumrechnung"),
)
_COVERAGE_KEYS = ("holding_positions_count", "implied_positions_count") + tuple(k for k, _ in _PRICE_BLOCKERS)


def _coverage_counts(live: dict) -> dict:
    def _count(key: str):
        try:
            return int(live[key])
        except (KeyError, TypeError, ValueError):
            return None

    return {key: _count(key) for key in _COVERAGE_KEYS}


def assert_holdings_valuation_complete(live: dict) -> None:
    """Strenge Vollstaendigkeitspruefung einer reinen Bestandsbewertung
    (DepotSnapshotV1 / IST-Stress): mindestens ein echter Bestand, alle
    Aggregate belegt, keine abgeleiteten, preislosen, veralteten oder
    FX-fehlerhaften Positionen. Wirft ``HoldingsValuationIncompleteError``.

    Die Handelsliste nutzt ``resolve_handoff_holdings_basis`` (IST = 0 fuer
    nicht gehaltene SOLL-Produkte); diese Funktion bleibt fuer Pfade, die
    ausschliesslich den gehaltenen Bestand bewerten."""
    counts = _coverage_counts(live)
    held_count = counts["holding_positions_count"]
    if held_count is not None and held_count <= 0:
        raise HoldingsValuationIncompleteError(
            "Kein erfasster Depotbestand. Bitte die Depotbestaende erfassen."
        )
    if any(value is None for value in counts.values()):
        raise HoldingsValuationIncompleteError(
            "Die Bewertungsabdeckung ist nicht belegt (Bestands-/Preis-/FX-Nachweis fehlt)."
        )
    blockers = (("implied_positions_count", "Position(en) ohne erfassten Depotbestand (nur aus dem Zielbetrag abgeleitet)"),) + _PRICE_BLOCKERS
    problems = [f"{counts[key]} {label}" for key, label in blockers if counts[key] > 0]
    if problems:
        raise HoldingsValuationIncompleteError(
            "Die Bewertung ist nicht vollstaendig belegt: " + "; ".join(problems)
            + ". Bitte Bestaende und Preise aktualisieren."
        )

def resolve_handoff_holdings_basis(
    live: dict,
    *,
    confirm_no_existing_holdings: bool = False,
    advisory_depot_recorded: bool = False,
    investable_wealth_rappen: int | None = None,
) -> tuple[list[dict], int, str]:
    """Liefert (position_drifts, Basis-Total, holdings_basis) fuer den Snapshot.

    HANDOFF-VALUATION-001 bleibt fail-closed: fehlende Aggregate, fehlende/
    veraltete Preise oder FX-Fehler -> ``HoldingsValuationIncompleteError``.

    HANDOFF-NEW-PRODUCT-001 (CIO-Entscheid): ein SOLL-Produkt ohne erfassten
    Bestand hat IST = 0 (``holding_origin = not_held``), aber nur wenn

    * das erfasste Depot vollstaendig belegt ist (jede gehaltene Position
      bewertet und mit Bestands-Stichtag, Zaehler konsistent) -- Basis ist
      dann die Summe der echten Bestaende; oder
    * gar kein Bestand erfasst ist und der Berater ausdruecklich bestaetigt,
      dass keiner existiert (Neugeld) -- Basis ist dann das investierbare
      Beratungsvermoegen. Die Bestaetigung wird abgelehnt, wenn das
      Beratungsvermoegen ein Wertschriftendepot enthaelt oder Bestaende
      erfasst sind.

    SOLL, IST und Delta werden mit derselben Funktion wie die Live-Ansicht
    neu gerechnet (IST + Delta = SOLL auf einer Basis)."""
    counts = _coverage_counts(live)
    held_count = counts["holding_positions_count"]
    if held_count is not None and held_count <= 0 and not confirm_no_existing_holdings:
        raise HoldingsValuationIncompleteError(
            "Kein erfasster Depotbestand: die Handelsliste beruht ausschliesslich "
            "auf aus dem Ziel abgeleiteten Positionen und ist keine Handelsinstruktion. "
            "Bitte die Depotbestaende erfassen oder -- nur bei Neugeld ohne bestehendes "
            "Depot -- ausdruecklich bestaetigen (confirm_no_existing_holdings)."
        )
    if any(value is None for value in counts.values()):
        raise HoldingsValuationIncompleteError(
            "Die Bewertungsabdeckung der Live-Handelsliste ist nicht belegt "
            "(Bestands-/Preis-/FX-Nachweis fehlt). Keine Weiterleitung moeglich."
        )
    problems = [f"{counts[key]} {label}" for key, label in _PRICE_BLOCKERS if counts[key] > 0]
    if problems:
        raise HoldingsValuationIncompleteError(
            "Die Live-Bewertung ist nicht vollstaendig belegt: " + "; ".join(problems)
            + ". Bitte Bestaende und Preise aktualisieren, bevor die Handelsliste weitergeleitet wird."
        )

    drifts = live.get("position_drifts") or []
    if held_count > 0:
        if confirm_no_existing_holdings:
            raise HoldingsValuationIncompleteError(
                "Widerspruch: es sind Depotbestaende erfasst, bestaetigt wurde aber, "
                "dass kein Bestand existiert. Bitte die Angaben pruefen."
            )
        basis = HOLDINGS_BASIS_RECORDED_DEPOT
    else:
        if advisory_depot_recorded:
            raise HoldingsValuationIncompleteError(
                "Das Beratungsvermoegen enthaelt ein Wertschriftendepot, aber kein Bestand "
                "ist erfasst. Die Bestaetigung 'kein Bestand' ist dafuer nicht zulaessig; "
                "bitte die Depotbestaende erfassen."
            )
        if not investable_wealth_rappen or int(investable_wealth_rappen) <= 0:
            raise HoldingsValuationIncompleteError(
                "Ohne Depotbestand und ohne investierbares Beratungsvermoegen gibt es "
                "keine belegte Basis fuer die Handelsliste."
            )
        basis = HOLDINGS_BASIS_CONFIRMED_NO_HOLDINGS

    if counts["implied_positions_count"] == 0 and basis == HOLDINGS_BASIS_RECORDED_DEPOT:
        # Alles gehalten: unveraenderte Live-Zeilen, nur die Herkunft markiert.
        return (
            [{**entry, "holding_origin": HOLDING_ORIGIN_HELD} for entry in drifts],
            int(live.get("live_total_value_rappen") or 0),
            basis,
        )

    present = [entry.get("holding_present") for entry in drifts]
    held_rows = sum(1 for flag in present if flag is True)
    if (
        any(not isinstance(flag, bool) for flag in present)
        or held_rows != held_count
        or len(drifts) - held_rows != counts["implied_positions_count"]
    ):
        raise HoldingsValuationIncompleteError(
            "Die Zuordnung gehaltener und nicht gehaltener Positionen ist nicht "
            "belegt (Zaehler und Zeilen stimmen nicht ueberein). Keine Weiterleitung moeglich."
        )
    for entry in drifts:
        if entry["holding_present"] and (
            not str(entry.get("holding_as_of_date") or "").strip()
            or int(entry.get("current_market_value_rappen") or 0) <= 0
        ):
            raise HoldingsValuationIncompleteError(
                "Das erfasste Depot ist nicht vollstaendig belegt: "
                f"{entry.get('product_name') or entry.get('product_id')} hat keinen "
                "Bestands-Stichtag oder keinen Bestandswert. Ohne vollstaendiges Depot "
                "darf ein nicht erfasstes Produkt nicht als Nullbestand gelten."
            )

    if basis == HOLDINGS_BASIS_RECORDED_DEPOT:
        total = sum(int(entry["current_market_value_rappen"]) for entry in drifts if entry["holding_present"])
    else:
        total = int(investable_wealth_rappen)
    entries = []
    for entry in drifts:
        row = dict(entry)
        # Quelle ist der Run-Betrag, nicht der Live-SOLL der bisherigen Basis.
        row["target_amount_rappen"] = entry.get("run_target_amount_rappen", entry.get("target_amount_rappen"))
        row.setdefault("latest_price_rappen", None)
        row.setdefault("reference_price_rappen", None)
        if entry["holding_present"]:
            row["holding_origin"] = HOLDING_ORIGIN_HELD
        else:
            row.update({
                "holding_origin": HOLDING_ORIGIN_NOT_HELD,
                "valuation_basis": HOLDING_ORIGIN_NOT_HELD,
                "current_market_value_rappen": 0,
                "current_units_milli": 0,
            })
        entries.append(row)
    return _build_live_position_drifts(entries, total), total, basis


def _advisory_depot_recorded(db: Session, mandate: Mandate) -> bool:
    """Enthaelt das Beratungsvermoegen des Kunden ein Wertschriftendepot mit
    Wert? Dann muss ein Bestand existieren (keine Neugeld-Bestaetigung)."""
    rows = db.query(WealthPosition.assignment, WealthPosition.is_active).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.position_type == "Depot",
        WealthPosition.current_value_rappen > 0,
    ).all()
    return any(
        row.is_active != 0 and str(row.assignment or "").strip() in ("Beratungsvermögen", "Beratungsvermoegen")
        for row in rows
    )


def snapshot_handoff_trades(db: Session, mandate: Mandate, run: RecommendationRun, user_id: str) -> tuple[list[dict], int]:
    """Liefert (trades, live_total_value_rappen) -- siehe ``snapshot_handoff``."""
    trades, total_value_rappen, _basis = snapshot_handoff(db, mandate, run, user_id)
    return trades, total_value_rappen


def snapshot_handoff(
    db: Session, mandate: Mandate, run: RecommendationRun, user_id: str,
    *, confirm_no_existing_holdings: bool = False,
) -> tuple[list[dict], int, str]:
    """Liefert (trades, Basis-Total, holdings_basis) fuer eine neue Weiterleitung.

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
    if not (live.get("position_drifts") or []) or int(live.get("live_total_value_rappen") or 0) <= 0:
        raise NoTradeListAvailableError("Keine Live-Rebalancing-Daten fuer diesen Lauf verfuegbar.")
    drifts, total_value_rappen, holdings_basis = resolve_handoff_holdings_basis(
        live,
        confirm_no_existing_holdings=confirm_no_existing_holdings,
        advisory_depot_recorded=confirm_no_existing_holdings and _advisory_depot_recorded(db, mandate),
        investable_wealth_rappen=payload.get("investable_advisory_wealth_rappen"),
    )

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
    return trades, total_value_rappen, holdings_basis


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


def _normalized_recipient(name: str | None) -> str:
    return " ".join(str(name or "").split()).casefold()


def handoff_business_key_hash(
    *, mandate_id: str, run_id: str, trades: list[dict], total_value_rappen: int, recipient_name: str,
) -> str:
    """HANDOFF-IDEMPOTENCY-001: SHA-256 der fachlichen Identitaet einer
    Weiterleitung -- Mandat, Run, kanonischer Trade-Snapshot, Live-Total und
    (normalisierter) Empfaenger. Ein identischer Retry ergibt denselben
    Schluessel; jede fachliche Aenderung einen neuen."""
    payload = {
        "schema": "PortfolioHandoffBusinessKeyV1",
        "mandate_id": str(mandate_id),
        "recommendation_run_id": str(run_id),
        "live_total_value_rappen": int(total_value_rappen),
        "recipient": _normalized_recipient(recipient_name),
        "trades": trades,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
