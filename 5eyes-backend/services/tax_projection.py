"""Optionale Steuer-Schaetzung fuer die Cashflow-Projektion (Roadmap #39).

Nutzt das CH-Tax-Plugin (services/tax) als DETERMINISTISCHE REFERENZ-SCHAETZUNG:
- Steuerbares Einkommen ~ wiederkehrende Einnahmen des Jahres (Erwerb/AHV/Rente/Miete).
- Steuerbares Vermoegen ~ Netto-Vermoegen aus den erfassten Positionen (Assets minus
  Schulden), OHNE 2./3. Saeule (Vorsorge ist nicht vermoegenssteuerpflichtig).
- Private Kapitalgewinne sind in CH steuerfrei (vom Plugin korrekt so behandelt).

Das ist eine NAEHERUNG fuer die Planung (opt-in), KEINE Steuerberatung. Jeder Fehler im
Plugin fuehrt zu 0 (fail-safe) und darf die Cashflow-Projektion nie brechen.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 2./3. Saeule (Vorsorge) sind nicht Teil der CH-Vermoegenssteuer.
_WEALTH_TAX_EXCLUDED_TYPES = {"Vorsorge"}


def taxable_wealth_rappen_from_positions(positions) -> int:
    """Netto-Vermoegen (Assets minus Schulden, ohne Vorsorge) als Vermoegenssteuer-Basis.

    Naeherung: Marktwert statt Steuerwert (Immobilien-Steuerwert < Marktwert); Freibetraege
    behandelt das Plugin selbst (wealth_allowance_*).
    """
    total = 0
    for pos in positions or []:
        ptype = str(getattr(pos, "position_type", "") or "")
        assignment = str(getattr(pos, "assignment", "") or "")
        value = int(getattr(pos, "current_value_rappen", 0) or 0)
        if assignment == "Verbindlichkeit" or ptype == "Hypothek":
            total -= abs(value)          # Schulden mindern das steuerbare Vermoegen
        elif ptype in _WEALTH_TAX_EXCLUDED_TYPES:
            continue                     # 2./3. Saeule: nicht vermoegenssteuerpflichtig
        else:
            total += value
    return max(0, total)


def _marital_status_from_civil(civil_status) -> str:
    s = str(civil_status or "").lower()
    if "partnerschaft" in s:
        return "partnership"
    if "verheirat" in s:
        return "married"
    return "single"


def estimate_annual_tax_rappen(
    *,
    country_code: str | None,
    region: str | None,
    taxable_income_rappen: int,
    taxable_wealth_rappen: int,
    year: int,
    civil_status: str | None = None,
) -> int:
    """Geschaetzte Jahres-Steuer (Einkommen + Vermoegen) in Rappen, >= 0.

    Fail-safe: nicht unterstuetztes Land oder ein Plugin-Fehler -> 0 (nie ein Crash der
    Projektion). Private Kapitalgewinne bleiben unbeeinflusst (steuerfrei in CH).
    """
    try:
        from schemas.tax import TaxProfileInput
        from services.tax.registry import get_jurisdiction

        cc = (str(country_code or "CH")[:2] or "CH").upper()
        plugin = get_jurisdiction(cc)
        profile = TaxProfileInput(
            country_code=cc,
            region=(str(region).strip() or None) if region else None,
            year=int(year),
            taxable_income_rappen=max(0, int(taxable_income_rappen or 0)),
            taxable_wealth_rappen=max(0, int(taxable_wealth_rappen or 0)),
            marital_status=_marital_status_from_civil(civil_status),
        )
        income_tax = int(plugin.estimate_income_tax(profile).total_tax_rappen)
        wealth_tax = int(plugin.estimate_wealth_tax(profile).total_tax_rappen)
        return max(0, income_tax + wealth_tax)
    except Exception as exc:  # noqa: BLE001 - Schaetzung darf die Projektion nie brechen
        logger.warning("Steuer-Schaetzung uebersprungen (%s): %s", country_code, exc)
        return 0
