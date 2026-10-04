"""TA-LEGACY-FABRICATION-001 (round 46 red test).

Hintergrund (Sibling-Befund TA-EDITOR-WRITE-CONTRACT-001): der einzige
Modus, in dem POST /mandates/{id}/target-allocation (manuelles Speichern)
ueberhaupt akzeptiert wird, ist ``settings.optimizer_mode == "house_matrix"``
(siehe routers/allocation.py::create_target_allocation -- 409 in jedem
anderen Modus).

Dieser Test verifiziert live (TestClient, echte DB), dass genau dieser
akzeptierte Pfad eine frisch erzeugte TargetAllocation-Zeile anlegt, die
wie ein Alt-Datensatz aussieht, selbst wenn sie heute neu gespeichert wird:

  (a) ``context_artifacts_required`` bleibt 0 und die modernen
      Kontext-Artefakte (CMA-Referenz, allocation_context_hash,
      sub_allocations_json, effective_constraints_json,
      input_snapshot_hash) fehlen komplett -- obwohl eine vorherige,
      per /target-allocation/generate erzeugte Allocation fuer dasselbe
      Mandat diese Artefakte vollstaendig hatte
      (services/portfolio_engine.py::generate_target_allocation,
      TargetAllocation-Konstruktion ~Zeile 4295: context_artifacts_required=1
      + alle Artefakte gesetzt).

  (b) ``risky_fraction_bps`` wird NICHT fuer die NEUEN Ziel-Quoten neu
      berechnet, sondern 1:1 so persistiert, wie der Client es schickt --
      der Endpunkt hat keine eigene Recompute-Logik (routers/allocation.py::
      create_target_allocation baut die Zeile direkt aus
      ``body.model_dump()``, siehe TargetAllocationCreate.risky_fraction_bps
      in schemas/allocation.py, ein reiner Passthrough-Wert ohne
      serverseitige Neuberechnung). Simuliert wird das UI-Verhalten: der
      Berater oeffnet den Editor, der die zuletzt gespeicherte
      risky_fraction_bps vorbefuellt, aendert NUR die Ziel-Quoten (viel
      mehr Aktien) und speichert -- die alte, jetzt stale Kennzahl geht
      unveraendert in die DB.

  (c) Weil zusaetzlich ``risky_fraction_bps_at_generation`` /
      ``risk_budget_bps_at_generation`` auf der manuell gespeicherten Zeile
      NICHT gesetzt werden (kein Feld in TargetAllocationCreate), feuert
      services/mandate_lock_audit.py::audit_mandate_editability's
      Risk-Budget-Check (vergleicht genau diese beiden ``_at_generation``-
      Felder) niemals, selbst wenn die neuen Ziel-Quoten das Risikobudget
      des Mandats real verletzen.

Gewuenschtes (korrektes) Verhalten, das dieser Test einfordert:
  (a) die neue Zeile traegt vollstaendige Kontext-Artefakte,
  (b) risky_fraction_bps wird aus den NEUEN Ziel-Quoten frisch berechnet
      (nicht aus der alten Zeile kopiert),
  (c) das Mandate-Lock erkennt die resultierende Risikobudget-Verletzung.

Alle drei werden unten gegen die echte, heutige Implementierung geprueft
und sind xfail(strict=True) markiert, bis TA-LEGACY-FABRICATION-001 gefixt
ist.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from services.auth import get_current_user, require_advisor  # noqa: E402
from services.jurisdiction.resolve import resolve_mandate_jurisdiction  # noqa: E402
from services.mandate_lock_audit import (  # noqa: E402
    REASON_RISK_BUDGET_VIOLATED,
    audit_mandate_editability,
)
from services.portfolio_engine import ensure_runtime_reference_data  # noqa: E402
from services.portfolio_engine_house_matrix import (  # noqa: E402
    _building_block_rows_for_policy,
)
from services.risk_matrix import compute_portfolio_risky_fraction_bps  # noqa: E402
from tests.risk_fixture_helpers import (  # noqa: E402
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
    noop_lifespan,
)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ta_legacy_fabrication.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    now = _utc_now_iso()
    return User(
        id="user-tlf-1", username="advisor-tlf", password_hash="h",
        full_name="Advisor TLF", role="advisor", is_active=1,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    # Der manuelle POST-Pfad ist laut TA-EDITOR-WRITE-CONTRACT-001 nur im
    # house_matrix-Modus ueberhaupt erreichbar -- jeder andere Modus
    # antwortet 409. Siehe routers/allocation.py::create_target_allocation.
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")

    def override_db():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    app.dependency_overrides[require_advisor] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client_and_mandate(session_factory, advisor_id: str):
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number=f"C-TLF-{cid[:6]}",
            first_name="Test", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-TLF-{mid[:6]}",
            mandate_type="Vermoegensverwaltung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return cid, mid


def _add_assessment(session_factory, mandate_id: str, advisor_id: str) -> tuple[str, int]:
    """Strategie-fertiges Risikoprofil, final_score_x10=60 -> 'Ausgewogen'
    (identische Quellwerte wie test_audit_quick_fixes.py::_add_assessment,
    dort live gegen compute_scores() verifiziert)."""
    aid = str(uuid.uuid4())
    now = _utc_now_iso()
    risk_fields = derive_current_risk_fields(
        q_income_points=2,
        q_obligations_points=3,
        q_savings_points=2,
        q_wealth_points=2,
        investment_horizon_label="8 bis 11 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    assert risk_fields["final_score_x10"] == 60
    assert risk_fields["final_profile"] == "Ausgewogen"
    with session_factory() as s:
        s.add(RiskAssessment(
            id=aid, mandate_id=mandate_id, version=1, is_current=1,
            valid_from=now[:10],
            **risk_fields,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
    return aid, int(risk_fields["final_score_x10"])


def _add_advisory_position(session_factory, client_id: str, value_rappen: int):
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client_id,
            label="Test-Depot", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=value_rappen, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000, alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TA-LEGACY-FABRICATION-001 — round 46 red test, see audit "
        "2026-10-04-target-allocation-editor-context-and-release-lifecycle-"
        "integrity-audit.md (not committed in this repo)"
    ),
)
def test_manual_house_mode_save_fabricates_legacy_looking_allocation(
    auth_client, session_factory, advisor_user
):
    # --- Setup: Mandat mit Beratungsvermoegen + strategie-fertigem Risikoprofil.
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)
    _add_advisory_position(session_factory, cid, value_rappen=1_000_000_00)
    _add_assessment(session_factory, mid, advisor_user.id)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        policy, _cma = ensure_runtime_reference_data(s, advisor_user.id)
        policy_id = policy.id
        s.commit()

    # --- Schritt 1: ECHTE, moderne Allocation ueber den Engine-Generate-Pfad
    # erzeugen (house_matrix-Modus, Policy/CMA/Risk-Evidence vollstaendig).
    gen_resp = auth_client.post(f"/mandates/{mid}/target-allocation/generate", json={})
    assert gen_resp.status_code == 200, gen_resp.text
    generated_ta_id = gen_resp.json()["target_allocation"]["id"]

    with session_factory() as s:
        generated = s.query(TargetAllocation).filter(TargetAllocation.id == generated_ta_id).first()
        assert generated is not None
        # Sanity: der Generate-Pfad liefert tatsaechlich vollstaendige
        # moderne Artefakte -- sonst waere der Vergleich unten wertlos.
        assert generated.context_artifacts_required == 1
        assert generated.allocation_context_hash is not None
        assert generated.capital_market_assumptions_id is not None
        assert generated.risky_fraction_bps_at_generation is not None
        assert generated.risk_budget_bps_at_generation is not None
        risk_budget_bps_at_generation = int(generated.risk_budget_bps_at_generation)
        prior_risky_fraction_bps = int(generated.risky_fraction_bps)

        policy_row = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
        jurisdiction = resolve_mandate_jurisdiction(mandate)
        building_block_rows = _building_block_rows_for_policy(
            s, policy_row.id, getattr(mandate, "investment_universe", None), jurisdiction,
        )

    # --- Schritt 2: Berater aendert NUR die Ziel-Quoten (viel mehr Aktien,
    # kaum noch Obligationen/Immobilien/Alternative/Liquiditaet) und speichert
    # ueber den manuellen Editor-Endpunkt. Das UI haette vorher dieselbe
    # risky_fraction_bps wie die generierte Allocation angezeigt (stale
    # Vorbefuellung) -- genau dieser unveraenderte Wert wird mitgeschickt.
    new_targets_bps = {
        "equities": 9500,
        "bonds": 500,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }
    assert sum(new_targets_bps.values()) == 10000

    true_risky_fraction_bps_for_new_targets = compute_portfolio_risky_fraction_bps(
        new_targets_bps, building_block_rows,
    )
    # Eigener, frisch verifizierter Repro-Wert (keine Audit-Zahl kopiert):
    # mit den oben gesetzten Ziel-Quoten (95% Aktien) MUSS die wahre Risky-
    # Fraction klar ueber dem "Ausgewogen"-Risikobudget liegen, sonst waere
    # der Testfall kein echter Budget-Verstoss.
    assert true_risky_fraction_bps_for_new_targets > risk_budget_bps_at_generation, (
        f"Repro-Annahme verletzt: wahre Risky-Fraction fuer die neuen Ziel-"
        f"Quoten ({true_risky_fraction_bps_for_new_targets} bps) liegt nicht "
        f"ueber dem Risikobudget ({risk_budget_bps_at_generation} bps) -- "
        f"Testdaten muessten aggressiver gewaehlt werden."
    )
    assert true_risky_fraction_bps_for_new_targets != prior_risky_fraction_bps, (
        "Repro-Annahme verletzt: die wahre neue Risky-Fraction ist identisch "
        "mit dem alten (stale) Wert -- kann einen Stale-Copy-Bug nicht zeigen."
    )

    manual_payload = {
        "policy_id": policy_id,
        "target_equities_bps": new_targets_bps["equities"],
        "target_bonds_bps": new_targets_bps["bonds"],
        "target_real_estate_bps": new_targets_bps["real_estate"],
        "target_alternatives_bps": new_targets_bps["alternatives"],
        "target_liquidity_bps": new_targets_bps["liquidity"],
        "band_equities_min_bps": 0, "band_equities_max_bps": 10000,
        "band_bonds_min_bps": 0, "band_bonds_max_bps": 10000,
        "band_real_estate_min_bps": 0, "band_real_estate_max_bps": 10000,
        "band_alternatives_min_bps": 0, "band_alternatives_max_bps": 10000,
        "band_liquidity_min_bps": 0, "band_liquidity_max_bps": 10000,
        # UI-Vorbefuellung: unveraendert aus der zuvor generierten Allocation.
        "risky_fraction_bps": prior_risky_fraction_bps,
    }
    manual_resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=manual_payload)
    assert manual_resp.status_code == 201, manual_resp.text
    manual_ta_id = manual_resp.json()["id"]

    with session_factory() as s:
        manual_ta = s.query(TargetAllocation).filter(TargetAllocation.id == manual_ta_id).first()
        assert manual_ta is not None
        assert manual_ta.is_current == 1

        # (a) Vollstaendige Kontext-Artefakte gefordert (CMA-Referenz,
        # Risk-Evidence, Input-Hash) -- NICHT eine leere Legacy-Zeile.
        assert manual_ta.context_artifacts_required == 1, (
            "Manuell gespeicherte Allocation im house_matrix-Modus hat "
            "context_artifacts_required=0 -- sieht wie ein Alt-Datensatz "
            "aus, obwohl sie heute frisch erzeugt wurde (TA-LEGACY-"
            "FABRICATION-001a)."
        )
        assert manual_ta.allocation_context_hash is not None
        assert manual_ta.capital_market_assumptions_id is not None
        assert manual_ta.sub_allocations_json is not None
        assert manual_ta.input_snapshot_hash is not None

        # (b) risky_fraction_bps muss fuer die NEUEN Ziel-Quoten neu
        # berechnet sein, nicht 1:1 aus der vorherigen Allocation kopiert.
        assert manual_ta.risky_fraction_bps == true_risky_fraction_bps_for_new_targets, (
            f"risky_fraction_bps ({manual_ta.risky_fraction_bps} bps) wurde "
            f"nicht fuer die neuen Ziel-Quoten neu berechnet -- erwartet "
            f"{true_risky_fraction_bps_for_new_targets} bps. Stattdessen "
            f"wurde der alte Wert ({prior_risky_fraction_bps} bps) 1:1 "
            f"uebernommen (TA-LEGACY-FABRICATION-001b)."
        )

        # (c) Mandate-Lock muss die resultierende Risikobudget-Verletzung
        # erkennen (die neuen Ziel-Quoten liegen klar ueber dem Budget).
        audit = audit_mandate_editability(s, mandate)
        assert REASON_RISK_BUDGET_VIOLATED in audit["lock_reasons"], (
            f"Mandate-Lock erkennt die Risikobudget-Verletzung nicht "
            f"(lock_reasons={audit['lock_reasons']!r}) -- die neuen Ziel-"
            f"Quoten verletzen das Budget real "
            f"({true_risky_fraction_bps_for_new_targets} bps > "
            f"{risk_budget_bps_at_generation} bps), aber "
            f"risky_fraction_bps_at_generation/risk_budget_bps_at_generation "
            f"wurden vom manuellen Save-Pfad nie gesetzt "
            f"(TA-LEGACY-FABRICATION-001c)."
        )
