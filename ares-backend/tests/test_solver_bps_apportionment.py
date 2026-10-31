"""SOLVER-BPS-APPORTIONMENT-001 (Kontrollrunde 2026-09-28,
docs/audits/2026-09-23-solver-goal-maximization-and-publication-integrity-
audit.md): `_weights_to_bps_dict()` rundete jeden Bucket einzeln und gab die
gesamte Restsumme immer dem groessten Gewicht -- unabhaengig davon, ob dieser
Bucket bereits an seiner Bounds-Obergrenze lag. Ein kontinuierlich zulaessiger
Kandidat an einer 50%-Aktien-Cap-Grenze wurde dadurch zu 5.001 Aktien-bps
gerundet und vom nachgelagerten Post-Round-Check faelschlich als
`diverged_infeasible` verworfen, obwohl die streng naehere Verteilung
5000/1750/999/999/1252 exakt 10.000 bps summiert und alle Constraints
erfuellt.

Reiner Unit-Test der Rundungsfunktion (kein voller Solver-Lauf noetig)."""
from __future__ import annotations

import numpy as np

import services.optimizer.solver as solver_module
from services.optimizer.constraints import is_feasible
from services.optimizer.scenario_engine import BUCKET_ORDER


def test_argmax_remainder_would_exceed_cap_but_constraint_aware_apportionment_fits():
    """Exakte Audit-Repro: continuous-feasible Kandidat an der 50%-Aktien-
    Cap. Mit bounds= erhaelt equities die Rundungsdifferenz NICHT, weil es
    bereits an seiner Obergrenze liegt; ein anderer Bucket mit Spielraum
    (hier liquidity) bekommt den Rest stattdessen."""
    bounds = [(0.0, 0.50), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
    weights = np.array([0.50004, 0.174996, 0.0999133, 0.0999133, 0.1251134])

    bps = solver_module._weights_to_bps_dict(weights, bounds=bounds)
    assert sum(bps.values()) == 10000
    assert bps["equities"] == 5000
    assert bps["liquidity"] == 1252

    rounded_w = solver_module._trusted_weights_bps_to_array(bps)
    feasible, reasons = is_feasible(rounded_w, bounds=bounds, constraints=[])
    assert feasible, reasons


def test_without_bounds_old_argmax_behaviour_is_preserved_for_back_compat():
    """Ruft jemand `_weights_to_bps_dict()` ohne bounds auf (z.B. ein noch
    nicht umgestellter externer Caller), bleibt exakt das alte Verhalten
    erhalten -- inklusive der Cap-Verletzung, die dieser Test bewusst NICHT
    behebt (Rueckwaertskompatibilitaet ist hier explizit gewuenscht)."""
    weights = np.array([0.50004, 0.174996, 0.0999133, 0.0999133, 0.1251134])
    bps = solver_module._weights_to_bps_dict(weights)
    assert sum(bps.values()) == 10000
    assert bps["equities"] == 5001


def test_sum_is_always_exactly_10000_across_random_weight_vectors():
    rng = np.random.default_rng(42)
    bounds = [(0.0, 1.0)] * len(BUCKET_ORDER)
    for _ in range(200):
        raw = rng.uniform(0.0, 1.0, size=len(BUCKET_ORDER))
        weights = raw / raw.sum()
        bps = solver_module._weights_to_bps_dict(weights, bounds=bounds)
        assert sum(bps.values()) == 10000
        assert all(v >= 0 for v in bps.values())


def test_never_exceeds_a_tight_upper_bound_when_a_feasible_apportionment_exists():
    """Fuzzt gegen eine harte 30%-Cap auf 'equities': die Rundung darf diese
    Cap nie verletzen, solange ein anderer Bucket noch Spielraum hat."""
    rng = np.random.default_rng(7)
    bounds = [(0.0, 0.30), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
    for _ in range(200):
        eq = rng.uniform(0.29, 0.30)
        rest = 1.0 - eq
        raw_rest = rng.uniform(0.0, 1.0, size=4)
        rest_weights = raw_rest / raw_rest.sum() * rest
        weights = np.array([eq, *rest_weights])
        bps = solver_module._weights_to_bps_dict(weights, bounds=bounds)
        assert sum(bps.values()) == 10000
        assert bps["equities"] <= 3000


def test_pathological_bounds_with_no_room_falls_back_without_crashing():
    """Wenn wirklich kein Bucket mehr Spielraum hat (alle exakt an ihrer
    Obergrenze), darf die Funktion nicht crashen -- der nachgelagerte
    is_feasible()-Post-Round-Check faengt eine daraus resultierende echte
    Verletzung ohnehin korrekt als diverged_infeasible ab."""
    bounds = [(0.0, 0.2), (0.0, 0.2), (0.0, 0.2), (0.0, 0.2), (0.0, 0.2)]
    weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2]) + np.array(
        [1e-6, -1e-6, 1e-6, -1e-6, 0.0]
    )
    bps = solver_module._weights_to_bps_dict(weights, bounds=bounds)
    assert sum(bps.values()) == 10000
