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
    # Phase 6: persistierte Stress-Auswertungen aus dem Solver (Phase 5.2),
    # JSON-serialisiertes dict[scenario_name, dict]. NULL bei house_matrix-Modus.
    # Damit kann das FE-Optimizer-Panel auch beim Reload (GET-Endpoint) die
    # Stress-Tabelle ohne erneuten Solver-Lauf rendern.
    stress_evaluations_json = Column(String)
    # Phase 6.2: persistierter Reasoning-Trace des Solvers (list[str] als JSON).
    # Nur die optimizer-spezifischen Zeilen werden gespeichert; die generischen
    # House-Matrix-Sätze und dynamischen Drift-Warnings werden im Read-Pfad
    # frisch berechnet. NULL bei house_matrix-Modus.
    optimizer_reasoning_json = Column(String)
    # V3 Sprint 2.1 (2026-05-09 / Plan §4.1): Verknuepfung zur optimizer_runs-
    # Zeile, die diese TA produziert hat. NULL bei house_matrix-Modus oder
    # bei shadow_stochastic (TA bleibt House-Matrix-basiert; der Run gehoert
    # nicht zur TA — nur stochastic-Modus aktualisiert die TA aus dem Solver).
    optimization_run_id = Column(String, ForeignKey("optimizer_runs.id"))
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="target_allocations")
    policy = relationship("OptimizerPolicy")
    optimization_run = relationship("OptimizerRun", foreign_keys=[optimization_run_id])


class OptimizerRun(Base):
    """V3 Sprint 2 (Plan §4.1): persistierter Audit-Trail aller Solver-Laufe.

    Im Gegensatz zur TargetAllocation, die nur den jeweils aktiven Stand
    haelt, sammelt diese Tabelle JEDEN Solver-Lauf — auch shadow_stochastic
    Laufe, die die TargetAllocation nicht ersetzen. Damit ist eine Advisory-Methodik-
    artige Risk-Engine-Historie moeglich (mehrere Runs, Seeds, Szenarien,
    Versionen).

    Persistenz-Trigger (siehe portfolio_engine._persist_optimizer_run):
    - 'shadow_stochastic'-Modus + Solver lief: ja
    - 'stochastic'-Modus + Solver lief: ja
    - 'house_matrix' / 'iterative': nein (Solver lief nicht)

    Verknuepfung optional zu target_allocation_id: bei stochastic-Modus
    zeigt sie auf die zugehoerige TA; bei shadow_stochastic ist sie NULL,
    weil die TA House-Matrix-basiert ist und nicht zum Run gehoert.
    """
    __tablename__ = "optimizer_runs"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    # use_alter=True bricht den Zyklus optimizer_runs <-> target_allocations
    # fuer SQLAlchemy DROP-Sortierung in Tests. Production-Lauf unbeeinflusst.
    target_allocation_id = Column(
        String, ForeignKey("target_allocations.id", use_alter=True, name="fk_optimizer_runs_target_allocation"),
    )
    run_at = Column(String, nullable=False)
    optimizer_mode = Column(String, nullable=False)  # 'shadow_stochastic' | 'stochastic'
    role = Column(String, nullable=False)  # 'shadow' | 'active'
    method = Column(String, nullable=False)  # 'stochastic' | 'fallback_house_matrix'
    status = Column(String, nullable=False)  # converged | diverged | diverged_infeasible | fallback_house_matrix
    seed = Column(Integer, nullable=False)
    n_paths = Column(Integer, nullable=False, default=0)
    n_iterations = Column(Integer, nullable=False, default=0)
    n_starts_attempted = Column(Integer, nullable=False, default=0)
    objective_value_milli = Column(Integer)
    weights_bps_json = Column(String, nullable=False)  # {"equities":...,"bonds":...,...}
    constraint_violations_json = Column(String)  # JSON list[str]
    reasoning_json = Column(String)  # JSON list[str]
    stress_evaluations_json = Column(String)  # JSON dict
    set_by = Column(String, ForeignKey("users.id"))
    created_at = Column(String, nullable=False)

    mandate = relationship("Mandate")
    target_allocation = relationship("TargetAllocation", foreign_keys=[target_allocation_id])


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
    # (backwards-compat, kein Verhaltens-Change ohne CMA-Daten). Werte in bps
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
    # Sprint 6 Phase 2 (2026-05-17): Nelson-Siegel Yield-Curve fuer Bonds.
    # Wenn alle 4 Felder gesetzt (!= None): scenario_inputs_from_cma nutzt
    # die NS-Curve fuer Bond-Returns (yield_at(maturity)) statt der fixen
    # bonds_*_return_bps Werte. lambda_x100 = lambda * 100 (Integer-DB).
    # Beispiel ZH-CHF-Kurve 2024: beta0=400, beta1=-200, beta2=80, lambda=60 (=0.6).
    bonds_ns_beta0_bps = Column(Integer)
    bonds_ns_beta1_bps = Column(Integer)
    bonds_ns_beta2_bps = Column(Integer)
    bonds_ns_lambda_x100 = Column(Integer)
    # Sprint 7 (2026-05-17): KGV-Mean-Reversion fuer Equity-Returns.
    # Wenn alle 3 Felder gesetzt: scenario_inputs_from_cma addiert ein
    # KGV-MR-Adjustment auf equity_*_return_bps. Werte als Integer skaliert:
    # kgv_*_x10 = KGV * 10 (z.B. 220 = 22.0), alpha_x100 = alpha*100 (15 = 0.15).
    # Beispiel SPX 2026: kgv_current=220, kgv_fair=170, alpha=15.
    equity_kgv_current_x10 = Column(Integer)
    equity_kgv_fair_x10 = Column(Integer)
    equity_kgv_alpha_x100 = Column(Integer)
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
