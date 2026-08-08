from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(String, primary_key=True)
    # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur. Nullable
    # in Stage 9 fuer Backwards-Compat (Default-Tenant 'main' via Migration).
    tenant_id = Column(String, ForeignKey("tenants.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    mandate_number = Column(String, nullable=False, unique=True)
    mandate_type = Column(String, nullable=False, default="Anlageberatung")
    status = Column(String, nullable=False, default="Aktiv")
    base_currency = Column(String, nullable=False, default="CHF")
    advisory_language = Column(String, nullable=False, default="DE")
    depot_bank = Column(String)
    depot_account_number = Column(String)
    opened_at = Column(String, nullable=False)
    closed_at = Column(String)
    # Sprint A3 (2026-05-06): Lebenserwartung & Rentenalter pro Mandat anpassbar.
    # NULL = nutzen Defaults (65 / 85 berechnet aus Geburtsjahr).
    retirement_year = Column(Integer)
    life_expectancy_year = Column(Integer)
    # Sprint B4 (2026-05-07): Anlageuniversum (Advisory-Methodik-Pattern).
    # 'Standard' = Referenzanbieter Anteil hoeher; 'Alternativ' = breiter Marktdurchschnitt.
    # Default 'Standard' (kompatibel zu existierenden Mandaten).
    investment_universe = Column(String, nullable=False, default="Standard")
    # Sprint B1 (2026-05-07): Persistierte Building-Block-Wahl pro Mandat.
    # JSON mit {equitiesGeo, bondsDuration, realestateMarket, altsXxx}.
    # NULL = nutze System-Defaults (Schweiz-Fokus, Langfristig, Schweiz, Gold-only).
    default_building_blocks_json = Column(String)
    # Sprint 4 Phase 3 (2026-05-17): Mortalitaets-Sampling fuer Cashflow-MC.
    # Wenn use_mortality_simulation=True und client_birth_year + client_sex
    # gesetzt: portfolio_engine sampled Sterbe-Alter aus BFS-Tafel und
    # ueberreicht death_year_index_per_path an scenario_engine.
    # Default: Off (Backwards-Compat fuer alle bestehenden Mandate).
    client_birth_year = Column(Integer)
    client_sex = Column(String)  # 'M' | 'F'
    use_mortality_simulation = Column(Integer, default=0)  # SQLite bool via int
    # Sprint U-P3 (2026-05-19): Steuersitz für tax-aware Allokations-MC.
    # NULL = tax-naiv (Backwards-Compat). Pattern matched gegen
    # services.tax.registry.REGIME_REGISTRY: 'CH', 'DE', 'CH-ZH', 'DE-BY', etc.
    # Fallback '*' = GenericFlatRateRegime (Pauschal-Rate).
    tax_jurisdiction = Column(String)
    # JSON-Overrides für TaxConfig-Felder (z.B. {"capital_gain_rate_bps": 1500}).
    # NULL = nur Plugin-Defaults aus dem registrierten Regime.
    tax_overrides_json = Column(String)
    # 2026-07-27 (Laender-Skalierung, Fonds-Kuratierung): Länder-Code fuer
    # dieses Mandat (z.B. "CH", "DE") -- NICHT dasselbe wie tax_jurisdiction
    # (kann kantonal sein, z.B. "CH-ZH"). Steuert, welche
    # ProductUniverseEntry-Zeilen (models/review.py) fuer die Fonds-Auswahl
    # in generate_recommendation_run gelten. NULL = "CH" (Backwards-Compat,
    # Schweiz bleibt fuer alle Bestandsmandate unveraendert) -- gleiches
    # Nullable-Pattern wie tax_jurisdiction, Code interpretiert NULL als "CH".
    jurisdiction = Column(String)
    # 2026-07-27 (HUD-Konfiguration): JSON-Array von Sektions-Keys aus dem
    # Advisory-Report-Aggregator (services/advisory_report.py), die fuer
    # DIESES Mandat ausgeblendet werden sollen. NULL = alles sichtbar
    # (Backwards-Compat, unveraendertes Verhalten fuer alle Bestandsmandate).
    hidden_report_sections = Column(String)
    # Roadmap #39 (Standpunkt 2026-08-07): geschaetzte Vermoegenssteuer als
    # optionale, abgeleitete jaehrliche Ausgabe in der deterministischen
    # Cashflow-Projektion (services.wealth_cashflows.derive_tax_cashflow).
    # Default 0 = aus (Backwards-Compat, unveraendertes Verhalten fuer alle
    # Bestandsmandate). Nutzt denselben tax_jurisdiction/tax_overrides_json
    # wie der steuer-bewusste Optimizer-Pfad (Single-Source-of-Truth).
    tax_estimate_in_cashflow_enabled = Column(Integer, default=0)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client", back_populates="mandates")
    risk_assessments = relationship("RiskAssessment", back_populates="mandate")
    goals = relationship("Goal", back_populates="mandate")
    planning_assumptions = relationship("PlanningAssumption", back_populates="mandate")
    target_allocations = relationship("TargetAllocation", back_populates="mandate")
    review_triggers = relationship("ReviewTrigger", back_populates="mandate")
    advisory_log = relationship("AdvisoryLog", back_populates="mandate")
    contract_documents = relationship("ContractDocument", back_populates="mandate")
    suitability_checks = relationship("SuitabilityCheck", back_populates="mandate")
    conflict_disclosures = relationship("ConflictOfInterestDisclosure", back_populates="mandate")
    recommendation_runs = relationship("RecommendationRun", back_populates="mandate")
    report_notes = relationship(
        "MandateReportNotes", back_populates="mandate", uselist=False
    )
    portfolio_handoffs = relationship("PortfolioHandoff", back_populates="mandate")
