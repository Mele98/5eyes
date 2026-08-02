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


def _build_total_wealth_allocation(
    total_summary: PortfolioSummary,
    total_liabilities_rappen: int,
    total_wealth_rappen: int,
    target_weights_bps: dict,
) -> dict:
    """Gesamtvermögens-Allokation mit der Immobilie als fixem Fundament (Sockel).

    Produkt-Entscheid 2026-07-13: IST und SOLL werden auf dem GESAMTvermögen
    dargestellt ("mit allem"), nicht nur auf dem Beratungsvermögen. Die Immobilie
    (real_estate) ist ein konstanter, nicht-optimierbarer Block ("Fundament",
    netto Hypothek) — identisch in IST und SOLL. Nur das liquide Finanzvermögen
    (der Rest) wird über die Asset-Klassen optimiert; die Ziel-% werden dafür ohne
    real_estate renormiert, weil das Haus die Immobilienquote bereits stellt.

    REIN ADDITIV: beeinflusst Optimizer/Reserve/Ziele NICHT — nur die Anzeige.
    Der Optimizer/die Reserve rechnen unverändert auf dem Beratungsvermögen.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, _bps

    amounts = {k: max(0, int(total_summary.amounts_rappen.get(k, 0))) for k in BUCKET_FIELDS}
    liabilities = max(0, int(total_liabilities_rappen or 0))
    total_base = max(0, int(total_wealth_rappen or 0))
    # Fundament = Immobilie netto Hypothek (konstant). Hypothek zuerst gegen die
    # Immobilie verrechnen; ein Überhang (Hypothek > Immobilie) mindert den Finanzteil.
    real_estate_gross = amounts["real_estate"]
    foundation_rappen = max(0, real_estate_gross - liabilities)
    liab_remaining = max(0, liabilities - real_estate_gross)
    financial_base_rappen = max(0, total_base - foundation_rappen)

    # IST (heutiger Mix, total): Fundament + heutige Finanz-Buckets; ein Rest-
    # Hypothek-Überhang wird von der Liquidität abgezogen (Netto-Konsistenz).
    current_amounts = dict(amounts)
    current_amounts["real_estate"] = foundation_rappen
    if liab_remaining:
        current_amounts["liquidity"] = max(0, current_amounts["liquidity"] - liab_remaining)

    # SOLL (Ziel, total): Fundament identisch; Ziel-% ohne real_estate renormiert
    # auf den Finanzteil (das Haus stellt die Immobilienquote bereits).
    tgt = {k: int((target_weights_bps or {}).get(k, 0) or 0) for k in BUCKET_FIELDS}
    non_re_sum = sum(v for k, v in tgt.items() if k != "real_estate")
    target_amounts = {k: 0 for k in BUCKET_FIELDS}
    target_amounts["real_estate"] = foundation_rappen
    if non_re_sum > 0 and financial_base_rappen > 0:
        for k in BUCKET_FIELDS:
            if k == "real_estate":
                continue
            target_amounts[k] = int(round(financial_base_rappen * tgt[k] / non_re_sum))
        # Rundungsrest dem grössten Finanz-Bucket zuschlagen -> Summe exakt = Finanzbasis.
        fin_keys = [k for k in BUCKET_FIELDS if k != "real_estate"]
        residual = financial_base_rappen - sum(target_amounts[k] for k in fin_keys)
        if residual and fin_keys:
            biggest = max(fin_keys, key=lambda k: target_amounts[k])
            target_amounts[biggest] += residual
    else:
        # Kein Finanzziel / kein liquider Teil → keine Umschichtung (Fallback = IST).
        for k in BUCKET_FIELDS:
            if k != "real_estate":
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
            "is_foundation": key == "real_estate",
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
        if not getattr(infl, "is_active", 1):
            continue
        try:
            base_amount = int(infl.amount_rappen or 0)
            if base_amount <= 0:
                continue
            year = int(infl.expected_year or 0)
            offset = year - int(start_year or 0)
            if offset < 0 or offset >= len(series):
                continue
            recurring = int(getattr(infl, "is_recurring", 0) or 0) == 1
            freq = str(getattr(infl, "frequency", "") or "").strip().lower()
            duration = int(getattr(infl, "duration_years", 0) or 0) if recurring else 0
            value_mode = str(getattr(infl, "value_mode", "nominal") or "nominal").strip().lower()
            is_real = value_mode == "real"

            def _amount_at_offset(off: int, base: int) -> int:
                if not is_real or not inflation_series_bps:
                    return base
                # kumulativ ueber Jahre
                cum = 1.0
                for k in range(min(off, len(inflation_series_bps))):
                    cum *= (1.0 + (int(inflation_series_bps[k]) / 10000.0))
                return int(round(base * cum))

            if recurring:
                annual_base = base_amount * 12 if freq == "monatlich" else base_amount
                last = min(len(series) - 1, offset + max(0, duration) - 1)
                for off in range(offset, last + 1):
                    series[off] += _amount_at_offset(off, annual_base)
            else:
                series[offset] += _amount_at_offset(offset, base_amount)
        except (TypeError, ValueError, AttributeError):
            continue
    return series
