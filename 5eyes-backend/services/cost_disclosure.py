"""Ex-ante cost disclosure for the Advisory-Report.

The service keeps calculation and persistence access outside the PDF layer.
Amounts are stored in Rappen and rates in basis points. Unknown costs are never
silently treated as zero.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session


DEFAULT_TRANSACTION_COST_BPS = 15

_ANNUAL_RATE_KEYS = (
    (
        ("default_advisory_fee_bps", "advisory_fee_bps"),
        "Beratungs-/Verwaltungsgebühr",
    ),
    (
        ("management_fee_bps", "portfolio_management_fee_bps"),
        "Vermögensverwaltungsgebühr",
    ),
    (
        ("custody_fee_bps", "depot_fee_bps"),
        "Depot-/Verwahrgebühr",
    ),
    (
        ("platform_fee_bps",),
        "Plattformgebühr",
    ),
)
_ONE_TIME_RATE_KEYS = (
    (
        ("onboarding_fee_bps", "setup_fee_bps", "initial_fee_bps"),
        "Einrichtungs-/Startgebühr",
    ),
    (
        ("entry_fee_bps",),
        "Einstiegsgebühr",
    ),
)


def build_cost_disclosure(db: Session, mandate: Any) -> dict[str, Any]:
    """Build a stable ex-ante cost payload for one mandate.

    The latest recommendation is the primary source because it freezes the fee
    assumptions used when the portfolio was generated. The current policy is a
    fallback only when the run does not contain a fee snapshot.
    """
    from models.allocation import OptimizerPolicy, TargetAllocation
    from models.review import (
        ConflictOfInterestDisclosure, Product, ProductUniverseEntry,
        RecommendationPosition, RecommendationRun,
    )

    latest_run = (
        db.query(RecommendationRun)
        .filter(RecommendationRun.mandate_id == mandate.id)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    if latest_run is None:
        return _pending_payload(
            "Noch keine Portfolioempfehlung vorhanden; ein konkreter "
            "Ex-ante-Kostenausweis kann noch nicht berechnet werden."
        )

    fee_model = _parse_fee_model(getattr(latest_run, "fee_assumptions_json", None))
    if not fee_model:
        policy = (
            db.query(OptimizerPolicy)
            .filter(OptimizerPolicy.id == latest_run.policy_id)
            .first()
        )
        fee_model = _parse_fee_model(getattr(policy, "fee_model_json", None))

    rows = (
        db.query(RecommendationPosition, Product)
        .join(Product, Product.id == RecommendationPosition.product_id)
        .filter(RecommendationPosition.run_id == latest_run.id)
        .all()
    )
    # 2026-07-27 (Fonds-Kuratierung): eine Verwaltung kann fuer ein Produkt
    # eine eigene, ausgehandelte Gebuehr hinterlegt haben (ProductUniverseEntry.
    # override_ter_bps) -- live nachgeschlagen (kein Snapshot), damit eine
    # spaetere Korrektur der Konditionen sofort im naechsten Kostenausweis
    # wirkt. Betrifft NUR diesen Tenant, das globale Produkt bleibt unveraendert.
    # mandate.tenant_id=NULL -> DEFAULT_TENANT_ID ('main'), gleiches Muster wie
    # services/auth.py::_resolve_tenant_id_for_user + portfolio_engine-Filter.
    ter_bps_overrides: dict[str, int] = {}
    if rows:
        from models.tenant import DEFAULT_TENANT_ID
        tenant_id = getattr(mandate, "tenant_id", None) or DEFAULT_TENANT_ID
        jurisdiction = getattr(mandate, "jurisdiction", None) or "CH"
        product_ids = {product.id for _, product in rows}
        override_entries = (
            db.query(ProductUniverseEntry)
            .filter(
                ProductUniverseEntry.tenant_id == tenant_id,
                ProductUniverseEntry.jurisdiction == jurisdiction,
                ProductUniverseEntry.product_id.in_(product_ids),
                ProductUniverseEntry.deleted_at.is_(None),
                ProductUniverseEntry.override_ter_bps.is_not(None),
            )
            .all()
        )
        ter_bps_overrides = {
            entry.product_id: int(entry.override_ter_bps) for entry in override_entries
        }
    positions = [
        {
            "amount_rappen": int(
                getattr(position, "target_amount_rappen", 0)
                or getattr(position, "current_amount_rappen", 0)
                or 0
            ),
            "weight_bps": int(getattr(position, "target_weight_bps", 0) or 0),
            "ter_bps": (
                ter_bps_overrides[product.id]
                if product.id in ter_bps_overrides
                else (
                    int(product.ter_bps)
                    if getattr(product, "ter_bps", None) is not None
                    else None
                )
            ),
        }
        for position, product in rows
    ]

    target_allocation = None
    target_allocation_id = getattr(latest_run, "target_allocation_id", None)
    if target_allocation_id:
        target_allocation = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.id == target_allocation_id)
            .first()
        )
    if target_allocation is None:
        target_allocation = (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_current == 1,
                TargetAllocation.deleted_at.is_(None),
            )
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )

    advisory_wealth = int(
        getattr(target_allocation, "advisory_wealth_at_generation_rappen", 0)
        or 0
    )
    # 2026-07-27 (Retrozessions-Feature): offengelegte, nicht-geloeschte
    # Interessenkonflikte mit einer bezifferten Retrozession fliessen in den
    # Kostenausweis ein (Offenlegungspflicht, siehe calculate_cost_disclosure).
    disclosure_rows = (
        db.query(ConflictOfInterestDisclosure)
        .filter(
            ConflictOfInterestDisclosure.mandate_id == mandate.id,
            ConflictOfInterestDisclosure.deleted_at.is_(None),
            ConflictOfInterestDisclosure.inducement_amount_rappen.isnot(None),
        )
        .all()
    )
    inducements = [
        {
            "amount_rappen": int(row.inducement_amount_rappen or 0),
            "frequency": row.inducement_frequency,
            "reimbursed_to_client": bool(row.reimbursed_to_client),
            "provider": row.inducement_provider,
        }
        for row in disclosure_rows
    ]
    return calculate_cost_disclosure(
        advisory_wealth_rappen=advisory_wealth,
        positions=positions,
        fee_model=fee_model,
        transaction_cost_bps=_first_int(
            fee_model,
            ("transaction_cost_bps", "estimated_transaction_cost_bps"),
            default=DEFAULT_TRANSACTION_COST_BPS,
        ),
        inducements=inducements,
        source_run_id=str(latest_run.id),
        as_of=str(getattr(latest_run, "created_at", "") or ""),
    )


def calculate_cost_disclosure(
    *,
    advisory_wealth_rappen: int,
    positions: Iterable[Mapping[str, Any]],
    fee_model: Mapping[str, Any] | str | None,
    transaction_cost_bps: int = DEFAULT_TRANSACTION_COST_BPS,
    inducements: Iterable[Mapping[str, Any]] | None = None,
    source_run_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Calculate one-time, annual and first-year cost totals.

    Product TER is calculated on the invested product volume. Service fees are
    calculated on advisory wealth. Totals are expressed as CHF amounts and as
    equivalent basis points of advisory wealth.
    """
    fee_data = _parse_fee_model(fee_model)
    clean_positions = [
        {
            "amount_rappen": max(0, _safe_int(item.get("amount_rappen"))),
            "weight_bps": max(0, _safe_int(item.get("weight_bps"))),
            "ter_bps": _optional_non_negative_int(item.get("ter_bps")),
        }
        for item in positions
    ]
    invested_amount = sum(item["amount_rappen"] for item in clean_positions)
    advisory_wealth = max(0, _safe_int(advisory_wealth_rappen))
    # FIDLEG: ist das echte Beratungsvermögen nicht erfasst, wird als Näherung das
    # investierte Produktvolumen als Gebührenbasis genutzt. Dann darf die Basis NICHT
    # als "Beratungsvermögen" etikettiert werden (irreführend, und bei nicht
    # investiertem Barvermögen wäre die Jahresgebühr sonst zu tief ausgewiesen).
    advisory_wealth_provided = advisory_wealth > 0
    advisory_basis_label = (
        "Beratungsvermögen" if advisory_wealth_provided else "Empfohlenes Produktvolumen"
    )
    if advisory_wealth <= 0:
        advisory_wealth = invested_amount
    if invested_amount <= 0 and advisory_wealth <= 0:
        return _pending_payload(
            "Keine belastbare Anlagebasis vorhanden; Kosten können noch "
            "nicht als Betrag ausgewiesen werden."
        )

    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    configured_annual_keys: set[str] = set()
    for keys, label in _ANNUAL_RATE_KEYS:
        key, rate = _first_present_rate(fee_data, keys)
        if key is None:
            continue
        configured_annual_keys.add(key)
        items.append(_rate_item(
            key=key,
            label=label,
            category="Dienstleistungskosten",
            frequency="jährlich",
            rate_bps=rate,
            basis_rappen=advisory_wealth,
            basis_label=advisory_basis_label,
            source="Gebührenmodell der Empfehlung",
            is_estimate=False,
        ))

    service_fee_known = bool(configured_annual_keys)
    if not service_fee_known:
        warnings.append(
            "Beratungs- oder Verwaltungsgebühren sind im Gebührenmodell "
            "nicht hinterlegt und deshalb nicht im Total enthalten."
        )
    elif not advisory_wealth_provided:
        warnings.append(
            "Beratungsvermögen war nicht erfasst; die jährlichen Dienstleistungs"
            "kosten sind auf das empfohlene Produktvolumen bezogen und können bei "
            "nicht investiertem Vermögen zu tief ausfallen."
        )

    for keys, label in _ONE_TIME_RATE_KEYS:
        key, rate = _first_present_rate(fee_data, keys)
        if key is None:
            continue
        items.append(_rate_item(
            key=key,
            label=label,
            category="Einmalige Dienstleistungskosten",
            frequency="einmalig",
            rate_bps=rate,
            basis_rappen=advisory_wealth,
            basis_label="Beratungsvermögen",
            source="Gebührenmodell der Empfehlung",
            is_estimate=False,
        ))

    ter_known_amount = sum(
        item["amount_rappen"]
        for item in clean_positions
        if item["ter_bps"] is not None
    )
    ter_cost_rappen = sum(
        int(round(item["amount_rappen"] * int(item["ter_bps"]) / 10000))
        for item in clean_positions
        if item["ter_bps"] is not None
    )
    ter_coverage_bps = (
        int(round(ter_known_amount / invested_amount * 10000))
        if invested_amount > 0
        else 0
    )
    if ter_known_amount > 0:
        ter_rate_bps = int(round(ter_cost_rappen / invested_amount * 10000))
        items.append({
            "key": "product_ter",
            "label": "Produktkosten (gewichtete TER)",
            "category": "Produktkosten",
            "frequency": "jährlich",
            "rate_bps": ter_rate_bps,
            "amount_rappen": ter_cost_rappen,
            "basis_rappen": invested_amount,
            "basis_label": "Empfohlenes Produktvolumen",
            "source": "TER der empfohlenen Produkte",
            "is_estimate": ter_coverage_bps < 10000,
            "included_in_total": True,
        })
    else:
        warnings.append(
            "Produktkosten (TER) sind für die empfohlenen Produkte nicht "
            "hinterlegt und deshalb nicht im Total enthalten."
        )
    if 0 < ter_coverage_bps < 10000:
        warnings.append(
            "Die TER-Abdeckung ist unvollständig; ausgewiesen werden nur "
            "die bekannten Produktkosten."
        )

    transaction_rate = max(0, _safe_int(transaction_cost_bps))
    if invested_amount > 0 and transaction_rate > 0:
        items.append(_rate_item(
            key="initial_transaction_costs",
            label="Transaktionskosten Erstumsetzung",
            category="Erwerbs-/Transaktionskosten",
            frequency="einmalig",
            rate_bps=transaction_rate,
            basis_rappen=invested_amount,
            basis_label="Empfohlenes Produktvolumen",
            source="Konservative Ex-ante-Annahme",
            is_estimate=True,
        ))
        warnings.append(
            "Transaktionskosten sind eine Ex-ante-Schätzung für die "
            "Erstumsetzung; tatsächliche Spreads, Courtagen und "
            "Börsenabgaben können abweichen."
        )

    # 2026-07-27 (Retrozessions-Feature): FIDLEG Art. 25/26 + BGE 132 III 460
    # verlangen Offenlegung von Vergütungen Dritter UNABHAENGIG davon, ob sie
    # an den Kunden zurückerstattet werden -- deshalb wird JEDE Retrozession
    # als Cost-Item ausgewiesen. Nur die tatsächliche RUECKERSTATTUNG (der
    # Kunde erhält netto weniger Kosten) fliesst als negativer Betrag ins
    # Total ein; eine vom Berater EINBEHALTENE Retrozession ist bereits Teil
    # der oben ausgewiesenen Produkt-/Dienstleistungskosten (kein separater
    # Kostenpunkt) und wird deshalb NICHT zusätzlich addiert (Doppelzähl-
    # Vermeidung), aber transparent als Warnung genannt.
    for inducement in (inducements or []):
        amount = _safe_int(inducement.get("amount_rappen"))
        if amount <= 0:
            continue
        frequency_raw = str(inducement.get("frequency") or "").strip().lower()
        is_annual = frequency_raw in ("", "jährlich", "jaehrlich", "annual", "annually", "yearly")
        reimbursed = bool(inducement.get("reimbursed_to_client"))
        provider = str(inducement.get("provider") or "Produktanbieter").strip() or "Produktanbieter"
        if reimbursed:
            items.append({
                "key": "retrocession_reimbursed",
                "label": f"Rückerstattung Vergütung von Dritten ({provider})",
                "category": "Vergütungen von Dritten",
                "frequency": "jährlich" if is_annual else frequency_raw,
                "rate_bps": None,
                "amount_rappen": -amount,
                "basis_rappen": advisory_wealth,
                "basis_label": advisory_basis_label,
                "source": "Interessenkonflikt-Offenlegung (Retrozession, zurückerstattet)",
                "is_estimate": False,
                "included_in_total": is_annual,
            })
            if not is_annual:
                warnings.append(
                    f"Eine zurückerstattete Vergütung von Dritten ({provider}) mit "
                    "nicht-jährlicher Frequenz ist offengelegt, aber nicht im Total verrechnet."
                )
        else:
            items.append({
                "key": "retrocession_disclosed",
                "label": f"Vergütung von Dritten, einbehalten ({provider})",
                "category": "Vergütungen von Dritten",
                "frequency": "jährlich" if is_annual else frequency_raw,
                "rate_bps": None,
                "amount_rappen": amount,
                "basis_rappen": advisory_wealth,
                "basis_label": advisory_basis_label,
                "source": "Interessenkonflikt-Offenlegung (Retrozession, Verzicht dokumentiert)",
                "is_estimate": False,
                "included_in_total": False,
            })
            warnings.append(
                f"Vergütung von Dritten ({provider}) ist offengelegt, wird gemäss "
                "dokumentiertem Kundenverzicht aber vom Berater einbehalten und ist "
                "bereits Teil der ausgewiesenen Kosten -- nicht zusätzlich im Total."
            )

    one_time_amount = sum(
        int(item.get("amount_rappen") or 0)
        for item in items
        if item.get("frequency") == "einmalig" and item.get("included_in_total", True)
    )
    annual_amount = sum(
        int(item.get("amount_rappen") or 0)
        for item in items
        if item.get("frequency") == "jährlich" and item.get("included_in_total", True)
    )
    first_year_amount = one_time_amount + annual_amount

    return {
        "data_pending": False,
        "currency": "CHF",
        "as_of": as_of,
        "source_run_id": source_run_id,
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": advisory_wealth,
        "invested_amount_rappen": invested_amount,
        "product_cost_coverage_bps": ter_coverage_bps,
        "cost_items": items,
        "totals": {
            "one_time_rappen": one_time_amount,
            "one_time_bps": _equivalent_bps(one_time_amount, advisory_wealth),
            "annual_rappen": annual_amount,
            "annual_bps": _equivalent_bps(annual_amount, advisory_wealth),
            "first_year_rappen": first_year_amount,
            "first_year_bps": _equivalent_bps(first_year_amount, advisory_wealth),
        },
        "is_complete": service_fee_known and ter_coverage_bps == 10000,
        "has_estimates": any(bool(item.get("is_estimate")) for item in items),
        "warnings": warnings,
    }


