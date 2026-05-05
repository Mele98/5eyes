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
    # Deprecated since audit-B4 (2026-05-01): goals are always evaluated against
    # advisory_wealth (ASIP §3.2). Field is retained for schema compatibility but
    # has no effect on scoring. Do not read or write from new code.
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
    capital_market_assumptions_id = Column(String, ForeignKey("capital_market_assumptions.id"))
    # C8: Audit-Anker fuer Reproduzierbarkeit / Drift-Erkennung.
    preferences_json = Column(String)
    input_snapshot_hash = Column(String)
    advisory_wealth_at_generation_rappen = Column(Integer)
    total_wealth_at_generation_rappen = Column(Integer)
    reserve_needed_at_generation_rappen = Column(Integer)
    external_reserve_at_generation_rappen = Column(Integer)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    set_by = Column(String, ForeignKey("users.id"), nullable=False)
    set_at = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"))
    approved_at = Column(String)
    # Optimizer-Audit-Anchor (Spec 2026-05-05). Wenn None: Allocation
    # kommt aus House-Matrix-Default (vor-Optimizer Baseline).
    optimization_method = Column(String)  # 'house_matrix' | 'iterative' | 'stochastic'
    optimization_objective_value_milli = Column(Integer)  # objective in milli (Praezision)
    optimization_iterations = Column(Integer)
    optimization_seed = Column(Integer)
    optimization_status = Column(String)  # 'converged' | 'diverged' | 'timeout' | 'fallback_house_matrix'
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
    correlation_matrix_json = Column(String)
    sub_asset_class_assumptions_json = Column(String)
    # Optimizer-Phase 1 (Spec 2026-05-05): Skewness und Excess-Kurtosis pro
    # Bucket. Default None bzw. 0 -> Cornish-Fisher faellt auf Normal zurueck
    # (backwards-compat, kein Verhaltens-Change ohne SLAM-Daten). Werte in bps
    # (z.B. equities_skewness_bps=-5000 = -0.5 skew, excess_kurt_bps=25000 = 2.5).
    equities_skewness_bps = Column(Integer)
    equities_excess_kurt_bps = Column(Integer)
    bonds_skewness_bps = Column(Integer)
    bonds_excess_kurt_bps = Column(Integer)
    real_estate_skewness_bps = Column(Integer)
    real_estate_excess_kurt_bps = Column(Integer)
    alternatives_skewness_bps = Column(Integer)
    alternatives_excess_kurt_bps = Column(Integer)
    liquidity_skewness_bps = Column(Integer)
    liquidity_excess_kurt_bps = Column(Integer)
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
