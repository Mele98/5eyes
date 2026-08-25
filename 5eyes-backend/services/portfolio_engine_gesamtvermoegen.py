"""ADR-014, Schritt 1: Gesamtvermoegen-Cluster, extrahiert aus
`services/portfolio_engine.py` (God-Modul-Split, Welle 3.2).

Reine Datei-Grenz-Verschiebung, 0 Zeilen Fachlogik-Aenderung: die 4
Funktionen unten sind Byte-fuer-Byte-Kopien ihrer vormaligen Definitionen in
`portfolio_engine.py` (Zeilen 2380-2455, 2949-2972, 4816-4871 zum Zeitpunkt
der Extraktion, siehe ADR-014). `portfolio_engine.py` re-exportiert sie
weiterhin unter denselben Namen (Rueckwaerts-Kompatibilitaet fuer
`services/advisory_report.py`, `routers/clients.py` und alle bestehenden
Tests, die `from services.portfolio_engine import _wealth_inflow_series_rappen`
o.ae. nutzen).

Zirkular-Import-Haertung: `_build_total_wealth_allocation` braucht
BUCKET_FIELDS/BUCKET_LABELS/_bps aus `services.portfolio_engine`, das
umgekehrt (via Re-Export weiter unten in dieser Datei) von HIER importiert.
Ein Modul-Top-Level-Import waere nur sicher, wenn `portfolio_engine.py`
IMMER der Einstiegspunkt der Import-Kette ist -- verifiziert per direktem
Test aber NICHT der Fall (ein direkter `import
services.portfolio_engine_gesamtvermoegen` als allererster Import wuerde
mit ImportError auf einem partiell initialisierten Modul scheitern). Fix:
der Cross-Cluster-Import ist function-local (lazy), nicht Modul-Top-Level
-- dadurch ist dieses Modul in JEDER Import-Reihenfolge sicher importierbar.
`PortfolioSummary` im Type-Hint unten braucht dank `from __future__ import
annotations` keinen echten Import (PEP 563, Annotationen sind Strings).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.portfolio_engine import PortfolioSummary


_TOTAL_FINANCIAL_BUCKETS = (
    "equities",
    "bonds",
    "real_estate",
    "alternatives",
    "liquidity",
)


def _total_financial_target_weights(target_weights_bps: dict) -> dict[str, int]:
    """Normalize the investable SAA once for display and all total paths."""
    raw = {
        key: max(0, int((target_weights_bps or {}).get(key, 0) or 0))
        for key in _TOTAL_FINANCIAL_BUCKETS
    }
    total = sum(raw.values())
    if total <= 0:
        return {key: 0 for key in _TOTAL_FINANCIAL_BUCKETS}
    normalized = {
        key: int(round(value * 10_000 / total))
        for key, value in raw.items()
    }
    residual = 10_000 - sum(normalized.values())
    if residual:
        largest = max(_TOTAL_FINANCIAL_BUCKETS, key=lambda key: raw[key])
        normalized[largest] += residual
    return normalized


def _build_total_wealth_allocation(
    total_summary: PortfolioSummary,
    total_liabilities_rappen: int,
    total_wealth_rappen: int,
    target_weights_bps: dict,
    direct_property_rappen: int | None = None,
) -> dict:
    """Gesamtvermögens-Allokation mit der Immobilie als fixem Fundament (Sockel).

    Produkt-Entscheid 2026-07-13: IST und SOLL werden auf dem GESAMTvermögen
    dargestellt ("mit allem"), nicht nur auf dem Beratungsvermögen. Die Immobilie
    aus direkten Liegenschaften ist ein konstanter, nicht-optimierbarer Block
    ("Fundament", netto Hypothek) — identisch in IST und SOLL. Kotierte
    Immobilienfonds/REITs bleiben dagegen Teil des investierbaren Finanzmixes
    und erhalten die normale SAA-Immobilienquote.

    REIN ADDITIV: beeinflusst Optimizer/Reserve/Ziele NICHT — nur die Anzeige.
    Der Optimizer/die Reserve rechnen unverändert auf dem Beratungsvermögen.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bps

    amounts = {k: max(0, int(total_summary.amounts_rappen.get(k, 0))) for k in BUCKET_FIELDS}
    liabilities = max(0, int(total_liabilities_rappen or 0))
    total_base = max(0, int(total_wealth_rappen or 0))
    # Only position_type='Immobilien' is the fixed direct-property foundation.
    # Listed funds/REITs inside depots remain an investable real-estate sleeve.
    real_estate_gross = amounts["real_estate"]
    direct_property_gross = (
        real_estate_gross
        if direct_property_rappen is None
        else max(0, int(direct_property_rappen or 0))
    )
    if direct_property_gross > real_estate_gross:
        raise ValueError(
            "Direktimmobilien-Sockel übersteigt den Immobilien-Gesamtbetrag."
        )
    listed_real_estate_rappen = real_estate_gross - direct_property_gross
    foundation_rappen = max(0, direct_property_gross - liabilities)
    liab_remaining = max(0, liabilities - direct_property_gross)
    financial_base_rappen = max(0, total_base - foundation_rappen)

    # IST (heutiger Mix, total): Fundament + heutige Finanz-Buckets; ein Rest-
    # Hypothek-Überhang wird von der Liquidität abgezogen (Netto-Konsistenz).
    current_amounts = dict(amounts)
    current_amounts["real_estate"] = (
        listed_real_estate_rappen + foundation_rappen
    )
    for key in ("liquidity", "bonds", "alternatives", "equities", "real_estate"):
        if liab_remaining <= 0:
            break
        removable = min(liab_remaining, current_amounts[key])
        current_amounts[key] -= removable
        liab_remaining -= removable

    # SOLL (Ziel, total): the fixed foundation stays in place. The financial
    # part follows the full investable SAA, including listed real estate.
    tgt = _total_financial_target_weights(target_weights_bps)
    target_amounts = {k: 0 for k in BUCKET_FIELDS}
    target_amounts["real_estate"] = foundation_rappen
    if sum(tgt.values()) > 0 and financial_base_rappen > 0:
        for k in BUCKET_FIELDS:
            target_amounts[k] += int(
                round(financial_base_rappen * tgt[k] / 10_000)
            )
        # Rundungsrest dem grössten Finanz-Bucket zuschlagen -> Summe exakt = Finanzbasis.
        allocated_financial = sum(target_amounts.values()) - foundation_rappen
        residual = financial_base_rappen - allocated_financial
        if residual:
            biggest = max(BUCKET_FIELDS, key=lambda k: tgt[k])
            target_amounts[biggest] += residual
    else:
        # Kein Finanzziel / kein liquider Teil → keine Umschichtung (Fallback = IST).
        for k in BUCKET_FIELDS:
            target_amounts[k] = current_amounts[k]

    base = max(1, total_base)
    allocation = []
    for key in BUCKET_FIELDS:
        allocation.append({
            "asset_class": BUCKET_LABELS[key],
            "current_weight_bps": _bps(current_amounts[key], base),
            "target_weight_bps": _bps(target_amounts[key], base),
            "current_amount_rappen": int(current_amounts[key]),
            "target_amount_rappen": int(target_amounts[key]),
            "is_foundation": key == "real_estate" and direct_property_gross > 0,
            "foundation_component_rappen": (
                int(foundation_rappen) if key == "real_estate" else 0
            ),
            "investable_component_rappen": (
                int(current_amounts[key] - foundation_rappen)
                if key == "real_estate"
                else int(current_amounts[key])
            ),
        })
    return {
        "basis": "gesamtvermoegen",
        "foundation_rappen": int(foundation_rappen),
        "financial_base_rappen": int(financial_base_rappen),
        "total_base_rappen": int(total_base),
        "allocation": allocation,
    }


