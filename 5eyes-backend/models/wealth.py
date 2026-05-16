from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class WealthPosition(Base):
    __tablename__ = "wealth_positions"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    label = Column(String, nullable=False)
    position_type = Column(String, nullable=False)
    assignment = Column(String, nullable=False, default="Anderes Vermögen")
    current_value_rappen = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="CHF")
    valuation_date = Column(String)
    depot_bank = Column(String)
    depot_account_number = Column(String)
    alloc_equities_bps = Column(Integer, nullable=False, default=0)
    alloc_bonds_bps = Column(Integer, nullable=False, default=0)
    alloc_real_estate_bps = Column(Integer, nullable=False, default=0)
    alloc_liquidity_bps = Column(Integer, nullable=False, default=0)
    alloc_alternatives_bps = Column(Integer, nullable=False, default=0)
    property_address = Column(String)
    property_zip_city = Column(String)
    property_usage = Column(String)
    property_rental_income_rappen = Column(Integer, nullable=False, default=0)
    pension_type = Column(String)
    pension_institution = Column(String)
    pension_technical_rate_bps = Column(Integer)
    pension_retirement_age = Column(Integer)
    pension_payout_form = Column(String)
    pension_wef_possible = Column(Integer, nullable=False, default=0)
    mortgage_bank = Column(String)
    mortgage_type = Column(String)
    mortgage_interest_rate_bps = Column(Integer)
    mortgage_maturity_date = Column(String)
    mortgage_amortization_rappen = Column(Integer, nullable=False, default=0)
    mortgage_amortization_type = Column(String)
    mortgage_linked_property_id = Column(String)
    asset_subtype = Column(String)
    asset_expected_return_bps = Column(Integer)
    asset_liquidity = Column(String)
    asset_valuation_method = Column(String)
    asset_location = Column(String)
    liquidity_instrument = Column(String)
    liquidity_interest_rate_bps = Column(Integer)
    liquidity_available_from = Column(String)
    is_available_for_goal_funding = Column(Integer, nullable=False, default=0)
    goal_funding_method = Column(String)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client", back_populates="wealth_positions")


class Cashflow(Base):
    __tablename__ = "cashflows"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    cashflow_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    amount_rappen = Column(Integer, nullable=False)
    gross_amount_rappen = Column(Integer)
    tax_amount_rappen = Column(Integer)
    timing_precision = Column(String)
    currency = Column(String, nullable=False, default="CHF")
    frequency = Column(String, nullable=False, default="jährlich")
    nature = Column(String, nullable=False, default="wiederkehrend")
    valid_from = Column(String)
    valid_until = Column(String)
    is_inflation_linked = Column(Integer, nullable=False, default=0)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client", back_populates="cashflows")


class WealthInflow(Base):
    """Erwarteter Vermögenszufluss (Erbschaft, Bonus, Saeule3b, Verkaufserlös, ...).

    Sprint A1 (2026-05-06): in Advisory-Methodik ein eigenes Konzept; bei uns vorher
    nur als pos-Cashflow modellierbar. First-class fuer:
    - Reserve-Berechnung: Inflow in Year T reduziert Reserve-Bedarf fuer
      Outflows ≤ T
    - cashflow_projection: positive Beitrag im erwarteten Jahr
    - FE-Visualisierung als gruener Marker
    """
    __tablename__ = "wealth_inflows"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    mandate_id = Column(String, ForeignKey("mandates.id"))  # optional, falls Mandate-spezifisch
    label = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # 'Erbschaft' | 'Bonus' | 'Saeule3b' | 'Verkaufserloes' | 'Andere'
    amount_rappen = Column(Integer, nullable=False)
    expected_year = Column(Integer, nullable=False)
    is_recurring = Column(Integer, nullable=False, default=0)
    frequency = Column(String)  # 'einmalig' | 'jaehrlich' | 'monatlich'
    duration_years = Column(Integer)  # bei recurring
    value_mode = Column(String, nullable=False, default="nominal")  # 'nominal' | 'real'
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)


class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    goal_family = Column(String, nullable=False)
    goal_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)
    weight_bps = Column(Integer)
    goal_scope = Column(String, nullable=False, default="Beratungsvermögen")
    value_mode = Column(String, nullable=False, default="nominal")
    target_amount_rappen = Column(Integer)
    target_wealth_rappen = Column(Integer)
    target_return_bps = Column(Integer)
    start_date = Column(String)
    horizon_years = Column(Integer)
    target_date = Column(String)
    is_ongoing = Column(Integer, nullable=False, default=0)
    frequency = Column(String)
    hardness = Column(String, nullable=False, default="Primär")
    # Sprint B6 (2026-05-08): Bedingte Goals — Eintrittswahrscheinlichkeit 0-100.
    # NULL/None wird in Engine als 100 (sicher eintretend) interpretiert.
    probability_pct = Column(Integer, nullable=True, default=100)
    # Sprint B3 (2026-05-08): Vorsorge-Differenziert. Ordnet Pensionsausgabe-Goals
    # einer konkreten Saeule zu (AHV / BVG / 3a / 1e / FZG). NULL bei nicht-
    # Pensionsausgabe-Goals oder unspezifizierter Saeule (audit-konsistent zu pre-B3).
    pension_pillar = Column(String, nullable=True)
    linked_position_id = Column(String)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    achievement_score = Column(Integer)
    last_scored_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="goals")


class PlanningAssumption(Base):
    __tablename__ = "planning_assumptions"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    supersedes_id = Column(String)
    retirement_age_primary = Column(Integer)
    retirement_age_partner = Column(Integer)
    life_expectancy_primary = Column(Integer)
    life_expectancy_partner = Column(Integer)
    inflation_assumption_bps = Column(Integer)
    pension_indexation_bps = Column(Integer)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="planning_assumptions")
