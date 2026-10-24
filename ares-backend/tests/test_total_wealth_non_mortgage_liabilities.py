"""TOTAL-WEALTH-LIABILITY-001 + MATH-DISP-1 (AA-Audit 2026-10).

Konvention (Produkt-Entscheid 2026-07-13): die Gesamtvermoegens-Allokation
zeigt IST und SOLL auf dem NETTO-Gesamtvermoegen (Aktiven minus ALLE
Verbindlichkeiten). Die Direktimmobilie ist ein fixes Fundament (netto
Hypothek), das nie wegoptimiert wird.

Erste Prinzipien, die fuer IST und SOLL gleichermassen gelten muessen:
    sum(Betraege) == Netto-Gesamtvermoegen
    sum(Gewichte) == 10'000 bps (sobald Netto-Gesamtvermoegen > 0)
    kein Betrag < 0

Defekt: seit GESAMTVERMOEGEN-FOUNDATION-LIABILITY-SCOPE-001 erhaelt
_build_total_wealth_allocation() nur noch die Hypotheken. Andere Schulden
(Privatkredit etc.) stecken zwar in total_wealth_rappen (SOLL-Basis), wurden
im IST aber nie abgezogen -> IST > Netto-Vermoegen, Gewichte > 100 %.

Die SCOPE-001-Garantie bleibt: ein unabhaengiger Kredit zehrt das
Fundament erst an, wenn ALLE liquiden Finanz-Buckets aufgebraucht sind
(Kaskade Liquiditaet -> Obligationen -> Alternative -> Aktien -> kotierte
Immobilien -> Fundament), und `foundation_rappen` bleibt "Immobilie netto
Hypothek".
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from services.portfolio_engine import PortfolioSummary  # noqa: E402
from services.portfolio_engine_gesamtvermoegen import (  # noqa: E402
    _build_total_wealth_allocation,
)
from test_gesamtvermoegen_foundation_liability_scope import (  # noqa: E402,F401
    _add_position,
    _seed_prereqs,
    orm_engine,
)

CHF = 100  # Rappen
TARGETS = {
    "equities": 5000,
    "bonds": 3000,
    "real_estate": 1000,
    "alternatives": 500,
    "liquidity": 500,
}


def _summary(**amounts_chf):
    full = {k: 0 for k in ("equities", "bonds", "real_estate", "alternatives", "liquidity")}
    full.update({k: v * CHF for k, v in amounts_chf.items()})
    return PortfolioSummary(amounts_rappen=full, total_rappen=sum(full.values()))


def _by(payload, field):
    return {row["asset_class"]: row[field] for row in payload["allocation"]}


def _assert_net_decomposition(payload, net_rappen):
    for side in ("current", "target"):
        amounts = _by(payload, f"{side}_amount_rappen")
        weights = _by(payload, f"{side}_weight_bps")
        assert all(v >= 0 for v in amounts.values()), (side, amounts)
        assert sum(amounts.values()) == net_rappen, (side, amounts)
        assert sum(weights.values()) == 10_000, (side, weights)
        # Jedes Gewicht liegt hoechstens 1 bp neben dem exakten Anteil.
        for key, amount in amounts.items():
            exact = amount * 10_000 / net_rappen
            assert abs(weights[key] - exact) < 1, (side, key, weights[key], exact)


def test_consumer_loan_is_deducted_from_ist_before_the_foundation():
    """Depot 300k Aktien, Haus 800k, Hypothek 300k, Privatkredit 100k.

    Netto = 1'100k - 400k = 700k. Der Kredit wird aus den Aktien gedeckt
    (300k -> 200k); das Fundament bleibt 500k. Vor dem Fix: IST = 800k
    (11'429 bps).
    """
    net = 700_000 * CHF
    payload = _build_total_wealth_allocation(
        _summary(equities=300_000, real_estate=800_000),
        300_000 * CHF,
        net,
        TARGETS,
        direct_property_rappen=800_000 * CHF,
        other_liabilities_rappen=100_000 * CHF,
    )
    _assert_net_decomposition(payload, net)
    current = _by(payload, "current_amount_rappen")
    assert current == {
        "Aktien": 200_000 * CHF,
        "Obligationen": 0,
        "Immobilien": 500_000 * CHF,
        "Alternative": 0,
        "Liquiditaet": 0,
    }
    assert payload["foundation_rappen"] == 500_000 * CHF
    assert payload["foundation_in_net_wealth_rappen"] == 500_000 * CHF
    assert payload["financial_base_rappen"] == 200_000 * CHF
    # SOLL: Fundament 500k fix + Finanzbasis 200k nach SAA.
    target = _by(payload, "target_amount_rappen")
    assert target == {
        "Aktien": 100_000 * CHF,
        "Obligationen": 60_000 * CHF,
        "Immobilien": 520_000 * CHF,
        "Alternative": 10_000 * CHF,
        "Liquiditaet": 10_000 * CHF,
    }
    assert payload["net_wealth_non_positive"] is False


def test_loan_larger_than_financial_assets_erodes_foundation_last():
    """Audit-Szenario (identisch zum SCOPE-001-Kern-Repro): Depot 100k,
    Haus 800k, Hypothek 300k, Privatkredit 200k -> Netto 400k.

    Kredit deckt zuerst die 100k Aktien, die restlichen 100k belasten das
    Fundament (500k -> 400k im Netto-Vermoegen). Vor dem Fix: IST/SOLL je
    Aktien 2'500 + Immobilien 12'500 = 15'000 bps.
    """
    net = 400_000 * CHF
    payload = _build_total_wealth_allocation(
        _summary(equities=100_000, real_estate=800_000),
        300_000 * CHF,
        net,
        TARGETS,
        direct_property_rappen=800_000 * CHF,
        other_liabilities_rappen=200_000 * CHF,
    )
    _assert_net_decomposition(payload, net)
    # SCOPE-001-Vertrag: Fundament = Immobilie netto (nur) Hypothek.
    assert payload["foundation_rappen"] == 500_000 * CHF
    assert payload["foundation_in_net_wealth_rappen"] == 400_000 * CHF
    assert payload["foundation_charged_other_liabilities_rappen"] == 100_000 * CHF
    assert payload["financial_base_rappen"] == 0
    assert _by(payload, "current_amount_rappen")["Immobilien"] == 400_000 * CHF
    assert _by(payload, "target_amount_rappen")["Immobilien"] == 400_000 * CHF
    re_row = next(r for r in payload["allocation"] if r["asset_class"] == "Immobilien")
    assert re_row["foundation_component_rappen"] == 400_000 * CHF
    assert re_row["investable_component_rappen"] == 0


def test_non_positive_net_wealth_fails_soft_with_flag():
    """Schulden > Aktiven: keine negativen Betraege, keine Gewichte > 100 %,
    sondern alles 0 plus explizites Flag und ungedeckter Rest."""
    payload = _build_total_wealth_allocation(
        _summary(liquidity=50_000),
        0,
        0,  # total_wealth_rappen wird vom Aufrufer auf 0 geflooret
        TARGETS,
        other_liabilities_rappen=80_000 * CHF,
    )
    assert payload["net_wealth_non_positive"] is True
    assert payload["uncovered_liabilities_rappen"] == 30_000 * CHF
    for row in payload["allocation"]:
        assert row["current_amount_rappen"] == 0
        assert row["target_amount_rappen"] == 0
        assert row["current_weight_bps"] == 0
        assert row["target_weight_bps"] == 0


def test_mortgage_only_target_weights_sum_to_exactly_10000():
    """MATH-DISP-1: Netto 800k, SOLL-Betraege exakt
    (Aktien 150k, Obli 90k, Immo 530k, Alt 15k, Liq 15k) -> exakte bps
    1875, 1125, 6625, 187.5, 187.5. Einzelrundung ergab 10'001."""
    net = 800_000 * CHF
    payload = _build_total_wealth_allocation(
        _summary(equities=300_000, real_estate=800_000),
        300_000 * CHF,
        net,
        TARGETS,
        direct_property_rappen=800_000 * CHF,
    )
    _assert_net_decomposition(payload, net)


def test_generate_target_allocation_total_view_decomposes_net_wealth(
    orm_engine, monkeypatch,
):
    """End-to-end ueber generate_target_allocation(): gleiche Positionen wie
    der SCOPE-001-Kern-Repro, aber mit der Netto-Invariante geprueft."""
    mandate_id = _seed_prereqs(orm_engine, monkeypatch)
    with Session(orm_engine) as session:
        _add_position(session, id="depot", position_type="Depot",
                      assignment="Beratungsvermögen", current_value_rappen=100_000_00,
                      alloc_equities_bps=10000)
        _add_position(session, id="house", position_type="Immobilien",
                      current_value_rappen=800_000_00, asset_expected_return_bps=0)
        _add_position(session, id="mortgage", position_type="Hypothek",
                      assignment="Verbindlichkeit", current_value_rappen=300_000_00)
        _add_position(session, id="personal-loan", position_type="Custom",
                      assignment="Verbindlichkeit", current_value_rappen=200_000_00)
        session.commit()
    with Session(orm_engine) as session:
        mandate = session.get(Mandate, mandate_id)
        result = pe.generate_target_allocation(
            session, mandate, "advisor-anchor", preferences=None,
        )
    ta = result["total_allocation"]
    net = 400_000 * CHF
    assert ta["total_base_rappen"] == net
    assert ta["foundation_rappen"] == 500_000 * CHF  # SCOPE-001 unveraendert
    _assert_net_decomposition(ta, net)