def _goal_uses_total_scope(goal) -> bool:
    """#83: True wenn das Ziel gegen das Gesamtvermoegen bewertet wird
    (goal_scope='Gesamtvermoegen'). Default ist 'Beratungsvermoegen'."""
    return "gesamt" in str(getattr(goal, "goal_scope", "") or "").strip().lower()


def _external_assets_inflation_value(
    base_rappen: int, years: int, inflation_series_bps: list[int] | None
) -> int:
    """#83 Gesamtvermoegen-Scope: externe Assets (Eigenheim etc.) wachsen
    KONSERVATIV nur mit der Teuerung — realer Zuwachs 0 % (User-Entscheid
    2026-06-19). Keine Volatilitaet -> in deterministischem UND Monte-Carlo-Pfad
    identisch addiert, daher KEIN MC-Drift (die fruehere B4-Falle). Default-Scope
    (Beratungsvermoegen) ruft das hier nie auf."""
    base = max(0, int(base_rappen or 0))
    if base <= 0:
        return 0
    series = list(inflation_series_bps or [])
    last_bps = int(series[-1]) if series else 150
    value = float(base)
    for idx in range(max(0, int(years or 0))):
        infl_bps = int(series[idx]) if idx < len(series) else last_bps
        value *= 1 + (infl_bps / 10000)
    return int(round(value))


