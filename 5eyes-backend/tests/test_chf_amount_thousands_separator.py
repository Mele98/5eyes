"""CHF-AMOUNT-THOUSANDS-001 (Assetallocation-Audit 2026-10-14).

"Min. Reserve CHF" / "Liquiditaetsreserve-Ziel" are free-text CHF amounts.
Both the schema and the engine replaced "," by "." and called float(), so a
thousands grouping became a decimal point: "50.000" and "50,000" were read as
CHF 50 instead of CHF 50'000 (factor 1000 on the client's reserve), and
"50.000,50" was silently dropped by the engine.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.chf_amount import normalize_chf_amount_text
from schemas.allocation import AllocationPreferencesPayload
from services.portfolio_engine import _parse_rappen


@pytest.mark.parametrize(
    "text,expected_rappen",
    [
        ("50000", 5_000_000),
        ("50'000", 5_000_000),
        ("CHF 50'000.50", 5_000_050),
        ("50 000", 5_000_000),
        ("50.000", 5_000_000),       # was CHF 50
        ("50,000", 5_000_000),       # was CHF 50
        ("1.250.000", 125_000_000),  # was rejected/None
        ("50.000,50", 5_000_050),    # was silently None
        ("1,250,000.50", 125_000_050),
        ("123,45", 12_345),
        ("1.5", 150),
        (50000, 5_000_000),
        (1250.5, 125_050),
    ],
)
def test_engine_parses_chf_amounts(text, expected_rappen):
    assert _parse_rappen(text) == expected_rappen


@pytest.mark.parametrize("text", ["50.0000", "5.00.000", "50.000.5", "50,00,000", "abc", "1e6"])
def test_ambiguous_shapes_are_rejected_not_guessed(text):
    assert normalize_chf_amount_text(text) is None
    assert _parse_rappen(text) is None


def test_schema_accepts_grouping_and_rejects_ambiguous_amounts():
    AllocationPreferencesPayload(limits={"minReserve": "50.000"})
    AllocationPreferencesPayload(assetClasses={"liquidityReserveTarget": "50,000"})
    with pytest.raises(ValidationError, match="CHF-Betrag"):
        AllocationPreferencesPayload(limits={"minReserve": "50.000.5"})
