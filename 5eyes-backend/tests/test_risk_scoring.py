from services.risk_scoring import canonicalize_horizon_label, compute_scores, map_surplus_points


def test_short_horizon_forces_capacity_score_to_zero():
    result = compute_scores(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Bis 2 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert result.risk_capacity_total == 32
    assert result.risk_capacity_profile == "Dynamisch"
    assert result.risk_capacity_score_x10 == 0
    assert result.risk_willingness_score_x10 == 100
    assert result.final_score_x10 == 0
    assert result.final_profile == "Kapitalschutz"


def test_balanced_capacity_and_growth_willingness_land_in_growth_profile():
    result = compute_scores(
        q_income_points=2,
        q_obligations_points=0,
        q_savings_points=6,
        q_wealth_points=6,
        investment_horizon_label="8 bis 11 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )

    assert result.risk_capacity_total == 14
    assert result.risk_capacity_profile == "Dynamisch"
    assert result.risk_capacity_score_x10 == 70
    assert result.risk_willingness_total == 9
    assert result.risk_willingness_profile == "Wachstumsorientiert"
    assert result.risk_willingness_score_x10 == 70
    assert result.final_score_x10 == 70
    assert result.final_profile == "Wachstumsorientiert"


def test_half_step_scores_round_half_up_instead_of_bankers_rounding():
    result = compute_scores(
        q_income_points=0,
        q_obligations_points=3,
        q_savings_points=0,
        q_wealth_points=0,
        investment_horizon_label="6 bis 7 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert result.risk_capacity_total == 3
    assert result.risk_capacity_profile == "Sicherheitsorientiert"
    assert result.risk_capacity_score_x10 == 45
    assert result.final_score_x10 == 45
    assert result.final_profile == "Ausgewogen"


def test_maximum_willingness_can_reach_score_100_and_aktien_profile():
    result = compute_scores(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert result.risk_willingness_score_x10 == 100
    assert result.final_score_x10 == 100
    assert result.final_profile == "Aktien"


def test_willingness_linear_no_buckets():
    total_10 = compute_scores(
        q_income_points=4,
        q_obligations_points=0,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    total_11 = compute_scores(
        q_income_points=4,
        q_obligations_points=0,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=3,
    )

    assert total_10.risk_willingness_total == 10
    assert total_10.risk_willingness_score_x10 == 80
    assert total_11.risk_willingness_total == 11
    assert total_11.risk_willingness_score_x10 == 90


def test_surplus_ratio_replaces_obligations():
    assert map_surplus_points(4000, 3000) == 3
    assert map_surplus_points(30000, 24000) == 2


def test_fzk_horizon_labels_map_cleanly_into_scoring_matrix():
    result = compute_scores(
        q_income_points=3,
        q_obligations_points=3,
        q_savings_points=9,
        q_wealth_points=9,
        investment_horizon_label="5 bis 7 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )

    assert result.risk_capacity_total == 24
    assert result.risk_capacity_profile == "Dynamisch"
    assert result.risk_capacity_score_x10 == 60


def test_willingness_questions_are_monotonic_across_all_four_answers():
    scores = []
    for goal_points in (1, 2, 3, 4):
        result = compute_scores(
            q_income_points=4,
            q_obligations_points=0,
            q_savings_points=12,
            q_wealth_points=12,
            investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=goal_points,
            q_risk_preference_points=1,
            q_risk_behavior_points=1,
        )
        scores.append(result.risk_willingness_score_x10)

    assert scores == [10, 20, 30, 40]


def test_capacity_horizon_is_binding_even_when_willingness_is_maximal():
    short_horizon = compute_scores(
        q_income_points=4,
        q_obligations_points=0,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="0 bis 4 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )
    long_horizon = compute_scores(
        q_income_points=4,
        q_obligations_points=0,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="12 Jahre und mehr",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert short_horizon.risk_willingness_score_x10 == 100
    assert long_horizon.risk_willingness_score_x10 == 100
    assert short_horizon.risk_capacity_score_x10 < long_horizon.risk_capacity_score_x10
    assert short_horizon.final_score_x10 < long_horizon.final_score_x10


def test_new_frontend_horizon_labels_are_canonicalized_for_persistence():
    assert canonicalize_horizon_label("12 Jahre und mehr") == "Mehr als 12 Jahre"
    assert canonicalize_horizon_label("5 bis 7 Jahre") == "6 bis 7 Jahre"
    assert canonicalize_horizon_label("0 bis 4 Jahre") == "2 bis 3 Jahre"


def test_final_score_stays_flat_when_non_binding_side_changes_only():
    capacity_bound = compute_scores(
        q_income_points=1,
        q_obligations_points=0,
        q_savings_points=3,
        q_wealth_points=3,
        investment_horizon_label="8 bis 11 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )
    willingness_changed_only = compute_scores(
        q_income_points=1,
        q_obligations_points=0,
        q_savings_points=3,
        q_wealth_points=3,
        investment_horizon_label="8 bis 11 Jahre",
        q_investment_goal_points=2,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )
    capacity_improved = compute_scores(
        q_income_points=4,
        q_obligations_points=0,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="8 bis 11 Jahre",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert capacity_bound.final_score_x10 == capacity_bound.risk_capacity_score_x10
    assert willingness_changed_only.risk_willingness_score_x10 < capacity_bound.risk_willingness_score_x10
    assert willingness_changed_only.final_score_x10 == capacity_bound.final_score_x10
    assert capacity_improved.risk_capacity_score_x10 > capacity_bound.risk_capacity_score_x10
    assert capacity_improved.final_score_x10 > capacity_bound.final_score_x10


def test_surplus_thresholds_cover_all_bands():
    assert map_surplus_points(1000, 1100) == 0
    assert map_surplus_points(1000, 950) == 1
    assert map_surplus_points(1000, 850) == 2
    assert map_surplus_points(1000, 700) == 3
    assert map_surplus_points(1000, 500) == 4
