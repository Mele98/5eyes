"""Round 46 red test — Erweiterung von AB-MODEL-001.

Audit-Fund (2026-10-04-house-matrix-policy-constraint-and-retirement-basis-
integrity-audit.md, nicht in diesem Repo committed): Das Policy-A/B-
Backtest-Feature (`services/backtest_ab.py::run_ab_backtest` ->
`_evaluate_policy`) berechnet Bucket-Gewichte, Risk-Metriken (Return/Vol/
Sharpe/TER) und alle Stress-Replays auf Basis der ROHEN HouseMatrix-
`*_target_bps`-Werte (`_baseline_target_bands()`), OHNE sie wie im echten
Allokations-Pfad (`generate_target_allocation`, siehe `_rebalance_to_total()`
-Aufrufe in `services/portfolio_engine.py` Zeilen 3724/3803/3892/5982) auf
die EFFEKTIVEN (durch Policy-Caps ggf. verschaerften) Min/Max-Bands zu
klemmen.

Reproduktion hier: Policy B bekommt ein `max_alternatives_bps`, das UNTER
dem HouseMatrix-`alt_target_bps` fuer den betroffenen Score-Bucket liegt.
`_baseline_target_bands()` berechnet daraus korrekt einen engeren
`bands["alternatives"]["max_bps"]` -- aber `targets["alternatives"]` bleibt
der rohe (zu hohe) HouseMatrix-Wert, weil `_evaluate_policy()` NIE
`_rebalance_to_total()` (oder irgendeine andere Klemm-Operation) aufruft,
bevor es `targets` als `weights_bps` zurueckgibt und an `_expected_metrics`
sowie `compute_stress_for_weights` weiterreicht.

Ergebnis: Das A/B-Vergleichs-Panel zeigt eine Allokation (inkl. Risk-
Metriken und Stress-Verlust-Zahlen) fuer Policy B, die die eigene
Policy-B-Bandbreite verletzt -- eine Allokation, die das System in der
echten Portfolio-Generierung NIE zulassen wuerde.

Gewuenschtes Verhalten (heute XFAIL): `_evaluate_policy()` muss die
Rueckgabe-Gewichte (und alles, was darauf aufbaut: Metriken, Stress-
Szenarien) auf Basis der per `_rebalance_to_total(targets, minimums,
maximums)` geklemmten EFFEKTIVEN Allokation berechnen, nicht auf Basis der
rohen `targets`.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date
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
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.tenant  # noqa: F401
configure_mappers()

from models.allocation import HouseMatrix, OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from services.backtest_ab import run_ab_backtest
from services.portfolio_engine import (
    _baseline_target_bands,
    _expected_metrics,
    _rebalance_to_total,
    ensure_runtime_reference_data,
)
from services.backtest_stress import compute_stress_for_weights


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ab_raw_target_outside_band.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_assessment(session_factory):
    """Mandat + Risikoprofil, das auf Score-Bucket 8 ("Wachstumsorientiert")
    faellt -- identischer Fixture-Aufbau wie tests/test_backtest_ab.py, damit
    das Score->Bucket-Mapping bereits verifiziert bekannt ist (final_score_x10
    = 80 -> score_bucket 8, Profil "Wachstumsorientiert" mit
    alt_target_bps=600 / alt_max_bps=1000, siehe
    services/portfolio_engine.py _ensure_runtime_reference_data_ch defaults).
    """
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-abraw-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today().isoformat()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv ABRaw", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Test", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=today,
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Dynamisch",
            risk_capacity_score_x10=100,
            investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=80,
            final_score_x10=80, final_profile="Wachstumsorientiert",
            is_overridden=0,
            knowledge_services_json="{}", knowledge_instruments_json="{}",
            income_sources_json='["Berufliche Taetigkeit"]',
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q, label, points in [
            (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
            (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
            (3, "CHF 12'000 bis 20'000", 3),
            (4, "Herkunft: Berufliche Taetigkeit", 0),
            (5, "CHF 3'000 bis 5'000", 3),
            (6, "CHF 1'000'000 bis 2'000'000", 9),
            (7, "25 bis 50 %", 9),
            (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
            (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
            (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
            (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
        ]:
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points, created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, mid


def _default_policy_id(session_factory) -> str:
    with session_factory() as s:
        p = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        return p.id


def _create_alt_capped_policy(session_factory, base_policy_id: str, *, max_alternatives_bps: int) -> str:
    """Klont die Default-Policy + ihre HouseMatrix-Rows 1:1, setzt aber ein
    verschaerftes `max_alternatives_bps`, das UNTER dem HouseMatrix-
    `alt_target_bps` des Ziel-Score-Buckets liegt. Damit entsteht garantiert
    ein roher Zielwert ausserhalb der eigenen effektiven Policy-Band."""
    suffix = str(uuid.uuid4())[:6]
    now = _now()
    new_id = str(uuid.uuid4())
    with session_factory() as s:
        original = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == base_policy_id).first()
        rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == original.id).all()
        s.add(OptimizerPolicy(
            id=new_id, policy_name=f"AltCapped-{suffix}", version=1, is_current=0,
            valid_from=now, optimizer_engine=original.optimizer_engine,
            max_real_estate_bps=original.max_real_estate_bps,
            max_alternatives_bps=max_alternatives_bps,
            min_liquidity_bps=original.min_liquidity_bps,
            fee_model_json=original.fee_model_json, notes="Test-AltCapped",
            created_by=original.created_by, created_at=now, updated_at=now,
        ))
        for r in rows:
            s.add(HouseMatrix(
                id=str(uuid.uuid4()), policy_id=new_id,
                score_from=r.score_from, score_to=r.score_to,
                profile_name=r.profile_name,
                liq_min_bps=r.liq_min_bps, liq_target_bps=r.liq_target_bps, liq_max_bps=r.liq_max_bps,
                bonds_min_bps=r.bonds_min_bps, bonds_target_bps=r.bonds_target_bps, bonds_max_bps=r.bonds_max_bps,
                equity_min_bps=r.equity_min_bps, equity_target_bps=r.equity_target_bps, equity_max_bps=r.equity_max_bps,
                real_estate_min_bps=r.real_estate_min_bps, real_estate_target_bps=r.real_estate_target_bps, real_estate_max_bps=r.real_estate_max_bps,
                alt_min_bps=r.alt_min_bps, alt_target_bps=r.alt_target_bps, alt_max_bps=r.alt_max_bps,
                equity_minimum_bps=r.equity_minimum_bps,
                max_risky_fraction_bps=r.max_risky_fraction_bps,
                is_active=1, created_at=now, updated_at=now,
            ))
        s.commit()
    return new_id


@pytest.mark.xfail(
    strict=True,
    reason="AB-MODEL-001 — round 46 red test, see audit "
           "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md "
           "(not committed in this repo)",
)
def test_ab_backtest_uses_effective_band_not_raw_target_outside_it(session_factory):
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_a_id = _default_policy_id(session_factory)

    # Policy B: identische HouseMatrix, aber max_alternatives_bps=200 --
    # unter dem HouseMatrix alt_target_bps=600 fuer Score-Bucket 8
    # ("Wachstumsorientiert", siehe _ensure_runtime_reference_data_ch).
    policy_b_id = _create_alt_capped_policy(session_factory, policy_a_id, max_alternatives_bps=200)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_ab_backtest(s, mandate, policy_a_id, policy_b_id)

        # Sanity: die HouseMatrix fuer Policy B liefert tatsaechlich einen
        # rohen alternatives-Zielwert, der die eigene (verschaerfte)
        # effektive Policy-Band sprengt. Falls diese Annahme je nicht mehr
        # zutrifft, ist der Testaufbau zu korrigieren (nicht die Assertion
        # darunter zu entfernen).
        policy_b = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_b_id).first()
        hm_row = s.query(HouseMatrix).filter(
            HouseMatrix.policy_id == policy_b_id,
            HouseMatrix.score_from <= result["score_bucket"],
            HouseMatrix.score_to >= result["score_bucket"],
        ).first()
        assert int(hm_row.alt_target_bps) > int(policy_b.max_alternatives_bps), (
            "Testaufbau ungueltig: roher alt_target_bps liegt nicht ausserhalb "
            "der verschaerften Policy-B-Band — Fixture anpassen."
        )

    view_b = result["policy_b"]
    effective_max_alt = view_b["bands"]["alternatives"]["max_bps"]

    # Bestaetigung des HEUTIGEN (fehlerhaften) Verhaltens: der A/B-Vergleich
    # zeigt fuer Policy B ein alternatives-Gewicht, das die vom A/B-Modul
    # selbst ausgewiesene effektive Max-Band sprengt.
    assert view_b["weights_bps"]["alternatives"] > effective_max_alt, (
        "Erwartung des heutigen (fehlerhaften) Zustands nicht erfuellt: "
        "weights_bps sollte den rohen, bandueberschreitenden Zielwert zeigen."
    )

    # GEWUENSCHTES Verhalten: _evaluate_policy() haette die Gewichte (und
    # alles Abgeleitete: Metriken, Stress-Szenarien) auf Basis der EFFEKTIV
    # geklemmten Allokation (wie im echten Allokations-Pfad via
    # _rebalance_to_total()) berechnen muessen, nicht auf Basis der rohen,
    # bandueberschreitenden HouseMatrix-Targets.
    with session_factory() as s:
        policy_b_db = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_b_id).first()
        hm_row_db = s.query(HouseMatrix).filter(
            HouseMatrix.policy_id == policy_b_id,
            HouseMatrix.score_from <= result["score_bucket"],
            HouseMatrix.score_to >= result["score_bucket"],
        ).first()
        raw_targets, minimums, maximums = _baseline_target_bands(hm_row_db, policy_b_db)
    effective_weights = _rebalance_to_total(raw_targets, minimums, maximums)

    assert view_b["weights_bps"] == effective_weights, (
        "A/B-Modul muss die EFFEKTIVE (geklemmte) Allokation als weights_bps "
        "zurueckgeben, nicht die rohen, ausserhalb der Policy-Band liegenden "
        f"HouseMatrix-Targets. Erhalten: {view_b['weights_bps']}, "
        f"erwartet (effektiv): {effective_weights}"
    )

    # Die Stress-Szenarien muessen auf Basis derselben effektiven Gewichte
    # berechnet sein wie die Metriken -- nicht auf Basis der rohen Targets.
    expected_stress = compute_stress_for_weights(effective_weights)
    expected_by_id = {sc["id"]: sc for sc in expected_stress}
    for sc in view_b["stress_scenarios"]:
        expected = expected_by_id[sc["id"]]
        assert sc["cumulative_return_bps"] == expected["cumulative_return_bps"], (
            f"Stress-Szenario {sc['id']!r} fuer Policy B basiert nicht auf der "
            "effektiven (geklemmten) Allokation."
        )
