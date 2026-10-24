"""MANUAL-SAVE-DEADEND-001: der manuelle Speicherpfad der Soll-Allokation.

``POST /mandates/{id}/target-allocation`` (React-AllocationEditor) schrieb
seit CERT-TA-WRITE-LIFECYCLE-001 einen ``manual_override_v1``-Datensatz, den
``_verified_persisted_allocation_context`` nie akzeptierte:

* ``active_method="manual_override"`` ohne passende ``optimization_method``-
  Spalte, ``engine_version`` ausserhalb {stochastic_core_v1, v2}, kein
  ``risky_fraction_per_bucket_bps``, ein Context-Hash anderer Form und ein
  ``input_snapshot_hash`` aus den Targets statt aus Vermoegen/Cashflows/Zielen.
* Die vorherige (gueltige) Engine-Allokation war da bereits auf
  ``is_current=0`` gesetzt -- Payload, Empfehlung, Finalisierung und
  Strategie-PDFs scheiterten, bis der Berater neu generierte. Selbst das
  identische Wiederspeichern der Engine-Targets endete in
  "409 Persistierte aktive Optimierungsmethode widerspricht der
  TargetAllocation-Spalte".
* Bandbreiten wurden ungeprueft uebernommen; 100 % Aktien fuer ein
  Score-3-Profil wurde mit risky 8636 > Budget 4500 als aktuell gespeichert.
  Ohne Begruendung und mit einem Audit-Eintrag ohne alte/neue Werte.

Vertrag nach dem Fix:
A) Ein manueller Datensatz ist ueber denselben Verifier lad-, empfehl- und
   finalisierbar; sein input_snapshot_hash veraltet mit dem Vermoegen.
B) Risky Fraction > Risikobudget -> 409, nichts aendert sich. Bandbreiten
   ausserhalb der Hausmatrix-Zeile -> Warnung + Begruendung, kein Abbruch.
C) Begruendung Pflicht; Audit-Log mit alten -> neuen Targets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: F401,E402
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
from models import tenant as _tenant  # noqa: F401,E402

configure_mappers()

import routers.allocation as allocation_router  # noqa: E402
from models.allocation import HouseMatrix, TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from schemas.allocation import TargetAllocationCreate  # noqa: E402
from services.foundation_example import (  # noqa: E402
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)
from services.portfolio_engine import (  # noqa: E402
    _verified_persisted_allocation_context,
    build_recommendation_payload_from_run,
    generate_recommendation_run,
)

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
REASON = (
    "Kunde wuenscht nach ausfuehrlichem Gespraech eine leicht angepasste "
    "Gewichtung der Anlageklassen."
)


@pytest.fixture()
def SF(tmp_path, monkeypatch):
    # Produktions-Modus: der Fehler trat genau dort auf.
    monkeypatch.setattr(allocation_router.settings, "optimizer_mode", "stochastic")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'manual_save.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    yield factory
    engine.dispose()


def _seed(s) -> tuple[Mandate, User]:
    adv = User(
        id="advisor-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
    )
    s.add(adv)
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    mandate = s.query(Mandate).filter(
        Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER
    ).one()
    return mandate, adv


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _current(s, mandate_id) -> TargetAllocation:
    return s.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).one()


def _assessment(s, mandate_id) -> RiskAssessment:
    return s.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
    ).one()


def _body_from(ta, assessment_id, *, reason=REASON, **overrides):
    kw = {}
    for b in BUCKETS:
        kw[f"target_{b}_bps"] = int(getattr(ta, f"target_{b}_bps"))
        kw[f"band_{b}_min_bps"] = int(getattr(ta, f"band_{b}_min_bps"))
        kw[f"band_{b}_max_bps"] = int(getattr(ta, f"band_{b}_max_bps"))
    kw.update(overrides)
    if reason is not None:
        kw["override_reason"] = reason
    # ALLOC-EDITOR-STALE-001: der Editor bearbeitet ``ta`` -> Vorgaenger-Token.
    kw.setdefault("expected_current_allocation_id", ta.id)
    kw.setdefault("expected_current_allocation_version", int(ta.version))
    return TargetAllocationCreate(
        policy_id=ta.policy_id, based_on_assessment_id=assessment_id, **kw,
    )


def _verify(ta):
    targets = {b: int(getattr(ta, f"target_{b}_bps")) for b in BUCKETS}
    minimums = {b: int(getattr(ta, f"band_{b}_min_bps")) for b in BUCKETS}
    maximums = {b: int(getattr(ta, f"band_{b}_max_bps")) for b in BUCKETS}
    return _verified_persisted_allocation_context(
        ta, targets=targets, minimums=minimums, maximums=maximums,
    )


def _shifted_targets(engine_ta) -> dict:
    """Leicht verschobene, aber budget-konforme Targets: 1 Prozentpunkt von
    Aktien nach Liquiditaet (senkt die Risky Fraction), Baender passend
    erweitert."""
    eq = int(engine_ta.target_equities_bps)
    liq = int(engine_ta.target_liquidity_bps)
    shift = 100 if eq >= 100 else 0
    return {
        "target_equities_bps": eq - shift,
        "target_liquidity_bps": liq + shift,
        "band_equities_min_bps": min(int(engine_ta.band_equities_min_bps), eq - shift),
        "band_liquidity_max_bps": max(int(engine_ta.band_liquidity_max_bps), liq + shift),
    }


# ---------------------------------------------------------------------------
# A) Ein manueller Datensatz bleibt ein vollwertiger, verifizierbarer Anker.
# ---------------------------------------------------------------------------


def test_identical_manual_resave_is_reloadable_via_same_verifier(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        allocation_router.get_current_allocation_payload(mandate.id, db=s, current_user=adv)

        manual = allocation_router.create_target_allocation(
            mandate.id, _body_from(engine_ta, aid), _request(), db=s, current_user=adv,
        )
        assert manual.is_current == 1 and manual.id != engine_ta.id
        assert manual.optimization_method == "manual_override"
        assert manual.optimization_status == "manual"

        sub_allocations, constraints = _verify(manual)
        assert sub_allocations, "manueller Datensatz muss Sub-Allokationen tragen"
        assert constraints["engine_version"] == "manual_override_v1"
        assert set(constraints["risky_fraction_per_bucket_bps"]) == set(BUCKETS)
        assert constraints["manual_override"]["reason"] == REASON
        # Identisches Wiederspeichern: dieselben Eingaben wie Generate ->
        # derselbe Input-Snapshot wie die Engine-Allokation.
        assert manual.input_snapshot_hash == engine_ta.input_snapshot_hash
        # Kein neues Risiko gegenueber der Engine-Allokation.
        assert manual.risky_fraction_bps_at_generation == engine_ta.risky_fraction_bps_at_generation

        try:
            payload = allocation_router.get_current_allocation_payload(
                mandate.id, db=s, current_user=adv,
            )
        except HTTPException as exc:  # pragma: no cover - Fehlerdiagnose
            pytest.fail(f"Manueller Datensatz nicht ladbar: {exc.status_code} {exc.detail}")
        got = {row["band_min_bps"]: None for row in payload["buckets"]}
        assert got  # Payload vollstaendig aufgebaut
        reloaded = [row["target_weight_bps"] for row in payload["buckets"]]
        assert reloaded == [int(getattr(engine_ta, f"target_{b}_bps")) for b in BUCKETS]
        assert payload["model_basis"]["optimization"]["basis_id"] == "manual_override_v1"
        assert any(REASON in str(line) for line in payload["reasoning"])


def test_changed_manual_save_supports_recommendation_and_finalization(SF):
    from routers.review import _validate_recommendation_for_finalization

    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        manual = allocation_router.create_target_allocation(
            mandate.id,
            _body_from(engine_ta, aid, **_shifted_targets(engine_ta)),
            _request(), db=s, current_user=adv,
        )
        _verify(manual)
        allocation_router.get_current_allocation_payload(mandate.id, db=s, current_user=adv)

        result = generate_recommendation_run(
            db=s, mandate=mandate, user_id=adv.id, preferences=None,
            target_allocation_id=manual.id, depot_bank=mandate.depot_bank,
        )
        run = result["run"]
        assert run.target_allocation_id == manual.id
        build_recommendation_payload_from_run(
            db=s, mandate=mandate, run=run, user_id=adv.id, preferences=None,
        )
        errors, _warnings = _validate_recommendation_for_finalization(s, mandate, run)
        context_errors = [
            e for e in errors
            if "Allocation-Kontext" in e or "Soll-Allokation" in e
        ]
        assert context_errors == [], errors

        # Strategie-PDF-Daten laufen ueber denselben Rebuild-Pfad.
        from routers.pdf_reports import _build_anlagestrategie_data

        strategy = _build_anlagestrategie_data(mandate, s)
        assert sum(int(v or 0) for v in strategy.target_allocation_bps.values()) == 10000
        assert int(manual.target_equities_bps) in {
            int(v or 0) for v in strategy.target_allocation_bps.values()
        }


def test_manual_record_goes_stale_when_wealth_changes(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        allocation_router.create_target_allocation(
            mandate.id, _body_from(engine_ta, aid), _request(), db=s, current_user=adv,
        )
        s.commit()
        position = s.query(WealthPosition).filter(
            WealthPosition.client_id == mandate.client_id,
            WealthPosition.deleted_at.is_(None),
            WealthPosition.assignment == "Beratungsvermögen",
        ).first()
        assert position is not None
        position.current_value_rappen = int(position.current_value_rappen or 0) + 5_000_000
        s.commit()
        with pytest.raises(HTTPException) as exc:
            allocation_router.get_current_allocation_payload(mandate.id, db=s, current_user=adv)
        assert exc.value.status_code == 409
        assert "veraltet" in str(exc.value.detail)


def test_verifier_rejects_tampered_manual_records(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        manual = allocation_router.create_target_allocation(
            mandate.id, _body_from(engine_ta, aid), _request(), db=s, current_user=adv,
        )
        _verify(manual)

        # (1) Methoden-Spalte leer (= Format der manuellen Datensaetze vor
        #     diesem Fix) -> klare Ablehnung mit Handlungsanweisung.
        original_method = manual.optimization_method
        manual.optimization_method = None
        with pytest.raises(ValueError, match="aelteren, nicht verifizierbaren Format"):
            _verify(manual)
        manual.optimization_method = original_method

        # (2) Engine-Version gegen Methode tauschen (stochastische Version mit
        #     manueller Methode) -> Ablehnung, auch bei neu gerechnetem Hash.
        constraints = json.loads(manual.effective_constraints_json)
        constraints["engine_version"] = "stochastic_core_v2"
        manual.effective_constraints_json = json.dumps(constraints, sort_keys=True)
        with pytest.raises(ValueError):
            _verify(manual)

        # (3) manuelle Version ohne Begruendung -> Ablehnung.
        constraints["engine_version"] = "manual_override_v1"
        constraints["manual_override"] = {**constraints["manual_override"], "reason": "  "}
        manual.effective_constraints_json = json.dumps(constraints, sort_keys=True)
        with pytest.raises(ValueError):
            _verify(manual)

        # (4) eine Engine-Allokation darf sich nicht als manuell ausgeben.
        constraints = json.loads(engine_ta.effective_constraints_json)
        constraints["engine_version"] = "manual_override_v1"
        engine_ta.effective_constraints_json = json.dumps(constraints, sort_keys=True)
        with pytest.raises(ValueError):
            _verify(engine_ta)


# ---------------------------------------------------------------------------
# B) Risikobudget hart, Hausmatrix-Bandbreiten als Warnung.
# ---------------------------------------------------------------------------


def _all_equity_body(ta, assessment_id, reason=REASON):
    kw = {f"target_{b}_bps": 0 for b in BUCKETS}
    kw["target_equities_bps"] = 10000
    for b in BUCKETS:
        kw[f"band_{b}_min_bps"] = 0
        kw[f"band_{b}_max_bps"] = 10000
    if reason is not None:
        kw["override_reason"] = reason
    kw["expected_current_allocation_id"] = ta.id
    return TargetAllocationCreate(
        policy_id=ta.policy_id, based_on_assessment_id=assessment_id, **kw,
    )


def test_over_budget_manual_save_is_rejected_and_nothing_changes(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        ra = _assessment(s, mandate.id)
        ra.is_overridden = 1
        ra.override_score_x10 = 30
        ra.override_profile = "Defensiv"
        ra.override_reason = "Kunde wuenscht nach Gespraech defensive Ausrichtung"
        s.commit()
        engine_ta = _current(s, mandate.id)
        engine_id = engine_ta.id
        count_before = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id
        ).count()

        with pytest.raises(HTTPException) as exc:
            allocation_router.create_target_allocation(
                mandate.id, _all_equity_body(engine_ta, ra.id), _request(),
                db=s, current_user=adv,
            )
        assert exc.value.status_code == 409
        detail = str(exc.value.detail)
        assert "Risikobudget" in detail and "45.00" in detail

        s.rollback()
        assert _current(s, mandate.id).id == engine_id
        assert s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id
        ).count() == count_before


def test_bands_outside_house_matrix_warn_but_save(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        hm = s.query(HouseMatrix).filter(
            HouseMatrix.policy_id == engine_ta.policy_id,
            HouseMatrix.is_active == 1,
        ).all()
        assert hm
        # Obligationen-Untergrenze auf 0 -- liegt unter jedem Hausmatrix-
        # Minimum > 0, die Targets bleiben unveraendert (Risiko gleich).
        manual = allocation_router.create_target_allocation(
            mandate.id,
            _body_from(engine_ta, aid, band_bonds_min_bps=0),
            _request(), db=s, current_user=adv,
        )
        warnings = list(getattr(manual, "manual_override_warnings", []) or [])
        assert any("Obligationen" in w and "Hausmatrix" in w for w in warnings), warnings
        constraints = json.loads(manual.effective_constraints_json)
        persisted = constraints["manual_override"]["house_band_deviations"]
        assert any(row["bucket"] == "bonds" for row in persisted), persisted
        reasoning = json.loads(manual.optimizer_reasoning_json)
        assert any("Obligationen" in line for line in reasoning)
        _verify(manual)


# ---------------------------------------------------------------------------
# C) Begruendung Pflicht, Audit mit alt -> neu.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   ", "ok", "Kundenwunsch"])
def test_manual_save_requires_meaningful_reason(SF, reason):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        engine_id = engine_ta.id
        aid = _assessment(s, mandate.id).id
        with pytest.raises(HTTPException) as exc:
            allocation_router.create_target_allocation(
                mandate.id, _body_from(engine_ta, aid, reason=reason), _request(),
                db=s, current_user=adv,
            )
        assert exc.value.status_code == 422
        assert "Begründung" in str(exc.value.detail)
        s.rollback()
        assert _current(s, mandate.id).id == engine_id


def test_manual_save_audit_log_records_old_and_new_targets(SF):
    with SF() as s:
        mandate, adv = _seed(s)
        engine_ta = _current(s, mandate.id)
        aid = _assessment(s, mandate.id).id
        shifted = _shifted_targets(engine_ta)
        manual = allocation_router.create_target_allocation(
            mandate.id, _body_from(engine_ta, aid, **shifted), _request(),
            db=s, current_user=adv,
        )
        rows = s.query(AuditLog).filter(AuditLog.record_id == manual.id).all()
        by_field = {row.field_name: row for row in rows}
        assert "soll_allokation" in by_field, [(r.action, r.field_name) for r in rows]
        entry = by_field["soll_allokation"]
        old = json.loads(entry.old_value)
        new = json.loads(entry.new_value)
        assert old["allocation_id"] == engine_ta.id
        assert old["targets_bps"]["equities"] == int(engine_ta.target_equities_bps)
        assert new["targets_bps"]["equities"] == shifted["target_equities_bps"]
        assert new["reason"] == REASON
        assert new["risky_fraction_bps"] <= new["risk_budget_bps"]
