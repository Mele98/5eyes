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


_PENSION_KEY = "pension_bound"


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


def _largest_remainder_bps(amounts: dict, base_rappen: int) -> dict[str, int]:
    """MATH-DISP-1: Gewichte in bps, deren Summe exakt 10'000 ergibt.

    Voraussetzung: base_rappen > 0 und sum(amounts) == base_rappen. Jedes
    Gewicht liegt < 1 bp neben dem exakten Anteil (Largest-Remainder).
    Gleichstand beim Rest: groesserer Betrag zuerst, dann Bucket-Reihenfolge.
    """
    keys = list(amounts)
    floors: dict[str, int] = {}
    remainders: dict[str, int] = {}
    for key in keys:
        floors[key], remainders[key] = divmod(int(amounts[key]) * 10_000, base_rappen)
    missing = 10_000 - sum(floors.values())
    order = sorted(
        keys,
        key=lambda k: (-remainders[k], -int(amounts[k]), keys.index(k)),
    )
    for key in order[:missing]:
        floors[key] += 1
    return floors


def _build_total_wealth_allocation(
    total_summary: PortfolioSummary,
    total_liabilities_rappen: int,
    total_wealth_rappen: int,
    target_weights_bps: dict,
    direct_property_rappen: int | None = None,
    other_liabilities_rappen: int = 0,
    foundation_projection: dict | None = None,
) -> dict:
    """Gesamtvermögens-Allokation mit der Immobilie als fixem Fundament (Sockel).

    Produkt-Entscheid 2026-07-13: IST und SOLL werden auf dem GESAMTvermögen
    dargestellt ("mit allem"), nicht nur auf dem Beratungsvermögen. Die Immobilie
    aus direkten Liegenschaften ist ein konstanter, nicht-optimierbarer Block
    ("Fundament", netto Hypothek) — identisch in IST und SOLL. Kotierte
    Immobilienfonds/REITs bleiben dagegen Teil des investierbaren Finanzmixes
    und erhalten die normale SAA-Immobilienquote.

    Verbindlichkeiten (TOTAL-WEALTH-LIABILITY-001):
    - `total_liabilities_rappen` = NUR Hypotheken (GESAMTVERMOEGEN-FOUNDATION-
      LIABILITY-SCOPE-001). Sie werden zuerst mit der Direktimmobilie
      verrechnet; `foundation_rappen` = Immobilie netto Hypothek (unverändert).
    - `other_liabilities_rappen` = alle übrigen Schulden (Privatkredit etc.).
      Sie sind in `total_wealth_rappen` (SOLL-Basis) bereits abgezogen und
      müssen deshalb auch im IST abgezogen werden — über dieselbe Kaskade wie
      ein Hypotheken-Überhang: Liquidität -> Obligationen -> Alternative ->
      Aktien -> kotierte Immobilien -> erst ganz zuletzt das Fundament. Das
      Fundament wird also nie VOR den Finanz-Buckets angetastet (SCOPE-001-
      Garantie bleibt). Der davon belastete Teil steht in
      `foundation_charged_other_liabilities_rappen`, der im Netto-Vermögen
      verbleibende Teil in `foundation_in_net_wealth_rappen` — nur dieser ist
      der fixe Block in IST und SOLL.

    Invariante (Netto-Gesamtvermögen > 0, konsistente Eingaben): Beträge von
    IST und SOLL summieren je exakt auf `total_base_rappen`, Gewichte je exakt
    auf 10'000 bps (Largest-Remainder-Rundung, MATH-DISP-1).

    Netto-Gesamtvermögen <= 0 (Schulden >= Aktiven): fail-soft — alle Beträge
    und Gewichte 0, `net_wealth_non_positive=True`, der nicht durch Aktiven
    gedeckte Rest in `uncovered_liabilities_rappen`. Keine negativen Beträge,
    keine Gewichte > 100 %.

    REIN ADDITIV: beeinflusst Optimizer/Reserve/Ziele NICHT — nur die Anzeige.
    Der Optimizer/die Reserve rechnen unverändert auf dem Beratungsvermögen.

    `foundation_projection` (TOTAL-WEALTH-LIABILITY-001, Snapshot-Parität):
    die FX-normalisierte Fundament-Projektion der Engine
    (`_build_external_foundation_projection`). Liefert die Direktimmobilie
    (Jahr 0), falls `direct_property_rappen` fehlt, und wird als
    `projection_basis` mitpubliziert, damit Browser-Chart und Bericht dieselbe
    Netto-Basis, dieselbe Fundament-Zerlegung und dieselben Jahresserien
    verwenden, statt sie aus rohen Positionen nachzubauen.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bps

    amounts = {k: max(0, int(total_summary.amounts_rappen.get(k, 0))) for k in BUCKET_FIELDS}
    # VORSORGE-PROJECTION-001 (2026-10-18): externe Vorsorge ist eine eigene,
    # nicht verwaltete Kategorie "Vorsorge (gebunden)" -- wie das Fundament ein
    # fixer Block in IST und SOLL, nie umgeschichtet.
    pension_bound = max(0, int(getattr(total_summary, "pension_bound_rappen", 0) or 0))
    liabilities = max(0, int(total_liabilities_rappen or 0))
    other_liabilities = max(0, int(other_liabilities_rappen or 0))
    total_base = max(0, int(total_wealth_rappen or 0))
    # Only position_type='Immobilien' is the fixed direct-property foundation.
    # Listed funds/REITs inside depots remain an investable real-estate sleeve.
    real_estate_gross = amounts["real_estate"]
    if direct_property_rappen is None and foundation_projection:
        direct_property_rappen = (foundation_projection.get("property_series_rappen") or [0])[0]
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
    # Hypotheken-Überhang (Hypothek > Immobilie) + alle übrigen Schulden.
    liab_remaining = (
        max(0, liabilities - direct_property_gross) + other_liabilities
    )

    # IST (heutiger Mix, total): heutige Finanz-Buckets + Fundament; offene
    # Schulden werden kaskadiert abgezogen (Netto-Konsistenz). Innerhalb der
    # Immobilien zuerst der kotierte Teil, das Fundament ganz zuletzt.
    current_amounts = dict(amounts)
    current_amounts["real_estate"] = listed_real_estate_rappen
    for key in ("liquidity", "bonds", "alternatives", "equities", "real_estate"):
        if liab_remaining <= 0:
            break
        removable = min(liab_remaining, current_amounts[key])
        current_amounts[key] -= removable
        liab_remaining -= removable
    # Gebundene Vorsorge wird nach den Finanz-Buckets, aber vor dem
    # Fundament belastet (Fundament bleibt zuletzt, SCOPE-001-Garantie).
    pension_charged = min(liab_remaining, pension_bound)
    pension_in_net_wealth = pension_bound - pension_charged
    liab_remaining -= pension_charged
    foundation_charged = min(liab_remaining, foundation_rappen)
    foundation_in_net_wealth = foundation_rappen - foundation_charged
    uncovered_liabilities = liab_remaining - foundation_charged
    current_amounts["real_estate"] += foundation_in_net_wealth
    financial_base_rappen = max(
        0, total_base - foundation_in_net_wealth - pension_in_net_wealth
    )

    # SOLL (Ziel, total): the fixed foundation stays in place. The financial
    # part follows the full investable SAA, including listed real estate.
    tgt = _total_financial_target_weights(target_weights_bps)
    target_amounts = {k: 0 for k in BUCKET_FIELDS}
    target_amounts["real_estate"] = foundation_in_net_wealth
    if sum(tgt.values()) > 0 and financial_base_rappen > 0:
        for k in BUCKET_FIELDS:
            target_amounts[k] += int(
                round(financial_base_rappen * tgt[k] / 10_000)
            )
        # Rundungsrest dem grössten Finanz-Bucket zuschlagen -> Summe exakt = Finanzbasis.
        allocated_financial = sum(target_amounts.values()) - foundation_in_net_wealth
        residual = financial_base_rappen - allocated_financial
        if residual:
            biggest = max(BUCKET_FIELDS, key=lambda k: tgt[k])
            target_amounts[biggest] += residual
    else:
        # Kein Finanzziel / kein liquider Teil → keine Umschichtung (Fallback = IST).
        for k in BUCKET_FIELDS:
            target_amounts[k] = current_amounts[k]

    if pension_bound > 0:
        current_amounts[_PENSION_KEY] = pension_in_net_wealth
        target_amounts[_PENSION_KEY] = pension_in_net_wealth

    def _weights(bucket_amounts: dict) -> dict[str, int]:
        # MATH-DISP-1: exakt 10'000 bps, sofern die Beträge die Basis exakt
        # zerlegen. Sonst (inkonsistente Eingaben / Basis 0 -> überall 0)
        # bisherige Einzelrundung, damit kein Fehler kaschiert wird.
        if total_base > 0 and sum(bucket_amounts.values()) == total_base:
            return _largest_remainder_bps(bucket_amounts, total_base)
        return {k: _bps(bucket_amounts[k], total_base) for k in bucket_amounts}

    current_weights = _weights(current_amounts)
    target_weights = _weights(target_amounts)
    allocation = []
    for key in BUCKET_FIELDS:
        allocation.append({
            "asset_class": BUCKET_LABELS[key],
            "current_weight_bps": current_weights[key],
            "target_weight_bps": target_weights[key],
            "current_amount_rappen": int(current_amounts[key]),
            "target_amount_rappen": int(target_amounts[key]),
            "is_foundation": key == "real_estate" and direct_property_gross > 0,
            "foundation_component_rappen": (
                int(foundation_in_net_wealth) if key == "real_estate" else 0
            ),
            "investable_component_rappen": (
                int(current_amounts[key] - foundation_in_net_wealth)
                if key == "real_estate"
                else int(current_amounts[key])
            ),
        })
    if pension_bound > 0:
        from services.portfolio_engine_pension_positions import PENSION_BOUND_LABEL

        allocation.append({
            "asset_class": PENSION_BOUND_LABEL,
            "current_weight_bps": current_weights[_PENSION_KEY],
            "target_weight_bps": target_weights[_PENSION_KEY],
            "current_amount_rappen": int(pension_in_net_wealth),
            "target_amount_rappen": int(pension_in_net_wealth),
            "is_foundation": False,
            "is_pension_bound": True,
            "foundation_component_rappen": 0,
            "investable_component_rappen": 0,
        })
    payload_extra = (
        {
            "pension_bound_rappen": int(pension_bound),
            "pension_in_net_wealth_rappen": int(pension_in_net_wealth),
        }
        if pension_bound > 0
        else {}
    )
    return {
        **payload_extra,
        "basis": "gesamtvermoegen",
        # Immobilie netto Hypothek (SCOPE-001-Vertrag, unverändert).
        "foundation_rappen": int(foundation_rappen),
        # Davon im Netto-Gesamtvermögen verbleibend (= fixer Block IST/SOLL).
        "foundation_in_net_wealth_rappen": int(foundation_in_net_wealth),
        "foundation_charged_other_liabilities_rappen": int(foundation_charged),
        "financial_base_rappen": int(financial_base_rappen),
        "total_base_rappen": int(total_base),
        "net_wealth_non_positive": total_base <= 0,
        "uncovered_liabilities_rappen": int(uncovered_liabilities),
        "allocation": allocation,
        **(
            {"projection_basis": total_wealth_projection_basis(
                foundation_projection,
                total_base_rappen=total_base,
                foundation_in_net_wealth_rappen=foundation_in_net_wealth,
                foundation_charged_other_liabilities_rappen=foundation_charged,
            )}
            if foundation_projection is not None
            else {}
        ),
    }


PROJECTION_BASIS_SCHEMA = "total-wealth-projection-basis/v1"


def total_wealth_projection_basis(
    foundation_projection: dict,
    *,
    total_base_rappen: int,
    foundation_in_net_wealth_rappen: int,
    foundation_charged_other_liabilities_rappen: int,
) -> dict:
    """Kanonische, FX-normalisierte Basis der Gesamtvermögens-Projektion.

    Single Source of Truth für den sichtbaren Chart (Monolith) und den Bericht:
    - `start_rappen`: Netto-Gesamtvermögen (= `total_base_rappen`, FX-normalisiert);
    - `foundation_in_net_wealth_rappen`: Fundament NACH der Liability-Kaskade
      (sonstige Schulden belasten zuerst die Finanz-Buckets, das Fundament
      zuletzt) -- der Sockel der Projektion;
    - `financial_net_rappen`: der rentierende Rest (Start minus Sockel);
    - Jahresserien Direktimmobilie / Verbindlichkeiten (alle, Hypotheken mit
      Tilgung) / Pledged-Asset aus derselben Engine-Projektion. Konsumenten
      verwenden nur deren Veränderung gegenüber Jahr 0, damit die
      Jahr-0-Zerlegung exakt dem Snapshot entspricht.
    `basis_hash` bindet alle Felder (SHA-256 über kanonisches JSON).
    """
    import hashlib
    import json

    def _series(key: str) -> list[int]:
        return [int(v) for v in (foundation_projection or {}).get(key) or []]

    start = max(0, int(total_base_rappen or 0))
    sockel = max(0, min(start, int(foundation_in_net_wealth_rappen or 0)))
    basis = {
        "schema": PROJECTION_BASIS_SCHEMA,
        "start_rappen": start,
        "foundation_in_net_wealth_rappen": sockel,
        "foundation_charged_other_liabilities_rappen": max(
            0, int(foundation_charged_other_liabilities_rappen or 0)
        ),
        "financial_net_rappen": start - sockel,
        "property_series_rappen": _series("property_series_rappen"),
        "liability_series_rappen": _series("liability_series_rappen"),
        "pledged_asset_series_rappen": _series("pledged_asset_series_rappen"),
    }
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"))
    basis["basis_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return basis


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
