"""LIQUIDITY-INSTRUMENT-MODEL-001: Codex-Reproducer, als regulaerer Test.

``Kontoguthaben`` existiert nur als Code-Default (portfolio_engine.py,
LIQ-INSTRUMENT-KONTOGUTHABEN-001). Er darf nicht still in eine bereits
genehmigte CMA-Version hineingeerbt und als "CMA Sub-Asset-Class" ausgewiesen
werden. Gerechnet wird unveraendert mit dem Code-Default -- aber deklariert
(Quelle, Freigabestatus, SHA-256) und im Reasoning sichtbar.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from services.portfolio_engine import _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS
from services.portfolio_engine_cma import (
    _sub_asset_class_assumption_map,
    _sub_asset_class_metrics,
    _sub_asset_class_model_map,
)
from services.portfolio_engine_payload import (
    _build_sub_asset_class_assumption_reference,
)

_SLEEVE = [
    {
        "asset_class": "Liquiditaet",
        "sub_asset_class": "Kontoguthaben",
        "target_weight_bps": 100,
    }
]


def _approved_cma(*, include_kontoguthaben: bool = False) -> SimpleNamespace:
    explicit = {
        label: dict(values)
        for label, values in _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.items()
        if include_kontoguthaben or label != "Kontoguthaben"
    }
    return SimpleNamespace(
        sub_asset_class_assumptions_json=json.dumps(explicit),
        status="approved",
        committee_approved=1,
        jurisdiction="CH",
        equity_ch_return_bps=620,
        equity_intl_return_bps=700,
        bonds_chf_ig_return_bps=220,
        bonds_fx_hedged_return_bps=220,
        real_estate_ch_return_bps=450,
        alternatives_gold_return_bps=120,
        liquidity_return_bps=0,
        equity_ch_vol_bps=1450,
        equity_intl_vol_bps=1600,
        bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_vol_bps=430,
        real_estate_ch_vol_bps=820,
        alternatives_gold_vol_bps=1200,
        liquidity_vol_bps=10,
    )


def test_new_instrument_does_not_silently_expand_an_approved_cma_snapshot() -> None:
    resolved = _sub_asset_class_assumption_map(_approved_cma())
    assert "Kontoguthaben" not in resolved, resolved["Kontoguthaben"]


def test_inherited_code_default_is_not_claimed_as_cma_sub_asset_evidence() -> None:
    reasoning: list[str] = []
    reference = _build_sub_asset_class_assumption_reference(
        _SLEEVE, _approved_cma(), reasoning
    )
    assert len(reference) == 1
    item = reference[0]
    assert item["source"] != "CMA Sub-Asset-Class", item
    assert item["source"] in {
        "unapproved_code_default",
        "legacy_missing_unavailable",
    }, item
    assert item["approval_status"] == "not_approved"
    assert len(item["evidence_sha256"]) == 64
    # Zahlen unveraendert: weiterhin der Code-Default, nichts erfunden.
    default = _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Kontoguthaben"]
    assert item["expected_return_bps"] == default["expected_return_bps"]
    assert item["expected_volatility_bps"] == default["expected_volatility_bps"]
    assert len(reasoning) == 1
    assert "Kontoguthaben" in reasoning[0] and "Code-Default" in reasoning[0]
    assert item["evidence_sha256"][:12] in reasoning[0]


def test_model_map_still_computes_with_declared_code_default() -> None:
    """Rechenpfad unveraendert (kein strict-Abbruch, gleiche Kennzahl)."""
    cma = _approved_cma()
    assert "Kontoguthaben" in _sub_asset_class_model_map(cma)
    ret, vol = _sub_asset_class_metrics(
        "Kontoguthaben", "Liquiditaet", cma, {"liquidity": 999}, {"liquidity": 999}
    )
    default = _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS["Kontoguthaben"]
    assert (ret, vol) == (
        default["expected_return_bps"],
        default["expected_volatility_bps"],
    )


def test_cma_that_explicitly_carries_the_label_is_cma_evidence() -> None:
    """Positivkontrolle: fuehrt die CMA-Version die Zeile, ist sie Evidenz."""
    cma = _approved_cma(include_kontoguthaben=True)
    assert "Kontoguthaben" in _sub_asset_class_assumption_map(cma)
    reasoning: list[str] = []
    reference = _build_sub_asset_class_assumption_reference(_SLEEVE, cma, reasoning)
    assert reference[0]["source"] == "CMA Sub-Asset-Class"
    assert "approval_status" not in reference[0]
    assert reasoning == []
