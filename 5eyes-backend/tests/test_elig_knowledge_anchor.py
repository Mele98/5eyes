"""ELIG-KNOWLEDGE-001 -- a positive appropriateness result needs a
knowledge anchor (schema) and the anchor must document knowledge (router).

Negative results and "Unvollständige Information" stay recordable without
an anchor: this is not a block on knowledge gaps (that remains a hint, see
services.knowledge_asset_class_gap), only on an unsupported positive claim.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from routers.profiling import _risk_assessment_documents_knowledge  # noqa: E402
from schemas.profiling import SuitabilityCheckCreate  # noqa: E402

DUTY = "Angemessenheitsprüfung"


def test_positive_result_with_knowledge_assessment_is_valid():
    check = SuitabilityCheckCreate(duty_type=DUTY, result="Angemessen", knowledge_assessment_id="k-1")
    assert check.knowledge_assessment_id == "k-1"


def test_positive_result_with_risk_assessment_anchor_is_schema_valid():
    check = SuitabilityCheckCreate(duty_type=DUTY, result="Angemessen", risk_assessment_id="ra-1")
    assert check.risk_assessment_id == "ra-1"


def test_positive_result_without_any_anchor_is_rejected():
    with pytest.raises(ValueError, match="Kenntnis-Nachweis"):
        SuitabilityCheckCreate(duty_type=DUTY, result="Angemessen")


@pytest.mark.parametrize("result", ["Nicht angemessen", "Unvollständige Information"])
def test_non_positive_results_stay_recordable_without_anchor(result):
    check = SuitabilityCheckCreate(duty_type=DUTY, result=result)
    assert check.result == result


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, False),
        ("", False),
        ("not json", False),
        ("[]", False),
        ('{"Anlagefonds": {"known": 0, "informed": 0}}', False),
        ('{"Anlagefonds": {"known": 1, "informed": 0}}', True),
        ('{"Aktien": {"known": 0, "informed": 1}}', True),
    ],
)
def test_risk_assessment_is_anchor_only_with_documented_knowledge(payload, expected):
    assessment = SimpleNamespace(knowledge_instruments_json=payload)
    assert _risk_assessment_documents_knowledge(assessment) is expected


def test_missing_risk_assessment_is_no_anchor():
    assert _risk_assessment_documents_knowledge(None) is False
