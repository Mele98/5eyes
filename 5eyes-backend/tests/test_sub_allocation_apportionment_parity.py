r"""SUB-SPLIT-ROUNDING-001: eine kanonische Aufteilung fuer alle Sub-Allokationspfade.

Soll-Invariante (``services/sub_allocation_apportionment.py``): ein Bucket mit
``T`` bps wird nach Hamilton/Largest Remainder auf die Sleeves verteilt --
Summe exakt ``T``, nichtnegativ, ``|a_i - T*w_i/W| < 1``, groesserer Rest
schlaegt kleineren, gleiche Reste: groesseres Gewicht, dann Label. Direkter
Builder (deterministisch, House-Fallback, Manual Save, Retirement/Wealth),
Split-Normalisierung, Kanonisierung und stochastische Materialisierung
verwenden dieselbe Funktion; gleiche Quote + gleiche Praeferenzen ergeben
dieselbe Sub-Allokation.

Der erste Test ist der Audit-Reproducer
``test_2026_10_16_sub_split_apportionment_parity_adversarial.py``, unveraendert
bis auf das Auffinden des Backends (per Struktur statt Umgebungsvariable) und
ohne xfail.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if not (
    BACKEND_ROOT / "services" / "portfolio_engine_house_matrix.py"
).is_file():
    raise RuntimeError("Backend-Verzeichnis nicht gefunden")
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine_house_matrix import (  # noqa: E402
    _build_stochastic_sub_allocation_plan,
    _build_sub_allocations,
    _canonicalize_sub_allocation_mix,
    _materialize_sub_allocation_plan,
    _normalize_splits,
)
from services.sub_allocation_apportionment import apportion_bps  # noqa: E402


BUCKET_KEYS = (
    "equities",
    "bonds",
    "real_estate",
    "alternatives",
    "liquidity",
)


def _targets(equities_bps: int) -> dict[str, int]:
    return {key: equities_bps if key == "equities" else 0 for key in BUCKET_KEYS}


def _equity_weights(rows: list[dict]) -> dict[str, int]:
    return {
        str(row["sub_asset_class"]): int(row["target_weight_bps"])
        for row in rows
        if row["asset_class"] == "Aktien"
    }


# ---------------------------------------------------------------------------
# Audit-Reproducer (ohne xfail)
# ---------------------------------------------------------------------------


def test_identical_final_bucket_uses_one_canonical_apportionment_policy() -> None:
    """Deterministic/manual and stochastic paths must materialize identically.

    The default equity mix is 45/40/10/5 percent.  For a three-basis-point
    bucket the direct builder currently gives the final basis point to the
    last 5-percent sleeve, while the canonical materializer gives it to the
    largest fractional remainder.  Conservation alone therefore hides both a
    priority reversal and a path-dependent portfolio composition.
    """
    final_targets = _targets(3)
    direct = _equity_weights(_build_sub_allocations(final_targets, {}))

    canonical_plan = _build_sub_allocations(_targets(10_000), {})
    materialized = _equity_weights(
        _materialize_sub_allocation_plan(canonical_plan, final_targets)
    )

    assert sum(direct.values()) == sum(materialized.values()) == 3
    assert direct.get("Aktien Europa", 0) >= direct.get(
        "Aktien Schwellenlaender", 0
    ), direct
    assert direct == materialized, {
        "direct_deterministic_or_manual": direct,
        "canonical_stochastic_materialization": materialized,
    }


# ---------------------------------------------------------------------------
# Referenzfall + Oracle der Aufteilungsfunktion
# ---------------------------------------------------------------------------


def test_reference_case_default_equity_mix_three_bps():
    """45/40/10/5 auf 3 bps: Quoten 1.35/1.20/0.30/0.15 -> 2/1/0/0."""
    assert apportion_bps(3, [4500, 4000, 1000, 500], ["S", "G", "E", "EM"]) == [2, 1, 0, 0]


def _oracle(total: int, weights: list[int], labels: list[str]) -> list[int]:
    """Unabhaengige Hamilton-Zuteilung mit exakten Bruechen."""
    weight_sum = sum(weights)
    if weight_sum == 0 or total == 0:
        return [0] * len(weights)
    quotas = [Fraction(total * w, weight_sum) for w in weights]
    seats = [q.numerator // q.denominator for q in quotas]
    fracs = [q - s for q, s in zip(quotas, seats)]
    left = total - sum(seats)
    ranking = sorted(range(len(weights)), key=lambda i: (-fracs[i], -weights[i], labels[i], i))
    for i in ranking[:left]:
        seats[i] += 1
    return seats


@pytest.mark.parametrize("seed", range(25))
def test_seeded_apportionment_matches_oracle_and_invariants(seed):
    rng = np.random.default_rng(seed)
    for _ in range(200):
        n = int(rng.integers(1, 8))
        weights = [int(v) for v in rng.integers(0, 6000, size=n)]
        labels = [f"S{int(v)}" for v in rng.permutation(n)]
        total = int(rng.integers(0, 10001))
        got = apportion_bps(total, weights, labels)
        assert got == _oracle(total, weights, labels)
        assert all(a >= 0 for a in got)
        if sum(weights) > 0:
            assert sum(got) == total
            for a, w in zip(got, weights):
                assert abs(Fraction(a) - Fraction(total * w, sum(weights))) < 1


@pytest.mark.parametrize("seed", range(15))
def test_permutation_of_rows_does_not_change_label_result(seed):
    rng = np.random.default_rng(100 + seed)
    for _ in range(100):
        n = int(rng.integers(2, 7))
        weights = [int(v) for v in rng.choice([500, 1000, 1500, 2500, 4000], size=n)]
        labels = [f"Sleeve {i}" for i in range(n)]
        total = int(rng.integers(1, 50))
        base = dict(zip(labels, apportion_bps(total, weights, labels)))
        perm = rng.permutation(n)
        permuted = dict(zip(
            [labels[i] for i in perm],
            apportion_bps(total, [weights[i] for i in perm], [labels[i] for i in perm]),
        ))
        assert base == permuted


def test_larger_remainder_never_loses_to_list_position():
    # 5%-Sleeve vor dem 10%-Sleeve gelistet: der groessere Rest gewinnt trotzdem.
    assert apportion_bps(3, [4500, 4000, 500, 1000], ["S", "G", "EM", "E"]) == [2, 1, 0, 0]
    assert apportion_bps(4, [4500, 4000, 500, 1000], ["S", "G", "EM", "E"]) == [2, 2, 0, 0]
    assert apportion_bps(5, [4500, 4000, 500, 1000], ["S", "G", "EM", "E"]) == [2, 2, 0, 1]


def test_tie_break_is_weight_then_label():
    # Gleiche Reste, gleiches Gewicht -> Label aufsteigend, unabhaengig von der Position.
    assert apportion_bps(1, [5000, 5000], ["B", "A"]) == [0, 1]
    assert apportion_bps(1, [5000, 5000], ["A", "B"]) == [1, 0]
    # Gleiche Reste, verschiedenes Gewicht -> groesseres Gewicht zuerst.
    assert apportion_bps(1, [3000, 1000, 1000], ["Z", "A", "B"]) == [1, 0, 0]


@pytest.mark.parametrize("bad", [-1])
def test_invalid_total_is_rejected(bad):
    with pytest.raises(ValueError):
        apportion_bps(bad, [1], ["a"])


def test_invalid_weights_are_rejected():
    with pytest.raises(ValueError):
        apportion_bps(10, [1, -1], ["a", "b"])
    with pytest.raises(ValueError):
        apportion_bps(10, [1.5], ["a"])
    with pytest.raises(ValueError):
        apportion_bps(10, [1, 2], ["a"])


def test_zero_total_or_zero_weights_give_zeros():
    assert apportion_bps(0, [1, 2], ["a", "b"]) == [0, 0]
    assert apportion_bps(7, [0, 0], ["a", "b"]) == [0, 0]


def test_normalize_splits_uses_the_same_policy():
    splits = [("A", 5500, "r"), ("B", 3500, "r")]  # Summe 9000 nach Filter
    assert [w for _l, w, _r in _normalize_splits(splits)] == apportion_bps(
        10000, [5500, 3500], ["A", "B"],
    ) == [6111, 3889]


# ---------------------------------------------------------------------------
# Pfadparitaet: direkter Builder == Kanonisierung + Materialisierung
# ---------------------------------------------------------------------------


PREFS = {
    "default": {},
    "global": {"assetClasses": {"equitiesGeo": "Global"}},
    "europa": {"assetClasses": {"equitiesGeo": "Europa"}},
    "em_focus": {"assetClasses": {"equitiesGeo": "Schwellenlaender"}},
    "no_em": {"geo": {"noEm": True}},
    "smid": {"assetClasses": {"equitiesSmid": True}},
    "three_theme_tilts": {
        "assetClasses": {"equitiesGeo": "Schweiz Fokus"},
        "tilts": {"defense": "overweight", "fossil": "overweight", "tobacco": "overweight"},
    },
    "wide_alternatives": {
        "assetClasses": {"altsGold": True, "altsLiquidAlts": True, "altsHedge": True,
                         "altsPe": True, "altsCrypto": True},
    },
    "wide_bonds": {
        "assetClasses": {"bondsInvestmentGrade": True, "bondsHighYield": True, "bondsEmerging": True},
    },
    "hy_em_only": {
        "assetClasses": {"bondsInvestmentGrade": False, "bondsHighYield": True, "bondsEmerging": True},
    },
}


def _rows_by_key(rows):
    return {
        (row["asset_class"], row["sub_asset_class"]): (
            int(row["target_weight_bps"]), int(row["within_bucket_weight_bps"]),
        )
        for row in rows
    }


@pytest.mark.parametrize("prefs_key", sorted(PREFS))
def test_every_bucket_weight_direct_equals_materialized(prefs_key):
    """0..10'000 bps je Bucket: Zeilen, Gewichte und Mix bytegleich."""
    prefs = PREFS[prefs_key]
    try:
        plan = _canonicalize_sub_allocation_mix(
            _build_sub_allocations({k: 10000 for k in BUCKET_KEYS}, prefs)
        )
    except ValueError as exc:  # pragma: no cover - Profil im Katalog unzulaessig
        pytest.skip(str(exc))
    bad = []
    for weight in range(1, 10001):
        targets = {k: weight for k in BUCKET_KEYS}
        direct = _build_sub_allocations(dict(targets), prefs)
        materialized = _materialize_sub_allocation_plan(plan, targets)
        if _rows_by_key(direct) != _rows_by_key(materialized):
            bad.append(weight)
        sums: dict[str, int] = {}
        for row in direct:
            assert int(row["target_weight_bps"]) >= 0
            sums[row["asset_class"]] = sums.get(row["asset_class"], 0) + int(row["target_weight_bps"])
        assert set(sums.values()) == {weight}, (weight, sums)
    assert not bad, f"{len(bad)} Gewichte abweichend, erste: {bad[:5]}"


