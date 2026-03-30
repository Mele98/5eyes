from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class OptimizerPolicy(Base):
    __tablename__ = "optimizer_policies"

    id = Column(String, primary_key=True)
    policy_name = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    optimizer_engine = Column(String, nullable=False, default="goal_based_v1")
    max_real_estate_bps = Column(Integer, nullable=False, default=2000)
    max_alternatives_bps = Column(Integer, nullable=False, default=1000)
    min_liquidity_bps = Column(Integer, nullable=False, default=0)
    allow_other_assets_for_goals = Column(Integer, nullable=False, default=1)
    fee_model_json = Column(String)
    notes = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    building_blocks = relationship("BuildingBlock", back_populates="policy")
    house_matrix_entries = relationship("HouseMatrix", back_populates="policy")


class TargetAllocation(Base):
    __tablename__ = "target_allocations"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    target_equities_bps = Column(Integer, nullable=False, default=0)
    target_bonds_bps = Column(Integer, nullable=False, default=0)
    target_real_estate_bps = Column(Integer, nullable=False, default=0)
    target_alternatives_bps = Column(Integer, nullable=False, default=0)
    target_liquidity_bps = Column(Integer, nullable=False, default=0)
    band_equities_min_bps = Column(Integer, nullable=False)
    band_equities_max_bps = Column(Integer, nullable=False)
    band_bonds_min_bps = Column(Integer, nullable=False)
    band_bonds_max_bps = Column(Integer, nullable=False)
    band_real_estate_min_bps = Column(Integer, nullable=False)
    band_real_estate_max_bps = Column(Integer, nullable=False)
    band_alternatives_min_bps = Column(Integer, nullable=False)
    band_alternatives_max_bps = Column(Integer, nullable=False)
    band_liquidity_min_bps = Column(Integer, nullable=False)
    band_liquidity_max_bps = Column(Integer, nullable=False)
    risky_fraction_bps = Column(Integer)
    based_on_assessment_id = Column(String)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    set_by = Column(String, ForeignKey("users.id"), nullable=False)
    set_at = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"))
    approved_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="target_allocations")
    policy = relationship("OptimizerPolicy")


class CapitalMarketAssumption(Base):
    __tablename__ = "capital_market_assumptions"

    id = Column(String, primary_key=True)
    assumption_set_name = Column(String, nullable=False, default="Standard")
    version = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_until = Column(String)
    is_current = Column(Integer, nullable=False, default=1)
    bonds_chf_ig_return_bps = Column(Integer)
    bonds_chf_ig_vol_bps = Column(Integer)
    bonds_fx_hedged_return_bps = Column(Integer)
    bonds_fx_hedged_vol_bps = Column(Integer)
    bonds_hy_return_bps = Column(Integer)
    bonds_hy_vol_bps = Column(Integer)
    equity_ch_return_bps = Column(Integer)
    equity_ch_vol_bps = Column(Integer)
    equity_intl_return_bps = Column(Integer)
    equity_intl_vol_bps = Column(Integer)
    equity_em_return_bps = Column(Integer)
    equity_em_vol_bps = Column(Integer)
    real_estate_ch_return_bps = Column(Integer)
    real_estate_ch_vol_bps = Column(Integer)
    alternatives_gold_return_bps = Column(Integer)
    alternatives_gold_vol_bps = Column(Integer)
    liquidity_return_bps = Column(Integer)
    liquidity_vol_bps = Column(Integer)
    inflation_path_json = Column(String)
    source = Column(String, default="Portfolio Management intern")
    notes = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)


class BuildingBlock(Base):
    __tablename__ = "building_blocks"

    id = Column(String, primary_key=True)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    asset_class = Column(String, nullable=False)
    sub_asset_class = Column(String, nullable=False)
    universe = Column(String, nullable=False, default="Standard")
    advisory = Column(Integer, nullable=False, default=1)
    risky_fraction_bps = Column(Integer, nullable=False)
    contribution_standard_bps = Column(Integer)
    contribution_alternative_bps = Column(Integer)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    policy = relationship("OptimizerPolicy", back_populates="building_blocks")


class HouseMatrix(Base):
    __tablename__ = "house_matrix"

    id = Column(String, primary_key=True)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    score_from = Column(Integer, nullable=False)
    score_to = Column(Integer, nullable=False)
    profile_name = Column(String, nullable=False)
    liq_min_bps = Column(Integer, nullable=False)
    liq_target_bps = Column(Integer, nullable=False)
    liq_max_bps = Column(Integer, nullable=False)
    bonds_min_bps = Column(Integer, nullable=False)
    bonds_target_bps = Column(Integer, nullable=False)
    bonds_max_bps = Column(Integer, nullable=False)
    equity_min_bps = Column(Integer, nullable=False)
    equity_target_bps = Column(Integer, nullable=False)
    equity_max_bps = Column(Integer, nullable=False)
    real_estate_min_bps = Column(Integer, nullable=False)
    real_estate_target_bps = Column(Integer, nullable=False)
    real_estate_max_bps = Column(Integer, nullable=False)
    alt_min_bps = Column(Integer, nullable=False)
    alt_target_bps = Column(Integer, nullable=False)
    alt_max_bps = Column(Integer, nullable=False)
    equity_minimum_bps = Column(Integer, nullable=False, default=0)
    max_risky_fraction_bps = Column(Integer, nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    policy = relationship("OptimizerPolicy", back_populates="house_matrix_entries")
