"""CCX P5 / M-2: ein kanonischer Risikoparametersatz (Vertrag 2026-11-13 §8.1).

Abnahme (Vertrag):
1. Solver, Payload und PDF lesen denselben Vektor (Integrationsteil in
   test_ccx_p5_channel_envelope.py; hier: Engine-Persistenz = Satz).
2. Zwei verschiedene Suballokationen desselben Buckets -> nachvollziehbar
   verschiedene Bucket-Koeffizienten.
3. Fehlende/ungepruefte IC-Policy blockiert fail-closed.
4. Kein produktiver Pfad liest die historischen Hardcode-Saetze.
5. (Kanaele: siehe Integrationsdatei.)
Dazu Inflation: kein lokaler 150-bps-/70-bps-Ersatzwert mehr.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.risk_parameter_set import (
    BASIS_NOT_INVESTABLE,
    BASIS_SUB_ALLOCATION,
    ParameterSetMissing,
    assert_release_allowed,
    build_parameter_set,
    canonical_bucket_coefficients,
    ic_bucket_means_bps,
    parameter_set_hash,
    verify_parameter_set,
)

BACKEND = Path(__file__).resolve().parents[1]


def _row(asset_class, sub, rf, mix, weight=0):
    return {"asset_class": asset_class, "sub_asset_class": sub, "risky_fraction_bps": rf,
            "within_bucket_weight_bps": mix, "target_weight_bps": weight}


def _policy():
    return SimpleNamespace(id="pol-1", version=1, valid_from="2026-01-01", max_real_estate_bps=2000,
                           max_alternatives_bps=1000, min_liquidity_bps=0)


BOUNDS = {b: (0, 10000) for b in ("equities", "bonds", "real_estate", "alternatives", "liquidity")}


def _set(rows):
    return build_parameter_set(policy=_policy(), sub_allocations=rows, bounds_bps=BOUNDS, risk_budget_bps=6000,
                               house_matrix_profile="Ausgewogen", max_risky_fraction_bps=6000,
                               rounding_policy_version="ares-rounding/1",
                               house_prior={"version": "test", "kappa_x100": 30000})


def test_two_sub_allocations_of_one_bucket_give_different_coefficients():
    ch_heavy = [_row("Aktien", "Aktien Schweiz", 7000, 8000), _row("Aktien", "Aktien Global", 8000, 2000)]
    global_heavy = [_row("Aktien", "Aktien Schweiz", 7000, 2000), _row("Aktien", "Aktien Global", 8000, 8000)]
    a, basis_a = canonical_bucket_coefficients(ch_heavy)
    b, _ = canonical_bucket_coefficients(global_heavy)
    assert a["equities"] == 7200 and b["equities"] == 7800
    assert basis_a["equities"] == BASIS_SUB_ALLOCATION
    assert _set(ch_heavy)["parameter_set_hash"] != _set(global_heavy)["parameter_set_hash"]


def test_bucket_without_subclass_is_not_investable_not_a_code_constant():
    coefficients, basis = canonical_bucket_coefficients([_row("Obligationen", "CHF IG", 2000, 10000)])
    # Gegenprobe zum frueheren Code-Satz: 7900/5000 sind verschwunden.
    assert coefficients["equities"] == 0 and coefficients["real_estate"] == 0
    assert basis["equities"] == BASIS_NOT_INVESTABLE


def test_weight_on_bucket_without_ic_value_fails_closed():
    from services.portfolio_engine_house_matrix import _enrich_sub_allocations_with_risk

    with pytest.raises(ParameterSetMissing):
        _enrich_sub_allocations_with_risk(
            [{"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 5000,
              "within_bucket_weight_bps": 0, "risky_fraction_bps": 7000}], {},
        )


def test_missing_ic_subclass_value_fails_closed():
    from services.portfolio_engine_house_matrix import _enrich_sub_allocations_with_risk

    with pytest.raises(ValueError):
        _enrich_sub_allocations_with_risk(
            [{"asset_class": "Aktien", "sub_asset_class": "Unbekannt", "target_weight_bps": 5000}], {},
        )


def test_historic_hardcoded_sets_are_gone():
    import services.optimizer.constraints as constraints
    import services.portfolio_engine as engine

    assert not hasattr(engine, "DEFAULT_ASSET_RISKY_WEIGHTS_BPS")
    assert not hasattr(constraints, "DEFAULT_BUCKET_RISKY_FRACTION")
    # AST-Waechter: kein produktives Dict mit den Vorlagewerten als Fallback.
    forbidden = ({7900, 2450, 5000, 6000}, {0.80, 0.25, 0.60})
    hits = []
    for path in (BACKEND / "services").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict) and node.keys and all(
                isinstance(k, ast.Constant) and k.value in {"equities", "bonds", "real_estate", "alternatives",
                                                            "liquidity"} for k in node.keys
            ):
                values = {v.value for v in node.values if isinstance(v, ast.Constant)}
                if any(group <= values for group in forbidden):
                    hits.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert hits == []


@pytest.fixture()
def no_test_vector():
    from services.optimizer.constraints import set_test_risky_fraction

    previous = set_test_risky_fraction(None)
    yield
    set_test_risky_fraction(previous)


def test_optimizer_without_canonical_vector_fails_closed(no_test_vector):
    from services.optimizer.constraints import build_risky_fraction_constraint
    from services.optimizer.solver import _candidate_risky_fraction

    with pytest.raises(ParameterSetMissing):
        build_risky_fraction_constraint(60, None)
    import numpy as np

    with pytest.raises(ParameterSetMissing):
        _candidate_risky_fraction(np.array([0.2] * 5), None)


def test_test_vector_is_only_settable_under_pytest_and_never_read_by_production_code():
    """Der Testvektor ist kein stiller Fallback: nur unter pytest setzbar und
    ausser in ``require_risky_fraction_per_bucket`` von keinem Modul gelesen."""
    readers = [
        str(path.relative_to(BACKEND)) for path in (BACKEND / "services").rglob("*.py")
        if "test_risky_fraction()" in path.read_text(encoding="utf-8")
    ]
    assert readers == [str(Path("services/optimizer/constraints.py"))]
    for path in list((BACKEND / "services").rglob("*.py")) + list((BACKEND / "routers").rglob("*.py")):
        assert "p5_test_vectors" not in path.read_text(encoding="utf-8"), path


def test_parameter_and_goal_metric_modules_are_stdlib_leaves():
    """Eine Quelle ohne Modulkanten: beide Vertraege sind reine Stdlib-Blaetter."""
    import ast

    for rel in ("core/risk_parameter_set.py", "core/goal_metric_contract.py"):
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert modules <= {"__future__", "hashlib", "json", "typing"}, (rel, modules)


def test_building_block_mean_without_bucket_fails_closed():
    from services.optimizer.constraints import bucket_risky_fractions_from_building_blocks

    rows = [SimpleNamespace(asset_class="Aktien", risky_fraction_bps=8000)]
    with pytest.raises(ParameterSetMissing):
        bucket_risky_fractions_from_building_blocks(rows)
    with pytest.raises(ParameterSetMissing):
        ic_bucket_means_bps({("aktien", "x"): 8000})


def test_parameter_set_hash_is_order_neutral_and_mutation_sensitive():
    rows = [_row("Aktien", "Aktien Schweiz", 7000, 5000), _row("Obligationen", "CHF IG", 2000, 10000)]
    record = _set(rows)
    reordered = dict(reversed(list(record.items())))
    assert parameter_set_hash(reordered) == record["parameter_set_hash"]
    mutated = _set([_row("Aktien", "Aktien Schweiz", 7001, 5000), _row("Obligationen", "CHF IG", 2000, 10000)])
    assert mutated["parameter_set_hash"] != record["parameter_set_hash"]
    assert verify_parameter_set(record) == record["parameter_set_hash"]
    tampered = {**record, "risk_budget_bps": 9000}
    with pytest.raises(ParameterSetMissing):
        verify_parameter_set(tampered)
    with pytest.raises(ParameterSetMissing):
        verify_parameter_set(None)
    with pytest.raises(ParameterSetMissing):
        verify_parameter_set(record, persisted_coefficients={**record["bucket_coefficients_bps"], "equities": 1})


def test_unreleased_parameters_fail_closed_in_production(monkeypatch):
    from config import settings

    record = _set([_row("Obligationen", "CHF IG", 2000, 10000)])
    assert record["ic_release_status"] == "UNRELEASED"  # nie als freigegeben behauptet
    monkeypatch.setattr(settings, "app_env", "development")
    assert settings.ic_release_required is False
    assert_release_allowed(record, release_required=settings.ic_release_required)
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(ParameterSetMissing):
        assert_release_allowed(record, release_required=settings.ic_release_required)
    # N-925-05 (CTO-Entscheid H-180): gepackte EXE gilt als Produktion.
    import sys

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert settings.ic_release_required is True
    with pytest.raises(ParameterSetMissing):
        assert_release_allowed(record, release_required=settings.ic_release_required)


def test_cma_without_inflation_path_fails_closed():
    from services.portfolio_engine_cma import _inflation_path_series

    with pytest.raises(ParameterSetMissing):
        _inflation_path_series(SimpleNamespace(inflation_path_json=None), 5, 2026)
    with pytest.raises(ParameterSetMissing):
        _inflation_path_series(SimpleNamespace(inflation_path_json="{}"), 5, 2026)
    series = _inflation_path_series(SimpleNamespace(inflation_path_json='{"2026": 50, "2027": 90}'), 3, 2026)
    assert series == [50, 90, 90]


def test_local_inflation_fallbacks_are_gone():
    from services.portfolio_engine_gesamtvermoegen import _external_assets_inflation_value
    from services.portfolio_engine_payload import _inflate_real_goal_target_rappen

    with pytest.raises(ParameterSetMissing):
        _inflate_real_goal_target_rappen(100_000, 5, [])
    with pytest.raises(ParameterSetMissing):
        _external_assets_inflation_value(100_000, 5, None)
    # Gegenprobe: mit Pfad unveraendert.
    assert _inflate_real_goal_target_rappen(100_000, 1, [100]) == 101_000
    assert _external_assets_inflation_value(100_000, 0, None) == 100_000
    for rel in ("services/portfolio_engine_payload.py", "services/portfolio_engine_gesamtvermoegen.py"):
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert "or [150]" not in text and "else 150" not in text


def test_integrity_check_ignores_inert_legacy_coefficient_of_non_investable_bucket():
    """Bestand vor P5 speicherte 7900 fuer einen nicht investierbaren Bucket;
    der Wert ist inert (Gewicht 0) und macht die Allokation nicht ungueltig."""
    from core.risk_parameter_set import risk_from_targets

    coefficients, basis = canonical_bucket_coefficients([_row("Obligationen", "CHF IG", 2000, 10000)])
    legacy = {**coefficients, "equities": 7900}
    targets = {"equities": 0, "bonds": 10000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    assert risk_from_targets(targets, legacy) == risk_from_targets(targets, coefficients) == 2000
    assert basis["equities"] == BASIS_NOT_INVESTABLE



def test_unreleased_set_is_labelled_in_advisor_and_customer_channels():
    """N-925-05: Kennzeichnung «Vorlagewerte – nicht IC-freigegeben» im
    Beraterkanal (Allocation-Banner) und im Fuss jedes Kunden-PDFs."""
    from core.customer_terms import decision_footer_label
    from core.risk_parameter_set import IC_UNRELEASED_LABEL, release_notice_messages

    record = _set([_row("Obligationen", "CHF IG", 2000, 10000)])
    messages = release_notice_messages(record)
    assert [m["code"] for m in messages] == ["WARN_RISK_PARAMETERS_UNRELEASED"]
    assert messages[0]["title"] == IC_UNRELEASED_LABEL == "Vorlagewerte – nicht IC-freigegeben"
    assert release_notice_messages({**record, "ic_release_status": "RELEASED"}) == []
    sealed = {"envelope_hash": "a" * 64, "fassung": "1", "ic_release_status": "UNRELEASED"}
    assert decision_footer_label(sealed).endswith(" · Vorlagewerte – nicht IC-freigegeben")
    assert decision_footer_label({"ic_release_status": "UNRELEASED"}) == (
        "Beratungsentscheid: keiner versiegelt · Vorlagewerte – nicht IC-freigegeben")
    assert "IC" not in decision_footer_label({**sealed, "ic_release_status": "RELEASED"})


@pytest.mark.p5_no_test_vector
def test_optimizer_integration_does_not_swallow_missing_parameter_set():
    """N-925-06: ohne Testvektor und mit unvollstaendigen BuildingBlocks endet
    der Optimierer-Pfad mit CCX_PARAMETER_SET_MISSING (frueher zu None
    geschluckt und vom session-weiten Testvektor verdeckt)."""
    from services.optimizer.constraints import test_risky_fraction
    from services.portfolio_engine_optimizer_integration import _run_stochastic_optimizer_pass

    assert test_risky_fraction() is None
    with pytest.raises(ParameterSetMissing):
        _run_stochastic_optimizer_pass(
            optimizer_mode="stochastic", apply_targets=False, cma=None, goals=[], house_matrix=None,
            assessment=SimpleNamespace(final_score_x10=50, final_profile="Ausgewogen", is_overridden=0,
                                  override_score_x10=None),
            advisory_wealth_rappen=100_000_00, cashflow_projection_series_rappen=[0] * 10,
            inflation_series_bps=[70] * 10, targets={}, minimums={}, maximums={}, reasoning=[],
            building_blocks_rows=[SimpleNamespace(asset_class="Aktien", risky_fraction_bps=8000)],
        )


def test_parameter_set_missing_is_a_typed_409_everywhere():
    """N-925-07: ungefangen (z. B. routers/clients.py Cashflow-Projektion,
    routers/wealth.py) war es HTTP 500; ueber ``except ValueError ->
    HTTPException(409, str(exc))`` ein 409 ohne Reason-Code. Beide Wege enden
    jetzt in 409 + ``CCX_PARAMETER_SET_MISSING`` bzw. ``CCX_GOAL_METRIC_UNCERTIFIED``."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from core.goal_metric_contract import GoalMetricUncertified
    from core.middleware import install_exception_handlers

    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/raw")
    def raw():
        raise ParameterSetMissing("Die Kapitalmarktannahmen enthalten keinen Inflationspfad.")

    @app.get("/wrapped")
    def wrapped():
        try:
            raise GoalMetricUncertified("keine Zertifizierung")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/plain")
    def plain():
        raise HTTPException(status_code=409, detail="anderer Konflikt")

    client = TestClient(app, raise_server_exceptions=False)
    raw_resp = client.get("/raw")
    assert raw_resp.status_code == 409
    assert raw_resp.json()["detail"]["reason_code"] == "CCX_PARAMETER_SET_MISSING"
    wrapped_resp = client.get("/wrapped")
    assert wrapped_resp.status_code == 409
    assert wrapped_resp.json()["detail"]["reason_code"] == "CCX_GOAL_METRIC_UNCERTIFIED"
    assert client.get("/plain").json() == {"detail": "anderer Konflikt"}  # Gegenprobe: unveraendert