@pytest.mark.parametrize("prefs_key", ["default", "three_theme_tilts", "wide_bonds", "no_em"])
@pytest.mark.parametrize("seed", range(5))
def test_stochastic_plan_materializes_like_direct_builder(prefs_key, seed):
    """Plan aus dem stochastischen Pfad (Referenzquoten) == direkter Builder."""
    rng = np.random.default_rng(700 + seed)
    maximums = {k: int(v) for k, v in zip(BUCKET_KEYS, rng.integers(3000, 10001, size=5))}
    minimums = {k: 0 for k in BUCKET_KEYS}
    plan, _effective = _build_stochastic_sub_allocation_plan(
        targets={k: 2000 for k in BUCKET_KEYS},
        minimums=minimums,
        maximums=maximums,
        preferences=PREFS[prefs_key],
        max_illiquid_bps=None,
        reasoning=[],
    )
    for _ in range(50):
        raw = rng.dirichlet(np.ones(5)) * 10000
        targets = {k: min(int(v), maximums[k]) for k, v in zip(BUCKET_KEYS, raw)}
        materialized = [
            row for row in _materialize_sub_allocation_plan(plan, targets)
            if targets[_bucket_of(row)] > 0
        ]
        direct = _build_sub_allocations(dict(targets), PREFS[prefs_key])
        assert _rows_by_key(direct) == _rows_by_key(materialized), targets


_ASSET_TO_BUCKET = {
    "Aktien": "equities", "Obligationen": "bonds", "Immobilien": "real_estate",
    "Alternative": "alternatives", "Liquiditaet": "liquidity",
}


def _bucket_of(row) -> str:
    return _ASSET_TO_BUCKET[row["asset_class"]]


def test_zero_weight_sleeves_stay_as_context_rows_only_in_positive_buckets():
    rows = _build_sub_allocations(_targets(3), {})
    equities = {r["sub_asset_class"]: r["target_weight_bps"] for r in rows}
    assert equities == {
        "Aktien Schweiz": 2, "Aktien Global": 1,
        "Aktien Europa": 0, "Aktien Schwellenlaender": 0,
    }
    # Leere Buckets erzeugen im direkten Builder keine Zeilen.
    assert {r["asset_class"] for r in rows} == {"Aktien"}
