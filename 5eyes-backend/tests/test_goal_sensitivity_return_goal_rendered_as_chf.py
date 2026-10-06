"""GOAL-SENSITIVITY-PUBLICATION-001 (Kontrollrunde 36, Repro A, round 47).

Fund: `evaluate_goal_sensitivity()` fuellt das generische Feld
`target_amount_rappen_*` per "erster Wahrheitswert"-Fallback aus
amount/wealth-target/return-bps (services/portfolio_engine.py, Ende von
`evaluate_goal_sensitivity`). Fuer ein Renditeziel (goal_type='Renditeziel')
gibt es weder target_amount_rappen noch target_wealth_rappen -- der Fallback
greift also auf target_return_bps durch und schreibt dessen Rohwert (z.B. 600
fuer 6.00% p.a.) in `target_amount_rappen_new`.

Die Classic-UI-Sensitivity-Slider-Anzeige (runSensitivityCall() in
5eyes_v2.html) liest IMMER `target_amount_rappen_new`, teilt durch 100 und
prefixed hart "CHF" -- unabhaengig vom Goal-Typ. Fuer das 500bps->600bps-
Renditeziel-Delta (+20%) ergibt das die irrefuehrende Anzeige
"Neuer Zielwert: CHF 6" statt der fachlich korrekten "6.00% p.a.".

Teil (a): Backend-Unit-Test -- reproduziert exakt das Szenario aus
test_optimizer_phase6.py::test_sensitivity_return_goal_changes_return_target_and_solver_horizon
(500bps -> 600bps, +20%, selbe _seed_mandate/_capture_sensitivity_solver_calls-
Fixtures) und zeigt, dass `target_amount_rappen_new` NICHT None/absent ist
(wie es fuer ein reines Renditeziel fachlich korrekt waere), sondern den
durchgesickerten bps-Rohwert 600 enthaelt.

Teil (b): Frontend-Rendering-Test -- extrahiert die echte
`.then(function(body){...})`-Callback-Ausdruck aus `runSensitivityCall()`
(etabliertes Extraktionsmuster dieses Repos, siehe
test_frontend_review_cockpit.py / test_frontend_depletion_readiness_fail_closed.py),
fuehrt ihn aber -- anders als das sonst in diesem Repo uebliche rein
statische String-Pattern -- tatsaechlich mit Node aus (in CI/lokal verfuegbar,
da dies ein Electron-Frontend ist), gefuettert mit genau dem Response-Body aus
Teil (a), und zeigt, dass der gerenderte String "CHF 6" statt "6.00% p.a."
enthaelt.

Beide Teile sind bewusst xfail(strict=True): sie dokumentieren den Fund rot,
bis GOAL-SENSITIVITY-PUBLICATION-001 gefixt ist. Siehe
docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers

from database import Base
from main import app  # noqa: F401  (ensures model/router wiring is loaded)
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)

configure_mappers()

import services.portfolio_engine as pe
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import ensure_runtime_reference_data, evaluate_goal_sensitivity
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------------------------
# Teil (a): Backend -- selbes Szenario wie
# test_optimizer_phase6.py::test_sensitivity_return_goal_changes_return_target_and_solver_horizon
# ----------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_sens_return_chf.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_return_goal_mandate(session_factory) -> tuple[str, str, str]:
    """Mandant mit EINEM aktiven Renditeziel (500bps), analog _seed_mandate()
    in test_optimizer_phase6.py, aber auf das Return-Goal-Szenario verengt."""
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"user-sens-chf-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    goal_id = f"goal-sens-chf-return-{suffix}"
    now = _now()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-sens-chf-{suffix}", password_hash="h",
                   full_name="Adv SensChf", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="SensChf", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-sens-chf-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-sens-chf-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        # Reines Renditeziel: KEIN target_amount_rappen, KEIN target_wealth_rappen --
        # nur target_return_bps, exakt wie im existierenden
        # test_sensitivity_return_goal_changes_return_target_and_solver_horizon-Fixture.
        s.add(Goal(
            id=goal_id, mandate_id=mid, client_id=cid,
            goal_family="Rendite", goal_type="Renditeziel",
            label="Zielrendite", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_amount_rappen=None,
            target_wealth_rappen=None,
            target_return_bps=500,
            horizon_years=30,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
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
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, mid, goal_id


def _capture_sensitivity_solver_calls(monkeypatch) -> list[dict]:
    """Minimal-Variante des Solver-Stubs aus test_optimizer_phase6.py: ersetzt
    den teuren echten Solver durch einen deterministischen Fake-Result, ohne
    hier die volle Liability-Introspektion zu brauchen."""
    import services.optimizer.solver as optimizer_solver

    calls: list[dict] = []

    def fake_run_solver(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            objective_value=float(len(calls)),
            weights_bps={
                "liquidity": 2000,
                "bonds": 3000,
                "equities": 4000,
                "real_estate": 500,
                "alternatives": 500,
            },
            status="converged",
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)
    return calls


def _evaluate_500_to_600_bps_sensitivity(session_factory, monkeypatch) -> dict:
    """Ruft evaluate_goal_sensitivity() fuer das 500bps->600bps(+20%)-
    Renditeziel-Szenario auf -- selbe Werte wie
    test_sensitivity_return_goal_changes_return_target_and_solver_horizon
    in test_optimizer_phase6.py -- und gibt das rohe Response-Dict zurueck."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, mid, goal_id = _seed_return_goal_mandate(session_factory)
    _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=20,
        )
    return out


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-SENSITIVITY-PUBLICATION-001 -- round 47 red test (return-goal "
        "sensitivity rendered as CHF amount instead of percent), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-"
        "integrity-audit.md"
    ),
)
def test_return_goal_sensitivity_does_not_leak_bps_into_amount_field(
    session_factory, monkeypatch,
):
    """Fachlich korrekt waere target_amount_rappen_new == None/absent fuer ein
    reines Renditeziel (es hat gar keinen Betrags-Zielwert). Tatsaechlich
    liefert der "erster Wahrheitswert"-Fallback in evaluate_goal_sensitivity()
    hier den rohen bps-Wert 600 (aus target_return_bps_new) zurueck."""
    out = _evaluate_500_to_600_bps_sensitivity(session_factory, monkeypatch)

    # Die fachlich richtigen Renditefelder sind da und korrekt --
    # das ist NICHT der Bug (siehe test_optimizer_phase6.py).
    assert out["target_return_bps_baseline"] == 500
    assert out["target_return_bps_new"] == 600

    # Der Bug: das generische Betragsfeld sollte fuer ein Renditeziel
    # None/absent sein, ist aber mit dem bps-Rohwert kontaminiert.
    assert out["target_amount_rappen_new"] is None, (
        "target_amount_rappen_new sollte fuer ein reines Renditeziel "
        f"None sein, ist aber {out['target_amount_rappen_new']!r} -- der "
        "bps-Rohwert aus target_return_bps_new ist durchgesickert "
        "(GOAL-SENSITIVITY-PUBLICATION-001)."
    )


