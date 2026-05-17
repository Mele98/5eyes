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
    # Sprint 9 Phase 4: Mandate-Currency fuer Report-Anzeige
    # Werte werden via services.currency.convert_rappen umgerechnet wenn
    # base_currency != CHF (5eyes-interne Basis-Currency ist CHF/Rappen).
    base_currency: str = "CHF"


@dataclass(frozen=True)
class AnlagestrategieData:
    """Daten-Bundle fuer Anlagestrategie-PDF (Sprint 11 vollumfaenglich).

    Replikat-Datenstruktur fuer Frontend-Vorlage buildAnlagestrategieDocHtml.
    Felder mit Default = Optional (Sektion wird ausgelassen wenn leer).
    """

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

    # ---- Sprint 11: erweiterte Felder fuer Frontend-Vorlagen-Replikation ----

    mandate_number: str | None = None
    """Mandat-Nummer fuer Header-Rechts."""

    advisory_wealth_rappen: int | None = None
    """Beratungsvermoegen in Rappen fuer Header + Soll-Tabelle-Total."""

    risk_score_x10: int | None = None
    """Risk-Score 0-100 (final_score_x10), wird als X.Y/10 angezeigt."""

    investment_horizon_years: int | None = None
    """Anlagehorizont aus Risk-Assessment (kann von horizon_years abweichen)."""

    mandate_type: str | None = None
    """'Anlageberatung' | 'Vermoegensverwaltung' | etc. fuer Risikoprofil-Box."""

    knowledge_services: Mapping[str, bool] = field(default_factory=dict)
    """{'Anlageberatung': True, 'Verwaltung': False} — Eignungspruefung."""

    knowledge_instruments: Mapping[str, bool] = field(default_factory=dict)
    """{'Aktien': True, 'Anleihen': True, 'Derivate': False}."""

    bucket_bands_bps: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    """{'equities': (min_bps, max_bps), ...} fuer Toleranzbaender-Spalte."""

    bucket_amounts_rappen: Mapping[str, int] = field(default_factory=dict)
    """{'equities': target_amount_rappen, ...} fuer Betrag-Spalte."""

    products: list = field(default_factory=list)
    """ISIN-Produkt-Liste. Jedes Element ist dict mit:
    name, isin, asset_class, sub_asset_class, target_weight_bps,
    target_amount_rappen, currency, ter_bps, provider."""

    goal_analysis: list = field(default_factory=list)
    """Goal-Analysis-Liste. Jedes Element ist dict mit:
    rank, label, achievement_score (0-100), target_text."""

    max_drawdown_bps: int | None = None
    """Max Drawdown aus Stress-Tests."""

    var_95_bps: int | None = None
    """Value-at-Risk 95% (1-Jahr)."""

    median_cagr_bps: int | None = None
    """Median CAGR aus MC-Simulation."""


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
