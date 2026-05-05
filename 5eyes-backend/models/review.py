from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from database import Base


class ReviewTrigger(Base):
    __tablename__ = "review_triggers"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_name = Column(String, nullable=False)
    threshold_bps = Column(Integer)
    frequency = Column(String)
    status = Column(String, nullable=False, default="Aktiv")
    next_due_at = Column(String)
    last_triggered_at = Column(String)
    triggered_value = Column(String)
    triggered_at = Column(String)
    triggered_notes = Column(String)
    calendar_exported = Column(Integer, nullable=False, default=0)
    calendar_exported_at = Column(String)
    is_system = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="review_triggers")


class ContractDocument(Base):
    __tablename__ = "contract_documents"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    document_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content_json = Column(String)
    pdf_path = Column(String)
    checksum_sha256 = Column(String)
    pdf_generated_at = Column(String)
    status = Column(String, nullable=False, default="Entwurf")
    signed_by_advisor = Column(Integer, nullable=False, default=0)
    signed_by_client = Column(Integer, nullable=False, default=0)
    signed_at = Column(String)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="contract_documents")
    creator = relationship("User")


class AdvisoryLog(Base):
    __tablename__ = "advisory_log"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    entry_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String)
    decision = Column(String)
    trigger_id = Column(String)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=True)
    status = Column(String, nullable=False, default="Empfohlen")
    advisor_id = Column(String, ForeignKey("users.id"), nullable=False)
    client_signed = Column(Integer, nullable=False, default=0)
    client_signed_at = Column(String)
    document_id = Column(String)
    entry_date = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    mandate = relationship("Mandate", back_populates="advisory_log")
    advisor = relationship("User")
    recommendation_run = relationship("RecommendationRun")


class ConflictOfInterestDisclosure(Base):
    __tablename__ = "conflict_of_interest_disclosures"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    conflict_type = Column(String, nullable=False)
    description = Column(String, nullable=False)
    inducement_provider = Column(String)
    inducement_amount_rappen = Column(Integer)
    inducement_frequency = Column(String)
    disclosed_to_client = Column(Integer, nullable=False, default=0)
    disclosed_at = Column(String)
    client_acknowledged = Column(Integer, nullable=False, default=0)
    client_acknowledged_at = Column(String)
    mitigation_action = Column(String)
    document_id = Column(String)
    disclosed_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="conflict_disclosures")
    discloser = relationship("User")


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True)
    isin = Column(String)
    symbol = Column(String)
    lookup_mode_override = Column(String)
    lookup_symbol_override = Column(String)
    figi = Column(String)
    composite_figi = Column(String)
    share_class_figi = Column(String)
    exchange_code = Column(String)
    market_sector = Column(String)
    security_type = Column(String)
    security_type2 = Column(String)
    mapping_provider = Column(String)
    mapping_resolved_at = Column(String)
    reference_data_provider = Column(String)
    reference_data_refreshed_at = Column(String)
    product_name = Column(String, nullable=False)
    provider = Column(String)
    product_type = Column(String, nullable=False)
    asset_class = Column(String, nullable=False)
    sub_asset_class = Column(String)
    currency = Column(String, nullable=False, default="CHF")
    ter_bps = Column(Integer)
    sfdr_class = Column(String)
    esg_rating = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    suitability = relationship("ProductSuitability", back_populates="product")
    price_history = relationship("PriceHistory", back_populates="product")


class ProductSuitability(Base):
    __tablename__ = "product_suitability"

    id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    profile_from = Column(Integer, nullable=False)
    profile_to = Column(Integer, nullable=False)
    advisory_allowed = Column(Integer, nullable=False, default=1)
    discretionary_allowed = Column(Integer, nullable=False, default=1)
    requires_appropriateness = Column(Integer, nullable=False, default=0)
    requires_override = Column(Integer, nullable=False, default=0)
    max_position_bps = Column(Integer)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    product = relationship("Product", back_populates="suitability")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("product_id", "price_date", "source", name="uq_price_history_product_date_source"),
        Index("ix_price_history_product_date", "product_id", "price_date"),
    )

    id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    price_date = Column(String, nullable=False)
    price_rappen = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="CHF")
    source = Column(String, nullable=False, default="yfinance")
    fetched_at = Column(String, nullable=False)

    product = relationship("Product", back_populates="price_history")


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    assessment_id = Column(String)
    target_allocation_id = Column(String)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    capital_market_assumptions_id = Column(String)
    run_type = Column(String, nullable=False)
    objective_summary = Column(String)
    optimizer_version = Column(String)
    weighting_regime = Column(String)
    fee_assumptions_json = Column(String)
    other_assets_included = Column(Integer, nullable=False, default=0)
    result_status = Column(String, nullable=False, default="Draft")
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    mandate = relationship("Mandate", back_populates="recommendation_runs")
    positions = relationship("RecommendationPosition", back_populates="run")


class RecommendationPosition(Base):
    __tablename__ = "recommendation_positions"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    target_weight_bps = Column(Integer, nullable=False)
    target_amount_rappen = Column(Integer)
    reference_price_rappen = Column(Integer)
    reference_price_date = Column(String)
    reference_price_source = Column(String)
    reference_lookup_mode = Column(String)
    reference_price_fetched_at = Column(String)
    rationale = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    run = relationship("RecommendationRun", back_populates="positions")
    product = relationship("Product")


class RecommendationHolding(Base):
    __tablename__ = "recommendation_holdings"
    __table_args__ = (
        Index("ix_recommendation_holdings_run_position", "run_id", "recommendation_position_id"),
    )

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    recommendation_position_id = Column(String, ForeignKey("recommendation_positions.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    depot_bank = Column(String)
    custody_account_number = Column(String)
    as_of_date = Column(String)
    units_milli = Column(Integer)
    market_value_rappen = Column(Integer)
    avg_cost_price_rappen = Column(Integer)
    source = Column(String, nullable=False, default="manual")
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    run = relationship("RecommendationRun")
    position = relationship("RecommendationPosition")
    product = relationship("Product")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    user_name = Column(String, nullable=False)
    table_name = Column(String, nullable=False)
    record_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    field_name = Column(String)
    old_value = Column(String)
    new_value = Column(String)
    mandate_id = Column(String)
    client_id = Column(String)
    integrity_hash = Column(String(64))
    created_at = Column(String, nullable=False)