# ----------------------------------------------------------------------------
# Teil (b): Frontend -- echte Ausfuehrung der extrahierten Rendering-Callback
# ----------------------------------------------------------------------------

_NODE = shutil.which("node")


def _extract_sensitivity_callback_js() -> str:
    """Extrahiert den echten `.then(function(body){...})`-Callback-Koerper
    aus runSensitivityCall() in 5eyes_v2.html (etabliertes
    Regex-Extraktionsmuster dieses Repos fuer Monolith-Frontend-Tests, siehe
    test_frontend_review_cockpit.py / test_frontend_depletion_readiness_fail_closed.py)."""
    html = _html()
    match = re.search(
        r"API\.post\(url,\{goal_id:gid,target_delta_pct:delta\}\)\.then\(function\(body\)\{(.*?)\}\)\.catch\(function\(err\)\{",
        html,
        re.DOTALL,
    )
    assert match, (
        "runSensitivityCall()-Callback nicht gefunden -- wurde die Stelle "
        "umbenannt/verschoben?"
    )
    return match.group(1)


@pytest.mark.skipif(_NODE is None, reason="node nicht im PATH verfuegbar")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-SENSITIVITY-PUBLICATION-001 -- round 47 red test (return-goal "
        "sensitivity rendered as CHF amount instead of percent), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-"
        "integrity-audit.md"
    ),
)
def test_return_goal_sensitivity_rendering_shows_percent_not_chf(
    session_factory, monkeypatch,
):
    """Fuehrt die echte Classic-UI-Rendering-Callback (aus runSensitivityCall())
    mit Node aus, gefuettert mit genau dem Response-Body des 500bps->600bps-
    Renditeziel-Szenarios aus Teil (a). Fachlich korrekt waere eine Anzeige
    mit '%' (z.B. '6.00% p.a.'); tatsaechlich rendert der echte Code
    'Neuer Zielwert: CHF 6', weil er target_amount_rappen_new hart durch 100
    teilt und 'CHF' prefixed, ohne je den Goal-Typ zu pruefen."""
    body = _evaluate_500_to_600_bps_sensitivity(session_factory, monkeypatch)
    # Baseline-Reality-Check: der Bug aus Teil (a) muss in diesem Response-
    # Body tatsaechlich vorhanden sein, sonst waere dieser Test kein echter
    # Nachweis fuer die UI-Konsequenz des Bugs.
    assert body["target_amount_rappen_new"] == 600

    callback_js = _extract_sensitivity_callback_js()
    script = (
        "var resEl={textContent:null};\n"
        "var body=" + json.dumps(body) + ";\n"
        "(function(){\n"
        + callback_js
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(resEl.textContent));\n"
    )
    result = subprocess.run(
        [_NODE, "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Node-Ausfuehrung der extrahierten Callback fehlgeschlagen: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    rendered = json.loads(result.stdout)

    # Fachlich korrekt fuer ein Renditeziel: eine Prozent-Anzeige.
    assert "%" in rendered.split("|")[0], (
        f"Erwartete eine Prozent-Anzeige fuer das Renditeziel, aber die "
        f"echte Classic-UI-Rendering-Callback produzierte: {rendered!r} "
        "(hartcodiertes 'CHF'-Prefix, GOAL-SENSITIVITY-PUBLICATION-001)."
    )
    assert "CHF" not in rendered.split("|")[0]
