"""K-3: RunContext-Freeze (Phase 2 Modularisierung, verhaltensneutral).

Nachweise:
1. ``RunContext`` ist eingefroren (frozen + slots).
2. ``build_run_context`` liefert fuer die Jurisdiktion exakt
   ``resolve_pack(mandate).code`` und fuer den Optimizer-Modus exakt
   ``settings.optimizer_mode``.
3. Ein Lauf mit explizit uebergebenem RunContext ist fuer ALLE Golden-
   Fixtures exakt gleich dem Lauf ohne (Default) -- und beide treffen das
   eingefrorene Golden-Fixture.
4. Freeze: eine Settings-Aenderung waehrend des Laufs beeinflusst den
   migrierten Leser (``optimizer_mode``) nicht mehr; der explizit
   uebergebene Kontext ist die einzige Quelle dieses Lesers.
"""
from __future__ import annotations

import dataclasses
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
from models.mandates import Mandate  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402


def _session_factory(path: Path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine, factory


@pytest.fixture()
def factories(tmp_path):
    made = []

    def make(name: str):
        engine, factory = _session_factory(tmp_path / f"{name}.db")
        made.append(engine)
        return factory

    yield make
    for engine in made:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# --- 1/2: Datentyp und Bildung ------------------------------------------------


def _ctx() -> RunContext:
    return RunContext.capture(resolve_pack(None), SimpleNamespace(optimizer_mode="stochastic"))


def test_run_context_is_frozen():
    ctx = _ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.optimizer_mode = "house_matrix"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.jurisdiction = "DE"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(ctx, "neues_feld", 1)
    assert dataclasses.replace(ctx) == ctx
    assert RunContext.__dataclass_params__.frozen is True


@pytest.mark.parametrize("raw", [None, "", "CH", "ch", " CH ", "CH-ZH", "DE", "AT", "XX"])
def test_build_run_context_matches_previous_readers(monkeypatch, raw):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    mandate = SimpleNamespace(jurisdiction=raw)
    ctx = pe.build_run_context(mandate)
    resolved = resolve_pack(mandate)
    assert ctx.jurisdiction == resolved.code
    assert type(ctx.jurisdiction) is type(resolved.code)
    assert ctx.jurisdiction == (getattr(mandate, "jurisdiction", None) or "CH")
    assert ctx.jurisdiction_source == resolved.source
    assert ctx.resolved_pack == resolved
    assert ctx.optimizer_mode == "shadow_stochastic"


def test_capture_snapshot_is_independent_of_later_settings_changes(monkeypatch):
    monkeypatch.setattr(settings, "optimizer_mode", "stochastic")
    ctx = pe.build_run_context(SimpleNamespace(jurisdiction=None))
    monkeypatch.setattr(settings, "optimizer_mode", "house_matrix")
    assert ctx.optimizer_mode == "stochastic"


# --- 3: expliziter RunContext == Default fuer alle Golden-Fixtures -------------


def _snapshot(factory, combo: dict, *, explicit: bool, monkeypatch) -> dict:
    original = golden.generate_target_allocation
    if explicit:
        def with_context(db, mandate, user_id, preferences=None):
            ctx = RunContext(
                jurisdiction=resolve_pack(mandate).code,
                jurisdiction_source=resolve_pack(mandate).source,
                resolved_pack=resolve_pack(mandate),
                optimizer_mode="stochastic",
            )
            return original(db, mandate, user_id, preferences=preferences, run_context=ctx)

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


# --- 4: Freeze des migrierten Lesers (optimizer_mode) ---------------------------


def _run_with_mid_run_flip(factory, monkeypatch, *, start_mode: str, flip_to: str, run_context=None):
    """Startet einen Lauf mit ``start_mode`` und stellt ``settings.optimizer_mode``
    waehrend des Laufs (nach der Kontextbildung, vor dem frueheren Lesezeitpunkt)
    auf ``flip_to`` um."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", start_mode)
    advisor_id, _cid, mid, _aid = golden._seed_ch_mandate(factory, suffix="k3_freeze", score_x10=50)
    real_ensure = pe.ensure_runtime_reference_data
    flips = []

    def flipping_ensure(*args, **kwargs):
        result = real_ensure(*args, **kwargs)
        monkeypatch.setattr(pe.settings, "optimizer_mode", flip_to)
        flips.append(flip_to)
        return result

    monkeypatch.setattr(pe, "ensure_runtime_reference_data", flipping_ensure)
    with factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = pe.generate_target_allocation(s, mandate, advisor_id, None, run_context=run_context)
    assert flips == [flip_to], "der Umschalter muss genau einmal waehrend des Laufs greifen"
    assert pe.settings.optimizer_mode == flip_to
    return result["target_allocation"]


def test_mid_run_settings_change_does_not_affect_optimizer_mode(factories, monkeypatch):
    allocation = _run_with_mid_run_flip(
        factories("freeze"), monkeypatch, start_mode="house_matrix", flip_to="stochastic",
    )
    # Vor K-3 haette der spaete Lesezeitpunkt den Solver eingeschaltet.
    # House-Matrix-Laeufe persistieren keine Solver-Methode (None).
    assert allocation.optimization_method is None


def test_mid_run_settings_change_does_not_switch_solver_off(factories, monkeypatch):
    allocation = _run_with_mid_run_flip(
        factories("freeze_reverse"), monkeypatch, start_mode="stochastic", flip_to="house_matrix",
    )
    assert allocation.optimization_method == "stochastic"


def test_explicit_run_context_is_the_only_source_of_optimizer_mode(factories, monkeypatch):
    ctx = RunContext.capture(resolve_pack(None), SimpleNamespace(optimizer_mode="house_matrix"))
    allocation = _run_with_mid_run_flip(
        factories("explicit_freeze"), monkeypatch,
        start_mode="stochastic", flip_to="stochastic", run_context=ctx,
    )
    assert allocation.optimization_method is None
