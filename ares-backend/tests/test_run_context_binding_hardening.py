"""Haertung der RunContext-Bindung (Pruefbefunde, niedrig).

1. ``RunContext.ensure_bound_to`` verglich nur die Mandats-ID: zwei
   verschiedene ungespeicherte Mandate (beide ``id=None``) galten als
   "dasselbe Mandat". Jetzt fail-closed: bei fehlender ID nur gebunden, wenn
   ``mandate`` exakt das Objekt ist, aus dem der Kontext gebildet wurde.
2. ``portfolio_engine_payload._expected_death_year_offset_from_mandate``
   verschluckte ``RunContextMandateMismatch`` im Report-Fallback
   ``except Exception: return None`` -> der Mortalitaets-Cutoff fehlte still.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import RunContext, RunContextMandateMismatch  # noqa: E402
from jurisdictions.resolve import resolve_pack  # noqa: E402
import services.mortality.horizon as horizon  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
import services.portfolio_engine_payload as payload  # noqa: E402

_CFG = SimpleNamespace(optimizer_mode="stochastic")


def _unsaved(jurisdiction="CH"):
    return SimpleNamespace(id=None, jurisdiction=jurisdiction)


# --- 1: Bindung bei id=None ------------------------------------------------


def test_two_unsaved_mandates_are_not_bound_to_each_other():
    first, second = _unsaved(), _unsaved()
    ctx = pe.build_run_context(first)
    assert ctx.mandate_id is None
    with pytest.raises(RunContextMandateMismatch, match=r"RunContext gehoert zu Mandat None"):
        ctx.ensure_bound_to(second)


def test_unsaved_mandate_stays_bound_to_its_own_context():
    mandate = _unsaved()
    ctx = pe.build_run_context(mandate)
    assert ctx.ensure_bound_to(mandate) is ctx


def test_context_without_id_and_without_object_binds_nothing():
    ctx = RunContext.capture(resolve_pack(code="CH"), _CFG, mandate_id=None)
    with pytest.raises(RunContextMandateMismatch):
        ctx.ensure_bound_to(_unsaved())
    with pytest.raises(RunContextMandateMismatch):
        ctx.ensure_bound_to(SimpleNamespace(jurisdiction="CH"))  # ganz ohne ``id``-Attribut


@pytest.mark.parametrize("ctx_id, mandate_id", [(None, "m-1"), ("m-1", None)])
def test_id_on_one_side_only_is_a_mismatch(ctx_id, mandate_id):
    mandate = SimpleNamespace(id=mandate_id, jurisdiction="CH")
    ctx = RunContext.capture(resolve_pack(code="CH"), _CFG, mandate_id=ctx_id, mandate=mandate)
    with pytest.raises(RunContextMandateMismatch):
        ctx.ensure_bound_to(mandate)


def test_saved_mandates_still_compare_by_id_only():
    ctx = pe.build_run_context(SimpleNamespace(id="m-1", jurisdiction="CH"))
    # anderes Objekt, gleiche ID -> gebunden (unveraendert)
    assert ctx.ensure_bound_to(SimpleNamespace(id="m-1", jurisdiction="DE")) is ctx
    with pytest.raises(RunContextMandateMismatch):
        ctx.ensure_bound_to(SimpleNamespace(id="m-2", jurisdiction="CH"))


def test_bound_mandate_is_not_part_of_equality_or_repr():
    mandate = _unsaved()
    with_obj = RunContext.capture(resolve_pack(code="CH"), _CFG, mandate_id=None, mandate=mandate)
    without = RunContext.capture(resolve_pack(code="CH"), _CFG, mandate_id=None)
    assert with_obj == without
    assert "bound_mandate" not in repr(with_obj)


# --- 2: Payload-Report-Fallback verschluckt keinen Mismatch -----------------


def _mortality_mandate(mandate_id):
    return SimpleNamespace(
        id=mandate_id, jurisdiction="CH", life_expectancy_year=0, use_mortality_simulation=1,
        client_birth_year=1960, client_sex="M", client=None,
    )


def test_payload_wrapper_reraises_run_context_mismatch():
    ctx_a = pe.build_run_context(_mortality_mandate("mandate-A"))
    with pytest.raises(RunContextMandateMismatch, match=r"'mandate-A'.*'mandate-B'"):
        payload._expected_death_year_offset_from_mandate(_mortality_mandate("mandate-B"), run_context=ctx_a)


def test_payload_wrapper_bound_context_still_returns_cutoff():
    mandate = _mortality_mandate("mandate-A")
    offset = payload._expected_death_year_offset_from_mandate(mandate, run_context=pe.build_run_context(mandate))
    assert isinstance(offset, int)


@pytest.mark.parametrize("with_context", [False, True])
def test_payload_wrapper_other_errors_keep_report_fallback(monkeypatch, with_context):
    mandate = _mortality_mandate("mandate-A")

    def boom(*_a, **_k):
        raise RuntimeError("defekte Sterbetafel")

    monkeypatch.setattr(horizon, "resolve_mortality_cutoff", boom)
    kwargs = {"run_context": pe.build_run_context(mandate)} if with_context else {}
    assert payload._expected_death_year_offset_from_mandate(mandate, **kwargs) is None
