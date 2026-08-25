"""Sprint U-P13 (2026-05-20): Historische Stress-Szenarien als Backtest-Replay.

Wendet historische Returns je Asset-Klasse auf die aktuelle Bucket-Gewichtung
eines Mandates an und liefert: cumulative_return, max_drawdown, recovery_months.

Foundation-Variante: hartcodierte Szenarien aus echten historischen Drawdowns
(Quellen: MSCI World/SPI/Bloomberg-Aggregate/Schweizer Bundesobligationen).
Voll-Pipeline mit Live-Marktdaten kommt in Sprint U-P11.

KEINE Datenmodell-Änderungen. Reiner Service auf existierender TargetAllocation.
"""
from __future__ import annotations

from typing import Mapping

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation
from models.mandates import Mandate


# Historische jährliche Returns pro Asset-Klasse während echter Drawdown-Perioden.
# Quellen:
# - Equity: MSCI World TR Net Net (DM-Equity)
# - Bonds: Bloomberg Global Aggregate (Hedged)
# - Real Estate: SXI Real Estate Funds / FTSE EPRA/NAREIT Developed
# - Alternatives: HFRX Global Hedge Fund Index
# - Liquidity: SARON/Euribor 1M (Geldmarkt)
#
# Format: jeder scenario hat eine years-Liste mit (jahr, dict(bucket → return_bps)).
# Engine multipliziert mit aktuellen Bucket-Weights, kumuliert.
_SCENARIOS: list[dict] = [
    {
        "id": "dotcom_2000_2002",
        "label": "Dotcom-Crash 2000-2002",
        "period": "März 2000 – Okt 2002 (31 Monate)",
        "recovery_months": 56,  # bis SPI/MSCI das Pre-Crash-Level wieder erreichte
        "annual_returns_bps": [
            # equities, bonds, real_estate, alternatives, liquidity (bps)
            {"year": 2000, "equities": -1300, "bonds": 1100, "real_estate": 500, "alternatives": 800, "liquidity": 350},
            {"year": 2001, "equities": -1700, "bonds": 800, "real_estate": -100, "alternatives": 200, "liquidity": 300},
            {"year": 2002, "equities": -2000, "bonds": 950, "real_estate": 400, "alternatives": -150, "liquidity": 200},
        ],
    },
    {
        "id": "global_financial_crisis_2008",
        "label": "Globale Finanzkrise 2008",
        "period": "Jan 2008 – Mär 2009 (15 Monate)",
        "recovery_months": 36,
        "annual_returns_bps": [
            {"year": 2008, "equities": -4200, "bonds": 1000, "real_estate": -3700, "alternatives": -2300, "liquidity": 200},
            {"year": 2009, "equities": 3000, "bonds": 700, "real_estate": 3500, "alternatives": 1600, "liquidity": 50},
        ],
    },
    {
        "id": "covid_2020",
        "label": "Covid-Crash 2020",
        "period": "Feb 2020 – Mär 2020 (5 Wochen) + Erholung",
        "recovery_months": 5,
        "annual_returns_bps": [
            # Annualisiert: Crash Q1 -34%, dann Erholung — Netto +15% MSCI World
            {"year": 2020, "equities": 1500, "bonds": 750, "real_estate": -800, "alternatives": 700, "liquidity": -10},
        ],
    },
    {
        "id": "bonds_crash_2022",
        "label": "Bond-Crash + Equity-Bear 2022",
        "period": "Jan 2022 – Okt 2022 (10 Monate)",
        "recovery_months": 14,
        "annual_returns_bps": [
            {"year": 2022, "equities": -1800, "bonds": -1300, "real_estate": -2400, "alternatives": -400, "liquidity": 100},
        ],
    },
    {
        "id": "stagflation_1973_1974",
        "label": "Ölkrise + Stagflation 1973-1974",
        "period": "Jan 1973 – Dez 1974 (24 Monate)",
        "recovery_months": 84,  # langer Bear-Markt
        "annual_returns_bps": [
            {"year": 1973, "equities": -1700, "bonds": -300, "real_estate": -700, "alternatives": 4000, "liquidity": 750},  # alts = Gold-Boom
            {"year": 1974, "equities": -2800, "bonds": 100, "real_estate": -1700, "alternatives": 6500, "liquidity": 800},
        ],
    },
]


def _compute_scenario_path(
    scenario: dict,
    weights_bps: Mapping[str, int],
) -> dict:
    """Wendet die jährlichen Returns auf die Bucket-Gewichtung an und
    liefert cumulative_return + max_drawdown."""
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    years_in_period = []
    for year_entry in scenario.get("annual_returns_bps", []):
        portfolio_return_bps = 0.0
        for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
            w = float(max(0, int(weights_bps.get(bucket, 0) or 0))) / 10000.0
            r_bps = float(year_entry.get(bucket, 0) or 0)
            portfolio_return_bps += w * r_bps
        annual_return = portfolio_return_bps / 10000.0
        cumulative *= (1.0 + annual_return)
        peak = max(peak, cumulative)
        drawdown = (peak - cumulative) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
        years_in_period.append({
            "year": int(year_entry.get("year", 0)),
            "return_bps": int(round(annual_return * 10000)),
            "wealth_index": round(cumulative, 4),
        })
    return {
        "id": scenario["id"],
        "label": scenario["label"],
        "period": scenario["period"],
        "cumulative_return_bps": int(round((cumulative - 1.0) * 10000)),
        "max_drawdown_bps": int(round(max_dd * 10000)),
        "recovery_months": int(scenario.get("recovery_months", 0)),
        "annual_breakdown": years_in_period,
    }


def compute_stress_for_weights(weights_bps: Mapping[str, int]) -> list[dict]:
    """Sprint U-P15 (2026-05-21): reine Stress-Replay-Berechnung für eine
    gegebene Bucket-Gewichtung.

    Public-Helper für A/B-Backtest und andere Aufrufer, die nicht an eine
    TargetAllocation gebunden sind. Keine DB-Abhängigkeit.
    """
    return [_compute_scenario_path(s, weights_bps) for s in _SCENARIOS]


def compute_stress_replays(db: Session, mandate: Mandate) -> dict:
    """Liefert für das Mandat ein Stress-Replay-Ergebnis: pro Szenario
    cumulative_return, max_drawdown, recovery, Jahres-Aufschlüsselung.

    Nutzt die aktuelle TargetAllocation als Gewichtung (Soll-Mix) — kein
    Backtest auf realer Position-History.
    """
    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    if not ta:
        return {
            "mandate_id": str(getattr(mandate, "id", "") or ""),
            "scenarios": [],
            "warning": "Keine aktive Target-Allocation gefunden. Bitte erst Strategie berechnen.",
        }

    weights_bps = {
        "equities": int(getattr(ta, "target_equities_bps", 0) or 0),
        "bonds": int(getattr(ta, "target_bonds_bps", 0) or 0),
        "real_estate": int(getattr(ta, "target_real_estate_bps", 0) or 0),
        "alternatives": int(getattr(ta, "target_alternatives_bps", 0) or 0),
        "liquidity": int(getattr(ta, "target_liquidity_bps", 0) or 0),
    }
    return {
        "mandate_id": str(getattr(mandate, "id", "") or ""),
        "weights_bps": weights_bps,
        "scenarios": compute_stress_for_weights(weights_bps),
        "note": "Replay mit historischen jährlichen Returns pro Asset-Klasse. Foundation-Variante mit hartcodierten Szenarien — volle Marktdaten-Pipeline kommt in Sprint U-P11.",
    }
