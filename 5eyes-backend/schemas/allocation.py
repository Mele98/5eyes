from pydantic import BaseModel, Field, model_validator
from typing import Optional
from schemas.common import BaseResponse


class TargetAllocationCreate(BaseModel):
    target_equities_bps: int
    target_bonds_bps: int
    target_real_estate_bps: int
    target_alternatives_bps: int
    target_liquidity_bps: int
    band_equities_min_bps: int
    band_equities_max_bps: int
    band_bonds_min_bps: int
    band_bonds_max_bps: int
    band_real_estate_min_bps: int
    band_real_estate_max_bps: int
    band_alternatives_min_bps: int
    band_alternatives_max_bps: int
    band_liquidity_min_bps: int
    band_liquidity_max_bps: int
    risky_fraction_bps: Optional[int] = None
    based_on_assessment_id: Optional[str] = None
    policy_id: str

    @model_validator(mode="after")
    def validate_alloc(self):
        total = (
            self.target_equities_bps + self.target_bonds_bps
            + self.target_real_estate_bps + self.target_alternatives_bps
            + self.target_liquidity_bps
        )
        if total != 10000:
            raise ValueError(f"Allokation muss 10000 BP ergeben (aktuell: {total})")
        # Band checks
        checks = [
            (self.band_equities_min_bps, self.target_equities_bps, self.band_equities_max_bps, "Aktien"),
            (self.band_bonds_min_bps, self.target_bonds_bps, self.band_bonds_max_bps, "Obligationen"),
            (self.band_real_estate_min_bps, self.target_real_estate_bps, self.band_real_estate_max_bps, "Immobilien"),
            (self.band_alternatives_min_bps, self.target_alternatives_bps, self.band_alternatives_max_bps, "Alternative"),
            (self.band_liquidity_min_bps, self.target_liquidity_bps, self.band_liquidity_max_bps, "Liquidität"),
        ]
        for lo, target, hi, name in checks:
            if not (lo <= target <= hi):
                raise ValueError(f"{name}: Ziel {target} muss zwischen Min {lo} und Max {hi} liegen")
        return self


class TargetAllocationResponse(BaseResponse):
    id: str
    mandate_id: str
    version: int
    is_current: int
    target_equities_bps: int
    target_bonds_bps: int
    target_real_estate_bps: int
    target_alternatives_bps: int
    target_liquidity_bps: int
    band_equities_min_bps: int
    band_equities_max_bps: int
    band_bonds_min_bps: int
    band_bonds_max_bps: int
    band_real_estate_min_bps: int
    band_real_estate_max_bps: int
    band_alternatives_min_bps: int
    band_alternatives_max_bps: int
    band_liquidity_min_bps: int
    band_liquidity_max_bps: int
    risky_fraction_bps: Optional[int]
    based_on_assessment_id: Optional[str]
    policy_id: str
    set_by: str
    set_at: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str


class HouseMatrixResponse(BaseResponse):
    id: str
    policy_id: str
    score_from: int
    score_to: int
    profile_name: str
    liq_min_bps: int
    liq_target_bps: int
    liq_max_bps: int
    bonds_min_bps: int
    bonds_target_bps: int
    bonds_max_bps: int
    equity_min_bps: int
    equity_target_bps: int
    equity_max_bps: int
    real_estate_min_bps: int
    real_estate_target_bps: int
    real_estate_max_bps: int
    alt_min_bps: int
    alt_target_bps: int
    alt_max_bps: int
    equity_minimum_bps: int
    max_risky_fraction_bps: int


class CapitalMarketAssumptionCreate(BaseModel):
    assumption_set_name: str = "Standard"
    valid_from: str
    valid_until: Optional[str] = None
    bonds_chf_ig_return_bps: Optional[int] = None
    bonds_chf_ig_vol_bps: Optional[int] = None
    bonds_fx_hedged_return_bps: Optional[int] = None
    bonds_fx_hedged_vol_bps: Optional[int] = None
    bonds_hy_return_bps: Optional[int] = None
    bonds_hy_vol_bps: Optional[int] = None
    equity_ch_return_bps: Optional[int] = None
    equity_ch_vol_bps: Optional[int] = None
    equity_intl_return_bps: Optional[int] = None
    equity_intl_vol_bps: Optional[int] = None
    equity_em_return_bps: Optional[int] = None
    equity_em_vol_bps: Optional[int] = None
    real_estate_ch_return_bps: Optional[int] = None
    real_estate_ch_vol_bps: Optional[int] = None
    alternatives_gold_return_bps: Optional[int] = None
    alternatives_gold_vol_bps: Optional[int] = None
    liquidity_return_bps: Optional[int] = None
    liquidity_vol_bps: Optional[int] = None
    inflation_path_json: Optional[str] = None
    source: Optional[str] = "Portfolio Management intern"
    notes: Optional[str] = None


