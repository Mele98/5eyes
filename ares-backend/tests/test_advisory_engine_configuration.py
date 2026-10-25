"""Sprint C2-Wiring (2026-06-08): engine_configuration im advisory_report-Aggregator.

Verifiziert dass:
1. compute_advisory_report den engine_configuration-Key liefert
2. _build_engine_configuration die OptimizerRun.reasoning_json korrekt parst
3. Defaults bei House-Matrix-Mode (keine OptimizerRun)
4. Sub-Allocation-Aware-Detection via TargetAllocation
5. Defensive bei korruptem reasoning_json
"""
from __future__ import annotations

from services.advisory_report import (
    _build_engine_configuration,
    _detect_is_status_from_reasoning,
    _detect_sub_allocation_aware,
    _detect_tax_mode_from_settings,
)


# ===========================================================================
# 1. _detect_is_status_from_reasoning
# ===========================================================================


def test_detect_is_aktiv_aus_reasoning():
    """P1-Konvention: 'Importance Sampling AKTIV (...)' wird erkannt."""
    text = "Stochastic Solver SLSQP: 5 iters. Importance Sampling AKTIV (Tail-Schutz)."
    is_active, reason = _detect_is_status_from_reasoning(text)
    assert is_active is True
    assert "aktiv" in reason.lower()


def test_detect_is_inaktiv_aus_reasoning():
    """'Importance Sampling INAKTIV' wird erkannt."""
    text = "Stochastic Solver. Importance Sampling INAKTIV (Standard-MC)."
    is_active, reason = _detect_is_status_from_reasoning(text)
    assert is_active is False
    assert "standard-mc" in reason.lower() or "uniform" in reason.lower()


def test_detect_is_kein_match_returns_inaktiv_default():
    """Wenn weder aktiv noch inaktiv im Text: Default = inaktiv."""
    text = "Some other reasoning ohne IS-Markierung."
    is_active, reason = _detect_is_status_from_reasoning(text)
    assert is_active is False
    assert reason == ""


def test_detect_is_case_insensitive():
    """Case-insensitive Match (Reasoning kann mixed-case sein)."""
    text = "IMPORTANCE SAMPLING AKTIV bla"
    is_active, _ = _detect_is_status_from_reasoning(text)
    assert is_active is True


# ===========================================================================
# 2. _detect_tax_mode_from_settings
# ===========================================================================


def test_detect_tax_mode_default_median():
    """Default ohne explizites Setting: 'median' (Backwards-Compat)."""
    mode = _detect_tax_mode_from_settings()
    assert mode in ("median", "binned", "per_path")


def test_detect_tax_mode_settings_override(monkeypatch):
    """Setting mc_default_tax_mode wird respektiert."""
    from config import settings
    monkeypatch.setattr(settings, "mc_default_tax_mode", "binned", raising=False)
    mode = _detect_tax_mode_from_settings()
    assert mode == "binned"


# ===========================================================================
# 3. _detect_sub_allocation_aware
# ===========================================================================


def test_detect_sub_allocation_aware_no_target_allocation():
    """Bei fehlender TargetAllocation: False (kein Crash)."""
    from types import SimpleNamespace

    class FakeDB:
        def query(self, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self): return None
            return Q()

    mandate = SimpleNamespace(id="m-test")
    result = _detect_sub_allocation_aware(FakeDB(), mandate)
    assert result is False


def test_detect_sub_allocation_aware_db_error_defensive():
    """Bei DB-Exception: False (defensive Fallback)."""
    from types import SimpleNamespace

    class FailingDB:
        def query(self, *args, **kwargs):
            raise RuntimeError("DB crash")

    mandate = SimpleNamespace(id="m-test")
    result = _detect_sub_allocation_aware(FailingDB(), mandate)
    assert result is False


# ===========================================================================
# 4. _build_engine_configuration End-to-End
# ===========================================================================


def test_build_engine_config_defaults_ohne_optimizer_run():
    """Ohne OptimizerRun: optimizer_mode='house_matrix', IS inaktiv."""
    from types import SimpleNamespace

    class EmptyDB:
        def query(self, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self): return None
            return Q()

    mandate = SimpleNamespace(id="m-empty")
    cfg = _build_engine_configuration(EmptyDB(), mandate)
    assert cfg["optimizer_mode"] == "house_matrix"
    assert cfg["importance_sampling_active"] is False
    assert cfg["sub_allocation_aware"] is False
    assert "tax_mode" in cfg
    assert "audit_basis" in cfg


def test_build_engine_config_mit_optimizer_run_is_aktiv():
    """Mit OptimizerRun mit IS-aktiv-Reasoning: importance_sampling_active=True."""
    from types import SimpleNamespace

    class StochasticDB:
        def query(self, model_class, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self):
                    return SimpleNamespace(
                        optimizer_mode="stochastic",
                        reasoning_json="Importance Sampling AKTIV (konservativ + hart-Goal)",
                    )
            return Q()

    mandate = SimpleNamespace(id="m-stoch")
    cfg = _build_engine_configuration(StochasticDB(), mandate)
    assert cfg["optimizer_mode"] == "stochastic"
    assert cfg["importance_sampling_active"] is True
    assert "aktiv" in cfg["importance_sampling_reason"].lower()


def test_build_engine_config_mit_optimizer_run_is_inaktiv():
    """Mit OptimizerRun mit IS-inaktiv-Reasoning."""
    from types import SimpleNamespace

    class StochasticDB:
        def query(self, model_class, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self):
                    return SimpleNamespace(
                        optimizer_mode="stochastic",
                        reasoning_json="Importance Sampling INAKTIV (Standard-MC)",
                    )
            return Q()

    mandate = SimpleNamespace(id="m-stoch-inaktiv")
    cfg = _build_engine_configuration(StochasticDB(), mandate)
    assert cfg["optimizer_mode"] == "stochastic"
    assert cfg["importance_sampling_active"] is False


def test_build_engine_config_defensive_bei_korruptem_reasoning():
    """reasoning_json kann beliebigen String enthalten — kein Crash."""
    from types import SimpleNamespace

    class CorruptDB:
        def query(self, model_class, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self):
                    return SimpleNamespace(
                        optimizer_mode="stochastic",
                        reasoning_json="{garbage}\n\nfailure!!@@%%",
                    )
            return Q()

    mandate = SimpleNamespace(id="m-corrupt")
    cfg = _build_engine_configuration(CorruptDB(), mandate)
    assert cfg["optimizer_mode"] == "stochastic"
    assert cfg["importance_sampling_active"] is False  # nicht erkannt → False


def test_build_engine_config_schema_struktur_korrekt():
    """Alle erwarteten Felder vorhanden + Typen korrekt."""
    from types import SimpleNamespace

    class EmptyDB:
        def query(self, *args, **kwargs):
            class Q:
                def filter(self, *a, **k): return self
                def order_by(self, *a, **k): return self
                def first(self): return None
            return Q()

    cfg = _build_engine_configuration(EmptyDB(), SimpleNamespace(id="m"))
    assert isinstance(cfg["importance_sampling_active"], bool)
    assert isinstance(cfg["importance_sampling_reason"], str)
    assert isinstance(cfg["tax_mode"], str)
    assert isinstance(cfg["sub_allocation_aware"], bool)
    assert isinstance(cfg["optimizer_mode"], str)
    assert isinstance(cfg["audit_basis"], str)
