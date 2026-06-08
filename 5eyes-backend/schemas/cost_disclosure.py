"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — Pydantic-Schemas.

Spiegelt die Datenstruktur aus services.cost_disclosure.build_cost_disclosure
und stellt sie als typsicheres Response-Schema bereit. Im pending-Fall
(noch keine Empfehlung) bleibt dieselbe Form (data_pending=True) — keine
401-Sonderbehandlung im Client noetig.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CostItem(BaseModel):
    key: str = Field(..., description="Stabiler Identifier des Kostenpostens")
    label: str
    category: str
    frequency: str = Field(..., description="'einmalig' oder 'jaehrlich'")
    rate_bps: int = Field(..., description="Satz in Basispunkten")
    amount_rappen: int
    basis_rappen: int
    basis_label: str
    source: str
    is_estimate: bool = False
    included_in_total: bool = True


class CostTotals(BaseModel):
    one_time_rappen: int = 0
    one_time_bps: Optional[int] = None
    annual_rappen: int = 0
    annual_bps: Optional[int] = None
    first_year_rappen: int = 0
    first_year_bps: Optional[int] = None


class CostDisclosureResponse(BaseModel):
    """Ex-ante Kostenausweis-Payload, FIDLEG-konform.

    data_pending=True wenn fuer das Mandat noch keine Empfehlung vorliegt;
    cost_items ist dann leer, warnings beschreibt den Grund.
    """
    data_pending: bool
    currency: str = "CHF"
    as_of: Optional[str] = None
    source_run_id: Optional[str] = None
    fidleg_basis: str
    advisory_wealth_rappen: int = 0
    invested_amount_rappen: int = 0
    product_cost_coverage_bps: int = 0
    cost_items: list[CostItem] = Field(default_factory=list)
    totals: CostTotals
    is_complete: bool = False
    has_estimates: bool = False
    warnings: list[str] = Field(default_factory=list)
