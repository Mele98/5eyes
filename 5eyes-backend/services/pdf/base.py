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
    # base_currency != CHF (interne Basis-Currency ist CHF/Rappen).
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
    """Risk-Score 0-100 fuer interne Herleitung; im Kunden-PDF nicht anzeigen."""

    risk_is_overridden: bool = False
    """True, wenn das Risikoprofil manuell uebersteuert wurde."""

    risk_override_reason: str | None = None
    """Dokumentierte Begruendung fuer eine manuelle Risikoprofil-Uebersteuerung."""

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

    # ---- Sprint 14: Cover-Seite Daten ----
    client_address_lines: list[str] = field(default_factory=list)
    """Klient-Adress-Zeilen fuer Cover, dynamisch aus Kundendaten."""
    client_phone: str | None = None

    # ---- Sprint 14 Phase 2: Eignungspruefung Frage-Antwort ----
    risk_answers: list = field(default_factory=list)
    """Liste von RiskAssessmentAnswer-Dicts mit question_number,
    answer_label, answer_points fuer FINMA-konforme Eignungspruefung."""

    # ---- Vermoegensuebersicht ----
    advisory_positions: list = field(default_factory=list)
    """Beratungsvermoegen-Positionen mit asset_class, sub_asset_class,
    current_amount_rappen fuer hierarchische Vermoegensuebersicht."""
    other_wealth_positions: list = field(default_factory=list)
    """Anderes Vermoegen (Hypothek, externe Immobilien, BVG/3a, etc.)."""

    # ---- Cashflows + Goals (Seite 12 der Vorlage) ----
    cashflow_events: list = field(default_factory=list)
    """Liste von Cashflow-Events mit name, recurrence, start_label,
    amount_rappen."""
    goals_list: list = field(default_factory=list)
    """Liste von Goals mit name, category, recurrence, start_label,
    amount_rappen oder target_pct."""

    # ---- IST-Allokation fuer 2-Donut-Vergleich ----
    current_allocation_bps: Mapping[str, int] = field(default_factory=dict)
    """{'equities': 3868, ...} aus IST-Bestand (Ausgangslage)."""

    allocation_preferences: Mapping[str, object] = field(default_factory=dict)
    """Gespeicherte Anlagepraeferenzen aus TargetAllocation.preferences_json."""


@dataclass(frozen=True)
class VertragData:
    """Sprint 12: Vertrags-PDF Daten-Bundle (ContractDocument)."""
    document_title: str = "Beratungsdokument"
    document_type: str | None = None
    praeambel: str = ""
    haftungsklausel: str = ""
    sondervereinbarungen: str | None = None
    ort_unterzeichnung: str = "Zürich"
    vereinbarungs_datum: str = ""
    mandate_number: str | None = None
    advisory_wealth_rappen: int | None = None


@dataclass(frozen=True)
class PortfolioData:
    """Sprint 11 Phase 6: Portfolio-PDF Daten-Bundle.

    Fokus auf konkrete Positionen mit Soll-vs-IST + Drift.
    """
    mandate_number: str | None = None
    advisory_wealth_rappen: int | None = None
    positions: list = field(default_factory=list)
    """Liste von Position-Dicts mit: name, isin, sub_asset_class,
    target_weight_bps, current_weight_bps, drift_bps,
    target_amount_rappen, current_amount_rappen, currency,
    ter_bps, provider."""


@dataclass(frozen=True)
class ProtokollData:
    """Beratungsprotokoll-PDF Daten-Bundle.

    Dokumentiert Advisory-Log, getroffene Entscheide und naechste Schritte.
    """
    mandate_number: str | None = None
    advisory_wealth_rappen: int | None = None
    entries: list = field(default_factory=list)
    """Liste von AdvisoryLog-Dicts mit entry_date, entry_type, title,
    description, decision, status."""
    latest_recommendation_summary: str | None = None


@dataclass(frozen=True)
class DepotCheckData:
    """Sprint U-P16 (2026-05-21): Depot-Check-PDF Daten-Bundle.

    Spiegelt 1:1 die Struktur von services.depot_check.compute_depot_check.
    Plus stress_scenarios aus services.backtest_stress.compute_stress_replays.
    """
    mandate_number: str | None = None
    total_advisory_wealth_rappen: int = 0
    # Bucket-Drift (IST vs SOLL)
    buckets: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    """{'equities': {label, ist_bps, soll_bps, drift_bps, band_min_bps,
                     band_max_bps, in_band, ist_rappen}, ...}"""
    # Aggregierte Exposures
    country_exposure_bps: Mapping[str, int] = field(default_factory=dict)
    sector_exposure_bps: Mapping[str, int] = field(default_factory=dict)
    currency_exposure_bps: Mapping[str, int] = field(default_factory=dict)
    concentration_hhi: Mapping[str, int] = field(default_factory=dict)
    """{country, sector, currency, top_positions} → HHI 0-10000"""
    # Top-Positionen
    top_positions: list = field(default_factory=list)
    """Liste mit product_name, isin, asset_class, sub_asset_class, currency,
    amount_rappen, weight_bps, ter_bps."""
    # Fund-Charakteristika (gewichtet)
    weighted_ter_bps: int = 0
    weighted_duration_years_x10: int = 0
    weighted_esg_score_x10: int = 0
    covered_share_bps: int = 0
    """Anteil Positionen mit gepflegtem TER/Duration/ESG (für Confidence)."""
    # Liquiditäts-Profil
    liquidity_profile_bps: Mapping[str, int] = field(default_factory=dict)
    """{daily_bps, weekly_bps, monthly_bps, illiquid_bps, unknown_bps}."""
    # Stress-Replays
    stress_scenarios: list = field(default_factory=list)
    """Liste mit id, label, period, cumulative_return_bps, max_drawdown_bps,
    recovery_months, annual_breakdown."""
    # Auto-Warnings
    warnings: list[str] = field(default_factory=list)


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
    is_overridden: bool = False
    override_reason: str | None = None
    override_client_confirmed: bool | None = None
    override_warning_delivered: bool | None = None


@runtime_checkable
class PDFRenderer(Protocol):
    """Universal-Interface fuer PDF-Renderer."""

    def render_anlagestrategie(
        self, ctx: PDFContext, data: AnlagestrategieData
    ) -> bytes:
        """Returns PDF-Bytes (komplettes Dokument)."""
        ...

    def render_asset_allocation(
        self, ctx: PDFContext, data: AnlagestrategieData
    ) -> bytes:
        """Returns PDF-Bytes fuer die reine Asset-Allocation-Uebersicht."""
        ...

    def render_risikoprofil(
        self, ctx: PDFContext, data: RisikoprofilData
    ) -> bytes:
        """Returns PDF-Bytes (komplettes Dokument)."""
        ...

    def render_portfolio(self, ctx: PDFContext, data: PortfolioData) -> bytes:
        """Returns PDF-Bytes fuer Portfolio/Umsetzung."""
        ...

    def render_vertrag(self, ctx: PDFContext, data: VertragData) -> bytes:
        """Returns PDF-Bytes fuer Vertragsdokumente."""
        ...

    def render_protokoll(self, ctx: PDFContext, data: ProtokollData) -> bytes:
        """Returns PDF-Bytes fuer das Beratungsprotokoll."""
        ...

    def render_depotcheck(self, ctx: PDFContext, data: DepotCheckData) -> bytes:
        """Returns PDF-Bytes fuer den Depot-Check-Report (Sprint U-P16)."""
        ...
