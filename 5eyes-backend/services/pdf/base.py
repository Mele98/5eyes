"""PDFRenderer-Protocol + gemeinsame Daten-Strukturen.

Engine-agnostisch: Documents werden mit einer PDFRenderer-Instanz erzeugt.
Tausch der Lib (ReportLab → WeasyPrint) erfordert nur neue Klasse die
das Protocol erfuellt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class PDFContext:
    """Eingabe-Metadata fuer jedes PDF-Dokument."""

    mandate_name: str
    advisor_name: str
    report_date: date
    advisor_org: str | None = None
    audit_hash: str | None = None
    locale: str = "de-CH"


@dataclass(frozen=True)
class AnlagestrategieData:
    """Daten-Bundle fuer Anlagestrategie-PDF."""

    target_allocation_bps: Mapping[str, int]
    """{'equities': 4000, 'bonds': 3000, ...} - Bucket-Allokation in bps"""

    cma_expected_return_bps: int
    """Erwartete Portfolio-Rendite in bps p.a."""

    cma_expected_vol_bps: int
    """Erwartete Portfolio-Volatilitaet in bps p.a."""

    horizon_years: int
    """Anlagehorizont"""

    monte_carlo_stats: Mapping[str, float] | None = None
    """Optional: {'p10': ..., 'p50': ..., 'p90': ...} - End-Wealth-Statistik"""

    optimizer_reasoning: str | None = None
    """Optional: Klartextliche Begruendung der SAA"""

    risk_profile_label: str | None = None
    """Optional: 'Ausgewogen', 'Wachstum', etc."""


@dataclass(frozen=True)
class RisikoprofilData:
    """Daten-Bundle fuer Risikoprofil-PDF (FINMA W305.02/W305.03)."""

    risk_profile_label: str
    risk_capacity_score: int
    risk_tolerance_score: int
    knowledge_services: Mapping[str, bool] = field(default_factory=dict)
    knowledge_instruments: Mapping[str, bool] = field(default_factory=dict)
    experience_years: int = 0
    suitability_note: str = ""


@runtime_checkable
class PDFRenderer(Protocol):
    """Universal-Interface fuer PDF-Renderer."""

    def render_anlagestrategie(
        self, ctx: PDFContext, data: AnlagestrategieData
    ) -> bytes:
        """Returns PDF-Bytes (komplettes Dokument)."""
        ...

    def render_risikoprofil(
        self, ctx: PDFContext, data: RisikoprofilData
    ) -> bytes:
        """Returns PDF-Bytes (komplettes Dokument)."""
        ...
