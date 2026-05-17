"""TaxRegime — abstrakte Basis fuer alle Land/Region-Steuer-Implementierungen.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §3
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class TaxContext:
    """Eingabe-Kontext fuer eine Steuer-Berechnung.

    Immutable per Design — eine TaxContext-Instanz repraesentiert genau
    EINEN Steuer-Zustand (Jahr T, Wealth W, Alter A). Engine erzeugt pro
    Jahr eine neue Instanz.
    """

    year_index: int
    """0-basierter Index seit Simulations-Start (t=0 = Jahr 1)."""

    calendar_year: int
    """Absolutes Kalender-Jahr fuer Tariff-Versioning (2026, 2027, ...)."""

    wealth_rappen: float
    """Aktuelles Reinvermoegen vor Steuerabzug in Rappen."""

    age: int | None = None
    """Aktuelles Alter des Hauptmandanten (fuer altersabhaengige Steuern,
    z.B. CH-Pension-Lumpsum mit reduzierten Saetzen ab 65)."""

    is_retired: bool = False
    """Phase: Akkumulation (False) vs. Decumulation (True). Beeinflusst
    z.B. CH-Pillar-3a-Befreiung von Vermoegenssteuer."""

    currency_code: str = "CHF"
    """Lokale Waehrung des Mandats. Multi-Currency-Vorbereitung — Engine
    konvertiert intern zu Rappen, Regime arbeitet in Lokalwaehrung."""

    marital_status: str = "single"
    """'single' | 'married' | 'partnership'. Wichtig fuer DE-Splitting,
    CH-Verheiratetentarif, US-Filing-Status."""

    children_count: int = 0
    """Fuer Kinderfreibetraege (DE, AT, FR, US)."""


@dataclass(frozen=True)
class TaxResult:
    """Ergebnis einer Steuer-Berechnung mit Audit-Information.

    Immutable. Wird vom Engine konsumiert (`amount_rappen`/`effective_bps`)
    und vom AuditLogger geloggt (alle Felder).
    """

    amount_rappen: float
    """Absoluter Steuerbetrag in Rappen (kann 0 sein, z.B. CH-Capital-Gains)."""

    effective_bps: float
    """Effektiver Steuersatz in Basispunkten (1 bps = 0.01%).
    Bezugsgroesse ist Tax-Typ-spezifisch:
    - wealth_tax: bps von Wealth
    - dividend_tax: bps von Dividend-Income
    - capital_gains_tax: bps von Gains."""

    regime_id: str
    """ID des verwendeten Regimes ('CH-ZH', 'DE', 'US-NY')."""

    tariff_version: str
    """Version-Label des Tarif-Sets ('2026-CH-ZH-v1'). Fuer Audit-Reproduzierbarkeit."""

    breakdown: Mapping[str, float] = field(default_factory=dict)
    """Aufschluesselung pro Komponente. Beispiel CH-ZH:
    {'kantonal': 0.0015, 'gemeinde': 0.0012, 'bund': 0.0}.
    Frei waehlbar pro Regime."""

    used_overrides: Mapping[str, float] | None = None
    """Falls Berater-Overrides aktiv: das angewendete Override-Dict.
    NULL wenn Standard-Regime ohne Overrides."""

    warnings: tuple[str, ...] = ()
    """Plausi-Warnungen ('Wealth-Tax 8% sehr hoch — Override pruefen')."""


@runtime_checkable
class TaxRegime(Protocol):
    """Universal-Interface fuer ein Land/eine Region.

    Engine kennt NUR diese Methoden. Jede Implementierung (CHTaxRegime,
    DETaxRegime, USTaxRegime, GenericFlatRateRegime) erfuellt dieses
    Protocol.

    Design-Entscheidungen:
    1. Methoden sind reine Funktionen (TaxContext+Wert → TaxResult).
       Keine Side-Effects, keine DB-Zugriffe. Test-freundlich.
    2. Properties fuer Identitaet/Metadata (id, country_code, ...).
    3. supports_*-Flags: damit Engine effizient ueberspringen kann (kein
       wealth_tax-Call wenn supports_wealth_tax=False).
    4. with_overrides(): Immutable-Pattern — Override erzeugt neue Instanz.
    """

    @property
    def id(self) -> str:
        """Eindeutige Jurisdiction-ID. Format: '<COUNTRY>[-<REGION>]'.
        Beispiele: 'CH-ZH', 'DE', 'US-NY', 'JP', 'SG'."""
        ...

    @property
    def country_code(self) -> str:
        """ISO 3166-1 alpha-2 Land-Code: 'CH', 'DE', 'US', 'JP'."""
        ...

    @property
    def region_code(self) -> str | None:
        """Optional: Kanton/State/Bundesland. None fuer Land-only ('DE')."""
        ...

    @property
    def display_name(self) -> str:
        """User-faces Anzeige: 'Schweiz — Zuerich', 'Deutschland'."""
        ...

    @property
    def local_currency(self) -> str:
        """ISO 4217: 'CHF', 'EUR', 'USD', 'JPY'."""
        ...

    @property
    def supports_wealth_tax(self) -> bool:
        """True wenn Land/Region Vermoegenssteuer hat (CH ja, DE nein)."""
        ...

    @property
    def supports_capital_gains_tax(self) -> bool:
        """True wenn Land/Region Kursgewinne besteuert
        (CH-Privat: nein, DE: ja, US: ja, SG/HK: nein)."""
        ...

    @property
    def supports_inheritance_tax(self) -> bool:
        """Phase 5+ — fuer Multi-Generation-Planning."""
        ...

    def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
        """Vermoegenssteuer p.a. auf das aktuelle Wealth (ctx.wealth_rappen).

        - CH: kantonal-progressiv (siehe CHTaxRegime)
        - DE/US/UK: amount=0, effective_bps=0
        - FR: nur IFI (Immo > 1.3 Mio)
        """
        ...

    def dividend_tax(
        self, ctx: TaxContext, dividend_income_rappen: float
    ) -> TaxResult:
        """Steuer auf Dividenden-Income im Geschaeftsjahr.

        - CH: marginal-progressiv (Einkommensteuer-Anteil)
        - DE: 25% KESt + Soli 5.5% = 26.375%
        - AT: 27.5% KESt
        - US: 0/15/20% LTCG-Rate je nach Bracket + NIIT 3.8%
        """
        ...

    def interest_tax(
        self, ctx: TaxContext, interest_income_rappen: float
    ) -> TaxResult:
        """Steuer auf Zins-Income. Oft = dividend_tax, kann abweichen
        (CH Bundes-Verrechnungssteuer auf Bank-Zinsen 35% rueckforderbar)."""
        ...

    def capital_gains_tax(
        self,
        ctx: TaxContext,
        gains_rappen: float,
        holding_years: int,
    ) -> TaxResult:
        """Steuer auf realisierte Kursgewinne.

        - CH: 0% (Privatvermoegen!) — ABER: gewerbsmaessiger Handel ausgenommen
        - DE: 26.375% (KESt+Soli)
        - US: 0/15/20% LTCG falls holding_years >= 1, sonst Income-Rate
        - SG/HK/AE: 0%
        """
        ...

    def pension_lumpsum_tax(
        self, ctx: TaxContext, amount_rappen: float
    ) -> TaxResult:
        """Kapitalbezugssteuer bei einmaliger Auszahlung von Pension/Vorsorge.

        - CH: kantonal separat-Tarif (privilegiert), ca. 1/5 - 1/10 vom
              ordentlichen Einkommensteuersatz, progressiv ueber Betrag
        - DE: Fuenftelregelung bei Einmalauszahlung
        - US: bei 401k Pre-Tax-Withdrawal → Ordinary-Income-Rate + ggf. 10% Penalty
        """
        ...

    def inheritance_tax(
        self,
        ctx: TaxContext,
        amount_rappen: float,
        relation: str,
    ) -> TaxResult:
        """Erbschaftssteuer. Phase 5+.

        relation: 'spouse' | 'child' | 'parent' | 'sibling' | 'other'
        - CH: kantonal, Ehegatten/Nachkommen meist befreit
        - DE: § 16 ErbStG Freibetraege 500k/400k/200k/20k EUR
        - US: Federal Estate Tax Exemption $13.6M (2026)
        """
        ...

    def validate_parameters(self, params: Mapping[str, float]) -> tuple[str, ...]:
        """Plausibilitaets-Pruefung der Parameter.

        Returns Warnungen als tuple[str, ...]. Leere tuple = keine Warnungen.
        Beispiel: wealth_tax_bps_pa=500 (5%) → Warnung "ungewoehnlich hoch".

        Diese Methode soll Tippfehler im Berater-Override fangen, nicht die
        wirklich gueltige Steuer ablehnen. Daher nur warnen, nie blockieren.
        """
        ...

    def with_overrides(self, overrides: Mapping[str, float]) -> "TaxRegime":
        """Returns neue Regime-Instanz mit ueberschriebenen Parameter-Werten.

        Immutable-Pattern: Original-Regime bleibt unveraendert.
        Berater-Overrides aus Mandate.tax_overrides_json werden hier
        eingespeist. Override-Dict bestimmt Regime — z.B. wenn Mandant
        in Pauschalbesteuerungs-Regime ist, kann wealth_tax_bps_pa
        auf einen Spezialwert gesetzt werden.
        """
        ...
