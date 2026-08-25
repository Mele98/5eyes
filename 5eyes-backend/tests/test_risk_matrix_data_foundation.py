"""Daten-Foundation-Guard für die Risk-Matrix (Stage 2 Vorbedingung).

Stage 2 der Stochastic Goal Engine (siehe
docs/planning/2026-05-23-stochastic-goal-engine-spec.md §1) verlangt eine
HARTE Risikobudget-Constraint aus HouseMatrix.max_risky_fraction_bps für den
Score-Bucket des Mandats + Portfolio-Risikogewichtung über
BuildingBlock.risky_fraction_bps. Damit das in JEDEM Fall — auch nach manuellen
Policy-Edits — fail-fast wird, muss die seed-/initialisierte Datenbasis ALLE
folgenden Bedingungen erfüllen:

1. HouseMatrix deckt Score-Buckets 1..10 lückenlos ab.
2. Jede HouseMatrix-Zeile hat max_risky_fraction_bps gesetzt (NOT NULL, > 0).
3. max_risky_fraction_bps ist monoton steigend mit dem Score-Bucket.
4. Alle 5 Asset-Klassen (Aktien/Obligationen/Immobilien/Alternative/Liquiditaet)
   haben mindestens einen aktiven BuildingBlock mit risky_fraction_bps gesetzt.
5. Liquiditaets-BuildingBlocks haben risky_fraction_bps == 0 (Definition von
   "risikolos" — andernfalls würde die Liquiditätsreserve in der
   Risikobudget-Berechnung als riskant zählen, was falsch wäre).

Dieser Test bewahrt vor stillen Daten-Lücken, die Stage 2 schwer-debuggbar
fallen lassen würden ("Keine HouseMatrix für Score X" mitten in einer
Beratungssitzung).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import BuildingBlock, HouseMatrix, OptimizerPolicy
from services.portfolio_engine import ensure_runtime_reference_data


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'risk_matrix.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_default_policy(session_factory):
    with session_factory() as s:
        ensure_runtime_reference_data(s, user_id="data-foundation-test")
        s.commit()
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).one()
        rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == policy.id,
                                           HouseMatrix.is_active == 1).all()
        bbs = s.query(BuildingBlock).filter(BuildingBlock.policy_id == policy.id,
                                            BuildingBlock.is_active == 1).all()
    return policy, rows, bbs


def test_house_matrix_covers_all_score_buckets_1_to_10(session_factory):
    """HouseMatrix muss Buckets 1..10 lückenlos abdecken — Stage 2 fail-fast
    bei fehlendem Bucket wäre sonst in jeder Beratung möglich."""
    _, rows, _ = _seed_default_policy(session_factory)
    covered = set()
    for r in rows:
        for bucket in range(int(r.score_from), int(r.score_to) + 1):
            covered.add(bucket)
    missing = set(range(1, 11)) - covered
    assert not missing, (
        f"HouseMatrix-Score-Buckets unvollständig nach ensure_runtime_reference_data: "
        f"fehlen {sorted(missing)} (vorhandene Ranges: "
        f"{sorted((int(r.score_from), int(r.score_to)) for r in rows)})"
    )


def test_house_matrix_max_risky_fraction_is_set_for_every_row(session_factory):
    """max_risky_fraction_bps darf nirgends NULL/0 sein — sonst kann Stage 2's
    Cap-Check (OD-A: strikt, kein Slack) das Profil nicht durchsetzen."""
    _, rows, _ = _seed_default_policy(session_factory)
    for r in rows:
        assert r.max_risky_fraction_bps is not None, (
            f"max_risky_fraction_bps ist NULL für HouseMatrix-Range "
            f"{r.score_from}-{r.score_to} ({r.profile_name})"
        )
        assert int(r.max_risky_fraction_bps) > 0, (
            f"max_risky_fraction_bps <= 0 für HouseMatrix-Range "
            f"{r.score_from}-{r.score_to}: {r.max_risky_fraction_bps}"
        )
        assert int(r.max_risky_fraction_bps) <= 10000, (
            f"max_risky_fraction_bps > 10000 (100%) für HouseMatrix-Range "
            f"{r.score_from}-{r.score_to}: {r.max_risky_fraction_bps}"
        )


def test_house_matrix_max_risky_monotonic_in_score(session_factory):
    """Höheres Risikoprofil ⇒ höheres oder gleiches max_risky_fraction. Sonst
    sind die Profil-Definitionen fachlich inkonsistent (Aktien-Profil hätte
    weniger Risikoraum als Defensiv-Profil)."""
    _, rows, _ = _seed_default_policy(session_factory)
    ranges_sorted = sorted(rows, key=lambda r: int(r.score_from))
    last_max = -1
    for r in ranges_sorted:
        cur = int(r.max_risky_fraction_bps)
        assert cur >= last_max, (
            f"max_risky_fraction nicht monoton: Range {r.score_from}-{r.score_to} "
            f"({r.profile_name}) hat {cur} bps, vorheriger Wert war {last_max} bps"
        )
        last_max = cur


def test_building_blocks_cover_all_five_asset_classes(session_factory):
    """Alle 5 Asset-Klassen brauchen mindestens 1 aktiven BuildingBlock — sonst
    kann compute_portfolio_risky_fraction_bps für die fehlende Klasse nicht
    rechnen (KeyError oder still 0)."""
    _, _, bbs = _seed_default_policy(session_factory)
    classes_with_bb = {bb.asset_class for bb in bbs}
    required = {"Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"}
    missing = required - classes_with_bb
    assert not missing, (
        f"Asset-Klassen ohne aktiven BuildingBlock: {sorted(missing)}"
    )


def test_building_blocks_have_risky_fraction_set(session_factory):
    """Jeder aktive BuildingBlock muss risky_fraction_bps gesetzt haben
    (auch wenn 0 — Liquidität)."""
    _, _, bbs = _seed_default_policy(session_factory)
    for bb in bbs:
        assert bb.risky_fraction_bps is not None, (
            f"risky_fraction_bps ist NULL für BuildingBlock "
            f"{bb.asset_class}/{bb.sub_asset_class}"
        )
        assert 0 <= int(bb.risky_fraction_bps) <= 10000, (
            f"risky_fraction_bps {bb.risky_fraction_bps} ausserhalb 0..10000 "
            f"für {bb.asset_class}/{bb.sub_asset_class}"
        )


def test_liquidity_building_blocks_are_risk_free(session_factory):
    """Liquiditäts-BBs müssen risky_fraction_bps == 0 haben — sie sind per
    Definition risikolos. Andernfalls würde die Liquiditätsreserve in der
    Risikobudget-Berechnung als riskant zählen — fachlich falsch."""
    _, _, bbs = _seed_default_policy(session_factory)
    liquidity_bbs = [bb for bb in bbs if bb.asset_class == "Liquiditaet"]
    assert liquidity_bbs, "Keine Liquiditäts-BuildingBlocks gefunden"
    for bb in liquidity_bbs:
        assert int(bb.risky_fraction_bps) == 0, (
            f"Liquiditäts-BuildingBlock {bb.sub_asset_class} hat "
            f"risky_fraction_bps={bb.risky_fraction_bps} — muss 0 sein (risikolos)"
        )
