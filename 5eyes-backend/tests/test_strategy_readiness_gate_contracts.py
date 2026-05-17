from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _function_block(path: str, name: str) -> str:
    source = (BACKEND_ROOT / path).read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    next_def = source.find("\ndef ", start + 1)
    next_route = source.find("\n@router", start + 1)
    candidates = [idx for idx in (next_def, next_route) if idx != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def test_direct_recommendation_create_uses_strategy_ready_assessment_gate():
    block = _function_block("routers/review.py", "create_recommendation_run")

    assert "require_strategy_ready_assessment" in block
    assert "final_score_x10 is None" not in block


def test_max_spending_uses_strategy_ready_assessment_gate():
    block = _function_block("routers/wealth.py", "calculate_max_pension_spending")

    assert "require_strategy_ready_assessment" in block
    assert "db.query(RiskAssessment)" not in block


def test_recommendation_payload_builders_use_strategy_ready_assessment_gate():
    source = (BACKEND_ROOT / "services/portfolio_engine.py").read_text(encoding="utf-8")

    for name in (
        "evaluate_goal_sensitivity",
        "build_recommendation_payload_from_run",
        "generate_recommendation_run",
    ):
        block = _function_block("services/portfolio_engine.py", name)
        assert "require_strategy_ready_assessment" in block

    assert source.count("require_strategy_ready_assessment(db, mandate.id)") >= 4


def test_strategy_generation_and_payload_rebuild_require_customer_inputs():
    generate_block = _function_block("services/portfolio_engine.py", "generate_target_allocation")
    rebuild_block = _function_block("services/portfolio_engine.py", "build_target_payload_from_allocation")

    assert "_require_customer_strategy_inputs(inputs)" in generate_block
    assert "_require_customer_strategy_inputs({" in rebuild_block
