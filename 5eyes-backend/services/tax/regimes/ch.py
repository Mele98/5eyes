"""CHTaxRegime-Light — Schweizer Pauschal-Mittelwerte fuer
Asset-Allocation-Wirkung.

BEWUSST MINIMAL gehalten (User-Direktive 2026-05-17):
- Pauschal-Mittelwerte ueber alle Kantone, kein Progressiv-Tarif
- Berater kann via Mandate.tax_overrides_json die 3 Werte ueberschreiben
  (z.B. fuer einen Kunden in GE: wealth_tax_bps_pa=80)
- Capital-Gains = 0 (Privatvermoegen, das ist CH-Spezifikum und wichtig
  fuer Allocation-Bias zu Aktien!)

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md (downscaled)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from services.tax.regimes.generic import GenericFlatRateRegime
from services.tax.registry import register_regime


@register_regime("CH")
@register_regime("CH-*")
@dataclass(frozen=True)
class CHTaxRegime(GenericFlatRateRegime):
    """Schweizer Pauschal-Steuer-Mittelwerte.

    Defaults sind CH-Durchschnitt — Berater kann pro Mandant overriden.

    Wichtige CH-Spezifika in den Defaults:
    - wealth_tax_bps_pa = 40 (~0.4% Durchschnitt, ZH=30, GE=80, SZ=10)
    - dividend_tax_bps = 2800 (marginaler Einkommensteuer-Satz ~28%
      fuer mittlere Einkommen; Verrechnungssteuer 35% ist rueckforderbar)
    - capital_gains_tax_bps = 0  ← KRITISCH: CH-Privatvermoegen steuerfrei,
      beeinflusst Asset-Allocation zugunsten von Aktien (Kursgewinn-Phantasie)
    - pension_lumpsum_tax_bps = 600 (~6%, privilegierter Tarif)
    """

    id: str = "CH"
    country_code: str = "CH"
    region_code: str | None = None
    display_name: str = "Schweiz (Pauschal-Mittelwerte)"
    local_currency: str = "CHF"
    tariff_version: str = "CH-LIGHT-v1-2026"

    wealth_tax_bps_pa: float = 40.0
    dividend_tax_bps: float = 2800.0
    interest_tax_bps: float | None = None  # = dividend (Income-Tax)
    capital_gains_tax_bps: float = 0.0  # CH-Privatvermoegen STEUERFREI
    pension_lumpsum_tax_bps: float = 600.0
    inheritance_tax_bps_default: float = 0.0  # Ehegatten/Nachkommen meist befreit

    overrides: Mapping[str, float] | None = None

    @classmethod
    def for_canton(
        cls,
        canton_code: str,
        wealth_tax_bps_pa: float | None = None,
    ) -> "CHTaxRegime":
        """Factory fuer kanton-spezifische Instanz mit angepasster Wealth-Tax.

        Erlaubte canton_codes: ZH, BE, LU, UR, SZ, OW, NW, GL, ZG, FR, SO,
        BS, BL, SH, AR, AI, SG, GR, AG, TG, TI, VD, VS, NE, GE, JU.

        Wenn wealth_tax_bps_pa nicht angegeben, nutzt es einen groben
        Mittelwert pro Kanton (Quelle: ESTV-Statistik 2024 — ungefaehr,
        nicht-progressiv. Fuer echten Tarif: Berater muss override geben).
        """
        canton = canton_code.upper().strip()
        if canton not in _CANTON_AVG_WEALTH_TAX_BPS:
            valid = sorted(_CANTON_AVG_WEALTH_TAX_BPS.keys())
            raise ValueError(
                f"Unknown canton '{canton_code}'. Valid: {', '.join(valid)}"
            )
        bps = (
            wealth_tax_bps_pa
            if wealth_tax_bps_pa is not None
            else _CANTON_AVG_WEALTH_TAX_BPS[canton]
        )
        return cls(
            id=f"CH-{canton}",
            region_code=canton,
            display_name=f"Schweiz — {_CANTON_NAMES[canton]}",
            wealth_tax_bps_pa=float(bps),
            tariff_version=f"CH-{canton}-LIGHT-v1-2026",
        )


# Grobe kantonale Mittelwerte fuer Wealth-Tax in bps p.a.
# Quelle: ESTV-Steuerbelastungsstatistik 2024 (vereinfacht).
# NICHT progressiv, NICHT Gemeinde-spezifisch. Fuer exakte Werte
# muss Berater override geben.
_CANTON_AVG_WEALTH_TAX_BPS: dict[str, float] = {
    "ZH": 35.0, "BE": 50.0, "LU": 30.0, "UR": 25.0, "SZ": 12.0,
    "OW": 25.0, "NW": 20.0, "GL": 40.0, "ZG": 15.0, "FR": 55.0,
    "SO": 50.0, "BS": 70.0, "BL": 55.0, "SH": 40.0, "AR": 35.0,
    "AI": 30.0, "SG": 40.0, "GR": 45.0, "AG": 35.0, "TG": 35.0,
    "TI": 60.0, "VD": 75.0, "VS": 55.0, "NE": 80.0, "GE": 85.0,
    "JU": 60.0,
}

_CANTON_NAMES: dict[str, str] = {
    "ZH": "Zuerich", "BE": "Bern", "LU": "Luzern", "UR": "Uri",
    "SZ": "Schwyz", "OW": "Obwalden", "NW": "Nidwalden", "GL": "Glarus",
    "ZG": "Zug", "FR": "Freiburg", "SO": "Solothurn", "BS": "Basel-Stadt",
    "BL": "Basel-Landschaft", "SH": "Schaffhausen", "AR": "Appenzell Ausserrhoden",
    "AI": "Appenzell Innerrhoden", "SG": "St. Gallen", "GR": "Graubuenden",
    "AG": "Aargau", "TG": "Thurgau", "TI": "Tessin", "VD": "Waadt",
    "VS": "Wallis", "NE": "Neuenburg", "GE": "Genf", "JU": "Jura",
}


CANTON_CODES: tuple[str, ...] = tuple(sorted(_CANTON_AVG_WEALTH_TAX_BPS.keys()))
"""Alle 26 CH-Kantone-Codes — fuer UI-Dropdown."""