def _rate_item(
    *,
    key: str,
    label: str,
    category: str,
    frequency: str,
    rate_bps: int,
    basis_rappen: int,
    basis_label: str,
    source: str,
    is_estimate: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "category": category,
        "frequency": frequency,
        "rate_bps": rate_bps,
        "amount_rappen": int(round(basis_rappen * rate_bps / 10000)),
        "basis_rappen": basis_rappen,
        "basis_label": basis_label,
        "source": source,
        "is_estimate": is_estimate,
        "included_in_total": True,
    }


def _parse_fee_model(raw: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _first_present_rate(
    fee_model: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, int]:
    for key in keys:
        if key not in fee_model or fee_model.get(key) is None:
            continue
        return key, max(0, _safe_int(fee_model.get(key)))
    return None, 0


def _first_int(
    fee_model: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: int,
) -> int:
    for key in keys:
        if key in fee_model and fee_model.get(key) is not None:
            return max(0, _safe_int(fee_model.get(key)))
    return default


def _equivalent_bps(amount_rappen: int, basis_rappen: int) -> int | None:
    if basis_rappen <= 0:
        return None
    return int(round(amount_rappen / basis_rappen * 10000))


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    return max(0, _safe_int(value))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pending_payload(note: str) -> dict[str, Any]:
    return {
        "data_pending": True,
        "currency": "CHF",
        "as_of": None,
        "source_run_id": None,
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": 0,
        "invested_amount_rappen": 0,
        "product_cost_coverage_bps": 0,
        "cost_items": [],
        "totals": {
            "one_time_rappen": 0,
            "one_time_bps": None,
            "annual_rappen": 0,
            "annual_bps": None,
            "first_year_rappen": 0,
            "first_year_bps": None,
        },
        "is_complete": False,
        "has_estimates": False,
        "warnings": [note],
    }
