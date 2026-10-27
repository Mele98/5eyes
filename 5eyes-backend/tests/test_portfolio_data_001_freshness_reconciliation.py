"""PORTFOLIO-DATA-001: Depot-Frische und Vermoegensabgleich als versionierte Policy.

Entscheiddokument 2026-10-27, Abschnitt 6 und 7 Punkt 5. Die vorgeschlagenen
Schwellen liegen als Policy-Daten mit Status PROPOSED vor und blockieren
nichts; nur eine freigegebene Policy (APPROVED, alle Rollen, verschiedene
Personen) setzt das Gate durch. Reine Logik, keine Datenbank.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone

import pytest

from services.bank_calendar import (
    BankCalendar,
    WeekendOnlyBankCalendar,
    business_days_elapsed,
    calendar_for_id,
)
from services.portfolio_data_freshness import FreshnessInputError, assess_freshness
from services.portfolio_data_policy import (
    PortfolioDataPolicyError,
    _default_policy_path,
    evaluate_portfolio_data_gate,
    load_portfolio_data_policy,
    parse_portfolio_data_policy,
)
from services.portfolio_reconciliation import (
    finalization_binding,
    reconcile_portfolio,
    verify_finalization_binding,
)

COMPONENTS = (
    "holdings_as_of", "cash_as_of", "price_as_of", "fx_as_of", "corporate_actions_checked_at",
)


def _raw_policy() -> dict:
    return json.loads(_default_policy_path().read_text(encoding="utf-8"))


def _approved_raw() -> dict:
    raw = _raw_policy()
    raw["status"] = "APPROVED"
    raw["approvals"] = [
        {"role": "investment", "approved_by": "person-a", "approved_at": "2026-11-01", "reference": "IC-1"},
        {"role": "compliance", "approved_by": "person-b", "approved_at": "2026-11-01", "reference": "CO-1"},
        {"role": "operations", "approved_by": "person-c", "approved_at": "2026-11-01", "reference": "OPS-1"},
    ]
    return raw


@pytest.fixture
def policy():
    return load_portfolio_data_policy()


@pytest.fixture
def active_policy():
    return parse_portfolio_data_policy(_approved_raw())


def _components(as_of="2026-10-23", **overrides) -> dict:
    comps = {name: {"as_of": as_of, "source": "custodian-feed"} for name in COMPONENTS}
    comps.update(overrides)
    return comps


# --- Policy ---------------------------------------------------------------

def test_shipped_policy_is_proposed_and_not_active(policy):
    assert policy.status == "PROPOSED"
    assert policy.is_active is False
    assert policy.approvals == ()
    assert policy.required_components == COMPONENTS
    assert (policy.final_max_business_days, policy.draft_max_business_days) == (1, 5)
    assert (policy.per_position_tolerance_minor_units, policy.aggregate_tolerance_major_units) == (1, 1)
    assert set(policy.required_approver_roles) == {"investment", "compliance", "operations"}
    assert len(policy.policy_hash) == 64


def test_approved_policy_needs_every_role_and_distinct_people():
    assert parse_portfolio_data_policy(_approved_raw()).is_active is True

    missing_role = _approved_raw()
    missing_role["approvals"] = missing_role["approvals"][:2]
    assert parse_portfolio_data_policy(missing_role).is_active is False

    same_person = _approved_raw()
    same_person["approvals"][2]["approved_by"] = "person-a"
    assert parse_portfolio_data_policy(same_person).is_active is False


@pytest.mark.parametrize("mutate", [
    lambda raw: raw.update(approvals=_approved_raw()["approvals"]),  # Freigaben unter PROPOSED
    lambda raw: raw.update(status="ACTIVE"),
    lambda raw: raw.update(extra=1),
    lambda raw: raw["freshness"].update(final_max_business_days=6),
    lambda raw: raw["freshness"].update(required_components=["upload_time"]),
    lambda raw: raw["reconciliation"].update(per_position_tolerance_minor_units=-1),
    lambda raw: raw["calendar"].update(calendar_id="erfundener-kalender"),
    lambda raw: raw["calendar"].update(timezone="Nowhere/Nothing"),
])
def test_invalid_policy_is_rejected(mutate):
    raw = _raw_policy()
    mutate(raw)
    with pytest.raises(PortfolioDataPolicyError):
        parse_portfolio_data_policy(raw)


def test_missing_policy_file_is_an_error(tmp_path):
    with pytest.raises(PortfolioDataPolicyError):
        load_portfolio_data_policy(tmp_path / "fehlt.json")


# --- Kalender -------------------------------------------------------------

def test_weekend_only_calendar_models_no_holidays():
    cal = calendar_for_id("weekend-only/v1")
    assert isinstance(cal, BankCalendar)
    assert cal.holidays_modelled is False
    # Freitag -> Montag = 1 Bankarbeitstag, Donnerstag -> Montag = 2.
    assert business_days_elapsed(cal, date(2026, 10, 23), date(2026, 10, 26)) == 1
    assert business_days_elapsed(cal, date(2026, 10, 22), date(2026, 10, 26)) == 2
    # Beratung am Samstag mit Freitagsdaten: 0.
    assert business_days_elapsed(cal, date(2026, 10, 23), date(2026, 10, 24)) == 0
    # Feiertage werden nicht erfunden: der 25.12.2026 (Freitag) zaehlt als Bankarbeitstag.
    assert WeekendOnlyBankCalendar().is_business_day(date(2026, 12, 25)) is True


# --- Frische --------------------------------------------------------------

def test_weekend_friday_data_is_final_on_monday(policy):
    result = assess_freshness(_components("2026-10-23"), advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["usability"] == "final"
    assert result["oldest_age_business_days"] == 1
    assert result["calendar"]["holidays_modelled"] is False
    assert result["calendar_notes"]


def test_thursday_data_on_monday_is_draft_only(policy):
    result = assess_freshness(_components("2026-10-22"), advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["usability"] == "draft"
    assert result["stale"] is True


def test_older_than_five_business_days_is_blocked(policy):
    result = assess_freshness(_components("2026-10-16"), advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["oldest_age_business_days"] == 6
    assert result["usability"] == "blocked"


def test_timezone_uses_local_date_of_policy_zone(policy):
    # 2026-10-26 23:30 UTC ist in Zuerich bereits Dienstag, 27.10. (00:30 MEZ).
    advice = datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc)
    result = assess_freshness(_components("2026-10-23"), advice_at=advice, policy=policy)
    assert result["reference_date"] == "2026-10-27"
    assert result["oldest_age_business_days"] == 2
    assert result["usability"] == "draft"


def test_naive_timestamp_is_rejected(policy):
    with pytest.raises(FreshnessInputError):
        assess_freshness(_components(), advice_at="2026-10-26T09:00:00", policy=policy)
    comps = _components(price_as_of={"as_of": "2026-10-23T17:30:00", "source": "feed"})
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["components"]["price_as_of"]["status"] == "invalid_as_of"
    assert result["usability"] == "blocked"


def test_missing_as_of_is_blocked_and_upload_time_is_no_substitute(policy):
    comps = _components(holdings_as_of={"as_of": None, "source": "csv", "uploaded_at": "2026-10-26T08:00:00+01:00"})
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    detail = result["components"]["holdings_as_of"]
    assert detail["status"] == "missing_as_of"
    assert detail["uploaded_at_ignored"] is True
    assert result["usability"] == "blocked"


def test_missing_component_and_missing_source_block(policy):
    comps = _components()
    del comps["corporate_actions_checked_at"]
    comps["fx_as_of"] = {"as_of": "2026-10-23", "source": ""}
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["components"]["corporate_actions_checked_at"]["status"] == "missing_as_of"
    assert result["components"]["fx_as_of"]["status"] == "missing_source"
    assert result["usability"] == "blocked"


def test_not_applicable_component_needs_reason(policy):
    comps = _components("2026-10-23", fx_as_of={"not_applicable": True, "reason": "nur Basiswaehrung"})
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["components"]["fx_as_of"]["status"] == "not_applicable"
    assert result["usability"] == "final"

    comps["fx_as_of"] = {"not_applicable": True}
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["usability"] == "blocked"

    only_na = {name: {"not_applicable": True, "reason": "x"} for name in COMPONENTS}
    result = assess_freshness(only_na, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["usability"] == "blocked"
    assert result["blocking_reasons"] == ["no_dated_component"]


def test_future_as_of_is_blocked(policy):
    result = assess_freshness(_components("2026-10-27"), advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["usability"] == "blocked"


def test_oldest_component_decides(policy):
    comps = _components("2026-10-26", fx_as_of={"as_of": "2026-10-21", "source": "fx-feed"})
    result = assess_freshness(comps, advice_at="2026-10-26T09:00:00+01:00", policy=policy)
    assert result["oldest_component"] == "fx_as_of"
    assert result["oldest_age_business_days"] == 3
    assert result["usability"] == "draft"


def test_trade_after_snapshot_forces_refresh_regardless_of_age(policy):
    comps = _components("2026-10-26T08:00:00+01:00")
    before = assess_freshness(
        comps, advice_at="2026-10-26T12:00:00+01:00", policy=policy,
        events=[{"type": "trade", "occurred_at": "2026-10-26T07:00:00+01:00"}],
    )
    assert before["usability"] == "final"
    after = assess_freshness(
        comps, advice_at="2026-10-26T12:00:00+01:00", policy=policy,
        events=[{"type": "trade", "occurred_at": "2026-10-26T10:00:00+01:00"}],
    )
    assert after["usability"] == "blocked"
    assert {r["component"] for r in after["refresh_required"]} == {"holdings_as_of", "cash_as_of"}


def test_cash_movement_after_cash_date_forces_refresh(policy):
    result = assess_freshness(
        _components("2026-10-23"), advice_at="2026-10-26T09:00:00+01:00", policy=policy,
        events=[{"type": "cash_movement", "occurred_at": "2026-10-24"}],
    )
    assert result["usability"] == "blocked"
    assert result["refresh_required"] == [{"type": "cash_movement", "component": "cash_as_of"}]
    # Tagesstichtag: ein Ereignis am selben Tag ist nicht belegt enthalten -> konservativ danach.
    same_day = assess_freshness(
        _components("2026-10-23"), advice_at="2026-10-26T09:00:00+01:00", policy=policy,
        events=[{"type": "cash_movement", "occurred_at": "2026-10-23T15:00:00+02:00"}],
    )
    assert same_day["usability"] == "blocked"
    earlier = assess_freshness(
        _components("2026-10-23"), advice_at="2026-10-26T09:00:00+01:00", policy=policy,
        events=[{"type": "cash_movement", "occurred_at": "2026-10-22"}],
    )
    assert earlier["usability"] == "final"


def test_unknown_event_type_blocks(policy):
    result = assess_freshness(
        _components("2026-10-23"), advice_at="2026-10-26T09:00:00+01:00", policy=policy,
        events=[{"type": "irgendwas", "occurred_at": "2026-10-24"}],
    )
    assert result["usability"] == "blocked"


# --- Abgleich -------------------------------------------------------------

def _pos(key, *, units=1000, price=10000, ccy="CHF", mv=10000, line="depot", asset_class="equities"):
    return {
        "key": key, "line": line, "asset_class": asset_class, "units_milli": units,
        "price_minor": price, "price_currency": ccy, "market_value_base_minor": mv,
    }


def _side(positions, *, cash=None, fx=None, lines=("depot", "external", "liabilities", "excluded")):
    return {
        "valuation_as_of": "2026-10-23",
        "base_currency": "CHF",
        "fx_rates": fx if fx is not None else {"EUR": "0.9400"},
        "perimeter_lines": list(lines),
        "positions": positions,
        "cash": cash if cash is not None else {"CHF": 500000},
    }


def _exp(category, key, amount=None, exp_type="PENDING_TRADE", **overrides):
    exp = {
        "explanation_id": f"e-{category}-{key}", "type": exp_type, "category": category, "key": key,
        "amount": amount, "source": "custodian-statement", "evidence_ref": "doc-123",
        "created_by": "advisor-1", "approved_by": "reviewer-2", "approved_at": "2026-10-26",
    }
    exp.update(overrides)
    return exp


def test_identical_sides_reconcile(policy):
    side = _side([_pos("CH0001"), _pos("CH0002", mv=25000)])
    result = reconcile_portfolio(side, copy.deepcopy(side), policy=policy)
    assert result["status"] == "reconciled"
    assert result["differences"] == []
    assert result["policy_version"] == policy.version


def test_rounding_boundary_per_position(policy):
    adv = _side([_pos("CH0001")])
    within = reconcile_portfolio(_side([_pos("CH0001", mv=10001)]), adv, policy=policy)
    assert within["status"] == "reconciled"
    beyond = reconcile_portfolio(_side([_pos("CH0001", mv=10002)]), adv, policy=policy)
    assert beyond["status"] == "unexplained_difference"


def test_rounding_boundary_aggregate_uses_absolute_sum(policy):
    keys = [f"P{i:03d}" for i in range(101)]
    adv = _side([_pos(k) for k in keys])
    hundred = _side([_pos(k, mv=10001) if i < 100 else _pos(k) for i, k in enumerate(keys)])
    assert reconcile_portfolio(hundred, adv, policy=policy)["status"] == "reconciled"
    hundred_one = _side([_pos(k, mv=10001) for k in keys])
    assert reconcile_portfolio(hundred_one, adv, policy=policy)["status"] == "unexplained_difference"
    # +1/-1 heben sich nicht auf: 60 x (+1) und 60 x (-1) = 120 > 100.
    keys120 = [f"Q{i:03d}" for i in range(120)]
    adv120 = _side([_pos(k) for k in keys120])
    mixed = _side([_pos(k, mv=10001 if i % 2 else 9999) for i, k in enumerate(keys120)])
    result = reconcile_portfolio(mixed, adv120, policy=policy)
    assert result["status"] == "unexplained_difference"
    assert result["aggregate_by_line"][0]["abs_residual"] == 120


def test_quantity_difference_needs_typed_approved_explanation(policy):
    adv = _side([_pos("CH0001")])
    depot = _side([_pos("CH0001", units=1500, mv=15000)])
    assert reconcile_portfolio(depot, adv, policy=policy)["status"] == "unexplained_difference"
    explained = reconcile_portfolio(
        depot, adv, policy=policy,
        explanations=[_exp("quantity", "CH0001", 500), _exp("market_value", "CH0001", 5000)],
    )
    assert explained["status"] == "reconciled"
    partially = reconcile_portfolio(
        depot, adv, policy=policy,
        explanations=[_exp("quantity", "CH0001", 499), _exp("market_value", "CH0001", 5000)],
    )
    assert partially["status"] == "unexplained_difference"


@pytest.mark.parametrize("override,reason", [
    ({"approved_by": ""}, "not_approved"),
    ({"approved_by": "advisor-1"}, "approver_equals_creator"),
    ({"evidence_ref": ""}, "missing_evidence_ref"),
    ({"type": "MANUAL"}, "unknown_type"),
    ({"type": "FX_TIMING"}, "type_not_allowed_for_category"),
])
def test_invalid_explanations_are_rejected(policy, override, reason):
    adv = _side([_pos("CH0001")])
    depot = _side([_pos("CH0001", units=1500)])
    result = reconcile_portfolio(depot, adv, policy=policy, explanations=[_exp("quantity", "CH0001", 500, **override)])
    assert result["status"] == "unexplained_difference"
    assert result["rejected_explanations"][0]["reason"] == reason


def test_cash_movement_difference_is_exact_and_explainable(policy):
    adv = _side([_pos("CH0001")], cash={"CHF": 500000})
    depot = _side([_pos("CH0001")], cash={"CHF": 500001})
    assert reconcile_portfolio(depot, adv, policy=policy)["status"] == "unexplained_difference"
    explained = reconcile_portfolio(
        depot, adv, policy=policy,
        explanations=[_exp("cash", "CHF", 1, exp_type="PENDING_CASH_MOVEMENT")],
    )
    assert explained["status"] == "reconciled"


def test_fx_difference_is_a_cause_not_rounding(policy):
    adv = _side([_pos("CH0001")], fx={"EUR": "0.9400"})
    same = reconcile_portfolio(_side([_pos("CH0001")], fx={"EUR": "0.94"}), adv, policy=policy)
    assert same["status"] == "reconciled"
    depot = _side([_pos("CH0001")], fx={"EUR": "0.9401"})
    assert reconcile_portfolio(depot, adv, policy=policy)["status"] == "unexplained_difference"
    explained = reconcile_portfolio(depot, adv, policy=policy, explanations=[_exp("fx", "EUR", exp_type="FX_TIMING")])
    assert explained["status"] == "reconciled"


def test_price_difference_needs_explanation(policy):
    adv = _side([_pos("CH0001")])
    depot = _side([_pos("CH0001", price=10001)])
    assert reconcile_portfolio(depot, adv, policy=policy)["status"] == "unexplained_difference"


@pytest.mark.parametrize("field,value", [
    ("asset_class", None),
    ("market_value_base_minor", None),
    ("price_minor", None),
    ("units_milli", None),
])
def test_unknown_or_unvalued_position_always_blocks(policy, field, value):
    unknown = _pos("XX0001")
    unknown[field] = value
    side = _side([_pos("CH0001"), unknown])
    result = reconcile_portfolio(
        side, copy.deepcopy(side), policy=policy,
        explanations=[_exp("perimeter", "XX0001", exp_type="PERIMETER_DECISION")],
    )
    assert result["status"] == "blocked"
    assert result["unknown_positions"][0]["key"] == "XX0001"
    assert result["rejected_explanations"][0]["reason"] == "unknown_position_not_overridable"


def test_perimeter_change_of_position_and_definition(policy):
    adv = _side([_pos("CH0001"), _pos("CH0002")])
    moved = _side([_pos("CH0001"), _pos("CH0002", line="excluded")])
    result = reconcile_portfolio(moved, adv, policy=policy)
    assert result["status"] == "unexplained_difference"
    assert result["differences"][0]["category"] == "perimeter"

    missing = _side([_pos("CH0001")])
    assert reconcile_portfolio(missing, adv, policy=policy)["status"] == "unexplained_difference"

    redefined = _side([_pos("CH0001"), _pos("CH0002")], lines=("depot", "external"))
    result = reconcile_portfolio(redefined, adv, policy=policy)
    assert result["status"] == "blocked"
    assert "perimeter_definition_changed" in result["preconditions_failed"]


@pytest.mark.parametrize("field,value,failed", [
    ("base_currency", "EUR", "base_currency_mismatch"),
    ("valuation_as_of", "2026-10-22", "valuation_as_of_mismatch"),
])
def test_preconditions_block(policy, field, value, failed):
    adv = _side([_pos("CH0001")])
    depot = copy.deepcopy(adv)
    depot[field] = value
    result = reconcile_portfolio(depot, adv, policy=policy)
    assert result["status"] == "blocked"
    assert failed in result["preconditions_failed"]


def test_result_hash_is_deterministic(policy):
    side = _side([_pos("CH0002"), _pos("CH0001")])
    reordered = _side([_pos("CH0001"), _pos("CH0002")])
    assert (
        reconcile_portfolio(side, side, policy=policy)["result_hash"]
        == reconcile_portfolio(reordered, reordered, policy=policy)["result_hash"]
    )


# --- Aenderung nach PDF ---------------------------------------------------

def test_change_after_pdf_invalidates_binding(policy, active_policy):
    binding = finalization_binding(
        snapshot_hash="a" * 64, reconciliation_hash="b" * 64, policy=policy, advice_at="2026-10-26T09:00:00+01:00",
    )
    ok = verify_finalization_binding(binding, snapshot_hash="a" * 64, reconciliation_hash="b" * 64, policy=policy)
    assert ok == {"valid": True, "changed": []}

    snap = verify_finalization_binding(binding, snapshot_hash="c" * 64, reconciliation_hash="b" * 64, policy=policy)
    assert snap["valid"] is False and snap["changed"] == ["snapshot_hash"]

    recon = verify_finalization_binding(binding, snapshot_hash="a" * 64, reconciliation_hash="d" * 64, policy=policy)
    assert recon["changed"] == ["reconciliation_hash"]

    new_policy = verify_finalization_binding(
        binding, snapshot_hash="a" * 64, reconciliation_hash="b" * 64, policy=active_policy,
    )
    assert "policy_hash" in new_policy["changed"]

    tampered = dict(binding, advice_at="2026-10-27T09:00:00+01:00")
    assert verify_finalization_binding(
        tampered, snapshot_hash="a" * 64, reconciliation_hash="b" * 64, policy=policy,
    )["changed"] == ["binding_digest"]


# --- Gate -----------------------------------------------------------------

def _fresh(usability):
    return {"usability": usability, "calendar_notes": []}


def test_proposed_policy_only_warns(policy):
    gate = evaluate_portfolio_data_gate(
        policy, action="pdf", freshness=_fresh("blocked"), reconciliation={"status": "blocked"},
    )
    assert gate["enforced"] is False
    assert gate["would_block"] is True
    assert gate["blocked"] is False
    assert gate["policy"]["status"] == "PROPOSED"
    assert any("PROPOSED" in w for w in gate["warnings"])


@pytest.mark.parametrize("action", ["finalize", "pdf", "signature", "handoff"])
def test_active_policy_blocks_final_actions_on_stale_data(active_policy, action):
    gate = evaluate_portfolio_data_gate(
        active_policy, action=action, freshness=_fresh("draft"), reconciliation={"status": "reconciled"},
    )
    assert gate["blocked"] is True
    assert gate["reasons"] == ["freshness_draft_only"]


def test_active_policy_allows_draft_on_stale_but_not_blocked_data(active_policy):
    draft = evaluate_portfolio_data_gate(active_policy, action="draft", freshness=_fresh("draft"), reconciliation=None)
    assert draft["blocked"] is False
    assert any("veraltet" in w for w in draft["warnings"])
    too_old = evaluate_portfolio_data_gate(active_policy, action="draft", freshness=_fresh("blocked"), reconciliation=None)
    assert too_old["blocked"] is True


def test_active_policy_blocks_unexplained_reconciliation(active_policy):
    gate = evaluate_portfolio_data_gate(
        active_policy, action="signature", freshness=_fresh("final"),
        reconciliation={"status": "unexplained_difference"},
    )
    assert gate["blocked"] is True
    assert gate["reasons"] == ["reconciliation_unexplained_difference"]
    clean = evaluate_portfolio_data_gate(
        active_policy, action="signature", freshness=_fresh("final"), reconciliation={"status": "reconciled"},
    )
    assert clean["blocked"] is False and clean["would_block"] is False


def test_unloadable_policy_warns_without_blocking():
    gate = evaluate_portfolio_data_gate(
        None, action="handoff", freshness=None, reconciliation=None, policy_error="Datei fehlt",
    )
    assert gate["blocked"] is False
    assert gate["would_block"] is True
    assert "nicht ladbar" in gate["warnings"][0]
