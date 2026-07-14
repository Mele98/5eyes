"""Gesamtvermögens-Allokation mit Immobilie als fixem Fundament (Sockel).

Produkt-Entscheid 2026-07-13: IST und SOLL werden auf dem GESAMTvermögen gezeigt
("mit allem"). Die Immobilie ist ein konstanter, nicht-optimierbarer Block
(Fundament, netto Hypothek) — identisch in IST und SOLL; nur das liquide
Finanzvermögen wird optimiert. Rein additiv (Optimizer/Reserve/Ziele unberührt).

Szenario = Mandat Leart Gashi: Konto 150k (Liquidität) + ETW 500k (Immobilie) −
Hypothek 300k = Netto-Gesamtvermögen 350k. Fundament = 500k − 300k = 200k.
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _build_total_wealth_allocation, PortfolioSummary

# Rappen-Helfer
K = 100_00  # 1'000 CHF in Rappen (1 CHF = 100 Rappen)


def _summary(liquidity_k=0, real_estate_k=0, equities_k=0, bonds_k=0, alternatives_k=0):
    amounts = {
        "equities": equities_k * K,
        "bonds": bonds_k * K,
        "real_estate": real_estate_k * K,
        "alternatives": alternatives_k * K,
        "liquidity": liquidity_k * K,
    }
    return PortfolioSummary(amounts_rappen=amounts, total_rappen=sum(amounts.values()))


def _by_class(result):
    return {row["asset_class"]: row for row in result["allocation"]}


def test_leart_foundation_is_constant_and_netted():
    # Konto 150k + Immobilie 500k − Hypothek 300k.
    summary = _summary(liquidity_k=150, real_estate_k=500)
    targets = {"equities": 6000, "bonds": 2000, "real_estate": 1000,
               "alternatives": 500, "liquidity": 500}
    r = _build_total_wealth_allocation(
        summary,
        total_liabilities_rappen=300 * K,
        total_wealth_rappen=350 * K,
        target_weights_bps=targets,
    )
    # Fundament = Immobilie netto Hypothek = 200k; Finanzbasis = 350 − 200 = 150k.
    assert r["foundation_rappen"] == 200 * K
    assert r["financial_base_rappen"] == 150 * K
    assert r["total_base_rappen"] == 350 * K

    by = _by_class(r)
    imm = by["Immobilien"]
    # KERN-INVARIANTE: das Fundament ist in IST und SOLL identisch (konstant).
    assert imm["current_amount_rappen"] == 200 * K
    assert imm["target_amount_rappen"] == 200 * K
    assert imm["current_weight_bps"] == imm["target_weight_bps"]
    assert imm["is_foundation"] is True
    # 200/350 ≈ 57.14 %
    assert 5713 <= imm["current_weight_bps"] <= 5715

    # IST: heute nur Cash (150k) neben dem Fundament — keine Aktien.
    assert by["Liquiditaet"]["current_amount_rappen"] == 150 * K
    assert by["Aktien"]["current_amount_rappen"] == 0

    # SOLL: der liquide Teil (150k) wird optimiert -> jetzt Aktien > 0, Cash < IST.
    assert by["Aktien"]["target_amount_rappen"] > 0
    assert by["Liquiditaet"]["target_amount_rappen"] < 150 * K

    # Gewichtssummen ~ 100 % (Rundung).
    cur_sum = sum(row["current_weight_bps"] for row in r["allocation"])
    tgt_sum = sum(row["target_weight_bps"] for row in r["allocation"])
    assert 9997 <= cur_sum <= 10003
    assert 9997 <= tgt_sum <= 10003
    # Beträge summieren exakt auf das Netto-Gesamtvermögen.
    assert sum(row["current_amount_rappen"] for row in r["allocation"]) == 350 * K
    assert sum(row["target_amount_rappen"] for row in r["allocation"]) == 350 * K


def test_financial_target_renormalized_excluding_real_estate():
    # Das Haus stellt die Immobilienquote; der Finanzteil verteilt sich auf die
    # Nicht-Immobilien-Klassen (Ziel-% ohne real_estate renormiert).
    summary = _summary(liquidity_k=150, real_estate_k=500)
    targets = {"equities": 6000, "bonds": 2000, "real_estate": 1000,
               "alternatives": 500, "liquidity": 500}
    r = _build_total_wealth_allocation(summary, 300 * K, 350 * K, targets)
    by = _by_class(r)
    # non-RE Summe = 9000 bps; Finanzbasis 150k: Aktien = 150k*6000/9000 = 100k
    # (± Rundungsrest, der dem grössten Finanz-Bucket zugeschlagen wird).
    assert abs(by["Aktien"]["target_amount_rappen"] - 100 * K) <= 2
    # Immobilien-Zielbetrag stammt NICHT aus dem 1000-bps-Ziel, sondern = Fundament.
    assert by["Immobilien"]["target_amount_rappen"] == 200 * K


def test_no_property_behaves_as_pure_financial():
    # Ohne Immobilie ist das Fundament 0 -> reine Finanzallokation auf Gesamt.
    summary = _summary(liquidity_k=200, equities_k=100)  # 300k, keine Immobilie
    targets = {"equities": 7000, "bonds": 2000, "real_estate": 0,
               "alternatives": 0, "liquidity": 1000}
    r = _build_total_wealth_allocation(summary, 0, 300 * K, targets)
    assert r["foundation_rappen"] == 0
    assert r["financial_base_rappen"] == 300 * K
    by = _by_class(r)
    assert by["Immobilien"]["current_amount_rappen"] == 0
    assert by["Immobilien"]["target_amount_rappen"] == 0
    # Aktien-Ziel = 70 % von 300k = 210k.
    assert by["Aktien"]["target_amount_rappen"] == 210 * K


def test_mortgage_exceeding_property_reduces_liquidity():
    # Hypothek > Immobilie: Überhang mindert die Liquidität, Fundament floored 0.
    summary = _summary(liquidity_k=150, real_estate_k=100)  # 250k brutto
    targets = {"equities": 6000, "bonds": 3000, "real_estate": 0,
               "alternatives": 0, "liquidity": 1000}
    # Hypothek 200k > Immobilie 100k -> Fundament 0, Überhang 100k.
    r = _build_total_wealth_allocation(summary, 200 * K, 50 * K, target_weights_bps=targets)
    assert r["foundation_rappen"] == 0
    by = _by_class(r)
    # IST-Liquidität = 150k − 100k Überhang = 50k = Netto-Gesamtvermögen.
    assert by["Liquiditaet"]["current_amount_rappen"] == 50 * K
    assert sum(row["current_amount_rappen"] for row in r["allocation"]) == 50 * K
