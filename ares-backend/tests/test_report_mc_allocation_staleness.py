"""MC-CONTEXT-001 (Codex-Review PR #645): Report-Monte-Carlo fail-closed.

Befund: Nach einem neuen aktuellen Risikoprofil verweigert der kanonische
Allocation-Payload die alte Soll-Allokation, die Advisory-Report-MC-Sektion
publizierte aber weiter deren Gewichte unter dem NEUEN Risikoprofil-Horizont
(``data_pending=False``) -- und rechnete zudem mit der global aktuellen statt
der in der Allokation verankerten CMA.

Vertrag:
* derselbe Staleness-Preflight wie Payload/Depot-Check (Risikoprofil-Anker,
  Override nach Allokation, Input-Snapshot-Hash);
* bei Drift: leere Quantile, ``projection_status`` ``stale``/``blocked`` und
  eine Berater-Meldung mit "Strategie neu berechnen" -- Web und PDF zeigen
  keine Kurve;
* die CMA kommt aus ``allocation.capital_market_assumptions_id``; fehlt der
  Anker (Altbestand) oder die referenzierte CMA, wird blockiert statt still
  die aktuelle CMA einzusetzen;
* alle weiteren Report-Sektionen, die Werte der Allokation projizieren
  (Zielerreichung, Key-Metrics, Zielkompatibilitaet, Stress-Replay), folgen
  demselben Urteil.

Der erste Test ist der Codex-Reproducer
``docs/audits/reproducers/test_2026_10_18_pr645_horizon_snapshot_adversarial.py``
ohne ``xfail``.
"""
from __future__ import annotations

import datetime
import uuid

import pytest

