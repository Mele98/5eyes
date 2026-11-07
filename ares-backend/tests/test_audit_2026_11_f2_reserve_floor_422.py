"""F-2 (Pruefrunde #859): 422 bei systembedingter Liquiditaets-Untergrenze.

Vorher (gemessen in der Pruefrunde, beide Modi): Reserve 99 % des
Vermoegens, davon 3 % intern -> Untergrenze 50 % -> "Die Mindestquoten
verlangen zusammen 128.00 % ... Liquiditaet min. 50.00 % ... Bitte ... ein
Berater-Minimum senken". Ursache ist aber die Zielreserve. Jetzt nennt die
Meldung die Herkunft und gibt einen passenden Hinweis; bei Reserve in der
Hoehe des investierbaren Vermoegens weist sie auf den gesonderten Fall
"keine Strategiebasis" hin. Die Pruefung laeuft in beiden Modi direkt nach
dem Setzen der Untergrenze (raise_if_locked_targets_infeasible).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe  # noqa: E402
from services.portfolio_engine_house_matrix import (  # noqa: E402
    BandEnvelopeInfeasibleError,
    raise_if_locked_targets_infeasible,
)

MINIMUMS = {"equities": 6000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 5000}


@pytest.mark.parametrize(
    "source",
    ["zwingend vorzuhaltende Zielreserve"],  # Hausmatrix-Modus (E-1) und stochastischer Reserve-Floor
)
def test_reserve_floor_422_names_reserve_and_not_advisor_minimum(source):
    with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
        raise_if_locked_targets_infeasible(
            dict(MINIMUMS), dict(MINIMUMS), set(), bucket_labels=pe.BUCKET_LABELS,
            min_sources={"liquidity": source},
        )
    msg = str(exc_info.value)
    assert "Liquiditaets-Untergrenze von 50.00 % (Zielreserve)" in msg, msg
    assert "128.00 %" in msg, msg
    assert "nicht eine Berater-Vorgabe" in msg, msg
    assert "Berater-Minimum senken" not in msg, msg
    assert "keine Strategiebasis" in msg, msg


@pytest.mark.parametrize(
    "source", ["globale Mindestliquiditaet des Modells", "globale Liquiditaets-Untergrenze des Modells"],
)
def test_model_floor_422_names_model_floor(source):
    minimums = {**MINIMUMS, "equities": 9000, "liquidity": 200}
    with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
        raise_if_locked_targets_infeasible(
            dict(minimums), dict(minimums), set(), bucket_labels=pe.BUCKET_LABELS,
            min_sources={"liquidity": source},
        )
    msg = str(exc_info.value)
    assert "(Mindestliquidität des Modells)" in msg and "uebrigen Anlageklassen senken" in msg, msg


def test_advisor_or_house_minimum_source_is_left_to_existing_messages():
    raise_if_locked_targets_infeasible(
        dict(MINIMUMS), dict(MINIMUMS), set(), bucket_labels=pe.BUCKET_LABELS,
        min_sources={"liquidity": "Mindestquote"},
    )


def test_both_modes_call_the_check_with_the_floor_source():
    source = inspect.getsource(pe.generate_target_allocation)
    assert 'min_sources={"liquidity": "zwingend vorzuhaltende Zielreserve"}' in source  # stochastisch
    assert 'min_sources={"liquidity": liquidity_floor_source}' in source  # Hausmatrix (E-1)
