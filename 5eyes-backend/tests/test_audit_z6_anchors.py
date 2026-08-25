"""Z6 - C8: Audit-Anchors + zentrale Drift-Warnings.

Der TargetAllocation-Datensatz speichert ab jetzt zusaetzlich:
  - capital_market_assumptions_id (war F3 schon)
  - preferences_json (Snapshot der Mandatspraeferenzen)
  - input_snapshot_hash (Hash der WealthPositions+Cashflows+Goals)
  - advisory_wealth_at_generation_rappen
  - total_wealth_at_generation_rappen
  - reserve_needed_at_generation_rappen
  - external_reserve_at_generation_rappen

build_target_payload_from_allocation blockiert Input-Snapshot-Drift, bevor
alte Targets mit aktuellen Pfaden kombiniert werden koennen. Nicht-hybride
Drift-Quellen (Assessment, CMA, Preferences, Reserve, Legacy-Anker) bleiben
zentral in _strategy_drift_warnings() als reasoning-Hinweise sichtbar.
"""
from __future__ import annotations
import copy
import sys
import datetime
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.allocation import TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    _compute_input_snapshot_hash,
    _strategy_drift_warnings,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z6.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(session_factory):
    advisor_id = "user-z6-1"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-z6-1", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_000, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000, alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        risk_fields = derive_current_risk_fields(
            q_income_points=2,
            q_obligations_points=3,
            q_savings_points=2,
            q_wealth_points=2,
            investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3,
            q_risk_preference_points=3,
            q_risk_behavior_points=3,
        )
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            **risk_fields,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def test_c8_input_snapshot_hash_deterministic():
    """Hash ist deterministisch ueber gleichen Input."""
    pos = type("P", (), dict(id="p1", current_value_rappen=100, assignment="x",
                              position_type="Depot",
                              alloc_equities_bps=0, alloc_bonds_bps=0,
                              alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                              alloc_alternatives_bps=0, property_usage=""))
    h1 = _compute_input_snapshot_hash(
        advisory_positions=[pos], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    h2 = _compute_input_snapshot_hash(
        advisory_positions=[pos], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    assert h1 == h2 and len(h1) == 64


def test_c8_input_snapshot_hash_changes_on_value_change():
    """Aendert sich Wealth-Wert, aendert sich der Hash."""
    pos1 = type("P", (), dict(id="p1", current_value_rappen=100, assignment="x",
                                position_type="Depot",
                                alloc_equities_bps=0, alloc_bonds_bps=0,
                                alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                                alloc_alternatives_bps=0, property_usage=""))
    pos2 = type("P", (), dict(id="p1", current_value_rappen=200, assignment="x",
                                position_type="Depot",
                                alloc_equities_bps=0, alloc_bonds_bps=0,
                                alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                                alloc_alternatives_bps=0, property_usage=""))
    h1 = _compute_input_snapshot_hash(
        advisory_positions=[pos1], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    h2 = _compute_input_snapshot_hash(
        advisory_positions=[pos2], cashflows=[], goals=[],
        advisory_wealth_rappen=200, total_wealth_rappen=200,
    )
    assert h1 != h2


def test_c8_v2_hash_binds_external_property_and_mortgage_projection_inputs():
    """Total-path assumptions must not drift silently under the same anchor."""
    from types import SimpleNamespace

    property_position = SimpleNamespace(
        id="house",
        current_value_rappen=1_000_000,
        assignment="Anderes Vermögen",
        position_type="Immobilien",
        currency="CHF",
        asset_expected_return_bps=100,
        property_rental_income_rappen=20_000,
        property_rental_inflation_linked=0,
    )
    changed_property = SimpleNamespace(
        **{
            **vars(property_position),
            "asset_expected_return_bps": 900,
        }
    )
    mortgage = SimpleNamespace(
        id="mortgage",
        current_value_rappen=500_000,
        assignment="Verbindlichkeit",
        position_type="Hypothek",
        currency="CHF",
        mortgage_amortization_rappen=10_000,
        mortgage_amortization_type="Direkt",
    )
    changed_mortgage = SimpleNamespace(
        **{
            **vars(mortgage),
            "mortgage_amortization_type": "Indirekt (Säule 3a)",
        }
    )

    def _hash(positions):
        return _compute_input_snapshot_hash(
            advisory_positions=[],
            all_positions=positions,
            cashflows=[],
            goals=[],
            advisory_wealth_rappen=0,
            total_wealth_rappen=500_000,
        )

    base = _hash([property_position, mortgage])
    assert base != _hash([changed_property, mortgage])
    assert base != _hash([property_position, changed_mortgage])


def _z6_v3_hash_fixture():
    """Minimaler, aber vollstaendiger Projektionskontext fuer Hash-Vertraege."""
    position = SimpleNamespace(
        id="depot-v3",
        current_value_rappen=2_000_000,
        assignment="Beratungsvermoegen",
        position_type="Depot",
        currency="USD",
        alloc_equities_bps=6000,
        alloc_bonds_bps=2500,
        alloc_real_estate_bps=500,
        alloc_liquidity_bps=500,
        alloc_alternatives_bps=500,
        property_usage="",
    )
    cashflow = SimpleNamespace(
        id="cf-v3",
        cashflow_type="Einnahme",
        amount_rappen=120_000,
        frequency="jaehrlich",
        nature="wiederkehrend",
        valid_from="2026-01-01",
        valid_until=None,
        currency="USD",
        is_inflation_linked=1,
    )
    goal = SimpleNamespace(
        id="goal-v3",
        mandate_id="mandate-v3",
        client_id="client-v3",
        goal_family="Vermoegen",
        goal_type="Zielvermoegen",
        label="Kapitalziel",
        target_amount_rappen=0,
        target_wealth_rappen=3_000_000,
        target_return_bps=0,
        start_date="2026-01-01",
        target_date="2029-12-31",
        horizon_years=3,
        is_ongoing=0,
        frequency="einmalig",
        hardness="Primaer",
        rank=1,
        weight_bps=7500,
        goal_scope="Gesamtvermoegen",
        value_mode="real",
        probability_pct=100,
        success_probability_min_x100=8000,
        pension_pillar=None,
        linked_position_id=None,
        is_active=1,
        is_inflation_linked=1,
        duration_years=0,
    )
    inflow = SimpleNamespace(
        id="inflow-v3",
        mandate_id="mandate-v3",
        label="Erbschaft",
        source_type="Erbschaft",
        amount_rappen=400_000,
        expected_year=2028,
        is_recurring=0,
        frequency="einmalig",
        duration_years=None,
        value_mode="real",
    )
    projection_context = {
        "goal_inflation_series_bps": [100, 110, 120, 130],
        "cashflow_inflation_series_bps": [90, 100, 115, 125],
        "fx_signature": [
            ["CHF", 100_000_000],
            ["USD", 88_000_000],
        ],
        "external_foundation_projection": {
            "property_series_rappen": [1_000_000, 1_020_000, 1_040_400, 1_061_208],
            "liability_series_rappen": [500_000, 480_000, 460_000, 440_000],
            "pledged_asset_series_rappen": [0, 0, 0, 0],
        },
        "optimizer_cashflow_projection_series_rappen": [0, 100_000, 105_000, 110_000],
        "mandate_projection_inputs": {
            "tax_jurisdiction": "CH-ZH",
            "tax_overrides_json": '{"wealth_tax_rate_bps": 12}',
            "tax_estimate_in_cashflow_enabled": 1,
            "use_mortality_simulation": 1,
            "client_birth_year": 1980,
            "client_sex": "F",
            "life_expectancy_year": 2075,
            "retirement_year": 2045,
        },
    }
    return position, cashflow, goal, inflow, projection_context


def _z6_v3_hash(*, projection_context, inflow):
    position, cashflow, goal, _, _ = _z6_v3_hash_fixture()
    return _compute_input_snapshot_hash(
        advisory_positions=[position],
        all_positions=[position],
        cashflows=[cashflow],
        goals=[goal],
        wealth_inflows=[inflow],
        projection_context=projection_context,
        snapshot_version="strategy_inputs_v3_projection_context",
        advisory_wealth_rappen=2_000_000,
        total_wealth_rappen=2_500_000,
    )


def _z6_v4_hash(*, goal):
    position, cashflow, _, inflow, projection_context = _z6_v3_hash_fixture()
    return _compute_input_snapshot_hash(
        advisory_positions=[position],
        all_positions=[position],
        cashflows=[cashflow],
        goals=[goal],
        wealth_inflows=[inflow],
        projection_context=projection_context,
        advisory_wealth_rappen=2_000_000,
        total_wealth_rappen=2_500_000,
    )


def test_c8_v3_projection_hash_stays_byte_exact_for_historical_allocations():
    """The v4 rollout may not invalidate an unchanged persisted v3 anchor."""
    _, _, _, inflow, projection_context = _z6_v3_hash_fixture()

    assert _z6_v3_hash(
        projection_context=projection_context,
        inflow=inflow,
    ) == "39123f7e7b51f7ff75dc0051f1249e381bf0afe7fba64feb69db8f6f4102d499"


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("goal_family", "Cashflow"),
        ("goal_type", "Pensionsausgabe"),
        ("label", "Neues Kapitalziel"),
        ("rank", 2),
        ("weight_bps", 2500),
        ("goal_scope", "Beratungsvermoegen"),
        ("value_mode", "nominal"),
        ("target_amount_rappen", 1),
        ("target_wealth_rappen", 3_000_001),
        ("target_return_bps", 1),
        ("success_probability_min_x100", 8100),
        ("start_date", "2027-01-01"),
        ("horizon_years", 4),
        ("target_date", "2030-12-31"),
        ("is_ongoing", 1),
        ("frequency", "jaehrlich"),
        ("hardness", "Hart"),
        ("probability_pct", 80),
        ("pension_pillar", "AHV"),
        ("linked_position_id", "pillar-position"),
    ],
)
def test_c8_v4_hash_binds_every_canonical_goal_input(field, changed_value):
    """Every goal input consumed by objective/reporting owns the v4 anchor."""
    _, _, goal, _, _ = _z6_v3_hash_fixture()
    changed_goal = SimpleNamespace(**{**vars(goal), field: changed_value})

    assert _z6_v4_hash(goal=goal) != _z6_v4_hash(goal=changed_goal)


@pytest.mark.parametrize(
    ("path", "changed_value"),
    [
        (("goal_inflation_series_bps", 2), 999),
        (("cashflow_inflation_series_bps", 1), 777),
        (("fx_signature", 1, 1), 91_000_000),
        (
            ("external_foundation_projection", "property_series_rappen", 2),
            1_055_000,
        ),
        (("optimizer_cashflow_projection_series_rappen", 2), 205_000),
        (
            ("mandate_projection_inputs", "tax_jurisdiction"),
            "DE-BY",
        ),
        (
            ("mandate_projection_inputs", "client_birth_year"),
            1970,
        ),
        (
            ("mandate_projection_inputs", "life_expectancy_year"),
            2085,
        ),
    ],
    ids=[
        "goal-inflation",
        "cashflow-inflation",
        "fx-signature",
        "external-foundation",
        "optimizer-cashflow",
        "tax-mandate-input",
        "stochastic-mortality-mandate-input",
        "deterministic-mortality-mandate-input",
    ],
)
def test_c8_v3_hash_binds_effective_projection_context(path, changed_value):
    """Jeder effektiv verwendete Projektionsinput muss Drift ausloesen."""
    _, _, _, inflow, projection_context = _z6_v3_hash_fixture()
    base = _z6_v3_hash(
        projection_context=projection_context,
        inflow=inflow,
    )
    changed_context = copy.deepcopy(projection_context)
    target = changed_context
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = changed_value

    assert base != _z6_v3_hash(
        projection_context=changed_context,
        inflow=inflow,
    )


def test_c8_v3_hash_binds_wealth_inflow():
    """Ein geaenderter Vermoegenszufluss darf denselben Hash nicht behalten."""
    _, _, _, inflow, projection_context = _z6_v3_hash_fixture()
    changed_inflow = SimpleNamespace(
        **{
            **vars(inflow),
            "amount_rappen": inflow.amount_rappen + 1,
        }
    )

    assert _z6_v3_hash(
        projection_context=projection_context,
        inflow=inflow,
    ) != _z6_v3_hash(
        projection_context=projection_context,
        inflow=changed_inflow,
    )


def test_c8_v2_hash_contract_stays_exact_without_projection_context():
    """Ohne Projektionskontext bleibt der bestehende v2-Hash bytegenau."""
    position, _, _, inflow, _ = _z6_v3_hash_fixture()
    expected_payload = {
        "advisory_wealth_rappen": 2_000_000,
        "total_wealth_rappen": 2_500_000,
        "positions": [
            (
                "depot-v3",
                2_000_000,
                "Beratungsvermoegen",
                "Depot",
                6000,
                2500,
                500,
                500,
                500,
                "",
                "USD",
                "",
                0,
                0,
                0,
                0,
                0,
                0,
                "",
                "",
                "",
                "",
                0,
            )
        ],
        "cashflows": [],
        "goals": [],
        "snapshot_version": "strategy_inputs_v2_foundation",
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    without_new_kwargs = _compute_input_snapshot_hash(
        advisory_positions=[position],
        all_positions=[position],
        cashflows=[],
        goals=[],
        advisory_wealth_rappen=2_000_000,
        total_wealth_rappen=2_500_000,
    )
    with_inflows_but_no_context = _compute_input_snapshot_hash(
        advisory_positions=[position],
        all_positions=[position],
        cashflows=[],
        goals=[],
        wealth_inflows=[inflow],
        advisory_wealth_rappen=2_000_000,
        total_wealth_rappen=2_500_000,
    )

    assert without_new_kwargs == expected
    assert with_inflows_but_no_context == expected


def test_c8_generate_persists_all_anchors(session_factory):
    """generate_target_allocation muss alle neuen Anker setzen."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    ta = result["target_allocation"]
    assert ta.preferences_json, "preferences_json muss persistiert sein"
    assert json.loads(ta.preferences_json), "preferences_json muss valid JSON sein"
    assert ta.input_snapshot_hash and len(ta.input_snapshot_hash) == 64
    assert ta.advisory_wealth_at_generation_rappen == 100_000_000
    assert ta.total_wealth_at_generation_rappen >= 0
    assert ta.reserve_needed_at_generation_rappen is not None
    assert ta.external_reserve_at_generation_rappen is not None


def test_c8_drift_warnings_legacy_allocation_has_legacy_hint():
    """Legacy allocation (alle Anker NULL) bekommt 'incomplete anchors'."""
    legacy_alloc = TargetAllocation(
        id="legacy-1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id=None,
        capital_market_assumptions_id=None,
        input_snapshot_hash=None,
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(legacy_alloc, assessment=fake_assess, cma=fake_cma)
    assert any("Audit-Anker" in m for m in msgs), msgs


def test_c8_drift_warnings_input_hash_change_warns():
    """Allocation hat anderen input_snapshot_hash als current -> Warning."""
    alloc = TargetAllocation(
        id="a1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id="a-current",
        capital_market_assumptions_id="c-current",
        input_snapshot_hash="abc123" * 10 + "0000",  # 64 chars
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(
        alloc, assessment=fake_assess, cma=fake_cma,
        current_input_snapshot_hash="def" * 21 + "x",  # different
    )
    assert any("Vermoegen, Cashflows oder Ziele" in m for m in msgs), msgs


def test_c8_drift_warnings_preferences_change_warns():
    """preferences_json mismatch -> Warning."""
    alloc = TargetAllocation(
        id="a1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id="a-current",
        capital_market_assumptions_id="c-current",
        input_snapshot_hash="x" * 64,
        preferences_json='{"old": "prefs"}',
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(
        alloc, assessment=fake_assess, cma=fake_cma,
        current_input_snapshot_hash="x" * 64,
        current_preferences_json='{"new": "prefs"}',
    )
    assert any("Mandatspraeferenzen" in m for m in msgs), msgs


def test_c8_payload_fails_closed_after_input_change(session_factory):
    """Alte Targets duerfen nie mit neu berechneten Pfaden kombiniert werden."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    # Wealth-Position aendern
    with session_factory() as s:
        pos = s.query(WealthPosition).filter(WealthPosition.id == "pos-z6-1").first()
        pos.current_value_rappen = 150_000_000  # von 100M auf 150M
        pos.updated_at = _now()
        s.commit()
    # build_payload aufrufen
    with session_factory() as s:
        from services.portfolio_engine import ensure_runtime_reference_data
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        assessment = s.query(RiskAssessment).filter(RiskAssessment.id == aid).first()
        policy, cma = ensure_runtime_reference_data(s, advisor_id)
        with pytest.raises(ValueError, match="veraltet|neu berechnen"):
            build_target_payload_from_allocation(
                db=s, mandate=mandate, allocation=allocation,
                policy=policy, cma=cma, assessment=assessment, preferences=None,
            )