def _wealth_inflow_series_rappen(
    inflows: list,
    projection_years: int,
    start_year: int,
    inflation_series_bps: list[int] | None,
) -> list[int]:
    """Sprint A1: konvertiert WealthInflow-Records in eine Year-Series.

    - is_recurring=0: Einmaliger Beitrag im expected_year
    - is_recurring=1 + frequency='jaehrlich': annual Beitrag ab expected_year
      ueber duration_years Jahre
    - is_recurring=1 + frequency='monatlich': annual = amount * 12, gleich wie oben
    - value_mode='real': Inflations-aufgezinst per offset

    Inflows fliessen ins Beratungsvermoegen, daher positiver Beitrag in der
    cashflow_projection_series_rappen.
    """
    series = [0] * max(0, int(projection_years or 0))
    if not series or not inflows:
        return series
    for infl in inflows:
        active = getattr(infl, "is_active", 1)
        if isinstance(active, bool) or not isinstance(active, int) or active not in (0, 1):
            raise ValueError("Vermoegenszufluss: is_active muss exakt 0 oder 1 sein.")
        if active == 0:
            continue
        base_amount = getattr(infl, "amount_rappen", None)
        year = getattr(infl, "expected_year", None)
        recurring_raw = getattr(infl, "is_recurring", None)
        duration_raw = getattr(infl, "duration_years", None)
        if isinstance(base_amount, bool) or not isinstance(base_amount, int) or base_amount <= 0:
            raise ValueError("Vermoegenszufluss: amount_rappen muss eine positive Ganzzahl sein.")
        if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
            raise ValueError("Vermoegenszufluss: expected_year muss zwischen 1900 und 2200 liegen.")
        if (
            isinstance(recurring_raw, bool)
            or not isinstance(recurring_raw, int)
            or recurring_raw not in (0, 1)
        ):
            raise ValueError("Vermoegenszufluss: is_recurring muss exakt 0 oder 1 sein.")
        recurring = recurring_raw == 1
        freq = str(getattr(infl, "frequency", "") or "").strip().lower()
        value_mode = str(getattr(infl, "value_mode", "") or "").strip().lower()
        if value_mode not in {"nominal", "real"}:
            raise ValueError("Vermoegenszufluss: value_mode muss nominal oder real sein.")
        if recurring:
            if freq not in {"jaehrlich", "monatlich"}:
                raise ValueError(
                    "Vermoegenszufluss: wiederkehrend erfordert frequency "
                    "jaehrlich oder monatlich."
                )
            if (
                isinstance(duration_raw, bool)
                or not isinstance(duration_raw, int)
                or not 1 <= duration_raw <= 99
            ):
                raise ValueError(
                    "Vermoegenszufluss: wiederkehrend erfordert duration_years "
                    "zwischen 1 und 99."
                )
            duration = duration_raw
        else:
            if freq not in {"", "einmalig"}:
                raise ValueError(
                    "Vermoegenszufluss: einmalig darf keine wiederkehrende "
                    "frequency besitzen."
                )
            if duration_raw not in (None, 0):
                raise ValueError(
                    "Vermoegenszufluss: einmalig darf keine duration_years besitzen."
                )
            duration = 0

        offset = year - int(start_year or 0)
        if offset < 0 or offset >= len(series):
            continue

        is_real = value_mode == "real"

        def _amount_at_offset(off: int, base: int) -> int:
            if not is_real or not inflation_series_bps:
                return base
            cum = 1.0
            for k in range(min(off, len(inflation_series_bps))):
                cum *= (1.0 + (int(inflation_series_bps[k]) / 10000.0))
            return int(round(base * cum))

        if recurring:
            annual_base = base_amount * 12 if freq == "monatlich" else base_amount
            last = min(len(series) - 1, offset + duration - 1)
            for off in range(offset, last + 1):
                series[off] += _amount_at_offset(off, annual_base)
        else:
            series[offset] += _amount_at_offset(offset, base_amount)
    return series
