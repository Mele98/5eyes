"""X2b: Leser der Mandats-Jurisdiktion im Engine-Lauf ueber den RunContext.

Folgeplan X2-Rest (PR #833), Gruppen A und B, verhaltensneutral:

* ``services/portfolio_engine_payload._filter_products_by_universe``
* ``services/product_eligibility_finalization.finalization_eligibility_findings``
* ``services/mortality/horizon.expected_death_year_offset_from_mandate``
  (+ Durchreichung ``resolve_mortality_cutoff`` / Payload-Wrapper)
* ``services/mandate_model_inputs.validate_mortality_model_inputs``
  (+ ``validate_mandate_model_inputs`` / ``mortality_solver_kwargs_from_mandate``)
* ``routers/review.py`` (Draft-Create, Finalisierung): Kontext einmal pro Request

Nachweise:
1. Tabellentest je Stelle: Ergebnis (Wert UND Typ) ohne Kontext == mit
   ``build_run_context(mandate)`` fuer NULL, "", CH, ch, " CH ", CH-ZH, DE,
   AT, XX -- und beide == das bisherige Inline-Orakel.
2. Quelle: mit Kontext folgt die Stelle dem Kontext, nicht ``mandate``.
3. Reihenfolge im Lauf: ``build_run_context`` vor der Modell-Input-Validierung
   wirft nicht und aendert Fehlerbild/Reihenfolge nicht.
4. Golden: expliziter RunContext == Default fuer alle Golden-Fixtures.
5. Statisch: Engine/Router reichen den Kontext tatsaechlich durch.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import tests.test_golden_snapshot_ch_regression as golden  # noqa: E402
from config import RunContext, settings  # noqa: E402
from database import Base  # noqa: E402
from jurisdictions.resolve import resolve_pack  # noqa: E402
import services.mandate_model_inputs as mmi  # noqa: E402
import services.mortality.horizon as horizon  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
import services.portfolio_engine_payload as payload  # noqa: E402
import services.product_eligibility_finalization as fin  # noqa: E402

RAWS = [None, "", "CH", "ch", " CH ", "CH-ZH", "DE", "AT", "XX"]
_MISSING = object()


def _ctx_for(mandate) -> RunContext:
    return pe.build_run_context(mandate)


def _outcome(fn):
    """(Wert, Typ) oder (Exception-Typ, Text) -- vergleichbar ueber Laeufe."""
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 -- Fehlerbild ist Teil des Vergleichs
        return ("raise", type(exc), str(exc))
    return ("ok", value, type(value))


# --- 1/2: Tabellentests je Stelle ---------------------------------------------


@pytest.mark.parametrize("raw", RAWS)
def test_filter_products_by_universe_table(raw):
    jurisdictions = [None, "", "CH", "ch", " CH ", "CH-ZH", "DE", "AT", "XX"]
    products = [SimpleNamespace(id=f"p{i}", jurisdiction=j) for i, j in enumerate(jurisdictions)]

    class _Query:
        def __init__(self, sink):
            self.sink = sink

        def filter(self, *args):
            for arg in args:
                left = getattr(arg, "left", None)
                if getattr(left, "key", None) == "jurisdiction":
                    self.sink.append(arg.right.value)
            return self

        def all(self):
            return []

    def run(run_context=_MISSING):
        sink: list = []
        db = SimpleNamespace(query=lambda *_a: _Query(sink))
        mandate = SimpleNamespace(jurisdiction=raw, tenant_id=None)
        kwargs = {} if run_context is _MISSING else {"run_context": run_context}
        if run_context is not _MISSING and run_context == "build":
            kwargs = {"run_context": _ctx_for(mandate)}
        out = payload._filter_products_by_universe(db, mandate, products, **kwargs)
        assert len(sink) == 1
        return [p.id for p in out], sink[0], type(sink[0])

    oracle = raw or "CH"
    legacy = run()
    explicit_none = run(None)
    with_ctx = run("build")
    assert legacy == explicit_none == with_ctx
    assert legacy[1] == oracle and legacy[2] is type(oracle)
    assert legacy[0] == [p.id for p in products if p.jurisdiction in (None, oracle)]


def _finalization(monkeypatch, raw, run_context=_MISSING):
    captured: list = []

    def fake_evaluate(_db, **kwargs):
        captured.append(("evaluate", kwargs["jurisdiction"], type(kwargs["jurisdiction"])))
        return SimpleNamespace(
            reason_codes=(f"JUR_{kwargs['jurisdiction']!r}",),
            matched_rule_id=None, position_limit_bps=None,
        )

    class FakeDecisionContext:
        def __init__(self, **kwargs):
            captured.append(("context", kwargs["jurisdiction"], type(kwargs["jurisdiction"])))

    monkeypatch.setattr(fin, "evaluate_product_eligibility", fake_evaluate)
    monkeypatch.setattr(fin, "DecisionContext", FakeDecisionContext)
    monkeypatch.setattr(fin, "_appropriateness_result", lambda *_a: None)
    monkeypatch.setattr(fin, "derive_service_mode", lambda _m: "advisory")
    monkeypatch.setattr(fin, "mandate_tenant_id", lambda _m: "main")
    monkeypatch.setattr(pe, "_risk_score_bucket", lambda _a: "4-5")
    mandate = SimpleNamespace(jurisdiction=raw, id="m1")
    product = SimpleNamespace(id="p1", deleted_at=None, is_active=1, product_name="Fonds")
    positions = [SimpleNamespace(product_id="p1", target_weight_bps=10000)]
    kwargs = {}
    if run_context == "build":
        kwargs = {"run_context": _ctx_for(mandate)}
    elif run_context is not _MISSING:
        kwargs = {"run_context": run_context}
    result = fin.finalization_eligibility_findings(
        None, mandate=mandate, run=SimpleNamespace(id="r1"), assessment=SimpleNamespace(),
        positions=positions, products={"p1": product}, **kwargs,
    )
    return result, captured


@pytest.mark.parametrize("raw", RAWS)
def test_finalization_eligibility_table(monkeypatch, raw):
    legacy = _finalization(monkeypatch, raw)
    explicit_none = _finalization(monkeypatch, raw, None)
    with_ctx = _finalization(monkeypatch, raw, "build")
    assert legacy == explicit_none == with_ctx
    oracle = raw or "CH"
    assert legacy[1] == [
        ("context", oracle, type(oracle)),
        ("evaluate", oracle, type(oracle)),
    ]


def _horizon_mandate(raw):
    return SimpleNamespace(
        jurisdiction=raw, life_expectancy_year=0, use_mortality_simulation=0,
        client_birth_year=1960, client_sex="M", client=None,
    )


def _mortality_mandate(raw):
    return SimpleNamespace(
        jurisdiction=raw, life_expectancy_year=0, use_mortality_simulation=1,
        client_birth_year=1960, client_sex="M", client=None,
    )


@pytest.mark.parametrize("raw", RAWS)
def test_horizon_offset_table(raw):
    mandate = _horizon_mandate(raw)
    legacy = _outcome(lambda: horizon.expected_death_year_offset_from_mandate(mandate, reference_year=2026))
    explicit_none = _outcome(lambda: horizon.expected_death_year_offset_from_mandate(
        mandate, reference_year=2026, run_context=None))
    with_ctx = _outcome(lambda: horizon.expected_death_year_offset_from_mandate(
        mandate, reference_year=2026, run_context=_ctx_for(mandate)))
    assert legacy == explicit_none == with_ctx
    if str(raw or "CH") == "CH":
        assert legacy[0] == "ok" and isinstance(legacy[1], int)
    else:
        assert legacy == ("ok", None, type(None))


@pytest.mark.parametrize("raw", RAWS)
def test_mortality_cutoff_and_payload_wrapper_table(raw):
    mandate = _mortality_mandate(raw)
    legacy = _outcome(lambda: horizon.resolve_mortality_cutoff(mandate, reference_year=2026))
    with_ctx = _outcome(lambda: horizon.resolve_mortality_cutoff(
        mandate, reference_year=2026, run_context=_ctx_for(mandate)))
    assert legacy == with_ctx
    wrap_legacy = _outcome(lambda: payload._expected_death_year_offset_from_mandate(mandate))
    wrap_ctx = _outcome(lambda: payload._expected_death_year_offset_from_mandate(
        mandate, run_context=_ctx_for(mandate)))
    assert wrap_legacy == wrap_ctx


@pytest.mark.parametrize("raw", RAWS)
def test_mandate_model_inputs_table(raw):
    mandate = _mortality_mandate(raw)
    for fn in (
        lambda **kw: mmi.validate_mortality_model_inputs(mandate, reference_year=2026, **kw),
        lambda **kw: mmi.validate_mandate_model_inputs(mandate, reference_year=2026, **kw),
        lambda **kw: mmi.mortality_solver_kwargs_from_mandate(mandate, **kw),
    ):
        legacy = _outcome(fn)
        explicit_none = _outcome(lambda: fn(run_context=None))
        with_ctx = _outcome(lambda: fn(run_context=_ctx_for(mandate)))
        assert legacy == explicit_none == with_ctx
    # Orakel: aktivierte Mortalitaet nur fuer CH (nach strip/upper).
    gate = _outcome(lambda: mmi.validate_mortality_model_inputs(
        mandate, reference_year=2026, run_context=_ctx_for(mandate)))
    if str(raw or "CH").strip().upper() == "CH":
        assert gate == ("ok", None, type(None))
    else:
        assert gate[0] == "raise" and gate[1] is mmi.MandateModelInputError


def _ctx(code) -> RunContext:
    return RunContext.capture(resolve_pack(code=code), SimpleNamespace(optimizer_mode="stochastic"))


def test_context_is_the_source_in_run():
    """Mit Kontext folgt jede umgestellte Stelle dem Kontext, nicht mandate."""
    de_mandate = _mortality_mandate("DE")
    ch_ctx = _ctx("CH")
    # Mortalitaets-Gate: DE-Mandat waere ohne Kontext abgelehnt.
    with pytest.raises(mmi.MandateModelInputError):
        mmi.validate_mortality_model_inputs(de_mandate, reference_year=2026)
    mmi.validate_mortality_model_inputs(de_mandate, reference_year=2026, run_context=ch_ctx)
    # Horizont: DE ohne Kontext -> kein Cutoff; mit CH-Kontext -> Offset.
    off_mandate = _horizon_mandate("DE")
    assert horizon.expected_death_year_offset_from_mandate(off_mandate, reference_year=2026) is None
    assert isinstance(horizon.expected_death_year_offset_from_mandate(
        off_mandate, reference_year=2026, run_context=ch_ctx), int)

    # Produktuniversum: Bindwert kommt aus dem Kontext.
    sink: list = []

    class _Q:
        def filter(self, *args):
            sink.extend(a.right.value for a in args if getattr(getattr(a, "left", None), "key", None) == "jurisdiction")
            return self

        def all(self):
            return []

    db = SimpleNamespace(query=lambda *_a: _Q())
    payload._filter_products_by_universe(db, SimpleNamespace(jurisdiction="DE", tenant_id=None), [], run_context=ch_ctx)
    assert sink == ["CH"]


def test_finalization_follows_context(monkeypatch):
    _result, captured = _finalization(monkeypatch, "DE", _ctx("CH"))
    assert [c[1] for c in captured] == ["CH", "CH"]


# --- 3: Reihenfolge Kontextbildung vor Validierung ----------------------------


@pytest.mark.parametrize("raw", [*RAWS, _MISSING, 0, 7])
def test_build_run_context_never_raises(raw):
    mandate = SimpleNamespace() if raw is _MISSING else SimpleNamespace(jurisdiction=raw)
    ctx = pe.build_run_context(mandate)
    assert ctx.jurisdiction == (getattr(mandate, "jurisdiction", None) or "CH")


def test_validation_still_first_and_error_unchanged(monkeypatch):
    """Ungueltige Modell-Inputs: gleicher Fehler wie die Einzel-Validierung,
    weiterhin vor Referenzdaten-Auswahl (ensure_runtime_reference_data)."""
    mandate = _mortality_mandate("DE")
    with pytest.raises(mmi.MandateModelInputError) as standalone:
        mmi.validate_mandate_model_inputs(mandate)

    def must_not_run(*_a, **_k):
        raise AssertionError("Referenzdaten vor der Validierung gelesen")

    monkeypatch.setattr(pe, "ensure_runtime_reference_data", must_not_run)
    with pytest.raises(mmi.MandateModelInputError) as in_run:
        pe.generate_target_allocation(None, mandate, "u1", None)
    assert str(in_run.value) == str(standalone.value)
    with pytest.raises(mmi.MandateModelInputError) as in_run_ctx:
        pe.generate_target_allocation(None, mandate, "u1", None, run_context=pe.build_run_context(mandate))
    assert str(in_run_ctx.value) == str(standalone.value)


# --- 4: Golden-Fixtures mit explizitem RunContext -----------------------------


@pytest.fixture()
def factories(tmp_path):
    made = []

    def make(name: str):
        engine = create_engine(f"sqlite:///{tmp_path / name}.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        made.append(engine)
        return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    yield make
    for engine in made:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _snapshot(factory, combo, *, explicit, monkeypatch):
    original = golden.generate_target_allocation
    if explicit:
        def with_context(db, mandate, user_id, preferences=None):
            return original(db, mandate, user_id, preferences=preferences,
                            run_context=pe.build_run_context(mandate))

        monkeypatch.setattr(golden, "generate_target_allocation", with_context)
    try:
        return golden._build_ch_snapshot(factory, combo)
    finally:
        monkeypatch.setattr(golden, "generate_target_allocation", original)


@pytest.mark.parametrize("combo", golden.COMBOS, ids=[c["name"] for c in golden.COMBOS])
def test_explicit_run_context_equals_default_for_golden_fixtures(factories, monkeypatch, combo):
    assert settings.optimizer_mode == "stochastic"
    default = _snapshot(factories("default"), combo, explicit=False, monkeypatch=monkeypatch)
    explicit = _snapshot(factories("explicit"), combo, explicit=True, monkeypatch=monkeypatch)
    assert json.dumps(explicit, sort_keys=True) == json.dumps(default, sort_keys=True)
    expected = json.loads((golden.FIXTURES_DIR / f"{combo['name']}.json").read_text(encoding="utf-8"))
    golden._assert_ch_snapshot_matches(explicit, expected)


# --- 5: statische Durchreichung -----------------------------------------------


def _calls(rel: str, func: str, callee: str) -> list[ast.Call]:
    tree = ast.parse((BACKEND_ROOT / rel).read_text(encoding="utf-8-sig"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func)
    return [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == callee
    ]


@pytest.mark.parametrize(
    "rel, func, callee",
    [
        ("services/portfolio_engine.py", "generate_target_allocation", "validate_mandate_model_inputs"),
        ("services/portfolio_engine.py", "generate_target_allocation", "_run_stochastic_optimizer_pass"),
        ("services/portfolio_engine.py", "generate_target_allocation", "_expected_death_year_offset_from_mandate"),
        ("services/portfolio_engine.py", "generate_recommendation_run", "_filter_products_by_universe"),
        ("services/portfolio_engine_optimizer_integration.py", "_run_stochastic_optimizer_pass",
         "mortality_solver_kwargs_from_mandate"),
        ("services/portfolio_engine_payload.py", "_expected_death_year_offset_from_mandate",
         "resolve_mortality_cutoff"),
        ("services/mortality/horizon.py", "resolve_mortality_cutoff", "expected_death_year_offset_from_mandate"),
        ("services/mandate_model_inputs.py", "validate_mandate_model_inputs", "validate_mortality_model_inputs"),
        ("services/mandate_model_inputs.py", "mortality_solver_kwargs_from_mandate",
         "validate_mortality_model_inputs"),
        ("services/mandate_model_inputs.py", "mortality_solver_kwargs_from_mandate",
         "expected_death_year_offset_from_mandate"),
        ("routers/review.py", "_validate_recommendation_for_finalization", "finalization_eligibility_findings"),
    ],
)
def test_run_context_is_passed_through(rel, func, callee):
    calls = _calls(rel, func, callee)
    assert calls, f"{func} ruft {callee} nicht auf"
    for call in calls:
        assert "run_context" in {k.arg for k in call.keywords}, f"{rel}:{call.lineno} ohne run_context"


def test_review_draft_create_uses_request_context():
    calls = _calls("routers/review.py", "create_recommendation_run", "ensure_runtime_reference_data")
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert ast.unparse(kw["jurisdiction"]) == "build_run_context(mandate).jurisdiction"