from models.allocation import CapitalMarketAssumption, TargetAllocation
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.wealth import WealthPosition
from services.advisory_report import _build_monte_carlo_paths_section
import services.portfolio_engine as pe
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
)
from tests.test_sim_horizon_from_risk_profile_backend import (  # noqa: F401
    _seed_mandate,
    advisor_user,
    session_factory,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _replace_current_assessment(session_factory, mandate_id: str, advisor_id: str) -> str:
    new_id = str(uuid.uuid4())
    now = _now()
    fields = derive_current_risk_fields(
        q_income_points=2,
        q_obligations_points=3,
        q_savings_points=2,
        q_wealth_points=2,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    # Make the new assessment observably different while remaining valid.
    fields["investment_horizon_years"] = 25
    with session_factory() as session:
        old = session.query(RiskAssessment).filter(
            RiskAssessment.mandate_id == mandate_id,
            RiskAssessment.is_current == 1,
        ).one()
        old.is_current = 0
        session.add(
            RiskAssessment(
                id=new_id,
                mandate_id=mandate_id,
                version=int(old.version or 1) + 1,
                is_current=1,
                valid_from=now[:10],
                **fields,
                is_overridden=0,
                **CURRENT_RISK_SCHEMA_MARKERS,
                assessed_at=now,
                assessed_by=advisor_id,
                created_at=now,
                updated_at=now,
            )
        )
        add_current_risk_answers(session, new_id, now)
        session.commit()
    return new_id


def _generate(session_factory, mandate_id: str, advisor_id: str) -> TargetAllocation:
    with session_factory() as session:
        generated = pe.generate_target_allocation(
            session,
            session.get(Mandate, mandate_id),
            advisor_id,
            {"simulation": {"stressMultiplier": "1.0"}},
        )
        allocation = generated["target_allocation"]
        session.commit()
    return allocation


def _section(session_factory, mandate_id: str) -> dict:
    with session_factory() as session:
        return _build_monte_carlo_paths_section(
            session, session.get(Mandate, mandate_id)
        )


@pytest.fixture()
def house_matrix(monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")


# ---------------------------------------------------------------------------
# Codex-Reproducer (ohne xfail)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_report_mc_does_not_publish_old_allocation_under_new_risk_horizon(
    session_factory,
    advisor_user,
    monkeypatch,
):
    mandate_id = _seed_mandate(session_factory, advisor_user.id)
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")

    with session_factory() as session:
        generated = pe.generate_target_allocation(
            session,
            session.get(Mandate, mandate_id),
            advisor_user.id,
            {"simulation": {"stressMultiplier": "1.0"}},
        )
        old_assessment_id = generated["target_allocation"].based_on_assessment_id
        session.commit()
    new_assessment_id = _replace_current_assessment(
        session_factory, mandate_id, advisor_user.id
    )
    assert new_assessment_id != old_assessment_id

    # The canonical allocation payload path fails closed on this identity
    # mismatch before it publishes the stored strategy.
    with session_factory() as session:
        allocation = pe._current_target_allocation_or_none(session, mandate_id)
        current = pe._current_risk_assessment_or_none(session, mandate_id)
        assert allocation.based_on_assessment_id != current.id

    # The advisory report must follow the same gate, not recompute a new MC
    # chart with old weights and the new 25-year assessment horizon.
    with session_factory() as session:
        section = _build_monte_carlo_paths_section(
            session, session.get(Mandate, mandate_id)
        )
    assert section["horizon_years"] == 25
    assert section["data_pending"] is True
    assert section["p50"] == []
    assert "Strategie neu berechnen" in section["note"]


# ---------------------------------------------------------------------------
# Weitere Pflichtregressionen
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_stale_assessment_status_and_every_quantile_empty(
    session_factory, advisor_user, house_matrix
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    _replace_current_assessment(session_factory, mid, advisor_user.id)

    section = _section(session_factory, mid)
    assert section["projection_status"] == "stale"
    for key in ("p5", "p10", "p25", "p50", "p75", "p90", "time_axis"):
        assert section[key] == [], key
    assert "Risikoprofil" in section["note"]


@pytest.mark.timeout(60)
def test_identical_assessment_publishes_paths_with_payload_horizon(
    session_factory, advisor_user, house_matrix
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)

    section = _section(session_factory, mid)
    assert section["data_pending"] is False
    assert section["projection_status"] == "current"
    assert section["horizon_years"] == 15
    assert len(section["p50"]) == 16
    # Feature-off-Mandat: explizit "disabled", kein Cutoff (MORT-CHANNEL-001).
    assert section["mortality_mode"] == "disabled"
    assert section["mortality_cutoff_year_index"] is None


@pytest.mark.timeout(60)
def test_newer_global_cma_does_not_replace_allocation_snapshot_cma(
    session_factory, advisor_user, house_matrix
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    baseline = _section(session_factory, mid)
    assert baseline["data_pending"] is False

    # Neue, deutlich optimistischere globale CMA wird "aktuell".
    with session_factory() as s:
        old = s.get(CapitalMarketAssumption, allocation.capital_market_assumptions_id)
        old.is_current = 0
        s.flush()
        clone = CapitalMarketAssumption(**{
            col.key: getattr(old, col.key)
            for col in CapitalMarketAssumption.__table__.columns
        })
        clone.id = str(uuid.uuid4())
        clone.version = int(old.version or 1) + 1
        clone.is_current = 1
        _shift_returns(clone, 800)
        s.add(clone)
        s.commit()
        clone_id = clone.id

    after = _section(session_factory, mid)
    assert after["data_pending"] is False
    assert after["p50"] == baseline["p50"]
    assert after["p90"] == baseline["p90"]

    # Positivkontrolle: mit der neuen CMA waere die Kurve sichtbar anders --
    # die Gleichheit oben ist also kein Zufall unveraenderter Kennzahlen.
    from services.monte_carlo_paths import compute_quantile_paths

    with session_factory() as s:
        mandate = s.get(Mandate, mid)
        with_new_cma = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=baseline["initial_wealth_rappen"],
            horizon_years=baseline["horizon_years"],
            cma=s.get(CapitalMarketAssumption, clone_id),
        )
    assert with_new_cma["data_pending"] is False
    assert with_new_cma["p50"][-1] > baseline["p50"][-1]


def _shift_returns(cma, delta_bps: int) -> None:
    import json

    for col in CapitalMarketAssumption.__table__.columns:
        value = getattr(cma, col.key)
        if col.key.endswith("_return_bps") and isinstance(value, int):
            setattr(cma, col.key, value + delta_bps)

    def _walk(node):
        if isinstance(node, dict):
            return {
                k: (v + delta_bps if k == "expected_return_bps" and isinstance(v, int) else _walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(v) for v in node]
        return node

    raw = getattr(cma, "sub_asset_class_assumptions_json", None)
    if raw:
        cma.sub_asset_class_assumptions_json = json.dumps(_walk(json.loads(raw)))


@pytest.mark.timeout(60)
def test_missing_snapshot_cma_blocks_instead_of_using_current_cma(
    session_factory, advisor_user, house_matrix
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        old = s.get(CapitalMarketAssumption, allocation.capital_market_assumptions_id)
        old.is_current = 0
        old.deleted_at = _now()
        s.flush()
        clone = CapitalMarketAssumption(**{
            col.key: getattr(old, col.key)
            for col in CapitalMarketAssumption.__table__.columns
        })
        clone.id = str(uuid.uuid4())
        clone.version = int(old.version or 1) + 1
        clone.is_current = 1
        clone.deleted_at = None
        s.add(clone)
        s.commit()

    section = _section(session_factory, mid)
    assert section["data_pending"] is True
    assert section["projection_status"] == "blocked"
    assert section["p50"] == []
    assert "Strategie neu berechnen" in section["note"]


@pytest.mark.timeout(60)
def test_legacy_allocation_without_cma_anchor_is_quarantined(
    session_factory, advisor_user, house_matrix
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        row = s.get(TargetAllocation, allocation.id)
        row.capital_market_assumptions_id = None
        row.context_artifacts_required = 0
        s.commit()

    section = _section(session_factory, mid)
    assert section["data_pending"] is True
    assert section["projection_status"] == "blocked"
    assert section["p50"] == []
    assert "Strategie neu berechnen" in section["note"]


@pytest.mark.timeout(60)
def test_changed_inputs_invalidate_report_mc(session_factory, advisor_user, house_matrix):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    now = _now()
    with session_factory() as s:
        client_id = s.get(Mandate, mid).client_id
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client_id, label="Neues Depot",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=10000, alloc_bonds_bps=0, alloc_real_estate_bps=0,
            alloc_liquidity_bps=0, alloc_alternatives_bps=0, is_active=1,
            created_at=now, updated_at=now,
        ))
        s.commit()

    section = _section(session_factory, mid)
    assert section["data_pending"] is True
    assert section["projection_status"] == "stale"
    assert section["p50"] == []
    assert "Strategie neu berechnen" in section["note"]


# ---------------------------------------------------------------------------
# Alle Report-Sektionen, die Werte der Allokation projizieren
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_full_report_hides_every_allocation_projection_when_stale(
    session_factory, advisor_user, house_matrix
):
    from services.advisory_report import compute_advisory_report

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        fresh = compute_advisory_report(s, s.get(Mandate, mid))
    assert fresh["goal_based_investing"]["monte_carlo_paths"]["data_pending"] is False
    assert fresh["ausgangslage"]["key_metrics"]["risky_fraction_bps"] is not None

    _replace_current_assessment(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        report = compute_advisory_report(s, s.get(Mandate, mid))

    gbi = report["goal_based_investing"]
    mc = gbi["monte_carlo_paths"]
    assert mc["data_pending"] is True
    assert mc["projection_status"] == "stale"
    assert mc["p50"] == []
    assert gbi["target_allocation_stale"] is True
    assert "Strategie neu berechnen" in gbi["staleness_hinweis"]
    assert gbi["plan_solvency"] is None
    assert gbi["goal_achievement_score_bps"] == 0
    for goal in gbi["goals"]:
        assert goal["probability_bps"] is None
        assert goal["status"] == "data_pending"

    key_metrics = report["ausgangslage"]["key_metrics"]
    assert all(value is None for value in key_metrics.values()), key_metrics

    stress = report["stress_replay"]
    assert stress["data_pending"] is True
    assert stress["scenarios"] == []
    assert stress["weights_bps"] == {}
    assert "Strategie neu berechnen" in stress["note"]

    # Sektionen 7/8/13 (bestehende Staleness) und 11/17 urteilen gleich.
    assert report["building_blocks"]["target_allocation_stale"] is True


@pytest.mark.timeout(120)
def test_pdf_goals_section_renders_hint_instead_of_chart_when_stale(
    session_factory, advisor_user, house_matrix
):
    from services.advisory_report import compute_advisory_report
    from services.pdf.documents.advisory_report import _build_goals_flowables
    from services.pdf.documents.advisory_report import make_advisory_styles

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    _replace_current_assessment(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        report = compute_advisory_report(s, s.get(Mandate, mid))

    from reportlab.graphics.shapes import Drawing
    from reportlab.platypus import Paragraph

    flowables = _build_goals_flowables(report["goal_based_investing"], make_advisory_styles())
    assert not any(isinstance(f, Drawing) for f in flowables)
    texts = " ".join(f.getPlainText() for f in flowables if isinstance(f, Paragraph))
    assert "Strategie neu berechnen" in texts