class CapitalMarketAssumptionResponse(BaseResponse):
    id: str
    assumption_set_name: str
    version: int
    valid_from: str
    valid_until: Optional[str]
    is_current: int
    bonds_chf_ig_return_bps: Optional[int]
    bonds_chf_ig_vol_bps: Optional[int]
    bonds_fx_hedged_return_bps: Optional[int]
    bonds_fx_hedged_vol_bps: Optional[int]
    bonds_hy_return_bps: Optional[int]
    bonds_hy_vol_bps: Optional[int]
    equity_ch_return_bps: Optional[int]
    equity_ch_vol_bps: Optional[int]
    equity_intl_return_bps: Optional[int]
    equity_intl_vol_bps: Optional[int]
    equity_em_return_bps: Optional[int]
    equity_em_vol_bps: Optional[int]
    real_estate_ch_return_bps: Optional[int]
    real_estate_ch_vol_bps: Optional[int]
    alternatives_gold_return_bps: Optional[int]
    alternatives_gold_vol_bps: Optional[int]
    liquidity_return_bps: Optional[int]
    liquidity_vol_bps: Optional[int]
    inflation_path_json: Optional[str]
    source: Optional[str]
    notes: Optional[str]
    created_at: str


class AllocationBandOverridePayload(BaseModel):
    min_bps: Optional[int] = None
    target_bps: Optional[int] = None
    max_bps: Optional[int] = None


class AllocationPreferencesPayload(BaseModel):
    policy: dict = Field(default_factory=dict)
    tilts: dict = Field(default_factory=dict)
    product: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    geo: dict = Field(default_factory=dict)
    assetClasses: dict = Field(default_factory=dict)
    bands: dict[str, AllocationBandOverridePayload] = Field(default_factory=dict)
    simulation: dict = Field(default_factory=dict)


class BuildingBlockResponse(BaseResponse):
    id: str
    policy_id: str
    asset_class: str
    sub_asset_class: str
    universe: str
    advisory: int
    risky_fraction_bps: int
    contribution_standard_bps: Optional[int]
    contribution_alternative_bps: Optional[int]
    is_active: int
    created_at: str
    updated_at: str


class TargetAllocationGenerateRequest(BaseModel):
    preferences: Optional[AllocationPreferencesPayload] = None


class AllocationBucketResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    current_amount_rappen: int
    target_weight_bps: int
    target_amount_rappen: int
    delta_weight_bps: int
    band_min_bps: int
    band_max_bps: int


class AllocationSubBucketResponse(BaseModel):
    asset_class: str
    sub_asset_class: str
    target_weight_bps: int
    risky_fraction_bps: Optional[int] = None
    rationale: str


class AssetClassAssumptionResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    target_weight_bps: int
    risky_fraction_bps: int
    expected_return_bps: int
    expected_volatility_bps: int
    liquidity_profile: str
    market_data_role: str


class AllocationSimulationEventResponse(BaseModel):
    year: int
    mode: str
    breached_buckets: list[str]
    turnover_rappen: int
    notes: str


class AllocationSimulationResponse(BaseModel):
    horizon_years: int
    start_year: int
    year_labels: list[int]
    rebalance_mode: str
    stress_multiplier: float
    current_mix_series_rappen: list[int]
    target_mix_series_rappen: list[int]
    downside_series_rappen: list[int]
    upside_series_rappen: list[int]
    real_target_series_rappen: list[int]
    inflation_series_bps: list[int]
    rebalancing_events: list[AllocationSimulationEventResponse]


class GoalAnalysisResponse(BaseModel):
    goal_id: str
    label: str
    goal_type: str
    goal_scope: str
    rank: int
    weight_bps: int
    target_amount_rappen: int
    target_wealth_rappen: Optional[int] = None
    target_return_bps: Optional[int] = None
    projected_value_rappen: int
    achievement_score: int
    status: str
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    horizon_years: Optional[int] = None
    is_ongoing: Optional[int] = None
    frequency: Optional[str] = None
    timing_label: Optional[str] = None
    path_success_rate_pct: Optional[int] = None
    funded_ratio_p50: Optional[float] = None
    projected_value_p10_rappen: Optional[int] = None
    projected_value_p50_rappen: Optional[int] = None
    projected_value_p90_rappen: Optional[int] = None


