import pytest
from services.portfolio_engine import _enforce_risk_budget


def test_enforce_risk_budget_raises_when_constraints_prevent_full_compliance():
    with pytest.raises(ValueError, match="Risikobudget konnte nicht eingehalten werden"):
        _enforce_risk_budget(
            targets={
                "equities": 6000,
                "bonds": 0,
                "real_estate": 2000,
                "alternatives": 2000,
                "liquidity": 0,
            },
            minimums={
                "equities": 6000,
                "bonds": 0,
                "real_estate": 2000,
                "alternatives": 2000,
                "liquidity": 0,
            },
            maximums={
                "equities": 6000,
                "bonds": 0,
                "real_estate": 2000,
                "alternatives": 2000,
                "liquidity": 0,
            },
            asset_risky_weights={
                "equities": 10000,
                "bonds": 1500,
                "real_estate": 7000,
                "alternatives": 9000,
                "liquidity": 0,
            },
            risk_budget_bps=5000,
        )
