"""Fail-closed contracts for the complete AllocationPreferences vocabulary.

The allocation preferences object crosses three trust boundaries: FastAPI,
direct Python callers of the portfolio engine, and the JSON snapshot persisted
on a TargetAllocation.  A misspelled key at any of those boundaries must not
be discarded or survive as inert audit metadata.

The allowlist below is deliberately derived from every current consumer in:

* ``portfolio_engine_house_matrix`` / ``portfolio_engine_reserve``;
* ``portfolio_engine_payload`` / ``portfolio_engine_mc_simulation``;
* ``portfolio_engine`` and the advisory/PDF reporting paths.

It therefore also documents reporting-only compatibility fields (for example
``geo.chFocus``) and runtime aliases (for example ``crisisStrength`` and
``cornishFisher``), rather than narrowing the contract to the current UI.
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from database import get_db
from main import app
from models.allocation import TargetAllocation
from models.mandates import Mandate
from routers import allocation as allocation_router
from schemas.allocation import AllocationPreferencesPayload
from services.auth import require_advisor
import services.optimizer.solver as solver_module
import services.portfolio_engine as pe
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _reload_payload,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - shared isolated-database fixture
)
from tests.risk_fixture_helpers import noop_lifespan


TOP_LEVEL_KEYS = frozenset(
    {
        "policy",
        "tilts",
        "product",
        "limits",
        "geo",
        "assetClasses",
        "bands",
        "simulation",
    }
)

NESTED_KEYS = {
    "policy": frozenset({"esg", "universe", "homeBias", "hedging"}),
    "tilts": frozenset(
        {"fossil", "defense", "tobacco", "alcohol", "gaming", "nuclear"}
    ),
    "product": frozenset(
        {"noDerivatives", "noLeverage", "noStructured", "listedOnly", "fundsOnly"}
    ),
    "limits": frozenset(
        {"singlePosition", "singleIssuer", "minReserve", "maxIlliquid"}
    ),
    "geo": frozenset(
        {"chFocus", "noEm", "hedgingRequired", "chfOnly", "noUsd"}
    ),
    "assetClasses": frozenset(
        {
            "equitiesGeo",
            "equitiesLargeCap",
            "equitiesSmid",
            "bondsDuration",
            "bondsInvestmentGrade",
            "bondsHighYield",
            "bondsEmerging",
            "realestateMarket",
            "realestateFunds",
            "realestateDirect",
            "altsGold",
            "altsLiquidAlts",
            "altsHedge",
            "altsPe",
            "altsCrypto",
            "liquidityInstrument",
            "liquidityReserveTarget",
        }
    ),
    "simulation": frozenset(
        {
            "horizonYears",
            "stressMultiplier",
            "rebalanceMode",
            "monteCarloRuns",
            "transactionCostBps",
            "crisisMode",
            "crisisStrength",
            "tailRisk",
            "cornishFisher",
        }
    ),
}

BAND_BUCKET_KEYS = frozenset(
    {
        "equities",
        "bonds",
        "real_estate",
        "alternatives",
        "liquidity",
        "Aktien",
        "Obligationen",
        "Immobilien",
        "Alternative",
        "Liquiditaet",
        "Liquidität",
    }
)
BAND_OVERRIDE_KEYS = frozenset({"min_bps", "target_bps", "max_bps"})


COMPLETE_VALID_PREFERENCES = {
    "policy": {
        "esg": "best_in_class",
        "universe": "funds_only",
        "homeBias": "ch_focus",
        "hedging": "hedged",
    },
    "tilts": {
        "fossil": "exclude",
        "defense": "underweight",
        "tobacco": "neutral",
        "alcohol": "overweight",
        "gaming": "neutral",
        "nuclear": "neutral",
    },
    "product": {
        "noDerivatives": True,
        "noLeverage": False,
        "noStructured": True,
        "listedOnly": False,
        "fundsOnly": True,
    },
    "limits": {
        "singlePosition": "10%",
        "singleIssuer": "20",
        "minReserve": "CHF 50'000",
        "maxIlliquid": "7.5",
    },
    "geo": {
        "chFocus": True,
        "noEm": False,
        "hedgingRequired": True,
        "chfOnly": False,
        "noUsd": False,
    },
    "assetClasses": {
        "equitiesGeo": "Schweiz Fokus",
        "equitiesLargeCap": True,
        "equitiesSmid": False,
        "bondsDuration": "Langfristig",
        "bondsInvestmentGrade": True,
        "bondsHighYield": False,
        "bondsEmerging": False,
        "realestateMarket": "Schweiz",
        "realestateFunds": True,
        "realestateDirect": False,
        "altsGold": True,
        "altsLiquidAlts": False,
        "altsHedge": False,
        "altsPe": True,
        "altsCrypto": False,
        "liquidityInstrument": "Geldmarktfonds",
        "liquidityReserveTarget": "50'000",
    },
    "bands": {
        "equities": {"min_bps": 3000, "target_bps": 4500, "max_bps": 6000},
        "bonds": {"min_bps": 1500, "target_bps": 3000, "max_bps": 4500},
        "real_estate": {"min_bps": 0, "target_bps": 1000, "max_bps": 2000},
        "alternatives": {"min_bps": 0, "target_bps": 500, "max_bps": 1000},
        "liquidity": {"min_bps": 500, "target_bps": 1000, "max_bps": 2500},
    },
    "simulation": {
        "horizonYears": "25",
        "stressMultiplier": "1.5",
        "rebalanceMode": "bands",
        "monteCarloRuns": "750",
        "transactionCostBps": 10,
        # Both names are consumed for backwards compatibility; false on the
        # primary spelling makes the alias the effective value without a
        # contradictory configuration.
        "crisisMode": False,
        "crisisStrength": 0.5,
        "tailRisk": False,
        "cornishFisher": True,
    },
}


UNKNOWN_KEY_CASES = (
    pytest.param({"mysteryTopLevel": True}, "mysteryTopLevel", id="top-level"),
    pytest.param({"policy": {"mysteryPolicy": "none"}}, "mysteryPolicy", id="policy"),
    pytest.param({"tilts": {"mysteryTilt": "neutral"}}, "mysteryTilt", id="tilts"),
    pytest.param({"product": {"mysteryProduct": False}}, "mysteryProduct", id="product"),
    pytest.param({"limits": {"mysteryLimit": ""}}, "mysteryLimit", id="limits"),
    pytest.param({"geo": {"mysteryGeo": False}}, "mysteryGeo", id="geo"),
    pytest.param(
        {"assetClasses": {"mysteryAssetClass": False}},
        "mysteryAssetClass",
        id="asset-classes",
    ),
    pytest.param(
        {"simulation": {"mysterySimulation": "1"}},
        "mysterySimulation",
        id="simulation",
    ),
    pytest.param(
        {"bands": {"mysteryBucket": {"min_bps": 0}}},
        "mysteryBucket",
        id="band-bucket",
    ),
    pytest.param(
        {"bands": {"equities": {"mysteryBandField": 100}}},
        "mysteryBandField",
        id="band-override-field",
    ),
)


@pytest.fixture(autouse=True)
def _fast_preferences_contract_layers(monkeypatch):
    """Keep integration gates focused on validation rather than a second MC."""

    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def _deep_merge(base: dict, fragment: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _rehash_allocation_context(allocation: TargetAllocation) -> None:
    """Rehash an intentionally mutated snapshot to isolate vocabulary checks.

    Without this, sensitivity correctly stops at the generic tamper hash.  The
    regression needs the stronger contract: even an internally consistent
    snapshot may not contain an unknown preference key.
    """

    targets = {
        bucket: int(getattr(allocation, f"target_{bucket}_bps"))
        for bucket in pe.BUCKET_FIELDS
    }
    context = {
        "engine_version": json.loads(allocation.effective_constraints_json)[
            "engine_version"
        ],
        "policy_id": str(allocation.policy_id),
        "cma_id": str(allocation.capital_market_assumptions_id),
        "assessment_id": str(allocation.based_on_assessment_id),
        "input_snapshot_hash": str(allocation.input_snapshot_hash),
        "preferences_json": allocation.preferences_json,
        "targets_bps": targets,
        "sub_allocations": json.loads(allocation.sub_allocations_json),
        "effective_constraints": json.loads(allocation.effective_constraints_json),
        "optimization_seed": allocation.optimization_seed,
    }
    allocation.allocation_context_hash = hashlib.sha256(
        json.dumps(
            context,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _persist_unknown_preference(
    session,
    allocation_id: str,
    fragment: dict,
) -> TargetAllocation:
    allocation = session.query(TargetAllocation).filter(
        TargetAllocation.id == allocation_id
    ).one()
    current = json.loads(allocation.preferences_json)
    allocation.preferences_json = json.dumps(
        _deep_merge(current, fragment),
        sort_keys=True,
        default=str,
    )
    _rehash_allocation_context(allocation)
    session.commit()
    session.refresh(allocation)
    return allocation


def test_complete_optimizer_and_reporting_allowlist_remains_accepted():
    parsed = AllocationPreferencesPayload.model_validate(
        copy.deepcopy(COMPLETE_VALID_PREFERENCES)
    ).model_dump()

    assert set(parsed) == TOP_LEVEL_KEYS
    for section, keys in NESTED_KEYS.items():
        assert set(parsed[section]) == keys
    assert set(parsed["bands"]) == {
        "equities",
        "bonds",
        "real_estate",
        "alternatives",
        "liquidity",
    }
    for override in parsed["bands"].values():
        assert set(override) == BAND_OVERRIDE_KEYS


@pytest.mark.parametrize("bucket_alias", sorted(BAND_BUCKET_KEYS))
def test_all_existing_band_bucket_aliases_remain_accepted(bucket_alias):
    parsed = AllocationPreferencesPayload.model_validate(
        {"bands": {bucket_alias: {"min_bps": 0, "target_bps": 500, "max_bps": 1000}}}
    ).model_dump()
    assert bucket_alias in parsed["bands"]


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        *(('policy', 'esg', value) for value in (
            'none', 'best_in_class', 'impact', 'net_zero',
            'esg_integration', 'negative_screening',
        )),
        *(('policy', 'universe', value) for value in (
            'funds_only', 'listed_only', 'standard', 'extended',
        )),
        *(('policy', 'homeBias', value) for value in (
            'ch_focus', 'none', 'europe_focus', 'global',
        )),
        *(('policy', 'hedging', value) for value in (
            'none', 'hedged', 'chf_only', 'risk_budget',
        )),
        *(('assetClasses', 'equitiesGeo', value) for value in (
            'Schweiz Fokus', 'Global', 'Europa',
            'Schwellenländer', 'Schwellenlaender',
        )),
        *(('assetClasses', 'bondsDuration', value) for value in (
            'Langfristig', 'Kurzfristig', 'Gemischt',
        )),
        *(('assetClasses', 'realestateMarket', value) for value in (
            'Schweiz', 'Ausland', 'Gemischt',
        )),
        *(('assetClasses', 'liquidityInstrument', value) for value in (
            'Geldmarktfonds', 'Kontoguthaben', 'Festgeld',
        )),
        *(('simulation', 'rebalanceMode', value) for value in (
            'band', 'bands', 'calendar', 'jaehrlich', 'none', 'off', 'aus',
        )),
        ('simulation', 'horizonYears', 25),
        ('simulation', 'horizonYears', '25'),
        ('simulation', 'stressMultiplier', 1.5),
        ('simulation', 'stressMultiplier', '1.5'),
        ('simulation', 'monteCarloRuns', 750),
        ('simulation', 'monteCarloRuns', '750'),
        ('simulation', 'transactionCostBps', 10),
        ('simulation', 'transactionCostBps', '10'),
        ('simulation', 'crisisMode', True),
        ('simulation', 'crisisStrength', 0.5),
        ('simulation', 'tailRisk', True),
        ('simulation', 'cornishFisher', 'on'),
        ('limits', 'singlePosition', ''),
        ('limits', 'singlePosition', '10%'),
        ('limits', 'singleIssuer', 20),
        ('limits', 'minReserve', "CHF 50'000"),
        ('limits', 'maxIlliquid', 7.5),
    ],
)
def test_existing_value_spellings_and_input_types_remain_accepted(section, key, value):
    parsed = AllocationPreferencesPayload.model_validate(
        {section: {key: value}}
    ).model_dump()
    assert parsed[section][key] == value


@pytest.mark.parametrize(("fragment", "unknown_key"), UNKNOWN_KEY_CASES)
def test_generate_api_rejects_unknown_preference_keys_with_422(
    monkeypatch,
    fragment,
    unknown_key,
):
    """Body validation must reject typos before mandate or engine lookup."""

    advisor = SimpleNamespace(
        id="advisor-preferences-contract",
        role="advisor",
        tenant_id=None,
        full_name="Preferences Contract",
    )

    def _override_db():
        yield None

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_advisor] = lambda: advisor
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mandates/not-looked-up/target-allocation/generate",
                json={"preferences": fragment},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
    assert unknown_key in response.text


@pytest.mark.parametrize(("fragment", "unknown_key"), UNKNOWN_KEY_CASES)
def test_direct_generate_rejects_unknown_runtime_keys_before_solver(
    session_factory,
    monkeypatch,
    fragment,
    unknown_key,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"prefs-runtime-{unknown_key.lower()}",
        )
    )
    solver_calls = []

    def _unexpected_solver(**kwargs):
        solver_calls.append(kwargs)
        raise AssertionError("solver must not receive unvalidated preferences")

    monkeypatch.setattr(solver_module, "run_solver", _unexpected_solver)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        with pytest.raises(ValueError, match=unknown_key):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=fragment,
            )

    assert solver_calls == []


@pytest.mark.parametrize(
    ("consumer", "fragment", "unknown_key"),
    [
        pytest.param(
            "reload",
            {"mysteryPersistedTopLevel": True},
            "mysteryPersistedTopLevel",
            id="reload-top-level",
        ),
        pytest.param(
            "reload",
            {"simulation": {"mysteryPersistedSimulation": 1}},
            "mysteryPersistedSimulation",
            id="reload-nested",
        ),
        pytest.param(
            "sensitivity",
            {"mysteryPersistedTopLevel": True},
            "mysteryPersistedTopLevel",
            id="sensitivity-top-level",
        ),
        pytest.param(
            "sensitivity",
            {"simulation": {"mysteryPersistedSimulation": 1}},
            "mysteryPersistedSimulation",
            id="sensitivity-nested",
        ),
    ],
)
def test_persisted_unknown_preferences_fail_closed_on_reload_and_sensitivity(
    session_factory,
    monkeypatch,
    consumer,
    fragment,
    unknown_key,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"prefs-persisted-{consumer}-{unknown_key.lower()}",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    allocation_id = generated["target_allocation"].id

    with session_factory() as session:
        allocation = _persist_unknown_preference(
            session,
            allocation_id,
            fragment,
        )
        if consumer == "reload":
            with pytest.raises(ValueError, match=unknown_key):
                _reload_payload(session, allocation)
            return

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()

        def _unexpected_sensitivity_solver(**_kwargs):
            raise AssertionError(
                "sensitivity solver must not receive persisted unknown preferences"
            )

        monkeypatch.setattr(
            solver_module,
            "run_solver",
            _unexpected_sensitivity_solver,
        )
        with pytest.raises(ValueError, match=unknown_key):
            pe.evaluate_goal_sensitivity(
                session,
                mandate,
                advisor_id,
                goal_id,
                target_delta_pct=0,
            )
