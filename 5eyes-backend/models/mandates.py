from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(String, primary_key=True)
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