class MonteCarloGoalSummaryResponse(BaseModel):
    goal_id: str
    label: str
    years: int
    success_rate_pct: int
    funded_ratio_p50: float
    projected_value_p10_rappen: int
    projected_value_p50_rappen: int
    projected_value_p90_rappen: int
    score: int


class MonteCarloResponse(BaseModel):
    simulations: int
    seed: int
    horizon_years: int
    start_year: int
    year_labels: list[int]
    current_p10_series_rappen: list[int]
    current_p50_series_rappen: list[int]
    current_p90_series_rappen: list[int]
    target_p10_series_rappen: list[int]
    target_p50_series_rappen: list[int]
    target_p90_series_rappen: list[int]
    current_annualized_return_p50_bps: int
    target_annualized_return_p50_bps: int
    target_var_95_1y_bps: int
    target_cvar_95_1y_bps: int
    target_loss_probability_1y_pct: int
    target_max_drawdown_p50_bps: int
    target_max_drawdown_p95_bps: int
    target_downside_probability_pct: int
    goal_summaries: list[MonteCarloGoalSummaryResponse]


class LiveRebalancingPositionResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    asset_class: str
    sub_asset_class: Optional[str] = None
    target_weight_bps: int
    target_amount_rappen: int
    current_weight_bps: int
    current_market_value_rappen: int
    delta_weight_bps: int
    rebalance_amount_rappen: int
    reference_price_date: Optional[str] = None
    reference_price_rappen: Optional[int] = None
    reference_recalibrated: bool = False
    latest_price_date: Optional[str] = None
    latest_price_rappen: Optional[int] = None
    price_change_bps: Optional[int] = None
    holding_present: bool = False
    holding_source: Optional[str] = None
    holding_as_of_date: Optional[str] = None
    holding_units_milli: Optional[int] = None
    current_units_milli: Optional[int] = None
    holding_market_value_rappen: Optional[int] = None
    holding_avg_cost_price_rappen: Optional[int] = None
    holding_depot_bank: Optional[str] = None
    holding_custody_account_number: Optional[str] = None
    holding_notes: Optional[str] = None
    valuation_basis: Optional[str] = None
    implied_units_milli: Optional[int] = None
    price_age_days: Optional[int] = None
    price_is_fresh: Optional[bool] = None
    rebalance_action: str


class LiveRebalancingBucketResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    target_weight_bps: int
    band_min_bps: int
    band_max_bps: int
    current_market_value_rappen: int
    target_market_value_rappen: int
    delta_weight_bps: int
    rebalance_amount_rappen: int
    breached: bool
    breach_bps: int


class LiveRebalancingResponse(BaseModel):
    as_of_date: Optional[str] = None
    reference_anchor_date: Optional[str] = None
    methodology: str
    live_total_value_rappen: int
    priced_positions_count: int
    stale_positions_count: int
    missing_prices_count: int
    holding_positions_count: int = 0
    implied_positions_count: int = 0
    recalibrated_positions_count: int = 0
    turnover_required_rappen: int
    breached_asset_classes: list[str]
    action_summary: list[str]
    market_data_quality: dict = Field(default_factory=dict)
    bucket_drifts: list[LiveRebalancingBucketResponse]
    position_drifts: list[LiveRebalancingPositionResponse]


class TargetAllocationGenerateResponse(BaseModel):
    target_allocation: TargetAllocationResponse
    house_matrix_profile: str
    score_bucket: int
    advisory_wealth_rappen: int
    total_wealth_rappen: int
    annual_net_cashflow_rappen: int
    cashflow_projection_series_rappen: list[int]
    reserve_needed_rappen: int
    risk_budget_bps: int
    risky_fraction_total_bps: int
    risky_fraction_headroom_bps: int
    asset_class_risky_weights_bps: dict[str, int]
    expected_return_bps: int
    expected_volatility_bps: int
    capital_market_assumption_set: Optional[str] = None
    capital_market_source: Optional[str] = None
    reasoning: list[str]
    buckets: list[AllocationBucketResponse]
    sub_allocations: list[AllocationSubBucketResponse]
    asset_class_assumptions: list[AssetClassAssumptionResponse]
    simulation: AllocationSimulationResponse
    monte_carlo: MonteCarloResponse
    goal_analysis: list[GoalAnalysisResponse]
    live_rebalancing: Optional[LiveRebalancingResponse] = None
